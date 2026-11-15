"""Pairwise panel tooling: blinding, the mapping from A/B back to variants, and the statistics."""
import json
import shutil

import evals.runners.pairwise_panel as pp

KEY = {"P01": {"A": pp.BASE, "B": pp.BEST}, "P02": {"A": pp.BEST, "B": pp.BASE}, "P03": {"A": pp.BASE, "B": pp.BEST}}


def test_sign_test_known_values():
    assert pp.sign_test_p(0, 0) == 1.0
    assert abs(pp.sign_test_p(10, 0) - 2 / 1024) < 1e-12
    assert abs(pp.sign_test_p(8, 2) - 0.109375) < 1e-12
    assert pp.sign_test_p(5, 5) == 1.0


def test_choices_map_back_to_variants_through_the_key():
    rows = [{"rater": r, "pair_id": p, "choice": c} for r, p, c in [
        ("ali", "P01", "B"), ("ali", "P02", "A"), ("ali", "P03", "T"),   # ali prefers BEST twice, one tie
        ("sara", "P01", "B"), ("sara", "P02", "B"), ("sara", "P03", "B"),  # sara: BEST, BASE, BEST
    ]]
    out = pp.analyse(rows, KEY, {"P01": pp.BEST, "P02": pp.BEST, "P03": pp.BASE})
    assert out["raters"] == 2 and out["pairs_rated"] == 3
    assert out["votes"] == {pp.BASE: 1, pp.BEST: 4, "tie": 1}
    assert out["pair_majority_wins"] == {pp.BASE: 0, pp.BEST: 2}  # P02 split 1-1 (tie), P03 won by sara's vote
    # raters agree on P01 only (P02 differs, P03 tie vs BEST): 1 of 3
    assert out["rater_pair_agreement"] == round(1 / 3, 3)
    assert out["agreement_with_llm_judge"] == 0.5 and out["pairs_compared_with_judge"] == 2


def test_invalid_rows_are_ignored():
    rows = [{"rater": "x", "pair_id": "P99", "choice": "A"}, {"rater": "x", "pair_id": "P01", "choice": "Z"}]
    assert pp.analyse(rows, KEY)["pairs_rated"] == 0


def test_make_is_blind_deterministic_and_never_leaks_variants(tmp_path, monkeypatch):
    shutil.copy(pp.DATA / "judge_labels.csv", tmp_path / "judge_labels.csv")
    monkeypatch.setattr(pp, "DATA", tmp_path)
    info = pp.make(n_pairs=8, seed=3)
    assert info["pairs"] == 8
    pairs = json.loads((tmp_path / "pairwise_pairs.json").read_text(encoding="utf-8"))
    key = json.loads((tmp_path / "pairwise_key.json").read_text(encoding="utf-8"))
    shown = json.dumps(pairs) + (tmp_path / "pairwise_sheet.html").read_text(encoding="utf-8")
    assert "v0_naive" not in shown and "v3_rerank" not in shown and "[ev:" not in shown
    assert set(key) == {p["pair_id"] for p in pairs}
    assert all({k["A"], k["B"]} == {pp.BASE, pp.BEST} for k in key.values())
    assert len({k["A"] for k in key.values()}) == 2  # the order is mixed, not always the same variant first
    pp.make(n_pairs=8, seed=3)
    again = json.loads((tmp_path / "pairwise_pairs.json").read_text(encoding="utf-8"))
    assert again == pairs
