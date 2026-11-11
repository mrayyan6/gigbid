"""Render both LangGraph graphs to Mermaid text and PNG from code (never hand drawn).

Writes docs/images/bid_graph.mmd, conversation_graph.mmd and, when the mermaid.ink service is reachable,
the matching PNG files. Run: python scripts/render_graphs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.graphs.bid_graph import build_bid_graph  # noqa: E402
from agent.graphs.conversation_graph import build_conversation_graph  # noqa: E402

OUT = ROOT / "docs" / "images"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("bid_graph", build_bid_graph), ("conversation_graph", build_conversation_graph)):
        g = build().get_graph()
        (OUT / f"{name}.mmd").write_text(g.draw_mermaid(), encoding="utf-8")
        try:
            (OUT / f"{name}.png").write_bytes(g.draw_mermaid_png())
            print("wrote", name, "mmd+png")
        except Exception as exc:  # offline or service down: the .mmd is the source of truth
            print("wrote", name, "mmd only:", type(exc).__name__)


if __name__ == "__main__":
    main()
