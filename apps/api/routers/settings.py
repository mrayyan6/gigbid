# ruff: noqa: B008
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from apps.api.auth import get_current_user, load_settings, save_settings
from apps.api.context import AppCtx, get_ctx
from apps.api.schemas import SettingsModel, SettingsOut, UserOut

router = APIRouter(prefix="/settings", tags=["settings"])


async def _out(ctx: AppCtx, user: UserOut) -> SettingsOut:
    s = SettingsModel(**await load_settings(ctx, user.id))
    return SettingsOut(**s.model_dump(), persona=user.persona,
                       marketplace_mode=os.environ.get("MARKETPLACE_MODE") or "gigsim")


@router.get("", response_model=SettingsOut, operation_id="get_settings")
async def get_settings(user: UserOut = Depends(get_current_user),
                       ctx: AppCtx = Depends(get_ctx)) -> SettingsOut:
    return await _out(ctx, user)


@router.put("", response_model=SettingsOut, operation_id="put_settings")
async def put_settings(body: SettingsModel, user: UserOut = Depends(get_current_user),
                       ctx: AppCtx = Depends(get_ctx)) -> SettingsOut:
    """Autonomy can auto-skip low fit jobs but never auto-sends (enforced in the graph, not here)."""
    await save_settings(ctx, user.id, body.model_dump())
    return await _out(ctx, user)
