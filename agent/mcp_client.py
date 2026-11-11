"""MCP client port: implements MarketplacePort by calling the Marketplace MCP server's tools.

Client discipline (Part A6):
- per-agent allowlists by tool name (config mcp.allowlists); a call outside the list raises
  ToolNotAllowed before anything goes on the wire,
- a timeout per call and bounded retries with exponential backoff (config mcp.client),
- any transport failure or marketplace outage becomes MarketplaceUnavailable, which the graph and
  the API turn into the visible degraded state.

Transports: streamable HTTP in compose and deployment (MARKETPLACE_MCP_URL plus bearer token),
stdio child process in dev, or any injected `caller` (tests use an in-memory client session).
The caller is the only place that knows about transports, so swapping it changes no node code.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable, ToolNotAllowed
from mcp_servers.common import cfg, current_trace, current_user

Caller = Callable[[str, dict[str, Any]], Awaitable[Any]]  # (tool, args) -> CallToolResult


def _unwrap(result: Any) -> Any:
    """Turn a CallToolResult into plain data. Raises on tool errors."""
    text = "".join(getattr(c, "text", "") for c in (result.content or []))
    if result.isError:
        if "marketplace_unavailable" in text:
            raise MarketplaceUnavailable(text)
        if "rate_limited" in text:
            raise _RateLimited(text)
        raise MarketplaceError(text)
    data = result.structuredContent
    if data is None:
        data = json.loads(text) if text else None
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]  # FastMCP wraps list and scalar returns
    return _strip_none(data)


def _strip_none(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _strip_none(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_strip_none(x) for x in v]
    return v


class _RateLimited(Exception):
    """Server side per-user limiter said no. Retried with backoff like a transient error."""


def default_caller(url: str | None = None, token: str | None = None) -> Caller:
    """Caller over langchain_mcp_adapters.MultiServerMCPClient. A short lived session is opened per
    call so per-user and per-trace headers are always current."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    url = url or os.environ.get("MARKETPLACE_MCP_URL")
    token = token or os.environ.get("MARKETPLACE_MCP_TOKEN", "")

    def connection() -> dict[str, Any]:
        if url:
            return {"transport": "streamable_http", "url": url,
                    "headers": {"Authorization": f"Bearer {token}",
                                "X-User-Id": current_user.get(), "X-Trace-Id": current_trace.get()}}
        return {"transport": "stdio", "command": sys.executable,
                "args": ["-m", "mcp_servers.marketplace.server"],
                "env": {**os.environ, "MARKETPLACE_BACKEND": "gigsim"}}

    async def call(tool: str, args: dict[str, Any]) -> Any:
        client = MultiServerMCPClient({"marketplace": connection()})
        async with client.session("marketplace") as session:
            return await session.call_tool(tool, args)
    return call


class MCPMarketplace:
    def __init__(self, caller: Caller | None = None, agent: str = "graph",
                 allowlists: dict[str, list[str]] | None = None, timeout_s: float | None = None,
                 retries: int | None = None, backoff_s: float | None = None):
        self._caller = caller or default_caller()
        self.agent = agent
        self.allowlists = allowlists if allowlists is not None else cfg("mcp.allowlists", {})
        self.timeout_s = timeout_s if timeout_s is not None else float(cfg("mcp.client.timeout_s", 15))
        self.retries = retries if retries is not None else int(cfg("mcp.client.retries", 2))
        self.backoff_s = backoff_s if backoff_s is not None else float(cfg("mcp.client.backoff_s", 0.3))

    @classmethod
    def from_env(cls, **kw) -> MCPMarketplace:
        return cls(**kw)

    def as_agent(self, agent: str) -> MCPMarketplace:
        """View of the same transport restricted to one agent's allowlist."""
        return MCPMarketplace(self._caller, agent, self.allowlists, self.timeout_s, self.retries,
                              self.backoff_s)

    def allowed(self, tool: str) -> bool:
        return tool in self.allowlists.get(self.agent, [])

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        if not self.allowed(tool):
            raise ToolNotAllowed(f"agent '{self.agent}' may not call tool '{tool}'")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                res = await asyncio.wait_for(self._caller(tool, args), self.timeout_s)
                return _unwrap(res)
            except MarketplaceError:
                raise  # a real answer such as a policy rejection: retrying will not help
            except Exception as e:  # transport errors, timeouts, outage, rate limit: all transient
                last = e
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff_s * 2 ** attempt)
        raise MarketplaceUnavailable(f"{tool} failed after {self.retries + 1} attempts: {last}")

    # MarketplacePort methods
    async def search_jobs(self, query: str = "", limit: int = 20, persona: str | None = None):
        args: dict[str, Any] = {"query": query, "limit": limit}
        if persona:
            args["persona"] = persona
        return await self.call("search_jobs", args)

    async def get_job(self, job_id: str):
        return await self.call("get_job", {"job_id": job_id})

    async def get_client_history(self, client_id: str):
        return await self.call("get_client_history", {"client_id": client_id})

    async def get_connects_balance(self):
        return await self.call("get_connects_balance", {})

    async def list_messages(self, client_id: str | None = None):
        return await self.call("list_messages", {"client_id": client_id} if client_id else {})

    async def get_policy(self):
        return await self.call("get_policy", {})

    async def create_proposal(self, payload: dict, idempotency_key: str, dry_run: bool = False):
        """Submits (or with dry_run previews) a proposal. Maps to the submit_proposal tool."""
        return await self.call("submit_proposal", {
            "job_id": payload["job_id"], "cover_letter": payload["cover_letter"],
            "bid_amount": payload["bid_amount"], "idempotency_key": idempotency_key,
            "dry_run": dry_run, "screening_answers": payload.get("screening_answers") or None})

    async def create_draft(self, payload: dict, idempotency_key: str, dry_run: bool = False):
        return await self.call("create_proposal_draft", {
            "job_id": payload["job_id"], "cover_letter": payload["cover_letter"],
            "bid_amount": payload["bid_amount"], "idempotency_key": idempotency_key,
            "dry_run": dry_run, "screening_answers": payload.get("screening_answers") or None})

    async def send_message(self, client_id: str, text: str, idempotency_key: str):
        return await self.call("send_message", {"client_id": client_id, "text": text,
                                                "idempotency_key": idempotency_key})
