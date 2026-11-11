# AI usage

The brief allows AI coding assistants if this file says which tool, which files, and one thing it got
wrong that was caught. All numbers in the project come from `evals/results/`, never from the assistant.

## Tools

| Tool | Used for | Main files |
|---|---|---|
| Claude Code (Anthropic CLI, in VS Code), Sonnet class model | Scaffolding, most Python and TypeScript, tests, docs drafts, running evals and reading their output | `agent/`, `apps/api/`, `apps/web/`, `mcp_servers/`, `rag/`, `evals/runners/`, `worker/`, `docs/` |
| Local models through Ollama (qwen2.5:7b-instruct, llama3.1:8b, llama3.2:3b) | The LLM nodes under evaluation: writer, critic, judge, tool calling in the tool design study | `agent/llm.py`, `agent/prompts/` |
| Groq hosted open weight model | Public deployment profile only (no GPU on the host) | `agent/config.yaml` |

The assistant wrote code that I reviewed and ran. I own the design decisions (extension X2, the shared
marketplace port, the self imposed change request, which RAG variants ship). Judge calibration labels are
mine, never filled by the assistant.

## Things the assistant got wrong

1. **A "dense" V0 that was really TF-IDF.** The first retrieval baseline was labelled dense but used TF-IDF,
   and the early queries were templated skill phrases, so V1 and V2 gave identical numbers. It was fixed with
   a real dense embedding baseline, queries built from the full job text, and ADR 0002 (hypothesis written
   before the rerun).
2. **The graph bypassed MCP.** An early graph version did not go through the MCP layer, so the audit log,
   rate limiter and per agent allowlists were not exercised. The graph lane was then rebuilt on
   `agent/mcp_client.py`.
3. **Circular decision metrics.** Scam precision and recall are 1.0 because the simulator's scam templates
   match the risk patterns that detect them. This is documented as a limitation, not claimed as a result.
4. **Evals run against a stopped model server.** In this session the LLM based runners were started while
   Ollama was not running (about 21 seconds per job, the connection wait before the fallback). The server
   was checked, started, and the runs were redone. Lesson: check the endpoint before trusting a run.

5. **A broken summary expression left in the proposal eval.** The first agent pass wrote a garbled dictionary
   expression in `summarise()` that is valid Python but raised a NameError at the end of every run, after all
   the LLM calls had been paid for. Found when a run crashed at the final step, fixed, and the runs were redone.
6. **Wrong model name written into results.** Several runners hard coded "qwen2.5:7b-instruct" in the result
   metadata while the run used the hosted model. Caught by reading the result file against the command that made
   it. The runners now record the model from config, and the files were regenerated rather than hand edited.
7. **Results lost to a save crash.** A numpy boolean in the significance test made `json.dumps` fail after the
   whole X2 run had finished, so the run had to be repeated. Fixed with a JSON default handler in the runners.
8. **Portfolio MCP server on the wrong port in containers.** The SDK version in use ignores `FASTMCP_PORT`, so the
   server started on 8000 (the API's port) and the container never became healthy. Found by running the real
   container image, not by the unit tests, which all passed.
9. **Docker web build failing on Linux.** `npm ci` rejects a lockfile written on Windows. Found by building the
   image before deploying.
10. **Hosting assumption out of date.** The plan assumed free Docker Spaces on Hugging Face, which now need a paid
    plan (HTTP 402). The plan was not re-checked against the host's current terms.

## Rules I set for the assistant

- No em dashes or double hyphens in any text, no assistant attribution in commits.
- Every prompt in `agent/prompts/`, every threshold in config, never in code.
- Negative results are reported, not tuned away.
