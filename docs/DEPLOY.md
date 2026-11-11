# Deploying the public URL

State on 2026-11-12: the all-in-one image builds and runs, and the whole flow works against the production
configuration (Neon Postgres checkpoints, Upstash Redis worker, Groq open model). **No public host is attached
yet**, because the planned free host stopped being free.

## What was found

- Hugging Face Docker Spaces on free CPU now require a PRO subscription. Creating the Space returned
  `402 Payment Required`. This was only discovered when deploying, the plan had not re-checked the host's terms.
- The container uses about 1 GiB of memory when idle (measured with `docker stats`), so the 512 MB free tiers of
  Render and Koyeb do not fit.

## Options, in order of preference

1. **Hugging Face PRO for one month** (about 9 USD). Subscribe, then run `python scripts/deploy_hf.py`. It generates
   the missing secrets into `.env`, creates the Space, pins the build to the pushed commit and sets the secrets.
   The URL will be `https://mrayyan6-gigbid-demo.hf.space`. Then run `python scripts/smoke_live.py <url>`.
2. **Any host with at least 2 GB of memory that runs a Docker image**, for example a small paid VM or a container
   service. Build `infra/docker/all-in-one.Dockerfile`, pass the variables listed in `scripts/deploy_hf.py`
   (`SECRET_KEYS` and `VARIABLES`) as environment, expose port 7860.
3. **Laptop plus a Cloudflare quick tunnel** (no account). It works while the laptop is awake and online, and the
   URL changes every time the tunnel restarts, so it is not acceptable for the hidden test window and must be
   described as temporary. Start the container with the production env file, then
   `cloudflared tunnel --url http://localhost:7860`.

## Reviewer login

`REVIEWER_EMAIL` is `reviewer@gigbid.demo` and persona `ai_ml`. The password is generated into the git ignored
`.env` as `REVIEWER_PASSWORD` and goes only in the private Classroom comment, never in the repository.

## Keep alive

The API health check is `GET /api/health`. Point a free uptime monitor at it every 30 minutes if the host sleeps.
