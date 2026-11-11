"""Workspace MCP server (local mock of Google Calendar and Gmail).

The agents only ever see these tools. State lives in a JSON file (env WORKSPACE_PATH, default
data/processed/workspace.json). Swapping in real Calendar and Gmail changes this file only.
Tools: free_slots (read), hold_interview (tentative hold, idempotent), draft_email (draft only,
never sends). Working hours and slot size come from config (mcp.workspace).

Run: python -m mcp_servers.workspace.server [--http]   (HTTP needs WORKSPACE_MCP_TOKEN)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common import ROOT, BearerAuthMiddleware, cfg

mcp = FastMCP("gigbid-workspace",
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                       openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                        openWorldHint=False)
DryRun = Annotated[bool, Field(description="True returns what would be stored and stores nothing")]


class Slots(BaseModel):
    slots: list[str] = Field(description="Free slot starts, ISO 8601 local time")
    duration_min: int


class Hold(BaseModel):
    hold_id: str | None = None
    slot: str
    client_id: str
    status: str = Field(description="tentative, or dry_run when nothing was stored")
    idempotent_replay: bool = False
    dry_run: bool = False


class EmailDraft(BaseModel):
    draft_id: str | None = None
    to: str
    subject: str
    body: str
    status: str = Field(description="draft (never sent), or dry_run when nothing was stored")
    dry_run: bool = False


def _path() -> Path:
    return Path(os.environ.get("WORKSPACE_PATH") or ROOT / "data" / "processed" / "workspace.json")


def _load() -> dict[str, Any]:
    p = _path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"holds": {}, "drafts": {}, "busy": []}


def _save(db: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(db, indent=1), encoding="utf-8")


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()


@mcp.tool(annotations=READ)
def free_slots(date_from: str, date_to: str,
               duration_min: Annotated[int, Field(ge=15, le=240)] = 30) -> Slots:
    """List free calendar slots between two dates (YYYY-MM-DD, inclusive) inside working hours.
    Existing tentative holds and busy blocks are excluded."""
    start, end = _parse_day(date_from), _parse_day(date_to)
    if end < start:
        raise ValueError("date_to must not be before date_from")
    w = cfg("mcp.workspace", {}) or {}
    open_t, close_t = _hm(w.get("workday_start", "09:00")), _hm(w.get("workday_end", "17:00"))
    step = timedelta(minutes=int(w.get("slot_step_min", 30)))
    limit = int(w.get("max_slots", 20))
    db = _load()
    taken = {h["slot"] for h in db["holds"].values()} | set(db.get("busy", []))
    out: list[str] = []
    day = start
    while day <= end and len(out) < limit:
        if not (w.get("skip_weekends", True) and day.weekday() >= 5):
            t = datetime.combine(day, open_t)
            last = datetime.combine(day, close_t) - timedelta(minutes=duration_min)
            while t <= last and len(out) < limit:
                if t.isoformat(timespec="minutes") not in taken:
                    out.append(t.isoformat(timespec="minutes"))
                t += step
        day += timedelta(days=1)
    return Slots(slots=out, duration_min=duration_min)


@mcp.tool(annotations=WRITE)
def hold_interview(slot: str, client_id: str,
                   idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
                   dry_run: DryRun = False) -> Hold:
    """Place a tentative interview hold on a free slot. The same idempotency_key returns the same
    hold. The hold is tentative: the user confirms it later."""
    slot = datetime.fromisoformat(slot).isoformat(timespec="minutes")
    hold_id = "hold-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]
    if dry_run:
        return Hold(slot=slot, client_id=client_id, status="dry_run", dry_run=True)
    db = _load()
    if hold_id in db["holds"]:
        h = db["holds"][hold_id]
        return Hold(hold_id=hold_id, slot=h["slot"], client_id=h["client_id"], status=h["status"],
                    idempotent_replay=True)
    if slot in {h["slot"] for h in db["holds"].values()} | set(db.get("busy", [])):
        raise ValueError(f"slot {slot} is not free")
    db["holds"][hold_id] = {"slot": slot, "client_id": client_id, "status": "tentative"}
    _save(db)
    return Hold(hold_id=hold_id, slot=slot, client_id=client_id, status="tentative")


@mcp.tool(annotations=WRITE)
def draft_email(to: str, subject: str, body: str, dry_run: DryRun = False) -> EmailDraft:
    """Store an email draft. It is never sent: the user reviews and sends it themselves. The same
    to, subject and body always give the same draft id."""
    draft_id = "mail-" + hashlib.sha256(f"{to}|{subject}|{body}".encode()).hexdigest()[:10]
    if dry_run:
        return EmailDraft(to=to, subject=subject, body=body, status="dry_run", dry_run=True)
    db = _load()
    db["drafts"][draft_id] = {"to": to, "subject": subject, "body": body}
    _save(db)
    return EmailDraft(draft_id=draft_id, to=to, subject=subject, body=body, status="draft")


def http_app():
    token = os.environ.get("WORKSPACE_MCP_TOKEN")
    if not token:
        raise RuntimeError("WORKSPACE_MCP_TOKEN must be set for HTTP transport")
    return BearerAuthMiddleware(mcp.streamable_http_app(), token)


def main() -> None:
    if "--http" in sys.argv:
        import uvicorn
        port = int(os.environ.get("WORKSPACE_MCP_PORT", cfg("mcp.workspace.port", 9200)))
        uvicorn.run(http_app(), host=os.environ.get("MCP_HOST", "127.0.0.1"), port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
