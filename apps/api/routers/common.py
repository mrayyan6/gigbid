"""Helpers shared by routers. Every query here is scoped by the authenticated user id."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from apps.api import runner
from apps.api.context import AppCtx
from apps.api.schemas import JobOut, RunOut, UserOut


async def owned_run(ctx: AppCtx, user: UserOut, tid: str) -> dict[str, Any]:
    """Return the runs row if it belongs to this user, else 404 (never reveal other tenants)."""
    row = await ctx.db.fetchone("SELECT * FROM runs WHERE thread_id=%s AND user_id=%s",
                                (tid, user.id))
    if row is None:
        raise HTTPException(404, "unknown run")
    return row


async def user_runs(ctx: AppCtx, user: UserOut, statuses: tuple[str, ...] | None = None) -> list:
    if statuses:
        marks = ",".join(["%s"] * len(statuses))
        return await ctx.db.fetchall(
            f"SELECT * FROM runs WHERE user_id=%s AND status IN ({marks}) ORDER BY created_at DESC",
            (user.id, *statuses))
    return await ctx.db.fetchall("SELECT * FROM runs WHERE user_id=%s ORDER BY created_at DESC",
                                 (user.id,))


async def run_out(ctx: AppCtx, row: dict[str, Any]) -> RunOut:
    """Build RunOut from the checkpoint (source of truth), not from the runs table."""
    snap = await runner.snapshot(ctx, row["user_id"], row["persona"], row["thread_id"])
    v = snap.values or {}
    status, pending = runner.describe(snap) if snap.values else (row["status"], [])
    status = runner.settle(ctx, row["thread_id"], status, row["status"])
    if status != row["status"] and snap.values:
        await runner.set_run(ctx, row["thread_id"], row["user_id"], row["job_id"], row["persona"],
                             status, None)
    return RunOut(
        thread_id=row["thread_id"], job_id=row["job_id"], status=status, next=list(snap.next),
        pending_approval=pending, job=v.get("job"), job_spec=v.get("job_spec"),
        risk_report=v.get("risk_report"), fit_report=v.get("fit_report"),
        evidence=v.get("evidence", []), decision=v.get("decision"), price_quote=v.get("price_quote"),
        proposal_draft=v.get("proposal_draft"), claim_verification=v.get("claim_verification", []),
        critique=v.get("critique"), compliance_verdict=v.get("compliance_verdict"),
        approval=v.get("approval"), outcome=v.get("outcome"), trace=v.get("trace", []),
        errors=v.get("errors", []), trace_id=row.get("trace_id"))


def job_out(raw: dict[str, Any], run: RunOut | None = None) -> JobOut:
    b = raw.get("budget") or {}
    badges = list(raw.get("warning_signals") or [])
    if run and run.risk_report:
        badges = sorted(set(badges) | set(run.risk_report.get("flags", [])))
    action = (run.decision or {}).get("action") if run else None
    return JobOut(
        job_id=raw["job_id"], title=raw.get("title", ""), description=raw.get("description", ""),
        required_skills=raw.get("required_skills", []), budget_min=b.get("min", 0),
        budget_max=b.get("max", 0), currency=b.get("currency", "USD"),
        connects_cost=raw.get("connects_cost", 0), client_id=raw.get("client_id"),
        risk_badges=badges,
        fit_score=(run.fit_report or {}).get("score") if run else None,
        recommended_action=action if action in ("bid", "watch", "skip") else "unscored",
        price=(run.price_quote or {}).get("amount") if run else None,
        thread_id=run.thread_id if run else None, run_status=run.status if run else None)
