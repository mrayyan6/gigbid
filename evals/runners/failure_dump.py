"""Failure analysis: failed dev jobs grouped into the report taxonomy, written to evals/results/failures.json.

Sources (nothing is invented, every entry points at a job id and a measured outcome):
  decision errors   re-run of the bid graph to the decision node in template mode on all dev jobs
                    (gold action vs predicted action)
  injection         evals/results/injection_eval.json rows where the attack succeeded
  unsupported claim evals/results/proposal_eval.json records with unsupported sentences before the verifier

Taxonomy used in the report: missed evidence, wrong skip, mispriced, unsupported claim, generic opening,
compliance miss, injection, tool error. Mapping of decision errors:
  gold bid, predicted skip or watch      -> wrong skip
  gold lowball skip, predicted bid       -> mispriced (bid on a job the budget does not justify)
  gold offtopic skip, predicted bid      -> missed evidence (fit judged high without matching evidence)
  gold scam skip, predicted bid          -> compliance miss
  gold inject skip, predicted bid        -> injection
  gold stretch watch, predicted bid/skip -> wrong skip when predicted skip, mispriced is NOT used
A "fix tried" is only filled when a fix actually exists in the repo and was measured. Otherwise it is "none yet".

Run: python -m evals.runners.failure_dump
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import Counter

from evals.runners._harness import RESULTS, Env, dev_jobs
from rag.retriever import get_retriever

PER_CATEGORY_LISTED = 5


def taxonomy(gold: dict, pred: str) -> str | None:
    g, k = gold["action"], gold["kind"]
    if g == pred:
        return None
    if g == "bid":
        return "wrong skip"
    if pred == "bid":
        return {"lowball": "mispriced", "offtopic": "missed evidence", "scam": "compliance miss",
                "inject": "injection"}.get(k, "mispriced")
    if g == "watch" and pred == "skip":
        return "wrong skip"
    return None


async def decision_failures() -> tuple[list[dict], dict]:
    os.environ["LLM_ENABLED"] = "0"
    env = Env()
    rows, total = [], Counter()
    for j in dev_jobs():
        p = j["gold"]["persona"]
        run = await env.run_to_interrupt(j["job_id"], f"fail-{j['job_id']}", get_retriever("v2_hybrid", p))
        dec_ = run["values"]["decision"]
        pred = dec_["action"]
        total["jobs"] += 1
        cat = taxonomy(j["gold"], pred)
        if cat:
            total[cat] += 1
            rows.append({"job_id": j["job_id"], "persona": p, "kind": j["gold"]["kind"], "taxonomy": cat,
                         "gold": j["gold"]["action"], "predicted": pred, "reason": dec_["reason"],
                         "fix_tried": "none yet", "fix_worked": None})
    return rows, dict(total)


def injection_failures() -> list[dict]:
    d = json.loads((RESULTS / "injection_eval.json").read_text(encoding="utf-8"))
    on = {(r["case"]): r for r in d["rows"] if r["defences"]}
    rows = []
    for r in d["rows"]:
        if r["defences"] or not r["success"]:
            continue
        after = on.get(r["case"])
        rows.append({"job_id": r["case"], "set": r["set"], "type": r["type"], "taxonomy": "injection",
                     "evidence": f"outcome {r['outcome']} with defences off",
                     "fix_tried": "delimit untrusted text, injection risk patterns, writer system rule (defences on)",
                     "fix_worked": (not after["success"]) if after else None,
                     "outcome_with_defences": after["outcome"] if after else None})
    return rows


def unsupported_failures() -> list[dict]:
    d = json.loads((RESULTS / "proposal_eval.json").read_text(encoding="utf-8"))
    rows = []
    for r in d["records"]:
        if r["audit_before"] > 0:
            rows.append({"job_id": r["job_id"], "variant": r["variant"], "taxonomy": "unsupported claim",
                         "evidence": f"{r['audit_before']} unsupported sentences in the writer draft",
                         "fix_tried": "claim verifier removes or rewrites untagged past-work claims before the Critic",
                         "fix_worked": r["audit_after"] == 0, "audit_after": r["audit_after"]})
    return rows


def main() -> None:
    dec, totals = asyncio.run(decision_failures())
    inj, uns = injection_failures(), unsupported_failures()
    allrows = dec + inj + uns
    by_cat = Counter(r["taxonomy"] for r in allrows)
    listed = []
    for cat in by_cat:
        listed += [r for r in allrows if r["taxonomy"] == cat][:PER_CATEGORY_LISTED]
    out = {"meta": {"taxonomy": ["missed evidence", "wrong skip", "mispriced", "unsupported claim", "generic opening",
                                 "compliance miss", "injection", "tool error"],
                    "counts_by_category": dict(by_cat), "decision_totals": totals,
                    "not_observed": ["generic opening", "tool error"],
                    "note": "generic opening is checked by the Critic but not logged per job, and no tool error "
                            "occurred in the dev runs, so those two categories have no entries"},
           "listed": listed, "all": allrows}
    (RESULTS / "failures.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["meta"], indent=1))


if __name__ == "__main__":
    main()
