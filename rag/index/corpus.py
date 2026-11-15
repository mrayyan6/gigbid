"""Per persona corpus: fixed-size chunks, dense matrix, BM25 index. Built once and shared by variants."""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from rag.config import cfg
from rag.index.embed import embed_passages, embed_queries
from rag.ingest.load import load_portfolio


def tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", s.lower())


def fixed_chunks(items: list[dict]) -> list[dict]:
    """Fixed-size word windows with overlap. Short items stay a single chunk."""
    size, ov = cfg()["chunking"]["chunk_words"], cfg()["chunking"]["overlap_words"]
    out = []
    for it in items:
        words = it["text"].split()
        start = 0
        while True:
            out.append({"evidence_id": it["evidence_id"], "text": " ".join(words[start:start + size])})
            if start + size >= len(words):
                break
            start += size - ov
    return out


def ranked_unique(order: np.ndarray, scores: np.ndarray, chunk_ids: list[str], n: int) -> list[tuple[str, float]]:
    seen, out = set(), []
    for i in order:
        eid = chunk_ids[i]
        if eid in seen:
            continue
        seen.add(eid)
        out.append((eid, float(scores[i])))
        if len(out) >= n:
            break
    return out


class Corpus:
    def __init__(self, items: list[dict]):
        self.items = items
        self.by_id = {i["evidence_id"]: i for i in items}
        self.chunks = fixed_chunks(items)
        self.chunk_ids = [c["evidence_id"] for c in self.chunks]
        self.emb = embed_passages([c["text"] for c in self.chunks])
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks])

    def with_items(self, new_items: list[dict]) -> tuple[Corpus, int]:
        """Incremental re-index: a corpus that also holds new_items, without re-embedding what is already
        indexed. Only the new chunks are embedded (the expensive step); the BM25 statistics are cheap and are
        recomputed from the stored tokens. Returns (corpus, number of chunks embedded). Items already present
        are ignored, so adding the same item twice is a no-op."""
        new_items = [i for i in new_items if i["evidence_id"] not in self.by_id]
        if not new_items:
            return self, 0
        c = object.__new__(Corpus)
        c.items = self.items + new_items
        c.by_id = {i["evidence_id"]: i for i in c.items}
        fresh = fixed_chunks(new_items)
        c.chunks = self.chunks + fresh
        c.chunk_ids = self.chunk_ids + [x["evidence_id"] for x in fresh]
        c.emb = np.vstack([self.emb, embed_passages([x["text"] for x in fresh])])
        c.bm25 = BM25Okapi([tokenize(x["text"]) for x in c.chunks])
        return c, len(fresh)

    def dense(self, query: str, n: int) -> list[tuple[str, float]]:
        sims = self.emb @ embed_queries([query])[0]
        return ranked_unique(np.argsort(-sims), sims, self.chunk_ids, n)

    def lexical(self, query: str, n: int) -> list[tuple[str, float]]:
        sc = np.asarray(self.bm25.get_scores(tokenize(query)))
        return ranked_unique(np.argsort(-sc), sc, self.chunk_ids, n)

    def skills(self) -> list[str]:
        return sorted({s for i in self.items for s in i["skills"]})


@lru_cache(maxsize=8)
def get_corpus(persona: str | None) -> Corpus:
    return Corpus(load_portfolio(persona))
