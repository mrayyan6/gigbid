"""Measure the change request: what changed, how many lines (config vs code vs tests), how long it took.

Reads git tags cr-start and cr-end (annotated tags, so the tagger time is the clock) and the two decision
eval files. Writes evals/results/change_request.json.
Run: python scripts/change_request_stats.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evals" / "results"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def kind(path: str) -> str:
    if path.startswith("tests/"):
        return "tests"
    if path.endswith((".yaml", ".yml", ".json", ".md")) and not path.startswith("evals/results"):
        return "config_or_docs"
    if path.startswith("evals/results"):
        return "results"
    if path.endswith(".py"):
        return "code"
    return "other"


def main() -> None:
    t0 = int(git("for-each-ref", "refs/tags/cr-start", "--format=%(taggerdate:unix)") or git("log", "-1", "--format=%ct", "cr-start"))
    t1 = int(git("for-each-ref", "refs/tags/cr-end", "--format=%(taggerdate:unix)") or git("log", "-1", "--format=%ct", "cr-end"))
    files = []
    for line in git("diff", "--numstat", "cr-start", "cr-end").splitlines():
        a, d, path = line.split("\t")
        files.append({"path": path, "added": int(a) if a != "-" else 0, "deleted": int(d) if d != "-" else 0,
                      "kind": kind(path)})
    split: dict[str, dict] = {}
    for f in files:
        s = split.setdefault(f["kind"], {"files": 0, "added": 0, "deleted": 0})
        s["files"] += 1
        s["added"] += f["added"]
        s["deleted"] += f["deleted"]

    def load(name: str):
        p = RES / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    before, after = load("decision_eval_before_cr.json"), load("decision_eval_after_cr.json")
    metrics = {}
    if before and after:
        for p in ("ai_ml", "web", "data"):
            metrics[p] = {"bid_f1_before": before[p]["bid_or_skip"]["f1"], "bid_f1_after": after[p]["bid_or_skip"]["f1"],
                          "bid_precision_before": before[p]["bid_or_skip"]["precision"],
                          "bid_precision_after": after[p]["bid_or_skip"]["precision"],
                          "accuracy_3way_before": before[p]["accuracy_3way"],
                          "accuracy_3way_after": after[p]["accuracy_3way"]}
    out = {"label": "self imposed change request, mirrors the announced 2 Nov platform policy update format; the "
                    "instructor did not publish a concrete policy text for self built simulators",
           "start_commit": git("rev-list", "-n1", "cr-start"), "end_commit": git("rev-list", "-n1", "cr-end"),
           "elapsed_minutes": round((t1 - t0) / 60, 1), "files_changed": len(files), "by_kind": split,
           "files": files, "decision_metrics": metrics,
           "tests_added": [f["path"] for f in files if f["kind"] == "tests"]}
    (RES / "change_request.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "files"}, indent=1))


if __name__ == "__main__":
    main()
