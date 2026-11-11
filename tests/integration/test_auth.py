"""Auth, tenant scoping, reviewer seeding, trace id, degraded mode, SSE."""
import json

from tests.integration.api_helpers import (
    boot,
    client,
    find_bid_run,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
    wait_status,
)


async def test_unauthorized_is_401(tmp_path, monkeypatch):
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    async with client(app) as c:
        for path in ("/api/jobs", "/api/approvals", "/api/auth/me", "/api/pipeline",
                     "/api/settings", "/api/memory", "/api/analytics", "/api/messages"):
            assert (await c.get(path)).status_code == 401, path
        bad = await c.get("/api/auth/me", headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401
        assert (await c.get("/api/health")).status_code == 200  # health is public
    await cm.__aexit__(None, None, None)


async def test_reviewer_seed_and_login(tmp_path, monkeypatch):
    set_env(monkeypatch, tmp_path)
    monkeypatch.setenv("REVIEWER_EMAIL", "reviewer@gigbid.test")
    monkeypatch.setenv("REVIEWER_PASSWORD", "correct horse battery")
    monkeypatch.setenv("REVIEWER_PERSONA", "data_analyst")
    app, cm = await boot()
    async with client(app) as c:
        bad = await c.post("/api/auth/login", json={"email": "reviewer@gigbid.test",
                                                    "password": "wrong"})
        assert bad.status_code == 401
        ok = await c.post("/api/auth/login", json={"email": "Reviewer@gigbid.test",
                                                   "password": "correct horse battery"})
        assert ok.status_code == 200
        tok = ok.json()
        assert tok["user"]["persona"] == "data_analyst"
        me = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
        assert me.json()["email"] == "reviewer@gigbid.test"
    await cm.__aexit__(None, None, None)
    app, cm = await boot()  # seeding twice is idempotent
    n = await app.state.ctx.db.fetchall("SELECT id FROM users")
    assert len(n) == 1
    await cm.__aexit__(None, None, None)


async def test_tenant_isolation(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    async with client(app) as c:
        a = await make_user(app, "a@example.test")
        b = await make_user(app, "b@example.test")
        run = await find_bid_run(c, a)
        tid = run["thread_id"]
        assert (await c.get(f"/api/runs/{tid}", headers=b)).status_code == 404
        assert (await c.get(f"/api/runs/{tid}/stream", headers=b)).status_code == 404
        assert (await c.post(f"/api/approvals/{tid}", json={"action": "approve"},
                             headers=b)).status_code == 404
        assert (await c.get("/api/approvals", headers=b)).json() == []
        assert len((await c.get("/api/approvals", headers=a)).json()) == 1
        # b starting the same job gets its own thread
        job_id = run["job_id"]
        rb = (await c.post("/api/runs", json={"job_id": job_id}, headers=b)).json()
        assert rb["thread_id"] != tid
        assert gigsim_up.store.proposals == {}
    await cm.__aexit__(None, None, None)


async def test_trace_id_header_and_stream(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    async with client(app) as c:
        h = await make_user(app, "s@example.test")
        r = await c.get("/api/health", headers={"X-Trace-Id": "abc123"})
        assert r.headers["x-trace-id"] == "abc123"
        assert len((await c.get("/api/health")).headers["x-trace-id"]) >= 16
        jobs = (await c.get("/api/jobs", params={"limit": 5}, headers=h)).json()
        r = await c.post("/api/runs", json={"job_id": jobs[0]["job_id"]}, headers={**h,
                         "X-Trace-Id": "trace-xyz"})
        assert r.status_code == 202 and r.json()["trace_id"] == "trace-xyz"
        tid = r.json()["thread_id"]
        events = []
        async with c.stream("GET", f"/api/runs/{tid}/stream", headers=h) as s:
            assert s.status_code == 200
            ev = None
            async for line in s.aiter_lines():
                if line.startswith("event:"):
                    ev = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and ev:
                    events.append((ev, json.loads(line.split(":", 1)[1])))
        names = [e for e, _ in events]
        assert "node" in names and names[-1] == "done" and "status" in names
        assert {d["node"] for e, d in events if e == "node"} >= {"scout", "decide"}
        done = await wait_status(c, h, tid, {"awaiting_approval", "skipped", "completed", "blocked"})
        assert done["trace_id"] == "trace-xyz"
    await cm.__aexit__(None, None, None)


async def test_marketplace_down_degraded_and_recovery(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    async with client(app) as c:
        h = await make_user(app, "d@example.test")
        assert (await c.get("/api/health")).json()["marketplace"] == "up"
        jobs = (await c.get("/api/jobs", params={"limit": 3}, headers=h)).json()
        await c.post("/api/test/marketplace-down", json={"down": True})
        health = (await c.get("/api/health")).json()
        assert health["marketplace"] == "down" and health["status"] == "degraded"
        assert (await c.get("/api/jobs", headers=h)).status_code == 503
        assert (await c.get("/api/pipeline", headers=h)).status_code == 200  # board still works
        r = (await c.post("/api/runs", json={"job_id": jobs[0]["job_id"]}, headers=h)).json()
        await wait_status(c, h, r["thread_id"], {"queued"})
        assert (await c.get("/api/health")).json()["queued_runs"] == 1
        await c.post("/api/test/marketplace-down", json={"down": False})
        assert (await c.get("/api/health")).json()["marketplace"] == "up"  # triggers drain
        run = await wait_status(c, h, r["thread_id"],
                                {"awaiting_approval", "skipped", "completed", "blocked"})
        assert run["decision"] is not None
    await cm.__aexit__(None, None, None)


async def test_test_endpoint_disabled_outside_test_mode(tmp_path, monkeypatch):
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    async with client(app) as c:
        monkeypatch.delenv("GIGBID_TEST_MODE")
        assert (await c.post("/api/test/marketplace-down")).status_code == 404
    await cm.__aexit__(None, None, None)
