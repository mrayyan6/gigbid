"""Run execution shared by the API (inline mode) and the Arq worker.

A "run" is one bid-graph thread, `thread_id = {user_id}:{job_id}`. State of record is the
LangGraph checkpoint (pending approvals are read from it, so a refresh or restart loses nothing).
The `runs` table only indexes threads by tenant for listing and analytics.

Graph API used (public only): build_bid_graph(saver).astream/ainvoke/aget_state, Command(resume=...).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from langgraph.types import Command

from agent.marketplace_port import MarketplaceUnavailable
from apps.api.context import AppCtx

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
KNOWN_STATUS = {"queued", "running", "awaiting_approval", "completed", "skipped", "blocked",
                "rejected", "needs_attention", "failed"}


def thread_id_for(user_id: str, job_id: str) -> str:
    return f"{user_id}:{job_id}"


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_trace_id() -> str:
    return uuid.uuid4().hex


class RunChannel:
    """In process event buffer so SSE clients can attach before, during or after a run."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.cond = asyncio.Condition()

    async def publish(self, event: str, data: Any, final: bool = False) -> None:
        async with self.cond:
            self.events.append({"event": event, "data": json.loads(json.dumps(
                jsonable_encoder(data, custom_encoder={}), default=str))})
            self.done = self.done or final
            self.cond.notify_all()


def graph_config(ctx: AppCtx, user_id: str, persona: str, tid: str, trace_id: str | None) -> dict:
    retr = ctx.retrievers.get(persona)
    if retr is None:
        from rag.retriever import get_retriever
        retr = ctx.retrievers.setdefault(persona, get_retriever("v2_hybrid", persona))
    return {"configurable": {"thread_id": tid, "marketplace": ctx.mp, "retriever": retr,
                             "user_id": user_id, "memory": ctx.memory, "trace_id": trace_id},
            "metadata": {"trace_id": trace_id, "user_id": user_id, "job_thread": tid},
            "tags": ["gigbid", f"user:{user_id}"]}


def status_of(values: dict, nxt: list, interrupts: list) -> str:
    """Status from a checkpoint snapshot. A snapshot taken mid superstep can show no pending nodes
    and no result, so anything without explicit terminal evidence is reported as running."""
    if interrupts:
        return "awaiting_approval"
    st = values.get("status")  # set by the graph lane for needs_attention and dead letter
    if st in KNOWN_STATUS and st != "running":
        return st
    if values.get("outcome"):
        return "completed"
    if (values.get("approval") or {}).get("action") == "reject":
        return "rejected"
    cv = values.get("compliance_verdict")
    if cv is not None and not cv.get("allowed", True):
        return "blocked"
    if (values.get("decision") or {}).get("action") in ("skip", "watch"):
        return "skipped"
    return "running" if values else "queued"


async def snapshot(ctx: AppCtx, user_id: str, persona: str, tid: str):
    return await ctx.graph.aget_state(graph_config(ctx, user_id, persona, tid, None))


def describe(snap) -> tuple[str, list]:
    pending = [i.value for t in snap.tasks for i in t.interrupts]
    return status_of(snap.values or {}, list(snap.next), pending), pending


def settle(ctx: AppCtx, tid: str, computed: str, row_status: str) -> str:
    """Refine a snapshot status. `running` from a snapshot is only believed while a run is live
    in this process or the table says so; a crashed or failed run keeps the table status."""
    if computed != "running":
        return computed
    chan = ctx.hub.get(tid)
    if chan is not None and not chan.done:
        return "running"
    return row_status if row_status in ("queued", "failed", "running") else "running"


async def set_run(ctx: AppCtx, tid: str, user_id: str, job_id: str, persona: str, status: str,
                  trace_id: str | None) -> None:
    ts = now()
    await ctx.db.execute(
        "INSERT INTO runs (thread_id,user_id,job_id,persona,status,trace_id,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (thread_id) DO UPDATE SET "
        "status=excluded.status, updated_at=excluded.updated_at, "
        "trace_id=COALESCE(excluded.trace_id, runs.trace_id)",
        (tid, user_id, job_id, persona, status, trace_id, ts, ts))


