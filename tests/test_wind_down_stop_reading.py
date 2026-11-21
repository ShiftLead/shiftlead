"""A Wind down's stop reading and the member-wise reading (design §4.9a *A wind-down closes its members*, *What it
leaves*, §6 rule 8, TD-1898 Fix items 4 and 5): the tick's close of a marked member, a rule 9 close and a record's
close of itself read `person` where the mark or the wrap-up is the person's; a manager by its `wound_down_by`; an
exit naming nobody by the person's mark where a later send cleared `wrapup_at`; and `finished_alone` replays nobody
while the team is being ended, nor any record a Wind down closed or marked."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sessionorc import work
from sessionorc.models import Session
from shiftlead import ending

T0 = datetime(2026, 11, 21, 6, 0, tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _rec(name: str, **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="closed",
        team="g", unattended=True, supervised=True, pane=False, lane=["free-pick"],
    )  # fmt: skip
    return Session(**{**base, **kw})


def _closer(by: str, why: str | None, at: datetime = T0, **kw) -> dict:
    return {"by": by, "why": why, "at": _iso(at), **kw}


def _mark(by: str, at: datetime = T0 - timedelta(minutes=10)) -> dict:
    return {"at": _iso(at), "by": by, "waits": False}


OUT = {"at": _iso(T0 - timedelta(hours=1)), "why": "nothing pickable"}


def test_a_marked_members_wind_down_close_reads_the_presser():
    person = _rec("g1", closer=_closer("tick", "wind_down"), wind_down=_mark("person"))
    assert work._how_stopped(person) == "person"
    session = _rec("g1", closer=_closer("tick", "wind_down"), wind_down=_mark("ao-t-m"))
    assert work._how_stopped(session) is None
    # a person's later send leaves the mark's `by` the person's, though the press was a session's
    pushed = _rec("g1", closer=_closer("tick", "wind_down"), wind_down=_mark("person"), wrapup_by=None)
    assert work._how_stopped(pushed) == "person"


def test_a_tick_close_for_another_cause_is_not_read_as_the_persons():
    for why in ("brief", "seat", "cache"):
        r = _rec("g1", closer=_closer("tick", why), wind_down=_mark("person"), wrapup_by="person")
        assert work._how_stopped(r) is None, why


def test_a_managers_rule_9_close_reads_its_wound_down_by_or_its_wrap_up():
    assert work._how_stopped(_rec("m", closer=_closer("tick", "finished", wound_down_by="person"))) == "person"
    assert work._how_stopped(_rec("m", closer=_closer("tick", "finished", wound_down_by="ao-t-x"))) is None
    assert work._how_stopped(_rec("m", closer=_closer("tick", "finished"))) is None
    # an unmarked manager the person sent a Wrap up, closed by rule 9's ordinary conclusion
    assert work._how_stopped(_rec("m", closer=_closer("tick", "finished"), wrapup_by="person")) == "person"


def test_a_manager_that_closed_itself_after_the_line_reads_its_closed_for():
    found = _rec(
        "m", closer=_closer("ao-t-m", None), closed_for={"why": "finished", "wound_down_by": "person", "closed_at": "x"}
    )
    assert work._how_stopped(found) == "person"
    plain = _rec("m", closer=_closer("ao-t-m", None), closed_for={"why": "finished", "closed_at": "x"})
    assert work._how_stopped(plain) is None
    # a manager that closes itself after the person's wrap-up
    assert work._how_stopped(_rec("m", closer=_closer("ao-t-m", None), wrapup_by="person")) == "person"
    # a restarted manager (no `wrapup_by`) that closes itself before the line: `other`
    assert work._how_stopped(_rec("m", closer=_closer("ao-t-m", None))) is None


def test_an_exit_naming_nobody_after_the_persons_mark_reads_person():
    ended = {"how": "tool", "at": _iso(T0)}
    r = _rec("g1", state="exited", ended=ended, wind_down=_mark("person"))
    assert work._how_stopped(r) == "person"
    # the stop time's wrap-up before the person's mark: the person's; after it: the stop time's
    early = _iso(T0 - timedelta(minutes=20))
    late = _iso(T0 - timedelta(minutes=5))
    assert (
        work._how_stopped(_rec("g1", state="exited", ended=ended, wind_down=_mark("person"), wrapup_sent_at=early))
        == "person"
    )
    assert (
        work._how_stopped(_rec("g1", state="exited", ended=ended, wind_down=_mark("person"), wrapup_sent_at=late))
        == "until"
    )
    # a session's mark is no person's word
    assert work._how_stopped(_rec("g1", state="exited", ended=ended, wind_down=_mark("ao-t-m"))) is None


def test_ao_grinds_case_reads_person_and_a_sessions_press_other():
    members = [
        _rec(
            n,
            closer=_closer("tick", "wind_down", T0 + timedelta(seconds=i)),
            wind_down=_mark("person"),
            out_of_work=OUT,
        )
        for i, n in enumerate(("g1", "g2"))
    ]
    undeclared = _rec("g3", closer=_closer("tick", "wind_down", T0), wind_down=_mark("person"))
    manager = _rec("m", closer=_closer("ao-t-m", None, T0 - timedelta(hours=2)))
    assert work.stopped_by([manager, *members, undeclared])["by"] == "person"
    by_session = [
        _rec(n, closer=_closer("tick", "wind_down", T0), wind_down=_mark("ao-t-m"), out_of_work=OUT)
        for n in ("g1", "g2")
    ]
    assert work.stopped_by(by_session)["by"] == "other"


def test_exit_words_read_a_wind_downs_mark_as_after_wrap_up():
    ended = {"how": "tool", "at": _iso(T0)}
    view = {"id": "ao-t-g1", "state": "exited", "ended": ended, "wind_down": _mark("person")}
    assert ending.exit_words(view).endswith("· after wrap-up")
    after = {**view, "wind_down": _mark("person", T0 + timedelta(minutes=1))}
    assert not ending.exit_words(after).endswith("· after wrap-up")
    assert not ending.exit_words({**view, "wind_down": "junk"}).endswith("· after wrap-up")


def _alone(*extra: Session) -> list[str]:
    seat = _rec("fc", state="idle", seat="fact-check")
    finished = _rec("g1", closer=_closer("tick", "finished"), out_of_work=OUT)
    return [r.name for r in work.finished_alone([seat, finished, *extra])]


def test_finished_alone_passes_over_a_wind_downs_close_and_its_marks():
    assert _alone() == ["g1"]
    assert _alone(_rec("g2", closer=_closer("tick", "wind_down"), out_of_work=OUT, wind_down=_mark("person"))) == ["g1"]
    gone = _rec("g2", state="exited", pane=None, ended={"how": "tool", "at": _iso(T0)}, out_of_work=OUT,
                wind_down=_mark("ao-t-m"))  # fmt: skip
    assert _alone(gone) == ["g1"]
    # a wind_down close with no mark left on the record is still the team's ending
    assert _alone(_rec("g2", closer=_closer("tick", "wind_down"), out_of_work=OUT)) == ["g1"]


def test_finished_alone_returns_none_while_the_crew_winds_down():
    for field in ({"wind_down": _mark("person")}, {"wrapup_at": _iso(T0)}, {"wrapup_sent_at": _iso(T0)}):
        assert _alone(_rec("g2", state="idle", **field)) == [], field
    # once none reads winding, the team runs on as today
    assert _alone(_rec("g2", state="idle")) == ["g1"]
