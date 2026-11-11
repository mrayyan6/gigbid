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

Captured by `scripts/make_traces.py` (hosted open profile, LLM on). Links and run ids are in
`evals/results/traces.json`. All data in them is synthetic.

| Scenario | What it shows | Job | Public link |
|---|---|---|---|
| Skipped scam job | scam and injection signals, early exit, nothing sent | dev-ai_ml-0011 | [trace](https://smith.langchain.com/public/17cd8b5c-4725-4c11-80cb-89a8faa1213f/r) |
| Approved proposal | full path, approval interrupt, resume with approve, submit (run 1 stops at the interrupt, run 2 is the resume) | dev-ai_ml-0001 | [run to interrupt](https://smith.langchain.com/public/1f095679-3dec-4022-af76-88f6b57fcf90/r) and [resume](https://smith.langchain.com/public/fda3b80c-af0c-4f1e-a0af-46cea8d9164b/r) |
| Critic loop | writer to verifier to critic send backs (the Critic rejected this draft until its cap of 2) | dev-ai_ml-0003 | [trace](https://smith.langchain.com/public/81d46882-8722-4546-b96f-d8e13d36c693/r) |
| Crash and resume | run 1 stops at the approval interrupt and its process exits, run 2 is a new Python process on the same SQLite checkpoint file | dev-ai_ml-0005 | [before crash](https://smith.langchain.com/public/54923d56-1832-4545-8136-d56231d70e17/r) and [after restart](https://smith.langchain.com/public/3068922c-8da0-440e-841c-858bc9eee62c/r) |

Crash and resume result: before the restart the thread was interrupted with 0 proposals in the marketplace. After the restart the approval was still pending (True), approving produced status `replied`, and after a second approve the marketplace held 1 proposal (exactly once).
The marketplace in this scenario is the in process GigSim, so its state is rebuilt from the seed in the new process; the durable part under test is the graph checkpoint.
