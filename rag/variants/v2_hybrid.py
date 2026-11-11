"""V2: hybrid BM25 + dense fused with reciprocal rank fusion. decompose=True gives V1+V2."""
from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from rag.variants.v0_naive import V0Naive


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", s.lower())


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    score: dict[int, float] = {}
    for r in rankings:
        for pos, i in enumerate(r):
            score[i] = score.get(i, 0) + 1 / (k + pos + 1)
    return sorted(score, key=score.get, reverse=True)


class V2Hybrid:
    name = "v2_hybrid"

    def __init__(self, chunks: list[dict], decompose: bool = False):
        self.chunks = chunks
        self.index = {c["evidence_id"]: i for i, c in enumerate(chunks)}
        self.dense = V0Naive(chunks)
        self.bm25 = BM25Okapi([_tok(c["text"]) for c in chunks])
        self.decompose = decompose

    def _queries(self, requirement: str) -> list[str]:
        if not self.decompose:
            return [requirement]
        parts = [p.strip() for p in re.split(r"[,;]|\band\b", requirement) if p.strip()]
        return parts or [requirement]

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        rankings = []
        for q in self._queries(requirement):
            rankings.append([int(i) for i in self.bm25.get_scores(_tok(q)).argsort()[::-1][:50]])
            rankings.append([self.index[x["evidence_id"]] for x in self.dense.search(q, k=50)])
        out = []
        for i in rrf(rankings):
            c = self.chunks[i]
            if filters and any(c.get(f) != v for f, v in filters.items()):
                continue
            out.append(dict(c))
            if len(out) >= k:
                break
        return out
