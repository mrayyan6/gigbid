"""Resource templates: portfolio://case/{id} and portfolio://proposal/{id}."""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from mcp_servers.portfolio import tools


def register(mcp: FastMCP) -> None:
    @mcp.resource("portfolio://case/{id}", mime_type="application/json")
    def case_resource(id: str) -> str:
        """One evidence record (case study, README or review) as JSON."""
        return json.dumps(tools.case_study(id), ensure_ascii=False)

    @mcp.resource("portfolio://proposal/{id}", mime_type="application/json")
    def proposal_resource(id: str) -> str:
        """One past proposal with its outcome, as JSON."""
        return json.dumps(tools.past_proposal(id), ensure_ascii=False)
