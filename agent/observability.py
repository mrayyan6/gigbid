"""Tracing setup. LangSmith is switched on only when a key and LANGSMITH_TRACING=true are present.

Env: LANGSMITH_TRACING (true to enable), LANGSMITH_API_KEY (secret), LANGSMITH_PROJECT (default
gigbid). Without a key tracing stays off and nothing is sent anywhere. The shared LangSmith client
is created with an anonymizer built from agent.security.pii, so emails, phones, cards and secrets
never leave the process in clear text.

Trace ids: apps/api/main.py middleware puts one id per request in a contextvar, apps/api/runner.py
copies it into graph config metadata (trace_id, user_id, job_thread). `run_config` below builds the
same metadata plus tags for callers that start a run themselves, and `trace_headers` gives the
X-Trace-Id header forwarded to the MCP servers (see agent/mcp_client.py).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from agent.security.pii import RULES, install_log_masking

log = logging.getLogger("gigbid.observability")
DEFAULT_PROJECT = "gigbid"
_configured = False


def tracing_enabled() -> bool:
    on = os.environ.get("LANGSMITH_TRACING", os.environ.get("LANGCHAIN_TRACING_V2", "")).lower()
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    return on in {"1", "true", "yes"} and bool(key)


def build_anonymizer():
    """LangSmith anonymizer that applies the shared PII rules to every string in a run."""
    from langsmith.anonymizer import create_anonymizer
    return create_anonymizer([{"pattern": p, "replace": r} for p, r in RULES])


def setup_tracing() -> bool:
    """Idempotent. Returns True when LangSmith tracing is active. Never raises."""
    global _configured
    install_log_masking()
    if _configured:
        return tracing_enabled()
    _configured = True
    if not tracing_enabled():
        # Make sure a stray LANGSMITH_TRACING=true without a key cannot produce error spam.
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        log.info("tracing off (no LANGSMITH_API_KEY or LANGSMITH_TRACING not true)")
        return False
    try:
        os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)
        from langsmith import run_trees
        run_trees.get_cached_client(anonymizer=build_anonymizer())  # first caller wins
        log.info("LangSmith tracing on, project %s", os.environ["LANGSMITH_PROJECT"])
        return True
    except Exception as exc:  # noqa: BLE001  tracing must never take the app down
        log.warning("tracing setup failed, continuing without: %s", type(exc).__name__)
        os.environ["LANGSMITH_TRACING"] = "false"
        return False


def run_config(trace_id: str, user_id: str = "", thread_id: str = "",
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Graph config fragment: trace id as run metadata and as a tag, so one id finds the LangSmith
    run, the audit.jsonl lines and the API response header."""
    metadata = {"trace_id": trace_id, "user_id": user_id, "job_thread": thread_id, **(extra or {})}
    return {"metadata": metadata, "tags": [f"trace:{trace_id}"]}


def trace_headers(trace_id: str, user_id: str = "") -> dict[str, str]:
    headers = {"X-Trace-Id": trace_id}
    if user_id:
        headers["X-User-Id"] = user_id
    return headers


def usage_metadata(node: str, tokens_in: int, tokens_out: int, usd: float) -> dict[str, Any]:
    """Per node token and cost metadata, attach with `config["metadata"].update(...)`."""
    return {f"node:{node}:tokens_in": tokens_in, f"node:{node}:tokens_out": tokens_out,
            f"node:{node}:usd": round(usd, 6)}
