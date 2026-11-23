"""What the home reads of an entry's Log for a stage record (design §4.9c act 2, TD-2051)."""

from __future__ import annotations

import pytest

from sessionorc import ledgerboard
from shiftlead.stage_read import EntryAnswer, answer_on

HEAD = "## TD-7: An entry\n\n**Priority:** Low\n**Status:** Open\n"
ASKED = "- 2026-11-20: asked by the stage record: n1\n"
LIFT = '- 2026-11-21: gate lifted: decision (paul) — by paul; answer "Polish it"\n'
OVERRIDE = "- 2026-11-21: gate lifted: decision (paul) — by shiftlead; override: its entry moved to another team\n"


def entry(*log: str, blocked: str = "") -> str:
    gate = f"**Blocked by:** {blocked}\n" if blocked else ""
    return f"{HEAD}{gate}\n**Why:** Because.\n\n**Log:**\n{''.join(log)}"


def test_a_standing_gate_has_no_answer_even_after_an_earlier_lift():
    assert answer_on(entry(ASKED, LIFT, blocked="decision (paul)"), "paul") == EntryAnswer(True, None, None)


def test_an_answer_names_the_question_it_lifted():
    assert answer_on(entry(ASKED, LIFT), "paul") == EntryAnswer(False, "Polish it", "n1")


def test_a_lift_with_no_question_of_the_records_has_no_mark():
    assert answer_on(entry(LIFT), "paul") == EntryAnswer(False, "Polish it", None)


def test_an_override_is_no_answer():
    assert answer_on(entry(ASKED, LIFT, OVERRIDE), "paul") == EntryAnswer(False, None, None)


def test_a_newer_question_leaves_the_earlier_answer_behind():
    newer = "- 2026-11-22: asked by the stage record: n2\n"
    assert answer_on(entry(ASKED, LIFT, newer), "paul") == EntryAnswer(False, None, None)


def test_another_persons_lift_is_not_this_gates():
    other = LIFT.replace("(paul)", "(sam)").replace("by paul", "by sam")
    assert answer_on(entry(ASKED, other), "paul") == EntryAnswer(False, None, None)


def test_a_note_quoting_a_mark_is_no_question():
    quoted = "- 2026-11-22: the Log's line asked by the stage record: n2 was checked\n"
    assert answer_on(entry(ASKED, LIFT, quoted), "paul") == EntryAnswer(False, "Polish it", "n1")


def test_an_entry_with_no_log_has_no_answer():
    assert answer_on(f"{HEAD}\n**Why:** Because.\n", "paul") == EntryAnswer(False, None, None)


@pytest.mark.parametrize("text", ["", "not an entry"])
def test_an_unreadable_entry_is_no_reading_rather_than_no_gate(text):
    with pytest.raises(ledgerboard.Refused):
        answer_on(text, "paul")
