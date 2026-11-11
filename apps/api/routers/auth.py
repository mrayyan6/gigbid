# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import authenticate, get_current_user, make_token
from apps.api.context import AppCtx, get_ctx
from apps.api.schemas import LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut, operation_id="login")
async def login(body: LoginIn, ctx: AppCtx = Depends(get_ctx)) -> TokenOut:
    user = await authenticate(ctx, body.email, body.password)
    if user is None:
        raise HTTPException(401, "invalid email or password")
    return TokenOut(access_token=make_token(user), user=user)


@router.get("/me", response_model=UserOut, operation_id="me")
async def me(user: UserOut = Depends(get_current_user)) -> UserOut:
    return user
