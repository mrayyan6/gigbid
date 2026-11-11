"""Live Upwork adapter: the marketplace port over the official Upwork MCP server.

STATUS: written against the documented transport (Streamable HTTP, OAuth bearer) but never run
against a live account. Remote tool names are configuration (mcp.live.tool_map) because they must
be checked against the server's tools/list before first use.

Platform rules enforced here, not left to callers:
- Reads only on the schedule the worker uses (config mcp.live.poll_minutes). No scraping, no
  browser automation, no cookies. Only the official MCP endpoint with an OAuth access token.
- Writes create DRAFTS only. create_proposal returns a draft id and requires_platform_confirmation;
  submit_proposal always raises RequiresPlatformConfirmation. The user presses send on Upwork.
- Tokens come from the encrypted TokenStore and are never logged.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from agent.marketplace_port import (
    MarketplaceError,
    MarketplaceUnavailable,
    RequiresPlatformConfirmation,
)
from agent.security.tokens import TokenStore
from mcp_servers.common import cfg

Caller = Callable[[str, dict[str, Any]], Awaitable[Any]]  # (remote tool, args) -> CallToolResult

DEFAULT_TOOL_MAP = {  # port method -> remote tool name (assumed, verify with tools/list)
    "search_jobs": "search_jobs", "get_job": "get_job_details",
    "get_client_history": "get_client_profile", "get_connects_balance": "get_connects_balance",
    "list_messages": "list_messages", "create_draft": "create_proposal_draft",
}


def normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a remote job record onto the shape GigSim and the agents use."""
    budget = raw.get("budget")
    if isinstance(budget, (int, float)):
        budget = {"min": float(budget), "max": float(budget)}
    elif not isinstance(budget, dict):
        lo, hi = raw.get("hourlyRateMin", 0), raw.get("hourlyRateMax", 0)
        budget = {"min": float(lo or 0), "max": float(hi or 0)}
    skills = raw.get("skills") or raw.get("required_skills") or []
    return {"job_id": str(raw.get("id") or raw.get("job_id") or raw.get("ciphertext")),
            "title": raw.get("title", ""), "description": raw.get("description", ""),
            "required_skills": [s["name"] if isinstance(s, dict) else str(s) for s in skills],
            "budget": {"min": budget.get("min", 0), "max": budget.get("max", 0)},
            "client_id": raw.get("client_id") or (raw.get("client") or {}).get("id"),
            "connects_cost": raw.get("connects_cost") or raw.get("connectsRequired"),
            "source": "upwork_live"}


def _data(result: Any) -> Any:
    text = "".join(getattr(c, "text", "") for c in (result.content or []))
    if result.isError:
        raise MarketplaceError(text[:300])
    data = result.structuredContent
    if data is None:
        data = json.loads(text) if text else None
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    return data


def http_caller(token_provider: Callable[[], str], url: str | None = None) -> Caller:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    url = url or cfg("mcp.live.url", "https://mcp.upwork.com/mcp")

    async def call(tool: str, args: dict[str, Any]) -> Any:
        client = MultiServerMCPClient({"upwork": {
            "url": url, "transport": "streamable_http",
            "headers": {"Authorization": f"Bearer {token_provider()}"}}})
        async with client.session("upwork") as session:
            return await session.call_tool(tool, args)
    return call


class UpworkLiveAdapter:
    def __init__(self, user: str = "default", store: TokenStore | None = None,
                 caller: Caller | None = None, tool_map: dict[str, str] | None = None,
                 timeout_s: float | None = None):
        store = store or TokenStore()
        self.caller = caller or http_caller(lambda: store.load(user, "upwork"))
        self.tools = {**DEFAULT_TOOL_MAP, **(tool_map or cfg("mcp.live.tool_map", {}) or {})}
        self.timeout_s = timeout_s if timeout_s is not None else float(cfg("mcp.client.timeout_s", 15))

    async def _call(self, method: str, args: dict[str, Any]) -> Any:
        try:
            return _data(await asyncio.wait_for(self.caller(self.tools[method], args),
                                                self.timeout_s))
        except MarketplaceError:
            raise
        except Exception as e:  # transport, auth refresh needed, timeout
            raise MarketplaceUnavailable(f"upwork {method}: {type(e).__name__}") from e

    # MarketplacePort methods
    async def search_jobs(self, query: str = "", limit: int = 20, persona: str | None = None):
        rows = await self._call("search_jobs", {"query": query, "limit": limit})
        return [normalize_job(r) for r in (rows or [])]

    async def get_job(self, job_id: str):
        return normalize_job(await self._call("get_job", {"job_id": job_id}))

    async def get_client_history(self, client_id: str):
        data = await self._call("get_client_history", {"client_id": client_id}) or {}
        return {"client_id": client_id, **data}

    async def get_connects_balance(self):
        data = await self._call("get_connects_balance", {}) or {}
        return {"balance": int(data.get("balance", data.get("connects", 0)))}

    async def list_messages(self, client_id: str | None = None):
        return await self._call("list_messages", {"client_id": client_id} if client_id else {})

    async def get_policy(self):
        return {"version": None, "connects_multiplier": 1.0, "source": "upwork_live",
                "rules": ["drafts only", "user confirms on Upwork", "no off-platform contact"]}

    async def create_proposal(self, payload: dict, idempotency_key: str, dry_run: bool = False):
        """Dry run previews. Otherwise creates a DRAFT on Upwork, never a submitted proposal."""
        if dry_run:
            return {"dry_run": True, "would_send": payload, "connects_cost": None,
                    "requires_platform_confirmation": True}
        data = await self._call("create_draft", {**payload, "idempotency_key": idempotency_key}) or {}
        return {"proposal_id": data.get("id"), "status": "draft_created",
                "requires_platform_confirmation": True, **{k: payload[k] for k in ("job_id",)}}

    async def submit_proposal(self, *_: Any, **__: Any):
        raise RequiresPlatformConfirmation(
            "GigBid never submits on Upwork. Open the draft on Upwork and confirm there.")

    async def send_message(self, client_id: str, text: str, idempotency_key: str):
        raise RequiresPlatformConfirmation(
            "Live messages are not sent by GigBid. Copy the approved reply into Upwork.")
