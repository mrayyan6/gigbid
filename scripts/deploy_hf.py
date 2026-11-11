"""Deploy GigBid to a Hugging Face Docker Space (infra/hf_space), pinned to the pushed git commit.

- Generates any missing deploy secrets into the gitignored .env (JWT_SECRET, TOKEN_ENCRYPTION_KEY,
  MARKETPLACE_MCP_TOKEN, WORKSPACE_MCP_TOKEN, REVIEWER_PASSWORD). Values are never printed.
- Creates or reuses the Space, uploads infra/hf_space/Dockerfile and README.md with GIGBID_COMMIT set to HEAD,
  and sets secrets and variables on the Space.
Run: python scripts/deploy_hf.py [--space gigbid-demo]
"""
from __future__ import annotations

import argparse
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402
from huggingface_hub import HfApi  # noqa: E402

ENV = ROOT / ".env"
SECRET_KEYS = ["JWT_SECRET", "TOKEN_ENCRYPTION_KEY", "MARKETPLACE_MCP_TOKEN", "WORKSPACE_MCP_TOKEN",
               "REVIEWER_PASSWORD", "DATABASE_URL", "REDIS_URL", "GROQ_API_KEY", "LANGSMITH_API_KEY"]
VARIABLES = {"GIGBID_PROFILE": "open_hosted", "LLM_ENABLED": "1", "MARKETPLACE_MODE": "mcp",
             "REVIEWER_EMAIL": "reviewer@gigbid.demo", "REVIEWER_PERSONA": "ai_ml",
             "LANGSMITH_TRACING": "true", "LANGSMITH_PROJECT": "gigbid"}


def ensure_secrets() -> dict:
    vals = dotenv_values(ENV)
    add = {}
    if not vals.get("JWT_SECRET"):
        add["JWT_SECRET"] = secrets.token_urlsafe(48)
    for k in ("MARKETPLACE_MCP_TOKEN", "WORKSPACE_MCP_TOKEN"):
        if not vals.get(k):
            add[k] = secrets.token_urlsafe(32)
    if not vals.get("TOKEN_ENCRYPTION_KEY"):
        from agent.security.tokens import new_key
        add["TOKEN_ENCRYPTION_KEY"] = new_key()
    if not vals.get("REVIEWER_PASSWORD"):
        alphabet = string.ascii_letters + string.digits
        add["REVIEWER_PASSWORD"] = "".join(secrets.choice(alphabet) for _ in range(16))
    if add:
        text = ENV.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.split("=", 1)[0] not in add]
        lines += [f"{k}={v}" for k, v in add.items()]
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("generated into .env:", ", ".join(add))
    return dotenv_values(ENV)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="gigbid-demo")
    a = ap.parse_args()
    vals = ensure_secrets()
    token, user = vals.get("HF_TOKEN"), vals.get("HF_USERNAME") or "mrayyan6"
    if not token:
        sys.exit("HF_TOKEN missing in .env")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "ls-remote", "origin", "main"], cwd=ROOT, capture_output=True, text=True).stdout
    if sha not in remote:
        sys.exit(f"HEAD {sha[:8]} is not pushed to origin/main yet, push first")
    repo = f"{user}/{a.space}"
    api = HfApi(token=token)
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
    docker = (ROOT / "infra" / "hf_space" / "Dockerfile").read_text(encoding="utf-8")
    docker = docker.replace("ARG GIGBID_COMMIT=main", f"ARG GIGBID_COMMIT={sha}", 1)
    tmp = ROOT / "data" / "processed" / "hf_space_upload"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "Dockerfile").write_text(docker, encoding="utf-8")
    (tmp / "README.md").write_text((ROOT / "infra" / "hf_space" / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    for k in SECRET_KEYS:
        if vals.get(k):
            api.add_space_secret(repo, k, vals[k])
    for k, v in VARIABLES.items():
        api.add_space_variable(repo, k, v)
    api.upload_folder(repo_id=repo, repo_type="space", folder_path=str(tmp),
                      commit_message=f"Deploy GigBid at {sha[:8]}")
    print(f"deployed {repo} at {sha[:8]}")
    print(f"url: https://{user}-{a.space}.hf.space")


if __name__ == "__main__":
    main()
