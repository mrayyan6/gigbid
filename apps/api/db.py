"""Tiny async DB layer for app tables (users, settings, runs). One interface, two backends.

Postgres when DATABASE_URL is set (pooled, so Neon idle disconnects heal), else SQLite.
SQL is written with %s placeholders and ON CONFLICT upserts, which both engines accept
(the SQLite backend rewrites %s to ?).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
        persona TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS user_settings (
        user_id TEXT PRIMARY KEY, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS runs (
        thread_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, job_id TEXT NOT NULL,
        persona TEXT NOT NULL, status TEXT NOT NULL, trace_id TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
]


class Db:
    def __init__(self, database_url: str | None, sqlite_path: str) -> None:
        self.url = database_url
        self.sqlite_path = sqlite_path
        self.kind = "postgres" if database_url else "sqlite"
        self.pool: Any = None
        self.conn: Any = None

    async def open(self) -> None:
        if self.kind == "postgres":
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
            self.pool = AsyncConnectionPool(
                self.url, min_size=1, max_size=4, open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                check=AsyncConnectionPool.check_connection)
            await self.pool.open()
        else:
            import aiosqlite
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = await aiosqlite.connect(self.sqlite_path)
            self.conn.row_factory = aiosqlite.Row
        for ddl in SCHEMA:
            await self.execute(ddl)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
        if self.conn is not None:
            await self.conn.close()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        if self.kind == "postgres":
            async with self.pool.connection() as c:
                await c.execute(sql, params)
        else:
            await self.conn.execute(sql.replace("%s", "?"), params)
            await self.conn.commit()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        if self.kind == "postgres":
            async with self.pool.connection() as c:
                cur = await c.execute(sql, params)
                return [dict(r) for r in await cur.fetchall()]
        cur = await self.conn.execute(sql.replace("%s", "?"), params)
        return [dict(r) for r in await cur.fetchall()]

    async def fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None


def sqlite_default() -> str:
    return os.environ.get("USERS_DB", "data/processed/users.sqlite")
