"""What the home reads of an entry's Log for a stage record (design §4.9c act 2, TD-2051)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import ledgerboard
from sessionorc.models import Pending, ProgressEntry, Session
from shiftlead.stage_acts import Holder
from shiftlead.stage_read import EntryAnswer, answer_on, holder_on

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


# -- what became of a record's holder (§4.9c act 4) ------------------------------------------------------------------

NOW = datetime(2026, 11, 23, 18, 0, tzinfo=UTC)


def ago(**delta) -> str:
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def session(*, claimed=timedelta(hours=1), **fields) -> Session:
    base = {"state": "idle", "unattended": True, "created": ago(hours=3), "turn_at": ago(minutes=5)}
    s = Session(id="build-td-7", name="build-td-7", kind="agent", adapter="claude-code", dir="/r", **{**base, **fields})
    if claimed is not None:
        s.progress = [ProgressEntry(ref="TD-7", at=(NOW - claimed).strftime("%Y-%m-%dT%H:%M:%SZ"))]
    return s


def test_a_session_with_no_record_is_lost():
    assert holder_on(None, "TD-7", NOW).lost


def test_a_working_holder_is_neither_lost_nor_silent():
    h = holder_on(session(), "TD-7", NOW)
    assert not h.lost and not h.silent and h.idle_for == timedelta(minutes=5)


def test_an_exited_holder_is_lost():
    assert holder_on(session(state="exited"), "TD-7", NOW).lost


def test_a_claim_past_its_lease_is_lost_and_a_renewed_one_is_not():
    assert holder_on(session(claimed=timedelta(hours=13)), "TD-7", NOW).lost
    s = session(claimed=timedelta(hours=13))
    s.progress.append(ProgressEntry(ref="TD-7", at=ago(hours=1)))
    assert not holder_on(s, "TD-7", NOW).lost


def test_a_claim_released_or_on_another_entry_is_no_lapsed_lease():
    s = session(claimed=None)
    s.progress = [
        ProgressEntry(ref="TD-7", status="done", at=ago(hours=13)),
        ProgressEntry(ref="TD-8", at=ago(hours=13)),
    ]
    assert not holder_on(s, "TD-7", NOW).lease_lapsed


def test_a_derived_claim_has_no_clock():
    s = session(claimed=None)
    s.progress = [ProgressEntry(ref="TD-7", at=ago(hours=13), source="derived")]
    assert not holder_on(s, "TD-7", NOW).lease_lapsed


def test_two_hours_with_no_turn_is_silent():
    assert holder_on(session(turn_at=ago(hours=2)), "TD-7", NOW).silent
    assert not holder_on(session(turn_at=ago(hours=1, minutes=59)), "TD-7", NOW).silent


def test_work_inside_a_long_turn_keeps_a_holder_from_silent():
    assert not holder_on(session(state="working", turn_at=ago(hours=5), work_at=ago(minutes=1)), "TD-7", NOW).silent


@pytest.mark.parametrize(
    "fields",
    [
        {"pending": Pending(kind="permission", text="run it?")},
        {"pending": Pending(kind="question", text="which?")},
        {"tool_open_at": ago(hours=3)},
        {"subagents": 1, "subagent_at": ago(minutes=1)},
    ],
)
def test_a_holder_waiting_on_something_of_its_own_is_never_silent(fields):
    assert not holder_on(session(turn_at=ago(hours=3), **fields), "TD-7", NOW).silent


def test_an_open_ask_keeps_a_holder_from_silent():
    assert not holder_on(session(turn_at=ago(hours=3)), "TD-7", NOW, open_ask=True).silent


def test_a_taken_over_holder_is_never_silent_but_is_lost_once_it_ends():
    assert not holder_on(session(unattended=False, turn_at=ago(hours=3)), "TD-7", NOW).silent
    assert holder_on(session(unattended=False, state="exited"), "TD-7", NOW).lost


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "limited"},
        {"state": "unreachable"},
        {"gated": {"sent_at": "x"}},
        {"stop_held": {"by": "person", "at": "x", "team": "t"}},
        {"wrapup_at": "2026-11-23T17:00:00Z"},
        {"suspended": {"at": "x", "by": "person", "why": "alarm"}},
    ],
)
def test_a_holder_held_by_the_person_or_the_home_is_neither_lost_nor_silent(fields):
    h = holder_on(session(claimed=timedelta(hours=13), turn_at=ago(hours=3), **fields), "TD-7", NOW)
    assert h.held and not h.lost and not h.silent


def test_a_stop_spends_no_offer():
    s = session(state="exited", ended={"how": "kill", "by": "person", "at": ago(minutes=1)})
    h = holder_on(s, "TD-7", NOW)
    assert h.ended_by_stop and not h.lost


def test_a_clock_ahead_of_the_home_reads_as_no_idle_time():
    assert holder_on(session(turn_at=ago(minutes=-5), created=ago(minutes=-5)), "TD-7", NOW).idle_for == timedelta(0)


def test_a_bare_holder_defaults_are_the_dataclass_ones():
    assert holder_on(session(), "TD-7", NOW) == Holder(idle_for=timedelta(minutes=5))


def test_a_tool_open_past_its_ceiling_no_longer_keeps_a_holder_from_silent():
    assert holder_on(session(turn_at=ago(hours=4), tool_open_at=ago(hours=3, minutes=1)), "TD-7", NOW).silent


def test_a_time_with_no_zone_reads_as_utc():
    s = session(claimed=None, turn_at="2026-11-23T17:55:00")
    s.progress = [ProgressEntry(ref="TD-7", at="2026-11-23T17:00:00")]
    h = holder_on(s, "TD-7", NOW)
    assert h.idle_for == timedelta(minutes=5) and not h.lease_lapsed
