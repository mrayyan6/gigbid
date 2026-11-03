# GigBid project instructions

- ALWAYS read `.claude-context/ASSIGNMENT_CONTEXT.md` BEFORE acting on every prompt, and re-check it AFTER finishing each prompt. After any meaningful progress or decision, update its STATUS section and `CLAUDE_NOTES.md`.
- `.claude-context/` is gitignored and may be missing in a fresh clone. If so, ask the user for it instead of guessing the assignment requirements.
- Never modify `gigsim/`. Never commit `.env`, tokens or the hidden test set.
- Every prompt lives in `agent/prompts/`. Rules and thresholds live in config, not code.
- No em dashes or double hyphens in any text. No Claude attribution in commits.
- If something is unclear, ask the user with AskUserQuestion.
