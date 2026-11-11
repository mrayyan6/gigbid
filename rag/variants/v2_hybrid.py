"""V2: hybrid BM25 + dense fused with reciprocal rank fusion, on the whole query."""
from __future__ import annotations

from rag.index.corpus import Corpus
from rag.variants.base import Pipeline


def build(corpus: Corpus) -> Pipeline:
    return Pipeline(corpus, name="v2_hybrid", use_bm25=True, use_dense=True)
