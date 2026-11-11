"""The single marketplace port. Adapters: mcp_servers/marketplace/adapters/gigsim.py (default)
and upwork_live.py. Selected by MARKETPLACE_MODE in config."""
from __future__ import annotations

import os
from typing import Any, Protocol


class MarketplacePort(Protocol):
    async def search_jobs(self, query: str = "", limit: int = 20,
                          persona: str | None = None) -> list[dict[str, Any]]: ...
    async def get_job(self, job_id: str) -> dict[str, Any]: ...
    async def get_client_history(self, client_id: str) -> dict[str, Any]: ...
    async def get_connects_balance(self) -> dict[str, Any]: ...
    async def list_messages(self, client_id: str | None = None) -> list[dict[str, Any]]: ...
    async def create_proposal(self, payload: dict[str, Any], idempotency_key: str,
                              dry_run: bool = False) -> dict[str, Any]: ...
    async def send_message(self, client_id: str, text: str,
                           idempotency_key: str) -> dict[str, Any]: ...


def get_marketplace(mode: str | None = None, **kw) -> MarketplacePort:
    mode = mode or os.environ.get("MARKETPLACE_MODE", "gigsim")
    if mode == "gigsim":
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
        return GigSimAdapter(**kw)
    if mode == "upwork":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
        return UpworkLiveAdapter(**kw)
    raise ValueError(f"unknown marketplace mode {mode}")
