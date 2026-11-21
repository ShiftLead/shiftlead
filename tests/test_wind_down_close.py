"""Rule 9's wind-down close (design §4.9a *A wind-down closes its members*, §6 rule 9 *A wind-down's close*,
TD-1898): a live member carrying a Wind down's mark is closed by the tick once it settles — nothing sent, or a turn
after the mark then idle `SEND_STALL_SECONDS`, or `WRAPUP_GRACE` past the first tick that read it — whatever
`work.finished` reads; `finished` reads a live marked member *winding down* and passes over an ended one; the
manager's own mark is inert; and a team the person wound down owes the person no note."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import park_ticks

from sessionorc import work
from sessionorc.agent_common import FINISHED_SETTLE, SEND_STALL_SECONDS, WRAPUP_GRACE
from sessionorc.models import SYSTEM, Session, now_iso

CLEAN = {"branch": "w", "dirty": 0, "unpushed": 0}
MANAGER = "ao-t-manager"
START = "2026-09-28T06:00:00Z"


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rec(name: str, **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="idle",
        team="g", unattended=True, supervised=True, git=dict(CLEAN), controllers=[MANAGER], created=START,
        out_of_work=None,
    )  # fmt: skip
    return Session(**{**base, **kw})


def _manager(**kw) -> Session:
    return _rec("manager", capabilities=["control"], controllers=[], **kw)


def _mark(at: datetime, by: str = "person", waits: bool = True) -> dict:
    return {"at": _iso(at), "by": by, "waits": waits}


class _Home:
    """The agent's close and its policy send stood in for: what the tick closed, under which closer, and typed."""

    def __init__(self, agent, monkeypatch, *recs: Session) -> None:
        self.agent, self.closed, self.sent, self.closers = agent, [], [], {}
        for r in recs:
            r.host = agent.host
            agent.sessions[r.id] = r
        monkeypatch.setattr(agent, "rpc_close", self._close)
        monkeypatch.setattr(agent, "_policy_send", self._send)

    async def _close(self, id: str, closer: dict | None = None, reap: bool | str = True) -> dict:
        s = self.agent.sessions[id]
        self.closers[s.name] = closer
        s.set_state("closed", confidence="scraped")
        s.closed_at, s.closed_for = now_iso(), None
        self.closed.append(s.name)
        return {}

    async def _send(self, s: Session, text: str) -> bool:
        self.sent.append((s.name, text))
        return True

    def notes(self) -> list[str]:
        return [e.text for e in self.agent.person_inbox if e.from_ == SYSTEM]


