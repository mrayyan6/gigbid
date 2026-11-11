"""Append-only JSONL audit log: user, tool, args (PII masked), result summary, trace id."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from mcp_servers.common import ROOT

DEFAULT_PATH = ROOT / "data" / "processed" / "audit.jsonl"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_lock = threading.Lock()


def mask(value: Any) -> Any:
    """Mask emails, card numbers and phone numbers in any JSON-like value."""
    if isinstance(value, str):
        value = _EMAIL.sub("[email]", value)
        value = _CARD.sub("[card]", value)
        return _PHONE.sub("[phone]", value)
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


class AuditLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_PATH

    def write(self, *, user: str, tool: str, args: dict, result: str, trace_id: str = "") -> None:
        line = {"ts": round(time.time(), 3), "user": user, "tool": tool, "args": mask(args),
                "result": mask(result)[:300], "trace_id": trace_id}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
