# GigBid Portfolio MCP server

A read only MCP server that lets an agent search a freelancer's evidence (case studies, past proposals, skills)
and ground proposal claims in it. Built with the official MCP Python SDK (`mcp` 1.30.0, FastMCP). Part of the
GigBid project, see the repository README.

All shipped data is **synthetic** (three invented personas, 16 case studies each).

## Run it

Not on PyPI. It runs straight from the public repository with `uvx` (tested on 2026-11-11, installs about 100
packages because the package is the whole project, so the first start takes a minute):

```
uvx --from git+https://github.com/mrayyan6/gigbid gigbid-portfolio-mcp
```

That starts the stdio transport. Add it to an MCP client, for example in a Claude Desktop style config:

```json
{ "mcpServers": { "gigbid-portfolio": {
    "command": "uvx",
    "args": ["--from", "git+https://github.com/mrayyan6/gigbid", "gigbid-portfolio-mcp"],
    "env": { "PORTFOLIO_PERSONA": "ai_ml" } } } }
```

Streamable HTTP, from a checkout of the repository:

```
FASTMCP_HOST=127.0.0.1 FASTMCP_PORT=9101 python -m mcp_servers.portfolio.server --http
```

Docker (one image holds all three GigBid MCP servers, the command picks one):

```
docker build -f infra/docker/mcp.Dockerfile -t gigbid-mcp .
docker run --rm -p 9101:9101 -e FASTMCP_HOST=0.0.0.0 -e FASTMCP_PORT=9101 gigbid-mcp \
  python -m mcp_servers.portfolio.server --http
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORTFOLIO_DATA` | repo data, else generated into a user cache dir | Directory with `portfolio.json`, or the file itself |
| `PORTFOLIO_PERSONA` | `ai_ml` | Which persona's portfolio to serve (`ai_ml`, `web`, `data`) |
| `RAG_VARIANT` | `v2_hybrid` | Retrieval variant (BM25 plus dense with reciprocal rank fusion) |
| `FASTMCP_HOST`, `FASTMCP_PORT` | `127.0.0.1`, `8000` | HTTP transport only |

## Surface

Tools, all annotated `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`:

- `search_evidence(requirement, k, filters)`: ranked evidence items with type, source, date and outcome.
- `get_case_study(id)`: one full case study.
- `list_skills()`: skills with the number of supporting items.

Resources: `portfolio://case/{id}`, `portfolio://proposal/{id}`.
Prompts: `answer_screening_question`, `map_requirements_to_evidence`.

Tool signatures are pinned by a schema snapshot test, so an unintended change fails CI.

## Trust and limits

Read only: it cannot change anything, send anything or reach the network. Retrieval is measured in the project
report (Recall@5 about 0.37 for the shipped hybrid variant on synthetic data), which says honestly that the
corpus is tiny and the gold labels partly circular.

## Tests

```
python -m pytest mcp_servers/portfolio -q
```
