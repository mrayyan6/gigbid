"""Proposal quality with the LLM on: unsupported claims before and after verification, judge score,
latency, tokens, cost and GigSim reply rate, for V0 (naive dense) vs the best retrieval variant.

For each bid job the graph runs to the approval interrupt with llm.enabled (Ollama). Latency is the wall
time of that run (judge and approval excluded). Then the draft is judged, auto approved in process and the
GigSim outcome recorded (see gigsim_outcomes.py). The first N drafts are exported to
evals/datasets/judge_labels.csv with blank user_score for the human to label (never filled here).

Two unsupported claim measures are reported for every draft:
 verifier rule: sentences about past work without a valid [ev:id] tag (what the Verifier node removes)
 strict audit: also flags a tagged sentence whose numbers are not in the cited evidence (independent check)
"before" = writer output, "after" = final draft that reaches the approval screen.

Run (background): python -m evals.runners.proposal_eval [--max-minutes 28]
Output: evals/results/proposal_eval.json, evals/results/gigsim_outcomes.json, evals/datasets/judge_labels.csv
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from agent import llm
from evals.runners import gigsim_outcomes
from evals.runners._harness import (CFG, DATASETS, RESULTS, Env, audit_unsupported, decision_pool, dev_jobs,
                                    draft_sentences_after, draft_sentences_before, hkey, judge_draft, llm_used,
                                    mean, pctl, verifier_rule_unsupported)
from evals.runners.ablation import pick_best
from evals.runners.judge_calibration import CSV, read_rows, write_rows
from rag.retriever import get_retriever

C = CFG["proposal_eval"]
PERSONAS = ("ai_ml", "web", "data")


def job_text(j: dict) -> str:
    return f"{j['title']}. {j['description']}"


def export_labels(drafts: list[dict]) -> bool:
    """Write the first drafts for human labelling. Never overwrites a file that already has user scores."""
    if CSV.exists() and any((r.get("user_score") or "").strip() for r in read_rows()):
        return False
    write_rows([{"id": d["id"], "persona": d["persona"], "job": d["job"], "draft": d["draft"],
                 "user_score": "", "judge_score": ""} for d in drafts[:C["judge_export_n"]]])
    return True


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    lat = [r["latency_s"] for r in rows]
    j = [r["judge"] for r in rows if r["judge"] is not None]
    return {"n_proposals": n,
            "llm_writer_used_share": mean([float(r["llm_used"]) for r in rows]),
            "unsupported_per_proposal_before": mean([r["verifier_before"] for r in rows]),
            "unsupported_per_proposal": mean([r["verifier_after"] for r in rows]),
            "unsupported_audit_before": mean([r["audit_before"] for r in rows]),
            "unsupported_audit_after": mean([r["audit_after"] for r in rows]),
            "judge_score": mean(j), "judge_n": len(j),
            "p50_latency_s": pctl(lat, 0.5), "p95_latency_s": pctl(lat, 0.95),
            "tokens_per_proposal": mean([r["tokens"] for r in rows]),
            "cost_per_proposal_usd": mean([r["cost_usd"] for r in rows]),
            "critic_revisions_mean": mean([r["revisions"] for r in rows]),
            "reply_rate": gigsim_outcomes.rate(rows)["reply_rate"]}


async def run(max_minutes: float, out_name: str = "proposal_eval.json", n_override: int | None = None,
              variants_override: list[str] | None = None) -> dict:
    os.environ["LLM_ENABLED"] = "1"
    t_start = time.time()
    if n_override:
        C["n_per_persona"] = n_override
    if variants_override:
        C["variants"] = variants_override
    env = Env()
    best = pick_best()
    names = {"v0_naive": "v0_naive", "best": best}
    variants = [("v0_naive" if v == "v0_naive" else best) for v in C["variants"]]
    pool = await decision_pool(env, sorted(dev_jobs(), key=lambda j: hkey(j["job_id"], C["seed"])),
                               lambda p: get_retriever("v2_hybrid", p), per_persona=C["n_per_persona"])
    records, exported, label_rows, skipped = [], False, [], 0
    stopped_early = False
    for rnd in range(C["n_per_persona"]):
        for p in PERSONAS:
            cand = [j for j in pool if j["gold"]["persona"] == p]
            if rnd >= len(cand):
                continue
            j = cand[rnd]
            for v in variants:
                if (time.time() - t_start) / 60 > max_minutes:
                    stopped_early = True
                    break
                run_ = await env.run_to_interrupt(j["job_id"], f"prop-{v}-{j['job_id']}",
                                                  get_retriever(v, p))
                vals = run_["values"]
                if not run_["interrupted"] or "proposal_draft" not in vals:
                    skipped += 1
                    continue
                args = (vals["evidence"], vals["job"], vals["price_quote"]["amount"])
                draft = vals["proposal_draft"]["cover_letter"]
                jd = judge_draft(job_text(j), draft)
                outcome = await env.approve(run_)
                rec = {"id": f"{v}:{j['job_id']}", "variant": v, "persona": p, "job_id": j["job_id"],
                       "kind": j["gold"]["kind"], "latency_s": round(run_["wall_s"], 2),
                       "tokens": vals.get("tokens", 0), "cost_usd": vals.get("cost_usd", 0.0),
                       "llm_used": llm_used(vals), "revisions": vals.get("revisions", 0),
                       "verifier_before": sum(r["status"] == "unsupported" for r in vals["claim_verification"]),
                       "verifier_after": sum(
                           1 for s in draft_sentences_after(vals)
                           if audit_unsupported([s], vals["evidence"], vals["job"], args[2]) and "[ev:" not in s),
                       "audit_before": audit_unsupported(draft_sentences_before(vals), *args),
                       "audit_after": audit_unsupported(draft_sentences_after(vals), *args),
                       "judge": jd["overall"], "judge_tokens": jd["tokens"],
                       "outcome_status": outcome.get("status"), "draft": draft}
                records.append(rec)
                label_rows.append({"id": rec["id"], "persona": p, "job": job_text(j), "draft": draft})
                print(f"{len(records):3d} {rec['id']:42s} {rec['latency_s']:6.1f}s judge={rec['judge']} "
                      f"audit {rec['audit_before']}->{rec['audit_after']} {rec['outcome_status']}", flush=True)
                if out_name == "proposal_eval.json" and not exported and len(label_rows) >= C["judge_export_n"]:
                    exported = export_labels(label_rows)
                    print("exported judge_labels.csv", exported, flush=True)
            if stopped_early:
                break
        if stopped_early:
            break
    if out_name == "proposal_eval.json" and not exported and label_rows:
        exported = export_labels(label_rows)
    res = {"meta": {"n_per_persona_requested": C["n_per_persona"], "variants": names,
                    "best_variant": best, "skipped_non_bid": skipped, "stopped_early": stopped_early,
                    "max_minutes": max_minutes, "elapsed_min": round((time.time() - t_start) / 60, 1),
                    "models": {n: llm.resolve_model(n) for n in ("analyst", "writer", "critic", "judge")},
                    "judge_labels_exported": exported, "n_labels_exported": min(len(label_rows),
                                                                                C["judge_export_n"]),
                    "profile": os.environ.get("GIGBID_PROFILE", "open"),
                    "latency_note": "wall time of the graph run to the approval interrupt (local runs share one laptop GPU)",
                    "cost_note": "USD from per token list prices in agent/config_extra.yaml providers (0 for local Ollama, hardware cost not included)",
                    "unsupported_note": "unsupported_per_proposal(_before) use the Verifier rule: past-work sentences "
                                        "without a valid evidence tag. before = writer output of the last pass, "
                                        "after = final draft shown for approval. The audit columns add a number "
                                        "check on tagged sentences.",
                    "judge_note": f"judge = agent/prompts/judge.md on {llm.resolve_model('judge')}, uncalibrated until "
                                  "judge_calibration.json has a kappa from the human labels"},
           **{v: summarise([r for r in records if r["variant"] == v]) for v in dict.fromkeys(variants)},
           "by_persona": {v: {p: summarise([r for r in records if r["variant"] == v and r["persona"] == p])
                              for p in PERSONAS} for v in dict.fromkeys(variants)},
           "records": records}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / out_name).write_text(json.dumps(res, indent=1), encoding="utf-8")
    if out_name == "proposal_eval.json":
        gigsim_outcomes.main()
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=28.0)
    ap.add_argument("--out", default="proposal_eval.json")
    ap.add_argument("--n", type=int, default=None, help="override n per persona")
    ap.add_argument("--variants", nargs="+", default=None, help="subset of: v0_naive best")
    a = ap.parse_args()
    out = asyncio.run(run(a.max_minutes, a.out, a.n, a.variants))
    for v in out["meta"]["variants"].values():
        print(v, {k: x for k, x in out[v].items()})
