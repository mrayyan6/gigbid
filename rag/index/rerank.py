"""Cross-encoder reranker (fastembed TextCrossEncoder, open model, CPU)."""
from __future__ import annotations

from functools import lru_cache

from rag.config import cfg


@lru_cache(maxsize=1)
def _encoder():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    c = cfg()["reranker"]
    try:
        return TextCrossEncoder(c["model"]), c["model"]
    except Exception:  # model download or load failure: use the declared fallback, never fail silently
        return TextCrossEncoder(c["fallback_model"]), c["fallback_model"]


def model_name() -> str:
    return _encoder()[1]


_CACHE: dict[tuple[str, str], float] = {}


def clear_cache() -> None:
    _CACHE.clear()


def score(query: str, passages: list[str]) -> list[float]:
    """Cross-encoder logits, memoised on (query, passage). Requirement strings repeat across jobs,
    so latency numbers reflect warm repeats within one variant run."""
    miss = [p for p in dict.fromkeys(passages) if (query, p) not in _CACHE]
    if miss:
        for p, s in zip(miss, _encoder()[0].rerank(query, miss)):
            _CACHE[(query, p)] = float(s)
    return [_CACHE[(query, p)] for p in passages]
