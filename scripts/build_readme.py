"""Build README.md from docs/README.template.md and docs/results_tables.md. Numbers are read from files.

Placeholders: {{TABLE:<section title>}} (a section of docs/results_tables.md), {{LIVE_URL}}, {{VIDEO_URL}}
(from env GIGBID_LIVE_URL and GIGBID_VIDEO_URL, otherwise a plain "not yet" text) and {{RESUME}}.
Run: python scripts/render_tables.py && python scripts/build_readme.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evals" / "results"


def sections() -> dict[str, str]:
    text = (ROOT / "docs" / "results_tables.md").read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1].strip() for p in parts}


def j(name: str):
    return json.loads((RES / f"{name}.json").read_text(encoding="utf-8"))


def resume() -> str:
    arch, prop = j("arch_compare")["results"], j("proposal_eval")
    best = prop["meta"]["best_variant"]
    g, r = arch["graph"]["overall"], arch["react"]["overall"]
    u0, u1 = prop[best]["unsupported_per_proposal_before"], prop[best]["unsupported_per_proposal"]
    return (f"Built GigBid, a nine agent LangGraph system with human approval, three MCP servers and a Next.js UI; a "
            f"claim verifier cut unsupported claims from {u0:.2f} to {u1:.2f} per proposal, and the hand built graph "
            f"beat a ReAct agent on bid or skip accuracy ({g['bid_or_skip_accuracy']:.2f} against "
            f"{r['bid_or_skip_accuracy']:.2f}) at {g['tokens_per_job_mean']:.0f} against "
            f"{r['tokens_per_job_mean']:.0f} tokens per job (30 synthetic dev jobs).")


def main() -> None:
    tpl = (ROOT / "docs" / "README.template.md").read_text(encoding="utf-8")
    sec = sections()

    def tab(m: re.Match) -> str:
        title = m.group(1)
        return f"**{title}**\n\n{sec[title]}\n" if title in sec else f"(missing section {title})"

    out = re.sub(r"\{\{TABLE:(.+?)\}\}", tab, tpl)
    out = out.replace("{{LIVE_URL}}", os.environ.get("GIGBID_LIVE_URL", "not deployed yet, see Honest limitations"))
    out = out.replace("{{VIDEO_URL}}", os.environ.get("GIGBID_VIDEO_URL", "not added yet"))
    out = out.replace("{{RESUME}}", resume())
    (ROOT / "README.md").write_text(out, encoding="utf-8")
    print("wrote README.md", len(out.split()), "words")


if __name__ == "__main__":
    main()
