"""Marketplace outage: allowlists, bounded retries, degraded (queued) threads and recovery.

The graph reaches the marketplace only through MCPMarketplace, which talks to the Marketplace MCP
server over an in-memory session. A switchable adapter plays the role of the killed server.
"""
import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from mcp.shared.memory import create_connected_server_and_client_session as connect

from agent.graphs.bid_graph import build_bid_graph
from agent.marketplace_port import MarketplaceUnavailable, ToolNotAllowed
from agent.mcp_client import MCPMarketplace
from gigsim import generate
from mcp_servers.marketplace import server
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag.retriever import get_retriever

ALLOW = {"scout": ["get_job"], "graph": ["search_jobs", "get_job", "get_client_history",
                                          "get_policy", "get_connects_balance",
                                          "submit_proposal", "send_message"]}


class Switchable:
    """Adapter proxy that behaves like a dead marketplace while `down` is true."""

    def __init__(self, inner):
        self.inner, self.down, self.writes_down = inner, False, False

    def __getattr__(self, name):
        fn = getattr(self.inner, name)

        async def call(*a, **k):
            real_write = name == "create_proposal" and not k.get("dry_run")
            if self.down or (self.writes_down and real_write):
                raise MarketplaceUnavailable("connection refused")
            return await fn(*a, **k)
        return call


def caller():
    async def call(tool, args):
        async with connect(server.mcp._mcp_server) as s:
            return await s.call_tool(tool, args)
    return call


@pytest.fixture
async def env(tmp_path):
    generate.build()
    from gigsim.app import app, store
    store.reset()
    raw = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app), retries=1)
    sw = Switchable(raw)
    server.configure(adapter=sw, audit_path=tmp_path / "audit.jsonl", rate_per_min=10000)
    mp = MCPMarketplace(caller(), allowlists=ALLOW, retries=1, backoff_s=0.01, timeout_s=10)
    jobs = await raw.search_jobs(limit=400, persona="ai_ml")
    yield raw, sw, mp, jobs
    server.configure()


def cfg(mp, tid):
    return {"configurable": {"thread_id": tid, "marketplace": mp,
                             "retriever": get_retriever("v2_hybrid", "ai_ml")}}


async def test_allowlist_blocks_tool_outside_agent_list(env):
    _, _, mp, jobs = env
    scout = mp.as_agent("scout")
    assert (await scout.get_job(jobs[0]["job_id"]))["job_id"] == jobs[0]["job_id"]
    with pytest.raises(ToolNotAllowed):
        await scout.send_message("c001", "hi", "key-allowlist-1")
    with pytest.raises(ToolNotAllowed):
        await scout.get_policy()


async def test_calls_through_mcp_return_plain_data(env):
    _, _, mp, jobs = env
    assert isinstance(await mp.search_jobs(limit=3), list)
    assert (await mp.get_connects_balance())["balance"] > 0
    pre = await mp.create_proposal({"job_id": jobs[0]["job_id"], "cover_letter": "hi",
                                    "bid_amount": 10}, "idem-key-00001", dry_run=True)
    assert pre["dry_run"] and "would_send" in pre


async def test_outage_raises_marketplace_unavailable_after_bounded_retries(env):
    _, sw, mp, jobs = env
    sw.down = True
    with pytest.raises(MarketplaceUnavailable):
        await mp.get_job(jobs[0]["job_id"])


async def test_scout_outage_queues_thread_then_recovers(env):
    raw, sw, mp, jobs = env
    g = build_bid_graph(MemorySaver())
    sw.down = True
    out = await g.ainvoke({"job_id": jobs[0]["job_id"]}, cfg(mp, "t-down"))
    assert out["status"] == "queued" and out["queue"][0]["node"] == "scout"
    assert "__interrupt__" not in out and await raw.list_messages() == []
    assert await raw._req("GET", "/proposals") == []
    sw.down = False  # recovery: re-run the queued job on a fresh thread
    for j in jobs:
        out = await g.ainvoke({"job_id": j["job_id"]}, cfg(mp, f"t-up-{j['job_id']}"))
        if "__interrupt__" in out:
            break
    assert "__interrupt__" in out and out.get("status") != "queued"


async def test_submit_outage_sends_nothing_then_submits_exactly_once(env):
    raw, sw, mp, jobs = env
    g = build_bid_graph(MemorySaver())
    for j in jobs:
        tid = f"t-{j['job_id']}"
        out = await g.ainvoke({"job_id": j["job_id"]}, cfg(mp, tid))
        if "__interrupt__" in out:
            break
    else:
        pytest.fail("no job reached approval")
    sw.writes_down = True  # the server dies after the human approved, before the send
    out = await g.ainvoke(Command(resume={"action": "approve"}), cfg(mp, tid))
    assert out["status"] == "queued" and out["queue"][-1]["node"] == "submit"
    sw.writes_down = False
    assert await raw._req("GET", "/proposals") == []
    await g.aupdate_state(cfg(mp, tid), {"status": "running"})
    done = await g.ainvoke(Command(goto="submit"), cfg(mp, tid))
    assert done["outcome"]["status"] in ("submitted", "replied")
    await g.aupdate_state(cfg(mp, tid), {"status": "running"})
    await g.ainvoke(Command(goto="submit"), cfg(mp, tid))  # a duplicate retry is a no-op replay
    assert len(await raw._req("GET", "/proposals")) == 1
