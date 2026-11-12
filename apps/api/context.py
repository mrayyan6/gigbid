"""Process wide application context, built once in the lifespan and read by routers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from apps.api.db import Db


class GuardedMarketplace:
    """Wraps the marketplace port. When the test switch is on it behaves like a dead server.

    Real outages surface as MarketplaceUnavailable from the adapter itself; this proxy only adds
    the switch used by POST /api/test/marketplace-down (viva demo, Playwright degraded-mode test).
    """

    def __init__(self, inner: Any, ctx: AppCtx) -> None:
        self._inner = inner
        self._ctx = ctx

    def as_agent(self, agent: str):
        """Role restricted view of the inner port, still behind the test switch."""
        inner = self._inner.as_agent(agent) if hasattr(self._inner, "as_agent") else self._inner
        return GuardedMarketplace(inner, self._ctx)

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        async def call(*a, **k):
            if self._ctx.marketplace_down:
                from agent.marketplace_port import MarketplaceUnavailable
                raise MarketplaceUnavailable("marketplace switched off (test mode)")
            return await attr(*a, **k)
        return call


@dataclass
class AppCtx:
    db: Db
    graph: Any
    checkpointer_kind: str
    mp: Any = None
    memory: Any = None
    arq: Any = None                      # ArqRedis when REDIS_URL is set, else None (inline mode)
    retrievers: dict = field(default_factory=dict)
    marketplace_down: bool = False
    tasks: set = field(default_factory=set)
    hub: dict = field(default_factory=dict)  # thread_id -> RunChannel (in process streaming)
    drain_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def get_ctx(request: Request) -> AppCtx:
    return request.app.state.ctx
