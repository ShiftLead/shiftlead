"""TD-1575, design §4.5a (TD-1564): a held seat says so — the card's **held** line on a seat whose view carries
`stop_held`, the team card's **work waiting** note and the **Inbox row: team start** each counting the questions
`work_waiting.seats_held` names, a held-only row (no lane ids) drawing Start and Snooze ▾ alone, under *Later* or
*Needs you* by the mark's `seats_held_by`; the mark's `held` (rule 8's start bound) draws as before."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shiftlead.ui import app as uiapp
from shiftlead.ui.app import inbox_sections
from shiftlead.ui.cards import stop_held_line, view
from shiftlead.ui.inbox import work_note, work_rows

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
AT = "2026-11-11T11:00:00+00:00"
STOP = "2026-11-11T10:00:00+00:00"
SEATS = {"ao-g-fc": "on a question"}
FC = {"id": "ao-g-fc", "name": "fact-check-ao-1", "team": "g"}


def _seat(**kw):
    base = {"id": "ao-g-fc", "name": "fact-check-ao-1", "kind": "interactive", "adapter": "shell", "dir": "/tmp/x",
            "state": "closed", "team": "g", "unattended": True, "supervised": True, "pane": False, "tail": [],
            "since": "2026-11-11T10:00:00Z", "created": "2026-11-11T09:00:00Z", "confidence": "tick",
            "seat": {"trigger": "asks"}}  # fmt: skip
    return {**base, **kw}


def _member(**kw):
    base = {"id": "ao-g-w", "name": "w", "kind": "interactive", "adapter": "shell", "dir": "/tmp/x",
            "state": "closed", "team": "g", "unattended": True, "supervised": True}  # fmt: skip
    return {**base, **kw}


def _held(by="person"):
    return {"at": "2026-11-11T10:00:00Z", "by": by, "team": "g"}


# ── the seat's card ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_held_line_counts_the_questions_and_says_who_stopped_it():
    assert stop_held_line(_seat(stop_held=_held(), asks_waiting=2), [_member()]) == (
        "held: team stopped (by you) — 2 questions wait for Start"
    )
    assert stop_held_line(_seat(stop_held=_held("until"), asks_waiting=1), [_member()]) == (
        "held: team stopped (at its stop time) — 1 question waits for Start"
    )
    assert stop_held_line(_seat(stop_held=_held(), asks_waiting=0), [_member()]) == (
        "held: team stopped — waits for Start"
    )
    assert stop_held_line(_seat(asks_waiting=3), [_member()]) == "", "no `stop_held`, no line"


def test_the_held_line_reads_wound_down_for_a_wound_down_team():
    done = _member(out_of_work={"at": "2026-11-11T09:50:00Z", "why": "nothing left"})
    assert stop_held_line(_seat(stop_held=_held(), asks_waiting=2), [done]) == (
        "held: team wound down (by you) — 2 questions wait for Start"
    )
    assert stop_held_line(_seat(stop_held=_held()), [done]) == "held: team wound down — waits for Start"


def test_both_cards_draw_the_held_line_and_none_without_the_mark(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    card = uiapp.templates.get_template("card.html")
    line = "held: team stopped (by you) — 2 questions wait for Start"
    v = view(_seat(stop_held=_held(), asks_waiting=2), [_member()], seats=SEATS)
    assert v["stop_held_line"] == line
    html = card.render(s=v)
    drawn = html[html.index('class="meta routed stop-held"') :]
    drawn = drawn[: drawn.index("</div>")]
    assert line in drawn and "<button" not in drawn and "<a " not in drawn
    assert line in card.render(s={**v, "compact": True}), "the compact card draws it too"
    plain = view(_seat(asks_waiting=2), [_member()], seats=SEATS)
    assert plain["stop_held_line"] == "" and "stop-held" not in card.render(s=plain)


# ── the team card's note ────────────────────────────────────────────────────────────────────────────────────


def test_the_team_note_adds_a_clause_per_held_seat_and_a_held_only_mark_draws_it_alone():
    both = {"at": AT, "members": {"w": ["TD-1"]}, "seats_held": {"ao-g-fc": 2}, "seats_held_by": "person"}
    note = work_note(both, NOW, records=[FC])
    assert note["n"] == 1 and [s["words"] for s in note["seats"]] == ["2 questions wait on fact-check-ao-1"]
    alone = work_note({"at": AT, "members": {}, "seats_held": {"ao-g-fc": 1}}, NOW, records=[FC])
    assert alone["n"] == 0 and [s["words"] for s in alone["seats"]] == ["1 question waits on fact-check-ao-1"]
    # a seat id the page's records do not hold draws as its id
    (gone,) = work_note({"members": {}, "seats_held": {"ao-g-gone": 3}}, NOW)["seats"]
    assert gone["words"] == "3 questions wait on ao-g-gone"
    # the start bound `held` is no held seat: the note is as it was
    plain = work_note({"at": AT, "members": {"w": ["TD-1"]}, "held": {"why": "day", "count": 3}}, NOW)
    assert plain["n"] == 1 and plain["seats"] == []
    assert work_note({"members": {}, "held": {"why": "until"}}, NOW) is None


def test_the_team_header_draws_the_held_clauses():
    from shiftlead.ui.app import team_groups

    rec = {"id": "w", "name": "w", "team": "t", "state": "closed", "state_class": "closed", "state_label": "closed",
           "scraped": False, "rank": 5, "controllers": [], "capabilities": []}  # fmt: skip
    (g,) = team_groups([rec])
    render = uiapp.templates.get_template("group_head.html").render
    seats = [{"id": "ao-g-fc", "name": "fact-check-ao-1", "n": 2, "words": "2 questions wait on fact-check-ao-1"}]
    head = render(g={**g, "live": False, "wound_down": True, "work_note": {"at": AT, "age": "5m", "n": 0,
                                                                        "title": "", "seats": seats}})  # fmt: skip
    assert "· 2 questions wait on fact-check-ao-1" in head and "entries waiting" not in head
    head = render(g={**g, "live": False, "wound_down": True, "work_note": {"at": AT, "age": "5m", "n": 2,
                                                                        "title": "", "seats": seats}})  # fmt: skip
    assert "2 entries waiting since" in head and "· 2 questions wait on fact-check-ao-1" in head


def test_team_groups_lets_a_held_only_mark_through_and_names_the_seat():
    from shiftlead.ui.repo import team_groups

    rec = {"id": "ao-g-w", "name": "w", "team": "g", "state": "closed", "state_class": "closed",
           "state_label": "closed", "scraped": False, "rank": 5, "controllers": [], "capabilities": []}  # fmt: skip
    seat = {**rec, "id": "ao-g-fc", "name": "fact-check-ao-1", "seat": {"trigger": "asks"}}
    work = {"g": {"at": AT, "members": {}, "seats_held": {"ao-g-fc": 2}, "seats_held_by": "person"}}
    (g,) = team_groups([rec, seat], work=work)
    assert g["work_note"] and [s["words"] for s in g["work_note"]["seats"]] == ["2 questions wait on fact-check-ao-1"]


# ── the team-start row ──────────────────────────────────────────────────────────────────────────────────────


def test_a_row_with_entries_adds_the_held_clause_and_keeps_its_section_and_dismiss():
    m = {"at": AT, "repo": "/r/shiftlead", "members": {"w": ["TD-1"]}, "stopped": {"by": "person", "at": STOP},
         "seats_held": {"ao-g-fc": 2}, "seats_held_by": "person"}  # fmt: skip
    (r,) = work_rows({"g": m}, {}, NOW, records=[FC], on_work=lambda t: "ask")
    assert r["text"] == "g · stopped by you · its lanes gained 1 entry: TD-1 · 2 questions wait on fact-check-ao-1"
    assert not r["held_only"] and r["later"] is True
    html = uiapp.templates.get_template("inbox_rows.html").render(rows=[r], section="later")
    assert "TD-1</a> · 2 questions wait on fact-check-ao-1" in html
    assert 'data-act="clear_work"' in html and 'data-act="work_start"' in html


def test_a_wound_down_row_with_entries_stays_under_needs_you_whatever_seats_held_by_says():
    m = {"at": AT, "members": {"w": ["TD-1"]}, "seats_held": {"ao-g-fc": 1}, "seats_held_by": "person"}
    (r,) = work_rows({"g": m}, {"g": STOP}, NOW, records=[FC], on_work=lambda t: "ask")
    assert not r["later"]
    assert inbox_sections([], states=[r])["count"] == 1


def test_a_held_only_mark_draws_its_own_row_start_and_snooze_alone():
    for by, later in (("person", True), ("until", False)):
        m = {"at": AT, "members": {}, "stopped": {"by": by, "at": STOP}, "seats_held": {"ao-g-fc": 2},
             "seats_held_by": by}  # fmt: skip
        (r,) = work_rows({"g": m}, {}, NOW, records=[FC], on_work=lambda t: "ask")
        said = "stopped by you" if by == "person" else "stopped at its stop time"
        assert r["text"] == f"g · {said} · 2 questions wait on fact-check-ao-1", by
        assert r["held_only"] and r["later"] is later and r["n"] == 0 and r["held"] == ""
        s = inbox_sections([], states=[r])
        assert (len(s["later"]), s["count"]) == ((1, 0) if later else (0, 1)), by
        html = uiapp.templates.get_template("inbox_rows.html").render(rows=[r], section="later" if later else "needs")
        assert 'data-act="work_start"' in html and "Snooze ▾" in html and 'data-act="clear_work"' not in html
        assert "· 2 questions wait on fact-check-ao-1</div>" in html


def test_a_held_only_row_without_a_stop_stamp_reads_wound_down_and_under_start_says_questions_start_nothing():
    m = {"at": AT, "members": {}, "seats_held": {"ao-g-fc": 1}, "seats_held_by": "until"}
    (r,) = work_rows({"g": m}, {"g": STOP}, NOW, records=[FC], on_work=lambda t: "start")
    assert r["text"] == (
        "g · wound down · 1 question waits on fact-check-ao-1 · not started: questions alone start no team"
    )
    assert r["held"] == "questions alone start no team"


def test_the_start_bound_held_draws_as_before_and_a_mark_of_nothing_draws_no_row():
    m = {"at": AT, "members": {"w": ["TD-1"]}, "held": {"why": "day", "count": 3}}
    (r,) = work_rows({"g": m}, {"g": STOP}, NOW, on_work=lambda t: "start")
    assert r["seats_held"] == [] and not r["held_only"] and r["held"] == "started 3 times today and found no work"
    assert work_rows({"g": {"members": {}, "seats_held": {}}}, {}, NOW) == []
    assert work_rows({"g": {"members": {}, "seats_held": {"ao-g-fc": 0}}}, {}, NOW) == []
