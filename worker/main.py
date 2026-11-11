"""Arq worker. Start with: arq worker.main.WorkerSettings  (needs REDIS_URL; DATABASE_URL optional).

Shares apps/api/bootstrap.open_ctx with the API, so it runs the same graph, checkpointer and
marketplace port. Scheduling: one cron tick per minute decides which saved searches are due, using
each search's own interval (default from config; live mode is floored to a conservative interval,
see docs/RUNBOOK.md for the rationale).
"""
from __future__ import annotations

import os
from contextlib import AsyncExitStack

from arq import cron
from arq.connections import RedisSettings

from agent.nodes.config import CFG
from apps.api.bootstrap import _load_env, open_ctx
from worker.tasks import run_bid_thread, scout_all, scout_saved_search

_load_env()


async def startup(ctx: dict) -> None:
    stack = AsyncExitStack()
    ctx["stack"] = stack
    ctx["app"] = await stack.enter_async_context(open_ctx(with_arq=False))


async def shutdown(ctx: dict) -> None:
    await ctx["stack"].aclose()


class WorkerSettings:
    functions = [run_bid_thread, scout_saved_search]
    cron_jobs = [cron(scout_all, second=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    job_timeout = CFG["worker"]["job_timeout_seconds"]
    max_tries = 3
    keep_result = 3600
