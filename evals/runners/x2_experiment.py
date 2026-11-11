"""Extension X2: proposal strategy A/B test against GigSim.

Strategy A = agent/prompts/writer.md (evidence first). Strategy B = agent/prompts/writer_b.md (outcome,
timeline and price first). The same pool of bid jobs is split by a hash of the job id into two arms, each
job gets exactly one strategy, drafts come from the LLM writer (Ollama), every draft is auto approved in
process and GigSim draws a reply. Primary test: two proportion z test on reply rate (scipy) with a 95
percent confidence interval for the difference, plus Fisher exact as a small sample check.

Secondary, lower variance diagnostic: GigSim's own reply probability for each submitted draft (computed by
calling the simulator's internal function in process). The real world has no such oracle, so it is reported
as a diagnostic of why the primary test is or is not powered, never as an outcome.

Run (background): python -m evals.runners.x2_experiment [--max-minutes 30]
Output: evals/results/x2_experiment.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time

from scipy import stats

from agent import llm
from evals.runners._harness import (CFG, RESULTS, Env, audit_unsupported, decision_pool, dev_jobs,
                                    draft_sentences_after, hkey, judge_draft, llm_used, mean, pctl, wilson)
from rag.retriever import get_retriever

C = CFG["x2"]


def arm_of(job_id: str) -> str:
    return "A" if int(hkey(job_id, "x2")[:8], 16) % 2 == 0 else "B"


def two_prop(k1: int, n1: int, k2: int, n2: int) -> dict:
    """A is group 1, B group 2. Difference = rate_B - rate_A."""
    p1, p2 = k1 / n1, k2 / n2
    pool = (k1 + k2) / (n1 + n2)
    se0 = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se0 if se0 else 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p2 - p1
    fisher = stats.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])[1]
    # smallest absolute difference detectable at 80 percent power for this n and the pooled rate
    mde = (1.96 + 0.84) * math.sqrt(2 * max(pool * (1 - pool), 1e-9) / ((n1 + n2) / 2))
    return {"rate_A": p1, "rate_B": p2, "diff_B_minus_A": d, "ci95_diff": [d - 1.96 * se, d + 1.96 * se],
            "z": z, "p_value_two_sided": p, "fisher_exact_p": fisher,
            "significant_at_0.05": p < CFG["x2"]["alpha"], "min_detectable_diff_80pct_power": mde}


def expected_reply_prob(rec: dict) -> float:
    from gigsim.app import _reply_probability, store
    job = store.jobs[rec["job_id"]]
    return _reply_probability(job, store.clients[job["client_id"]], rec)


async def run(max_minutes: float) -> dict:
    os.environ["LLM_ENABLED"] = "1"
    t0 = time.time()
    env = Env()
    pool = await decision_pool(env, sorted(dev_jobs(), key=lambda j: hkey(j["job_id"], 7)),
                               lambda p: get_retriever("v2_hybrid", p))
    jobs = pool[:C["n_jobs"]]
    rows, stopped = [], False
    for j in jobs:
        if (time.time() - t0) / 60 > max_minutes:
            stopped = True
            break
        arm = arm_of(j["job_id"])
        strategy = C["strategies"][arm]
        run_ = await env.run_to_interrupt(j["job_id"], f"x2-{j['job_id']}",
                                          get_retriever("v2_hybrid", j["gold"]["persona"]),
                                          {"writer_strategy": strategy})
        v = run_["values"]
        if not run_["interrupted"] or "proposal_draft" not in v:
            continue
        draft = v["proposal_draft"]["cover_letter"]
        out = await env.approve(run_)
        rows.append({"job_id": j["job_id"], "persona": j["gold"]["persona"], "kind": j["gold"]["kind"],
                     "arm": arm, "strategy_used": v.get("strategy"), "llm_used": llm_used(v),
                     "status": out.get("status"), "replied": out.get("status") == "replied",
                     "expected_reply_prob": expected_reply_prob(out), "words": len(draft.split()),
                     "audit_after": audit_unsupported(draft_sentences_after(v), v["evidence"], v["job"],
                                                      v["price_quote"]["amount"]),
                     "tokens": v.get("tokens", 0), "latency_s": round(run_["wall_s"], 2), "draft": draft})
        print(len(rows), arm, rows[-1]["status"], round(rows[-1]["expected_reply_prob"], 2),
              f"{rows[-1]['latency_s']}s", flush=True)

    def arm_stats(a: str) -> dict:
        r = [x for x in rows if x["arm"] == a]
        k = sum(x["replied"] for x in r)
        return {"strategy": C["strategies"][a], "n": len(r), "replies": k,
                "reply_rate": k / len(r) if r else None, "ci95": wilson(k, len(r)),
                "mean_expected_reply_prob": mean([x["expected_reply_prob"] for x in r]),
                "mean_words": mean([x["words"] for x in r]),
                "unsupported_audit_mean": mean([x["audit_after"] for x in r]),
                "llm_writer_used_share": mean([float(x["llm_used"]) for x in r]),
                "p50_latency_s": pctl([x["latency_s"] for x in r], 0.5)}

    sa, sb = arm_stats("A"), arm_stats("B")
    res = {"meta": {"n_pool": len(pool), "n_requested": C["n_jobs"], "n_run": len(rows),
                    "stopped_early": stopped, "elapsed_min": round((time.time() - t0) / 60, 1),
                    "design": "jobs the graph decides to bid on, not scam or injected, ordered by sha256, first N; "
                              "arm = sha256(x2:job_id) parity; one strategy per job",
                    "writer_model": llm.resolve_model("writer"), "profile": os.environ.get("GIGBID_PROFILE", "open"),
                    "retriever": "v2_hybrid", "alpha": C["alpha"],
                    "caveat": "GigSim reply draws are pseudo random per proposal id, so n near 30 per arm can only "
                              "detect large differences (see min_detectable_diff_80pct_power)"},
           "A": sa, "B": sb}
    if sa["n"] and sb["n"]:
        res["test_reply_rate"] = two_prop(sa["replies"], sa["n"], sb["replies"], sb["n"])
        ea = [x["expected_reply_prob"] for x in rows if x["arm"] == "A"]
        eb = [x["expected_reply_prob"] for x in rows if x["arm"] == "B"]
        t = stats.ttest_ind(eb, ea, equal_var=False)
        res["diagnostic_expected_reply_prob"] = {
            "mean_A": mean(ea), "mean_B": mean(eb), "diff_B_minus_A": mean(eb) - mean(ea),
            "welch_t": float(t.statistic), "p_value": float(t.pvalue),
            "note": "simulator internal probability, not observable in the real world"}
    res["rows"] = rows
    (RESULTS / "x2_experiment.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=30.0)
    r = asyncio.run(run(ap.parse_args().max_minutes))
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=1))
