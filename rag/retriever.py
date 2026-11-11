from __future__ import annotations

from rag.ingest.load import load_portfolio
from rag.variants.v0_naive import V0Naive
from rag.variants.v2_hybrid import V2Hybrid

VARIANTS = {
    "v0_naive": lambda c: V0Naive(c),
    "v2_hybrid": lambda c: V2Hybrid(c),
    "v1_decompose_hybrid": lambda c: V2Hybrid(c, decompose=True),
}


def get_retriever(variant: str = "v2_hybrid", persona: str | None = None):
    return VARIANTS[variant](load_portfolio(persona))
