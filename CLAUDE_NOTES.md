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

## 2026-11-11 evening session (single chat, no subagents, per user instruction)
- Tests: 80 pass. smoke_eval.json and evals/thresholds.yaml written (bid F1 floor 0.7, unsupported max 0.1). decision_eval_before_cr.json saved.
- Docs done: ARCHITECTURE.md (graphs rendered by scripts/render_graphs.py), AI_USAGE.md, adr 0001 and 0005.
- Finding: local Ollama (4060, 8 GB) takes about 4 min per LLM graph run, too slow for the LLM evals. Groq llama-3.1-8b-instant is retired. open_hosted profile now uses groq/qwen/qwen3.8-27b (Apache 2.0). Groq free tier: 8000 tokens/min, 1000 requests/day. Local Ollama kept for a small run to report tokens/sec.
- Eval harness loads .env (GROQ_API_KEY). Select profile with GIGBID_PROFILE=open_hosted.
- Still to run: injection_eval (running), proposal_eval, gigsim_outcomes, x2_experiment, arch_compare, model_compare (runner missing), render_tables (missing). Then change request (tags cr-start, cr-end), deploy, README, REPORT.

### Update 2026-11-11 21:00 PKT
- Done and committed: injection_eval (hosted qwen3.8-27b: ASR 0.20 off vs 0.15 on, n=20 each, CIs overlap), proposal_eval (n=18 V0, 17 V3, unsupported 0.33/0.59 before verifier, 0.0 after; V3 reply rate 0.24 vs V0 0.39, noise), gigsim_outcomes, smoke_eval + thresholds.yaml, results tables renderer, model_compare runner, failure_dump runner (not yet run), ADRs 0001 to 0007, DATA_CARD final (Kaggle NOT used), AI_USAGE, ARCHITECTURE.
- Found and fixed: proposal_eval summarise() had a garbled expression (NameError at end of run), evals mislabelled the model in metadata (now read from config), X2 and arch runners crashed on numpy bool when saving JSON.
- RUNNING overnight (local Ollama qwen2.5:7b): arch_compare --n 30 --budget-min 150, log in %TEMP%/arch.log. Do NOT run other CPU/GPU heavy work or change data/policy_pack/gigsim_policy.json until it finishes.
- Pending order: 1) arch_compare finish; 2) model_compare + failure_dump; 3) after Groq quota resets (about 07:15 PKT 12 Nov): rerun x2_experiment (full 40 jobs, first attempt lost to a save crash) and LangSmith traces; 4) change request (cr-start, edit policy json, test, cr-end, change_request_stats); 5) push, deploy HF Space, smoke; 6) README, REPORT, WRITEUP; 7) user: label 30 drafts (evals/datasets/judge_labels.csv), record video, post reviewer password in Classroom.
- Critic note: critic_revisions_mean is 3.0 everywhere. revisions counts failed critiques, so 3 means 2 send-backs then proceed (within the cap). The Critic rejects every draft, which costs latency.

### YOUR ACTIONS (owner checklist, no secrets here) as of 2026-11-11 21:15 PKT
1. Label 30 drafts: evals/datasets/judge_labels.csv, fill the user_score column (1 to 5, same rubric as agent/prompts/judge.md). Then tell Claude, it runs evals.runners.judge_calibration for Cohen kappa.
2. Record the 3 minute demo video: inbox to approved proposal, one scam caught, one injected instruction ignored, one client reply handled. Upload and send the link. Do it AFTER deploy is live (or on localhost if deploy slips).
3. Reviewer password: Claude generates it at deploy time and tells you in chat. You paste it into the PRIVATE Classroom comment only, never the repo.
4. Publish the 1200 to 1800 word write-up (Claude drafts docs/WRITEUP_DRAFT.md) and send the link.
5. Decide on a LICENSE file (none yet).
6. Submit on Google Classroom before 2026-11-12 23:59 PKT: live URL, GitHub link, report PDF, video link, Portfolio MCP and write-up links.
- Docker Desktop: installed (Docker 29.9.2, Compose 5.6.1), engine NOT running (app not started). Claude starts it after the overnight eval ends, to test the compose build. The public deploy does not need local Docker (Hugging Face builds the image).

