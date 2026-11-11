"""Render docs/results_tables.md from evals/results/*.json. README and report paste from that file only.

Every number printed here is read from a results file, never typed. A missing file prints "not run".
Run: python scripts/render_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evals" / "results"
OUT = ROOT / "docs" / "results_tables.md"


def load(name: str):
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def f(x, nd=3):
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int, float)):
        return f"{x:.{nd}f}"
    return str(x)


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def b5() -> str:
    rag, prop = load("rag_eval"), load("proposal_eval")
    if not rag:
        return "not run (evals/results/rag_eval.json missing)\n"
    best = (prop or {}).get("meta", {}).get("best_variant")
    names = ["v0_naive"] + ([best] if best and best != "v0_naive" else [])
    rows = []
    for v in names:
        m = rag["variants"][v]["by_persona"]["all"]
        p = (prop or {}).get(v) or {}
        rows.append([v, f(m["recall@5"]), f(m["ndcg@10"]), f(p.get("unsupported_per_proposal")),
                     f(p.get("judge_score"), 2), f(p.get("reply_rate"), 2), f(p.get("p95_latency_s"), 1),
                     f(p.get("cost_per_proposal_usd"), 5)])
    head = ["Variant", "Evidence Recall@5", "nDCG@10", "Unsupported claims per proposal (after verifier)",
            "Judge score (uncalibrated)", "GigSim reply rate", "p95 latency s", "Cost per proposal USD"]
    note = ""
    if prop:
        note = (f"\nProposal columns: n = {prop['v0_naive']['n_proposals']} per variant, model "
                f"{prop['meta']['models'].get('writer')}, profile {prop['meta'].get('profile')}. "
                "Source: evals/results/rag_eval.json and evals/results/proposal_eval.json.\n")
    return table(head, rows) + note


def retrieval() -> str:
    rag = load("rag_eval")
    if not rag:
        return "not run\n"
    rows = []
    for v, d in rag["variants"].items():
        a, b = d["by_persona"]["all"], d["by_bucket"].get("4+", {})
        rows.append([v, f(a["recall@5"]), f(a["recall@5_capped"]), f(a["mrr"]), f(a["ndcg@10"]),
                     f(b.get("recall@5")), f(a["p95_ms"], 1)])
    head = ["Variant", "Recall@5", "Recall@5 capped", "MRR", "nDCG@10", "Recall@5 (4+ requirements)", "p95 ms"]
    return table(head, rows) + f"\nn jobs = {rag['meta']['n_jobs']}. Source: evals/results/rag_eval.json.\n"


def by_persona() -> str:
    rag = load("rag_eval")
    if not rag:
        return "not run\n"
    rows = []
    for v, d in rag["variants"].items():
        rows.append([v] + [f(d["by_persona"][p]["recall@5"]) for p in ("ai_ml", "web", "data")])
    return table(["Variant", "ai_ml", "web", "data"], rows) + "\nRecall@5 by persona. Source: evals/results/rag_eval.json.\n"


def ablation() -> str:
    ab = load("ablation")
    if not ab:
        return "not run\n"
    rows = []
    for name, d in ab["rows"].items():
        a = d["by_persona"]["all"]
        rows.append([name, f(a["recall@5"]), f(a["mrr"]), f(a["ndcg@10"]), f(d["by_bucket"]["4+"]["recall@5"])])
    return (table(["Pipeline", "Recall@5", "MRR", "nDCG@10", "Recall@5 4+"], rows)
            + f"\nBest pipeline {ab['meta']['best_pipeline']}, n = {ab['meta']['n_jobs']}. "
            "Source: evals/results/ablation.json.\n")


def decision() -> str:
    d = load("decision_eval")
    if not d:
        return "not run\n"
    rows = []
    for p in ("ai_ml", "web", "data"):
        x = d[p]
        rows.append([p, x["n"], f(x["bid_or_skip"]["precision"], 2), f(x["bid_or_skip"]["recall"], 2),
                     f(x["bid_or_skip"]["f1"], 2), f(x["scam"]["precision"], 2), f(x["scam"]["recall"], 2)])
    return (table(["Persona", "n", "Bid P", "Bid R", "Bid F1", "Scam P", "Scam R"], rows)
            + "\nScam precision and recall are circular (synthetic scam templates match the risk patterns), see "
              "docs/DATA_CARD.md. Source: evals/results/decision_eval.json.\n")


def injection() -> str:
    d = load("injection_eval")
    if not d:
        return "not run\n"
    rows = []
    for k, label in (("defences_off", "off"), ("defences_on", "on")):
        o = d[k]["overall"]
        rows.append([label, o["n"], o["successes"], f(o["asr"], 2), f"{o['ci95'][0]:.2f} to {o['ci95'][1]:.2f}",
                     o["writer_followed"]])
    return (table(["Defences", "n", "Attack successes", "ASR", "95% CI", "Writer followed instruction"], rows)
            + f"\nWriter model {d['meta']['model_writer']}. Source: evals/results/injection_eval.json.\n")


def tool_design() -> str:
    d = load("tool_design")
    if not d:
        return "not run\n"
    rows = []
    for k, v in d["results"].items():
        rows.append([k, v["n_tools"], f(v["tool_selection_accuracy"], 3), f(v["arg_accuracy_overall"], 3),
                     f(v["tokens_per_task"]["total"], 0)])
    return (table(["Tool set", "Tools", "Selection accuracy", "Argument accuracy", "Tokens per task"], rows)
            + f"\nModel {d['meta']['model']}, n = {d['meta']['n_tasks']} tasks. Source: evals/results/tool_design.json.\n")


def arch() -> str:
    d = load("arch_compare")
    if not d:
        return "not run\n"
    rows = []
    for a, v in d["results"].items():
        o = v["overall"]
        rows.append([a, o.get("bid_or_skip_accuracy"), f(o.get("bid_f1"), 2),
                     f(o.get("unsupported_claims_final_per_letter"), 2), o.get("violating_letters_shipped"),
                     f(o.get("reply_rate_expected_per_submitted"), 3), f(o.get("tokens_per_job_mean"), 0),
                     f(o.get("latency_s_p50"), 1)])
    head = ["Architecture", "Bid-or-skip acc", "Bid F1", "Unsupported per letter", "Violating letters shipped",
            "Expected reply prob", "Tokens per job", "p50 latency s"]
    return (table(head, rows) + f"\nSource: evals/results/arch_compare.json. meta: "
            f"{json.dumps({k: v for k, v in d['meta'].items() if k in ('n_jobs_completed', 'model', 'n')})}\n")


def models() -> str:
    d = load("model_compare")
    if not d:
        return "not run\n"
    rows = [[r.get("config"), r.get("model"), r.get("n"), f(r.get("judge_score"), 2),
             f(r.get("unsupported_per_proposal"), 2), f(r.get("p50_latency_s"), 1), f(r.get("tokens_per_s"), 1),
             f(r.get("cost_per_proposal_usd"), 5)] for r in d.get("configs", [])]
    return (table(["Config", "Writer model", "n", "Judge", "Unsupported", "p50 latency s", "tokens/s",
                   "USD per proposal"], rows) + "\nSource: evals/results/model_compare.json.\n")


def x2() -> str:
    d = load("x2_experiment")
    if not d:
        return "not run\n"
    t = d.get("test_reply_rate", {})
    rows = [[k, d[k]["n"], d[k]["replies"], f(d[k].get("reply_rate"), 3)] for k in ("A", "B")]
    return (table(["Strategy", "n", "Replies", "Reply rate"], rows)
            + f"\nTwo proportion test: {json.dumps(t)}\nSource: evals/results/x2_experiment.json.\n")


def change_request() -> str:
    d = load("change_request")
    if not d:
        return "not run\n"
    return "```json\n" + json.dumps({k: v for k, v in d.items() if k != "diff"}, indent=1) + "\n```\nSource: evals/results/change_request.json.\n"


def main() -> None:
    parts = [("Main results table (B5)", b5()), ("Retrieval variants", retrieval()),
             ("Recall@5 by persona", by_persona()), ("Ablation, one component removed", ablation()),
             ("Bid or skip decisions", decision()), ("Prompt injection attack success rate", injection()),
             ("R&D A: tool design", tool_design()), ("R&D C: architecture comparison", arch()),
             ("Two LLM configurations", models()), ("Extension X2: proposal strategy A/B", x2()),
             ("Change request", change_request())]
    text = ("# Results tables\n\nGenerated by `scripts/render_tables.py` from `evals/results/*.json`. "
            "Do not edit by hand.\n\n" + "\n".join(f"## {h}\n\n{b}" for h, b in parts))
    OUT.write_text(text, encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
