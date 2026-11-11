# ADR 0005: In-process vector index

Status: accepted.

## Context

The portfolio corpus is small (48 portfolio items for the three personas in the generated data). The
brief requires one vector store, and `docker compose up` must run everything on a laptop. The public
deployment runs on a free host with no GPU.

## Decision

Keep embeddings in memory as a NumPy matrix next to a BM25 index (`rag/index/corpus.py`), cached on
disk under `data/processed`. Embeddings come from `BAAI/bge-small-en-v1.5` through fastembed (CPU, open
weights). The reranker is the int8 export of bge-reranker-v2-m3 with a small MiniLM fallback.

## Consequences

- No extra service to run, start or secure, and cold start is fast.
- Exact cosine search is fine at this size. A corpus of tens of thousands of chunks would need an
  approximate index (pgvector or Qdrant), and the retriever factory in `rag/retriever.py` is the only place
  that would change.
- Incremental re-indexing (brief item B1) is NOT implemented yet. At this size a full rebuild is cheap, so it
  is a known gap, not a performance problem.
