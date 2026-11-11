"""Bid-or-skip and scam metrics on the dev set, by persona (graph run up to the decision node).
Run: python -m evals.runners.decision_eval -> evals/results/decision_eval.json
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from langgraph.checkpoint.memory import MemorySaver

from agent.graphs.bid_graph import build_bid_graph
from gigsim import generate
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag.retriever import get_retriever

OUT = Path(__file__).resolve().parents[1] / "results"


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


async def run() -> dict:
    generate.build()
    import gigsim.app as gs
    from gigsim.app import app, store
    gs.RATE_OVERRIDE = 10**6  # in-process eval, no real traffic
    store.reset()
    mp = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app))
    dev = json.loads((OUT.parent / "datasets" / "dev_jobs.json").read_text(encoding="utf-8"))
    g = build_bid_graph(MemorySaver())
    res: dict = {}
    for persona in ("ai_ml", "web", "data"):
        retr = get_retriever("v2_hybrid", persona)
        rows = []
        for j in [d for d in dev if d["gold"]["persona"] == persona]:
            cfg = {"configurable": {"thread_id": f"e-{j['job_id']}", "marketplace": mp,
                                    "retriever": retr}}
            out = await g.ainvoke({"job_id": j["job_id"]}, cfg)
            pred = out["decision"]["action"]
            rows.append((j["gold"], pred, out))
        # bid-or-skip: positive class = bid; watch counts as not bid
        tp = sum(g_["action"] == "bid" and p == "bid" for g_, p, _ in rows)
        fp = sum(g_["action"] != "bid" and p == "bid" for g_, p, _ in rows)
        fn = sum(g_["action"] == "bid" and p != "bid" for g_, p, _ in rows)
        stp = sum(g_["scam"] and p == "skip" for g_, p, _ in rows)
        sfp = sum(not g_["scam"] and o["risk_report"]["score"] >= 0.6 for g_, _, o in rows)
        sfn = sum(g_["scam"] and p != "skip" for g_, p, _ in rows)
        res[persona] = {"n": len(rows), "bid_or_skip": prf(tp, fp, fn), "scam": prf(stp, sfp, sfn),
                        "accuracy_3way": sum(g_["action"] == p for g_, p, _ in rows) / len(rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "decision_eval.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=1))
