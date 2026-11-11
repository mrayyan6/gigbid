# ruff: noqa: B008
"""Auth: PBKDF2 password hashing (hashlib), JWT (PyJWT), tenant id on every query.

Tenant rule: a user id is the tenant. Thread ids are `{user_id}:{job_id}`, runs and settings rows
carry user_id, and every router filters by `user.id` taken from the verified token, never from
the request body.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent.nodes.config import CFG
from apps.api.context import AppCtx, get_ctx
from apps.api.schemas import UserOut

_bearer = HTTPBearer(auto_error=False)
_FALLBACK_SECRET = secrets.token_urlsafe(32)  # per process; set JWT_SECRET for multi instance


def _secret() -> str:
    return os.environ.get("JWT_SECRET") or _FALLBACK_SECRET


def hash_password(password: str, iterations: int | None = None) -> str:
    iters = iterations or CFG["api"]["pbkdf2_iterations"]
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters)
    return f"pbkdf2_sha256${iters}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def make_token(user: UserOut) -> str:
    ttl = CFG["api"]["jwt_ttl_minutes"] * 60
    claims = {"sub": user.id, "email": user.email, "persona": user.persona,
              "iat": int(time.time()), "exp": int(time.time()) + ttl}
    return jwt.encode(claims, _secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=["HS256"])


# users ----------------------------------------------------------------------------------------
async def create_user(ctx: AppCtx, email: str, password: str, persona: str) -> UserOut:
    uid = "u" + uuid.uuid4().hex[:12]
    now = datetime.now(UTC).isoformat()
    await ctx.db.execute(
        "INSERT INTO users (id,email,pw_hash,persona,created_at) VALUES (%s,%s,%s,%s,%s)",
        (uid, email.lower(), hash_password(password), persona, now))
    return UserOut(id=uid, email=email.lower(), persona=persona)


async def authenticate(ctx: AppCtx, email: str, password: str) -> UserOut | None:
    row = await ctx.db.fetchone("SELECT * FROM users WHERE email=%s", (email.lower(),))
    if row is None:
        verify_password(password, hash_password("x", 1000))  # equalise timing
        return None
    if not verify_password(password, row["pw_hash"]):
        return None
    return UserOut(id=row["id"], email=row["email"], persona=row["persona"])


async def seed_reviewer(ctx: AppCtx) -> UserOut | None:
    """Idempotent. Creates (or refreshes the password and persona of) the reviewer user from env."""
    email, pw = os.environ.get("REVIEWER_EMAIL"), os.environ.get("REVIEWER_PASSWORD")
    persona = os.environ.get("REVIEWER_PERSONA", "ai_ml")
    if not email or not pw:
        return None
    row = await ctx.db.fetchone("SELECT * FROM users WHERE email=%s", (email.lower(),))
    if row is None:
        return await create_user(ctx, email, pw, persona)
    if not verify_password(pw, row["pw_hash"]) or row["persona"] != persona:
        await ctx.db.execute("UPDATE users SET pw_hash=%s, persona=%s WHERE id=%s",
                             (hash_password(pw), persona, row["id"]))
    return UserOut(id=row["id"], email=row["email"], persona=persona)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None, include_in_schema=False),  # EventSource cannot set headers
    ctx: AppCtx = Depends(get_ctx),
) -> UserOut:
    raw = creds.credentials if creds else token
    if not raw:
        raise HTTPException(401, "not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(raw)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    row = await ctx.db.fetchone("SELECT id,email,persona FROM users WHERE id=%s", (claims["sub"],))
    if row is None:
        raise HTTPException(401, "unknown user")
    return UserOut(**row)


async def load_settings(ctx: AppCtx, user_id: str) -> dict:
    row = await ctx.db.fetchone("SELECT data FROM user_settings WHERE user_id=%s", (user_id,))
    return json.loads(row["data"]) if row else dict(CFG["api"]["default_settings"])


async def save_settings(ctx: AppCtx, user_id: str, data: dict) -> None:
    await ctx.db.execute(
        "INSERT INTO user_settings (user_id,data) VALUES (%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET data=excluded.data", (user_id, json.dumps(data)))
