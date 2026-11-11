"""LLM judge calibration against the user's own labels.

CSV: evals/datasets/judge_labels.csv, columns id,persona,job,draft,user_score,judge_score.
user_score (1 to 5 overall) is filled by the human only. This script never writes it.

Usage
  python -m evals.runners.judge_calibration --export drafts.json   # drafts.json: [{id, persona, job, draft}]
      writes the CSV with blank user_score and runs the judge (agent/prompts/judge.md) into judge_score
  python -m evals.runners.judge_calibration --judge                # (re)fill judge_score for rows missing it
  python -m evals.runners.judge_calibration                        # compute kappa -> evals/results/judge_calibration.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "evals" / "datasets" / "judge_labels.csv"
OUT = ROOT / "evals" / "results" / "judge_calibration.json"
PROMPT = ROOT / "agent" / "prompts" / "judge.md"
FIELDS = ["id", "persona", "job", "draft", "user_score", "judge_score"]
MIN_LABELS = 30


def read_rows() -> list[dict]:
    with CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows: list[dict]) -> None:
    CSV.parent.mkdir(parents=True, exist_ok=True)
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in FIELDS} for r in rows)


def judge_one(job: str, draft: str) -> int | None:
    from agent import llm
    user = f"<job_post>\n{job}\n</job_post>\n<draft>\n{draft}\n</draft>"
    res = llm.complete("judge", PROMPT.read_text(encoding="utf-8"), user, json_mode=True, max_tokens=200)
    obj = llm.parse_json(res.text)
    try:
        return max(1, min(5, int(round(float(obj["overall"])))))
    except (TypeError, KeyError, ValueError):
        return None


def fill_judge(rows: list[dict]) -> None:
    for r in rows:
        if not r.get("judge_score"):
            s = judge_one(r["job"], r["draft"])
            r["judge_score"] = "" if s is None else str(s)


def calibrate(rows: list[dict]) -> dict:
    pairs = [(r, int(r["user_score"]), int(r["judge_score"])) for r in rows
             if str(r.get("user_score", "")).strip() and str(r.get("judge_score", "")).strip()]
    if not pairs:
        return {"status": "not run", "reason": "no rows have both user_score and judge_score",
                "n_rows": len(rows), "n_labelled": 0}
    u, j = [p[1] for p in pairs], [p[2] for p in pairs]

    def kappa(w):
        try:
            k = float(cohen_kappa_score(u, j, weights=w, labels=[1, 2, 3, 4, 5]))
        except ValueError:
            return None
        return None if k != k else k      # NaN when a rater is constant

    worst = sorted(pairs, key=lambda p: -abs(p[1] - p[2]))[:2]
    return {
        "status": "ok" if len(pairs) >= MIN_LABELS else f"partial: fewer than {MIN_LABELS} labels",
        "n_labelled": len(pairs),
        "kappa_quadratic": kappa("quadratic"), "kappa_unweighted": kappa(None),
        "exact_agreement": sum(a == b for a, b in zip(u, j)) / len(u),
        "within_one": sum(abs(a - b) <= 1 for a, b in zip(u, j)) / len(u),
        "mean_user": sum(u) / len(u), "mean_judge": sum(j) / len(j),
        "largest_disagreements": [{"id": r["id"], "user_score": a, "judge_score": b,
                                   "job": r["job"][:300], "draft": r["draft"][:600]} for r, a, b in worst],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", help="drafts json to turn into the labelling CSV")
    ap.add_argument("--judge", action="store_true", help="fill missing judge_score in the CSV")
    a = ap.parse_args()
    if a.export:
        drafts = json.loads(Path(a.export).read_text(encoding="utf-8"))
        rows = [{"id": d["id"], "persona": d.get("persona", ""), "job": d["job"], "draft": d["draft"],
                 "user_score": "", "judge_score": ""} for d in drafts]
        fill_judge(rows)
        write_rows(rows)
        print(f"wrote {len(rows)} rows to {CSV}; user_score is blank for you to fill")
    elif a.judge:
        rows = read_rows()
        fill_judge(rows)
        write_rows(rows)
    else:
        if not CSV.exists():
            res = {"status": "not run", "reason": f"{CSV.name} does not exist", "n_labelled": 0}
        else:
            res = calibrate(read_rows())
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in res.items() if k != "largest_disagreements"}, indent=1))
