import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.portfolio import tools
from mcp_servers.portfolio.server import mcp


@pytest.fixture(autouse=True)
def seed():
    from gigsim import generate
    generate.build()


async def test_tools_listed_with_readonly_annotations():
    async with connect(mcp._mcp_server) as s:
        tools_ = (await s.list_tools()).tools
        assert {t.name for t in tools_} == {"search_evidence", "get_case_study", "list_skills"}
        assert all(t.annotations.readOnlyHint for t in tools_)


async def test_search_returns_evidence_with_metadata():
    async with connect(mcp._mcp_server) as s:
        r = await s.call_tool("search_evidence", {"requirement": "churn prediction", "k": 3})
        assert not r.isError and "evidence_id" in r.content[0].text


async def test_resource_templates_and_prompts():
    async with connect(mcp._mcp_server) as s:
        tpl = {t.uriTemplate for t in (await s.list_resource_templates()).resourceTemplates}
        assert tpl == {"portfolio://case/{id}", "portfolio://proposal/{id}"}
        case = await s.read_resource("portfolio://case/ai_ml-cs-00")
        assert json.loads(case.contents[0].text)["evidence_id"] == "ai_ml-cs-00"
        pid = tools._read("past_proposals")[0]["proposal_id"]
        prop = await s.read_resource(f"portfolio://proposal/{pid}")
        assert json.loads(prop.contents[0].text)["outcome"] in ("replied", "no_reply")
        names = {p.name for p in (await s.list_prompts()).prompts}
        assert "answer_screening_question" in names


@pytest.fixture
def restore_rag_data(monkeypatch):
    import rag.ingest.load as load_mod
    monkeypatch.setattr(load_mod, "DATA", load_mod.DATA)


def test_data_generated_into_cache_without_repo_layout(tmp_path, monkeypatch, restore_rag_data):
    monkeypatch.setattr(tools, "REPO_DATA", tmp_path / "missing")
    monkeypatch.setattr(tools, "_data_dir", None)
    monkeypatch.setattr(tools, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.delenv("PORTFOLIO_DATA", raising=False)
    assert tools.resolve_data_dir() == tmp_path / "cache"
    assert (tmp_path / "cache" / "portfolio.json").exists()


def test_portfolio_data_env_wins(tmp_path, monkeypatch, restore_rag_data):
    (tmp_path / "portfolio.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(tools, "_data_dir", None)
    monkeypatch.setenv("PORTFOLIO_DATA", str(tmp_path))
    assert tools.resolve_data_dir() == tmp_path
