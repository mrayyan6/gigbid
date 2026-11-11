"""PII and secret masking. One implementation reused by the MCP audit log, the application log
filter and the LangSmith anonymizer, so a value masked in one place is masked everywhere.

Masks emails, card numbers, phone numbers and API style secrets (anchored, so words such as
"risk-based" are left alone). `mask` accepts any JSON like value and returns a masked copy.
"""
from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d")
SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|lsv2_[A-Za-z0-9_]{20,})"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}")

# Order matters: secrets and emails first, then cards before phones (a card is also phone shaped).
RULES: list[tuple[re.Pattern[str], str]] = [
    (SECRET, "[secret]"),
    (EMAIL, "[email]"),
    (CARD, "[card]"),
    (PHONE, "[phone]"),
]


def mask_text(text: str) -> str:
    for pattern, replacement in RULES:
        text = pattern.sub(replacement, text)
    return text


def mask(value: Any) -> Any:
    """Mask every string inside a str, dict, list or tuple. Other types are returned unchanged."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    if isinstance(value, tuple):
        return tuple(mask(v) for v in value)
    return value


class MaskingFilter(logging.Filter):
    """Logging filter: masks the formatted message (and drops args) before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        with contextlib.suppress(Exception):  # never let masking break logging
            record.msg = mask_text(record.getMessage())
            record.args = None
        return True


def install_log_masking(logger: logging.Logger | None = None) -> None:
    """Attach the masking filter to every handler of `logger` (default root). Idempotent."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, MaskingFilter) for f in handler.filters):
            handler.addFilter(MaskingFilter())
