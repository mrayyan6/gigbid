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


# ---- policy endpoint, admin batch loader and generic optional policy rules ----

@pytest.fixture
def patch_policy(monkeypatch, tmp_path):
    import json

    from gigsim import app as gapp

    def apply(**extra):
        pol = {**json.loads(gapp.POLICY.read_text(encoding="utf-8")), **extra}
        f = tmp_path / "policy.json"
        f.write_text(json.dumps(pol), encoding="utf-8")
        monkeypatch.setattr(gapp, "POLICY", f)
        return pol
    return apply


def _proposal(job, text="hello", amount=100):
    return {"job_id": job["job_id"], "cover_letter": text, "bid_amount": amount}


async def test_policy_endpoint(mp):
    pol = await mp.get_policy()
    assert pol["version"] >= 1 and "connects_multiplier" in pol


async def test_admin_batch_load_makes_jobs_visible(mp):
    batch = [{"job_id": "hidden-001", "title": "Hidden batch job", "description": "Need FastAPI.",
              "required_skills": ["FastAPI"], "budget": {"min": 100, "max": 300},
              "client_id": "c-new", "connects_cost": 8}]
    r = await mp._req("POST", "/admin/jobs/load", json=batch)
    assert r["loaded"] == 1
    job = await mp.get_job("hidden-001")
    assert job["title"] == "Hidden batch job" and "gold" not in job
    assert (await mp.get_client_history("c-new"))["client_id"] == "c-new"


async def test_admin_batch_load_requires_token(mp):
    bad = GigSimAdapter(base_url="http://t", token="wrong", retries=1, transport=mp._client._transport)
    with pytest.raises(httpx.HTTPStatusError):
        await bad._req("POST", "/admin/jobs/load", json=[])


async def test_min_budget_rejects_low_budget_job(mp, patch_policy):
    patch_policy(min_budget_usd=10**9)
    job = (await mp.search_jobs(limit=1))[0]
    with pytest.raises(httpx.HTTPStatusError) as e:
        await mp.create_proposal(_proposal(job), "k-min")
    assert e.value.response.status_code == 422


async def test_boost_fee_and_multiplier_added_to_cost(mp, patch_policy):
    job = (await mp.search_jobs(limit=1))[0]
    patch_policy(connects_multiplier=1.0, boost_fee_connects=3)
    again = await mp.get_job(job["job_id"])
    assert again["connects_cost"] == job["connects_cost"] + 3
    r = await mp.create_proposal(_proposal(job), "k-boost", dry_run=True)
    assert r["connects_cost"] == again["connects_cost"]


async def test_banned_link_regex_rejects_cover_letter(mp, patch_policy):
    patch_policy(banned_link_regex=r"https?://")
    job = (await mp.search_jobs(limit=1))[0]
    with pytest.raises(httpx.HTTPStatusError) as e:
        await mp.create_proposal(_proposal(job, "see http://evil.example"), "k-link")
    assert e.value.response.status_code == 422
    ok = await mp.create_proposal(_proposal(job, "no links here"), "k-link2")
    assert ok["proposal_id"]


async def test_daily_proposal_cap_returns_429(mp, patch_policy):
    patch_policy(max_proposals_per_day=1)
    jobs = await mp.search_jobs(limit=2)
    await mp.create_proposal(_proposal(jobs[0]), "k-cap1")
    mp.retries = 1
    with pytest.raises(Exception) as e:
        await mp.create_proposal(_proposal(jobs[1]), "k-cap2")
    assert "429" in str(e.value)
    replay = await mp.create_proposal(_proposal(jobs[0]), "k-cap1")  # replay still fine
    assert replay["idempotent_replay"]


async def test_absent_optional_rules_mean_no_rule(mp, patch_policy):
    import json

    from gigsim import app as gapp
    base = json.loads(gapp.POLICY.read_text(encoding="utf-8"))
    for k in ("min_budget_usd", "max_proposals_per_day", "boost_fee_connects", "banned_link_regex"):
        base.pop(k, None)
    patch_policy.__wrapped__ if False else None
    import pathlib
    f = pathlib.Path(gapp.POLICY).with_name("p2.json")
    f.write_text(json.dumps(base), encoding="utf-8")
    gapp.POLICY = f
    job = (await mp.search_jobs(limit=1))[0]
    assert (await mp.create_proposal(_proposal(job, "http://ok"), "k-none"))["proposal_id"]
