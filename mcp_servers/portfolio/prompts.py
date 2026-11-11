"""Prompt templates exposed by the Portfolio server."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.prompt()
    def answer_screening_question(question: str) -> str:
        """Answer a client screening question using only retrieved evidence."""
        return ("Answer the screening question using ONLY facts returned by search_evidence. "
                f"Cite evidence ids. If no evidence supports a claim, say so.\nQuestion: {question}")

    @mcp.prompt()
    def map_requirements_to_evidence(requirements: str) -> str:
        """Build a requirement to evidence table, one search_evidence call per requirement."""
        return ("For each requirement below call search_evidence once, then output a table with "
                "columns requirement, evidence_id, supported (yes, partly, no). Never invent "
                f"evidence.\nRequirements:\n{requirements}")
