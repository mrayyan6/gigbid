"""FastAPI backend. Runs bid-graph threads and resumes them on approval.

Auth is a stub (single dev token); multi-user auth, SSE streaming and Postgres are TODO.
Run: uvicorn apps.api.main:app --port 8000 (GigSim on :9000).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from agent.graphs.bid_graph import build_bid_graph
from agent.marketplace_port import get_marketplace
from rag.retriever import get_retriever

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = os.environ.get("CHECKPOINT_DB", "data/processed/checkpoints.sqlite")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        state["graph"] = build_bid_graph(saver)
        state["mp"] = get_marketplace()
        state["retr"] = {}
        yield


app = FastAPI(title="GigBid API", version="0.1.0", lifespan=lifespan)


def _cfg(thread_id: str, persona: str) -> dict:
    retr = state["retr"].setdefault(persona, get_retriever("v2_hybrid", persona))
    return {"configurable": {"thread_id": thread_id, "marketplace": state["mp"], "retriever": retr}}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gigbid-api"}


@app.get("/jobs")
async def jobs(persona: str = "ai_ml", limit: int = 20):
    return await state["mp"].search_jobs(limit=limit, persona=persona)


class RunIn(BaseModel):
    job_id: str
    persona: str = "ai_ml"


@app.post("/runs")
async def start_run(body: RunIn):
    tid = f"run-{body.job_id}"
    out = await state["graph"].ainvoke({"job_id": body.job_id}, _cfg(tid, body.persona))
    return _summary(tid, out)


@app.get("/runs/{thread_id}")
async def get_run(thread_id: str, persona: str = "ai_ml"):
    snap = await state["graph"].aget_state(_cfg(thread_id, persona))
    if not snap.values:
        raise HTTPException(404, "unknown run")
    pending = [i.value for t in snap.tasks for i in t.interrupts]
    return {"thread_id": thread_id, "next": list(snap.next), "pending_approval": pending,
            "values": snap.values}


class ApprovalIn(BaseModel):
    action: str  # approve | edit | reject
    text: str | None = None
    reason: str | None = None


@app.post("/runs/{thread_id}/approval")
async def approve(thread_id: str, body: ApprovalIn, persona: str = "ai_ml"):
    if body.action not in ("approve", "edit", "reject"):
        raise HTTPException(422, "bad action")
    out = await state["graph"].ainvoke(Command(resume=body.model_dump()), _cfg(thread_id, persona))
    return _summary(thread_id, out)


def _summary(tid: str, out: dict) -> dict:
    return {"thread_id": tid, "decision": out.get("decision"),
            "pending_approval": [i.value for i in out.get("__interrupt__", [])],
            "outcome": out.get("outcome")}
