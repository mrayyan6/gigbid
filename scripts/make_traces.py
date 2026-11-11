"""Produce the four public LangSmith traces required by the brief and write their share links.

Scenarios (hosted open profile, LLM on, tracing on):
  scam    a planted scam job is skipped, nothing is sent
  approve a bid job runs to the approval interrupt, is approved and submitted
  critic  a bid job where the Critic sends the draft back (look for the writer to critic loop)
  crash   process 1 runs to the approval interrupt and exits, process 2 (a new Python process, same SQLite
          checkpoint file) resumes with approve, and the proposal exists exactly once

Writes evals/results/traces.json (links, run ids, outcomes). Run: python scripts/make_traces.py
Internal: python scripts/make_traces.py crash_pending|crash_resume <job_id> <db_path>
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GIGBID_PROFILE", "open_hosted")
os.environ["LLM_ENABLED"] = "1"
os.environ["LANGSMITH_TRACING"] = "true"
os.environ.setdefault("LANGSMITH_PROJECT", "gigbid")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ["LANGSMITH_TRACING"] = "true"

from langchain_core.tracers.context import collect_runs
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from agent.observability import setup_tracing
from evals.runners._harness import Env, dev_jobs
from rag.retriever import get_retriever

OUT = ROOT / "evals" / "results" / "traces.json"


def cfg(env: Env, job: dict, tid: str, tag: str) -> dict:
    return {"configurable": {"thread_id": tid, "marketplace": env.mp,
                             "retriever": get_retriever("v2_hybrid", job["gold"]["persona"])},
            "tags": ["gigbid-trace", tag], "metadata": {"scenario": tag, "job_id": job["job_id"]},
            "run_name": f"gigbid {tag} {job['job_id']}"}


def pick(kind: str) -> dict:
    return next(j for j in sorted(dev_jobs(), key=lambda j: j["job_id"]) if j["gold"]["kind"] == kind)


async def run_graph(graph, payload, config) -> tuple[dict, str | None]:
    with collect_runs() as cb:
        out = await graph.ainvoke(payload, config)
    root = str(cb.traced_runs[0].id) if cb.traced_runs else None
    return out, root


async def simple(tag: str, job: dict, approve: bool) -> dict:
    env = Env()
    g = env.graph
    c = cfg(env, job, f"trace-{tag}-{job['job_id']}", tag)
    out, rid = await run_graph(g, {"job_id": job["job_id"]}, c)
    res = {"scenario": tag, "job_id": job["job_id"], "run_id": rid,
           "decision": out["decision"]["action"], "revisions": out.get("revisions"), "interrupted": "__interrupt__" in out}
    if approve and "__interrupt__" in out:
        done, rid2 = await run_graph(g, Command(resume={"action": "approve"}), c)
        res["resume_run_id"] = rid2
        res["status"] = (done.get("outcome") or {}).get("status")
    res["proposals_in_marketplace"] = len(await env.mp._req("GET", "/proposals"))
    return res


async def crash_pending(job_id: str, db: str) -> None:
    job = next(j for j in dev_jobs() if j["job_id"] == job_id)
    env = Env()
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        g = build_bid_graph(saver)
        c = cfg(env, job, f"trace-crash-{job_id}", "crash_before")
        out, rid = await run_graph(g, {"job_id": job_id}, c)
        print(json.dumps({"run_id": rid, "interrupted": "__interrupt__" in out,
                          "proposals": len(await env.mp._req("GET", "/proposals"))}))


async def crash_resume(job_id: str, db: str) -> None:
    job = next(j for j in dev_jobs() if j["job_id"] == job_id)
    env = Env()
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        g = build_bid_graph(saver)
        c = cfg(env, job, f"trace-crash-{job_id}", "crash_after_restart")
        snap = await g.aget_state(c)
        pending = bool(snap.next)
        done, rid = await run_graph(g, Command(resume={"action": "approve"}), c)
        await g.ainvoke(Command(resume={"action": "approve"}), c)  # a second resume must not send again
        print(json.dumps({"run_id": rid, "pending_after_restart": pending,
                          "status": (done.get("outcome") or {}).get("status"),
                          "proposals": len(await env.mp._req("GET", "/proposals"))}))


def sub(*args: str) -> dict:
    r = subprocess.run([sys.executable, __file__, *args], capture_output=True, text=True, cwd=ROOT, timeout=900)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not line:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(line[-1])


def share(run_ids: list[str]) -> dict:
    from langsmith import Client
    client = Client()
    client.flush() if hasattr(client, "flush") else None
    import time
    time.sleep(8)
    return {rid: client.share_run(rid) for rid in run_ids if rid}


async def main() -> None:
    setup_tracing()
    results = []
    results.append(await simple("scam", pick("scam"), approve=False))
    bid = next(j for j in sorted(dev_jobs(), key=lambda j: j["job_id"]) if j["gold"]["kind"] == "good")
    results.append(await simple("approve", bid, approve=True))
    good2 = [j for j in sorted(dev_jobs(), key=lambda j: j["job_id"]) if j["gold"]["kind"] == "good"][1]
    results.append(await simple("critic", good2, approve=False))
    crash_job = [j for j in sorted(dev_jobs(), key=lambda j: j["job_id"]) if j["gold"]["kind"] == "good"][2]["job_id"]
    db = str(ROOT / "data" / "processed" / "trace_crash.sqlite")
    Path(db).unlink(missing_ok=True)
    before = sub("crash_pending", crash_job, db)
    after = sub("crash_resume", crash_job, db)
    results.append({"scenario": "crash", "job_id": crash_job, "before": before, "after": after,
                    "run_id": before["run_id"], "resume_run_id": after["run_id"]})
    ids = [x for r in results for x in (r.get("run_id"), r.get("resume_run_id")) if x]
    links = share(ids)
    for r in results:
        r["public_url"] = links.get(r.get("run_id"))
        if r.get("resume_run_id"):
            r["resume_public_url"] = links.get(r["resume_run_id"])
    OUT.write_text(json.dumps({"project": os.environ.get("LANGSMITH_PROJECT"), "profile": os.environ["GIGBID_PROFILE"],
                               "traces": results}, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "crash_pending":
        asyncio.run(crash_pending(sys.argv[2], sys.argv[3]))
    elif len(sys.argv) > 1 and sys.argv[1] == "crash_resume":
        asyncio.run(crash_resume(sys.argv[2], sys.argv[3]))
    else:
        asyncio.run(main())
