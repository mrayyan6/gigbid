"""Dense embeddings (fastembed, open model) with an on-disk cache under data/processed."""
from __future__ import annotations

import hashlib
from functools import lru_cache

import numpy as np

from rag.config import ROOT, cfg


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(cfg()["embedding"]["model"])


def _cache_path(kind: str, texts: list[str]):
    h = hashlib.sha256((cfg()["embedding"]["model"] + kind + "\x00".join(texts)).encode()).hexdigest()[:16]
    d = ROOT / cfg()["embedding"]["cache_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"emb_{kind}_{h}.npy"


def _normalise(m: np.ndarray) -> np.ndarray:
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)


def embed_passages(texts: list[str]) -> np.ndarray:
    p = _cache_path("passage", texts)
    if p.exists():
        return np.load(p)
    m = _normalise(np.array(list(_model().passage_embed(texts)), dtype=np.float32))
    np.save(p, m)
    return m


_QCACHE: dict[str, np.ndarray] = {}


def embed_queries(texts: list[str]) -> np.ndarray:
    """Queries are cached in memory only (they are ad hoc); corpus passages are cached on disk."""
    miss = [t for t in dict.fromkeys(texts) if t not in _QCACHE]
    if miss:
        m = _normalise(np.array(list(_model().query_embed(miss)), dtype=np.float32))
        _QCACHE.update(zip(miss, m))
    return np.stack([_QCACHE[t] for t in texts])