### Update 2026-11-12 early morning (night autopilot run)
- DONE: arch_compare (graph beats ReAct and supervisor), model_compare, failure_dump, X2 rerun (A 0.263 vs B 0.150, p 0.38, not significant), change request (cr-start..cr-end, 3.7 min, no node code changed, F1 rise is a lowball=40 artifact), budget_eval (declared budgets met on dev set), four public LangSmith traces (docs/TRACES.md, evals/results/traces.json), README (built by scripts/build_readme.py), REPORT.md + REPORT.pdf (4 pages), WRITEUP_DRAFT.md (1394 words), Portfolio MCP README (uvx command tested), ADRs 0001 to 0007, CI enabled and green (ci + eval), lint clean, 84 tests pass, 5 Playwright pass, Docker image builds and runs (all-in-one, production env on Neon/Upstash/Groq works end to end via scripts/smoke_live.py).
- Bugs fixed on the way: Portfolio MCP ignored FASTMCP_PORT (SDK 1.30), Docker npm ci on Linux, proposal_eval summarise NameError, wrong model labels in results, numpy bool JSON crash.
- BLOCKER: Hugging Face Docker Spaces now need PRO (HTTP 402 on create). No public URL yet. Container gigbid-live runs locally on port 7860 with production env (restart unless-stopped). A Cloudflare quick tunnel was started once and stopped on user interrupt. Options for the user: (a) HF PRO for one month then run python scripts/deploy_hf.py, (b) Render or Koyeb free web service from the all-in-one Dockerfile (needs account), (c) quick tunnel from the laptop (temporary URL, laptop must stay on).
- Reviewer login: REVIEWER_EMAIL=reviewer@gigbid.demo, password was generated into .env (REVIEWER_PASSWORD). Tell the user in chat, never commit.
- judge_labels.csv still has 0 user scores in the repo file (checked 2026-11-11 22:00). User said they labelled them; file may be elsewhere or unsaved.
- TODO next: MCP Inspector screenshots, per-agent allowlist inside graph (known gap), demo GIF/video (user), final README fill of live URL and video link, final push before 2026-11-12 23:59 PKT.

### SAVE POINT 2026-11-12 about 08:30 PKT (deadline 2026-11-12 23:59 PKT)
- Since the last update: paragraph regeneration implemented (API plus Studio UI, tests), per agent tool allowlists enforced inside the graph (scout fetches policy into state, Compliance Guard has no marketplace access, tests/integration/test_graph_allowlists.py), interview pipeline stage derived from client messages, MCP Inspector screenshots (docs/images/inspector_*.jpg, Portfolio server only, no execution result), CI enabled and green, lint clean, 91 tests pass, 5 Playwright pass, report PDF regenerated.
- Local container gigbid-live is OLD (built before regenerate and allowlist changes). Rebuild before any deploy: docker build -f infra/docker/all-in-one.Dockerfile -t gigbid-all . then recreate the container with the env file in the scratchpad (live.env, outside the repo).
- STILL OPEN (owner): 1) public hosting (HF Docker Spaces need PRO, see docs/DEPLOY.md; then python scripts/deploy_hf.py and scripts/smoke_live.py <url>); 2) 30 judge labels are NOT in evals/datasets/judge_labels.csv (0 scored at 08:00), then run python -m evals.runners.judge_calibration and re-render tables; 3) 3 minute video; 4) reviewer password (in .env as REVIEWER_PASSWORD) into the private Classroom comment; 5) publish write-up (docs/WRITEUP_DRAFT.md); 6) LICENSE decision; 7) Classroom submission.
- STILL OPEN (Claude): README live URL and video link placeholders (GIGBID_LIVE_URL, GIGBID_VIDEO_URL env then scripts/build_readme.py), re-render report PDF after judge kappa, incremental re-indexing (not implemented), message drafts still regex based in API, final check_repo and CI green before the last push.
- Do NOT start the Cloudflare tunnel again unless the user asks (they interrupted it once).

