"""Shared helpers for API integration tests. SQLite only: tests never touch Neon or Upstash."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from apps.api import auth as auth_mod


def set_env(monkeypatch, tmp_path, name: str = "ck") -> None:
    monkeypatch.setenv("GIGBID_TEST_MODE", "1")
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / f"{name}.sqlite"))
    monkeypatch.setenv("USERS_DB", str(tmp_path / "users.sqlite"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-test-secret-test-secret")
    monkeypatch.setenv("MARKETPLACE_MODE", "gigsim")
    for k in ("DATABASE_URL", "REDIS_URL", "REVIEWER_EMAIL", "REVIEWER_PASSWORD",
              "REVIEWER_PERSONA"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
async def gigsim_up(monkeypatch):
    from gigsim import generate
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


async def boot():
    from apps.api.main import app, lifespan
    cm = lifespan(app)
    await cm.__aenter__()
    return app, cm


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def make_user(app, email: str, password: str = "pw-12345", persona: str = "ai_ml") -> dict:
    """Create a user directly (there is no public signup endpoint) and return auth headers."""
    u = await auth_mod.create_user(app.state.ctx, email, password, persona)
    return {"Authorization": f"Bearer {auth_mod.make_token(u)}"}


async def wait_status(c, headers, tid: str, want: set[str], timeout: float = 30.0) -> dict:
    end = asyncio.get_event_loop().time() + timeout
    while True:
        run = (await c.get(f"/api/runs/{tid}", headers=headers)).json()
        if run["status"] in want:
            return run
        assert asyncio.get_event_loop().time() < end, f"timeout, last status {run['status']}"
        await asyncio.sleep(0.1)


async def find_bid_run(c, headers) -> dict:
    """Start runs until one waits for approval (a 'bid' decision)."""
    jobs = (await c.get("/api/jobs", params={"limit": 300}, headers=headers)).json()
    for j in jobs:
        r = (await c.post("/api/runs", json={"job_id": j["job_id"]}, headers=headers)).json()
        run = await wait_status(c, headers, r["thread_id"],
                                {"awaiting_approval", "completed", "skipped", "blocked",
                                 "rejected", "failed", "needs_attention"})
        if run["status"] == "awaiting_approval":
            return run
    raise AssertionError("no bid-able job found")
