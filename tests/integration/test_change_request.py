"""Platform policy update v2 (self imposed change request), absorbed through config only.

Policy v2 (data/policy_pack/gigsim_policy.json): Connects x1.5, minimum budget 50 USD, boost fee 2 Connects,
no external links except portfolio links. No node code reads these literals, nodes call get_policy().
"""
import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver

from agent.graphs.bid_graph import build_bid_graph
from agent.nodes import core
from gigsim import generate
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag.retriever import get_retriever

pytestmark = pytest.mark.live_policy


@pytest.fixture
async def env():
    generate.build()
    from gigsim.app import app, store
    store.reset()
    mp = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app))
    return mp, store, build_bid_graph(MemorySaver())


def cfg(mp, tid):
    return {"configurable": {"thread_id": tid, "marketplace": mp,
                             "retriever": get_retriever("v2_hybrid", "ai_ml")}}


async def test_policy_version_2_is_served(env):
    mp, _, _ = env
    pol = await mp.get_policy()
    assert pol["version"] == 2 and pol["connects_multiplier"] == 1.5 and pol["min_budget_usd"] == 50


async def test_job_under_minimum_budget_is_skipped(env):
    mp, store, g = env
    jobs = await mp.search_jobs(limit=400, persona="ai_ml")
    good = next(j for j in jobs if not j["warning_signals"])
    store.jobs[good["job_id"]]["budget"] = {"min": 20, "max": 40}
    out = await g.ainvoke({"job_id": good["job_id"]}, cfg(mp, "t-cr-min"))
    assert out["decision"]["action"] == "skip"
    assert "below platform minimum" in out["decision"]["reason"]
    assert await mp._req("GET", "/proposals") == []


async def test_dry_run_cost_reflects_multiplier_and_boost_fee(env):
    mp, store, _ = env
    jobs = await mp.search_jobs(limit=400, persona="ai_ml")
    j = next(x for x in jobs if x["budget"]["max"] >= 50)
    raw = store.jobs[j["job_id"]]["connects_cost"]
    res = await mp.create_proposal({"job_id": j["job_id"], "bid_amount": j["budget"]["max"],
                                    "cover_letter": "A short honest letter."}, "k-cr-dry", dry_run=True)
    assert res["connects_cost"] == round(raw * 1.5) + 2


async def test_external_link_blocked_by_compliance(env):
    mp, _, _ = env
    pol = await mp.get_policy()
    assert core.violations("See my work at https://example.com/me", pol)
    assert not core.violations("See my work at https://portfolio.example.com/case", pol)
