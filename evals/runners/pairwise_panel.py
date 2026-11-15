"""Blind pairwise human panel (brief B4: classmates rate anonymised proposals).

Two commands:

  python -m evals.runners.pairwise_panel make [--pairs 10] [--seed 7]
      Builds anonymised pairs from the proposal drafts that were also scored by the LLM judge
      (evals/datasets/judge_labels.csv): for each job, the draft written with the baseline retrieval (v0_naive)
      against the draft written with the best retrieval (v3_rerank). Which one is shown first is random. Writes
        evals/datasets/pairwise_pairs.json   what raters see (no variant names)
        evals/datasets/pairwise_key.json     which variant is A and B in each pair (keep it from the raters)
        evals/datasets/pairwise_sheet.html   a printable sheet to give to raters

  python -m evals.runners.pairwise_panel score
      Reads evals/datasets/pairwise_responses.csv (columns rater, pair_id, choice with choice A, B or T for a tie)
      and writes evals/results/pairwise_panel.json: wins per variant, a two sided sign test, inter rater agreement
      and agreement with the LLM judge. Nothing is written when there are no responses, so no result can exist
      without human data.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
from collections import defaultdict
from itertools import combinations
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evals" / "datasets"
RESULTS = ROOT / "evals" / "results"
BASE, BEST = "v0_naive", "v3_rerank"
TAG = re.compile(r"\s*\[ev:[^\]]*\]")


def clean(text: str) -> str:
    """Evidence tags like [ev:ai_ml-cs-03] are internal bookkeeping, so raters do not see them."""
    return TAG.sub("", text).strip()


def make(n_pairs: int = 10, seed: int = 7) -> dict:
    rows = list(csv.DictReader((DATA / "judge_labels.csv").open(encoding="utf-8")))
    by: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        variant, job_id = r["id"].split(":", 1)
        by[job_id][variant] = r
    jobs = sorted(j for j, v in by.items() if BASE in v and BEST in v)
    rng = random.Random(seed)
    chosen = sorted(rng.sample(jobs, min(n_pairs, len(jobs))))
    rng.shuffle(chosen)
    pairs, key = [], {}
    for n, job_id in enumerate(chosen, start=1):
        base_first = rng.random() < 0.5
        a, b = (BASE, BEST) if base_first else (BEST, BASE)
        pid = f"P{n:02d}"
        pairs.append({"pair_id": pid, "job": by[job_id][BASE]["job"], "A": clean(by[job_id][a]["draft"]),
                      "B": clean(by[job_id][b]["draft"])})
        key[pid] = {"A": a, "B": b, "job_id": job_id,
                    "judge_score": {BASE: float(by[job_id][BASE]["judge_score"] or 0),
                                    BEST: float(by[job_id][BEST]["judge_score"] or 0)}}
    (DATA / "pairwise_pairs.json").write_text(json.dumps(pairs, indent=1), encoding="utf-8")
    (DATA / "pairwise_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (DATA / "pairwise_sheet.html").write_text(sheet(pairs), encoding="utf-8")
    return {"pairs": len(pairs), "seed": seed, "jobs_available": len(jobs)}


def sheet(pairs: list[dict]) -> str:
    css = ("body{font-family:Segoe UI,Arial,sans-serif;font-size:13px;margin:26px 34px;line-height:1.5;color:#111}"
           "h1{font-size:21px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 4px;border-bottom:1px solid #bbb}"
           ".job{background:#f3f3f3;padding:6px 9px}.p{border:1px solid #999;padding:7px 10px;margin:6px 0}"
           ".q{font-weight:600;margin:6px 0 2px}.box{border:1px solid #888;background:#f7f7f7;padding:8px 11px}"
           ".pb{page-break-inside:avoid}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>Proposal comparison sheet</title><style>{css}</style></head><body>",
           "<h1>Which proposal is better? (about 15 minutes)</h1>",
           "<div class='box'><p>Each question shows a freelance job and two proposals written for it, <b>Proposal A</b> and "
           "<b>Proposal B</b>. You do not know which system wrote which. Pick the one you would rather receive if you were "
           "the client: clearer, more relevant, more believable, with specific evidence and no empty claims.</p>"
           "<p>Answer with <b>A</b>, <b>B</b> or <b>T</b> (a tie, only if you really cannot choose). All jobs and proposals are "
           "synthetic. Please do your own judgement and do not discuss it with other raters.</p>"
           "<p><b>How to reply:</b> send one line with your name and one letter per question, for example: "
           "<i>Ali: P01 A, P02 B, P03 A, P04 T, ...</i></div>"]
    for p in pairs:
        out.append(f"<div class='pb'><h2>{p['pair_id']}</h2><div class='job'><b>Job:</b> {html.escape(p['job'])}</div>"
                   f"<div class='p'><b>Proposal A</b><br>{html.escape(p['A'])}</div>"
                   f"<div class='p'><b>Proposal B</b><br>{html.escape(p['B'])}</div>"
                   f"<div class='q'>Your choice for {p['pair_id']}: A / B / T</div></div>")
    out.append("</body></html>")
    return "".join(out)


def sign_test_p(wins: int, losses: int) -> float:
    """Two sided exact sign test p value (ties excluded)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def analyse(responses: list[dict], key: dict, judge_pick: dict[str, str | None] | None = None) -> dict:
    per_pair: dict[str, list[str]] = defaultdict(list)
    per_rater: dict[str, dict[str, str]] = defaultdict(dict)
    for r in responses:
        c = r["choice"].strip().upper()
        if c not in {"A", "B", "T"} or r["pair_id"] not in key:
            continue
        variant = "T" if c == "T" else key[r["pair_id"]][c]
        per_pair[r["pair_id"]].append(variant)
        per_rater[r["rater"]][r["pair_id"]] = variant
    votes = {BASE: 0, BEST: 0, "tie": 0}
    majority: dict[str, str] = {}
    for pid, vs in per_pair.items():
        for v in vs:
            votes[BASE if v == BASE else BEST if v == BEST else "tie"] += 1
        a, b = vs.count(BASE), vs.count(BEST)
        majority[pid] = BASE if a > b else BEST if b > a else "tie"
    decisive = votes[BASE] + votes[BEST]
    pair_wins = {BASE: sum(m == BASE for m in majority.values()), BEST: sum(m == BEST for m in majority.values())}
    # agreement: share of rater pairs that chose the same variant on the pairs both rated
    agree = total = 0
    for r1, r2 in combinations(per_rater, 2):
        for pid in set(per_rater[r1]) & set(per_rater[r2]):
            total += 1
            agree += per_rater[r1][pid] == per_rater[r2][pid]
    out = {"raters": len(per_rater), "pairs_rated": len(per_pair), "votes": votes,
           "share_best_of_decisive_votes": round(votes[BEST] / decisive, 3) if decisive else None,
           "sign_test_p_votes": round(sign_test_p(votes[BEST], votes[BASE]), 4),
           "pair_majority_wins": pair_wins,
           "rater_pair_agreement": round(agree / total, 3) if total else None,
           "variants": {"baseline": BASE, "best": BEST}}
    if judge_pick:
        both = [(majority[p], judge_pick[p]) for p in majority if judge_pick.get(p) and majority[p] != "tie"]
        out["agreement_with_llm_judge"] = (round(sum(h == j for h, j in both) / len(both), 3) if both else None)
        out["pairs_compared_with_judge"] = len(both)
    return out


