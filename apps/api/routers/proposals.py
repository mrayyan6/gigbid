# ruff: noqa: B008
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from agent.nodes import core
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

    The writer model rewrites the paragraph (prompt agent/prompts/rewrite_paragraph.md), the claim verifier removes
    any unsupported claim, and the compliance rules and platform policy are applied. On success the new draft is
    written into the paused thread so the approval screen and the final submit use it. The thread stays at the
    approval step: nothing is sent.
    """
    row = await owned_run(ctx, user, tid)
    snap = await runner.snapshot(ctx, user.id, row["persona"], tid)
    values = snap.values or {}
    draft = values.get("proposal_draft")
    if not draft:
        raise HTTPException(409, "no draft for this run yet")
    if "approval" not in list(snap.next):
        raise HTTPException(409, "the run is not waiting for approval, so the draft cannot be changed")
    paras = [p for p in draft.get("cover_letter", "").split("\n\n") if p.strip()]
    if body.paragraph_index >= max(len(paras), 1):
        raise HTTPException(422, f"paragraph_index out of range (0..{max(len(paras) - 1, 0)})")
    try:
        policy = await ctx.mp.get_policy()
    except Exception:
        policy = None
    out = await asyncio.to_thread(core.rewrite_paragraph, values, body.paragraph_index, policy)
    if out["regenerated"]:
        draft = {**draft, "cover_letter": out["cover_letter"]}
        cfg = runner.graph_config(ctx, user.id, row["persona"], tid, None)
        await ctx.graph.aupdate_state(cfg, {"proposal_draft": draft}, as_node="compliance")
        await ctx.graph.ainvoke(None, cfg)  # re-run the approval node so the interrupt is raised again, nothing is sent
    return RegenerateOut(thread_id=tid, paragraph_index=body.paragraph_index, regenerated=out["regenerated"],
                         draft=draft, message=out["message"])
