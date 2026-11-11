"""V0b: TF-IDF cosine. This is what the first pass called V0; kept for transparency and as a
dependency free baseline (no embedding model needed)."""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from rag.index.corpus import Corpus, ranked_unique


class V0bTfidf:
    name = "v0b_tfidf"

    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.m = self.vec.fit_transform([c["text"] for c in corpus.chunks])

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        sims = (self.m @ self.vec.transform([requirement]).T).toarray().ravel()
        out = []
        for eid, sc in ranked_unique(np.argsort(-sims), sims, self.corpus.chunk_ids, len(self.corpus.items)):
            item = self.corpus.by_id[eid]
            if filters and any(item.get(f) != v for f, v in filters.items()):
                continue
            out.append({**item, "score": sc})
            if len(out) >= k:
                break
        return out
