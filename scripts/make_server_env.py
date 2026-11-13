"""Write server.env for the VM from the local .env, keeping only the keys the deployed app needs.

Usage: python scripts/make_server_env.py <public-ip>
server.env is git ignored. Copy it to the VM with scp, never commit it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ["JWT_SECRET", "TOKEN_ENCRYPTION_KEY", "MARKETPLACE_MCP_TOKEN", "WORKSPACE_MCP_TOKEN",
           "REVIEWER_PASSWORD", "DATABASE_URL", "REDIS_URL", "GROQ_API_KEY", "LANGSMITH_API_KEY"]
VARIABLES = {"GIGBID_PROFILE": "open_hosted", "LLM_ENABLED": "1", "MARKETPLACE_MODE": "mcp",
             "REVIEWER_EMAIL": "reviewer@gigbid.demo", "REVIEWER_PERSONA": "ai_ml",
             "LANGSMITH_TRACING": "true", "LANGSMITH_PROJECT": "gigbid"}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/make_server_env.py <public-ip, or a domain>")
    host = sys.argv[1].strip()
    domain = host if not host.replace(".", "").isdigit() else host.replace(".", "-") + ".sslip.io"
    vals = dotenv_values(ROOT / ".env")
    lines = [f"DOMAIN={domain}"]
    lines += [f"{k}={v}" for k, v in VARIABLES.items()]
    missing = []
    for k in SECRETS:
        if vals.get(k):
            lines.append(f"{k}={vals[k]}")
        else:
            missing.append(k)
    (ROOT / "server.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote server.env for https://{domain} (keys not set locally: {', '.join(missing) or 'none'})")


if __name__ == "__main__":
    main()