def score(responses_path: Path | None = None, out_path: Path | None = None, rater_type: str = "human") -> dict | None:
    """Score a responses file. rater_type is written into the result so an agent file can never be mistaken for a
    human one: human replies go to pairwise_responses.csv, agent replies to agent_rater_responses.csv."""
    path = responses_path or DATA / "pairwise_responses.csv"
    if not path.exists():
        print("no responses file:", path)
        return None
    responses = list(csv.DictReader(path.open(encoding="utf-8")))
    if not responses:
        print("responses file is empty")
        return None
    key = json.loads((DATA / "pairwise_key.json").read_text(encoding="utf-8"))
    judge_pick = {}
    for pid, k in key.items():
        sc = k["judge_score"]
        judge_pick[pid] = BEST if sc[BEST] > sc[BASE] else BASE if sc[BASE] > sc[BEST] else None
    res = analyse(responses, key, judge_pick)
    res["rater_type"] = rater_type
    res["responses_file"] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name
    res["note"] = ("Blind pairwise ratings: raters saw anonymised drafts in random order. Sample is small, so read the "
                   "sign test p value and the raters count before the share. rater_type says who rated.")
    dest = out_path or RESULTS / "pairwise_panel.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--pairs", type=int, default=10)
    m.add_argument("--seed", type=int, default=7)
    sc = sub.add_parser("score")
    sc.add_argument("--responses", type=Path, default=None)
    sc.add_argument("--out", type=Path, default=None)
    sc.add_argument("--rater-type", default="human", choices=["human", "agent"])
    a = ap.parse_args()
    if a.cmd == "make":
        print(make(a.pairs, a.seed))
    else:
        score(a.responses, a.out, a.rater_type)


if __name__ == "__main__":
    main()
