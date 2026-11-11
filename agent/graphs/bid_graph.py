"""Hand-written LangGraph bid graph.

scout -> [analyst | risk | matcher] in parallel (Send) -> decide -> pricing -> writer -> verifier
-> critic (max 2 revisions back to writer) -> compliance -> approval interrupt -> submit.
Nothing is sent before a human resumes the interrupted thread with an approval.

Every node is wrapped by core.guarded (step count, retries, queue or dead letter) and every edge by
core.gated (step and token budget, terminal statuses). Over budget goes to `needs_attention`.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from agent.nodes import core
from agent.state import GigBidState


def fan_out(state):
    return [Send("analyst", state), Send("risk", state), Send("matcher", state)]


def _key(state, config) -> str:
    return f"{config['configurable']['thread_id']}:{state['job_id']}"


def _body(state, text: str | None = None) -> dict:
    return {"job_id": state["job_id"], "bid_amount": state["price_quote"]["amount"],
            "cover_letter": text or state["proposal_draft"]["cover_letter"]}


async def approval(state, config):
    """interrupt() BEFORE any external write. Payload carries everything the UI must show."""
    mp = core.deps(config)["marketplace"]
    payload = {"job_id": state["job_id"], "draft": state["proposal_draft"],
               "evidence": state["evidence"], "risk": state["risk_report"],
               "price": state["price_quote"], "claims": state["claim_verification"],
               "compliance": state["compliance_verdict"], "style_notes": state.get("memory_notes", []),
               "dry_run": await mp.create_proposal(_body(state), _key(state, config), dry_run=True)}
    decision = interrupt(payload)
    return {"approval": decision, **core._t("approval", action=decision.get("action"))}


def route_approval(state):
    return "submit" if state["approval"]["action"] in ("approve", "edit") else "end"


async def recheck_edit(state, config):
    """An approved edit goes back through Compliance (config rules plus the live platform policy),
    then its diff against the draft is fed to style memory (which promotes only by explicit rule)."""
    a = state["approval"]
    if a["action"] == "reject":
        return {"status": "rejected", **core._t("recheck", action="reject", reason=a.get("reason"))}
    if a["action"] != "edit":
        return {}
    bad = core.violations(a["text"], await core.get_policy(config))
    if bad:
        return {"approval": {"action": "reject", "reason": f"edit violates policy: {bad}"},
                "status": "rejected", "compliance_verdict": {"allowed": False, "violations": bad}}
    mem = core.deps(config).get("memory")
    promoted = []
    if mem is not None:
        try:
            promoted = mem.record_edit(config["configurable"].get("user_id", "default"),
                                       config["configurable"]["thread_id"],
                                       state["proposal_draft"]["cover_letter"], a["text"])
        except Exception:
            promoted = []
    d = dict(state["proposal_draft"], cover_letter=a["text"])
    return {"proposal_draft": d, **core._t("recheck", action="edit", promoted=promoted)}


async def submit(state, config):
    mp = core.deps(config)["marketplace"]
    key = _key(state, config)
    rec = await mp.create_proposal(_body(state), key)  # idempotency key makes resume safe
    return {"outcome": rec, "status": "submitted", **core._t("submit", tool="create_proposal", key=key)}


def block_or_approve(state):
    return "approval" if state["compliance_verdict"]["allowed"] else "end"


def build_bid_graph(checkpointer=None):
    g = StateGraph(GigBidState)
    nodes = [("scout", core.scout), ("analyst", core.analyst), ("risk", core.risk),
             ("matcher", core.matcher), ("decide", core.decide), ("pricing", core.pricing),
             ("writer", core.writer), ("verifier", core.verifier), ("critic", core.critic),
             ("compliance", core.compliance), ("approval", approval),
             ("recheck", recheck_edit), ("submit", submit)]
    for name, fn in nodes:
        g.add_node(name, core.guarded(name, fn))
    g.add_node("needs_attention", core.needs_attention)
    g.add_edge("needs_attention", END)

    def edges(src, router, targets):
        g.add_conditional_edges(src, core.gated(router),
                                {**{t: t for t in targets}, "needs_attention": "needs_attention",
                                 END: END})

    g.add_edge(START, "scout")
    edges("scout", fan_out, ["analyst", "risk", "matcher"])
    g.add_edge(["analyst", "risk", "matcher"], "decide")
    g.add_conditional_edges("decide", core.gated(lambda s: core.route_decision(s)),
                            {"pricing": "pricing", "end": END, "needs_attention": "needs_attention",
                             END: END})
    for src, dst in [("pricing", "writer"), ("writer", "verifier"), ("verifier", "critic")]:
        edges(src, lambda s, d=dst: d, [dst])
    edges("critic", core.route_critic, ["writer", "compliance"])
    g.add_conditional_edges("compliance", core.gated(block_or_approve),
                            {"approval": "approval", "end": END, "needs_attention": "needs_attention"})
    edges("approval", lambda s: "recheck", ["recheck"])
    g.add_conditional_edges("recheck", core.gated(route_approval),
                            {"submit": "submit", "end": END, "needs_attention": "needs_attention"})
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["Command", "build_bid_graph"]
