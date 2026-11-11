# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api import runner
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import owned_run, user_runs
from apps.api.schemas import ApprovalIn, ApprovalItem, ApprovalOut, UserOut

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalItem], operation_id="list_approvals")
async def list_approvals(user: UserOut = Depends(get_current_user),
                         ctx: AppCtx = Depends(get_ctx)) -> list[ApprovalItem]:
    """Pending approvals, read from checkpoint state so a refresh or API restart loses nothing.

    The runs table status can lag a crash (it may still say `running`), so every candidate is
    confirmed against the checkpoint.
    """
    out = []
    for row in await user_runs(ctx, user, ("awaiting_approval", "running", "queued")):
        snap = await runner.snapshot(ctx, user.id, row["persona"], row["thread_id"])
        status, pending = runner.describe(snap) if snap.values else (row["status"], [])
        status = runner.settle(ctx, row["thread_id"], status, row["status"])
        if status != row["status"] and snap.values:
            await runner.set_run(ctx, row["thread_id"], user.id, row["job_id"], row["persona"],
                                 status, None)
        for p in pending:
            title = ((snap.values or {}).get("job") or {}).get("title", "")
            out.append(ApprovalItem(thread_id=row["thread_id"], job_id=row["job_id"],
                                    title=title, payload=p))
    return out


@router.post("/{tid}", response_model=ApprovalOut, operation_id="decide_approval")
async def decide(tid: str, body: ApprovalIn, user: UserOut = Depends(get_current_user),
                 ctx: AppCtx = Depends(get_ctx)) -> ApprovalOut:
    """Resume the interrupted thread with approve, edit (text) or reject (reason)."""
    row = await owned_run(ctx, user, tid)
    if body.action == "reject" and not (body.reason or "").strip():
        raise HTTPException(422, "reject requires a reason")
    if body.action == "edit" and not (body.text or "").strip():
        raise HTTPException(422, "edit requires text")
    snap = await runner.snapshot(ctx, user.id, row["persona"], tid)
    status, pending = runner.describe(snap) if snap.values else (row["status"], [])
    if not pending:
        raise HTTPException(409, f"no pending approval for this run (status {status})")
    draft_text = ((pending[0].get("draft") or {}).get("cover_letter")) or ""
    status = await runner.execute_run(ctx, user.id, row["persona"], row["job_id"], tid,
                                      runner.trace_id_var.get(),
                                      resume=body.model_dump(exclude_none=True))
    promoted: list[str] = []
    if body.action == "edit" and ctx.memory is not None:
        try:  # edits feed style memory, which only promotes by explicit rule
            promoted = list(ctx.memory.record_edit(user.id, tid, draft_text, body.text or ""))
        except Exception:  # noqa: BLE001  memory must never block an approval
            promoted = []
    after = await runner.snapshot(ctx, user.id, row["persona"], tid)
    return ApprovalOut(thread_id=tid, status=status, outcome=(after.values or {}).get("outcome"),
                       promoted_memory=promoted)
