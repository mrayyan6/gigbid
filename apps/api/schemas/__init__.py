"""Typed API contract (frozen). The web client is generated from the OpenAPI schema of these models.

Variable-shape graph payloads (evidence, risk report, ...) are typed as dict so the contract does
not break when a node adds a field. Add fields, never rename or remove them.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["queued", "running", "awaiting_approval", "completed", "skipped", "blocked",
                    "rejected", "needs_attention", "failed"]
Action = Literal["approve", "edit", "reject"]
Persona = str


class ErrorOut(BaseModel):
    detail: str


# auth -----------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    persona: Persona


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# jobs -----------------------------------------------------------------------------------------
class JobOut(BaseModel):
    job_id: str
    title: str
    description: str = ""
    required_skills: list[str] = Field(default_factory=list)
    budget_min: float = 0
    budget_max: float = 0
    currency: str = "USD"
    connects_cost: int = 0
    client_id: str | None = None
    risk_badges: list[str] = Field(default_factory=list)
    fit_score: float | None = None
    recommended_action: Literal["bid", "watch", "skip", "unscored"] = "unscored"
    price: float | None = None
    thread_id: str | None = None
    run_status: RunStatus | None = None


class RunOut(BaseModel):
    thread_id: str
    job_id: str
    status: RunStatus
    next: list[str] = Field(default_factory=list)
    pending_approval: list[dict[str, Any]] = Field(default_factory=list)
    job: dict[str, Any] | None = None
    job_spec: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    fit_report: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    decision: dict[str, Any] | None = None
    price_quote: dict[str, Any] | None = None
    proposal_draft: dict[str, Any] | None = None
    claim_verification: list[dict[str, Any]] = Field(default_factory=list)
    critique: dict[str, Any] | None = None
    compliance_verdict: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class JobDetailOut(BaseModel):
    job: JobOut
    raw: dict[str, Any]
    run: RunOut | None = None


class RunIn(BaseModel):
    job_id: str


class RunStartOut(BaseModel):
    thread_id: str
    job_id: str
    status: RunStatus
    trace_id: str | None = None


# approvals ------------------------------------------------------------------------------------
class ApprovalItem(BaseModel):
    thread_id: str
    job_id: str
    title: str = ""
    payload: dict[str, Any]


class ApprovalIn(BaseModel):
    action: Action
    text: str | None = Field(default=None, description="Edited cover letter, for action=edit")
    reason: str | None = Field(default=None, description="Required for action=reject")


class ApprovalOut(BaseModel):
    thread_id: str
    status: RunStatus
    outcome: dict[str, Any] | None = None
    promoted_memory: list[str] = Field(default_factory=list)


class RegenerateIn(BaseModel):
    paragraph_index: int = Field(ge=0)


class RegenerateOut(BaseModel):
    thread_id: str
    paragraph_index: int
    regenerated: bool
    draft: dict[str, Any] | None = None
    message: str = ""


# pipeline, messages, analytics ----------------------------------------------------------------
class PipelineCard(BaseModel):
    thread_id: str
    job_id: str
    title: str = ""
    stage: str
    amount: float | None = None
    client_id: str | None = None
    updated_at: str | None = None


class PipelineOut(BaseModel):
    stages: list[str]
    columns: dict[str, list[PipelineCard]]


class MessageThreadOut(BaseModel):
    client_id: str
    messages: list[dict[str, Any]]


class MessagesOut(BaseModel):
    threads: list[MessageThreadOut]


class DraftIn(BaseModel):
    instruction: str | None = None


class DraftOut(BaseModel):
    client_id: str
    intent: str
    draft: str
    slots: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["awaiting_approval", "flagged"] = "awaiting_approval"


class ReasonCount(BaseModel):
    reason: str
    count: int


class AnalyticsOut(BaseModel):
    runs_total: int
    by_status: dict[str, int]
    by_action: dict[str, int]
    submitted: int
    rejected: int
    connects_spent: int
    replied: int
    reply_rate: float | None = None
    avg_steps: float | None = None
    top_rejection_reasons: list[ReasonCount] = Field(default_factory=list)


# memory, settings, health ---------------------------------------------------------------------
class MemoryItem(BaseModel):
    ns: str
    key: str
    value: dict[str, Any]


class MemoryOut(BaseModel):
    items: list[MemoryItem]


class DeleteOut(BaseModel):
    deleted: bool


class SavedSearch(BaseModel):
    name: str
    query: str = ""
    interval_minutes: int = Field(default=30, ge=1)


class SettingsModel(BaseModel):
    autonomy: Literal["manual", "auto_skip_low_fit"] = "manual"
    weekly_connects_budget: int = Field(default=100, ge=0)
    min_hourly_rate: float = Field(default=25, ge=0)
    keywords: list[str] = Field(default_factory=list)
    saved_searches: list[SavedSearch] = Field(default_factory=list)


class SettingsOut(SettingsModel):
    persona: Persona
    marketplace_mode: str
    upwork_status: str = "not connected (live mode untested)"


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    marketplace: Literal["up", "down"]
    service: str = "gigbid-api"
    checkpointer: str = ""
    queued_runs: int = 0


class MarketplaceDownIn(BaseModel):
    down: bool = True


class MarketplaceDownOut(BaseModel):
    down: bool
