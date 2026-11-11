"""Read-only Portfolio MCP server (official MCP Python SDK, FastMCP).

Tools: search_evidence, get_case_study, list_skills. Resources: portfolio://case/{id},
portfolio://proposal/{id}. Prompts: answer_screening_question, map_requirements_to_evidence.

Run: gigbid-portfolio-mcp            (stdio, console script)
     python -m mcp_servers.portfolio.server [--http]
Env: PORTFOLIO_DATA (directory with portfolio.json; default repo data, else generated into a user
cache dir), PORTFOLIO_PERSONA (default ai_ml), RAG_VARIANT (default v2_hybrid).
"""
from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from mcp_servers.portfolio import prompts, resources, tools

mcp = FastMCP("gigbid-portfolio")
tools.register(mcp)
resources.register(mcp)
prompts.register(mcp)


def main() -> None:
    tools.resolve_data_dir()  # fail fast or generate data before the first request
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")


if __name__ == "__main__":
    main()
