from rag.query import decompose
from rag.retriever import VARIANTS, get_retriever
from evals.runners.rag_eval import metrics

JOB = "Admin. We need help. Required: FastAPI, PostgreSQL, Next.js. Deliver a documented, tested solution."


def test_decompose_marker_keeps_dotted_names():
    assert decompose(JOB) == ["Experience with FastAPI", "Experience with PostgreSQL", "Experience with Next.js"]


def test_decompose_short_text_is_one_requirement():
    assert decompose("Experience in FastAPI") == ["Experience in FastAPI"]


def test_decompose_without_marker_splits_plain_text():
    parts = decompose(JOB, use_marker=False)
    assert "FastAPI" in parts and "Next.js" in parts


def test_metrics_perfect_and_empty():
    m = metrics(["a", "b"], {"a", "b"})
    assert m["recall@5"] == 1.0 and m["mrr"] == 1.0 and abs(m["ndcg@10"] - 1.0) < 1e-9
    assert metrics(["x"], {"a"})["recall@5"] == 0.0


def test_search_interface_and_filters():
    for v in ("v0b_tfidf", "v0_naive", "v2_hybrid", "v1_decompose_hybrid"):
        r = get_retriever(v, "ai_ml")
        hits = r.search("hands-on PyTorch model training", k=3)
        assert 1 <= len(hits) <= 3 and "evidence_id" in hits[0] and "score" in hits[0]
        typ = hits[0]["type"]
        assert all(h["type"] == typ for h in r.search("PyTorch", k=5, filters={"type": typ}))
    assert set(VARIANTS) >= {"v0_naive", "v2_hybrid", "v1_decompose_hybrid", "v3_rerank", "v8_corrective"}
