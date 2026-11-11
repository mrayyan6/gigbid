# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.schemas import DeleteOut, MemoryItem, MemoryOut, UserOut

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=MemoryOut, operation_id="list_memory")
async def list_memory(user: UserOut = Depends(get_current_user),
                      ctx: AppCtx = Depends(get_ctx)) -> MemoryOut:
    """Promoted memory only (style and outcome), scoped to the calling user."""
    if ctx.memory is None:
        return MemoryOut(items=[])
    return MemoryOut(items=[MemoryItem(**i) for i in ctx.memory.list(user.id)])


@router.delete("/{ns}/{key}", response_model=DeleteOut, operation_id="delete_memory")
async def delete_memory(ns: str, key: str, user: UserOut = Depends(get_current_user),
                        ctx: AppCtx = Depends(get_ctx)) -> DeleteOut:
    if ctx.memory is None or not ctx.memory.delete(user.id, ns, key):
        raise HTTPException(404, "no such memory item")
    return DeleteOut(deleted=True)
