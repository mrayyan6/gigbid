# GigBid runbook

Operational notes for starting, stopping, demoing failure modes and running the deployed app.
Status legend used below: "run" means the command was executed while writing this file, "written"
means it was written from the code but not executed. See the table at the end.

## 1. Start and stop

### Local without Docker (Windows, fastest for development)

```
.venv/Scripts/python -m gigsim.generate                      # once, data/processed is git-ignored
.venv/Scripts/python -m uvicorn gigsim.app:app --port 9000   # GigSim
.venv/Scripts/python -m apps.api                             # API on :8000 (selector loop on Windows)
cd apps/web && npm run build && npm run start                # web on :3000, proxies /api to :8000
```

Optional: `.venv/Scripts/arq worker.main.WorkerSettings` (needs `REDIS_URL`), and the MCP servers
`python -m mcp_servers.marketplace.server --http` (needs `MARKETPLACE_MCP_TOKEN`, port 9100),
`python -m mcp_servers.workspace.server --http` (needs `WORKSPACE_MCP_TOKEN`, port 9200) and
`python -m mcp_servers.portfolio.server --http`. With `MARKETPLACE_MODE=gigsim` the graph talks to
GigSim directly, with `MARKETPLACE_MODE=mcp` it goes through the Marketplace MCP server
(`MARKETPLACE_MCP_URL`, `MARKETPLACE_MCP_TOKEN`). Stop with Ctrl+C in each terminal.

### Local with Docker Compose

```
copy .env.example .env      # then fill JWT_SECRET, TOKEN_ENCRYPTION_KEY, MARKETPLACE_MCP_TOKEN,
                            # WORKSPACE_MCP_TOKEN, REVIEWER_PASSWORD (see comments in the file)
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
docker compose --env-file .env -f infra/docker-compose.yml --profile open up -d   # adds Ollama
curl http://localhost:8000/api/health        # API
start http://localhost:3000                  # web UI
docker compose -f infra/docker-compose.yml down          # stop, keeps volumes
docker compose -f infra/docker-compose.yml down -v       # stop and wipe Postgres, Redis, state
```

Services: web 3000, api 8000, gigsim 9000, mcp-marketplace 9100, mcp-portfolio 9101,
mcp-workspace 9102, postgres and redis (internal), ollama 11434 (profile `open`). Inside the stack
the API and worker use Postgres, Redis and `MARKETPLACE_MODE=mcp`, whatever `.env` says, because the
compose file overrides those variables. The `--env-file .env` flag matters: Compose looks for `.env`
next to the compose file (`infra/`), not in the repo root.

### Single container (same image as the deployment)

```
docker build -f infra/docker/all-in-one.Dockerfile -t gigbid-all .
docker run --rm -p 7860:7860 -e REVIEWER_PASSWORD=change-me gigbid-all
curl http://localhost:7860/api/health
```

`infra/docker/start.sh` starts GigSim, the three MCP servers, the API, the worker (only when
`REDIS_URL` is set) and Next.js on `$PORT` (7860). If any service dies the container exits so the
platform restarts it.

## 2. Degraded mode demo (kill the marketplace server)

Goal: show that the UI says the marketplace is unavailable, queues work, and recovers on its own.

1. Compose or single process with `MARKETPLACE_MODE=mcp`. Log in and open the dashboard.
2. Kill the marketplace side: `docker compose -f infra/docker-compose.yml stop mcp-marketplace`
   (locally: Ctrl+C the `mcp_servers.marketplace.server` process).
3. `/api/health` now returns `{"status":"degraded","marketplace":"down",...}` within
   `api.health_probe_timeout_s` (2 s). The web banner (`MarketplaceBanner`) shows
   "Marketplace unavailable, work is queued".
4. Start a job run. It is stored with status `queued` instead of failing. The MCP client retried with
   backoff first (`mcp.client.retries`, `mcp.client.backoff_s`, `mcp.client.timeout_s` in config).
5. Start the server again (`docker compose ... start mcp-marketplace`). The next `/api/health` poll
   sees it up and drains queued runs automatically. The banner disappears.

For a deterministic demo without killing anything, set `GIGBID_TEST_MODE=1` and call
`POST /api/test/marketplace-down` with `{"down": true}` then `{"down": false}`. This is what the
Playwright test does. It is disabled (404) outside test mode.

## 3. Crash and resume demo

Goal: show that a pending approval survives a process crash and that nothing is submitted twice.

1. Start a run for a job. Wait until the run page shows the approval screen (the graph is stopped at
   `interrupt()`, state is in the checkpointer: Postgres when `DATABASE_URL` is set, else SQLite at
   `data/processed/checkpoints.sqlite`).
