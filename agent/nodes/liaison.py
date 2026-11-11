"""Client Liaison nodes for the conversation graph.

Client messages are untrusted data. Intent is decided by the cheap model (intent.md) with a regex
fallback from config, and the regex scam check is a floor: a message the rules call a scam signal stays
a scam signal whatever the model says. Scam replies always use the template, the model never engages
with the text. Slots come from the Workspace tool (injectable, config['configurable']['workspace']).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from langgraph.types import interrupt

from agent import llm
from agent.nodes import core
from agent.nodes.config import CFG, load_prompt

INTENTS = ("question", "negotiation", "interview_request", "scam_signal")


def _cc() -> dict:
    return CFG["conversation"]


def _t(node: str, **kw) -> dict:
    return core._t(node, **kw)


def rule_intent(text: str, cfg: dict | None = None) -> str:
    c = cfg or _cc()
    low = text.lower()
    for intent in c["intent_order"]:
        for pat in c["intent_patterns"].get(intent, []):
            rx = (r"\b" if pat[:1].isalnum() else "") + re.escape(pat)
            if re.search(rx, low):
                return intent
    return c["default_intent"]


class LocalWorkspace:
    """Deterministic stand-in used only when no Workspace tool is injected. Weekdays at fixed hours
    from config (conversation.local_slot_hours)."""

    async def free_slots(self, date_from: str, date_to: str, duration_min: int) -> list[dict]:
        d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
        out, d = [], d0
        while d <= d1:
            if d.weekday() < 5:
                for hh in _cc()["local_slot_hours"]:
                    start = datetime(d.year, d.month, d.day, hh)
                    out.append({"start": start.isoformat(timespec="minutes"),
                                "end": (start + timedelta(minutes=duration_min)).isoformat(timespec="minutes")})
            d += timedelta(days=1)
        return out


def _slot_text(s: Any) -> str:
    if isinstance(s, dict):
        return str(s.get("start") or s.get("text") or s)
    return str(s)


async def _get_slots(config) -> list[str]:
    c = _cc()
    ws = core.deps(config).get("workspace")
    if ws is None and c["local_slots_fallback"]:
        ws = LocalWorkspace()
    if ws is None:
        return []
    today = date.today()
    try:
        raw = await ws.free_slots(today.isoformat(),
                                  (today + timedelta(days=c["slot_days_ahead"])).isoformat(),
                                  c["slot_duration_min"])
    except Exception:  # noqa: BLE001 - workspace down: ask the client for times instead
        return []
    return [_slot_text(s) for s in (raw or [])][:c["max_slots_offered"]]


def _history(state) -> str:
    n = _cc()["max_messages_context"]
    return "\n".join(f"{m.get('from', '?')}: {m.get('text', '')}" for m in state.get("messages", [])[-n:])


# ---------------------------------------------------------------- nodes
async def read_messages(state, config):
    msgs = await core.deps(config)["marketplace"].list_messages(state["client_id"])
    last = next((m for m in reversed(msgs) if m.get("from") == "client"), None)
    status = "running" if last else "idle"
    return {"messages": msgs, "last_message": last, "status": status,
            **_t("read_messages", tool="list_messages", args={"client_id": state["client_id"]},
                 n=len(msgs))}


def classify_intent(state, config):
    text = state["last_message"]["text"]
    rule = rule_intent(text)
    intent, reason, extra = rule, "rules", {}
    if llm.enabled():
        res = llm.complete("intent", load_prompt("intent"),
                           f"<client_message>\n{text}\n</client_message>", json_mode=True, max_tokens=120)
        extra = core.llm_fields("classify_intent", res)
        obj = llm.parse_json(res.text) or {}
        if obj.get("intent") in INTENTS:
            intent, reason = obj["intent"], str(obj.get("reason", ""))[:200]
    if rule == "scam_signal":  # safety floor
        intent, reason = "scam_signal", "rule floor"
    return {"intent": intent, "intent_reason": reason, "tokens": extra.get("tokens", 0),
            "cost_usd": extra.get("cost_usd", 0.0),
            "trace": [{"node": "classify_intent", "intent": intent, "reason": reason,
                       **({"llm": extra["trace"][0]["llm"]} if extra else {})}]}


def route_intent(state):
    return {"scam_signal": "flag_scam", "interview_request": "propose_slots"}.get(
        state["intent"], "draft_reply")


async def _compose(state, config, intent: str, slots: list[str]) -> tuple[str, dict]:
    t = _cc()["templates"]
    if intent == "interview_request":
        template = t["interview_request"].format(slots="; ".join(slots)) if slots \
            else t["interview_no_slots"]
    else:
        template = t[intent]
    text, extra = None, {}
    if llm.enabled() and intent != "scam_signal":
        user = (f"Intent: {intent}\nSlots to offer: {'; '.join(slots) or 'none'}\n"
                f"<client_message>\n{_history(state)}\n</client_message>")
        res = llm.complete("liaison", load_prompt("liaison"), user, max_tokens=220)
        extra = core.llm_fields("compose", res)
        text = res.text
        if text and core.violations(text, await core.get_policy(config)):
            text = None  # unsafe model output: use the vetted template
    return text or template, extra


async def draft_reply(state, config):
    text, extra = await _compose(state, config, state["intent"], [])
    return {"draft": text, "tokens": extra.get("tokens", 0), "cost_usd": extra.get("cost_usd", 0.0),
            **_t("draft_reply", intent=state["intent"])}


async def propose_slots(state, config):
    slots = await _get_slots(config)
    text, extra = await _compose(state, config, "interview_request", slots)
    return {"slots": slots, "draft": text, "tokens": extra.get("tokens", 0),
            "cost_usd": extra.get("cost_usd", 0.0),
            **_t("propose_slots", tool="free_slots", n=len(slots))}


async def flag_scam(state, config):
    text, _ = await _compose(state, config, "scam_signal", [])
    return {"draft": text, "flagged": True, **_t("flag_scam", reason=state.get("intent_reason"))}


def _msg_id(state) -> str:
    return str(state["last_message"].get("message_id") or "m0")


def _key(state, config) -> str:
    return f"{config['configurable']['thread_id']}:{_msg_id(state)}"


async def approval(state, config):
    """interrupt() BEFORE a message is sent. Resume with {"action": approve|edit|reject, ...}."""
    key = _key(state, config)
    payload = {"client_id": state["client_id"], "message": state["last_message"],
               "intent": state["intent"], "flagged": bool(state.get("flagged")),
               "slots": state.get("slots", []), "draft": state["draft"],
               "dry_run": {"dry_run": True, "would_send": {"client_id": state["client_id"],
                                                           "text": state["draft"],
                                                           "idempotency_key": key}}}
    decision = interrupt(payload)
    return {"approval": decision, **_t("approval", action=decision.get("action"))}


async def recheck(state, config):
    a = state["approval"]
    if a["action"] == "reject":
        return {"status": "rejected", **_t("recheck", action="reject", reason=a.get("reason"))}
    if a["action"] == "edit":
        bad = core.violations(a["text"], await core.get_policy(config))
        if bad:
            return {"approval": {"action": "reject", "reason": f"edit violates policy: {bad}"},
                    "status": "rejected", **_t("recheck", action="reject", violations=bad)}
        return {"draft": a["text"], **_t("recheck", action="edit")}
    return {}


def route_approval(state):
    return "send" if state["approval"]["action"] in ("approve", "edit") else "end"


async def send(state, config):
    key = _key(state, config)
    rec = await core.deps(config)["marketplace"].send_message(state["client_id"], state["draft"], key)
    return {"outcome": rec, "status": "sent", **_t("send", tool="send_message", key=key)}
