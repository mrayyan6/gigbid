"""Marketplace MCP server (FastMCP `gigbid-marketplace`).

Wraps a marketplace adapter (GigSim by default, chosen by MARKETPLACE_MODE) behind typed tools.
Read tools are readOnly. Write tools need an idempotency_key and support dry_run, which returns
the exact payload and the Connects cost without sending or spending anything.

Run: python -m mcp_servers.marketplace.server            (stdio)
     python -m mcp_servers.marketplace.server --http     (streamable HTTP, bearer token required)
Env: MARKETPLACE_MCP_TOKEN (HTTP bearer), MARKETPLACE_MODE, MARKETPLACE_RATE_PER_MIN, AUDIT_LOG_PATH.
"""
from __future__ import annotations

import functools
import hashlib
import os
import sys
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from agent.marketplace_port import MarketplaceUnavailable, get_marketplace
from mcp_servers.common import BearerAuthMiddleware, cfg, current_trace, current_user
from mcp_servers.marketplace.audit import AuditLog
from mcp_servers.marketplace.ratelimit import RateLimited, TokenBucket
from mcp_servers.marketplace.schemas import (
    ClientHistory,
    ConnectsBalance,
    Job,
    Message,
    MessageResult,
    Policy,
    ProposalResult,
)

mcp = FastMCP("gigbid-marketplace",
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                       openWorldHint=True)
DRAFT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                        openWorldHint=False)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True,
                       openWorldHint=True)

IdemKey = Annotated[str, Field(min_length=8, max_length=128,
                               description="Unique key per logical write. Same key returns the "
                                           "same result and never repeats the side effect.")]
DryRun = Annotated[bool, Field(description="True returns the exact payload and cost, sends nothing")]


class _Ctx:
    adapter: Any = None
    audit: AuditLog | None = None
    limiter: TokenBucket | None = None
    drafts: dict[str, dict] = {}


_ctx = _Ctx()


def configure(adapter=None, audit_path=None, rate_per_min: int | None = None, clock=None) -> None:
    """Inject collaborators (tests, or the HTTP entry point). Resets drafts and rate state."""
    _ctx.adapter = adapter
    _ctx.audit = AuditLog(audit_path or os.environ.get("AUDIT_LOG_PATH") or None)
    rate = rate_per_min or int(os.environ.get("MARKETPLACE_RATE_PER_MIN", 0)) \
        or int(cfg("mcp.marketplace.rate_per_min", 60))
    _ctx.limiter = TokenBucket(rate, **({"clock": clock} if clock else {}))
    _ctx.drafts = {}


def _adapter():
    if _ctx.adapter is None:
        mode = os.environ.get("MARKETPLACE_BACKEND") or os.environ.get("MARKETPLACE_MODE", "gigsim")
        _ctx.adapter = get_marketplace("gigsim" if mode == "mcp" else mode)  # never wrap ourselves
    return _ctx.adapter


def _guard(fn):
    """Rate limit per user, write an audit line for every call, map errors to tool errors."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        if _ctx.limiter is None:
            configure()
        user, trace = current_user.get(), current_trace.get()
        summary = "ok"
        try:
            _ctx.limiter.take(user)
            out = await fn(*args, **kwargs)
            if isinstance(out, list):
                summary = f"ok n={len(out)}"
            elif getattr(out, "dry_run", False):
                summary = "ok dry_run"
            return out
        except RateLimited as e:
            summary = f"error {e}"
            raise ToolError(str(e)) from e
        except MarketplaceUnavailable as e:
            summary = f"error marketplace_unavailable {e}"
            raise ToolError(f"marketplace_unavailable: {e}") from e
        except httpx.HTTPStatusError as e:
            summary = f"error http {e.response.status_code}"
            raise ToolError(f"marketplace_error {e.response.status_code}: "
                            f"{e.response.text[:200]}") from e
        except Exception as e:
            summary = f"error {type(e).__name__}"
            raise
        finally:
            _ctx.audit.write(user=user, tool=fn.__name__, trace_id=trace, result=summary,
                             args={k: v for k, v in kwargs.items()})
    return wrapper


@mcp.tool(annotations=READ)
@_guard
async def search_jobs(query: str = "", limit: Annotated[int, Field(ge=1, le=100)] = 20,
                      persona: str | None = None) -> list[Job]:
    """Search the marketplace job feed by text. Returns public job fields and the current
    Connects cost per proposal."""
    return [Job.model_validate(j) for j in await _adapter().search_jobs(query, limit, persona)]


@mcp.tool(annotations=READ)
@_guard
async def get_job(job_id: str) -> Job:
    """Get one job by id, including budget, required skills and Connects cost."""
    return Job.model_validate(await _adapter().get_job(job_id))


@mcp.tool(annotations=READ)
@_guard
async def get_client_history(client_id: str) -> ClientHistory:
    """Get a client's public history: payment verification, spend, hire rate, past reviews."""
    return ClientHistory.model_validate(await _adapter().get_client_history(client_id))