async def execute_run(ctx: AppCtx, user_id: str, persona: str, job_id: str, tid: str,
                      trace_id: str | None, resume: dict | None = None,
                      fresh: bool = True, restart: bool = False) -> str:
    """Drive the graph until it ends or hits interrupt(). Returns the resulting status.

    fresh=True starts the thread, resume=... answers an interrupt, fresh=False with no resume
    continues an interrupted-by-crash thread from its last checkpoint (input None).
    """
    chan = ctx.hub.setdefault(tid, RunChannel()) if resume is None else None
    cfg = graph_config(ctx, user_id, persona, tid, trace_id)
    if resume is not None:
        inp: Any = Command(resume=resume)
    else:
        inp = {"job_id": job_id} if fresh else None
        if restart:  # graph parked the thread as queued (marketplace outage): rerun from the start
            inp = {"job_id": job_id, "status": "running"}
    await set_run(ctx, tid, user_id, job_id, persona, "running", trace_id)
    try:
        async for mode, chunk in ctx.graph.astream(inp, cfg, stream_mode=["updates", "custom"]):
            if chan is None:
                continue
            if mode == "updates":
                for node, upd in chunk.items():
                    if node == "__interrupt__":
                        await chan.publish("interrupt", {"payload": [i.value for i in upd]})
                    else:
                        await chan.publish("node", {"node": node, "update": upd})
            else:
                await chan.publish("custom", chunk)
        snap = await ctx.graph.aget_state(cfg)
        status, _ = describe(snap)
        if status == "running":  # graph ended with no terminal marker: settled, not running
            status = "completed"
    except MarketplaceUnavailable as e:
        status = "queued"
        if chan:
            await chan.publish("error", {"detail": f"marketplace unavailable: {e}", "queued": True})
    except Exception as e:
        status = "failed"
        if chan:
            await chan.publish("error", {"detail": type(e).__name__ + ": " + str(e)[:300]})
    await set_run(ctx, tid, user_id, job_id, persona, status, trace_id)
    if chan:
        await chan.publish("status", {"status": status}, final=True)
    return status


async def dispatch_run(ctx: AppCtx, user_id: str, persona: str, job_id: str, tid: str,
                       trace_id: str | None) -> str:
    """Enqueue to Arq when Redis is configured, else run as an in process background task."""
    await set_run(ctx, tid, user_id, job_id, persona, "queued", trace_id)
    if ctx.arq is not None:
        await ctx.arq.enqueue_job("run_bid_thread", user_id, job_id, persona, tid, trace_id,
                                  _job_id=f"bid:{tid}")  # same _job_id is deduped by Arq
    else:  # dev fallback, documented in docs/RUNBOOK.md
        ctx.hub[tid] = RunChannel()
        t = asyncio.create_task(execute_run(ctx, user_id, persona, job_id, tid, trace_id))
        ctx.tasks.add(t)
        t.add_done_callback(ctx.tasks.discard)
    return "queued"


async def drain_queued(ctx: AppCtx) -> int:
    """Marketplace recovered: start every run that was queued while it was down."""
    if ctx.drain_lock.locked():
        return 0
    async with ctx.drain_lock:
        rows = await ctx.db.fetchall("SELECT * FROM runs WHERE status=%s", ("queued",))
        for r in rows:
            live = ctx.hub.get(r["thread_id"])
            if live is not None and not live.done:
                continue  # still being executed, not a parked run
            snap = await snapshot(ctx, r["user_id"], r["persona"], r["thread_id"])
            if snap.values and snap.values.get("status") == "queued":
                await execute_run(ctx, r["user_id"], r["persona"], r["job_id"], r["thread_id"],
                                  r["trace_id"], restart=True)
            elif snap.values and snap.next:  # crashed mid run: continue from the checkpoint
                await execute_run(ctx, r["user_id"], r["persona"], r["job_id"], r["thread_id"],
                                  r["trace_id"], fresh=False)
            else:
                await dispatch_run(ctx, r["user_id"], r["persona"], r["job_id"], r["thread_id"],
                                   r["trace_id"])
        return len(rows)
