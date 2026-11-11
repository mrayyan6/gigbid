# ADR 0006: Verify claims before the Critic sees the draft

Status: accepted.

The brief requires that unsupported claims are removed or rewritten before the Critic. The `verifier` node
(`agent/nodes/core.py`, rules in `agent/config_extra.yaml` under `verifier`) splits the draft into sentences and
labels each one:

- supported: it carries `[ev:id]` tags and every tag is a real evidence item retrieved for this job,
- unsupported: it talks about past work (regex in config) without a valid tag, or cites an unknown tag,
- no_claim: everything else (greetings, questions, plans).

Unsupported sentences are removed (never rewritten). With `llm.verify_partial` on, a model may also mark a
claim partly supported, and `verifier.drop_partial` decides whether those are dropped too.

## Known weakness

The check is structural: a sentence that cites a real tag is "supported" even if its wording says more than the
evidence does. The stricter audit in `evals/runners/_harness.py` catches some of that (numbers in a tagged
sentence must appear in the cited evidence or job context), and that is the number to read for residual risk.

## Measured effect (`evals/results/proposal_eval.json`)

By the verifier rule, unsupported sentences per proposal went from 0.33 to 0.00 for V0 and from 0.59 to 0.00 for V3.
By the stricter audit they went from 0.33 to 0.00 (V0) and from 0.71 to 0.12 (V3), so a small residue survives
verification in V3 drafts. Samples are 17 to 18 proposals per variant.
