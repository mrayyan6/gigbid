"""Retrieval metrics per variant, persona, requirement-count bucket and job kind.

Query: the full dev job text (title + description), exactly what the agent sees.
Gold: the persona's portfolio items whose skill tags cover at least one required skill.
Gold circularity (disclosed in results meta): tags and chunk text come from the same synthetic
generator and chunk text contains a "Skills:" line, so lexical rankers have an easy path. The numbers
measure retrieval of tagged evidence, not human judged relevance.

Run: python -m evals.runners.rag_eval  -> evals/results/rag_eval.json
"""
from __future__ import annotations

import json
import math
import random
import statistics
import time
from pathlib import Path

from rag.config import cfg
from rag.index import embed, rerank
from rag.index.corpus import get_corpus
from rag.retriever import VARIANTS, build_variant

RESULTS = Path(__file__).resolve().parents[1] / "results"
DEV = Path(__file__).resolve().parents[1] / "datasets" / "dev_jobs.json"
PERSONAS = ("ai_ml", "web", "data")


def job_text(j: dict) -> str:
    return f"{j['title']}. {j['description']}"


def gold_for(job: dict, corpus) -> set[str]:
    req = set(job["required_skills"])
    return {i["evidence_id"] for i in corpus.items if req & set(i["skills"])}


def coverage(ranked: list[str], job: dict, corpus, k: int = 5) -> float:
    """Share of required skills (that the persona can cover at all) with an item in the top k."""
    top = [corpus.by_id[e] for e in ranked[:k]]
    coverable = [s for s in job["required_skills"] if any(s in i["skills"] for i in corpus.items)]
    if not coverable:
        return 0.0
    return sum(any(s in t["skills"] for t in top) for s in coverable) / len(coverable)


