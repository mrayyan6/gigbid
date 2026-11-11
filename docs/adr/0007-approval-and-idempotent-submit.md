# ADR 0007: Human approval by interrupt, exactly once submit

Status: accepted.

Nothing is sent without the user. The bid graph pauses at `approval` with LangGraph `interrupt()`. The payload
carries the draft, evidence, risk report, price rationale and the dry run preview. The checkpoint lives in
Postgres (SQLite in local dev), so a pending approval survives an API restart and a page refresh.

The `submit` node calls `create_proposal` with an idempotency key made from the thread id and the job id
(`_key` in `agent/graphs/bid_graph.py`), so a resume or a worker restart returns the original proposal instead
of creating a second one. Edits go through `recheck` (Compliance again, edits diffed into style memory) before
submit. An autonomy setting may skip low fit jobs but never sends.

The restart behaviour is covered by tests in `tests/integration`.
