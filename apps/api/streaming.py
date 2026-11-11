"""SSE for a run. Two sources, same event names (node, custom, interrupt, status, error, done):

1. In process: the run is executing in this API process, events come from graph.astream
   (stream_mode=["updates","custom"]) via the RunChannel buffer. Late subscribers replay the buffer.
2. Checkpoint polling: the run is executing in the Arq worker, or already finished, or the API
   restarted. Trace entries are read from the checkpoint and emitted as node events.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.encoders import jsonable_encoder
from sse_starlette.sse import EventSourceResponse

from agent.nodes.config import CFG
from apps.api import runner
from apps.api.context import AppCtx


def _sse(event: str, data: Any, id_: int | None = None) -> dict:
    out = {"event": event, "data": json.dumps(jsonable_encoder(data), default=str)}
    if id_ is not None:
        out["id"] = str(id_)
    return out


async def _from_channel(chan: runner.RunChannel) -> AsyncIterator[dict]:
    i = 0
    while True:
        async with chan.cond:
            await chan.cond.wait_for(lambda: len(chan.events) > i or chan.done)  # noqa: B023
            batch, i, done = chan.events[i:], len(chan.events), chan.done
        for n, ev in enumerate(batch):
            yield _sse(ev["event"], ev["data"], i - len(batch) + n)
        if done:
            return


async def _from_checkpoint(ctx: AppCtx, row: dict) -> AsyncIterator[dict]:
    cfg = CFG["api"]
    seen = 0
    waited = 0.0
    while waited <= cfg["stream_max_seconds"]:
        snap = await runner.snapshot(ctx, row["user_id"], row["persona"], row["thread_id"])
        status, pending = runner.describe(snap) if snap.values else ("queued", [])
        trace = (snap.values or {}).get("trace", [])
        for entry in trace[seen:]:
            yield _sse("node", {"node": entry.get("node"), "update": {"trace": [entry]}})
        seen = len(trace)
        if pending:
            yield _sse("interrupt", {"payload": pending})
        if status not in ("queued", "running"):
            yield _sse("status", {"status": status})
            return
        await asyncio.sleep(cfg["stream_poll_interval_s"])
        waited += cfg["stream_poll_interval_s"]
    yield _sse("status", {"status": "running", "timeout": True})


def run_event_response(ctx: AppCtx, row: dict) -> EventSourceResponse:
    chan = ctx.hub.get(row["thread_id"])
    gen = _from_channel(chan) if chan is not None else _from_checkpoint(ctx, row)

    async def with_done() -> AsyncIterator[dict]:
        async for ev in gen:
            yield ev
        yield _sse("done", {"thread_id": row["thread_id"]})

    return EventSourceResponse(with_done(), headers={"Cache-Control": "no-cache",
                                                     "X-Accel-Buffering": "no"})
