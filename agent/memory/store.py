"""Long-term memory on a LangGraph BaseStore.

Backends: PostgresStore when DATABASE_URL is set (needs langgraph-checkpoint-postgres), else an
InMemoryStore that is persisted to data/processed/memory.json after every write.

Namespaces (all scoped by user id, so tenants never mix):
  ("style", user)         PROMOTED style notes. Shown in the UI memory viewer, fed to the writer.
  ("outcome", user)       PROMOTED per category reply rates.
  ("style_stage", user)   staging: signals from the last approved edits. Not memory, not shown.
  ("outcome_stage", user) staging: outcome counters per category.
Only agent/memory/promotion_rules.py decides what moves from staging to promoted.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from agent.memory import promotion_rules as rules
from agent.nodes.config import CFG, REPO_ROOT

PROMOTED = ("style", "outcome")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


class _PersistedInMemoryStore:
    """InMemoryStore wrapper that mirrors every write to a JSON file."""

    def __init__(self, path: Path | None) -> None:
        from langgraph.store.memory import InMemoryStore
        self.store = InMemoryStore()
        self.path = path
        self._ns: set[tuple[str, ...]] = set()
        self._lock = threading.Lock()
        if path and path.exists():
            try:
                for ns_s, items in json.loads(path.read_text(encoding="utf-8")).items():
                    ns = tuple(ns_s.split("/"))
                    self._ns.add(ns)
                    for k, v in items.items():
                        self.store.put(ns, k, v)
            except (OSError, ValueError):
                pass

    def put(self, ns: tuple[str, ...], key: str, value: dict) -> None:
        with self._lock:
            self._ns.add(ns)
            self.store.put(ns, key, value)
            self._flush()

    def delete(self, ns: tuple[str, ...], key: str) -> None:
        with self._lock:
            self.store.delete(ns, key)
            self._flush()

    def get(self, ns: tuple[str, ...], key: str):
        return self.store.get(ns, key)

    def search(self, ns: tuple[str, ...], limit: int = 1000):
        return self.store.search(ns, limit=limit)

    def _flush(self) -> None:
        if not self.path:
            return
        dump = {"/".join(ns): {i.key: i.value for i in self.store.search(ns, limit=10000)}
                for ns in self._ns}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dump, indent=1), encoding="utf-8")


class _PostgresBackend:
    def __init__(self, url: str) -> None:
        from langgraph.store.postgres import PostgresStore
        from psycopg import Connection
        from psycopg.rows import dict_row
        conn = Connection.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        self.store = PostgresStore(conn)
        self.store.setup()

    def put(self, ns, key, value):
        self.store.put(ns, key, value)

    def delete(self, ns, key):
        self.store.delete(ns, key)

    def get(self, ns, key):
        return self.store.get(ns, key)

    def search(self, ns, limit: int = 1000):
        return self.store.search(ns, limit=limit)


def make_backend(path: Path | None = None, database_url: str | None = None):
    url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if url and url.startswith("postgres"):
        try:
            return _PostgresBackend(url)
        except Exception:  # package missing or DB down: fall back, memory is non critical
            pass
    return _PersistedInMemoryStore(path)


class GigBidMemory:
    """Facade used by nodes, the API and tests. All methods are sync and cheap."""

    def __init__(self, backend=None, cfg: dict | None = None, persist: bool = True) -> None:
        self.cfg = cfg or CFG
        if backend is None:
            p = (REPO_ROOT / self.cfg["memory"]["persist_path"]) if persist else None
            backend = make_backend(p)
        self.b = backend

    # style --------------------------------------------------------------------------------
    def record_edit(self, user_id: str, thread_id: str, draft: str, edited: str) -> list[str]:
        """Diff an approved edit, stage its signals, promote what the rule allows.

        Returns the keys promoted by this call."""
        sig = rules.extract_signals(draft, edited, self.cfg)
        stage_ns = ("style_stage", user_id)
        seq = 1 + max([i.value["seq"] for i in self.b.search(stage_ns)] or [0])
        self.b.put(stage_ns, f"{seq:08d}", {"seq": seq, "thread_id": thread_id, "signals": sig})
        rows = [i.value for i in self.b.search(stage_ns)]
        promoted = []
        for signal, threads in rules.signals_to_promote(rows, self.cfg).items():
            key = _slug(signal)
            if self.b.get(("style", user_id), key) is None:
                self.b.put(("style", user_id), key,
                           {**rules.style_item(signal, threads), "signal": signal})
                promoted.append(key)
        return promoted

    def style_notes(self, user_id: str) -> list[dict[str, Any]]:
        return [i.value for i in self.b.search(("style", user_id))]

    # outcome ------------------------------------------------------------------------------
    def record_outcome(self, user_id: str, category: str, replied: bool, thread_id: str) -> bool:
        """Count one outcome. Promotes reply_rate for the category once enough are seen."""
        ns, key = ("outcome_stage", user_id), _slug(category)
        cur = self.b.get(ns, key)
        stage = dict(cur.value) if cur else {"n": 0, "replied": 0, "threads": []}
        if thread_id in stage["threads"]:
            return False  # one outcome per thread
        stage = {"n": stage["n"] + 1, "replied": stage["replied"] + int(replied),
                 "threads": stage["threads"] + [thread_id]}
        self.b.put(ns, key, stage)
        if rules.outcome_ready(stage, self.cfg):
            self.b.put(("outcome", user_id), key, rules.outcome_item(category, stage))
            return True
        return False

    def outcome_notes(self, user_id: str) -> list[dict[str, Any]]:
        return [i.value for i in self.b.search(("outcome", user_id))]

    # viewer and delete (API) --------------------------------------------------------------
    def list(self, user_id: str) -> list[dict[str, Any]]:
        """Promoted items only: [{ns, key, value}]."""
        out = []
        for ns in PROMOTED:
            out += [{"ns": ns, "key": i.key, "value": i.value} for i in self.b.search((ns, user_id))]
        return out

    def delete(self, user_id: str, ns: str, key: str) -> bool:
        """Delete a promoted item. For style, also strip its signal from staging so it needs fresh
        evidence to come back."""
        if ns not in PROMOTED:
            return False
        item = self.b.get((ns, user_id), key)
        if item is None:
            return False
        self.b.delete((ns, user_id), key)
        if ns == "style":
            sig = item.value.get("signal")
            for row in self.b.search(("style_stage", user_id)):
                if sig in row.value["signals"]:
                    left = [s for s in row.value["signals"] if s != sig]
                    self.b.put(("style_stage", user_id), row.key, {**row.value, "signals": left})
        else:
            self.b.delete(("outcome_stage", user_id), key)
        return True
