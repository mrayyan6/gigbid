"""Crash-and-resume: a proposal waiting for approval survives an API restart and is submitted once."""
from tests.integration.api_helpers import (
    boot,
    client,
    find_bid_run,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
    wait_status,
)


async def test_pending_approval_survives_restart(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    async with client(app) as c:
        h = await make_user(app, "rev@example.test")
        run = await find_bid_run(c, h)
        tid = run["thread_id"]
        assert [a["thread_id"] for a in (await c.get("/api/approvals", headers=h)).json()] == [tid]
    await cm.__aexit__(None, None, None)  # "kill" the API

    app, cm = await boot()  # restart with same DB
    async with client(app) as c:
        h = {"Authorization": h["Authorization"]}  # same token still valid (same JWT secret)
        pend = (await c.get("/api/approvals", headers=h)).json()
        assert pend and pend[0]["thread_id"] == tid, "approval lost after restart"
        assert gigsim_up.store.proposals == {}
        done = (await c.post(f"/api/approvals/{tid}", json={"action": "approve"},
                             headers=h)).json()
        assert done["status"] == "completed" and done["outcome"]["proposal_id"]
        again = await c.post(f"/api/approvals/{tid}", json={"action": "approve"}, headers=h)
        assert again.status_code == 409  # a second approve cannot submit twice
        run = await wait_status(c, h, tid, {"completed"})
        assert run["outcome"]["proposal_id"]
    await cm.__aexit__(None, None, None)
    assert len(gigsim_up.store.proposals) == 1
