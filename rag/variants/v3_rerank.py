"""V3: V1 + V2 first stage (decompose, hybrid RRF), then cross-encoder rerank per requirement."""
from __future__ import annotations

from rag.index.corpus import Corpus
from rag.variants.base import Pipeline


def build(corpus: Corpus) -> Pipeline:
    return Pipeline(corpus, name="v3_rerank", use_decompose=True, use_bm25=True, use_dense=True,
                    use_rerank=True)
