# ADR 0001: One marketplace port, several adapters

Status: accepted.

## Context

R1 requires one marketplace port with a GigSim adapter and an Upwork adapter, switched by config. The
graph and the UI must not know which marketplace they talk to. Live mode must never be graded on
outcomes and must never submit without explicit confirmation.

## Decision

`agent/marketplace_port.py` defines one Protocol (search jobs, get job, client history, Connects balance,
policy, messages, draft proposal, submit, send message). `get_marketplace()` returns an adapter chosen by
`MARKETPLACE_MODE`:

- `gigsim`: direct HTTP to the simulator, used by fast tests.
- `mcp`: every call goes through the Marketplace MCP server (`agent/mcp_client.py`), so allowlists, rate
  limits, idempotency keys and the audit log apply. This is the default in compose and deployment (the code default is `gigsim`).
- `upwork`: the official Upwork MCP behind the same server, drafts only.

Platform rules (minimum budget, Connects multiplier, banned links) are read from `get_policy()` at run
time, not written in node code.

## Consequences

- Switching to live changes the adapter and credentials. Graph code, prompts and UI stay the same.
- The platform change request was absorbed through config only (see the change request section of the report).
- Cost: a thin mapping layer, and the live adapter can only expose what the official MCP offers.
