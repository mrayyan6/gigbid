"""Conversation graph, one thread per client conversation (thread id = client id).

read_messages -> classify_intent -> draft_reply | propose_slots | flag_scam -> approval (interrupt)
-> recheck -> send. A message is only sent after a human approves (or edits, then Compliance
re-checks). The send idempotency key is `<thread>:<client message id>`, so a resume replays safely.
Nodes get the marketplace port and an optional workspace tool from config['configurable'].
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agent.nodes import core, liaison
from agent.state import ConversationState


def build_conversation_graph(checkpointer=None):
    g = StateGraph(ConversationState)
    for name, fn in [("read_messages", liaison.read_messages),
                     ("classify_intent", liaison.classify_intent),
                     ("draft_reply", liaison.draft_reply), ("propose_slots", liaison.propose_slots),
                     ("flag_scam", liaison.flag_scam), ("approval", liaison.approval),
                     ("recheck", liaison.recheck), ("send", liaison.send)]:
        g.add_node(name, core.guarded(name, fn))
    g.add_node("needs_attention", core.needs_attention)
    g.add_edge("needs_attention", END)

    def edges(src, router, targets):
        g.add_conditional_edges(src, core.gated(router),
                                {**{t: t for t in targets}, "needs_attention": "needs_attention",
                                 END: END})

    g.add_edge(START, "read_messages")
    g.add_conditional_edges("read_messages",
                            core.gated(lambda s: "classify_intent" if s.get("last_message") else "end"),
                            {"classify_intent": "classify_intent", "end": END,
                             "needs_attention": "needs_attention", END: END})
    edges("classify_intent", liaison.route_intent, ["draft_reply", "propose_slots", "flag_scam"])
    for n in ("draft_reply", "propose_slots", "flag_scam"):
        edges(n, lambda s: "approval", ["approval"])
    edges("approval", lambda s: "recheck", ["recheck"])
    g.add_conditional_edges("recheck", core.gated(liaison.route_approval),
                            {"send": "send", "end": END, "needs_attention": "needs_attention", END: END})
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["build_conversation_graph", "Command"]
