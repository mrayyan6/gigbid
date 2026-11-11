"""Schema snapshot: fails CI when a tool name, input schema, output schema or annotation changes.

An intended change is accepted by regenerating the snapshot and committing the diff:
    UPDATE_SNAPSHOTS=1 .venv/Scripts/python -m pytest tests/contract -q
Descriptions are not part of the snapshot on purpose, so wording can be tuned freely (R&D A).
"""
import json
import os
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session as connect

SNAPSHOT = Path(__file__).parent / "snapshots" / "tools.json"


def _servers():
    from mcp_servers.marketplace.server import mcp as marketplace
    from mcp_servers.portfolio.server import mcp as portfolio
    from mcp_servers.workspace.server import mcp as workspace
    return {"portfolio": portfolio, "marketplace": marketplace, "workspace": workspace}


async def current() -> dict:
    out: dict = {}
    for name, mcp in _servers().items():
        async with connect(mcp._mcp_server) as s:
            tools = (await s.list_tools()).tools
            out[name] = {
                t.name: {"input": t.inputSchema, "output": t.outputSchema,
                         "annotations": t.annotations.model_dump(exclude_none=True)
                         if t.annotations else None}
                for t in sorted(tools, key=lambda t: t.name)}
    return json.loads(json.dumps(out, sort_keys=True))


async def test_tool_signatures_match_snapshot():
    now = await current()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for server in sorted(set(now) | set(want)):
        assert set(now.get(server, {})) == set(want.get(server, {})), f"{server}: tool set changed"
        for tool in now[server]:
            assert now[server][tool] == want[server][tool], \
                f"{server}.{tool} signature changed (UPDATE_SNAPSHOTS=1 to accept)"


async def test_every_write_tool_is_idempotent_with_dry_run():
    snap = await current()
    for server in ("marketplace", "workspace"):
        for name, t in snap[server].items():
            if t["annotations"].get("readOnlyHint"):
                continue
            assert t["annotations"].get("idempotentHint") is True, name
            assert "dry_run" in t["input"]["properties"], name


async def test_portfolio_is_read_only():
    snap = await current()
    assert all(t["annotations"]["readOnlyHint"] for t in snap["portfolio"].values())
