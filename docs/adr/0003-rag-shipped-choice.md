# ADR 0003: Which retrieval variant ships

Status: accepted. Numbers are from `evals/results/rag_eval.json`, `ablation.json` and `proposal_eval.json`.

## Hypothesis from ADR 0002 and what happened

- H1 (V1+V2+V3 raises Recall@5 by 10 points or more on jobs with 4+ requirements): **rejected.** V3 rerank
  gained +0.005 on the 4+ bucket (95% CI -0.010 to +0.020, n = 70 jobs), nowhere near +0.10.
- H2 (gain is smaller on 1 to 3 requirement jobs): **reversed.** The gain was larger there, +0.053 (CI +0.032
  to +0.075, n = 51).
- H3 (decomposition gives most of the 4+ gain): not supported. Removing decomposition from the best pipeline
  moved Recall@5 from 0.385 to 0.377 and 4+ Recall from 0.349 to 0.355. Removing BM25 or dense changed nothing
  because the reranker decides the final top 5 from the pooled candidates.
- H4 (better retrieval does not lift GigSim reply rate): consistent. V3 had the best retrieval numbers and the
  lower reply rate (0.24 against 0.39 for V0), but with 17 to 18 proposals per arm that gap is noise, not an
  effect.

The honest test of decomposition is the `no_marker` ablation row, because every synthetic job text contains the
literal required skills list that equals the gold labels. Without it Recall@5 fell to 0.355 and nDCG@10 to
0.884, below V0. So the decomposition variants partly read the answer key (see `docs/DATA_CARD.md`).

## Decision

Ship **V2 hybrid (BM25 + dense, RRF)** as the default retriever, and keep V3 rerank as a config switch.

Why: on a 16 item per persona corpus every variant is within a few points of V0, the differences that exist
are small or not distinguishable from noise, and V3 costs a p95 retrieval latency of about 7 s against about
90 ms for V2, plus a reranker model download on the host. The final proposal quality (judge score, unsupported
claims after verification) did not separate V0 from V3. V2 is the cheapest variant that is never worse than V0.

## Consequences

- Retrieval is not where proposal quality is won on this data. The claim verifier removed all unsupported
  claims regardless of variant, which matters more than the retriever.
- A larger, more realistic corpus and gold labels not derived from tags would be needed to see a real
  difference between variants.
