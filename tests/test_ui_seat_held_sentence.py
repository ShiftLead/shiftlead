"""TD-1574 slice 5, design §4.10 *When it is read* (the held seat row) and §6 rule 3 *A stopped team's seats are held*
(TD-1564): the seat card's own composer sentence — `cards.view` redraws a seat on call from `mail.read_when(None, …,
seat=True)` — passes the view's `stop_held`, display only, with the team's wound-down reading."""

from __future__ import annotations

from shiftlead.ui.cards import view

SEATS = {"ao-g-tl": "on a question"}


def _seat(**kw):
    base = {"id": "ao-g-tl", "name": "tl", "kind": "interactive", "adapter": "shell", "dir": "/tmp/x",
            "state": "closed", "team": "g", "unattended": True, "supervised": True,
            "seat": {"trigger": "asks"}}  # fmt: skip
    return {**base, **kw}


def _member(**kw):
    base = {"id": "ao-g-w", "name": "w", "kind": "interactive", "adapter": "shell", "dir": "/tmp/x",
            "state": "closed", "team": "g", "unattended": True, "supervised": True}  # fmt: skip
    return {**base, **kw}


def test_a_held_seat_card_reads_the_held_row_stopped_by_you():
    s = _seat(stop_held={"at": "2026-11-11T06:00:00Z", "by": "person", "team": "g"})
    rw = view(s, [_member()], seats=SEATS)["read_when"]
    for k in ("ask", "note"):
        assert rw[k].startswith(
            "waits in the seat's mailbox: its team g is stopped (by you), and the seat is filled at its next Start"
            " — Start the team to have it read"
        ), rw[k]
    assert "default bound" in rw["ask"] and "default bound" not in rw["note"]


def test_an_until_hold_reads_at_its_stop_time():
    s = _seat(stop_held={"at": "2026-11-11T06:00:00Z", "by": "until", "team": "g"})
    assert "is stopped (at its stop time)" in view(s, [_member()], seats=SEATS)["read_when"]["ask"]


def test_a_wound_down_team_reads_wound_down():
    s = _seat(stop_held={"at": "2026-11-11T06:00:00Z", "by": "person", "team": "g"})
    done = _member(out_of_work={"at": "2026-11-11T05:50:00Z", "why": "nothing left"})
    assert "its team g is wound down (by you)" in view(s, [done], seats=SEATS)["read_when"]["ask"]
    # another team's out-of-work member is not this team's reading
    other = _member(id="ao-h-w", team="h", out_of_work={"at": "2026-11-11T05:50:00Z", "why": "x"})
    assert "its team g is stopped (by you)" in view(s, [_member(), other], seats=SEATS)["read_when"]["ask"]


def test_a_seat_with_no_stop_held_keeps_the_on_call_row():
    rw = view(_seat(), [_member()], seats=SEATS)["read_when"]
    assert rw["ask"].startswith("fills this seat"), rw["ask"]
    assert "Start" not in rw["ask"]


def test_a_persons_own_record_and_the_other_seats_leave_the_wound_down_reading_alone():
    s = _seat(stop_held={"at": "2026-11-11T06:00:00Z", "by": "person", "team": "g"})
    done = _member(out_of_work={"at": "2026-11-11T05:50:00Z", "why": "nothing left"})
    own = _member(id="ao-g-me", name="me", unattended=False)  # a person's own session never declares
    fc = _seat(id="ao-g-fc", name="fc")  # another seat of the team: a seat never declares either
    assert "its team g is wound down (by you)" in view(s, [done, own, fc], seats=SEATS)["read_when"]["ask"]


def test_a_mark_naming_no_team_keeps_the_on_call_row():
    s = _seat(team=None, stop_held={"at": "2026-11-11T06:00:00Z", "by": "person"})
    assert view(s, [_member()], seats=SEATS)["read_when"]["ask"].startswith("fills this seat")
