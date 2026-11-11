# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.nodes.config import CFG
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import run_out, user_runs
from apps.api.schemas import DraftIn, DraftOut, MessagesOut, MessageThreadOut, UserOut

router = APIRouter(prefix="/messages", tags=["messages"])


async def _my_clients(ctx: AppCtx, user: UserOut) -> set[str]:
    """Tenant scope: only clients of jobs this user ran."""
    out = set()
    for row in await user_runs(ctx, user):
        run = await run_out(ctx, row)
        if (run.job or {}).get("client_id"):
            out.add(run.job["client_id"])
    return out


@router.get("", response_model=MessagesOut, operation_id="list_messages")
async def list_messages(user: UserOut = Depends(get_current_user),
                        ctx: AppCtx = Depends(get_ctx)) -> MessagesOut:
    mine = await _my_clients(ctx, user)
    threads: dict[str, list] = {}
    for m in await ctx.mp.list_messages():
        if m.get("client_id") in mine:
            threads.setdefault(m["client_id"], []).append(m)
    return MessagesOut(threads=[MessageThreadOut(client_id=c, messages=ms)
                                for c, ms in sorted(threads.items())])


def classify_intent(text: str) -> str:
    """Regex intent classifier from config. TODO(graph lane): replace with the conversation graph
    (agent/graphs/conversation_graph.py is still empty), which uses the intent prompt and an LLM."""
    conv = CFG["conversation"]
    low = text.lower()
    for intent in conv["intent_order"]:
        if any(p in low for p in conv["intent_patterns"][intent]):
            return intent
    return conv["default_intent"]


@router.post("/{client_id}/draft", response_model=DraftOut, operation_id="draft_reply")
async def draft_reply(client_id: str, body: DraftIn | None = None,
                      user: UserOut = Depends(get_current_user),
                      ctx: AppCtx = Depends(get_ctx)) -> DraftOut:
    """Suggest a reply to the latest client message. Nothing is sent: sending needs approval."""
    if client_id not in await _my_clients(ctx, user):
        raise HTTPException(404, "unknown client")
    msgs = [m for m in await ctx.mp.list_messages(client_id) if m.get("from") == "client"]
    if not msgs:
        raise HTTPException(409, "no client message to answer")
    intent = classify_intent(msgs[-1]["text"])
    t = CFG["conversation"]["templates"]
    slots: list[dict] = []  # TODO: Workspace MCP free_slots (server not implemented yet)
    text = t["interview_no_slots"] if intent == "interview_request" and not slots else (
        t[intent].replace("{slots}", ", ".join(s["start"] for s in slots)))
    # body.instruction is accepted for the contract; the LLM liaison will use it (TODO).
    return DraftOut(client_id=client_id, intent=intent, draft=text, slots=slots,
                    status="flagged" if intent == "scam_signal" else "awaiting_approval")
