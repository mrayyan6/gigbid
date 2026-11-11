import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from agent.marketplace_port import MarketplaceUnavailable
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


class PolicyProxy:
    """Delegates to the real adapter but serves a different platform policy (no file edits)."""

    def __init__(self, mp, policy):
        self._mp, self._policy = mp, policy

    async def get_policy(self):
        return self._policy

    def __getattr__(self, name):
        return getattr(self._mp, name)


async def first_approval(g, mp, jobs, prefix):
    for j in jobs:
        out = await run(g, mp, j["job_id"], f"{prefix}-{j['job_id']}")
        if "__interrupt__" in out:
            return j, out
    pytest.fail("no job reached approval")


async def test_tiny_step_budget_moves_thread_to_needs_attention(env):
    mp, jobs, g = env
    c = cfg(mp, "t-budget")
    c["configurable"]["budgets"] = {"max_steps_per_thread": 2}
    out = await g.ainvoke({"job_id": jobs[0]["job_id"]}, c)
    assert out["status"] == "needs_attention" and "budget exceeded" in out["errors"][0]
    assert "__interrupt__" not in out and await mp._req("GET", "/proposals") == []


async def test_token_budget_moves_thread_to_needs_attention(env):
    mp, jobs, g = env
    c = cfg(mp, "t-tok")
    c["configurable"]["budgets"] = {"max_tokens_per_thread": -1}
    out = await g.ainvoke({"job_id": jobs[0]["job_id"]}, c)
    assert out["status"] == "needs_attention"


async def test_policy_minimum_budget_skips_with_reason(env):
    mp, jobs, g = env
    c = cfg(PolicyProxy(mp, {"min_budget_usd": 10 ** 9, "version": 9}), "t-min")
    out = await g.ainvoke({"job_id": jobs[0]["job_id"]}, c)
    assert out["decision"]["action"] == "skip"
    assert "below platform minimum" in out["decision"]["reason"]
    assert out["status"] == "skipped"


async def test_policy_link_rule_blocks_draft_in_compliance(env):
    mp, jobs, g = env
    pol = {"banned_link_regex": r"\[ev:"}  # any evidence tag now counts as a forbidden link
    j = None
    for cand in jobs:
        out = await g.ainvoke({"job_id": cand["job_id"]}, cfg(PolicyProxy(mp, pol), f"t-l-{cand['job_id']}"))
        if out.get("decision", {}).get("action") == "bid":
            j = out
            break
    assert j and j["status"] == "blocked" and not j["compliance_verdict"]["allowed"]
    assert "__interrupt__" not in j


async def test_unavailable_marketplace_is_queued_after_retries(env):
    mp, jobs, g = env

    class Down(PolicyProxy):
        async def get_job(self, job_id):
            raise MarketplaceUnavailable("down")

    c = cfg(Down(mp, {}), "t-down")
    c["configurable"]["budgets"] = {"retry_backoff_s": 0.0}
    out = await g.ainvoke({"job_id": jobs[0]["job_id"]}, c)
    assert out["status"] == "queued" and out["queue"][0]["node"] == "scout"


async def test_node_bug_goes_to_dead_letter(env):
    mp, jobs, g = env

    class Broken(PolicyProxy):
        async def get_job(self, job_id):
            raise KeyError("boom")

    out = await g.ainvoke({"job_id": jobs[0]["job_id"]}, cfg(Broken(mp, {}), "t-dead"))
    assert out["status"] == "dead_letter" and "KeyError" in out["errors"][0]


async def test_approved_edit_feeds_style_memory_after_two_edits(env):
    mp, jobs, g = env
    from agent.memory.store import GigBidMemory
    memory = GigBidMemory(persist=False)
    for n in range(2):
        j, out = await first_approval(g, mp, jobs[n * 40:], f"m{n}")
        tid = f"m{n}-{j['job_id']}"
        draft = out["__interrupt__"][0].value["draft"]["cover_letter"]
        edited = draft.replace("I will share weekly updates", "").replace("I can deliver", "Delivery is")
        c = cfg(mp, tid)
        c["configurable"].update(memory=memory, user_id="u1")
        await g.ainvoke(Command(resume={"action": "edit", "text": edited}), c)
    notes = memory.style_notes("u1")
    assert any("i can deliver" == n["text"] for n in notes)


async def test_llm_writer_critic_and_fallback(env, monkeypatch):
    import json

    from agent import llm
    monkeypatch.setenv("LLM_ENABLED", "1")
    state = {"fail": False}

    def handler(request):
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        if state["fail"]:
            return httpx.Response(500, text="boom")
        if system.startswith("# writer"):
            ev_id = user.split("id=")[1].split(" ")[0]
            text = f"Your project is a good match. On it I used Python and the outcome was good. [ev:{ev_id}]"
        elif system.startswith("# critic"):
            text = '{"ok": true, "issues": []}'
        else:
            text = '{"deliverables": ["Build the thing"]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    llm.set_transport(httpx.MockTransport(handler))
    try:
        mp, jobs, g = env
        j, out = await first_approval(g, mp, jobs, "llm")
        letter = out["__interrupt__"][0].value["draft"]["cover_letter"]
        assert letter.startswith("Your project is a good match") and "[ev:" in letter
        snap = await g.aget_state(cfg(mp, f"llm-{j['job_id']}"))
        assert snap.values["tokens"] > 0
        assert any("llm" in t for t in snap.values["trace"])
        state["fail"] = True  # provider down: fallback model fails too, templates take over
        j2, out2 = await first_approval(g, mp, jobs, "llmfail")
        assert out2["__interrupt__"][0].value["draft"]["cover_letter"].startswith("Your ")
    finally:
        llm.set_transport(None)
