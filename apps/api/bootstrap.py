"""Builds the AppCtx (DB, checkpointer, graph, marketplace, memory, optional Arq pool).

Used by the FastAPI lifespan and by the Arq worker so both run the same graph the same way.
Checkpointer: AsyncPostgresSaver when DATABASE_URL is set, else AsyncSqliteSaver.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from agent.graphs.bid_graph import build_bid_graph
from agent.marketplace_port import get_marketplace
from agent.nodes.config import CFG
from apps.api.context import AppCtx, GuardedMarketplace
from apps.api.db import Db


def test_mode() -> bool:
    return os.environ.get("GIGBID_TEST_MODE") == "1"


def _load_env() -> None:
    if test_mode():
        return  # tests must never pick up the real Neon or Upstash URLs from .env
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass


@asynccontextmanager
async def checkpointer(database_url: str | None):
    if database_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(
            database_url, min_size=1, max_size=4, open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            check=AsyncConnectionPool.check_connection)
        await pool.open()
        try:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            yield saver, "postgres"
        finally:
            await pool.close()
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        path = os.environ.get("CHECKPOINT_DB") or CFG["api"]["checkpoint_db"]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await saver.setup()
            yield saver, "sqlite"


def _users_sqlite_path() -> str:
    if os.environ.get("USERS_DB"):
        return os.environ["USERS_DB"]
    if os.environ.get("CHECKPOINT_DB"):
        return str(Path(os.environ["CHECKPOINT_DB"]).with_name("users.sqlite"))
    return CFG["api"]["users_db"]


@asynccontextmanager
async def open_ctx(with_arq: bool = True):
    _load_env()
    database_url = os.environ.get("DATABASE_URL") or None
    db = Db(database_url, _users_sqlite_path())
    await db.open()
    arq = None
    try:
        async with checkpointer(database_url) as (saver, kind):
            ctx = AppCtx(db=db, graph=build_bid_graph(saver), checkpointer_kind=kind)
            ctx.mp = GuardedMarketplace(get_marketplace(), ctx)
            try:
                from agent.memory.store import GigBidMemory
                ctx.memory = GigBidMemory(persist=not test_mode())
            except Exception:
                ctx.memory = None
            redis_url = os.environ.get("REDIS_URL")
            if with_arq and redis_url:
                from arq import create_pool
                from arq.connections import RedisSettings
                arq = await create_pool(RedisSettings.from_dsn(redis_url))
                ctx.arq = arq
            yield ctx
    finally:
        if arq is not None:
            await arq.aclose()
        await db.close()
