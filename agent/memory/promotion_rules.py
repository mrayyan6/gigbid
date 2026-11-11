"""Explicit promotion rules for long-term memory (R7). Pure functions, thresholds from config.

Style: each approved user edit is diffed against the draft (difflib). Two kinds of signal come out:
  avoid:<phrase>        a short phrase the user deleted
  cut_first_sentence    the user dropped the opening sentence
A signal is PROMOTED to style memory only when it appears in at least `min_count` of the last
`window` edits. Until then it stays in staging, which the UI memory viewer does not show.

Outcome: per job category we count outcomes in staging and promote `reply_rate` only after
`min_outcomes` outcomes. Raw tool output is never written to either store.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

from agent.nodes.config import CFG

_TAG = re.compile(r"\[ev:[^\]]*\]")
_WORD = re.compile(r"[A-Za-z0-9'%+#.-]+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", _TAG.sub("", text)) if s.strip()]


def _words(text: str) -> list[str]:
    return [w.strip(".,;:!?").lower() for w in _WORD.findall(_TAG.sub("", text)) if w.strip(".,;:!?")]


def extract_signals(draft: str, edited: str, cfg: dict | None = None) -> list[str]:
    """Return the distinct style signals implied by editing `draft` into `edited`."""
    c = (cfg or CFG)["memory"]["style"]
    signals: set[str] = set()
    ds, es = _sentences(draft), _sentences(edited)
    if len(ds) >= 2 and ds[0].lower() not in [s.lower() for s in es] and \
            all(s.lower() in [x.lower() for x in es] for s in ds[1:3]):
        signals.add("cut_first_sentence")
    dw, ew = _words(draft), _words(edited)
    ignore = set(c["ignore_words"])
    for op, i1, i2, _j1, _j2 in difflib.SequenceMatcher(a=dw, b=ew, autojunk=False).get_opcodes():
        if op not in ("delete", "replace"):
            continue
        span = dw[i1:i2]
        if not span or len(span) > c["max_phrase_words"]:
            continue
        phrase = " ".join(span)
        if len(phrase) < c["min_phrase_chars"] or all(w in ignore for w in span):
            continue
        signals.add(f"avoid:{phrase}")
    return sorted(signals)


def signals_to_promote(recent_edits: list[dict], cfg: dict | None = None) -> dict[str, list[str]]:
    """recent_edits: staging rows [{"seq", "thread_id", "signals"}]. Returns {signal: [thread ids]}."""
    c = (cfg or CFG)["memory"]["style"]
    last = sorted(recent_edits, key=lambda e: e["seq"])[-c["window"]:]
    count: Counter[str] = Counter()
    threads: dict[str, list[str]] = {}
    for e in last:
        for s in set(e["signals"]):
            count[s] += 1
            threads.setdefault(s, []).append(e["thread_id"])
    return {s: threads[s] for s, n in count.items() if n >= c["min_count"]}


def style_item(signal: str, threads: list[str]) -> dict:
    """The value stored in long-term style memory, with provenance."""
    if signal == "cut_first_sentence":
        return {"kind": "cut_first_sentence", "text": "Skip the opening pleasantry; start with substance.",
                "provenance": {"threads": threads, "rule": "min_count_in_window"}}
    phrase = signal.split(":", 1)[1]
    return {"kind": "avoid_phrase", "text": phrase,
            "provenance": {"threads": threads, "rule": "min_count_in_window"}}


def outcome_ready(stage: dict, cfg: dict | None = None) -> bool:
    return stage["n"] >= (cfg or CFG)["memory"]["outcome"]["min_outcomes"]


def outcome_item(category: str, stage: dict) -> dict:
    return {"category": category, "reply_rate": round(stage["replied"] / stage["n"], 3),
            "n": stage["n"], "provenance": {"threads": stage["threads"][-10:],
                                            "rule": "min_outcomes"}}
