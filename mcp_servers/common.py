"""Shared helpers for the GigBid MCP servers: config lookup, request context, bearer auth."""
from __future__ import annotations

import contextvars
import hmac
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "agent" / "config.yaml"

current_user: contextvars.ContextVar[str] = contextvars.ContextVar("gigbid_user", default="local")
current_trace: contextvars.ContextVar[str] = contextvars.ContextVar("gigbid_trace", default="")


def cfg(path: str, default: Any = None) -> Any:
    """Read a dotted key such as 'mcp.marketplace.rate_per_min' from agent/config.yaml.
    Falls back to `default` when the key is absent, so servers run before the key is added."""
    try:
        node: Any = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        return default
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


class BearerAuthMiddleware:
    """ASGI middleware: requires `Authorization: Bearer <token>` on HTTP requests and copies
    X-User-Id and X-Trace-Id into context variables for rate limiting and the audit log."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        given = headers.get("authorization", "")
        if not hmac.compare_digest(given, f"Bearer {self.token}"):
            body = b'{"error":"unauthorized"}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        u = current_user.set(headers.get("x-user-id", "default"))
        t = current_trace.set(headers.get("x-trace-id", ""))
        try:
            await self.app(scope, receive, send)
        finally:
            current_user.reset(u)
            current_trace.reset(t)
