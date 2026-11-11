"""Render docs/results_tables.md from evals/results/*.json. README and report paste from that file only.

Every figure is copied from a results file. A missing file or key renders as "not measured".
Run: python scripts/render_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evals" / "results"
OUT = ROOT / "docs" / "results_tables.md"
NM = "not measured"


def load(name: str):
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def fmt(x) -> str:
    if x is None:
        return NM
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def flatten(d, prefix="") -> dict:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(d, list):
        if all(not isinstance(x, (dict, list)) for x in d):
            out[prefix[:-1]] = ", ".join(map(str, d))
        else:
            for i, v in enumerate(d):
                out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = d
    return out


def generic(name: str, title: str, blurb: str = "") -> str:
    data = load(name)
    s = f"## {title}\n\n{blurb}\n\n" if blurb else f"## {title}\n\n"
    if data is None:
        return s + f"{NM} (evals/results/{name}.json does not exist).\n\n"
    s += f"Source: evals/results/{name}.json\n\n"
    if isinstance(data, dict) and data and all(isinstance(v, dict) for v in data.values()):
        flat = {k: flatten(v) for k, v in data.items()}
        cols = sorted({c for f in flat.values() for c in f})
        return s + table(["key"] + cols, [[k] + [f.get(c) for c in cols] for k, f in flat.items()]) + "\n"
    flat = flatten(data)
    return s + table(["field", "value"], [[k, v] for k, v in flat.items()]) + "\n"


def pick(d: dict | None, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and not isinstance(d[k], dict):
            return d[k]
    return None


def b5() -> str:
    rag = load("rag_eval")
    prop = load("proposal_eval") or {}
    out = "## B5 results table (all personas pooled)\n\n"
    if rag is None:
        return out + f"{NM} (evals/results/rag_eval.json does not exist).\n\n"
    out += (f"Retrieval columns come from rag_eval.json (n={rag['meta']['n_jobs']} dev jobs, full job text "
            "queries). The remaining columns come from proposal_eval.json and gigsim_outcomes.json when "
            "those runs exist, else they read not measured.\n\n")
    rows = []
    for v, s in rag["variants"].items():
        a = s["by_persona"]["all"]
        p = prop.get(v, {}) if isinstance(prop, dict) else {}
        rows.append([v, a["recall@5"], a["ndcg@10"],
                     pick(p, "unsupported_per_proposal", "unsupported_claims_per_proposal"),
                     pick(p, "judge_score", "judge_mean"),
                     pick(p, "reply_rate", "gigsim_reply_rate"),
                     pick(p, "p95_latency_s", "p95_latency"),
                     pick(p, "cost_per_proposal_usd", "cost_per_proposal")])
    return out + table(["Variant", "Evidence Recall@5", "nDCG@10", "Unsupported claims per proposal",
                        "Judge score", "GigSim reply rate", "p95 latency (s)", "Cost per proposal (USD)"], rows) + "\n"


def rag_detail() -> str:
    rag = load("rag_eval")
    if rag is None:
        return ""
    m = rag["meta"]
    out = "## Retrieval by persona and requirement bucket\n\n"
    out += (f"n per persona: {m['n_per_persona']}; jobs with 4 or more requirements: {m['n_4plus']}. "
            f"Gold: {m['gold']}. Note: {m['circularity_note']}\n\n")
    rows = []
    for v, s in rag["variants"].items():
        row = [v]
        for p in ("ai_ml", "web", "data"):
            row.append(s["by_persona"][p]["recall@5"])
        row += [s["by_bucket"]["1-3"]["recall@5"], s["by_bucket"]["4+"]["recall@5"],
                s["by_bucket"]["4+"]["coverage@5"], s["by_persona"]["all"]["mrr"],
                s["by_persona"]["all"]["p95_ms"]]
        rows.append(row)
    out += table(["Variant", "R@5 ai_ml", "R@5 web", "R@5 data", "R@5 1-3 req", "R@5 4+ req",
                  "Coverage@5 4+ req", "MRR", "p95 ms"], rows) + "\n"
    ht = rag.get("hypothesis_tests")
    if ht:
        out += "### Paired Recall@5 difference against V0 (bootstrap 95 percent CI)\n\n"
        rows = []
        for k, t in ht.items():
            rows.append([k, t["4+"]["delta"], f"{t['4+']['ci95'][0]:.3f} to {t['4+']['ci95'][1]:.3f}", t["4+"]["n"],
                         t["1-3"]["delta"], f"{t['1-3']['ci95'][0]:.3f} to {t['1-3']['ci95'][1]:.3f}", t["1-3"]["n"]])
        out += table(["Comparison", "4+ delta", "4+ CI", "4+ n", "1-3 delta", "1-3 CI", "1-3 n"], rows) + "\n"
    return out


def ablation() -> str:
    ab = load("ablation")
    out = "## Ablation, one component removed at a time\n\n"
    if ab is None:
        return out + f"{NM} (evals/results/ablation.json does not exist).\n\n"
    out += f"Best pipeline: {ab['meta']['best_pipeline']}. {ab['meta']['note']}.\n\n"
    rows = []
    for k, s in ab["rows"].items():
        a = s["by_persona"]["all"]
        d = ab["delta_vs_full_recall@5"].get(k)
        rows.append([k, a["recall@5"], a["ndcg@10"], a["coverage@5"], s["by_bucket"]["4+"]["recall@5"],
                     None if d is None else d["delta"],
                     None if d is None else f"{d['ci95'][0]:.3f} to {d['ci95'][1]:.3f}", a["p95_ms"]])
    out += table(["Row", "R@5", "nDCG@10", "Coverage@5", "R@5 4+ req", "Delta R@5 vs full", "CI", "p95 ms"], rows)
    out += "\nNot run here: " + "; ".join(f"{k}: {v}" for k, v in ab["not_run"].items()) + "\n\n"
    return out


def decision() -> str:
    d = load("decision_eval")
    out = "## Decision metrics (bid or skip, scam)\n\n"
    if d is None:
        return out + f"{NM}.\n\n"
    rows = [[p, m["n"], m["bid_or_skip"]["f1"], m["scam"]["precision"], m["scam"]["recall"], m["accuracy_3way"]]
            for p, m in d.items() if isinstance(m, dict) and "bid_or_skip" in m]
    return out + "Source: evals/results/decision_eval.json\n\n" + table(
        ["Persona", "n", "Bid-or-skip F1", "Scam precision", "Scam recall", "3-way accuracy"], rows) + "\n"


def judge() -> str:
    j = load("judge_calibration")
    out = "## Judge calibration\n\n"
    if j is None:
        return out + f"{NM} (evals/results/judge_calibration.json does not exist).\n\n"
    return out + table(["Status", "n labelled", "Kappa (quadratic)", "Kappa (unweighted)", "Exact agreement",
                        "Within one point"],
                       [[j.get("status"), j.get("n_labelled"), j.get("kappa_quadratic"), j.get("kappa_unweighted"),
                         j.get("exact_agreement"), j.get("within_one")]]) + "\n"


def main() -> None:
    parts = ["# Results tables\n\nGenerated by scripts/render_tables.py from evals/results/*.json. Do not edit by hand.\n",
             "[//]: # (results:start)\n", b5(), rag_detail(), ablation(), decision(), judge(),
             generic("proposal_eval", "Proposal eval (unsupported claims, judge, latency, cost)"),
             generic("gigsim_outcomes", "GigSim reply and hire rate"),
             generic("arch_compare", "Architecture comparison (ReAct vs supervisor vs graph)"),
             generic("model_compare", "Model configuration comparison"),
             generic("injection_eval", "Prompt injection attack success rate"),
             generic("tool_design", "Tool design study"),
             generic("x2_experiment", "Extension X2, proposal strategy A/B test"),
             "[//]: # (results:end)\n"]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
