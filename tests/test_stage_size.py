"""A team's numbers and the room they leave (design §4.9d *Sessions at once*, TD-2065)."""

from __future__ import annotations

from types import SimpleNamespace

from shiftlead import stage_size
from shiftlead.stage_size import Limits, Room


def test_a_stage_with_no_number_runs_one_and_a_team_with_no_most_has_no_limit():
    got = stage_size.limits({"at_once": {"build": 3, "review": "two", "check": -1, "flag": True}})
    assert got == Limits({"build": 3}, None)
    assert stage_size.limits(None) == Limits({}, None)
    assert stage_size.limits({"at_once": [1], "most": "5"}) == Limits({}, None)
    assert stage_size.limits({"most": 4}).most == 4


def test_a_stage_fits_below_its_number_and_the_team_below_its_limit():
    room = Room(Limits({"build": 2}, None))
    assert room.stage_fits("build") and room.stage_fits("review") and not room.stage_fits(None)
    room.take_stage("build")
    room.take_stage("review")
    assert room.stage_fits("build") and not room.stage_fits("review")
    room.take_stage("build")
    assert not room.stage_fits("build") and room.audit_fits()
    capped = Room(Limits({"build": 5}, 2), audits=1)
    assert capped.stage_fits("build") and capped.audit_fits()
    capped.take_stage("build")
    assert not capped.stage_fits("build") and not capped.audit_fits() and capped.total() == 2


def test_the_room_counts_the_teams_held_open_records_and_its_audits_with_a_holder():
    records = {
        "TD-1": {"team": "t", "stage": "build", "holder": "s1"},
        "TD-2": {"team": "t", "stage": "build", "holder": None},
        "TD-3": {"team": "t", "stage": "review", "holder": "s3", "closed_at": "2026-11-20"},
        "TD-4": {"team": "u", "stage": "build", "holder": "s4"},
        "TD-5": {"team": "t", "stage": "review", "holder": "s5"},
    }
    runs = {"docs": {"holder": "s6"}, "code": {"holder": None}}

    def audit(team, key):
        if key == "bad":
            raise ValueError("bad json")
        return runs.get(key)

    doc = {"audits": [{"name": "Docs"}, {"name": "Code"}, {"name": "Bad"}, {"name": "Gone"}, "junk"]}
    got = stage_size.room(SimpleNamespace(audit=audit), Limits(), records, "t", doc)
    assert dict(got.held) == {"build": 1, "review": 1} and got.audits == 1 and got.total() == 3
    assert stage_size.room(SimpleNamespace(audit=audit), Limits(), {}, "t", None).total() == 0
