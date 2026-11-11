"""Retriever factory. Every retriever exposes search(requirement, k, filters) -> list[evidence dict].

Callers: mcp_servers/portfolio and agent nodes call get_retriever(variant, persona).
"""
from __future__ import annotations

from rag.index.corpus import Corpus, get_corpus
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
