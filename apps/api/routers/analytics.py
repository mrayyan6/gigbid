# ruff: noqa: B008
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends

from agent.marketplace_port import MarketplaceUnavailable
from apps.api.auth import get_current_user
from apps.api.context import AppCtx, get_ctx
from apps.api.routers.common import run_out, user_runs
from apps.api.schemas import AnalyticsOut, ReasonCount, UserOut

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsOut, operation_id="get_analytics")
async def analytics(user: UserOut = Depends(get_current_user),
                    ctx: AppCtx = Depends(get_ctx)) -> AnalyticsOut:
    try:
        replied_clients = {m.get("client_id") for m in await ctx.mp.list_messages()
                           if m.get("from") == "client"}
    except MarketplaceUnavailable:
        replied_clients = set()
    by_status, by_action, reasons = Counter(), Counter(), Counter()
    submitted = replied = spent = steps = n = 0
    for row in await user_runs(ctx, user):
        run = await run_out(ctx, row)
        n += 1
        by_status[run.status] += 1
        action = (run.decision or {}).get("action")
        if action:
            by_action[action] += 1
        if run.outcome and run.outcome.get("proposal_id"):
            submitted += 1
            spent += int(run.outcome.get("connects_spent", 0))
            replied += int((run.job or {}).get("client_id") in replied_clients)
        reason = (run.approval or {}).get("reason") if run.status == "rejected" else None
        if run.status == "blocked":
            reason = "compliance: " + "; ".join((run.compliance_verdict or {}).get("reasons", []) or
                                                 ["blocked"])
        if reason:
            reasons[reason] += 1
        steps += len(run.trace)
    return AnalyticsOut(
        runs_total=n, by_status=dict(by_status), by_action=dict(by_action), submitted=submitted,
        rejected=by_status["rejected"], connects_spent=spent, replied=replied,
        reply_rate=(replied / submitted) if submitted else None,
        avg_steps=(steps / n) if n else None,
        top_rejection_reasons=[ReasonCount(reason=r, count=c) for r, c in reasons.most_common(5)])
