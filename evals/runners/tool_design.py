"""R&D question A: tool design study.

40 tasks with one known correct tool and known arguments (evals/datasets/tool_tasks.json), run on three
tool sets with qwen2.5:7b-instruct through Ollama native tool calling:
  fine    the nine real Marketplace MCP tools with their real descriptions (read from the live server)
  coarse  three tools (marketplace_read, proposal, messages) that take an `action` argument
  best    the same nine fine tools with descriptions rewritten in agent/prompts/tool_descriptions_v2.md
Metrics: tool selection accuracy, argument accuracy (overall and given the right tool), tokens per task.

Every request starts with a random nonce so Ollama's prefix cache cannot hide the tool schema tokens, so
prompt_eval_count is the full prompt. A cache check (identical request twice, no nonce) is recorded.
Run: python -m evals.runners.tool_design [--n 40] -> evals/results/tool_design.json
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import re
import time
import uuid
from pathlib import Path

import httpx

from agent.nodes.config import CFG, load_prompt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "tool_design.json"
MODEL = "qwen2.5:7b-instruct"
URL = CFG["llm"]["ollama_url"].rstrip("/") + "/api/chat"

# coarse call (tool, action) -> equivalent fine tool
COARSE_MAP = {
    ("marketplace_read", "search_jobs"): "search_jobs",
    ("marketplace_read", "get_job"): "get_job",
    ("marketplace_read", "get_client_history"): "get_client_history",
    ("marketplace_read", "get_connects_balance"): "get_connects_balance",
    ("marketplace_read", "get_policy"): "get_policy",
    ("proposal", "create_draft"): "create_proposal_draft",
    ("proposal", "submit"): "submit_proposal",
    ("messages", "list"): "list_messages",
    ("messages", "send"): "send_message",
}


def _p(type_: str, desc: str, **kw) -> dict:
    return {"type": type_, "description": desc, **kw}


def coarse_tools() -> list[dict]:
    """Three coarse tools. Descriptions are plain and short, written once, not tuned."""
    def fn(name, desc, props, required):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}
    return [
        fn("marketplace_read",
           "Read marketplace data. The action selects what to read: search_jobs searches the job feed, "
           "get_job returns one job, get_client_history returns a client's public history, "
           "get_connects_balance returns the Connects balance, get_policy returns the platform policy.",
           {"action": _p("string", "What to read",
                         enum=["search_jobs", "get_job", "get_client_history", "get_connects_balance",
                               "get_policy"]),
            "query": _p("string", "Search text (search_jobs)"),
            "limit": _p("integer", "Maximum results (search_jobs)"),
            "persona": _p("string", "Persona feed (search_jobs)"),
            "job_id": _p("string", "Job id (get_job)"),
            "client_id": _p("string", "Client id (get_client_history)")},
           ["action"]),
        fn("proposal",
           "Work with proposals. The action create_draft stores a draft and spends nothing, the action "
           "submit sends the proposal to the client and spends Connects. dry_run previews without effect.",
           {"action": _p("string", "What to do", enum=["create_draft", "submit"]),
            "job_id": _p("string", "Job id"),
            "cover_letter": _p("string", "Proposal text"),
            "bid_amount": _p("number", "Price in USD"),
            "idempotency_key": _p("string", "Unique key per logical write"),
            "dry_run": _p("boolean", "Preview only")},
           ["action", "job_id", "cover_letter", "bid_amount", "idempotency_key"]),
        fn("messages",
           "Work with client messages. The action list reads messages, the action send writes a message "
           "to a client. dry_run previews without sending.",
           {"action": _p("string", "What to do", enum=["list", "send"]),
            "client_id": _p("string", "Client id"),
            "text": _p("string", "Message text (send)"),
            "idempotency_key": _p("string", "Unique key per logical write (send)"),
            "dry_run": _p("boolean", "Preview only (send)")},
           ["action"]),
    ]


async def fine_tools() -> list[dict]:
    """The nine real tools, taken from the live Marketplace MCP server definitions."""
    from mcp_servers.marketplace.server import mcp
    out = []
    for t in await mcp.list_tools():
        out.append({"type": "function", "function": {
            "name": t.name, "description": t.description or "", "parameters": t.inputSchema}})
    return out


def parse_v2() -> tuple[str, dict[str, dict]]:
    """Parse agent/prompts/tool_descriptions_v2.md into (system prompt, {tool: {desc, args}})."""
    text = load_prompt("tool_descriptions_v2")
    sections = re.split(r"(?m)^## ", text)[1:]
    out, system = {}, ""
    for sec in sections:
        name, _, body = sec.partition("\n")
        name = name.strip()
        args = dict(re.findall(r"(?m)^- (\w+): (.+)$", body))
        desc = "\n".join(ln for ln in body.splitlines() if not ln.startswith("- ")).strip()
        if name == "_system_prompt":
            system = desc
        else:
            out[name] = {"desc": desc, "args": args}
    return system, out


def best_tools(fine: list[dict], v2: dict[str, dict]) -> list[dict]:
    tools = copy.deepcopy(fine)
    for t in tools:
        f = t["function"]
        rew = v2[f["name"]]
        f["description"] = rew["desc"]
        for arg, d in rew["args"].items():
            f["parameters"]["properties"][arg]["description"] = d
    return tools


# ------------------------------------------------------------------ calling the model
async def chat(client: httpx.AsyncClient, system: str, user: str, tools: list[dict], nonce: bool) -> dict:
    sys_text = (f"[session {uuid.uuid4().hex}] " if nonce else "") + system
    body = {"model": MODEL, "stream": False, "keep_alive": "20m", "tools": tools,
            "messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "seed": 0, "num_ctx": 4096, "num_predict": 300}}
    t0 = time.perf_counter()
    r = await client.post(URL, json=body)
    r.raise_for_status()
    d = r.json()
    d["_wall_s"] = time.perf_counter() - t0
    return d


# ------------------------------------------------------------------ scoring
def _norm(s) -> str:
    return str(s).strip().casefold().rstrip(".!?,;: ")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def score_args(expected: dict, actual: dict, schema_keys: set[str]) -> tuple[bool, list[str]]:
    errs = []
    for k, want in expected.items():
        got = actual.get(k)
        if k == "idempotency_key":
            if not (isinstance(got, str) and len(got) >= 8):
                errs.append(f"{k}: missing")
        elif k == "dry_run":
            if bool(got) is not want or (got is not None and not isinstance(got, bool)):
                errs.append(f"dry_run: want {want} got {got!r}")
        elif _is_num(want):
            if not (_is_num(got) and abs(float(got) - float(want)) <= 0.01):
                errs.append(f"{k}: want {want} got {got!r}")
        else:
            if got is None or _norm(got) != _norm(want):
                errs.append(f"{k}: want {want!r} got {got!r}")
    for k, v in actual.items():
        if k in expected:
            continue
        if k not in schema_keys:
            errs.append(f"{k}: unknown argument")
        elif k == "limit" and v == 20:  # the schema default, harmless
            continue
        elif k == "dry_run" and v is False:
            continue
        elif v not in (None, "", []):
            errs.append(f"{k}: unexpected value {v!r}")
    return not errs, errs


def interpret(kind: str, name: str, args: dict) -> tuple[str, dict]:
    """Map a call on any tool set to (fine tool name, args without the action)."""
    if kind != "coarse":
        return name, args
    args = dict(args)
    action = args.pop("action", None)
    return COARSE_MAP.get((name, action), f"{name}:{action}"), args


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


async def run_set(client, kind: str, tools: list[dict], system: str, tasks: list[dict]) -> dict:
    schema = {t["function"]["name"]: set(t["function"]["parameters"].get("properties", {})) for t in tools}
    rows = []
    for t in tasks:
        d = await chat(client, system, t["instruction"], tools, nonce=True)
        calls = (d.get("message") or {}).get("tool_calls") or []
        row = {"id": t["id"], "expected_tool": t["tool"], "n_calls": len(calls),
               "prompt_tokens": d.get("prompt_eval_count", 0), "completion_tokens": d.get("eval_count", 0),
               "latency_s": round(d["_wall_s"], 2)}
        if calls:
            fn = calls[0]["function"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool, flat = interpret(kind, fn["name"], args)
            ok_tool = tool == t["tool"]
            keys = schema.get(fn["name"], set()) - ({"action"} if kind == "coarse" else set())
            ok_args, errs = score_args(t["args"], flat, keys) if ok_tool else (False, ["wrong tool"])
            row.update({"called": tool, "args": flat, "tool_ok": ok_tool, "args_ok": ok_args,
                        "arg_errors": errs})
        else:
            row.update({"called": None, "args": {}, "tool_ok": False, "args_ok": False,
                        "arg_errors": ["no tool call"]})
        rows.append(row)
        print(f"{kind} task {t['id']:>2} {'OK ' if row['args_ok'] else ('TOOL' if row['tool_ok'] else 'BAD')} "
              f"{row['called']}", flush=True)
    n = len(rows)
    tool_ok = sum(r["tool_ok"] for r in rows)
    args_ok = sum(r["args_ok"] for r in rows)
    per_tool: dict[str, dict] = {}
    for r in rows:
        s = per_tool.setdefault(r["expected_tool"], {"n": 0, "tool_ok": 0, "args_ok": 0})
        s["n"] += 1
        s["tool_ok"] += r["tool_ok"]
        s["args_ok"] += r["args_ok"]
    conf: dict[str, int] = {}
    for r in rows:
        if not r["tool_ok"]:
            k = f"{r['expected_tool']} -> {r['called']}"
            conf[k] = conf.get(k, 0) + 1
    pt = [r["prompt_tokens"] for r in rows]
    ct = [r["completion_tokens"] for r in rows]
    return {
        "n": n, "tool_selection_accuracy": round(tool_ok / n, 3), "tool_selection_ci95": wilson(tool_ok, n),
        "arg_accuracy_overall": round(args_ok / n, 3), "arg_accuracy_ci95": wilson(args_ok, n),
        "arg_accuracy_given_correct_tool": round(args_ok / tool_ok, 3) if tool_ok else None,
        "tokens_per_task": {"prompt": round(sum(pt) / n, 1), "completion": round(sum(ct) / n, 1),
                            "total": round((sum(pt) + sum(ct)) / n, 1)},
        "mean_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
        "n_tools": len(tools), "tool_definition_chars": len(json.dumps(tools)),
        "per_tool": per_tool, "tool_confusions": conf, "rows": rows,
    }


async def main(n: int) -> dict:
    tasks = json.loads((ROOT / "datasets" / "tool_tasks.json").read_text(encoding="utf-8"))["tasks"][:n]
    system, v2 = parse_v2()
    fine = await fine_tools()
    sets = {"fine": fine, "coarse": coarse_tools(), "best": best_tools(fine, v2)}
    meta = {"model": MODEL, "runtime": "ollama /api/chat native tool calling", "temperature": 0, "seed": 0,
            "n_tasks": len(tasks), "tool_set_sizes": {k: len(v) for k, v in sets.items()},
            "scoring": "see evals/datasets/tool_tasks.json meta; numeric strings are not accepted as numbers; "
                       "unknown or unexpected non-empty arguments count as errors; only the first tool call is scored",
            "tokens": "prompt_eval_count + eval_count, every request began with a random nonce so the prefix "
                      "cache cannot hide the schema tokens",
            "descriptions_v2": "agent/prompts/tool_descriptions_v2.md was written before the first run and "
                               "not edited after seeing results",
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    async with httpx.AsyncClient(timeout=180) as client:
        # warm the model (excluded from everything), then the cache check
        await chat(client, system, "Check my current Connects balance.", sets["fine"], nonce=True)
        a = await chat(client, system, tasks[0]["instruction"], sets["fine"], nonce=False)
        b = await chat(client, system, tasks[0]["instruction"], sets["fine"], nonce=False)
        meta["cache_check"] = {"first_prompt_eval_count": a.get("prompt_eval_count"),
                               "second_identical_prompt_eval_count": b.get("prompt_eval_count"),
                               "note": "a much smaller second count means the prefix cache hides tokens; "
                                       "the study avoids this with a per-request nonce"}
        res = {}
        for kind, tools in sets.items():
            res[kind] = await run_set(client, kind, tools, system, tasks)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps({"meta": meta, "results": res}, indent=1), encoding="utf-8")
    meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out = {"meta": meta, "results": res}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    o = asyncio.run(main(a.n))
    for k, v in o["results"].items():
        print(k, {x: v[x] for x in ("tool_selection_accuracy", "arg_accuracy_overall",
                                    "arg_accuracy_given_correct_tool", "tokens_per_task")})
