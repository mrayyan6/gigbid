"""Hand-written LangGraph bid graph.

scout -> [analyst | risk | matcher] in parallel (Send) -> decide -> pricing -> writer -> verifier
-> critic (max 2 revisions back to writer) -> compliance -> approval interrupt -> submit.
Nothing is sent before a human resumes the interrupted thread with an approval.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from agent.nodes import core
from agent.state import GigBidState


def fan_out(state):
    return [Send("analyst", state), Send("risk", state), Send("matcher", state)]


async def approval(state, config):
    """interrupt() BEFORE any external write. Payload carries everything the UI must show."""
    mp = core.deps(config)["marketplace"]
    key = f"{config['configurable']['thread_id']}:{state['job_id']}"
    payload = {"job_id": state["job_id"], "draft": state["proposal_draft"],
               "evidence": state["evidence"], "risk": state["risk_report"],
               "price": state["price_quote"], "claims": state["claim_verification"],
               "compliance": state["compliance_verdict"],
               "dry_run": await mp.create_proposal(_body(state), key, dry_run=True)}
    decision = interrupt(payload)
    return {"approval": decision, **core._t("approval", action=decision.get("action"))}


def _body(state, text: str | None = None) -> dict:
    return {"job_id": state["job_id"], "bid_amount": state["price_quote"]["amount"],
            "cover_letter": text or state["proposal_draft"]["cover_letter"]}


def route_approval(state):
    a = state["approval"]
    return "submit" if a["action"] in ("approve", "edit") else "end"


async def recheck_edit(state, config):
    """An approved edit goes back through Compliance before anything is sent."""
    a = state["approval"]
    if a["action"] != "edit":
        return {}
    text = a["text"].lower()
    bad = [p for p in core.CFG["compliance"]["banned_phrases"] if p in text]
    if bad:
        return {"approval": {"action": "reject", "reason": f"edit violates policy: {bad}"}}
    d = dict(state["proposal_draft"], cover_letter=a["text"])
    return {"proposal_draft": d}


async def submit(state, config):
    mp = core.deps(config)["marketplace"]
    key = f"{config['configurable']['thread_id']}:{state['job_id']}"
    rec = await mp.create_proposal(_body(state), key)  # idempotency key makes resume safe
    return {"outcome": rec, **core._t("submit", tool="create_proposal", key=key)}


def block_or_approve(state):
    return "approval" if state["compliance_verdict"]["allowed"] else "end"


def build_bid_graph(checkpointer=None):
    g = StateGraph(GigBidState)
    for name, fn in [("scout", core.scout), ("analyst", core.analyst), ("risk", core.risk),
                     ("matcher", core.matcher), ("decide", core.decide), ("pricing", core.pricing),
                     ("writer", core.writer), ("verifier", core.verifier), ("critic", core.critic),
                     ("compliance", core.compliance), ("approval", approval),
                     ("recheck", recheck_edit), ("submit", submit)]:
        g.add_node(name, fn)
    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", fan_out, ["analyst", "risk", "matcher"])
    g.add_edge(["analyst", "risk", "matcher"], "decide")
    g.add_conditional_edges("decide", core.route_decision, {"pricing": "pricing", "end": END})
    g.add_edge("pricing", "writer")
    g.add_edge("writer", "verifier")
    g.add_edge("verifier", "critic")
    g.add_conditional_edges("critic", core.route_critic,
                            {"writer": "writer", "compliance": "compliance"})
    g.add_conditional_edges("compliance", block_or_approve, {"approval": "approval", "end": END})
    g.add_edge("approval", "recheck")
    g.add_conditional_edges("recheck", route_approval, {"submit": "submit", "end": END})
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["build_bid_graph", "Command"]
