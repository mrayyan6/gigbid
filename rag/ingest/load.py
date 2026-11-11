"""Load portfolio evidence (synthetic GigSim personas) into chunks with metadata."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "processed" / "gigsim"


def load_portfolio(persona: str | None = None) -> list[dict]:
    items = json.loads((DATA / "portfolio.json").read_text(encoding="utf-8"))
    if persona:
        items = [i for i in items if i["freelancer_id"] == persona]
    return [{**i, "text": f"{i['title']}. {i['summary']} Skills: {', '.join(i['skills'])}."}
            for i in items]