async def test_a_member_marked_with_nothing_sent_is_closed_at_once_whatever_it_declared(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    g1 = _rec("g1", wind_down=_mark(now, waits=False))  # undeclared: rule 9 alone would close nobody
    manager = _manager()
    home = _Home(agent, monkeypatch, g1, manager)
    await agent._finished_pass(now)
    assert home.closed == ["g1"] and home.closers["g1"] == {"by": "tick", "why": "wind_down"}
    assert home.sent == [], "the manager waits the settle, as rule 9 has it"


async def test_a_wrap_up_sent_closes_once_its_turn_ran_and_the_member_sat_idle(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    g1 = _rec("g1", wind_down=_mark(now), turn_at=_iso(now - timedelta(minutes=1)))
    home = _Home(agent, monkeypatch, g1, _manager())
    await agent._finished_pass(now + timedelta(seconds=30))
    assert home.closed == [], "no turn since the wrap-up's yet"
    g1.set_state("working", confidence="hook")
    await agent._finished_pass(now + timedelta(seconds=40))
    g1.set_state("idle", confidence="hook")
    g1.turn_at = _iso(now + timedelta(seconds=50))
    at = now + timedelta(seconds=60)
    await agent._finished_pass(at)
    assert home.closed == [], "the idle window starts at the first tick that reads it idle after the turn"
    await agent._finished_pass(at + timedelta(seconds=SEND_STALL_SECONDS - 1))
    assert home.closed == []
    await agent._finished_pass(at + timedelta(seconds=SEND_STALL_SECONDS))
    assert home.closed == ["g1"]


async def test_a_wrap_up_whose_turn_never_shows_closes_after_the_grace(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    g1 = _rec("g1", wind_down=_mark(now))
    home = _Home(agent, monkeypatch, g1, _manager())
    await agent._finished_pass(now)
    await agent._finished_pass(now + WRAPUP_GRACE - timedelta(seconds=1))
    assert home.closed == []
    g1.wind_down = _mark(now + timedelta(minutes=5))  # a person's later send moved it: the grace starts again
    await agent._finished_pass(now + WRAPUP_GRACE)
    assert home.closed == []
    await agent._finished_pass(now + 2 * WRAPUP_GRACE)
    assert home.closed == ["g1"]


async def test_one_at_work_or_with_work_left_stays_open_and_is_tried_again(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    busy = _rec("g1", wind_down=_mark(now, waits=False), state="working")
    dirty = _rec("g2", wind_down=_mark(now, waits=False), git={"branch": "w", "dirty": 1, "unpushed": 0})
    sub = _rec("g3", wind_down=_mark(now, waits=False), subagents=1, subagent_at=_iso(now))
    home = _Home(agent, monkeypatch, busy, dirty, sub, _manager())
    await agent._finished_pass(now)
    assert home.closed == [] and dirty.state == "idle"
    dirty.git = dict(CLEAN)
    await agent._finished_pass(now + timedelta(seconds=10))
    assert home.closed == ["g2"], "pushed, it is closed on a later tick; never killed"


async def test_the_managers_own_mark_is_inert(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    manager = _manager(wind_down=_mark(now, waits=False))
    g1 = _rec("g1", out_of_work={"at": _iso(now), "why": "nothing"})
    home = _Home(agent, monkeypatch, g1, manager)
    await agent._finished_pass(now)
    assert home.closed == [], "the manager is never this close's, and an unmarked member is rule 9's"
    views = [agent._finished_view(r, now) for r in (g1, manager)]
    assert work.finished(views)["why"] == [], "and the manager's mark keeps no reading off"


def test_finished_reads_a_live_marked_member_winding_down_and_passes_over_an_ended_one():
    mark = {"at": START, "by": "person", "waits": True}
    manager = _manager()
    live = _rec("g1", wind_down=mark, out_of_work={"at": START, "why": "x"})
    gone = _rec("g2", wind_down=mark, state="closed")  # undeclared, and closed by the tick: passed over
    reading = work.finished([manager, live, gone])
    assert reading["why"] == ["g1 winding down"]
    live.set_state("closed", confidence="scraped")
    assert work.finished([manager, live, gone])["why"] == []


async def test_a_team_the_person_wound_down_owes_the_person_no_note(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    g1 = _rec("g1", wind_down=_mark(now, waits=False))
    manager = _manager()
    home = _Home(agent, monkeypatch, g1, manager)
    await agent._finished_pass(now)
    assert home.closed == ["g1"]
    await agent._finished_pass(now + FINISHED_SETTLE)
    assert [n for n, _ in home.sent] == ["manager"]
    manager.finished_sent_at = _iso(now + FINISHED_SETTLE)
    await agent._finished_pass(now + FINISHED_SETTLE + WRAPUP_GRACE)
    assert home.closed == ["g1", "manager"]
    assert home.notes() == [], "the person ended it, and the page said so"


async def test_a_marked_member_takes_no_wind_down_back_and_nothing_is_owed(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    g1 = _rec("g1", wind_down=_mark(now), git={"branch": "w", "dirty": 1, "unpushed": 0})
    manager = _manager(finished_sent_at=_iso(now))
    home = _Home(agent, monkeypatch, g1, manager)
    await agent._finished_pass(now + timedelta(seconds=1))
    assert manager.finished_sent_at, "a marked member, undeclared, is the wind-down close's, never rule 9's take-back"
    assert home.closed == []

    manager.set_state("closed", confidence="scraped")
    agent._finished_owed["g"] = now
    await agent._finished_pass(now + timedelta(seconds=2))
    assert "g" not in agent._finished_owed, "a Wind down's team owes no note by the reading"


async def test_only_this_runs_marks_hold_the_note_back(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    old = _rec(
        "g0", wind_down=_mark(now - timedelta(hours=2)), state="closed", closed_at=_iso(now - timedelta(hours=1))
    )
    home = _Home(agent, monkeypatch, old, _manager())
    top = {"id": agent._address(agent.sessions[MANAGER])}
    assert agent._run_marks("g", [old], top) == [old], "with no start written, every mark counts"
    agent._host_rec.setdefault("teams", {})["g"] = {"started_at": _iso(now - timedelta(minutes=30))}
    assert agent._run_marks("g", [old], top) == [], "an earlier run's mark"
    old.closed_at = _iso(now - timedelta(minutes=30))
    assert agent._run_marks("g", [old], top) == [old], "ended at the start counts"
    old.closed_at = "garbled"
    assert agent._run_marks("g", [old], top) == [old], "an end that does not parse is none"
    assert home.closed == []


async def test_a_sessions_wind_down_still_tells_the_person(agent, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    g1 = _rec("g1", wind_down=_mark(now, by=MANAGER, waits=False))
    manager = _manager()
    home = _Home(agent, monkeypatch, g1, manager)
    await agent._finished_pass(now)
    await agent._finished_pass(now + FINISHED_SETTLE)
    manager.finished_sent_at = _iso(now + FINISHED_SETTLE)
    await agent._finished_pass(now + FINISHED_SETTLE + WRAPUP_GRACE)
    assert home.closed == ["g1", "manager"] and len(home.notes()) == 1, "only the person's press holds it back"
