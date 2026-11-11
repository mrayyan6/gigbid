"""One component at a time ablation of the best retrieval pipeline.

The best pipeline is picked from evals/results/rag_eval.json (highest mean Recall@5 over all eval
jobs among the pipelines built from components; ties broken by nDCG@10). Each row removes exactly
one component. Breakdown by persona, requirement bucket and job kind comes from rag_eval.summarise.
Claim verification is an answer side component and needs LLM drafts, so it is recorded as not run here.

Run: python -m evals.runners.ablation -> evals/results/ablation.json
"""
from __future__ import annotations

import json

from evals.runners.rag_eval import RESULTS, eval_jobs, evaluate, paired_delta, summarise
from rag.variants.base import Pipeline
from rag.variants.v8_corrective import V8Corrective

# component flags of each pipeline variant
SPECS = {
    "v1_decompose_hybrid": dict(decompose=True, bm25=True, dense=True, rerank=False, corrective=False),
    "v3_rerank": dict(decompose=True, bm25=True, dense=True, rerank=True, corrective=False),
    "v8_corrective": dict(decompose=True, bm25=True, dense=True, rerank=True, corrective=True),
}


def build(spec: dict):
    def make(corpus):
        p = Pipeline(corpus, name="ablation", use_decompose=spec["decompose"], use_bm25=spec["bm25"],
                     use_dense=spec["dense"], use_rerank=spec["rerank"],
                     use_marker=spec.get("marker", True))
        return V8Corrective(corpus, base=p) if spec["corrective"] else p
    return make


def pick_best() -> str:
    rag = json.loads((RESULTS / "rag_eval.json").read_text(encoding="utf-8"))["variants"]
    cand = [v for v in SPECS if v in rag]
    return max(cand, key=lambda v: (round(rag[v]["by_persona"]["all"]["recall@5"], 6),
                                    rag[v]["by_persona"]["all"]["ndcg@10"]))


def run() -> dict:
    best = pick_best()
    spec = SPECS[best]
    jobs = eval_jobs()
    rows = {"full": evaluate(build(spec), jobs)}
    for comp in [c for c, on in spec.items() if on]:
        s = {**spec, comp: False}
        if comp == "rerank":
            s["corrective"] = False           # the corrective loop grades with rerank scores
        if not (s["bm25"] or s["dense"]):
            continue
        rows[f"no_{comp}"] = evaluate(build(s), jobs)
    if spec["decompose"]:
        # robustness: decomposition without the generator's 'Required:' marker (no oracle skill list)
        rows["no_marker"] = evaluate(build({**spec, "marker": False}), jobs)
    res = {"meta": {"best_pipeline": best, "components": spec, "n_jobs": len(jobs),
                    "note": "no_rerank also disables the corrective loop because it needs rerank scores. "
                            "no_marker keeps every component but decomposes by plain sentence and comma "
                            "splitting instead of reading the 'Required:' list, which equals the gold skills"},
           "rows": {k: summarise(v) for k, v in rows.items()},
           "delta_vs_full_recall@5": {k: paired_delta(rows["full"], v) for k, v in rows.items() if k != "full"},
           "not_run": {"no_claim_verification": "needs LLM drafts; see proposal_eval.json when it exists"}}
    (RESULTS / "ablation.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    out = run()
    print("best:", out["meta"]["best_pipeline"])
    for k, s in out["rows"].items():
        a = s["by_persona"]["all"]
        d = out["delta_vs_full_recall@5"].get(k, {}).get("delta", 0.0)
        print(f"{k:16s} R@5 {a['recall@5']:.3f} ndcg {a['ndcg@10']:.3f} cov {a['coverage@5']:.3f} delta {d:+.3f}")
