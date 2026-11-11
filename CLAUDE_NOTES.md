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

## API lane (T0.3, T2.5, T2.6) status
- Contract frozen: apps/web/openapi.json (18 endpoints under /api, regenerate with app.openapi()). Add fields only.
- apps/api: bootstrap.py (ctx, Postgres or SQLite checkpointer), auth/ (PBKDF2, JWT, reviewer seed), runner.py (runs, SSE hub, drain of queued runs), streaming.py, routers/. POST /api/runs returns 202 and runs in Arq (REDIS_URL) or inline task.
- Degraded mode: POST /api/test/marketplace-down (GIGBID_TEST_MODE=1), /api/health marketplace up|down, runs queue and drain on recovery.
- worker/: Arq tasks with processed and inflight Redis keys plus checkpoint resume.
- TODO adapters: paragraph regenerate (writer), draft_reply (regex intent, no Workspace slots), pipeline stages beyond replied, MCP trace header.
- Windows dev: psycopg needs the selector loop, use `python -m apps.api` (make dev).

## SAVE POINT 2026-11-11 16:45 local (PKT). Deadline 2026-11-12 23:59 PKT (about 31 h left).
Repo: https://github.com/mrayyan6/gigbid (public, branch main). GitHub workflows ci.yml and eval.yml are DISABLED on GitHub (old empty files spammed email). Re-enable only after real workflows are verified: gh workflow enable ci.yml --repo mrayyan6/gigbid.
Accounts done (secrets only in .env, gitignored, never print): Groq, LangSmith, Hugging Face (user mrayyan6, write token HF_TOKEN), Neon (DATABASE_URL, direct not pooled), Upstash (REDIS_URL). All verified connecting. TOKEN_ENCRYPTION_KEY, JWT_SECRET, REVIEWER_* not yet generated.
No 2 Nov policy text exists on Classroom: use the self-defined change request in PLAN.md section 6 (connects x1.5, min budget 50, banned external links, boost fee 2), label it self-imposed.
Done and committed: MCP layer (Marketplace, Workspace, Portfolio servers, client with allowlists and degraded mode, Upwork adapter stub, schema snapshot, docs/TOOLS.md), graph lane (LLM client, budgets, dead letter, memory with promotion rules, conversation graph), API lane (18 endpoint contract, JWT auth, Postgres checkpointer, SSE, Arq worker), web UI (all screens, 5 Playwright tests pass), RAG variants V0 dense/V0b/V1/V2/V3/V8 with rag_eval results. 80 tests passed at last full run.
In flight when saved (background Sonnet agents, may have been interrupted, files uncommitted or partial): E1 (ablation, injection_eval, smoke_eval, proposal_eval, gigsim_outcomes, x2_experiment, render_tables), E2 (tool_design done, arch_compare, model_compare), Infra (tracing, CI, Dockerfiles, compose, HF space, RUNBOOK). Check git status and each runner's evals/results file; rerun what is missing.
Known gaps: Inspector screenshots, per-agent allowlists inside graph, regenerate-paragraph, API message drafts use regex, pipeline only submitted/replied, X-Trace-Id not sent to MCP, no real Ollama run of LLM nodes yet, judge labels need the user (30 drafts), demo video needs the user.
Next steps in order: 1) check agents' results, run full pytest and npx playwright test; 2) run change request (PLAN.md section 6, tags cr-start/cr-end, evals/results/change_request.json); 3) deploy HF Space (infra/hf_space), set Space secrets, reviewer login, smoke; 4) docs: ARCHITECTURE (graphs from code), ADRs, DATA_CARD final, AI_USAGE, README with results tables, REPORT.md to PDF, WRITEUP_DRAFT; 5) LangSmith traces (4 public links) and Inspector screenshots via Chrome; 6) enable CI, final push before 2026-11-12 23:59 PKT; user: label 30 drafts, record 3 min video, post reviewer password privately on Classroom, publish write-up.
