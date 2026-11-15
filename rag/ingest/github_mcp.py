"""Load repo READMEs and code through the official GitHub MCP server (a third party server we did not write).

Trust rationale (also in docs/TOOLS.md): maintained by GitHub, reached over Streamable HTTP with a read only
token. The server exposes about 49 tools including writes (create_pull_request, delete_file and more), so this
loader keeps an allowlist by name and only ever calls get_file_contents. Nothing else is exposed to any agent.
The token comes from the server environment (GITHUB_TOKEN) and is never logged or returned.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ALLOWED_TOOLS = frozenset({"get_file_contents"})
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
PATH_RE = re.compile(r"^[A-Za-z0-9_./ -]{1,200}$")
TEXT_EXT = {".md", ".markdown", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".sql", ".ipynb"}
MAX_CHARS = 200_000


class GitHubNotConfigured(Exception):
    pass


class GitHubFetchError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))


def parse_request(repo: str, path: str | None) -> tuple[str, str, str]:
    """Validate user input before anything is sent to GitHub. Returns (owner, name, path)."""
    if not REPO_RE.match(repo or ""):
        raise ValueError("repo must look like owner/name")
    path = (path or "README.md").strip().lstrip("/")
    if not PATH_RE.match(path) or ".." in path.split("/"):
        raise ValueError("path is not allowed")
    if Path(path).suffix.lower() not in TEXT_EXT:
        raise ValueError(f"only text and code files can be imported ({', '.join(sorted(TEXT_EXT))})")
    owner, name = repo.split("/", 1)
    return owner, name, path


def extract_text(result) -> str:
    """get_file_contents answers with content blocks: a status line, then the file text."""
    blocks = result if isinstance(result, list) else [result]
    parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in blocks]
    return "\n".join(p for p in parts if p and not p.startswith("successfully downloaded")).strip()


def _client():
    from langchain_mcp_adapters.client import MultiServerMCPClient
    return MultiServerMCPClient({"github": {
        "transport": "streamable_http",
        "url": os.environ.get("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/"),
        "headers": {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]}}})


async def fetch_file(repo: str, path: str | None = None, client=None) -> tuple[str, str]:
    """Read one file from a GitHub repo through the GitHub MCP server. Returns (file name, text)."""
    if client is None:
        if not configured():
            raise GitHubNotConfigured("GITHUB_TOKEN is not set on this server")
        client = _client()
    owner, name, path = parse_request(repo, path)
    tools = {t.name: t for t in await client.get_tools() if t.name in ALLOWED_TOOLS}  # allowlist by name
    if "get_file_contents" not in tools:
        raise GitHubFetchError("the GitHub MCP server did not offer get_file_contents")
    try:
        result = await tools["get_file_contents"].ainvoke({"owner": owner, "repo": name, "path": path})
    except Exception as exc:
        raise GitHubFetchError(f"GitHub could not return {owner}/{name}/{path} ({type(exc).__name__})") from exc
    text = extract_text(result)
    if not text or text.lower().startswith(("failed", "error", "not found")):
        raise GitHubFetchError(f"no file content for {owner}/{name}/{path}")
    return f"{name}-{Path(path).name}", text[:MAX_CHARS]
