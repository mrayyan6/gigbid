"""Arq tasks. Long runs never execute inside a web request.

Idempotency (a worker restart must never double analyse or double submit), three layers:
1. Arq `_job_id = bid:{thread_id}`: enqueueing the same thread twice is a no-op while the job exists.
2. Redis keys here: `processed:{user}:{job}` (finished, long TTL) and `inflight:{user}:{job}`
   (short TTL lease, expires if the worker dies so Arq's retry can take over).
3. Thread id is `{user}:{job}`, so the LangGraph checkpointer holds one state per job. A retried
   run resumes from the last checkpoint (input None) instead of starting over, and the submit node
   uses an idempotency key, so the marketplace itself rejects a second proposal.
"""
from __future__ import annotations

from typing import Any

from agent.marketplace_port import MarketplaceUnavailable
from agent.nodes.config import CFG
from apps.api import runner
from apps.api.auth import load_settings


def processed_key(user_id: str, job_id: str) -> str:
    return f"processed:{user_id}:{job_id}"


def inflight_key(user_id: str, job_id: str) -> str:
    return f"inflight:{user_id}:{job_id}"


async def process_job(app: Any, redis: Any, user_id: str, persona: str, job_id: str, tid: str,
                      trace_id: str | None = None) -> str:
    """Run one bid thread exactly once. Returns started, resumed, duplicate or in_progress."""
    w = CFG["worker"]
    if await redis.get(processed_key(user_id, job_id)):
        return "duplicate"
    if not await redis.set(inflight_key(user_id, job_id), "1", nx=True,
                           ex=w["job_timeout_seconds"]):
        return "in_progress"  # another worker holds the lease
    try:
        snap = await runner.snapshot(app, user_id, persona, tid)
        values = snap.values or {}
        status, pending = runner.describe(snap) if values else ("queued", [])
        if values and status not in ("queued", "running") or pending:
            outcome = "duplicate"  # already finished or parked on approval: nothing to redo
        elif values and snap.next:
            await runner.execute_run(app, user_id, persona, job_id, tid, trace_id, fresh=False)
            outcome = "resumed"
        else:
            await runner.execute_run(app, user_id, persona, job_id, tid, trace_id)
            outcome = "started"
        row = await app.db.fetchone("SELECT status FROM runs WHERE thread_id=%s", (tid,))
        if row and row["status"] != "queued":  # queued = marketplace down, allow a later retry
            await redis.set(processed_key(user_id, job_id), "1", ex=w["processed_ttl_seconds"])
        return outcome
    finally:
        await redis.delete(inflight_key(user_id, job_id))


async def run_bid_thread(ctx: dict, user_id: str, job_id: str, persona: str, tid: str,
                         trace_id: str | None = None) -> str:
    return await process_job(ctx["app"], ctx["redis"], user_id, persona, job_id, tid, trace_id)


async def scout_saved_search(ctx: dict, user_id: str, persona: str, query: str = "") -> int:
    """Read the marketplace once for a saved search and enqueue one bid thread per new job.
    Already processed jobs are skipped here (cheap) and again in process_job (authoritative)."""
    app, redis = ctx["app"], ctx["redis"]
    try:
        jobs = await app.mp.search_jobs(query=query, limit=CFG["worker"]["max_jobs_per_scout"],
                                        persona=persona)
    except MarketplaceUnavailable:
        return 0  # degraded mode: try again at the next scheduled tick
    n = 0
    for j in jobs:
        job_id = j["job_id"]
        if await redis.get(processed_key(user_id, job_id)):
            continue
        tid = runner.thread_id_for(user_id, job_id)
        await runner.set_run(app, tid, user_id, job_id, persona, "queued", None)
        await redis.enqueue_job("run_bid_thread", user_id, job_id, persona, tid, None,
                                _job_id=f"bid:{tid}")
        n += 1
    return n


def interval_minutes(search_interval: int, mode: str) -> int:
    """Live mode never polls faster than the conservative configured floor."""
    w = CFG["worker"]
    floor = w["live_scout_interval_minutes"] if mode == "upwork" else 1
    return max(search_interval or w["gigsim_scout_interval_minutes"], floor)


async def scout_all(ctx: dict) -> int:
    """Cron, every minute. Starts each user's saved searches whose interval has elapsed."""
    import os
    import time
    app, redis = ctx["app"], ctx["redis"]
    mode = os.environ.get("MARKETPLACE_MODE", "gigsim")
    started = 0
    for u in await app.db.fetchall("SELECT id, persona FROM users"):
        for s in (await load_settings(app, u["id"])).get("saved_searches", []):
            key = f"lastscout:{u['id']}:{s['name']}"
            every = interval_minutes(s.get("interval_minutes", 0), mode) * 60
            if not await redis.set(key, str(int(time.time())), nx=True, ex=every):
                continue  # not due yet
            started += await scout_saved_search(ctx, u["id"], u["persona"], s.get("query", ""))
    return started
