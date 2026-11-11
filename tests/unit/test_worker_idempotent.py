"""Worker idempotency with fakeredis and a fake runner: no network, no Neon, no Upstash."""
from types import SimpleNamespace

import fakeredis
import pytest

from worker import tasks


class FakeDb:
    def __init__(self):
        self.status = "queued"

    async def fetchone(self, sql, params=()):
        return {"status": self.status}


class FakeRunner:
    def __init__(self, db, snap=None, final="completed"):
        self.db, self.calls, self.snap, self.final = db, [], snap, final

    async def snapshot(self, app, user, persona, tid):
        return self.snap or SimpleNamespace(values={}, next=(), tasks=[])

    async def execute_run(self, app, user, persona, job_id, tid, trace_id, **kw):
        self.calls.append(kw)
        self.db.status = self.final
        return self.final


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis()


def patch(monkeypatch, fr):
    monkeypatch.setattr(tasks.runner, "snapshot", fr.snapshot)
    monkeypatch.setattr(tasks.runner, "execute_run", fr.execute_run)


async def test_same_job_twice_runs_once(monkeypatch, redis):
    db = FakeDb()
    fr = FakeRunner(db)
    patch(monkeypatch, fr)
    app = SimpleNamespace(db=db)
    a = await tasks.process_job(app, redis, "u1", "ai_ml", "j1", "u1:j1")
    b = await tasks.process_job(app, redis, "u1", "ai_ml", "j1", "u1:j1")
    assert (a, b) == ("started", "duplicate")
    assert len(fr.calls) == 1


async def test_other_user_same_job_is_separate(monkeypatch, redis):
    db = FakeDb()
    fr = FakeRunner(db)
    patch(monkeypatch, fr)
    app = SimpleNamespace(db=db)
    await tasks.process_job(app, redis, "u1", "ai_ml", "j1", "u1:j1")
    db.status = "queued"
    assert await tasks.process_job(app, redis, "u2", "ai_ml", "j1", "u2:j1") == "started"
    assert len(fr.calls) == 2


async def test_concurrent_lease_blocks_second_worker(monkeypatch, redis):
    db = FakeDb()
    patch(monkeypatch, FakeRunner(db))
    await redis.set(tasks.inflight_key("u1", "j1"), "1", ex=60)  # another worker holds the lease
    r = await tasks.process_job(SimpleNamespace(db=db), redis, "u1", "ai_ml", "j1", "u1:j1")
    assert r == "in_progress"


async def test_crashed_run_resumes_from_checkpoint_not_restart(monkeypatch, redis):
    db = FakeDb()
    mid = SimpleNamespace(values={"job_id": "j1", "job": {}}, next=("pricing",), tasks=[])
    fr = FakeRunner(db, snap=mid)
    patch(monkeypatch, fr)
    r = await tasks.process_job(SimpleNamespace(db=db), redis, "u1", "ai_ml", "j1", "u1:j1")
    assert r == "resumed" and fr.calls == [{"fresh": False}]


async def test_marketplace_down_leaves_job_retryable(monkeypatch, redis):
    db = FakeDb()
    fr = FakeRunner(db, final="queued")
    patch(monkeypatch, fr)
    app = SimpleNamespace(db=db)
    await tasks.process_job(app, redis, "u1", "ai_ml", "j1", "u1:j1")
    assert not await redis.get(tasks.processed_key("u1", "j1"))
    await tasks.process_job(app, redis, "u1", "ai_ml", "j1", "u1:j1")
    assert len(fr.calls) == 2  # not marked processed, so the retry really runs


def test_live_interval_is_floored():
    assert tasks.interval_minutes(1, "upwork") >= 60
    assert tasks.interval_minutes(1, "gigsim") == 1
