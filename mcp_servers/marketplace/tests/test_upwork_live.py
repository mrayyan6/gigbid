import json
from types import SimpleNamespace

import pytest

from agent.marketplace_port import RequiresPlatformConfirmation
from agent.security.tokens import TokenError, TokenStore, decrypt, encrypt, new_key
from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter


def result(data, error=False):
    return SimpleNamespace(isError=error, structuredContent=data,
                           content=[SimpleNamespace(text=json.dumps(data))])


class FakeRemote:
    def __init__(self):
        self.calls = []

    async def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "search_jobs":
            return result({"result": [{"id": 7, "title": "ML job", "skills": [{"name": "python"}],
                                       "budget": 500, "client": {"id": "c9"},
                                       "connectsRequired": 12}]})
        if tool == "create_proposal_draft":
            return result({"id": "draft-1"})
        return result({})


def adapter(remote, tmp_path):
    store = TokenStore(tmp_path / "t.json", key=new_key())
    store.save("u1", "upwork", "oauth-secret")
    return UpworkLiveAdapter("u1", store, caller=remote)


async def test_search_maps_remote_jobs_onto_port_shape(tmp_path):
    jobs = await adapter(FakeRemote(), tmp_path).search_jobs("ml")
    assert jobs[0] == {"job_id": "7", "title": "ML job", "description": "",
                       "required_skills": ["python"], "budget": {"min": 500.0, "max": 500.0},
                       "client_id": "c9", "connects_cost": 12, "source": "upwork_live"}


async def test_writes_are_drafts_and_submit_refuses(tmp_path):
    remote = FakeRemote()
    a = adapter(remote, tmp_path)
    prev = await a.create_proposal({"job_id": "7", "cover_letter": "x", "bid_amount": 1}, "k" * 8,
                                   dry_run=True)
    assert prev["dry_run"] and remote.calls == []
    rec = await a.create_proposal({"job_id": "7", "cover_letter": "x", "bid_amount": 1}, "k" * 8)
    assert rec["status"] == "draft_created" and rec["requires_platform_confirmation"]
    with pytest.raises(RequiresPlatformConfirmation):
        await a.submit_proposal()
    with pytest.raises(RequiresPlatformConfirmation):
        await a.send_message("c9", "hi", "k" * 8)


def test_tokens_encrypted_at_rest_and_not_in_repr(tmp_path):
    key = new_key()
    store = TokenStore(tmp_path / "t.json", key=key)
    store.save("u1", "upwork", {"access_token": "AAA-secret"})
    assert "AAA-secret" not in (tmp_path / "t.json").read_text(encoding="utf-8")
    assert "AAA-secret" in store.load("u1", "upwork") and "AAA" not in repr(store)
    with pytest.raises(TokenError):
        store.load("other-user", "upwork")
    with pytest.raises(TokenError):
        decrypt(encrypt("x", key), new_key())
