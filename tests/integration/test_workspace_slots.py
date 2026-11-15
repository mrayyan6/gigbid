"""Interview slots: the Workspace MCP server is used for free slots, and a failure degrades to a reply without slots."""
import pytest

from agent.mcp_workspace import MCPWorkspace, WorkspaceUnavailable
from agent.nodes.config import CFG
from tests.integration.api_helpers import (
    boot,
    client,
    find_bid_run,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
)


async def test_client_reads_free_slots_from_the_real_workspace_server_over_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path / "ws.json"))
    monkeypatch.delenv("WORKSPACE_MCP_URL", raising=False)
    ws = MCPWorkspace(retries=0, timeout_s=60)
    slots = await ws.free_slots("2026-11-16", "2026-11-16", 30)
    assert len(slots) >= 10 and slots[0] == {"start": "2026-11-16T09:00", "end": "2026-11-16T09:30"}
    with pytest.raises(WorkspaceUnavailable):
        await ws.call("delete_everything", {})  # not on the allowlist


async def test_unreachable_server_raises_workspace_unavailable():
    async def broken(tool, args):
        raise ConnectionError("down")
    with pytest.raises(WorkspaceUnavailable):
        await MCPWorkspace(caller=broken, retries=1, backoff_s=0, timeout_s=1).free_slots("2026-11-16", "2026-11-16")


class FakeWorkspace:
    def __init__(self, slots=None, fail=False):
        self.slots, self.fail, self.calls = slots or [], fail, 0

    async def free_slots(self, date_from, date_to, duration_min=30):
        self.calls += 1
        if self.fail:
            raise WorkspaceUnavailable("down")
        return self.slots


async def _client_asks_for_a_call(c, app, h, gs):
    run = await find_bid_run(c, h)
    tid = run["thread_id"]
    assert (await c.post(f"/api/approvals/{tid}", json={"action": "approve"}, headers=h)).status_code == 200
    cid = (await c.get(f"/api/runs/{tid}", headers=h)).json()["job"]["client_id"]
    gs.store.messages[cid].append({"message_id": "m-call", "client_id": cid, "job_id": run["job_id"],
                                   "from": "client", "text": "Looks good, are you free for a video call tomorrow?"})
    return cid


async def test_interview_request_offers_slots_from_the_workspace_and_degrades_without_them(
        tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    try:
        async with client(app) as c:
            h = await make_user(app, "slots@example.com")
            cid = await _client_asks_for_a_call(c, app, h, gigsim_up)

            app.state.ctx.workspace = FakeWorkspace([
                {"start": "2026-11-16T10:00", "end": "2026-11-16T10:30"},
                {"start": "2026-11-16T11:00", "end": "2026-11-16T11:30"}])
            d = (await c.post(f"/api/messages/{cid}/draft", json={}, headers=h)).json()
            assert d["intent"] == "interview_request"
            assert [s["start"] for s in d["slots"]] == ["2026-11-16T10:00", "2026-11-16T11:00"]
            assert "2026-11-16 10:00" in d["draft"] and "2026-11-16 11:00" in d["draft"]

            # the workspace is down: a draft without slots, not an error
            app.state.ctx.workspace = FakeWorkspace(fail=True)
            d = (await c.post(f"/api/messages/{cid}/draft", json={}, headers=h)).json()
            assert d["intent"] == "interview_request" and d["slots"] == [] and d["draft"]

            # no workspace configured at all behaves the same
            app.state.ctx.workspace = None
            d = (await c.post(f"/api/messages/{cid}/draft", json={}, headers=h)).json()
            assert d["slots"] == [] and d["draft"] == CFG["conversation"]["templates"]["interview_no_slots"]
    finally:
        await cm.__aexit__(None, None, None)
