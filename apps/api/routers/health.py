# ruff: noqa: B008
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from agent.nodes.config import CFG
from apps.api import runner
from apps.api.bootstrap import test_mode
from apps.api.context import AppCtx, get_ctx
from apps.api.schemas import HealthOut, MarketplaceDownIn, MarketplaceDownOut

router = APIRouter(tags=["health"])
test_router = APIRouter(prefix="/test", include_in_schema=False)


async def marketplace_up(ctx: AppCtx) -> bool:
    try:
        await asyncio.wait_for(ctx.mp.get_connects_balance(),
                               CFG["api"]["health_probe_timeout_s"])
        return True
    except Exception:  # noqa: BLE001  any failure means degraded mode
        return False


@router.get("/health", response_model=HealthOut, operation_id="health")
async def health(ctx: AppCtx = Depends(get_ctx)) -> HealthOut:
    """Public. `marketplace: down` puts the UI in degraded mode. When it is up again, runs that
    were queued during the outage are started."""
    up = await marketplace_up(ctx)
    rows = await ctx.db.fetchall("SELECT thread_id FROM runs WHERE status=%s", ("queued",))
    if up and rows:
        task = asyncio.create_task(runner.drain_queued(ctx))
        ctx.tasks.add(task)
        task.add_done_callback(ctx.tasks.discard)
    return HealthOut(status="ok" if up else "degraded", marketplace="up" if up else "down",
                     checkpointer=ctx.checkpointer_kind, queued_runs=len(rows))


@test_router.post("/marketplace-down", response_model=MarketplaceDownOut)
async def marketplace_down(body: MarketplaceDownIn | None = None,
                           ctx: AppCtx = Depends(get_ctx)) -> MarketplaceDownOut:
    """Test only (GIGBID_TEST_MODE=1): simulate the marketplace server being killed."""
    if not test_mode():
        raise HTTPException(404, "not found")
    ctx.marketplace_down = (body.down if body else True)
    return MarketplaceDownOut(down=ctx.marketplace_down)
