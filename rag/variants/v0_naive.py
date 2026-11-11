"""V0: naive dense retrieval, top-k cosine over fixed chunks.

Vectors are TF-IDF for now so tests need no model server; swap in Ollama embeddings via config.
"""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class V0Naive:
    name = "v0_naive"

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.m = self.vec.fit_transform([c["text"] for c in chunks])

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        q = self.vec.transform([requirement])
        sims = (self.m @ q.T).toarray().ravel()
        out = []
        for i in np.argsort(-sims):
            c = self.chunks[i]
            if filters and any(c.get(f) != v for f, v in filters.items()):
                continue
            out.append({**c, "score": float(sims[i])})
            if len(out) >= k:
                break
        return out