def metrics(ranked: list[str], gold: set[str]) -> dict:
    hits = len(set(ranked[:5]) & gold)
    rr = next((1 / (i + 1) for i, x in enumerate(ranked) if x in gold), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(ranked[:10]) if x in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    return {"recall@5": hits / len(gold), "recall@5_capped": hits / min(len(gold), 5), "mrr": rr,
            "ndcg@10": dcg / idcg}


def eval_jobs(persona: str | None = None) -> list[dict]:
    ex = set(cfg()["eval"]["exclude_kinds"])
    out = []
    for j in json.loads(DEV.read_text(encoding="utf-8")):
        if j["gold"]["kind"] in ex or (persona and j["gold"]["persona"] != persona):
            continue
        if gold_for(j, get_corpus(j["gold"]["persona"])):
            out.append(j)
    return out


def evaluate(make_retriever, jobs: list[dict] | None = None) -> list[dict]:
    """make_retriever(corpus) -> retriever. Returns one row per job (kept for paired statistics)."""
    jobs = jobs if jobs is not None else eval_jobs()
    embed._QCACHE.clear()            # fair latency: each variant starts with cold query caches
    rerank.clear_cache()
    retrievers, rows = {}, []
    for j in jobs:
        p = j["gold"]["persona"]
        corpus = get_corpus(p)
        if p not in retrievers:
            retrievers[p] = make_retriever(corpus)
        r = retrievers[p]
        t = time.perf_counter()
        ranked = [x["evidence_id"] for x in r.search(job_text(j), k=10)]
        ms = (time.perf_counter() - t) * 1000
        rows.append({"job_id": j["job_id"], "persona": p, "kind": j["gold"]["kind"],
                     "n_req": len(j["required_skills"]), **metrics(ranked, gold_for(j, corpus)),
                     "coverage@5": coverage(ranked, j, corpus), "ms": ms})
    evaluate.stats = {"corrective_rewrites": sum(getattr(r, "rewrites", 0) for r in retrievers.values()),
                      "corrective_queries": sum(getattr(r, "queries", 0) for r in retrievers.values())}
    return rows


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[int(q * (len(s) - 1))]


def agg(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    keys = ("recall@5", "recall@5_capped", "mrr", "ndcg@10", "coverage@5")
    out = {k: statistics.fmean(r[k] for r in rows) for k in keys}
    ms = [r["ms"] for r in rows]
    return {**out, "n": len(rows), "p50_ms": pct(ms, 0.5), "p95_ms": pct(ms, 0.95)}


def bucket(r: dict) -> str:
    return "4+" if r["n_req"] >= cfg()["eval"]["buckets"]["four_plus_min"] else "1-3"


def summarise(rows: list[dict]) -> dict:
    s: dict = {"by_persona": {p: agg([r for r in rows if r["persona"] == p]) for p in PERSONAS}}
    s["by_persona"]["all"] = agg(rows)
    s["by_bucket"] = {b: agg([r for r in rows if bucket(r) == b]) for b in ("1-3", "4+")}
    s["by_persona_bucket"] = {p: {b: agg([r for r in rows if r["persona"] == p and bucket(r) == b])
                                  for b in ("1-3", "4+")} for p in PERSONAS}
    s["by_kind"] = {k: agg([r for r in rows if r["kind"] == k]) for k in sorted({r["kind"] for r in rows})}
    return s


def paired_delta(a: list[dict], b: list[dict], metric: str = "recall@5") -> dict:
    """Mean of (b - a) over the same jobs with a bootstrap 95 percent CI."""
    d = [y[metric] - x[metric] for x, y in zip(a, b)]
    rng = random.Random(cfg()["eval"]["seed"])
    boots = sorted(statistics.fmean(rng.choices(d, k=len(d))) for _ in range(cfg()["eval"]["bootstrap_resamples"]))
    return {"delta": statistics.fmean(d), "ci95": [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]],
            "n": len(d)}


def run(variants: list[str] | None = None) -> dict:
    jobs = eval_jobs()
    names = variants or list(VARIANTS)
    all_rows, stats = {}, {}
    for v in names:
        all_rows[v] = evaluate(lambda c, v=v: build_variant(v, c), jobs)
        stats[v] = dict(evaluate.stats)
    res = {"meta": {
        "n_jobs": len(jobs),
        "n_per_persona": {p: sum(j["gold"]["persona"] == p for j in jobs) for p in PERSONAS},
        "n_4plus": {p: sum(j["gold"]["persona"] == p and len(j["required_skills"]) >= 4 for j in jobs)
                    for p in PERSONAS},
        "query": "full job text: title + description",
        "gold": "persona portfolio items whose skill tags include at least one required skill",
        "excluded_kinds": cfg()["eval"]["exclude_kinds"],
        "corpus_items_per_persona": {p: len(get_corpus(p).items) for p in PERSONAS},
        "embedding_model": cfg()["embedding"]["model"],
        "circularity_note": "Gold is skill tag membership; tags and chunk text come from one synthetic "
                            "generator and the chunk text repeats the tags, so lexical rankers have an easy "
                            "path. Larger leak: decompose() reads the literal 'Required: a, b, c.' marker "
                            "that the generator writes into every job, and that list IS the gold skill list. "
                            "V1, V3 and V8 therefore partly read the answer key. The ablation runner adds a "
                            "no_marker row (decomposition by plain sentence and comma splitting) as the "
                            "honest test of the decomposition hypothesis.",
        "chunking_note": "Portfolio items are about 30 words and chunk_words is 60, so every item is a "
                         "single chunk: fixed-size chunking is implemented but not exercised by this corpus.",
        "rerank_note": "Reranker scores are memoised per (query, passage) within a variant run, so p95 "
                       "latency reflects warm repeats of requirement strings across jobs.",
        "recall_note": "recall@5 = hits in top 5 / gold size; with gold larger than 5 the maximum is below 1. "
                       "recall@5_capped divides by min(gold size, 5). coverage@5 = share of coverable "
                       "required skills with a tagged item in the top 5.",
        "latency_note": "wall clock per search on this laptop CPU, cold query cache per variant",
    }, "variants": {v: summarise(r) for v, r in all_rows.items()}}
    if "v8_corrective" in stats:
        res["meta"]["v8_corrective_stats"] = stats["v8_corrective"]
    if "v0_naive" in all_rows:
        res["hypothesis_tests"] = {}
        for best in ("v3_rerank", "v8_corrective", "v1_decompose_hybrid", "v2_hybrid"):
            if best not in all_rows:
                continue
            a, b = all_rows["v0_naive"], all_rows[best]
            res["hypothesis_tests"][f"{best}_minus_v0_naive"] = {
                "4+": paired_delta([r for r in a if bucket(r) == "4+"], [r for r in b if bucket(r) == "4+"]),
                "1-3": paired_delta([r for r in a if bucket(r) == "1-3"], [r for r in b if bucket(r) == "1-3"]),
                "by_persona_4+": {p: paired_delta([r for r in a if r["persona"] == p and bucket(r) == "4+"],
                                                  [r for r in b if r["persona"] == p and bucket(r) == "4+"])
                                  for p in PERSONAS}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "rag_eval.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    out = run()
    for v, s in out["variants"].items():
        a = s["by_persona"]["all"]
        print(f"{v:22s} R@5 {a['recall@5']:.3f} cov@5 {a['coverage@5']:.3f} mrr {a['mrr']:.3f} "
              f"ndcg {a['ndcg@10']:.3f} 4+ R@5 {s['by_bucket']['4+']['recall@5']:.3f} p95 {a['p95_ms']:.0f}ms")
