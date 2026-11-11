import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from gigsim import generate
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag.retriever import get_retriever


@pytest.fixture
async def env():
    generate.build()
    from gigsim.app import app, store
    store.reset()
    mp = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app))
    jobs = await mp.search_jobs(limit=400, persona="ai_ml")
    return mp, jobs, build_bid_graph(MemorySaver())


def cfg(mp, tid):
    return {"configurable": {"thread_id": tid, "marketplace": mp,
                             "retriever": get_retriever("v2_hybrid", "ai_ml")}}


async def run(graph, mp, job_id, tid):
    return await graph.ainvoke({"job_id": job_id}, cfg(mp, tid))


async def test_scam_is_skipped_and_nothing_sent(env):
    mp, jobs, g = env
    scam = next(j for j in jobs if "unpaid_work" in j["warning_signals"])
    out = await run(g, mp, scam["job_id"], "t-scam")
    assert out["decision"]["action"] == "skip"
    assert "__interrupt__" not in out
    assert await mp._req("GET", "/proposals") == []


async def test_approval_interrupts_then_submits_exactly_once(env):
    mp, jobs, g = env
    for j in jobs:
        out = await run(g, mp, j["job_id"], f"t-{j['job_id']}")
        if "__interrupt__" in out:
            break
    else:
        pytest.fail("no job reached approval")
    assert await mp._req("GET", "/proposals") == []  # nothing sent before approval
    payload = out["__interrupt__"][0].value
    assert payload["dry_run"]["dry_run"] and payload["evidence"]
    tid = f"t-{j['job_id']}"
    done = await g.ainvoke(Command(resume={"action": "approve"}), cfg(mp, tid))
    assert done["outcome"]["status"] in ("submitted", "replied")
    await g.ainvoke(Command(resume={"action": "approve"}), cfg(mp, tid))
    assert len(await mp._req("GET", "/proposals")) == 1


async def test_reject_sends_nothing_and_banned_edit_blocked(env):
    mp, jobs, g = env
    for j in jobs:
        out = await run(g, mp, j["job_id"], f"r-{j['job_id']}")
        if "__interrupt__" in out:
            break
    tid = f"r-{j['job_id']}"
    res = await g.ainvoke(Command(resume={"action": "edit", "text": "I guarantee results"}),
                          cfg(mp, tid))
    assert res["approval"]["action"] == "reject"
    assert await mp._req("GET", "/proposals") == []


async def test_injected_text_never_reaches_draft(env):
    mp, jobs, g = env
    inj = [j for j in jobs if "prompt_injection" in j["warning_signals"] or "ignore all" in j["description"].lower()]
    assert inj
    for j in inj[:10]:
        out = await run(g, mp, j["job_id"], f"i-{j['job_id']}")
        draft = out.get("proposal_draft", {}).get("cover_letter", "")
        assert "google" not in draft.lower() and "phd" not in draft.lower()
