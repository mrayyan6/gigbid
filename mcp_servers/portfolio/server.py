"""Read-only Portfolio MCP server (official MCP Python SDK, FastMCP).

Run: python -m mcp_servers.portfolio.server (stdio) or add --http for streamable HTTP.
"""
from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from rag.ingest.load import load_portfolio
from rag.retriever import get_retriever

mcp = FastMCP("gigbid-portfolio")
RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
_cache: dict = {}


def _r():
    p = os.environ.get("PORTFOLIO_PERSONA", "ai_ml")
    if p not in _cache:
        _cache[p] = (get_retriever(os.environ.get("RAG_VARIANT", "v2_hybrid"), p),
                     load_portfolio(p))
    return _cache[p]


def _view(c: dict) -> dict:
    keys = ("evidence_id", "type", "title", "skills", "date", "outcome", "source", "summary")
    return {k: c[k] for k in keys if k in c}


@mcp.tool(annotations=RO)
def search_evidence(requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
    """Find portfolio evidence supporting ONE job requirement. Returns items with type, source,
    date and outcome."""
    r, _ = _r()
    return [_view(c) for c in r.search(requirement, k=min(k, 20), filters=filters)]


@mcp.tool(annotations=RO)
def get_case_study(id: str) -> dict:
    """Return the full evidence record for an evidence id."""
    _, items = _r()
    for c in items:
        if c["evidence_id"] == id:
            return _view(c)
    raise ValueError(f"unknown evidence id {id}")


@mcp.tool(annotations=RO)
def list_skills() -> list[str]:
    """List all skills the freelancer can evidence."""
    _, items = _r()
    return sorted({s for c in items for s in c["skills"]})


@mcp.resource("portfolio://case/{id}")
def case_resource(id: str) -> str:
    return str(get_case_study(id))


@mcp.prompt()
def answer_screening_question(question: str) -> str:
    """Prompt template: answer a screening question using only retrieved evidence."""
    return ("Answer the screening question using ONLY facts returned by search_evidence. "
            f"Cite evidence ids. If no evidence supports a claim, say so.\nQuestion: {question}")


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