@mcp.tool(annotations=READ)
@_guard
async def get_connects_balance() -> ConnectsBalance:
    """Return the freelancer's current Connects balance."""
    return ConnectsBalance.model_validate(await _adapter().get_connects_balance())


@mcp.tool(annotations=READ)
@_guard
async def list_messages(client_id: str | None = None) -> list[Message]:
    """List messages, optionally only the conversation with one client."""
    return [Message.model_validate(m) for m in await _adapter().list_messages(client_id)]


@mcp.tool(annotations=READ)
@_guard
async def get_policy() -> Policy:
    """Return the current platform policy: Connects multiplier, minimum budget, limits, rules."""
    return Policy.model_validate(await _adapter().get_policy())


@mcp.tool(annotations=DRAFT)
@_guard
async def create_proposal_draft(job_id: str, cover_letter: Annotated[str, Field(min_length=1)],
                                bid_amount: Annotated[float, Field(ge=0)],
                                idempotency_key: IdemKey, dry_run: DryRun = False,
                                screening_answers: list[str] | None = None) -> ProposalResult:
    """Store a proposal draft on the server. Spends no Connects and sends nothing to the client.
    dry_run returns the exact payload and the Connects cost a later submit would incur."""
    payload = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount,
               "screening_answers": screening_answers or []}
    if dry_run:
        pre = await _adapter().create_proposal(payload, idempotency_key, dry_run=True)
        return ProposalResult.model_validate(pre)
    draft_id = "draft-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]
    replay = draft_id in _ctx.drafts
    _ctx.drafts.setdefault(draft_id, payload)
    return ProposalResult(draft_id=draft_id, status="draft", would_send=_ctx.drafts[draft_id],
                          idempotent_replay=replay)


@mcp.tool(annotations=SEND)
@_guard
async def submit_proposal(job_id: str, cover_letter: Annotated[str, Field(min_length=1)],
                          bid_amount: Annotated[float, Field(ge=0)], idempotency_key: IdemKey,
                          dry_run: DryRun = False,
                          screening_answers: list[str] | None = None) -> ProposalResult:
    """Submit a proposal to the client. Spends Connects. Call only after human approval. The
    same idempotency_key submits at most once. dry_run previews payload and cost."""
    payload = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount,
               "screening_answers": screening_answers or []}
    rec = await _adapter().create_proposal(payload, idempotency_key, dry_run=dry_run)
    return ProposalResult.model_validate(rec)


@mcp.tool(annotations=SEND)
@_guard
async def send_message(client_id: str, text: Annotated[str, Field(min_length=1)],
                       idempotency_key: IdemKey, dry_run: DryRun = False) -> MessageResult:
    """Send a message to a client. Call only after human approval. The same idempotency_key
    sends at most once. dry_run returns the exact message without sending."""
    if dry_run:
        return MessageResult(dry_run=True, would_send={"client_id": client_id, "text": text})
    return MessageResult.model_validate(
        await _adapter().send_message(client_id, text, idempotency_key))


def http_app():
    """Streamable HTTP ASGI app guarded by the bearer token."""
    token = os.environ.get("MARKETPLACE_MCP_TOKEN")
    if not token:
        raise RuntimeError("MARKETPLACE_MCP_TOKEN must be set for HTTP transport")
    return BearerAuthMiddleware(mcp.streamable_http_app(), token)


def main() -> None:
    configure()
    if "--http" in sys.argv:
        import uvicorn
        port = int(os.environ.get("MARKETPLACE_MCP_PORT", cfg("mcp.marketplace.port", 9100)))
        uvicorn.run(http_app(), host=os.environ.get("MCP_HOST", "127.0.0.1"), port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
