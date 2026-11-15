"""GitHub MCP loader: allowlist by name, input validation, content extraction."""
import pytest

from rag.ingest import github_mcp as gh


class FakeTool:
    def __init__(self, name, calls):
        self.name, self._calls = name, calls

    async def ainvoke(self, args):
        self._calls.append((self.name, args))
        return [{"type": "text", "text": "successfully downloaded text file (SHA: abc)"},
                {"type": "text", "text": "# Demo repo\nBuilt a FastAPI service with MLOps practices and NLP models for a logistics client."}]


class FakeClient:
    """Offers the real server's mix of read and write tools so the allowlist is tested."""
    def __init__(self):
        self.calls = []

    async def get_tools(self):
        return [FakeTool(n, self.calls) for n in ("get_file_contents", "delete_file", "create_pull_request",
                                                  "create_or_update_file", "search_code")]


async def test_only_the_read_tool_is_ever_called():
    c = FakeClient()
    name, text = await gh.fetch_file("octo/demo", "README.md", client=c)
    assert c.calls == [("get_file_contents", {"owner": "octo", "repo": "demo", "path": "README.md"})]
    assert name == "demo-README.md" and text.startswith("# Demo repo") and "successfully" not in text


async def test_missing_read_tool_is_an_error():
    class OnlyWrites(FakeClient):
        async def get_tools(self):
            return [FakeTool("delete_file", self.calls)]
    c = OnlyWrites()
    with pytest.raises(gh.GitHubFetchError):
        await gh.fetch_file("octo/demo", "README.md", client=c)
    assert c.calls == []


async def test_not_configured_without_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(gh.GitHubNotConfigured):
        await gh.fetch_file("octo/demo", "README.md")


@pytest.mark.parametrize("repo,path", [("nope", "README.md"), ("a/b/c", "README.md"), ("a/b", "../secrets.md"),
                                       ("a/b", "bin/tool.exe"), ("a b/c", "README.md"), ("a/b", "x;rm -rf.md")])
def test_bad_input_is_rejected_before_any_request(repo, path):
    with pytest.raises(ValueError):
        gh.parse_request(repo, path)


def test_defaults_and_code_files_are_allowed():
    assert gh.parse_request("octo/demo", None) == ("octo", "demo", "README.md")
    assert gh.parse_request("octo/demo", "/src/app.py") == ("octo", "demo", "src/app.py")
