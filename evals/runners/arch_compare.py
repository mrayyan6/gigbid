"""R&D question C: three agent architectures on the same dev jobs, the same model (qwen2.5:7b-instruct).

  react       langgraph.prebuilt.create_react_agent with all tools
  supervisor  langgraph_supervisor.create_supervisor with three workers
  graph       our hand built bid graph run in LLM mode (agent/graphs/bid_graph.py)

Protocol (one pipeline for every metric):
- Each architecture returns (action, bid_amount, cover_letter) for a job. The harness submits bids to
  in-process GigSim (httpx ASGITransport) and, for the graph, the graph submits after the harness approves its
  interrupt. Before every submit the GigSim store counters are cleared so the proposal id is always the same
  and the realized reply draw depends only on the job, not on how many bids came earlier.
- Unsupported claims and compliance violations are counted by the same deterministic checks for all three
  architectures on the final letter (the verifier's past-claim regex without a valid [ev:id] tag, and
  core.violations with the platform policy). For the graph the verifier's pre-removal count is also reported.
- GigSim reply rate: realized (hash draw) and expected (mean reply probability from the simulator formula).
  Expected reply probability is far less noisy at small n.
- Jobs are stratified by kind and visited in round robin order, all three architectures per job, so stopping
  early leaves an equal n for each. n comes from config evals.arch_n (default 50) or --n, and the run stops
  starting new jobs after --budget-min minutes. The n actually completed is written into the results meta.
Run: python -m evals.runners.arch_compare [--n 50] [--budget-min 22] -> evals/results/arch_compare.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import time
from pathlib import Path

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent import llm
from agent.graphs.bid_graph import build_bid_graph
from agent.nodes import core
from agent.nodes.config import CFG, load_prompt
from gigsim import generate
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag.index.corpus import get_corpus
from rag.retriever import get_retriever

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "arch_compare.json"
MODEL = "qwen2.5:7b-instruct"
NUM_CTX = 8192
OLLAMA = CFG["llm"]["ollama_url"].rstrip("/")
ARCHS = ("react", "supervisor", "graph")
JOB_TIMEOUT_S = {"react": 200, "supervisor": 300, "graph": 240}
RECURSION_LIMIT = 25
KINDS = ["good", "lowball", "stretch", "offtopic", "inject", "scam"]

# ---------------------------------------------------------------- native Ollama client for llm.complete
STATS: list[dict] = []  # one record per llm.complete HTTP call, from Ollama's own counters


def _native_call(model: str, system: str, user: str, json_mode: bool, max_tokens: int) -> llm.LLMResult:
    """Replacement for agent.llm._call that uses Ollama /api/chat so eval_count and eval_duration are
    available. Same contract as the original: never raises, returns text=None on error."""
    _, name = llm._split(model)
    body = {"model": name, "stream": False, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": CFG["llm"]["temperature"], "num_predict": max_tokens,
                        "num_ctx": NUM_CTX}}
    if json_mode:
        body["format"] = "json"
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=CFG["llm"]["timeout_s"] * 2) as c:
            r = c.post(OLLAMA + "/api/chat", json=body)
        r.raise_for_status()
        d = r.json()
        text = (d["message"]["content"] or "").strip()
    except Exception as e:
        STATS.append({"model": name, "error": f"{type(e).__name__}: {e}"})
        return llm.LLMResult(None, model, latency_ms=int((time.perf_counter() - t0) * 1000),
                             error=f"{type(e).__name__}: {e}")
    ms = int((time.perf_counter() - t0) * 1000)
    tin, tout, ev = d.get("prompt_eval_count", 0), d.get("eval_count", 0), d.get("eval_duration", 0)
    STATS.append({"model": name, "prompt_eval_count": tin, "eval_count": tout, "eval_duration_ns": ev,
                  "prompt_eval_duration_ns": d.get("prompt_eval_duration", 0),
                  "load_duration_ns": d.get("load_duration", 0), "total_duration_ns": d.get("total_duration", 0),
                  "empty": not text})
    return llm.LLMResult(text or None, model, tin, tout, ms, round(tout / (ev / 1e9), 1) if ev else 0.0, 0.0,
                         error=None if text else "empty completion")


def install_native_llm() -> None:
    llm._call = _native_call


def set_profile(name: str, default: str, fallback: str, nodes: dict[str, str] | None = None) -> None:
    """Runtime routing profile (no config file edit). Selected through GIGBID_PROFILE."""
    CFG["routing"][name] = {"default": default, "fallback": fallback, "nodes": nodes or {}}
    os.environ["GIGBID_PROFILE"] = name
    os.environ["LLM_ENABLED"] = "1"


# ---------------------------------------------------------------- GigSim in process
class Sim:
    def __init__(self):
        generate.build()
        import gigsim.app as gs
        self.gs = gs
        gs.RATE_OVERRIDE = 10**6  # in-process eval, no real traffic
        gs.store.reset()
        self.mp = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=gs.app))

    def clear(self) -> None:
        s = self.gs.store
        s.proposals.clear()
        s.idem.clear()
        s.connects.clear()
        s.messages.clear()

    def expected_prob(self, job_id: str, letter: str, amount: float) -> float:
        job = self.gs.store.jobs[job_id]
        client = self.gs.store.clients[job["client_id"]]
        return self.gs._reply_probability(job, client, {"cover_letter": letter, "bid_amount": amount})


# ---------------------------------------------------------------- shared checks
def unsupported_count(letter: str, valid_ids: set[str]) -> int:
    """Claims about past work with no [ev:id] tag, or a tag that is not a real portfolio item."""
    past = re.compile(CFG["verifier"]["past_claim_regex"], re.IGNORECASE)
    n = 0
    for s in core._sentences(letter):
        tags = re.findall(r"\[ev:([^\]]+)\]", s)
        if tags and all(t in valid_ids for t in tags):
            continue
        if tags or past.search(s):
            n += 1
    return n


class TokenCounter(BaseCallbackHandler):
    """Sums model usage over every LLM call in the run, including worker and supervisor turns."""

    def __init__(self):
        self.tin = self.tout = self.calls = 0

    def on_llm_end(self, response, **kw):
        self.calls += 1
        for gens in response.generations:
            for g in gens:
                um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                self.tin += um.get("input_tokens", 0)
                self.tout += um.get("output_tokens", 0)


# ---------------------------------------------------------------- tools for react and supervisor
async def build_tools(sim: Sim, retr, counters: dict) -> dict[str, StructuredTool]:
    from mcp_servers.marketplace.server import mcp
    server_tools = {t.name: t for t in await mcp.list_tools()}
    mp = sim.mp
    policy = await mp.get_policy()

    def compact(x, limit=900):
        s = json.dumps(x, ensure_ascii=False)
        return s if len(s) <= limit * 3 else s[: limit * 3] + "..."

    def count(name):
        counters["tool_calls"] += 1
        counters["by_tool"][name] = counters["by_tool"].get(name, 0) + 1

    def mk(name, fn):
        t = server_tools[name]

        async def run(**kw):
            count(name)
            try:
                return await fn(**kw)
            except Exception as e:
                return f"tool error: {type(e).__name__}: {e}"
        return StructuredTool(name=name, description=t.description or name, args_schema=t.inputSchema,
                              coroutine=run)

    async def search_jobs(query: str = "", limit: int = 5, persona: str | None = None):
        jobs = await mp.search_jobs(query, min(int(limit), 5), persona)
        return compact([{k: j[k] for k in ("job_id", "title", "budget", "required_skills")} for j in jobs])

    async def get_job(job_id: str):
        return compact(await mp.get_job(job_id))

    async def get_client_history(client_id: str):
        return compact(await mp.get_client_history(client_id))

    async def get_connects_balance():
        return compact(await mp.get_connects_balance())

    async def list_messages(client_id: str | None = None):
        return compact((await mp.list_messages(client_id))[:5])

    async def get_policy():
        return compact(policy)

    async def create_proposal_draft(job_id: str, cover_letter: str, bid_amount: float, idempotency_key: str,
                                    dry_run: bool = False, screening_answers: list[str] | None = None):
        counters["write_calls"] += 1  # writes are forced to dry_run: the harness submits after approval
        return compact(await mp.create_proposal({"job_id": job_id, "cover_letter": cover_letter,
                                                 "bid_amount": bid_amount}, idempotency_key, dry_run=True))

    async def submit_proposal(job_id: str, cover_letter: str, bid_amount: float, idempotency_key: str,
                              dry_run: bool = False, screening_answers: list[str] | None = None):
        counters["write_calls"] += 1
        return compact(await mp.create_proposal({"job_id": job_id, "cover_letter": cover_letter,
                                                 "bid_amount": bid_amount}, idempotency_key, dry_run=True))

    async def send_message(client_id: str, text: str, idempotency_key: str, dry_run: bool = False):
        counters["write_calls"] += 1
        return compact({"dry_run": True, "would_send": {"client_id": client_id, "text": text}})

    tools = {n: mk(n, f) for n, f in [
        ("search_jobs", search_jobs), ("get_job", get_job), ("get_client_history", get_client_history),
        ("get_connects_balance", get_connects_balance), ("list_messages", list_messages),
        ("get_policy", get_policy), ("create_proposal_draft", create_proposal_draft),
        ("submit_proposal", submit_proposal), ("send_message", send_message)]}

    async def search_evidence(requirement: str, k: int = 3):
        count("search_evidence")
        hits = retr.search(requirement, k=min(int(k), 5))
        return compact([{x_: x[x_] for x_ in ("evidence_id", "title", "skills", "outcome")} for x in hits])

    async def check_compliance(text: str):
        count("check_compliance")
        bad = core.violations(text, policy, check_length=True)
        return compact({"allowed": not bad, "violations": bad})

    tools["search_evidence"] = StructuredTool(
        name="search_evidence",
        description="Search the freelancer's portfolio evidence (case studies, reviews, past proposals) for one "
                    "requirement or skill. Returns evidence ids, titles, skills and outcomes.",
        args_schema={"type": "object", "properties": {
            "requirement": {"type": "string", "description": "A requirement or skill, for example FastAPI"},
            "k": {"type": "integer", "description": "How many items to return, default 3"}},
            "required": ["requirement"]}, coroutine=search_evidence)
    tools["check_compliance"] = StructuredTool(
        name="check_compliance",
        description="Check a draft cover letter against platform and compliance rules. Returns allowed and the "
                    "list of violations.",
        args_schema={"type": "object", "properties": {
            "text": {"type": "string", "description": "The full cover letter text"}}, "required": ["text"]},
        coroutine=check_compliance)
    return tools


def prompts() -> dict[str, str]:
    text = load_prompt("arch_compare")
    secs = {n.strip(): b.strip() for n, b in re.findall(r"(?ms)^## (\w+)\n(.*?)(?=^## |\Z)", text)}
    fill = {**CFG["decision"], "target_position": CFG["pricing"]["target_position"],
            "max_words": CFG["compliance"]["max_words"], "max_evidence": CFG["writer"]["max_evidence"]}
    rules = secs["decision_rules"].format(**fill)
    final = secs["final_format"].format(**fill)
    writer = load_prompt("writer")
    return {
        "react": f"{secs['react_system']}\n\n{rules}\n\n{writer}\n\n{final}",
        "supervisor": f"{secs['supervisor_system']}\n\n{rules}\n\n{final}",
        "job_analyst": secs["worker_job_analyst"], "evidence_finder": secs["worker_evidence_finder"],
        "proposal_writer": f"{secs['worker_proposal_writer']}\n\n{writer}",
    }


def chat_model():
    from langchain_ollama import ChatOllama
    return ChatOllama(model=MODEL, base_url=OLLAMA, temperature=CFG["llm"]["temperature"], num_ctx=NUM_CTX,
                      num_predict=700, keep_alive="30m", client_kwargs={"timeout": 120})


def build_react(tools: dict, ps: dict):
    from langgraph.prebuilt import create_react_agent
    return create_react_agent(chat_model(), list(tools.values()), prompt=ps["react"])


def build_supervisor(tools: dict, ps: dict):
    from langgraph.prebuilt import create_react_agent
    from langgraph_supervisor import create_supervisor
    m = chat_model()
    reads = [tools[n] for n in ("search_jobs", "get_job", "get_client_history", "get_connects_balance",
                                "list_messages", "get_policy")]
    writes = [tools[n] for n in ("check_compliance", "create_proposal_draft", "submit_proposal", "send_message")]
    workers = [
        create_react_agent(m, reads, name="job_analyst", prompt=ps["job_analyst"]),
        create_react_agent(m, [tools["search_evidence"]], name="evidence_finder", prompt=ps["evidence_finder"]),
        create_react_agent(m, writes, name="proposal_writer", prompt=ps["proposal_writer"]),
    ]
    return create_supervisor(workers, model=m, prompt=ps["supervisor"]).compile()


def parse_decision(messages) -> dict | None:
    """Last message that holds a JSON object with an action."""
    for m in reversed(messages):
        c = getattr(m, "content", "")
        if isinstance(c, list):
            c = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in c)
        obj = llm.parse_json(c) if isinstance(c, str) else None
        if obj and str(obj.get("action", "")).lower() in ("bid", "watch", "skip"):
            return obj
    return None


# ---------------------------------------------------------------- one job, one architecture
async def run_agent(arch: str, agent, sim: Sim, job: dict, retr, counters: dict) -> dict:
    cb = TokenCounter()
    res = await agent.ainvoke(
        {"messages": [{"role": "user", "content": f"Job id: {job['job_id']}"}]},
        {"callbacks": [cb], "recursion_limit": RECURSION_LIMIT})
    obj = parse_decision(res["messages"])
    out = {"tokens": cb.tin + cb.tout, "tokens_in": cb.tin, "tokens_out": cb.tout, "llm_calls": cb.calls}
    if obj is None:
        return {**out, "parse_ok": False}
    action = str(obj["action"]).lower()
    letter = obj.get("cover_letter") if isinstance(obj.get("cover_letter"), str) else ""
    amount = obj.get("bid_amount")
    return {**out, "parse_ok": True, "action": action, "letter": letter or "",
            "amount": float(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else None}


async def run_graph(g, sim: Sim, job: dict, retr, tag: str) -> dict:
    sim.clear()
    cfg = {"configurable": {"thread_id": f"{tag}-{job['job_id']}", "marketplace": sim.mp, "retriever": retr},
           "recursion_limit": 60}
    st = await g.ainvoke({"job_id": job["job_id"]}, cfg)
    if st.get("__interrupt__"):
        st = await g.ainvoke(Command(resume={"action": "approve"}), cfg)
    ver = st.get("claim_verification") or []
    llm_errors = sum(1 for t in st.get("trace", []) if (t.get("llm") or {}).get("error"))
    draft = st.get("proposal_draft") or {}
    return {"parse_ok": True, "action": st["decision"]["action"], "letter": draft.get("cover_letter", ""),
            "amount": (st.get("price_quote") or {}).get("amount"), "tokens": st.get("tokens", 0),
            "status": st.get("status"), "unsupported_pre_verifier": sum(r["status"] == "unsupported" for r in ver),
            "critic_revisions": st.get("revisions", 0), "llm_errors": llm_errors,
            "blocked": st.get("status") == "blocked",
            "blocked_violations": (st.get("compliance_verdict") or {}).get("violations", []),
            "outcome": st.get("outcome"), "n_steps": st.get("steps", 0)}


async def evaluate_job(arch, runner, sim: Sim, job: dict, retr, valid_ids: set[str], tag: str) -> dict:
    gold = job["gold"]
    row = {"job_id": job["job_id"], "kind": gold["kind"], "persona": gold["persona"], "arch": arch,
           "gold_action": gold["action"], "gold_scam": gold["scam"], "gold_injected": gold["injected"],
           "error": None}
    counters = {"tool_calls": 0, "write_calls": 0, "by_tool": {}}
    t0 = time.perf_counter()
    try:
        if arch == "graph":
            r = await asyncio.wait_for(run_graph(runner, sim, job, retr, tag), JOB_TIMEOUT_S[arch])
        else:
            tools = await build_tools(sim, retr, counters)
            agent = runner(tools)
            r = await asyncio.wait_for(run_agent(arch, agent, sim, job, retr, counters), JOB_TIMEOUT_S[arch])
    except Exception as e:
        r = {"parse_ok": False, "tokens": 0}
        row["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    row["latency_s"] = round(time.perf_counter() - t0, 1)
    row.update(r)
    row["tool_calls"], row["write_tool_calls"] = counters["tool_calls"], counters["write_calls"]
    pred = row.get("action")
    letter = row.get("letter") or ""
    row["pred_action"] = pred
    # unified checks on the final letter
    if pred == "bid" and letter:
        row["unsupported_final"] = unsupported_count(letter, valid_ids)
        pol = await sim.mp.get_policy()
        row["violations_final"] = core.violations(letter, pol, check_length=True)
    # GigSim outcome
    row["submitted"] = row["replied"] = False
    row["expected_reply_prob"] = 0.0
    if pred == "bid" and letter:
        amt = row.get("amount")
        if arch == "graph":
            oc = row.get("outcome")
            if oc and oc.get("status") in ("replied", "submitted"):
                row["submitted"], row["replied"] = True, oc["status"] == "replied"
                row["expected_reply_prob"] = sim.expected_prob(job["job_id"], letter, amt)
        else:
            if amt is None:
                b = job["budget"]
                amt = round(b["min"] + (b["max"] - b["min"]) * CFG["pricing"]["target_position"])
                row["amount_fallback"] = True
            sim.clear()
            try:
                rec = await sim.mp.create_proposal({"job_id": job["job_id"], "cover_letter": letter,
                                                    "bid_amount": amt}, f"{tag}-{job['job_id']}")
                row["submitted"], row["replied"] = True, rec["status"] == "replied"
                row["expected_reply_prob"] = sim.expected_prob(job["job_id"], letter, amt)
            except Exception as e:
                row["submit_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return row


# ---------------------------------------------------------------- aggregation
def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, math.ceil(q * len(xs)) - 1)
    return xs[i]


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    pb = [r.get("pred_action") == "bid" for r in rows]
    gb = [r["gold_action"] == "bid" for r in rows]
    tp = sum(p and g for p, g in zip(pb, gb))
    fp = sum(p and not g for p, g in zip(pb, gb))
    fn = sum((not p) and g for p, g in zip(pb, gb))
    prec, rec = (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)
    bids = [r for r in rows if r.get("pred_action") == "bid" and r.get("letter")]
    subs = [r for r in rows if r["submitted"]]
    lat = [r["latency_s"] for r in rows]
    unsup = [r.get("unsupported_final", 0) for r in bids]
    viol_final = [r for r in bids if r.get("violations_final")]
    shipped_viol = [r for r in subs if r.get("violations_final")]
    blocked = [r for r in rows if r.get("blocked")]
    return {
        "n": n, "errors": sum(bool(r["error"]) for r in rows), "parse_failures": sum(not r["parse_ok"] for r in rows),
        "bid_or_skip_accuracy": round(sum(p == g for p, g in zip(pb, gb)) / n, 3),
        "accuracy_3way": round(sum(r.get("pred_action") == r["gold_action"] for r in rows) / n, 3),
        "bid_precision": round(prec, 3), "bid_recall": round(rec, 3),
        "bid_f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
        "bids": len(pb) and sum(pb), "scam_jobs_bid_on": sum(p and r["gold_scam"] for p, r in zip(pb, rows)),
        "injected_jobs_bid_on": sum(p and r["gold_injected"] for p, r in zip(pb, rows)),
        "letters": len(bids), "unsupported_claims_final_total": sum(unsup),
        "unsupported_claims_final_per_letter": round(sum(unsup) / len(bids), 3) if bids else None,
        "letters_with_unsupported": sum(u > 0 for u in unsup),
        "unsupported_pre_verifier_total": (sum(r.get("unsupported_pre_verifier", 0) for r in rows)
                                           if any("unsupported_pre_verifier" in r for r in rows) else None),
        "letters_with_violations": len(viol_final) + sum(1 for r in blocked if r not in viol_final),
        "violations_caught_before_submit": len(blocked),
        "violating_letters_shipped": len(shipped_viol),
        "submitted": len(subs), "replied": sum(r["replied"] for r in subs),
        "reply_rate_realized_per_submitted": round(sum(r["replied"] for r in subs) / len(subs), 3) if subs else None,
        "reply_rate_expected_per_submitted": round(sum(r["expected_reply_prob"] for r in subs) / len(subs), 3)
        if subs else None,
        "expected_replies_per_job_attempted": round(sum(r["expected_reply_prob"] for r in subs) / n, 3),
        "tokens_per_job_mean": round(sum(r["tokens"] for r in rows) / n, 1),
        "latency_s_mean": round(sum(lat) / n, 1), "latency_s_p50": round(statistics.median(lat), 1),
        "latency_s_p95": pct(lat, 0.95),
        "tool_calls_per_job_mean": round(sum(r["tool_calls"] for r in rows) / n, 2),
    }


def _np(o):
    """json default: numpy scalars (bool_, float64, int64) from scipy and numpy results."""
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def aggregate(rows: list[dict]) -> dict:
    out = {}
    for a in ARCHS:
        ra = [r for r in rows if r["arch"] == a]
        if not ra:
            continue
        out[a] = {"overall": summarize(ra), "by_kind": {k: summarize([r for r in ra if r["kind"] == k])
                                                         for k in KINDS if any(r["kind"] == k for r in ra)}}
    return out


def pick_jobs(dev: list[dict], n: int) -> list[dict]:
    """Stratified, deterministic: per kind sorted by (index, persona), visited round robin by kind."""
    by = {k: sorted([j for j in dev if j["gold"]["kind"] == k],
                    key=lambda j: (int(j["job_id"].rsplit("-", 1)[1]), j["gold"]["persona"])) for k in KINDS}
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by.values()):
        for k in KINDS:
            if i < len(by[k]) and len(out) < n:
                out.append(by[k][i])
        i += 1
    return out


async def main(n: int, budget_min: float, archs: tuple[str, ...], out_path: Path) -> dict:
    install_native_llm()
    set_profile("eval_qwen", f"ollama/{MODEL}", f"ollama/{MODEL}")
    sim = Sim()
    dev = json.loads((ROOT / "datasets" / "dev_jobs.json").read_text(encoding="utf-8"))
    jobs = pick_jobs(dev, n)
    ps = prompts()
    g = build_bid_graph(MemorySaver())
    retrs = {p: get_retriever("v2_hybrid", p) for p in ("ai_ml", "web", "data")}
    valid = {p: set(get_corpus(p).by_id) for p in retrs}
    runners = {"react": lambda tools: build_react(tools, ps), "supervisor": lambda tools: build_supervisor(tools, ps),
               "graph": g}
    meta = {"model": MODEL, "runtime": "ollama", "num_ctx": NUM_CTX, "temperature": CFG["llm"]["temperature"],
            "n_requested": n, "n_arch_n_config": CFG.get("evals", {}).get("arch_n", "unset, default 50"),
            "budget_minutes": budget_min, "architectures": list(archs),
            "job_selection": "stratified by gold kind, round robin, deterministic (see pick_jobs)",
            "decision_note": "In the graph the bid-or-skip decision is rule based (risk regex plus retriever fit), "
                             "the LLM only affects analyst deliverables, the letter and the critic. In react and "
                             "supervisor the LLM makes the decision using the same thresholds given in the prompt.",
            "fairness_notes": [
                "Baselines get the same decision thresholds and pricing rule through the prompt (agent/prompts/arch_compare.md).",
                "Baselines have no injection defence, claim verifier or compliance node, which is the point of the comparison.",
                "Baseline write tools are forced to dry_run, the harness submits the final JSON answer to GigSim.",
                "Tokens are Ollama prompt_eval_count plus eval_count summed over all LLM calls. The tool design run showed this Ollama build reports the full prompt count for an identical repeated prompt (925 and 925), so cached prefixes are not hidden.",
                "Unsupported claims and violations are measured on the final letter by one shared checker.",
                "GigSim store counters are cleared before each submit so replies depend on the job only."],
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows: list[dict] = []
    t_start = time.time()
    done = 0
    for job in jobs:
        if (time.time() - t_start) / 60 > budget_min:
            print("time budget reached, stopping", flush=True)
            break
        persona = job["gold"]["persona"]
        for arch in archs:
            row = await evaluate_job(arch, runners[arch], sim, job, retrs[persona], valid[persona], arch)
            rows.append(row)
            print(f"[{done + 1}/{len(jobs)}] {job['job_id']} {job['gold']['kind']:<8} {arch:<10} "
                  f"pred={row.get('pred_action')} gold={job['gold']['action']} {row['latency_s']}s "
                  f"tok={row['tokens']} {row['error'] or ''}", flush=True)
        done += 1
        meta["n_jobs_completed"] = done
        meta["elapsed_min"] = round((time.time() - t_start) / 60, 1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"meta": meta, "results": aggregate(rows), "rows": rows}, indent=1),
                            encoding="utf-8")
    meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta["llm_http_calls_graph"] = len(STATS)
    meta["llm_http_call_errors_graph"] = sum("error" in s for s in STATS)
    out = {"meta": meta, "results": aggregate(rows), "rows": rows}
    out_path.write_text(json.dumps(out, indent=1, default=_np), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=int(CFG.get("evals", {}).get("arch_n", 50)))
    ap.add_argument("--budget-min", type=float, default=22.0)
    ap.add_argument("--archs", default=",".join(ARCHS))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    res = asyncio.run(main(a.n, a.budget_min, tuple(a.archs.split(",")), Path(a.out)))
    print(json.dumps({k: v["overall"] for k, v in res["results"].items()}, indent=1))
