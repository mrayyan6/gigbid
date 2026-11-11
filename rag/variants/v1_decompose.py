"""V1: requirement decomposition. One dense query per requirement, merged with RRF.
Set hybrid=True for the V1 + V2 combination."""
from __future__ import annotations

from rag.index.corpus import Corpus
from rag.variants.base import Pipeline


def build(corpus: Corpus, hybrid: bool = False) -> Pipeline:
    return Pipeline(corpus, name="v1_decompose_hybrid" if hybrid else "v1_decompose",
                    use_decompose=True, use_bm25=hybrid, use_dense=True)
