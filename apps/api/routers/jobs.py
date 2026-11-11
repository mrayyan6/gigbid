# ruff: noqa: B008
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import job_out, run_out, user_runs
from apps.api.runner import thread_id_for
from apps.api.schemas import JobDetailOut, JobOut, UserOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut], operation_id="list_jobs")
async def list_jobs(limit: int = Query(20, ge=1, le=300), query: str = "",
                    user: UserOut = Depends(get_current_user),
                    ctx: AppCtx = Depends(get_ctx)) -> list[JobOut]:
    """Inbox: jobs for the user's persona, ranked by fit (scored runs first), then low risk."""
    raws = await ctx.mp.search_jobs(query=query, limit=limit, persona=user.persona)
    runs = {r["job_id"]: r for r in await user_runs(ctx, user)}
    outs = await asyncio.gather(*[run_out(ctx, runs[j["job_id"]]) if j["job_id"] in runs
                                  else _none() for j in raws])
    jobs = [job_out(j, o) for j, o in zip(raws, outs, strict=True)]
    # TODO(graph lane): rank unscored jobs with a real fit score once a cheap scorer is exposed.
    jobs.sort(key=lambda j: (-(j.fit_score if j.fit_score is not None else -1),
                             len(j.risk_badges), -j.budget_max))
    return jobs


async def _none():
    return None


@router.get("/{job_id}", response_model=JobDetailOut, operation_id="get_job")
async def get_job(job_id: str, user: UserOut = Depends(get_current_user),
                  ctx: AppCtx = Depends(get_ctx)) -> JobDetailOut:
    raw = await ctx.mp.get_job(job_id)
    if not raw:
        raise HTTPException(404, "job not found")
    row = await ctx.db.fetchone("SELECT * FROM runs WHERE thread_id=%s AND user_id=%s",
                                (thread_id_for(user.id, job_id), user.id))
    run = await run_out(ctx, row) if row else None
    return JobDetailOut(job=job_out(raw, run), raw=raw, run=run)
