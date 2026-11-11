"""TD-1574 slice 4, design §4.9b *Why it did not answer* and §6 rule 3 *A stopped team's seats are held* (TD-1564):
a question taken up from a held seat reads `held` — after `suspended`, before the ceilings — with the words *<seat>
waits for its team's Start: <team> was stopped (by you | at its stop time)*; and a Start keeps the mail of a held
seat the person killed (`exited`), as it keeps a closed one's."""

from __future__ import annotations

from datetime import UTC, datetime

from sessionorc import unanswered
from sessionorc.models import Session
from shiftlead import teamrun

Q = "2026-11-05T10:00:00Z"
AT = "2026-11-05T12:00:00Z"
HELD = {"at": "2026-11-05T09:30:00Z", "by": "person", "team": "ao-grind"}


def _rec(**kw) -> Session:
    r = Session(id="ao-x-tl", name="tl", kind="interactive", adapter="claude-code", dir="/tmp/x", profile="max")
    r.created, r.team, r.state = "2026-11-05T09:00:00Z", "ao-grind", "closed"
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _read(r: Session, **kw) -> dict:
    return unanswered.read(r, "ao-x-tl", question_at=Q, at=AT, **kw)


def _words(stamp: dict) -> str:
    return unanswered.words(stamp, now=datetime(2026, 11, 5, 12, tzinfo=UTC))


def test_a_held_seat_reads_held_with_its_team_and_who_stopped_it():
    got = _read(_rec(seat={"trigger": "asks"}, stop_held=HELD))
    assert got == {
        "by": "ao-x-tl", "at": AT, "name": "tl", "seat": True,
        "state": "held", "since": HELD["at"], "team": "ao-grind", "stopped_by": "person",
    }  # fmt: skip
    assert _words(got) == "tl waits for its team's Start: ao-grind was stopped (by you)."
    clock = _read(_rec(seat={"trigger": "asks"}, stop_held={**HELD, "by": "until"}))
    assert _words(clock) == "tl waits for its team's Start: ao-grind was stopped (at its stop time)."


def test_held_comes_after_suspended_and_before_the_ceilings_and_the_rest():
    ceiling = {"at": AT, "why": "fill", "held": True}
    got = _read(_rec(seat={"trigger": "asks"}, stop_held=HELD, restart_ceiling=ceiling), over={"resets": AT})
    assert got["state"] == "held" and "held" not in got and "gate" not in got, "the hold before the ceiling and gate"
    sus = _read(_rec(seat={"trigger": "asks"}, stop_held=HELD, suspended={"at": AT}))
    assert sus["state"] == "suspended"
    # a seat never filled since the question would read `not_filled`: held wins
    assert _read(_rec(seat={"trigger": "asks"}, stop_held=HELD))["state"] != "not_filled"
    # a record that is no seat keeps its own reading, whatever mark it carries
    assert _read(_rec(stop_held=HELD))["state"] == "ended"


def test_a_held_stamp_missing_its_fields_reads_the_plain_line():
    assert _words({"by": "ao-x-tl", "name": "tl", "state": "held", "since": AT}) == "tl did not answer."


def _call(rows: list[dict]):
    def call(method: str, **_kw):
        assert method == "list"
        return rows

    return call


def test_a_start_keeps_the_mail_of_a_held_seat_the_person_killed():
    verdicts = {
        "tl": {"verdict": "supersede", "holder": "ao-tl", "holder_state": "exited"},
        "fc": {"verdict": "supersede", "holder": "ao-fc", "holder_state": "exited"},  # a crash: not held
    }
    rows = [{"id": "ao-tl", "stop_held": HELD, "controllers": []}, {"id": "ao-fc", "controllers": []}]
    keeps, notes = teamrun.keep_mail_for(_call(rows), verdicts, None)
    assert keeps == {"tl"} and notes == [], "a person's start keeps it"
    # a session's start keeps it only where it controls the holder, as for a closed one
    keeps, notes = teamrun.keep_mail_for(_call(rows), verdicts, "ao-lead")
    assert keeps == set() and notes and "tl starts with an empty mailbox" in notes[0]
    rows[0]["controllers"] = ["ao-lead"]
    assert teamrun.keep_mail_for(_call(rows), verdicts, "ao-lead") == ({"tl"}, [])


def test_no_exited_holder_asks_no_list_for_a_persons_start():
    def call(method: str, **_kw):
        raise AssertionError("no list read")

    verdicts = {"tl": {"verdict": "supersede", "holder": "ao-tl", "holder_state": "closed"}}
    assert teamrun.keep_mail_for(call, verdicts, None) == ({"tl"}, [])
