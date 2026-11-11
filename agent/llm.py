"""One OpenAI compatible chat client (Ollama and Groq both speak this protocol).

Routing is per node from config (`routing.<profile>.nodes`). On error, timeout or empty output the
call retries once on the profile fallback model, then returns text=None so the caller uses its
deterministic template (failure handling C7). Nothing here raises for model or network problems.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass

import httpx

from agent.nodes.config import CFG

_TRANSPORT: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests inject httpx.MockTransport here."""
    global _TRANSPORT
    _TRANSPORT = transport


@dataclass
class LLMResult:
    text: str | None
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tokens_per_s: float = 0.0
    cost_usd: float = 0.0
    fallback_used: bool = False
    error: str | None = None

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def trace(self) -> dict:
        d = asdict(self)
        d.pop("text")
        return d


def enabled() -> bool:
    env = os.environ.get("LLM_ENABLED")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return bool(CFG["llm"]["enabled"])


def _profile() -> dict:
    name = os.environ.get("GIGBID_PROFILE") or CFG.get("llm_profile") or CFG.get("profile", "open")
    routing = CFG["routing"]
    return routing.get(name) or routing["open"]


def resolve_model(node: str) -> str:
    p = _profile()
    return (p.get("nodes") or {}).get(node) or p["default"]


def fallback_model() -> str:
    return _profile()["fallback"]


def _split(model: str) -> tuple[str, str]:
    provider, _, name = model.partition("/")
    return provider, name


def _call(model: str, system: str, user: str, json_mode: bool, max_tokens: int) -> LLMResult:
    provider, name = _split(model)
    prov = CFG["providers"][provider]
    headers = {}
    key_env = prov.get("api_key_env")
    if key_env:
        key = os.environ.get(key_env, "")
        if not key:
            return LLMResult(None, model, error=f"{key_env} not set")
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": name, "temperature": CFG["llm"]["temperature"], "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    t0 = time.perf_counter()
    try:
        with httpx.Client(transport=_TRANSPORT, timeout=CFG["llm"]["timeout_s"]) as c:
            r = c.post(prov["base_url"].rstrip("/") + "/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # network, timeout, HTTP error, malformed body
        return LLMResult(None, model, latency_ms=int((time.perf_counter() - t0) * 1000),
                         error=f"{type(e).__name__}: {e}")
    ms = int((time.perf_counter() - t0) * 1000)
    use = data.get("usage") or {}
    tin, tout = int(use.get("prompt_tokens", 0)), int(use.get("completion_tokens", 0))
    cost = (tin * prov.get("usd_per_1m_in", 0) + tout * prov.get("usd_per_1m_out", 0)) / 1e6
    return LLMResult(text or None, model, tin, tout, ms, round(tout / (ms / 1000), 1) if ms else 0.0,
                     cost, error=None if text else "empty completion")


def complete(node: str, system: str, user: str, *, json_mode: bool = False,
             max_tokens: int | None = None) -> LLMResult:
    """Return LLMResult. result.text is None when the caller must use its template."""
    if not enabled():
        return LLMResult(None, error="llm disabled")
    mt = max_tokens or CFG["llm"]["max_output_tokens"]
    res = _call(resolve_model(node), system, user, json_mode, mt)
    if res.text is None and fallback_model() != res.model:
        first_err = res.error
        res = _call(fallback_model(), system, user, json_mode, mt)
        res.fallback_used = True
        if res.text is None:
            res.error = f"primary: {first_err}; fallback: {res.error}"
    return res


def parse_json(text: str | None) -> dict | None:
    """Tolerant JSON object parse (models sometimes wrap output in prose or code fences)."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
