"""Retriever factory. Every retriever exposes search(requirement, k, filters) -> list[evidence dict].

Callers: mcp_servers/portfolio and agent nodes call get_retriever(variant, persona).
"""
from __future__ import annotations

import time

from rag.index.corpus import Corpus, get_corpus
from rag.ingest.user_store import load_user_items, version
from rag.variants import v0_naive, v0b_tfidf, v1_decompose, v2_hybrid, v3_rerank, v8_corrective

VARIANTS = {
    "v0_naive": v0_naive.build,                       # dense, fixed chunks
    "v0b_tfidf": v0b_tfidf.V0bTfidf,                  # TF-IDF baseline (the first pass "V0")
    "v1_decompose": v1_decompose.build,
    "v2_hybrid": v2_hybrid.build,
    "v1_decompose_hybrid": lambda c: v1_decompose.build(c, hybrid=True),
    "v3_rerank": v3_rerank.build,
    "v8_corrective": v8_corrective.V8Corrective,
}

_cache: dict[tuple[str, str | None], object] = {}


def build_variant(variant: str, corpus: Corpus):
    return VARIANTS[variant](corpus)


def get_retriever(variant: str = "v2_hybrid", persona: str | None = None):
    key = (variant, persona)
    if key not in _cache:
        _cache[key] = build_variant(variant, get_corpus(persona))
    return _cache[key]


# == per user portfolios: the seeded corpus plus the user's uploads, extended incrementally ==
_user_corpora: dict[tuple[str | None, str], tuple[str, Corpus]] = {}
_user_retrievers: dict[tuple, object] = {}


def user_corpus(persona: str | None, user_id: str) -> tuple[Corpus, dict]:
    """The corpus for one user. When the user's uploads change, the previous corpus is extended with only the
    new chunks (incremental re-index). If something was removed, it restarts from the seeded corpus.
    Returns (corpus, stats) where stats describes the last update: new_items, chunks_embedded, seconds."""
    base = get_corpus(persona)
    items = load_user_items(user_id)
    ver = version(items)
    cached = _user_corpora.get((persona, user_id))
    if cached and cached[0] == ver:
        return cached[1], {"new_items": 0, "chunks_embedded": 0, "seconds": 0.0, "user_items": len(items)}
    prev = cached[1] if cached else base
    if cached and not (set(prev.by_id) - set(base.by_id)) <= {i["evidence_id"] for i in items}:
        prev = base  # an upload was deleted: rebuild from the seeded corpus
    t0 = time.perf_counter()
    new_only = [i for i in items if i["evidence_id"] not in prev.by_id]
    corpus, n_chunks = prev.with_items(new_only)
    _user_corpora[(persona, user_id)] = (ver, corpus)
    return corpus, {"new_items": len(new_only), "chunks_embedded": n_chunks,
                    "seconds": round(time.perf_counter() - t0, 3), "user_items": len(items)}


def get_user_retriever(variant: str, persona: str | None, user_id: str):
    corpus, _ = user_corpus(persona, user_id)
    key = (variant, persona, user_id, id(corpus))
    if key not in _user_retrievers:
        for k in [k for k in _user_retrievers if k[:3] == key[:3]]:
            del _user_retrievers[k]  # drop retrievers built on the previous corpus
        _user_retrievers[key] = build_variant(variant, corpus)
    return _user_retrievers[key]