2. Kill the API hard: `docker compose ... kill api` or end the `python -m apps.api` process.
3. Start it again. Reload the run page. The same draft and the same approval request are shown,
   because the thread id and its checkpoint are unchanged.
4. Approve. The submit step uses an idempotency key, so a retry after a crash never creates a second
   proposal. The restart test in `tests/` covers the same path.
5. Use the trace id from the response header `X-Trace-Id` to find the run in LangSmith and the lines
   in `audit.jsonl` (see `docs/TRACES.md`).

## 4. Live mode poll interval

Live mode means the official Upwork MCP server. Reads are deliberately slow:
`worker.live_scout_interval_minutes: 120` and `mcp.live.poll_minutes: 60` in config. Reasons:

- The official MCP is rate limited and the platform bans bots, so burst polling risks the account.
- Proposals are human paced (every proposal needs approval), so a fresh job list every hour or two
  loses nothing a person could act on.
- The brief forbids scraping like behaviour. A few reads per hour is the opposite of scraping.
- GigSim mode is local, so its interval is 30 minutes (`worker.gigsim_scout_interval_minutes`) and
  per saved search the worker floors live intervals (`worker/tasks.py`).

Writes in live mode are drafts only. The user confirms on Upwork. Live mode is never auto submitted.

## 5. Hidden test batch loader

GigSim can ingest an extra batch of jobs at run time (for example the instructor's hidden test set):

```
curl -X POST http://localhost:9000/admin/jobs/load ^
  -H "Authorization: Bearer %GIGSIM_TOKEN%" -H "Content-Type: application/json" ^
  --data @batch.json
```

The body is a JSON list of jobs (`job_id`, `client_id`, `title`, `description`, `budget`, ...).
Unknown clients get a neutral stub, missing gold fields get neutral defaults. The response is
`{"loaded": N, "total_jobs": M}`. Loaded jobs live in memory only: after a GigSim restart, regenerate
from the seed and load the batch again. The hidden set must never be committed to the repo.

On the deployed Space only port 7860 is public and GigSim listens on 127.0.0.1 inside the container,
so the loader cannot be called from outside. Load the batch from inside the container, or ask the
owner to expose a proxy route. This gap is listed in the status table.

## 6. Reviewer password rotation

The API seeds the reviewer user at startup from `REVIEWER_EMAIL`, `REVIEWER_PASSWORD` and
`REVIEWER_PERSONA` (`apps/api/auth`, idempotent: it refreshes the stored hash when the value changes).

1. Generate a password: `python -c "import secrets; print(secrets.token_urlsafe(12))"`.
2. Update the secret: Hugging Face Space settings, Variables and secrets, edit `REVIEWER_PASSWORD`
   (or `.env` locally). Restart the Space or the API.
3. Log in with the new password to confirm. The old password stops working at once.
4. Share it only in the private Classroom comment. Never put it in the repo, README or report.

Also rotate `JWT_SECRET` if a token leaked (this signs everyone out) and
`MARKETPLACE_MCP_TOKEN` / `WORKSPACE_MCP_TOKEN` (change in the API and MCP side together).

## 7. Keep alive monitor

Free Spaces sleep after a period without traffic and the local disk is ephemeral. To keep the demo up
during grading:

1. Create a free monitor (cron-job.org or UptimeRobot) that requests
   `https://<space-subdomain>.hf.space/api/health` every 30 minutes.
2. Treat HTTP 200 as healthy. The body says `"status":"degraded"` when the marketplace is down, which
   is still a live app.
3. Keep `DATABASE_URL` (Postgres) set so pending approvals and users survive a restart, and
   `REDIS_URL` so the worker queue survives too. Without them state lives in the container disk.

## 8. Redeploy to the Space

1. Push the repo to GitHub and note the commit SHA.
2. In the Space repo (`git clone https://huggingface.co/spaces/<user>/gigbid-demo`), copy
   `infra/hf_space/Dockerfile` and `infra/hf_space/README.md` to the root.
3. Set `ARG GIGBID_COMMIT=<sha>` in the Dockerfile (or pass it as a build variable), commit, push.
4. Set the Space secrets listed at the top of `infra/hf_space/Dockerfile`. Embedding models are baked
   into the image, so there is no download at start.
5. Smoke: open the URL, log in as the reviewer, run one job to approval, approve, see the pipeline
   card.

## 9. Verification status of this document

| Item | Status |
|---|---|
| `docker compose config` on `infra/docker-compose.yml` | run, valid |
| API image build | see the final report of the infra lane (build is slow) |
| All-in-one image build and `/api/health` on a mapped port | see the final report |
| Full `docker compose up` stack | not run |
| Degraded mode, crash and resume steps | written from the code, exercised by the API and Playwright tests |
| Hidden batch loader through the public Space | gap, see section 5 |
| Keep alive monitor | written, needs the owner to create the monitor |
