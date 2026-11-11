"""Crash-and-resume: a proposal waiting for approval survives an API restart and is submitted once."""
import httpx
import pytest

from gigsim import generate


async def _client(db):
    import os
    os.environ["CHECKPOINT_DB"] = str(db)
    from apps.api.main import app, lifespan
    cm = lifespan(app)
    await cm.__aenter__()
    return app, cm


@pytest.fixture
async def gigsim_up(monkeypatch):
    generate.build()
    import gigsim.app as gs
    gs.RATE_OVERRIDE = 10**6
    gs.store.reset()
    import mcp_servers.marketplace.adapters.gigsim as ad
    orig = ad.GigSimAdapter.__init__

    def init(self, *a, **k):
        orig(self, base_url="http://t", transport=httpx.ASGITransport(app=gs.app))
    monkeypatch.setattr(ad.GigSimAdapter, "__init__", init)
    return gs


async def test_pending_approval_survives_restart(tmp_path, gigsim_up):
    db = tmp_path / "ck.sqlite"
    app, cm = await _client(db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a") as c:
        jobs = (await c.get("/jobs", params={"limit": 300})).json()
        for j in jobs:
            r = (await c.post("/runs", json={"job_id": j["job_id"]})).json()
            if r["pending_approval"]:
                break
        tid = r["thread_id"]
    await cm.__aexit__(None, None, None)  # "kill" the API

    app, cm = await _client(db)  # restart with same DB
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a") as c:
        run = (await c.get(f"/runs/{tid}")).json()
        assert run["pending_approval"], "approval lost after restart"
        assert gigsim_up.store.proposals == {}
        done = (await c.post(f"/runs/{tid}/approval", json={"action": "approve"})).json()
        assert done["outcome"]["proposal_id"]
    await cm.__aexit__(None, None, None)
    assert len(gigsim_up.store.proposals) == 1
