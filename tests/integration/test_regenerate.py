"""Paragraph regeneration: model off leaves the draft alone, model on rewrites it and keeps it safe."""
import contextlib

from agent import llm
from tests.integration.api_helpers import (
    boot,
    client,
    find_bid_run,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
)


def _fake(text):
    def complete(node, system, user, **kw):
        return llm.LLMResult(text, "fake/model", 10, 20, 5)
    return complete


@contextlib.asynccontextmanager
async def pending(tmp_path, monkeypatch):
    """A booted API with one run waiting for approval. Yields (client, auth headers, run)."""
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    try:
        async with client(app) as c:
            h = await make_user(app, "regen@example.com")
            yield c, h, await find_bid_run(c, h)
    finally:
        await cm.__aexit__(None, None, None)


async def test_model_off_leaves_draft_unchanged(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    async with pending(tmp_path, monkeypatch) as (c, h, run):
        r = await c.post(f"/api/proposals/{run['thread_id']}/regenerate", json={"paragraph_index": 0}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["regenerated"] is False and "language model" in body["message"]


async def test_regenerate_updates_the_pending_draft(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    async with pending(tmp_path, monkeypatch) as (c, h, run):
        tid = run["thread_id"]
        ev = run["evidence"][0]["evidence_id"]
        monkeypatch.setenv("LLM_ENABLED", "1")
        monkeypatch.setattr(llm, "complete", _fake(f"A fresh opening about this project, backed by my earlier work [ev:{ev}]."))
        r = await c.post(f"/api/proposals/{tid}/regenerate", json={"paragraph_index": 0}, headers=h)
        body = r.json()
        assert r.status_code == 200 and body["regenerated"] is True, body
        assert "A fresh opening" in body["draft"]["cover_letter"]
        again = (await c.get(f"/api/runs/{tid}", headers=h)).json()
        assert again["status"] == "awaiting_approval"  # nothing was sent
        assert "A fresh opening" in again["pending_approval"][0]["draft"]["cover_letter"]


async def test_banned_text_is_not_accepted(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    async with pending(tmp_path, monkeypatch) as (c, h, run):
        tid = run["thread_id"]
        before = run["pending_approval"][0]["draft"]["cover_letter"]
        monkeypatch.setenv("LLM_ENABLED", "1")
        monkeypatch.setattr(llm, "complete", _fake("I guarantee results and you can reach me on telegram."))
        r = await c.post(f"/api/proposals/{tid}/regenerate", json={"paragraph_index": 0}, headers=h)
        body = r.json()
        assert body["regenerated"] is False and "platform rules" in body["message"]
        assert body["draft"]["cover_letter"] == before


async def test_out_of_range_index_is_422(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    async with pending(tmp_path, monkeypatch) as (c, h, run):
        r = await c.post(f"/api/proposals/{run['thread_id']}/regenerate", json={"paragraph_index": 9}, headers=h)
        assert r.status_code == 422