### Update 2026-11-12 17:10 PKT
- Judge calibration DONE: instructor allowed AI labelling, so Claude wrote the 30 user_score values (not the user). kappa quadratic 0.59, unweighted 0.45, exact agreement 0.70, within one 1.0 (evals/results/judge_calibration.json). Disclosed in docs/AI_USAGE.md (new section), README, REPORT, ADR 0004. Report PDF and README regenerated. To rerun the judge: LLM_ENABLED=1 GIGBID_PROFILE=open_hosted.
- Reviewer password set in .env (simple one, user asked). Must also be set in the deploy env. Never commit .env.
- User will record the video. LICENSE explained to user, decision pending.
- STILL OPEN: public hosting choice, deploy + smoke, README live URL and video link, write-up publish, Classroom submission, final push + CI green.

### SAVE POINT 2026-11-13 (deadline extended to 2026-11-15 23:59 PKT)
- Done and pushed: judge calibration (30 labels written by Claude, kappa 0.59, disclosed in AI_USAGE, README, REPORT, ADR 0004; user writes their own disclosure elsewhere), MIT LICENSE (holder Muhammad Rayyan), write-up draft updated (1438 words, no AI note on purpose per user), Oracle deploy files (infra/oracle/: compose, Caddyfile, README with steps; scripts/make_server_env.py, server.env gitignored). Last commits: 02781bb, eae9c74, then Oracle files.
- Reviewer login: reviewer@gigbid.demo, password in .env (REVIEWER_PASSWORD), user keeps it for now.
- Hosting decision: Render free (0.1 CPU, 512 MB, sleeps) does NOT fit (app needs about 1 GiB, 8 processes). User chose Oracle Always Free ARM VM (will create account). Laptop tunnel rejected (laptop must stay on, URL changes, risks E deployment marks in hidden test run).
- USER HAS NOT STARTED ANY ORACLE STEP YET. Next session: user follows infra/oracle/README.md (create VM A1.Flex 2 OCPU 12 GB Ubuntu 24.04, open ports 80/443, SSH, install Docker, clone, scp server.env, docker compose up). Claude then runs scripts/smoke_live.py <url>, fixes any ARM build issues (ARM image not yet built or tested; Docker Desktop engine was off here).
- After deploy: fill README live URL and video link (GIGBID_LIVE_URL, GIGBID_VIDEO_URL then scripts/build_readme.py), regenerate report PDF (markdown to HTML in scratchpad, Chrome headless print), final check_repo, CI green, push.
- User does: video, publishing write-up, reviewer password in private Classroom comment, Classroom submission. kickbacks.dev ad not showing: likely no live bids on their side, nothing to fix.
- Still not done: incremental re-indexing, regex message drafts in API, X-Trace-Id to MCP, human judge labels, human pairwise panel.

### Update 2026-11-15 (Oracle VM setup via Chrome)
- Oracle account active, home region Mumbai (ap-mumbai-1), Free Trial. Done in console: VCN gigbid-vcn (10.0.0.0/16) with public subnet, internet gateway, default security list now allows TCP 22, 80, 443 from 0.0.0.0/0.
- Local SSH key made at ~/.ssh/gigbid_oracle (ed25519, no passphrase); public half pasted into the instance form. No key downloaded from the browser.
- Instance form is filled (name gigbid, Ubuntu 24.04, A1.Flex, boot volume 100 GB, public IPv4 on). Create fails: "Out of capacity for shape VM.Standard.A1.Flex in AD-1" at 2 OCPU/12 GB, then "Too many requests for the user" when retrying at 1 OCPU/6 GB. Mumbai has a single AD.
- Next: wait a few minutes, retry Create (try 2/12 then 1/6), then follow infra/oracle/README.md sections 2 to 4 over ssh -i ~/.ssh/gigbid_oracle ubuntu@<ip>.
- 2026-11-15: user declined the Oracle pay-as-you-go upgrade (hold about PKR 31,000). Plan: keep retrying A1 capacity. Chrome instance form was lost (tab moved to the payment page), rebuild it before the next Create attempt.
- Local demo stack for the video (started by Claude): GigSim on 9000, API on 8000 with DATABASE_URL and REDIS_URL empty (SQLite, inline runs) and REVIEWER_EMAIL plus REVIEWER_PASSWORD exported, web on http://localhost:3000. Note: the API only seeds the reviewer if both REVIEWER vars are in its environment (.env has only the password locally).

