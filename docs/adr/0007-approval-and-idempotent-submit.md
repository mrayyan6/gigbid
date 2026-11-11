# ADR 0007: Human approval by interrupt, exactly once submit

Status: accepted.

Nothing is sent without the user. The bid graph pauses at `approval` with LangGraph `interrupt()`, the payload
carries the draft, evidence, risk report, price rationale and the dry run preview. The checkpoint lives in
Postgres (SQLite in local dev), so a pending approval survives an API restart and a page refresh. The submit
tool carries an idempotency key built from the thread, so a resume or worker restart returns the original
result instead of creating a second proposal. The restart tests in `tests/integration` cover this. Edits go
through `recheck` (Compliance again) before submit. An autonomy setting may skip low fit jobs but never sends.
