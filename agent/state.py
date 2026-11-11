"""Typed graph state. Three things are kept apart on purpose:
1. State: what this thread needs now (this TypedDict).
2. Execution trace: every node and tool call for audit (the `trace` field, append only).
3. Long-term memory: promoted knowledge only, in agent/memory/store.py (never raw tool output).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class GigBidState(TypedDict, total=False):
    job_id: str
    job: dict[str, Any]
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    evidence: Annotated[list[dict[str, Any]], operator.add]
    decision: dict[str, Any]
    price_quote: dict[str, Any]
    proposal_draft: dict[str, Any]
    claim_verification: list[dict[str, Any]]
    critique: dict[str, Any]
    revisions: int
    compliance_verdict: dict[str, Any]
    approval: dict[str, Any]
    outcome: dict[str, Any]
    steps: int
    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
