"""FastAPI backend. Contract: see apps/api/schemas and apps/web/openapi.json (all under /api).

Run: uvicorn apps.api.main:app --port 8000 (GigSim on :9000).
Env: DATABASE_URL (Postgres checkpointer and app tables, else SQLite), REDIS_URL (Arq queue, else
inline background tasks), JWT_SECRET, REVIEWER_EMAIL, REVIEWER_PASSWORD, REVIEWER_PERSONA,
GIGBID_TEST_MODE=1 (enables POST /api/test/marketplace-down, disables .env loading).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from agent.marketplace_port import MarketplaceUnavailable
from agent.observability import setup_tracing
from apps.api import auth as auth_mod
from apps.api.bootstrap import open_ctx
from apps.api.routers import (
    analytics,
    approvals,
    health,
    jobs,
    memory,
    messages,
    pipeline,
    proposals,
    runs,
    settings,
)
from apps.api.routers import auth as auth_router
from apps.api.runner import trace_id_var


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with open_ctx() as ctx:
        app.state.ctx = ctx
        setup_tracing()  # after open_ctx so LANGSMITH_* from .env are loaded; off without a key
        await auth_mod.seed_reviewer(ctx)
        yield


class TraceIdMiddleware:
    """Pure ASGI (safe for SSE). One trace id per request: taken from X-Trace-Id if the caller sent
    one, else a new uuid. It is put in a contextvar (read when a run starts, then stored in graph
    config metadata) and echoed in the response header."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        hdrs = dict(scope["headers"])
        tid = (hdrs.get(b"x-trace-id") or b"").decode()[:64] or uuid.uuid4().hex
        token = trace_id_var.set(tid)

        async def send_with_header(msg):
            if msg["type"] == "http.response.start":
                msg.setdefault("headers", []).append((b"x-trace-id", tid.encode()))
            await send(msg)
        try:
            await self.app(scope, receive, send_with_header)
        finally:
            trace_id_var.reset(token)


app = FastAPI(title="GigBid API", version="1.0.0", lifespan=lifespan)
app.add_middleware(TraceIdMiddleware)


@app.exception_handler(MarketplaceUnavailable)
async def _marketplace_down(_: Request, exc: MarketplaceUnavailable):
    return JSONResponse({"detail": f"marketplace unavailable: {exc}"}, status_code=503,
                        headers={"Retry-After": "5"})


@app.exception_handler(httpx.HTTPStatusError)
async def _upstream_status(_: Request, exc: httpx.HTTPStatusError):
    code = exc.response.status_code
    return JSONResponse({"detail": f"marketplace said {code}"}, status_code=code if code < 500 else 502)


api = APIRouter(prefix="/api")
for r in (auth_router, jobs, runs, approvals, proposals, pipeline, messages, analytics, memory,
          settings, health):
    api.include_router(r.router)
api.include_router(health.test_router)
app.include_router(api)
