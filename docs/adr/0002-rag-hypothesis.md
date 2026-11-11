# ADR 0002: RAG hypothesis, stated before the comparison is run

Status: accepted. Written before any V0..V8 result on the hardened eval exists.

## Context

The brief (R&D question B) asks for a hypothesis before running. The first retrieval pass in this
repo was weak: V0 was actually TF-IDF, the queries were 10 templated skill phrases per persona, and
V1 and V2 gave identical numbers. We are replacing it with a real dense V0 (BAAI/bge-small-en-v1.5),
BM25 + dense RRF (V2), requirement decomposition (V1), cross-encoder rerank (V3) and a corrective
loop (V8), evaluated on the full text of the dev jobs.

## Hypothesis

H1 (primary): the pipeline V1 (decompose) + V2 (hybrid RRF) + V3 (rerank) raises Evidence
Recall@5 by at least 10 percentage points over the dense V0 on dev jobs with 4 or more required
skills, averaged over the three personas.

H2: on jobs with 1 to 3 required skills the gain is smaller than on the 4 or more bucket, because
one dense query already covers few requirements.

H3: decomposition contributes most of the gain on the 4 or more bucket (a single query vector
blurs many skills), hybrid BM25 contributes on exact tool names (FastAPI, PostgreSQL), and rerank
mostly improves MRR and nDCG rather than Recall@5.

H4 (negative result we expect to possibly see): better retrieval will not move GigSim reply rate
much, because the simulator's reply model depends on risk, price and relevance of the proposal as a
whole, not on which of several valid evidence items was cited.

## Falsification

H1 is rejected if the mean Recall@5 difference (V1+V2+V3 minus V0) on the 4+ bucket is below 10
points, or if the per persona differences disagree in sign. We report n per persona and bucket and
do not drop buckets after seeing results.

## Known limitation of the measurement

Gold evidence is "portfolio items whose skill tags cover a required skill". Tags and the item text
come from the same synthetic generator, so the gold is partly circular: lexical retrievers can
exploit the "Skills:" line in the chunk text. Results measure retrieval of tagged evidence, not
human judged relevance. This is disclosed in the results notes and the data card.