### PLAN 2026-11-15 (decided with user)
- Demo script PDF: .claude-context/DEMO_SCRIPT.pdf (gitignored), copy on Desktop. Jobs: approve dev-ai_ml-0001, scam dev-ai_ml-0011, injection dev-ai_ml-0015. Local app is stopped, start only when the user says.
- Hosting: keep retrying Oracle A1.Flex (1 OCPU 6 GB, Mumbai) about hourly until 18:00 PKT, user keeps laptop on. If no VM by 18:00, fall back to Hugging Face PRO one month (about USD 9) with scripts/deploy_hf.py then scripts/smoke_live.py. Oracle pay-as-you-go upgrade declined (hold about PKR 31,000).
- Hidden test: informs B, C and E, and a down URL during the run loses E deployment marks. If hosting fails, state it plainly in the report as a failure (brief says no excuses).

### 2026-11-15 Azure deploy (replaces Oracle, whose ARM capacity never freed)
- User got an Azure free account with USD 200 credit. VM gigbid in resource group gigbid-rg, centralindia, Standard_B2als_v2 (2 vCPU, 4 GB, x86), Ubuntu 24.04, public IP 20.235.68.147 (Standard SKU, static), ports 22, 80 and 443 open. Login: ssh -i ~/.ssh/gigbid_oracle azureuser@20.235.68.147 (key is the local one made earlier, name is historical).
- Done on the VM: 4 GB swap, Docker 29.9.3, repo cloned to ~/gigbid, server.env copied (made with scripts/make_server_env.py 20.235.68.147), compose build started with infra/oracle/docker-compose.yml. URL will be https://20-235-68-147.sslip.io. Oracle retry cron removed.
- Credit lasts about 30 days, then Azure stops the VM unless the account is upgraded. Remember before grades are released.
- 2026-11-15: video link (Google Drive) and write-up (https://mrayyan6.github.io/gigbid-writeup/ , repo mrayyan6/gigbid-writeup, noindex) added to README. Only the Classroom submission is left for the user.

### 2026-11-15 afternoon: required gaps closed (user asked to complete everything the brief requires)
- DONE and tested: Messages send endpoint plus enabled button (tests/integration/test_messages_send.py); incremental re-indexing with per user uploads (PDF, md, txt, json) and GitHub MCP import (rag/ingest/user_store.py, github_mcp.py, rag/index/corpus.py with_items, rag/retriever.py get_user_retriever, apps/api/routers/portfolio.py; tests in rag/tests/test_incremental.py, tests/integration/test_portfolio_upload.py, tests/unit/test_github_mcp.py); Inspector screenshots with executed results for Portfolio, Marketplace and Workspace (docs/images/inspector_*, docs/TOOLS.md); GitHub MCP exercised for real (evals/results/github_mcp_check.json, scripts/github_mcp_check.py, allowlist get_file_contents only); Portfolio server warm up fix (first search_evidence took about 25 s); pairwise panel tooling (evals/runners/pairwise_panel.py, pairs and key in evals/datasets, sheet PDF and message in D:\panel).
- Deps pinned: python-multipart 0.0.33, pypdf 7.1.0. pytest testpaths now include rag. 119 Python tests passed before the E2E run.
- Still not done (honest): live Upwork adapter never run (needs Upwork credentials), Kaggle unused, V4 to V7 and V9 optional, sample sizes small. Human panel result pending raters (user sends the sheet from D:\panel, then give the reply lines to Claude, run: python -m evals.runners.pairwise_panel score).
- GITHUB_TOKEN is NOT set on the Azure deployment (import answers 503 there).
- Next: Playwright run, push, redeploy Azure (git pull then docker compose up --build), smoke test, update D:\submission report copy, add panel result to report if raters reply.

- 2026-11-15 later: Messages is now driven by the conversation graph (thread conv:<user>:<client>, approval interrupt, edit re-check, idempotent send, rules fallback), interview slots come from the Workspace MCP server (agent/mcp_workspace.py, WORKSPACE_MCP_URL in start.sh and compose). 122 Python tests and 7 Playwright tests passed. Azure rebuilt several times, live smoke (scripts/smoke_live.py, scripts/smoke_live_features.py) passed. NOTE: test fixture pins a baseline policy without banned_link_regex, so tests that need the link rule patch gigsim.POLICY themselves. NOTE: every Azure redeploy resets the in-memory GigSim (Connects balance), so do not run approving smoke tests after the final deploy.
- Time correction: the context file entry timed 15:40 was really about 14:40 PKT.
