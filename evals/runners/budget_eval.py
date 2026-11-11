"""Measured latency and cost per job analysed (a job that ends at the decision node), against the declared budget.

Uses dev jobs of kinds offtopic, lowball and stretch (the graph ends at decide or skips, no proposal is drafted),
LLM on. Reports p50 and p95 wall seconds, tokens and USD per job, and compares with agent/config.yaml
budgets.declared.job_analysed. The per proposal numbers come from proposal_eval.json.
Run: GIGBID_PROFILE=open_hosted python -m evals.runners.budget_eval -> evals/results/budget_eval.json
"""
from __future__ import annotations

import asyncio
import json
import os

import yaml

from agent import llm
from evals.runners._harness import RESULTS, ROOT, Env, dev_jobs, hkey, mean, pctl
from rag.retriever import get_retriever

KINDS = ("offtopic", "lowball", "stretch")
PER_KIND = 8


async def main() -> None:
    os.environ["LLM_ENABLED"] = "1"
    declared = yaml.safe_load((ROOT / "agent" / "config.yaml").read_text(encoding="utf-8"))["budgets"]["declared"]
    env = Env()
    rows = []
    for kind in KINDS:
        jobs = sorted([j for j in dev_jobs() if j["gold"]["kind"] == kind], key=lambda j: hkey(j["job_id"]))[:PER_KIND]
        for j in jobs:
            run = await env.run_to_interrupt(j["job_id"], f"budget-{j['job_id']}", get_retriever("v2_hybrid", j["gold"]["persona"]))
            v = run["values"]
            rows.append({"job_id": j["job_id"], "kind": kind, "action": v["decision"]["action"],
                         "latency_s": round(run["wall_s"], 2), "tokens": v.get("tokens", 0), "cost_usd": v.get("cost_usd", 0.0),
                         "interrupted": run["interrupted"]})
            print(len(rows), rows[-1], flush=True)
    only = [r for r in rows if not r["interrupted"]]
    lat = [r["latency_s"] for r in only]
    d = declared["job_analysed"]
    res = {"meta": {"profile": os.environ.get("GIGBID_PROFILE", "open"), "writer_model": llm.resolve_model("analyst"),
                    "kinds": list(KINDS), "per_kind": PER_KIND, "n_total": len(rows), "n_analysed_only": len(only),
                    "note": "jobs that reached the approval screen are excluded from the per job analysed figures"},
           "declared": declared,
           "measured_job_analysed": {"n": len(only), "p50_latency_s": pctl(lat, 0.5), "p95_latency_s": pctl(lat, 0.95),
                                     "tokens_mean": mean([r["tokens"] for r in only]),
                                     "cost_usd_mean": mean([r["cost_usd"] for r in only]),
                                     "p95_within_budget": pctl(lat, 0.95) <= d["p95_latency_s"],
                                     "cost_within_budget": mean([r["cost_usd"] for r in only]) <= d["cost_usd"]},
           "rows": rows}
    (RESULTS / "budget_eval.json").write_text(json.dumps(res, indent=1, default=lambda o: o.item()), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
