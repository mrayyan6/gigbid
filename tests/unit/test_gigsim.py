import httpx
import pytest

from gigsim import generate
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter


@pytest.fixture
async def mp():
    generate.build()
    from gigsim.app import app, store
    store.reset()
    return GigSimAdapter(base_url="http://t", transport=httpx.ASGITransport(app=app))


async def test_search_hides_gold(mp):
    jobs = await mp.search_jobs(limit=5)
    assert jobs and all("gold" not in j for j in jobs)


async def test_proposal_idempotent_and_spends_once(mp):
    job = (await mp.search_jobs(limit=1))[0]
    before = (await mp.get_connects_balance())["balance"]
    pl = {"job_id": job["job_id"], "cover_letter": "hello", "bid_amount": 100}
    a = await mp.create_proposal(pl, "k1")
    b = await mp.create_proposal(pl, "k1")
    assert a["proposal_id"] == b["proposal_id"]
    assert before - (await mp.get_connects_balance())["balance"] == a["connects_spent"]


async def test_dry_run_spends_nothing(mp):
    job = (await mp.search_jobs(limit=1))[0]
    before = (await mp.get_connects_balance())["balance"]
    r = await mp.create_proposal({"job_id": job["job_id"], "cover_letter": "x", "bid_amount": 1}, "k", True)
    assert r["dry_run"] and (await mp.get_connects_balance())["balance"] == before
