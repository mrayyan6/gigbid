import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.workspace.server import mcp


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path / "workspace.json"))
    return tmp_path / "workspace.json"


def ok(res):
    assert not res.isError, res.content
    return res.structuredContent


async def test_tools_and_annotations():
    async with connect(mcp._mcp_server) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert set(tools) == {"free_slots", "hold_interview", "draft_email"}
        assert tools["free_slots"].annotations.readOnlyHint is True
        assert tools["hold_interview"].annotations.idempotentHint is True
        assert tools["draft_email"].annotations.destructiveHint is False
        assert "idempotency_key" in tools["hold_interview"].inputSchema["required"]


async def test_free_slots_inside_working_hours_skip_weekends():
    async with connect(mcp._mcp_server) as s:
        # 2026-11-14 is a Saturday, 2026-11-16 a Monday
        out = ok(await s.call_tool("free_slots", {"date_from": "2026-11-14",
                                                  "date_to": "2026-11-16", "duration_min": 60}))
        assert out["slots"][0] == "2026-11-16T09:00"
        assert out["slots"][-1] <= "2026-11-16T16:00"


async def test_hold_removes_slot_and_is_idempotent():
    async with connect(mcp._mcp_server) as s:
        slot = ok(await s.call_tool("free_slots", {"date_from": "2026-11-16",
                                                   "date_to": "2026-11-16"}))["slots"][0]
        args = {"slot": slot, "client_id": "c001", "idempotency_key": "hold-key-0001"}
        a = ok(await s.call_tool("hold_interview", args))
        b = ok(await s.call_tool("hold_interview", args))
        assert a["hold_id"] == b["hold_id"] and b["idempotent_replay"]
        after = ok(await s.call_tool("free_slots", {"date_from": "2026-11-16",
                                                    "date_to": "2026-11-16"}))["slots"]
        assert slot not in after
        clash = await s.call_tool("hold_interview", {**args, "idempotency_key": "hold-key-0002"})
        assert clash.isError


async def test_dry_run_stores_nothing(store):
    async with connect(mcp._mcp_server) as s:
        h = ok(await s.call_tool("hold_interview", {"slot": "2026-11-16T09:00", "client_id": "c1",
                                                    "idempotency_key": "hold-key-0003",
                                                    "dry_run": True}))
        d = ok(await s.call_tool("draft_email", {"to": "a@b.com", "subject": "s", "body": "b",
                                                 "dry_run": True}))
        assert h["dry_run"] and d["dry_run"] and not store.exists()


async def test_email_draft_is_stored_never_sent(store):
    async with connect(mcp._mcp_server) as s:
        d = ok(await s.call_tool("draft_email", {"to": "a@b.com", "subject": "Hi", "body": "Body"}))
        assert d["status"] == "draft"
        again = ok(await s.call_tool("draft_email", {"to": "a@b.com", "subject": "Hi",
                                                     "body": "Body"}))
        assert again["draft_id"] == d["draft_id"]
    assert len(json.loads(store.read_text(encoding="utf-8"))["drafts"]) == 1
