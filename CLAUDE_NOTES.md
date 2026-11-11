# GigBid running notes
- Repo: D:\gigbid (not OneDrive, to avoid sync churn). Brief PDF: OneDrive A2 folder.
- Due 2026-11-12 23:59 PKT. Extension chosen: X2 Proposal experiments.
- Docker Desktop installed via winget (may need restart/WSL setup).
- Done: empty required directory layout, config.yaml, .env.example, git init.
- Next: pyproject, Portfolio MCP server, marketplace port, once kit arrives wire GigSim.
- 2026-11-11: Starter kit v0.1 zip arrived but is scaffold only, no gigsim. Instructor says we build the simulator ourselves from Kaggle datasets plus labelled synthetic data (6 dataset slugs listed in scripts/fetch_datasets.py).
- Added scripts/fetch_datasets.py (needs Kaggle token in ~/.kaggle/kaggle.json), docs/DATA_CARD.md draft, gitignore for data/raw and zips.
- Open: user adds Kaggle token and runs the fetch; then preprocessing, synthetic generators, simulator in gigsim/, merge useful kit files (marketplace_port, handoffs tests, Makefile, pyproject).

## State as of 2026-11-11 (build day)
Done and tested (`make test`, 9 tests pass): gigsim/ (own synthetic simulator, generate.py + app.py, idempotent writes, dry_run, rate limit, hidden gold), marketplace port + GigSim adapter (retries/backoff, MarketplaceUnavailable), Portfolio MCP server (3 read tools, resource, prompt, in-memory client tests), RAG V0 naive, V2 hybrid (BM25+dense RRF), V1 decompose; bid graph (parallel Send, decide, pricing, writer, claim verifier, critic max 2, compliance, interrupt approval, edit re-check, idempotent submit); FastAPI /runs with SqliteSaver (restart test proves pending approval survives and submits once).
Measured (evals/results/): retrieval Recall@5 V0 ~0.52-0.63 vs V2 ~0.53-0.65 (V2 NOT clearly better, negative result); decision F1 ~0.75 per persona, scam P/R 1.0 (circular: synthetic scam templates match the risk patterns, say so in report).
Config change vs kit: models are qwen2.5:7b-instruct / llama3.1:8b (what is installed). LLM nodes are deterministic templates; llm.enabled=false.
NOT done: Marketplace/Workspace MCP servers, V3 rerank/V8/V9, conversation graph, memory store + promotion, Postgres/Redis/worker, auth, SSE, whole web UI (Next.js + Playwright), Docker/compose, CI gates, tracing, injection ASR measurement, judge calibration, R&D questions A/B/C, deploy, report, video, extension X2, kaggle data (no token).
