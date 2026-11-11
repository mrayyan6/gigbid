# Traces

How tracing works, how to read one, and where the public trace links go.

## Setup

- Library: LangSmith, configured in `agent/observability.py` and started from the API lifespan
  (`apps/api/main.py`, `setup_tracing()`).
- Environment: `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` (secret), `LANGSMITH_PROJECT=gigbid`.
  Without a key (or without `LANGSMITH_TRACING=true`) tracing is off and nothing leaves the process.
- PII: the shared LangSmith client is built with an anonymizer made from the rules in
  `agent/security/pii.py` (emails, card numbers, phone numbers, API style secrets). The same
  `mask()` function is used by the MCP audit log and by the log filter
  (`install_log_masking()`), so one rule set covers traces, audit lines and application logs.

## One id across systems

1. The API middleware (`TraceIdMiddleware` in `apps/api/main.py`) takes `X-Trace-Id` from the request
   or creates one, and echoes it in the response header.
2. `apps/api/runner.py` copies it into the graph config metadata (`trace_id`, `user_id`,
   `job_thread`). `agent.observability.run_config()` adds the tag `trace:<id>`.
3. `agent/mcp_client.py` sends it to the MCP servers as the `X-Trace-Id` header. The Marketplace
   server writes it into each `audit.jsonl` line (`trace_id` field).

To follow a run: take the `X-Trace-Id` from the response, search LangSmith for metadata
`trace_id = <id>` (or tag `trace:<id>`), and `grep <id> audit.jsonl` for the tool calls.

Per node token and cost metadata can be attached with `agent.observability.usage_metadata()`.

## Public traces

Not yet captured. Fill this table after running the four scenarios with a LangSmith key, then make
each trace public (Share, Public link) and paste the URL. Do not invent links.

| Scenario | What it shows | Trace id | Public link |
|---|---|---|---|
| Skipped scam job | injection and scam signals, early exit | not captured | not captured |
| Approved proposal | full path, interrupt, approval, submit | not captured | not captured |
| Critic loop | writer sent back by the critic (max 2) | not captured | not captured |
| Crash and resume | run resumed from checkpoint after a kill | not captured | not captured |
