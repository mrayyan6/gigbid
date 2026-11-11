"""Config loader. agent/config.yaml is the base, agent/config_extra.yaml is deep merged over it."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_DIR.parent


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    base = yaml.safe_load((AGENT_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
    extra_path = AGENT_DIR / "config_extra.yaml"
    extra = yaml.safe_load(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
    return deep_merge(base, extra or {})


CFG = load_config()


def load_prompt(name: str) -> str:
    return (AGENT_DIR / "prompts" / f"{name}.md").read_text(encoding="utf-8")
