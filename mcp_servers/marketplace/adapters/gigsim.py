from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class MarketplaceUnavailable(Exception):
    """Raised when GigSim cannot be reached after bounded retries (degraded mode)."""


class GigSimAdapter:
    def __init__(self, base_url: str | None = None, token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, retries: int = 3,
                 timeout: float = 10.0):
        self.base_url = base_url or os.environ.get("GIGSIM_URL", "http://localhost:9000")
        self.token = token or os.environ.get("GIGSIM_TOKEN", "gigsim-dev-token")
        self.retries = retries
        self._client = httpx.AsyncClient(base_url=self.base_url, transport=transport,
                                         timeout=timeout,
                                         headers={"Authorization": f"Bearer {self.token}"})

    async def _req(self, method: str, url: str, **kw) -> Any:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = await self._client.request(method, url, **kw)
                if r.status_code in RETRY_STATUS:
                    wait = float(r.headers.get("Retry-After", 2 ** attempt * 0.2))
                    last = MarketplaceUnavailable(f"{r.status_code} from GigSim")
                    await asyncio.sleep(min(wait, 5))
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.TransportError as e:
                last = MarketplaceUnavailable(str(e))
                await asyncio.sleep(2 ** attempt * 0.2)
        raise MarketplaceUnavailable(str(last))

    async def search_jobs(self, query: str = "", limit: int = 20, persona: str | None = None):
        params = {"query": query, "limit": limit}
        if persona:
            params["persona"] = persona
        return await self._req("GET", "/jobs", params=params)

    async def get_job(self, job_id: str):
        return await self._req("GET", f"/jobs/{job_id}")

    async def get_client_history(self, client_id: str):
        return await self._req("GET", f"/clients/{client_id}/history")

    async def get_connects_balance(self):
        return await self._req("GET", "/connects")

    async def list_messages(self, client_id: str | None = None):
        return await self._req("GET", "/messages", params={"client_id": client_id} if client_id else None)

    async def create_proposal(self, payload: dict, idempotency_key: str, dry_run: bool = False):
        return await self._req("POST", "/proposals", json=payload, params={"dry_run": dry_run},
                               headers={"Idempotency-Key": idempotency_key})

    async def send_message(self, client_id: str, text: str, idempotency_key: str):
        return await self._req("POST", "/messages", json={"client_id": client_id, "text": text},
                               headers={"Idempotency-Key": idempotency_key})
