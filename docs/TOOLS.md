# Tool catalogue

One row per tool. Annotations are the MCP hints (RO = readOnlyHint, D = destructiveHint, I = idempotentHint). Signatures are frozen by `tests/contract/snapshots/tools.json`; `pytest tests/contract` fails on any unintended change.

## Own servers

| Tool | Server | R/W | Annotations | Auth |
|---|---|---|---|---|
| search_evidence(requirement, k, filters) | portfolio | read | RO true, D false, I true | stdio: none (local process). HTTP: none, expose only on a private network |
| get_case_study(id) | portfolio | read | RO true, D false, I true | same |
| list_skills() | portfolio | read | RO true, D false, I true | same |
| search_jobs(query, limit, persona) | marketplace | read | RO true, D false, I true | HTTP bearer `MARKETPLACE_MCP_TOKEN`, per user rate limit, audit line |
| get_job(job_id) | marketplace | read | RO true, D false, I true | same |
| get_client_history(client_id) | marketplace | read | RO true, D false, I true | same |
| get_connects_balance() | marketplace | read | RO true, D false, I true | same |
| list_messages(client_id) | marketplace | read | RO true, D false, I true | same |
| get_policy() | marketplace | read | RO true, D false, I true | same |
| create_proposal_draft(job_id, cover_letter, bid_amount, idempotency_key, dry_run) | marketplace | write (draft, no spend) | RO false, D false, I true | same |
| submit_proposal(job_id, cover_letter, bid_amount, idempotency_key, dry_run) | marketplace | write (spends Connects) | RO false, D true, I true | same, call only after human approval |
| send_message(client_id, text, idempotency_key, dry_run) | marketplace | write | RO false, D true, I true | same, call only after human approval |
| free_slots(date_from, date_to, duration_min) | workspace | read | RO true, D false, I true | HTTP bearer `WORKSPACE_MCP_TOKEN` |
| hold_interview(slot, client_id, idempotency_key, dry_run) | workspace | write (tentative hold) | RO false, D false, I true | same |
| draft_email(to, subject, body, dry_run) | workspace | write (draft, never sent) | RO false, D false, I true | same |

Resources (portfolio): `portfolio://case/{id}`, `portfolio://proposal/{id}`. Prompts (portfolio): `answer_screening_question`, `map_requirements_to_evidence`.

## Write tool contract

- Every write takes an `idempotency_key` (8 to 128 chars). The same key returns the same result and never repeats the side effect (`idempotent_replay: true`).
- Every write takes `dry_run`. With `dry_run: true` nothing is stored or spent. The result holds the exact `would_send` payload and the Connects cost, which the approval screen shows.
- Every tool has a declared output schema (Pydantic models in `mcp_servers/marketplace/schemas.py`).
- Marketplace calls are rate limited per user (config `mcp.marketplace.rate_per_min`, 60, below the GigSim limit of 120) and appended to `data/processed/audit.jsonl` (user, tool, args with emails, phones and cards masked, result summary, trace id).

## Client discipline (agent/mcp_client.py)

- Per agent allowlists by tool name (config `mcp.allowlists`). A call outside the list raises `ToolNotAllowed` before anything is sent.
- Timeout per call and bounded retries with exponential backoff (config `mcp.client`). Failures become `MarketplaceUnavailable`; the graph then sets the thread status to `queued` (degraded mode) and the API reports `marketplace: down`.

## Third party servers

| Server | Used for | Auth | Trust rationale |
|---|---|---|---|
| Upwork official MCP (`https://mcp.upwork.com/mcp`) | Live marketplace reads and draft creation behind the same `MarketplacePort` (`mcp_servers/marketplace/adapters/upwork_live.py`) | OAuth 2.1 bearer, tokens encrypted per user with Fernet (`agent/security/tokens.py`) | First party endpoint run by the platform itself, so using it is the only sanctioned way to reach Upwork data without scraping. Drafts only, the user confirms on Upwork. Never run against a live account in this project. |
| GitHub official MCP (`ghcr.io/github/github-mcp-server`) | Loading README files for RAG ingestion | Personal access token with read only scope, `repos` toolset, `read_only` true | Maintained by GitHub, open source and pinnable by image digest. Read only toolset means it cannot change a repository. |

## Inspector

`npx @modelcontextprotocol/inspector .venv/Scripts/python -m mcp_servers.portfolio.server` (screenshots belong in `docs/images/`; not yet captured).

## MCP Inspector screenshots

Captured on 2026-11-12 with `@modelcontextprotocol/inspector` 2.13.0 against the Portfolio server over stdio
(`python -m mcp_servers.portfolio.server`):

- `docs/images/inspector_1_connected.jpg`: the server connects as `gigbid-portfolio` (protocol 2025-11-25).
- `docs/images/inspector_2_tools.jpg`: the three tools `get_case_study`, `list_skills`, `search_evidence`.
- `docs/images/inspector_3_search_evidence_annotations.jpg`: `search_evidence` with its READ-ONLY and IDEMPOTENT
  annotations and its input form (requirement, k, filters).

Not captured: a successful execution result in the Inspector. The first `search_evidence` call was still running
(model load on first use) when I stopped, so call results are covered only by the in-memory MCP client tests
(`mcp_servers/portfolio/tests`, `mcp_servers/marketplace/tests`), not by a screenshot. Inspector screenshots of the
Marketplace and Workspace servers were not taken.
