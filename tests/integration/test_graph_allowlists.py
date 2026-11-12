"""Per agent tool allowlists are enforced inside the graph, not only in the MCP client.

A full bid (scout to approved submit) runs through the real MCP client. Every tool call is recorded with the agent
role that made it. Each call must be inside that role's list from config, and the Compliance Guard must make none.
"""
import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from mcp.shared.memory import create_connected_server_and_client_session as connect

from agent.graphs.bid_graph import build_bid_graph
from agent.mcp_client import MCPMarketplace
from agent.nodes.config import CFG
from gigsim import generate
from mcp_servers.marketplace import server
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag.retriever import get_retriever


@pytest.fixture
async def env(tmp_path, monkeypatch):
    generate.build()
    from gigsim.app import app, store
    store.reset()
    raw = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app), retries=1)
    server.configure(adapter=raw, audit_path=tmp_path / "audit.jsonl", rate_per_min=10000)

    async def caller(tool, args):
        async with connect(server.mcp._mcp_server) as s:
            return await s.call_tool(tool, args)

    calls = []
    orig = MCPMarketplace.call

    async def recording(self, tool, args):
        calls.append((self.agent, tool))
        return await orig(self, tool, args)

    monkeypatch.setattr(MCPMarketplace, "call", recording)
    mp = MCPMarketplace(caller, retries=1, backoff_s=0.01, timeout_s=10)
    jobs = await raw.search_jobs(limit=400, persona="ai_ml")
    yield mp, jobs, calls
    server.configure()


async def test_every_node_call_stays_inside_its_role(env):
    mp, jobs, calls = env
    g = build_bid_graph(MemorySaver())
    for j in jobs:
        c = {"configurable": {"thread_id": f"t-{j['job_id']}", "marketplace": mp,
                              "retriever": get_retriever("v2_hybrid", "ai_ml")}}
        out = await g.ainvoke({"job_id": j["job_id"]}, c)
        if "__interrupt__" in out:
            await g.ainvoke(Command(resume={"action": "approve"}), c)
            break
    else:
        pytest.fail("no job reached approval")
    allow = CFG["mcp"]["allowlists"]
    assert calls, "the graph made no marketplace calls"
    for agent, tool in calls:
        assert tool in allow[agent], f"{agent} called {tool}, allowed {allow[agent]}"
    roles = {a for a, _ in calls}
    assert "compliance" not in roles, "the Compliance Guard must not use the marketplace"
    assert {"scout", "approval"} <= roles
    assert ("approval", "submit_proposal") in calls or ("approval", "create_proposal_draft") in calls
    assert "graph" not in roles, "no node may use the broad catch all allowlist"


async def test_compliance_agent_has_no_tools(env):
    mp, _, _ = env
    from agent.marketplace_port import ToolNotAllowed
    with pytest.raises(ToolNotAllowed):
        await mp.as_agent("compliance").get_policy()
