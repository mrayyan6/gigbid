"""Two open LLM configurations compared on the same dev jobs.

  local   profile open, Ollama on the laptop (analyst/risk llama3.2:3b, writer/critic/judge qwen2.5:7b-instruct)
  hosted  profile open_hosted, Groq qwen3.8-27b (open weights, Apache 2.0) for every node

Both come from proposal_eval.py runs (evals/results/model_local.json and proposal_eval.json). Only jobs present in
both files, for the best retrieval variant, are compared. Local tokens per second is measured directly from the
Ollama response (eval_count / eval_duration). Hosted cost is USD from the list price in agent/config_extra.yaml.

Run (after both proposal runs exist): python -m evals.runners.model_compare
Output: evals/results/model_compare.json
"""
from __future__ import annotations

import json
import platform
import subprocess

import httpx

from evals.runners._harness import CFG, RESULTS
from evals.runners.proposal_eval import summarise

PROMPT = "Write a 120 word cover letter for a freelance data analyst bidding on a dashboard project."
LOCAL_MODELS = ["qwen2.5:7b-instruct", "llama3.2:3b"]


def ollama_tps(model: str) -> dict:
    url = CFG["llm"].get("ollama_url", "http://localhost:11434")
    body = {"model": model, "prompt": PROMPT, "stream": False, "options": {"num_predict": 160, "temperature": 0}}
    httpx.post(url + "/api/generate", json={**body, "options": {"num_predict": 4}}, timeout=300)  # warm load
    r = httpx.post(url + "/api/generate", json=body, timeout=300).json()
    return {"model": model, "tokens_per_s": round(r["eval_count"] / (r["eval_duration"] / 1e9), 1),
            "eval_tokens": r["eval_count"]}


def gpu() -> str:
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    local = json.loads((RESULTS / "model_local.json").read_text(encoding="utf-8"))
    hosted = json.loads((RESULTS / "proposal_eval.json").read_text(encoding="utf-8"))
    best = local["meta"]["best_variant"]
    lrec = [r for r in local["records"] if r["variant"] == best]
    ids = {r["job_id"] for r in lrec}
    hrec = [r for r in hosted["records"] if r["variant"] == best and r["job_id"] in ids]
    common = {r["job_id"] for r in hrec} & ids
    lrec = [r for r in lrec if r["job_id"] in common]
    hrec = [r for r in hrec if r["job_id"] in common]
    tps = [ollama_tps(m) for m in LOCAL_MODELS]
    main_tps = next(t["tokens_per_s"] for t in tps if t["model"] == "qwen2.5:7b-instruct")
    rows = []
    for name, recs, meta, t in (("local_open", lrec, local["meta"], main_tps),
                                ("hosted_open", hrec, hosted["meta"], None)):
        s = summarise(recs)
        rows.append({"config": name, "model": meta["models"]["writer"], "analyst_model": meta["models"]["analyst"],
                     "n": s["n_proposals"], "judge_score": s["judge_score"],
                     "unsupported_per_proposal": s["unsupported_per_proposal"],
                     "unsupported_per_proposal_before": s["unsupported_per_proposal_before"],
                     "p50_latency_s": s["p50_latency_s"], "p95_latency_s": s["p95_latency_s"],
                     "tokens_per_proposal": s["tokens_per_proposal"], "tokens_per_s": t,
                     "cost_per_proposal_usd": s["cost_per_proposal_usd"], "reply_rate": s["reply_rate"]})
    out = {"meta": {"variant": best, "common_jobs": sorted(common), "n_common": len(common),
                    "local_hardware": gpu(), "os": platform.platform(),
                    "judge_caveat": "the judge is the writer model of each config (self judging) and is uncalibrated, "
                                    "so judge scores are not comparable across configs",
                    "latency_caveat": "hosted latency includes Groq free tier token per minute pacing; local latency is "
                                      "8 GB VRAM with partial CPU offload",
                    "cost_note": "local: 0 USD per token, laptop hardware not costed; hosted: list price per 1M tokens in "
                                 "agent/config_extra.yaml (third party listing, verify before quoting)"},
           "local_tokens_per_s": tps, "configs": rows}
    (RESULTS / "model_compare.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
