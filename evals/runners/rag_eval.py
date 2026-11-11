"""Retrieval metrics per variant and persona against gold evidence.

Gold for a requirement = persona portfolio items whose skills include it. Queries are the
natural-language requirement phrase, so lexical overlap with the gold label is not trivial.
Run: python -m evals.runners.rag_eval  -> evals/results/rag_eval.json
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from gigsim.generate import PERSONAS, build
from rag.ingest.load import load_portfolio
from rag.retriever import VARIANTS

OUT = Path(__file__).resolve().parents[1] / "results"


def metrics(ranked: list[str], gold: set[str]) -> tuple[float, float, float]:
    rec = len(set(ranked[:5]) & gold) / len(gold)
    rr = next((1 / (i + 1) for i, x in enumerate(ranked) if x in gold), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(ranked[:10]) if x in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    return rec, rr, dcg / idcg


def run() -> dict:
    build()
    res: dict = {}
    for variant, factory in VARIANTS.items():
        per = {}
        for persona, p in PERSONAS.items():
            chunks = load_portfolio(persona)
            r = factory(chunks)
            rows, lat = [], []
            for skill in p["skills"]:
                gold = {c["evidence_id"] for c in chunks if skill in c["skills"]}
                if not gold:
                    continue
                q = f"We need someone with hands-on experience in {skill} for a client project"
                t = time.perf_counter()
                ranked = [x["evidence_id"] for x in r.search(q, k=10)]
                lat.append((time.perf_counter() - t) * 1000)
                rows.append(metrics(ranked, gold))
            n = len(rows)
            per[persona] = {"recall@5": sum(x[0] for x in rows) / n, "mrr": sum(x[1] for x in rows) / n,
                            "ndcg@10": sum(x[2] for x in rows) / n, "n_queries": n,
                            "p95_ms": sorted(lat)[int(0.95 * (len(lat) - 1))]}
        res[variant] = per
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rag_eval.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    for v, per in run().items():
        print(v, {k: round(m["recall@5"], 3) for k, m in per.items()})
