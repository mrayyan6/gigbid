"""Portfolio upload: files become the user's own evidence, indexed incrementally and used by their runs."""
import rag.retriever as retr_mod
from tests.integration.api_helpers import (
    boot,
    client,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
)

MD = (b"# Invoice OCR pipeline\nBuilt an OCR and NLP pipeline in Python and FastAPI for a logistics client. "
      b"Cut manual data entry by 70% and reduced errors from 9% to 2%. Deployed with MLOps practices.")


async def test_upload_is_incremental_private_and_used_by_runs(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    monkeypatch.setenv("USER_PORTFOLIO_DIR", str(tmp_path / "uploads"))
    retr_mod._user_corpora.clear()
    retr_mod._user_retrievers.clear()
    app, cm = await boot()
    try:
        async with client(app) as c:
            h = await make_user(app, "up1@example.com")
            other = await make_user(app, "up2@example.com")

            r = await c.post("/api/portfolio/upload", headers=h,
                             files=[("files", ("invoice_case_study.md", MD, "text/markdown")),
                                    ("files", ("virus.exe", b"MZ" * 40, "application/octet-stream"))])
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["added"] == 1 and body["chunks_embedded"] == 1 and body["incremental"] is True
            assert body["user_items"] == 1 and body["seeded_items"] == 16
            assert len(body["rejected"]) == 1 and "virus.exe" in body["rejected"][0]

            # the same file again adds nothing and embeds nothing
            again = (await c.post("/api/portfolio/upload", headers=h,
                                  files=[("files", ("invoice_case_study.md", MD, "text/markdown"))])).json()
            assert again["added"] == 0 and again["duplicates"] == 1 and again["chunks_embedded"] == 0

            mine = (await c.get("/api/portfolio", headers=h)).json()
            assert [i["title"] for i in mine["uploaded"]] == ["Invoice OCR pipeline"]
            assert (await c.get("/api/portfolio", headers=other)).json()["uploaded"] == []

            # this user's agents search the seeded portfolio plus the upload; other users do not see it
            from apps.api.runner import graph_config
            ctx = app.state.ctx
            users = {u: (await c.get("/api/auth/me", headers=hh)).json()["id"] for u, hh in (("a", h), ("b", other))}
            mine_cfg = graph_config(ctx, users["a"], "ai_ml", "t1", None)["configurable"]["retriever"]
            other_cfg = graph_config(ctx, users["b"], "ai_ml", "t2", None)["configurable"]["retriever"]
            assert any(x["source"] == "user_upload" for x in mine_cfg.search("OCR pipeline for invoices", k=3))
            assert all(x["source"] != "user_upload" for x in other_cfg.search("OCR pipeline for invoices", k=5))

            # unauthenticated and bad requests
            assert (await c.post("/api/portfolio/upload",
                                 files=[("files", ("a.md", MD))])).status_code in (401, 403)
            assert (await c.post("/api/portfolio/upload", headers=h)).status_code == 422
    finally:
        await cm.__aexit__(None, None, None)


async def test_github_import_uses_the_mcp_loader_and_needs_configuration(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    from rag.ingest import github_mcp
    set_env(monkeypatch, tmp_path)
    monkeypatch.setenv("USER_PORTFOLIO_DIR", str(tmp_path / "uploads"))
    retr_mod._user_corpora.clear()
    retr_mod._user_retrievers.clear()
    app, cm = await boot()
    try:
        async with client(app) as c:
            h = await make_user(app, "gh1@example.com")
            # not configured: a clear 503, nothing fetched
            monkeypatch.delenv("GITHUB_TOKEN", raising=False)
            r = await c.post("/api/portfolio/github", json={"repo": "octo/demo"}, headers=h)
            assert r.status_code == 503

            async def fake_fetch(repo, path=None, client=None):
                github_mcp.parse_request(repo, path)
                return "demo-README.md", MD.decode()
            monkeypatch.setattr(github_mcp, "fetch_file", fake_fetch)
            ok = await c.post("/api/portfolio/github", json={"repo": "octo/demo"}, headers=h)
            assert ok.status_code == 200, ok.text
            assert ok.json()["added"] == 1 and ok.json()["chunks_embedded"] == 1
            item = (await c.get("/api/portfolio", headers=h)).json()["uploaded"][0]
            assert item["type"] == "readme" and item["source"] == "github_mcp"
            # bad input is a 422 and unauthenticated is refused
            assert (await c.post("/api/portfolio/github", json={"repo": "not a repo"}, headers=h)).status_code == 422
            assert (await c.post("/api/portfolio/github", json={"repo": "octo/demo"})).status_code in (401, 403)
    finally:
        await cm.__aexit__(None, None, None)
