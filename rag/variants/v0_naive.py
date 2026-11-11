"""V0: naive dense retrieval. Fixed-size chunks, bge-small-en-v1.5 embeddings, top-k cosine."""
from __future__ import annotations

from rag.index.corpus import Corpus
from rag.variants.base import Pipeline


def build(corpus: Corpus) -> Pipeline:
    return Pipeline(corpus, name="v0_naive", use_dense=True)
