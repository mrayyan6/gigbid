"""Portfolio data access and the three read-only tools.

Data lookup order (so the published server works outside the repo layout):
1. env PORTFOLIO_DATA (a directory holding portfolio.json, or the json file itself)
2. the repo copy at data/processed/gigsim when it exists
3. generate the synthetic dataset with gigsim.generate into a per-user cache directory
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                     openWorldHint=False)
REPO_DATA = Path(__file__).resolve().parents[2] / "data" / "processed" / "gigsim"
_cache: dict = {}
_data_dir: Path | None = None


def user_cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "gigbid" / "portfolio"


def resolve_data_dir() -> Path:
    """Find or create the directory with portfolio.json. Result is cached for the process."""
    global _data_dir
    if _data_dir is not None:
        return _data_dir
    env = os.environ.get("PORTFOLIO_DATA")
    if env:
        p = Path(env)
        p = p.parent if p.is_file() else p
        if not (p / "portfolio.json").exists():
            raise FileNotFoundError(f"PORTFOLIO_DATA={env} has no portfolio.json")
        _data_dir = p
    elif (REPO_DATA / "portfolio.json").exists():
        _data_dir = REPO_DATA
    else:
        cache = user_cache_dir()
        if not (cache / "portfolio.json").exists():
            from gigsim.generate import build
            build(out_dir=cache)
        _data_dir = cache
    # the retriever factory reads rag.ingest.load.DATA, so point it at the resolved directory
    import rag.ingest.load as load_mod
    load_mod.DATA = _data_dir
    return _data_dir


def _read(name: str) -> list[dict]:
    path = resolve_data_dir() / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def retriever_and_items() -> tuple:
    from rag.ingest.load import load_portfolio
    from rag.retriever import get_retriever
    resolve_data_dir()
    persona = os.environ.get("PORTFOLIO_PERSONA", "ai_ml")
    if persona not in _cache:
        _cache[persona] = (get_retriever(os.environ.get("RAG_VARIANT", "v2_hybrid"), persona),
                           load_portfolio(persona))
    return _cache[persona]


def view(c: dict) -> dict:
    keys = ("evidence_id", "type", "title", "skills", "date", "outcome", "source", "summary")
    return {k: c[k] for k in keys if k in c}


def case_study(id: str) -> dict:
    _, items = retriever_and_items()
    for c in items:
        if c["evidence_id"] == id:
            return view(c)
    raise ValueError(f"unknown evidence id {id}")


def past_proposal(id: str) -> dict:
    for p in _read("past_proposals"):
        if p["proposal_id"] == id:
            return {k: p[k] for k in ("proposal_id", "job_id", "text", "outcome", "source")
                    if k in p}
    raise ValueError(f"unknown proposal id {id}")


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=RO)
    def search_evidence(requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        """Find portfolio evidence supporting ONE job requirement. Returns items with type,
        source, date and outcome."""
        r, _ = retriever_and_items()
        return [view(c) for c in r.search(requirement, k=min(k, 20), filters=filters)]

    @mcp.tool(annotations=RO)
    def get_case_study(id: str) -> dict:
        """Return the full evidence record for an evidence id."""
        return case_study(id)

    @mcp.tool(annotations=RO)
    def list_skills() -> list[str]:
        """List all skills the freelancer can evidence."""
        _, items = retriever_and_items()
        return sorted({s for c in items for s in c["skills"]})
