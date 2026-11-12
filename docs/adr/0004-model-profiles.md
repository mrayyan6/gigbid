# ADR 0004: Model profiles and where evaluations run

Status: accepted.

## Context

The brief requires an open weight profile that the deployed link works on, with routing by node, and a
comparison of at least two open configurations. The laptop has an 8 GB RTX 4060. The free host has no GPU.

## Decision

- Profile `open`: local Ollama. llama3.2:3b for analyst, risk, intent and verifier, qwen2.5:7b-instruct for
  writer, critic, liaison and judge.
- Profile `open_hosted`: Groq, qwen/qwen3.8-27b (Apache 2.0 open weights) for every node, local llama3.2:3b as
  the fallback. This is the profile the public deployment uses. The earlier plan named llama-3.1-8b-instant,
  which Groq no longer serves (HTTP 404 on 2026-11-11).
- Evaluations that run the full graph with LLM nodes use `open_hosted`, because the local graph takes minutes
  per job on 8 GB of VRAM with CPU offload (measured in `model_compare.json`). The architecture comparison
  (R&D question C) and the tool design study use local qwen2.5:7b-instruct by design.

## Limits

- Groq free tier: 8,000 tokens per minute and 1,000 requests per day. This capped sample sizes (n = 17 to 40
  per arm) and is stated in every results file.
- Hosted price per token is from a third party listing and is marked "verify before quoting" in the config.
- Judge and writer are the same model within a config, so judge scores are not comparable across configs.
  Kappa against 30 labels (written by an AI assistant, with instructor permission) is 0.59, see AI_USAGE.md.
