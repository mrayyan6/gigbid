"""Incremental re-indexing: adding work embeds only the new chunks and gives the same index as a full rebuild."""
import numpy as np
import pytest

import rag.index.corpus as corpus_mod
import rag.retriever as retr_mod
from rag.index.corpus import Corpus, get_corpus
from rag.ingest.load import load_portfolio
from rag.ingest.user_store import add_files, load_user_items

MD = (b"# Invoice OCR pipeline\nBuilt an OCR and NLP pipeline in Python and FastAPI for a logistics client. "
      b"Cut manual data entry by 70% and reduced errors from 9% to 2%. Deployed with MLOps practices.")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_PORTFOLIO_DIR", str(tmp_path))
    retr_mod._user_corpora.clear()
    retr_mod._user_retrievers.clear()
    return tmp_path


def test_only_new_chunks_are_embedded_and_result_equals_full_rebuild(store, monkeypatch):
    base = get_corpus("ai_ml")
    assert add_files("u1", "ai_ml", [("invoice_ocr_case_study.md", MD)])["added"] == 1
    new_items = load_user_items("u1")

    embedded: list[int] = []
    real = corpus_mod.embed_passages
    monkeypatch.setattr(corpus_mod, "embed_passages", lambda texts: (embedded.append(len(texts)), real(texts))[1])
    inc, n = base.with_items(new_items)
    assert n == 1 and embedded == [1]  # one new chunk embedded, none of the 16 existing ones

    full = Corpus(load_portfolio("ai_ml") + new_items)
    assert inc.chunk_ids == full.chunk_ids
    assert np.allclose(inc.emb, full.emb, atol=1e-5)
    for q in ("OCR pipeline for invoices", "sentiment analysis", "FastAPI MLOps"):
        di, df = inc.dense(q, 5), full.dense(q, 5)
        assert [e for e, _ in di] == [e for e, _ in df]
        assert np.allclose([x for _, x in di], [x for _, x in df], atol=1e-4)
        assert [e for e, _ in inc.lexical(q, 5)] == [e for e, _ in full.lexical(q, 5)]


def test_adding_the_same_work_twice_is_a_noop(store):
    assert add_files("u1", "ai_ml", [("a.md", MD)])["added"] == 1
    again = add_files("u1", "ai_ml", [("a.md", MD)])
    assert again["added"] == 0 and again["duplicates"] == 1
    c1, s1 = retr_mod.user_corpus("ai_ml", "u1")
    assert s1["chunks_embedded"] == 1
    c2, s2 = retr_mod.user_corpus("ai_ml", "u1")
    assert c2 is c1 and s2["chunks_embedded"] == 0


def test_second_upload_embeds_only_the_second_file(store):
    add_files("u1", "ai_ml", [("a.md", MD)])
    retr_mod.user_corpus("ai_ml", "u1")
    other = (b"# Churn model for telecom\nTrained scikit-learn and PyTorch models to predict churn for a telecom client, "
             b"improved retention by 12% with careful model evaluation.")
    add_files("u1", "ai_ml", [("churn_readme.md", other)])
    c, stats = retr_mod.user_corpus("ai_ml", "u1")
    assert stats["new_items"] == 1 and stats["chunks_embedded"] == 1 and stats["user_items"] == 2
    assert len(c.items) == len(get_corpus("ai_ml").items) + 2


def test_uploads_are_private_to_the_user(store):
    add_files("u1", "ai_ml", [("a.md", MD)])
    assert load_user_items("u2") == []
    r1 = retr_mod.get_user_retriever("v2_hybrid", "ai_ml", "u1")
    assert any(h["source"] == "user_upload" for h in r1.search("OCR pipeline for invoices", k=3))
    assert all(h["source"] != "user_upload" for h in get_corpus("ai_ml").items and
               retr_mod.get_retriever("v2_hybrid", "ai_ml").search("OCR pipeline for invoices", k=5))


def test_metadata_and_rejections(store):
    res = add_files("u1", "ai_ml", [("notes.exe", b"x" * 50), ("tiny.md", b"too short"), ("cv.md", MD)])
    assert res["added"] == 1 and len(res["rejected"]) == 2
    item = load_user_items("u1")[0]
    assert item["type"] == "cv" and item["freelancer_id"] == "ai_ml" and item["source"] == "user_upload"
    assert {"FastAPI", "MLOps"} <= set(item["skills"]) and item["client_industry"] == "logistics"
    assert "70%" in item["outcome"] and item["date"]
