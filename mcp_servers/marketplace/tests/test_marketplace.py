import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from gigsim import generate
from mcp_servers.common import BearerAuthMiddleware, current_trace, current_user
from mcp_servers.marketplace import server
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.marketplace.audit import mask

READS = {"search_jobs", "get_job", "get_client_history", "get_connects_balance", "list_messages",
         "get_policy"}
WRITES = {"create_proposal_draft", "submit_proposal", "send_message"}


@pytest.fixture
async def env(tmp_path):
    generate.build()
    from gigsim.app import app, store
    store.reset()
    adapter = GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app), retries=1)
    audit = tmp_path / "audit.jsonl"
    server.configure(adapter=adapter, audit_path=audit, rate_per_min=1000)
    yield adapter, audit
    server.configure()


def payload(res):
    assert not res.isError, res.content
    return res.structuredContent


async def first_job(s):
    jobs = payload(await s.call_tool("search_jobs", {"limit": 1}))["result"]
    return jobs[0]


async def test_tools_listed_with_annotations_and_output_schemas(env):
    async with connect(server.mcp._mcp_server) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert set(tools) == READS | WRITES
        for n in READS:
            assert tools[n].annotations.readOnlyHint is True
        assert tools["submit_proposal"].annotations.destructiveHint is True
        assert tools["send_message"].annotations.destructiveHint is True
        assert tools["create_proposal_draft"].annotations.destructiveHint is False
        for n in WRITES:
            assert tools[n].annotations.idempotentHint is True
            assert "idempotency_key" in tools[n].inputSchema["required"]
            assert "dry_run" in tools[n].inputSchema["properties"]
        assert all(t.outputSchema for t in tools.values())


async def test_dry_run_spends_nothing_and_returns_cost(env):
    adapter, _ = env
    async with connect(server.mcp._mcp_server) as s:
        job = await first_job(s)
        before = payload(await s.call_tool("get_connects_balance", {}))["balance"]
        out = payload(await s.call_tool("submit_proposal", {
            "job_id": job["job_id"], "cover_letter": "hello", "bid_amount": 50,
            "idempotency_key": "dry-run-key-1", "dry_run": True}))
        assert out["dry_run"] and out["connects_cost"] == job["connects_cost"]
        assert out["would_send"]["cover_letter"] == "hello"
        assert payload(await s.call_tool("get_connects_balance", {}))["balance"] == before
        assert await adapter._req("GET", "/proposals") == []


async def test_same_idempotency_key_submits_once(env):
    adapter, _ = env
    args = None
    async with connect(server.mcp._mcp_server) as s:
        job = await first_job(s)
        args = {"job_id": job["job_id"], "cover_letter": "hello", "bid_amount": 50,
                "idempotency_key": "submit-key-0001"}
        a = payload(await s.call_tool("submit_proposal", args))
        b = payload(await s.call_tool("submit_proposal", args))
        assert a["proposal_id"] == b["proposal_id"] and b["idempotent_replay"]
    assert len(await adapter._req("GET", "/proposals")) == 1


async def test_draft_is_idempotent_and_sends_nothing(env):
    adapter, _ = env
    async with connect(server.mcp._mcp_server) as s:
        job = await first_job(s)
        args = {"job_id": job["job_id"], "cover_letter": "hi", "bid_amount": 10,
                "idempotency_key": "draft-key-0001"}
        a = payload(await s.call_tool("create_proposal_draft", args))
        b = payload(await s.call_tool("create_proposal_draft", args))
        assert a["draft_id"] == b["draft_id"] and b["idempotent_replay"]
    assert await adapter._req("GET", "/proposals") == []


async def test_send_message_idempotent(env):
    adapter, _ = env
    async with connect(server.mcp._mcp_server) as s:
        args = {"client_id": "c001", "text": "hello", "idempotency_key": "msg-key-00001"}
        payload(await s.call_tool("send_message", args))
        payload(await s.call_tool("send_message", args))
        listed = payload(await s.call_tool("list_messages", {"client_id": "c001"}))["result"]
        assert len(listed) == 1


async def test_audit_log_written_with_masked_pii_and_trace(env):
    _, audit = env
    tok = current_trace.set("trace-123")
    usr = current_user.set("alice")
    try:
        async with connect(server.mcp._mcp_server) as s:
            await s.call_tool("send_message", {"client_id": "c001", "text": "mail me a@b.com",
                                               "idempotency_key": "audit-key-001"})
    finally:
        current_trace.reset(tok)
        current_user.reset(usr)
    line = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
    assert line["tool"] == "send_message" and line["user"] == "alice"
    assert line["trace_id"] == "trace-123" and "a@b.com" not in json.dumps(line)


async def test_rate_limiter_rejects_burst_per_user(env):
    adapter, audit = env
    now = [0.0]
    server.configure(adapter=adapter, audit_path=audit, rate_per_min=3, clock=lambda: now[0])
    async with connect(server.mcp._mcp_server) as s:
        for _ in range(3):
            assert not (await s.call_tool("get_policy", {})).isError
        res = await s.call_tool("get_policy", {})
        assert res.isError and "rate_limited" in res.content[0].text
        now[0] += 60
        assert not (await s.call_tool("get_policy", {})).isError


def test_rate_limit_is_per_user():
    from mcp_servers.marketplace.ratelimit import RateLimited, TokenBucket
    b = TokenBucket(1, clock=lambda: 0.0)
    b.take("alice")
    with pytest.raises(RateLimited):
        b.take("alice")
    b.take("bob")


async def test_marketplace_down_maps_to_tool_error(tmp_path):
    dead = GigSimAdapter(base_url="http://127.0.0.1:9", retries=1, timeout=0.5)
    server.configure(adapter=dead, audit_path=tmp_path / "a.jsonl", rate_per_min=100)
    try:
        async with connect(server.mcp._mcp_server) as s:
            res = await s.call_tool("get_policy", {})
            assert res.isError and "marketplace_unavailable" in res.content[0].text
    finally:
        server.configure()


async def test_http_bearer_auth_required(monkeypatch, env):
    monkeypatch.setenv("MARKETPLACE_MCP_TOKEN", "s3cret-token")
    app = server.http_app()
    assert isinstance(app, BearerAuthMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.post("/mcp", json={})).status_code == 401
        bad = await c.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401


def test_mask_pii():
    out = mask({"t": "call +1 415 555 2671 or x@y.org card 4111 1111 1111 1111"})
    assert "x@y.org" not in out["t"] and "4111" not in out["t"] and "555" not in out["t"]
