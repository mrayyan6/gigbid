"""Shared in-process helpers for the LLM runners: GigSim over ASGI, graph run to the approval
interrupt, strict claim audit, stats helpers. Nothing here talks to the network except Ollama."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent import llm
from agent.graphs.bid_graph import build_bid_graph
from agent.nodes import core
from evals.runners.judge_calibration import PROMPT as JUDGE_PROMPT

load_dotenv()  # GROQ_API_KEY etc for the hosted profile; never printed
from gigsim import generate
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
DATASETS = ROOT / "evals" / "datasets"
CFG = yaml.safe_load((ROOT / "evals" / "config.yaml").read_text(encoding="utf-8"))


def hkey(s: str, seed: int = 7) -> str:
    return hashlib.sha256(f"{seed}:{s}".encode()).hexdigest()


def dev_jobs() -> list[dict]:
    return json.loads((DATASETS / "dev_jobs.json").read_text(encoding="utf-8"))


def pctl(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[int(q * (len(s) - 1))]


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


class Env:
    """GigSim in process plus the marketplace adapter. Daily cap and connects are lifted for evals."""

    def __init__(self) -> None:
        generate.build()
        import gigsim.app as gs
        from gigsim.app import app, store
        gs.RATE_OVERRIDE = 10**6
        store.reset()
        store.connects["user"] = 10**7
        self.store = store
        self.mp = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app))
        self.graph = build_bid_graph(MemorySaver())

    def add_jobs(self, jobs: list[dict]) -> None:
        for j in jobs:
            self.store.jobs[j["job_id"]] = j

    def lift_daily_cap(self) -> None:
        for p in self.store.proposals.values():
            p["created_at"] = 0.0
        self.store.connects["user"] = 10**7

    async def run_to_interrupt(self, job_id: str, tid: str, retriever, extra: dict | None = None) -> dict:
        cfg = {"configurable": {"thread_id": tid, "marketplace": self.mp, "retriever": retriever,
                                **(extra or {})}}
        t0 = time.perf_counter()
        await self.graph.ainvoke({"job_id": job_id}, cfg)
        wall = time.perf_counter() - t0
        snap = await self.graph.aget_state(cfg)
        return {"values": snap.values, "interrupted": bool(snap.next), "wall_s": wall, "cfg": cfg}

    async def approve(self, run: dict) -> dict:
        self.lift_daily_cap()
        out = await self.graph.ainvoke(Command(resume={"action": "approve"}), run["cfg"])
        return out.get("outcome") or {}


async def decision_pool(env: Env, jobs: list[dict], retriever_for, per_persona: int | None = None) -> list[dict]:
    """Jobs the graph itself decides to bid on (template mode, no LLM), not scam or injected by gold."""
    prev = os.environ.get("LLM_ENABLED")
    os.environ["LLM_ENABLED"] = "0"
    out = []
    try:
        for j in jobs:
            if j["gold"]["scam"] or j["gold"]["injected"]:
                continue
            if per_persona and sum(o["gold"]["persona"] == j["gold"]["persona"] for o in out) >= per_persona:
                continue
            cfg = {"configurable": {"thread_id": f"pool-{j['job_id']}", "marketplace": env.mp,
                                    "retriever": retriever_for(j["gold"]["persona"])}}
            r = await env.graph.ainvoke({"job_id": j["job_id"]}, cfg)
            if (r.get("decision") or {}).get("action") == "bid":
                out.append(j)
    finally:
        if prev is None:
            os.environ.pop("LLM_ENABLED", None)
        else:
            os.environ["LLM_ENABLED"] = prev
    return out


# ---------------------------------------------------------------- claim audit
def audit_unsupported(sentences: list[str], evidence: list[dict], job: dict, price: float) -> int:
    """Strict claim audit, independent of the verifier rule. A sentence is unsupported when it makes a
    claim about past work without a valid [ev:id] tag, or cites evidence but states a number that is in
    neither the cited evidence nor the job context (price, timeline, budget)."""
    num = re.compile(CFG["audit"]["number_regex"])
    past = re.compile(core.CFG["verifier"]["past_claim_regex"], re.IGNORECASE)
    ev = {e["evidence_id"]: e for e in evidence}
    ctx = " ".join(map(str, [price, job.get("duration_days"), job["budget"]["min"], job["budget"]["max"],
                             len(job.get("required_skills", []))]))
    bad = 0
    for s in sentences:
        tags = re.findall(r"\[ev:([^\]]+)\]", s)
        body = re.sub(r"\[ev:[^\]]*\]", "", s)
        nums = [n.strip(".,") for n in num.findall(body)]
        if tags and not all(t in ev for t in tags):
            bad += 1
        elif tags:
            src = " ".join(f"{ev[t]['title']} {ev[t]['outcome']} {' '.join(ev[t]['skills'])}" for t in tags)
            if any(n not in src and n not in ctx for n in nums):
                bad += 1
        elif past.search(body) or any("%" in n for n in nums):
            bad += 1
    return bad


def verifier_rule_unsupported(sentences: list[str], evidence: list[dict]) -> int:
    """The Verifier node rule applied to any list of sentences: past-work sentence without a valid tag."""
    past = re.compile(core.CFG["verifier"]["past_claim_regex"], re.IGNORECASE)
    ev = {e["evidence_id"] for e in evidence}
    n = 0
    for s in sentences:
        tags = re.findall(r"\[ev:([^\]]+)\]", s)
        if tags and all(t in ev for t in tags):
            continue
        n += bool(past.search(s) or tags)
    return n


def judge_draft(job_text: str, draft: str) -> dict:
    """Judge rubric score for one draft with agent/prompts/judge.md. Returns overall and token use."""
    user = f"<job_post>\n{job_text}\n</job_post>\n<draft>\n{draft}\n</draft>"
    res = llm.complete("judge", JUDGE_PROMPT.read_text(encoding="utf-8"), user, json_mode=True, max_tokens=200)
    obj = llm.parse_json(res.text) or {}
    try:
        score = max(1, min(5, int(round(float(obj["overall"])))))
    except (TypeError, KeyError, ValueError):
        score = None
    return {"overall": score, "tokens": res.tokens, "cost_usd": res.cost_usd, "error": res.error}


def llm_used(values: dict) -> bool:
    """True when the writer's text came from the model, not the template fallback."""
    for t in values.get("trace", []):
        if t.get("node") == "writer" and "llm" in t:
            return t["llm"].get("error") is None
    return False


def draft_sentences_before(values: dict) -> list[str]:
    return [r["claim"] for r in values.get("claim_verification", [])]


def draft_sentences_after(values: dict) -> list[str]:
    return core._sentences(values["proposal_draft"]["cover_letter"])
