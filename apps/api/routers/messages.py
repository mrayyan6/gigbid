# ruff: noqa: B008
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command

from agent.nodes import core
from agent.nodes.config import CFG
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import run_out, user_runs
from apps.api.schemas import (
    DraftIn,
    DraftOut,
    MessagesOut,
    MessageThreadOut,
    SendIn,
    SendOut,
    UserOut,
)

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


async def _free_slots(ctx: AppCtx) -> list[dict]:
    """Interview slots from the Workspace MCP server. If it is down or not configured the reply is drafted
    without slots (degraded), never an error."""
    if ctx.workspace is None:
        return []
    c = CFG["conversation"]
    today = date.today()
    try:
        slots = await ctx.workspace.free_slots(today.isoformat(), (today + timedelta(days=c["slot_days_ahead"])).isoformat(),
                                               c["slot_duration_min"])
    except Exception:
        return []
    return slots[: c["max_slots_offered"]]


def _conv_config(ctx: AppCtx, user: UserOut, client_id: str) -> dict:
    """One graph thread per client conversation, scoped to the user so tenants never share a thread."""
    return {"configurable": {"thread_id": f"conv:{user.id}:{client_id}", "marketplace": ctx.mp,
                             "workspace": ctx.workspace, "user_id": user.id, "memory": ctx.memory}}


def _pending(snapshot) -> dict | None:
    """The payload of an approval interrupt that is waiting for the user, if any."""
    for task in getattr(snapshot, "tasks", ()) or ():
        for it in getattr(task, "interrupts", ()) or ():
            return it.value
    return None


def _draft_out(client_id: str, p: dict) -> DraftOut:
    return DraftOut(client_id=client_id, intent=p["intent"], draft=p["draft"],
                    slots=[{"start": s} if isinstance(s, str) else s for s in p.get("slots", [])],
                    status="flagged" if p.get("flagged") else "awaiting_approval")


async def _draft_with_graph(ctx: AppCtx, user: UserOut, client_id: str) -> DraftOut:
    """Run the conversation graph to its approval interrupt. Calling it again while a draft is waiting returns
    that same draft, so the pending approval is never replaced by accident."""
    cfg = _conv_config(ctx, user, client_id)
    waiting = _pending(await ctx.conv_graph.aget_state(cfg))
    if waiting is None:
        out = await ctx.conv_graph.ainvoke({"client_id": client_id}, cfg)
        interrupts = out.get("__interrupt__")
        if not interrupts:
            raise RuntimeError(f"conversation graph ended with status {out.get('status')}")
        waiting = interrupts[0].value
    return _draft_out(client_id, waiting)


def _rule_draft(client_id: str, text: str, slots: list[dict]) -> DraftOut:
    """The earlier rule based draft, kept as a fallback when the graph cannot run."""
    intent = classify_intent(text)
    t = CFG["conversation"]["templates"]
    if intent == "interview_request":
        body = t["interview_request"].replace("{slots}", "; ".join(s["start"].replace("T", " ") for s in slots))             if slots else t["interview_no_slots"]
    else:
        body = t[intent]
    return DraftOut(client_id=client_id, intent=intent, draft=body, slots=slots,
                    status="flagged" if intent == "scam_signal" else "awaiting_approval")


@router.post("/{client_id}/draft", response_model=DraftOut, operation_id="draft_reply")
async def draft_reply(client_id: str, body: DraftIn | None = None,
                      user: UserOut = Depends(get_current_user),
                      ctx: AppCtx = Depends(get_ctx)) -> DraftOut:
    """Suggest a reply to the latest client message with the conversation graph (read, classify intent, draft or
    propose interview slots, then an approval interrupt). Nothing is sent: sending needs approval."""
    if client_id not in await _my_clients(ctx, user):
        raise HTTPException(404, "unknown client")
    msgs = [m for m in await ctx.mp.list_messages(client_id) if m.get("from") == "client"]
    if not msgs:
        raise HTTPException(409, "no client message to answer")
    if ctx.conv_graph is not None:
        try:
            return await _draft_with_graph(ctx, user, client_id)
        except Exception:
            pass
    intent = classify_intent(msgs[-1]["text"])
    slots = await _free_slots(ctx) if intent == "interview_request" else []
    return _rule_draft(client_id, msgs[-1]["text"], slots)


@router.post("/{client_id}/send", response_model=SendOut, operation_id="send_reply")
async def send_reply(client_id: str, body: SendIn, user: UserOut = Depends(get_current_user),
                     ctx: AppCtx = Depends(get_ctx)) -> SendOut:
    """Send a reply the user has approved (the click on Approve and send is the approval).

    The text is re-checked against the platform policy first. The idempotency key is derived from the
    user, the client and the exact text, so a double click or a retry never sends the message twice."""
    if client_id not in await _my_clients(ctx, user):
        raise HTTPException(404, "unknown client")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "reply is empty")
    if ctx.conv_graph is not None:
        cfg = _conv_config(ctx, user, client_id)
        snap = await ctx.conv_graph.aget_state(cfg)
        waiting = _pending(snap)
        if waiting is not None:
            # resume the interrupted conversation thread: approve as drafted, or edit (Compliance re-checks)
            action = "approve" if text == waiting["draft"] else "edit"
            out = await ctx.conv_graph.ainvoke(Command(resume={"action": action, "text": text}), cfg)
            if out.get("status") == "rejected":
                reason = (out.get("approval") or {}).get("reason", "rejected")
                raise HTTPException(422, f"reply breaks the platform policy: {reason}")
            if out.get("status") != "sent":
                raise HTTPException(409, f"reply was not sent (status {out.get('status')})")
            rec = out.get("outcome") or {}
            return SendOut(client_id=client_id, message_id=rec.get("message_id"),
                           idempotent_replay=bool(rec.get("idempotent_replay")))
        done = snap.values or {}
        if done.get("status") == "sent" and (done.get("draft") or "").strip() == text:
            rec = done.get("outcome") or {}  # a double click after the send: report it, never send again
            return SendOut(client_id=client_id, message_id=rec.get("message_id"), idempotent_replay=True)
    bad = core.violations(text, await ctx.mp.get_policy())
    if bad:
        raise HTTPException(422, f"reply breaks the platform policy: {', '.join(bad)}")
    key = hashlib.sha256(f"{user.id}|{client_id}|{text}".encode()).hexdigest()[:32]
    rec = await ctx.mp.send_message(client_id, text, key)
    return SendOut(client_id=client_id, message_id=rec.get("message_id"),
                   idempotent_replay=bool(rec.get("idempotent_replay")))
