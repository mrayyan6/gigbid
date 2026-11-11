"""Loads rag/config.yaml once. All RAG rules and thresholds come from there."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def cfg() -> dict:
    return yaml.safe_load((Path(__file__).with_name("config.yaml")).read_text(encoding="utf-8"))
