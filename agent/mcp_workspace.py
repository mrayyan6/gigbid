"""Client for the Workspace MCP server (free calendar slots, tentative interview holds, email drafts).

The agents see MCP tools only: nothing here reads the calendar file directly. Transport is Streamable HTTP when
WORKSPACE_MCP_URL is set (the deployed container), otherwise a stdio subprocess of the same server (local dev).
Calls get a timeout and bounded retries with backoff. A failure raises WorkspaceUnavailable, and callers degrade
(for example, a reply without slots) instead of failing the whole request.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from mcp_servers.common import cfg, current_trace, current_user

Caller = Callable[[str, dict[str, Any]], Awaitable[Any]]
ALLOWED_TOOLS = frozenset({"free_slots", "hold_interview", "draft_email"})


class WorkspaceUnavailable(Exception):
    pass


def default_caller(url: str | None = None, token: str | None = None) -> Caller:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    url = url if url is not None else os.environ.get("WORKSPACE_MCP_URL")
    token = token if token is not None else os.environ.get("WORKSPACE_MCP_TOKEN", "")

    def connection() -> dict[str, Any]:
        if url:
            return {"transport": "streamable_http", "url": url,
                    "headers": {"Authorization": f"Bearer {token}",
                                "X-User-Id": current_user.get(), "X-Trace-Id": current_trace.get()}}
        return {"transport": "stdio", "command": sys.executable, "args": ["-m", "mcp_servers.workspace.server"],
                "env": {**os.environ}}

    async def call(tool: str, args: dict[str, Any]) -> Any:
        client = MultiServerMCPClient({"workspace": connection()})
        async with client.session("workspace") as session:
            return await session.call_tool(tool, args)
    return call


def _data(result: Any) -> Any:
    if getattr(result, "isError", False):
        raise WorkspaceUnavailable("".join(getattr(c, "text", "") for c in (result.content or [])) or "tool error")
    return result.structuredContent


class MCPWorkspace:
    def __init__(self, caller: Caller | None = None, timeout_s: float | None = None, retries: int | None = None,
                 backoff_s: float = 0.3):
        self._caller = caller or default_caller()
        self.timeout_s = timeout_s if timeout_s is not None else float(cfg("mcp.client.timeout_s", 15))
        self.retries = retries if retries is not None else int(cfg("mcp.client.retries", 2))
        self.backoff_s = backoff_s

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        if tool not in ALLOWED_TOOLS:
            raise WorkspaceUnavailable(f"tool '{tool}' is not allowed")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return _data(await asyncio.wait_for(self._caller(tool, args), self.timeout_s))
            except Exception as exc:
                last = exc
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff_s * 2 ** attempt)
        raise WorkspaceUnavailable(f"{tool} failed after {self.retries + 1} attempts: {last}")

    async def free_slots(self, date_from: str, date_to: str, duration_min: int = 30) -> list[dict]:
        """Free slots as dicts with start and end (ISO, local time), from the Workspace MCP server."""
        data = await self.call("free_slots", {"date_from": date_from, "date_to": date_to,
                                              "duration_min": duration_min}) or {}
        out = []
        for s in data.get("slots", []):
            start = datetime.fromisoformat(s)
            out.append({"start": start.isoformat(timespec="minutes"),
                        "end": (start + timedelta(minutes=duration_min)).isoformat(timespec="minutes")})
        return out
