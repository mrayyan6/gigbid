# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api import runner
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import owned_run, run_out
from apps.api.schemas import RunIn, RunOut, RunStartOut, UserOut
from apps.api.streaming import run_event_response

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunStartOut, operation_id="start_run", status_code=202)
async def start_run(body: RunIn, user: UserOut = Depends(get_current_user),
                    ctx: AppCtx = Depends(get_ctx)) -> RunStartOut:
    """Start (or return) the bid thread for a job. Never blocks on the graph.

    Idempotent: one thread per user and job. If the marketplace is down the run stays `queued`
    and is started automatically when it recovers.
    """
    tid = runner.thread_id_for(user.id, body.job_id)
    trace_id = runner.trace_id_var.get()
    row = await ctx.db.fetchone("SELECT * FROM runs WHERE thread_id=%s AND user_id=%s",
                                (tid, user.id))
    if row is not None and row["status"] not in ("failed",):
        return RunStartOut(thread_id=tid, job_id=body.job_id, status=row["status"],
                           trace_id=row["trace_id"])
    status = await runner.dispatch_run(ctx, user.id, user.persona, body.job_id, tid, trace_id)
    return RunStartOut(thread_id=tid, job_id=body.job_id, status=status, trace_id=trace_id)


@router.get("/{tid}", response_model=RunOut, operation_id="get_run")
async def get_run(tid: str, user: UserOut = Depends(get_current_user),
                  ctx: AppCtx = Depends(get_ctx)) -> RunOut:
    return await run_out(ctx, await owned_run(ctx, user, tid))


@router.get("/{tid}/stream", operation_id="stream_run",
            responses={200: {"content": {"text/event-stream": {}},
                             "description": "SSE events: node, custom, interrupt, status, error, "
                                            "done. Auth via Bearer header or ?token= for EventSource."}})
async def stream_run(tid: str, user: UserOut = Depends(get_current_user),
                     ctx: AppCtx = Depends(get_ctx)):
    return run_event_response(ctx, await owned_run(ctx, user, tid))
