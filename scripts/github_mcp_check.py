"""Exercise the official GitHub MCP server for real and record the result in evals/results/github_mcp_check.json.

Run:  GITHUB_TOKEN=<read only token> python scripts/github_mcp_check.py [owner/name] [path]
Lists the server's tools, confirms our allowlist keeps only get_file_contents, reads one file, and ingests it
into a throwaway user store to show the incremental index embedding only the new chunks. The token is read from
the environment and is never written anywhere.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(repo: str, path: str) -> dict:
    os.environ["USER_PORTFOLIO_DIR"] = tempfile.mkdtemp()
    from rag.ingest import github_mcp as gh
    from rag.ingest.user_store import add_texts, load_user_items
    from rag.retriever import user_corpus

    client = gh._client()
    t0 = time.perf_counter()
    offered = sorted(t.name for t in await client.get_tools())
    list_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    name, text = await gh.fetch_file(repo, path, client=client)
    fetch_s = time.perf_counter() - t0
    res = add_texts("check-user", "ai_ml", [(name, text)])
    _, stats = user_corpus("ai_ml", "check-user")
    item = load_user_items("check-user")[0] if res["added"] else {}
    out = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "server": "https://api.githubcopilot.com/mcp/ (official GitHub MCP server, Streamable HTTP)",
           "client": "langchain-mcp-adapters MultiServerMCPClient",
           "tools_offered": len(offered),
           "write_tools_offered_but_blocked": sorted(n for n in offered if n not in gh.ALLOWED_TOOLS
                                                     and n.split("_")[0] in {"create", "delete", "update", "merge", "push", "fork"}),
           "allowlist": sorted(gh.ALLOWED_TOOLS), "repo": repo, "path": path,
           "file_chars": len(text), "list_tools_seconds": round(list_s, 2), "fetch_seconds": round(fetch_s, 2),
           "ingested": res, "ingested_type": item.get("type"), "ingested_source": item.get("source"),
           "ingested_skills": item.get("skills"), "chunks_embedded": stats["chunks_embedded"],
           "note": "token came from the environment and is not stored; the repo read is public"}
    dest = ROOT / "evals" / "results" / "github_mcp_check.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "mrayyan6/gigbid",
                                      sys.argv[2] if len(sys.argv) > 2 else "mcp_servers/portfolio/README.md")), indent=1))
