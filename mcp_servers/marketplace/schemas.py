"""Pydantic output models for the Marketplace MCP server (declared output schemas).

Models allow extra fields so a marketplace adapter can add data without breaking clients, but the
fields the agents rely on are declared and typed.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Budget(BaseModel):
    min: float
    max: float


class Job(_Open):
    job_id: str
    title: str
    description: str = ""
    required_skills: list[str] = []
    budget: Budget | None = None
    connects_cost: int | None = Field(default=None, description="Connects this proposal costs now")
    client_id: str | None = None


class ClientHistory(_Open):
    client_id: str


class ConnectsBalance(BaseModel):
    balance: int


class Message(_Open):
    message_id: str | None = None
    client_id: str
    text: str = ""


class Policy(_Open):
    version: int | None = None
    connects_multiplier: float = 1.0
    min_budget_usd: float = 0
    rate_limit_per_min: int | None = None


class ProposalResult(_Open):
    """Result of create_proposal_draft or submit_proposal. With dry_run true nothing is stored or
    spent and `would_send` holds the exact payload."""
    dry_run: bool = False
    would_send: dict[str, Any] | None = None
    connects_cost: int | None = None
    balance_after: int | None = None
    proposal_id: str | None = None
    draft_id: str | None = None
    status: str | None = None
    connects_spent: int | None = None
    idempotent_replay: bool = False


class MessageResult(_Open):
    dry_run: bool = False
    would_send: dict[str, Any] | None = None
    message_id: str | None = None
    idempotent_replay: bool = False
