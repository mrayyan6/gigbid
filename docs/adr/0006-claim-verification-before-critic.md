# ADR 0006: Verify claims before the Critic sees the draft

Status: accepted.

The brief requires that unsupported claims are removed or rewritten before the Critic. The verifier
(`agent/nodes/verifier.py`, rules in `agent/config_extra.yaml` under `verifier`) splits the draft into
sentences, treats a sentence about past work without a valid `[ev:id]` tag as unsupported, and removes it. The
audit in `evals/runners/_harness.py` is stricter (it also checks numbers against the cited evidence), so
unsupported claims are measured twice, before and after verification, and both are reported.

Measured effect (`proposal_eval.json`): unsupported sentences per proposal went from 0.33 to 0.00 for V0 and
from 0.59 to 0.00 for V3 by the verifier rule, and from 0.33 to 0.00 and 0.71 to 0.12 by the stricter audit.
The stricter audit still finds a residue in V3 drafts (numbers not in the cited evidence), which is the known gap.
