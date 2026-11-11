from agent.memory.store import GigBidMemory
from agent.nodes.core import apply_style


def mem():
    return GigBidMemory(persist=False)  # in memory, no file written


DRAFT = ("I am passionate about data work. Your churn model needs Python. "
         "On Churn Study, I used XGBoost and the outcome was: AUC 0.91. [ev:e1]")
EDIT = "Your churn model needs Python. On Churn Study, I used XGBoost and the outcome was: AUC 0.91. [ev:e1]"


def test_one_edit_does_not_promote_two_do():
    m = mem()
    assert m.record_edit("u1", "t1", DRAFT, EDIT) == []
    assert m.style_notes("u1") == []
    promoted = m.record_edit("u1", "t2", DRAFT, EDIT)
    assert "cut-first-sentence" in promoted
    notes = m.style_notes("u1")
    assert any(n["kind"] == "cut_first_sentence" for n in notes)
    assert notes[0]["provenance"]["threads"] == ["t1", "t2"]  # provenance kept


def test_phrase_rule_and_tenant_isolation():
    m = mem()
    d = "I am passionate about this. Needs Python. [ev:e1]"
    e = "I am keen about this. Needs Python. [ev:e1]"
    m.record_edit("u1", "t1", d, e)
    m.record_edit("u1", "t2", d, e)
    assert any(n["text"] == "passionate" for n in m.style_notes("u1"))
    assert m.style_notes("u2") == []


def test_delete_removes_and_needs_fresh_evidence():
    m = mem()
    m.record_edit("u1", "t1", DRAFT, EDIT)
    m.record_edit("u1", "t2", DRAFT, EDIT)
    items = m.list("u1")
    assert items and items[0]["ns"] == "style"
    assert m.delete("u1", items[0]["ns"], items[0]["key"])
    assert m.list("u1") == []
    assert not m.delete("u1", "style", "missing")
    assert not m.delete("u1", "style_stage", "x")  # staging is not user visible memory
    m.record_edit("u1", "t3", DRAFT, EDIT)
    assert m.list("u1") == []  # one new edit alone cannot bring it back


def test_outcome_promoted_only_after_min_outcomes():
    m = mem()
    assert not m.record_outcome("u1", "ml", True, "a")
    assert not m.record_outcome("u1", "ml", False, "b")
    assert m.outcome_notes("u1") == []
    assert m.record_outcome("u1", "ml", True, "c")
    note = m.outcome_notes("u1")[0]
    assert note["n"] == 3 and abs(note["reply_rate"] - 0.667) < 0.01
    assert not m.record_outcome("u1", "ml", True, "c")  # same thread counted once


def test_apply_style_removes_phrase_and_first_sentence():
    notes = [{"kind": "avoid_phrase", "text": "passionate"},
             {"kind": "cut_first_sentence", "text": "x"}]
    out = apply_style("I am passionate about data. Needs Python. Did X. [ev:e1] Price 5.", notes)
    assert "passionate" not in out and out.startswith("Needs Python.")
