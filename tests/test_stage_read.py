"""What the home reads of an entry's Log for a stage record (design §4.9c act 2, TD-2051)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import board, ledgerboard
from sessionorc.models import Pending, ProgressEntry, Session
from shiftlead.stage_acts import Holder
from shiftlead.stage_read import (
    EntryAnswer,
    EntryForge,
    EntryLedger,
    answer_on,
    forge_on,
    holder_on,
    ledger_on,
    renumbered_on,
)

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


def led(tid: str, *fields: str) -> str:
    return "\n".join(
        [f"## {tid}: An entry", "", "**Priority:** Low", "**Status:** Open", *fields, "", "**Why:** It.", ""]
    )


def test_an_open_entry_that_is_no_design():
    assert ledger_on("TD-7", led("TD-7", "**Kind:** build"), "") == EntryLedger("open")


def test_an_archived_entry_reads_archived_by_its_number():
    assert ledger_on("TD-7", led("TD-8"), led("TD-007")) == EntryLedger("archived")


def test_an_entry_in_neither_has_no_reading():
    assert ledger_on("TD-7", led("TD-8"), None) is None


def test_a_design_counts_its_open_parts_and_knows_it_had_parts():
    text = led("TD-7", "**Kind:** design-first") + led("TD-8", "**Part of:** TD-007") + led("TD-9", "**Part of:** TD-7")
    assert ledger_on("TD-7", text, led("TD-5", "**Part of:** TD-7")) == EntryLedger("open", True, 2, True)


def test_a_design_whose_parts_are_all_archived_had_parts():
    text = led("TD-7", "**Kind:** design-first")
    assert ledger_on("TD-7", text, led("TD-5", "**Part of:** TD-7 the first")) == EntryLedger("open", True, 0, True)


def test_a_design_with_no_parts_had_none():
    text = led("TD-7", "**Kind:** design-first") + led("TD-8", "**Part of:** TD-70")
    assert ledger_on("TD-7", text, led("TD-5")) == EntryLedger("open", True, 0, False)


def git(root, *args: str) -> str:
    who = ("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false")
    return subprocess.run(["git", "-C", str(root), *who, *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "docs/ledger/archive").mkdir(parents=True)
    (tmp_path / "docs/ledger/TD-7.md").write_text(
        led("TD-7", "**Kind:** build") + "A body long enough to be alike.\n" * 9
    )
    (tmp_path / "docs/ledger/TD-8.md").write_text("## TD-8: Another\n\n**Status:** Open\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "first")
    return tmp_path


def test_a_renumbered_entry_names_its_new_id(repo):
    git(repo, "mv", "docs/ledger/TD-7.md", "docs/ledger/TD-12.md")
    git(repo, "commit", "-qm", "renumber")
    assert renumbered_on(repo, "main", "docs/ledger", "TD-7") == "TD-12"


def test_a_file_deleted_outright_was_not_renumbered(repo):
    git(repo, "rm", "-q", "docs/ledger/TD-7.md")
    git(repo, "commit", "-qm", "gone")
    assert renumbered_on(repo, "main", "docs/ledger", "TD-7") is None


def test_a_move_into_the_archive_is_no_renumbering(repo):
    git(repo, "mv", "docs/ledger/TD-7.md", "docs/ledger/archive/TD-7.md")
    git(repo, "commit", "-qm", "archive")
    assert renumbered_on(repo, "main", "docs/ledger", "TD-7") is None


def test_an_entry_never_removed_was_not_renumbered(repo):
    assert renumbered_on(repo, "main", "docs/ledger", "TD-7") is None


def test_a_ref_git_cannot_read_is_no_reading(repo):
    assert renumbered_on(repo, "no-such-ref", "docs/ledger", "TD-7") is None


# -- the forge ----------------------------------------------------------------------------------------------------


def pr_row(number: int, state: str = "open", head: str = "abc", title: str = "work") -> dict:
    return {"number": number, "state": state, "head": head, "title": title}


def test_an_open_pull_request_carries_its_head():
    assert forge_on("TD-7", 4, [pr_row(4)]) == EntryForge("open", "abc")


@pytest.mark.parametrize("state", ["merged", "closed"])
def test_a_finished_pull_request_has_no_head_to_carry(state):
    assert forge_on("TD-7", 4, [pr_row(4, state)]) == EntryForge(state, None)


def test_an_open_row_with_no_head_reads_as_none():
    assert forge_on("TD-7", 4, [pr_row(4, head="")]) == EntryForge("open", None)


@pytest.mark.parametrize("rows", [[], [pr_row(5)], [pr_row(4, "unknown")]])
def test_a_pull_request_not_read_is_no_reading_rather_than_gone(rows):
    assert forge_on("TD-7", 4, rows) is None


def test_a_record_with_no_pull_request_is_a_reading():
    assert forge_on("TD-7", None, [pr_row(5)]) == EntryForge()


def test_the_homes_open_archive_pull_request_is_seen():
    row = pr_row(9, title=board.archive_subject("TD-7"))
    assert forge_on("TD-7", None, [row]).archive_open
    assert forge_on("TD-7", 4, [pr_row(4, "merged"), row]) == EntryForge("merged", None, True)


@pytest.mark.parametrize(
    "row",
    [pr_row(9, "merged", title=board.archive_subject("TD-7")), pr_row(9, title=board.archive_subject("TD-70"))],
)
def test_a_finished_or_another_entrys_archive_pull_request_is_not_this_ones(row):
    assert not forge_on("TD-7", None, [row]).archive_open
