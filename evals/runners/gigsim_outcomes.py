"""GigSim simulated reply and hire rate from auto approved proposals.

proposal_eval.py runs each draft to the approval interrupt, then resumes it in process with an approve
decision so GigSim draws a reply from its hidden client preference model. That is the only place proposals
are submitted by an eval (a stand in for the human approval step, never used outside evals). This module
aggregates those outcomes: reply rate per variant, persona and job kind with Wilson 95 percent intervals.

GigSim has no hire event in this simulator version, so hire rate is reported as not measured.

Run: python -m evals.runners.gigsim_outcomes   (re-aggregates evals/results/proposal_eval.json records)
"""
from __future__ import annotations

import json

from evals.runners._harness import RESULTS, wilson


def rate(rows: list[dict]) -> dict:
    sub = [r for r in rows if r.get("outcome_status") in ("replied", "submitted")]
    k = sum(r["outcome_status"] == "replied" for r in sub)
    return {"n_submitted": len(sub), "replies": k, "reply_rate": k / len(sub) if sub else None,
            "ci95": wilson(k, len(sub))}


def summarise(records: list[dict]) -> dict:
    out: dict = {}
    for v in sorted({r["variant"] for r in records}):
        rows = [r for r in records if r["variant"] == v]
        out[v] = {**rate(rows),
                  "by_persona": {p: rate([r for r in rows if r["persona"] == p])
                                 for p in sorted({r["persona"] for r in rows})},
                  "by_kind": {k: rate([r for r in rows if r["kind"] == k])
                              for k in sorted({r["kind"] for r in rows})}}
    return out


def main() -> None:
    src = json.loads((RESULTS / "proposal_eval.json").read_text(encoding="utf-8"))
    res = {"meta": {"source": "evals/results/proposal_eval.json records",
                    "how": "each draft approved in process, GigSim draws a reply from the client hidden preference",
                    "hire_rate": "not measured (the simulator has no hire event)",
                    "caveat": "reply probability in GigSim depends on keyword and price rules, so this measures "
                              "agreement with the simulator, not real market response"},
           **summarise(src["records"])}
    (RESULTS / "gigsim_outcomes.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "meta"}, indent=1)[:1500])


if __name__ == "__main__":
    main()
