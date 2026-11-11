# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api import runner
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import owned_run
from apps.api.schemas import RegenerateIn, RegenerateOut, UserOut

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.post("/{tid}/regenerate", response_model=RegenerateOut, operation_id="regenerate_paragraph")
async def regenerate(tid: str, body: RegenerateIn, user: UserOut = Depends(get_current_user),
                     ctx: AppCtx = Depends(get_ctx)) -> RegenerateOut:
    """Regenerate one paragraph of the pending draft.

    TODO(graph lane): the bid graph has no single paragraph rewrite entry point yet. This adapter
    validates ownership and the paragraph index, then reports regenerated=false so the UI can show
    the message. Wire it to a writer rewrite function when agent/nodes/writer.py exposes one.
    """
    row = await owned_run(ctx, user, tid)
    snap = await runner.snapshot(ctx, user.id, row["persona"], tid)
    draft = (snap.values or {}).get("proposal_draft")
    if not draft:
        raise HTTPException(409, "no draft for this run yet")
    paras = [p for p in draft.get("cover_letter", "").split("\n\n") if p.strip()]
    if body.paragraph_index >= len(paras):
        raise HTTPException(422, f"paragraph_index out of range (0..{max(len(paras) - 1, 0)})")
    return RegenerateOut(thread_id=tid, paragraph_index=body.paragraph_index, regenerated=False,
                         draft=draft, message="paragraph regeneration is not wired to the writer yet")
