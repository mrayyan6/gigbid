# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends

from agent.marketplace_port import MarketplaceUnavailable
from agent.nodes.config import CFG
from apps.api import runner
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import run_out, user_runs
from apps.api.schemas import PipelineCard, PipelineOut, UserOut

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("", response_model=PipelineOut, operation_id="get_pipeline")
async def get_pipeline(user: UserOut = Depends(get_current_user),
                       ctx: AppCtx = Depends(get_ctx)) -> PipelineOut:
    """Kanban from checkpoint state plus marketplace events (a client message means `replied`).

    Works while the marketplace is down (cards just stop advancing), so the board never errors.
    """
    stages: list[str] = CFG["pipeline"]["stages"]
    cols: dict[str, list[PipelineCard]] = {s: [] for s in stages}
    try:
        replied_clients = {m.get("client_id") for m in await ctx.mp.list_messages()
                           if m.get("from") == "client"}
    except MarketplaceUnavailable:
        replied_clients = set()
    for row in await user_runs(ctx, user):
        run = await run_out(ctx, row)
        rec = run.outcome or {}
        client = (run.job or {}).get("client_id")
        if run.status == "awaiting_approval":
            stage = "drafted"
        elif run.status == "completed" and rec.get("proposal_id"):
            stage = rec.get("status") if rec.get("status") in stages else "submitted"
            if stage == "submitted" and client in replied_clients:
                stage = "replied"
        elif run.status in ("rejected", "blocked"):
            stage = "lost"
        else:
            continue
        cols[stage].append(PipelineCard(
            thread_id=run.thread_id, job_id=run.job_id, title=(run.job or {}).get("title", ""),
            stage=stage, amount=(run.price_quote or {}).get("amount"), client_id=client,
            updated_at=row["updated_at"]))
    return PipelineOut(stages=stages, columns=cols)


__all__ = ["router", "runner"]
