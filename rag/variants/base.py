"""Configurable retrieval pipeline. The numbered variants are thin presets of this class, and the
ablation runner switches one component off at a time.

Components: decompose (V1), bm25, dense, rerank (V3). Corrective loop (V8) wraps it in v8_corrective.py.
Interface for every variant: search(requirement, k, filters) -> list of evidence dicts.
"""
from __future__ import annotations

from rag.config import cfg
from rag.index.corpus import Corpus
from rag.index import rerank as rr
from rag.query import decompose


def rrf(rankings: list[list[str]], k: int | None = None) -> list[tuple[str, float]]:
    k = k or cfg()["fusion"]["rrf_k"]
    score: dict[str, float] = {}
    for r in rankings:
        for pos, eid in enumerate(r):
            score[eid] = score.get(eid, 0.0) + 1 / (k + pos + 1)
    return sorted(score.items(), key=lambda kv: -kv[1])


class Pipeline:
    def __init__(self, corpus: Corpus, *, name: str, use_decompose: bool = False, use_bm25: bool = False,
                 use_dense: bool = True, use_rerank: bool = False, use_marker: bool = True):
        if not (use_bm25 or use_dense):
            raise ValueError("need at least one first stage ranker")
        self.corpus, self.name = corpus, name
        self.use_decompose, self.use_bm25, self.use_dense, self.use_rerank = (
            use_decompose, use_bm25, use_dense, use_rerank)
        self.use_marker = use_marker
        self.last_requirements: list[str] = []

    def requirements(self, text: str) -> list[str]:
        return decompose(text, self.use_marker) if self.use_decompose else [text]

    def rank_requirement(self, req: str) -> list[tuple[str, float]]:
        """Ranked (evidence_id, score) for one requirement. Score is the reranker logit when
        reranking, else the fused RRF score (or the single ranker's score)."""
        n = cfg()["fusion"]["candidate_pool"]
        lists, single = [], None
        if self.use_dense:
            d = self.corpus.dense(req, n)
            lists.append([e for e, _ in d])
            single = d
        if self.use_bm25:
            b = self.corpus.lexical(req, n)
            lists.append([e for e, _ in b])
            single = b
        fused = rrf(lists) if len(lists) > 1 else single
        if not self.use_rerank:
            return list(fused)
        pool = [e for e, _ in fused[: cfg()["reranker"]["pool"]]]
        sc = rr.score(req, [self.corpus.by_id[e]["text"] for e in pool])
        return sorted(zip(pool, sc), key=lambda t: -t[1])

    def merge(self, per_req: list[list[tuple[str, float]]]) -> list[tuple[str, float]]:
        if len(per_req) == 1:
            return per_req[0]
        return rrf([[e for e, _ in r] for r in per_req])

    def finish(self, ranked: list[tuple[str, float]], k: int, filters: dict | None) -> list[dict]:
        out = []
        for eid, sc in ranked:
            item = self.corpus.by_id[eid]
            if filters and any(item.get(f) != v for f, v in filters.items()):
                continue
            out.append({**item, "score": float(sc)})
            if len(out) >= k:
                break
        return out

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        reqs = self.requirements(requirement)
        self.last_requirements = reqs
        return self.finish(self.merge([self.rank_requirement(r) for r in reqs]), k, filters)
