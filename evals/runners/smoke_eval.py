"""30 job smoke eval for CI: template mode (no LLM), in process GigSim, deterministic.

Measures bid-or-skip F1 (positive class = bid) and unsupported claims per proposal on a fixed set of dev
jobs (first N by a hash of the job id, so the set is stable and mixed across personas and kinds).

Usage
  python -m evals.runners.smoke_eval                    # measure, write evals/results/smoke_eval.json, check thresholds
  python -m evals.runners.smoke_eval --write-thresholds # also write evals/thresholds.yaml (baseline with margin)
Exit code 1 when a threshold in evals/thresholds.yaml is violated.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import yaml

from evals.runners._harness import (CFG, RESULTS, ROOT, Env, audit_unsupported, dev_jobs, draft_sentences_after,
                                    draft_sentences_before, hkey)
from rag.retriever import get_retriever

THRESHOLDS = ROOT / "evals" / "thresholds.yaml"


async def measure() -> dict:
    os.environ["LLM_ENABLED"] = "0"
    env = Env()
    n = CFG["smoke"]["n_jobs"]
    jobs = sorted(dev_jobs(), key=lambda j: hkey(j["job_id"]))[:n]
    tp = fp = fn = 0
    drafts, rows = [], []
    for j in jobs:
        retr = get_retriever("v2_hybrid", j["gold"]["persona"])
        run = await env.run_to_interrupt(j["job_id"], f"smoke-{j['job_id']}", retr)
        v = run["values"]
        pred = v["decision"]["action"]
        gold = j["gold"]["action"]
        tp += gold == "bid" and pred == "bid"
        fp += gold != "bid" and pred == "bid"
        fn += gold == "bid" and pred != "bid"
        row = {"job_id": j["job_id"], "kind": j["gold"]["kind"], "gold": gold, "pred": pred}
        if "proposal_draft" in v and pred == "bid":
            args = (v["evidence"], v["job"], v["price_quote"]["amount"])
            before = audit_unsupported(draft_sentences_before(v), *args)
            after = audit_unsupported(draft_sentences_after(v), *args)
            verifier_before = sum(r["status"] == "unsupported" for r in v["claim_verification"])
            row.update({"audit_before": before, "audit_after": after, "verifier_removed": verifier_before})
            drafts.append(row)
        rows.append(row)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    n_d = len(drafts)
    return {"meta": {"mode": "template (llm disabled)", "n_jobs": len(jobs), "n_proposals": n_d,
                     "selection": "first n dev jobs ordered by sha256(seed:job_id)", "retriever": "v2_hybrid"},
            "bid_or_skip": {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1},
            "unsupported_per_proposal": (sum(d["audit_after"] for d in drafts) / n_d) if n_d else None,
            "unsupported_per_proposal_before_verification": (sum(d["audit_before"] for d in drafts) / n_d)
            if n_d else None,
            "rows": rows}


def check(res: dict) -> list[str]:
    if not THRESHOLDS.exists():
        return ["evals/thresholds.yaml missing"]
    t = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    bad = []
    if res["bid_or_skip"]["f1"] < t["bid_f1_min"]:
        bad.append(f"bid F1 {res['bid_or_skip']['f1']:.3f} below {t['bid_f1_min']}")
    u = res["unsupported_per_proposal"]
    if u is not None and u > t["unsupported_per_proposal_max"]:
        bad.append(f"unsupported per proposal {u:.3f} above {t['unsupported_per_proposal_max']}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-thresholds", action="store_true")
    a = ap.parse_args()
    res = asyncio.run(measure())
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "smoke_eval.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if a.write_thresholds:
        s, f1 = CFG["smoke"], res["bid_or_skip"]["f1"]
        u = res["unsupported_per_proposal"] or 0.0
        THRESHOLDS.write_text(
            "# CI gate for evals/runners/smoke_eval.py. Values are the measured baseline (see\n"
            "# evals/results/smoke_eval.json) with a margin from evals/config.yaml. Raise the floor only with a new\n"
            "# measured baseline.\n"
            f"bid_f1_min: {round(max(0.0, f1 - s['margin_bid_f1']), 3)}\n"
            f"unsupported_per_proposal_max: {round(u + s['margin_unsupported'], 3)}\n"
            f"baseline_bid_f1: {round(f1, 3)}\n"
            f"baseline_unsupported_per_proposal: {round(u, 3)}\n", encoding="utf-8")
    bad = check(res)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for b in bad:
        print("THRESHOLD VIOLATED:", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
