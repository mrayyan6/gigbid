import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.portfolio.server import mcp


@pytest.fixture(autouse=True)
def seed():
    from gigsim import generate
    generate.build()


async def test_tools_listed_with_readonly_annotations():
    async with connect(mcp._mcp_server) as s:
        tools = (await s.list_tools()).tools
        assert {t.name for t in tools} == {"search_evidence", "get_case_study", "list_skills"}
        assert all(t.annotations.readOnlyHint for t in tools)


async def test_search_returns_evidence_with_metadata():
    async with connect(mcp._mcp_server) as s:
        r = await s.call_tool("search_evidence", {"requirement": "churn prediction", "k": 3})
        assert not r.isError and "evidence_id" in r.content[0].text
