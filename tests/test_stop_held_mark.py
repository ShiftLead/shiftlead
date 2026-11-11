"""TD-1574 slice 3, design §6 rule 8 *A team that stopped* (TD-1564): the questions waiting on a team's held seats
ride its `work_waiting` mark as `seats_held: {<seat>: n}` beside `seats_held_by` and `seats_held_at`, on every
return; with no lane news they make a **held-only** mark, which never starts the team, which Dismiss leaves, and
which goes when the questions close; lane news coming to it is aged from itself; Telegram tells an `until` hold
once on a row of its own, `held:<team>`, and a person's never."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import notify
from sessionorc import settings as settings_mod
from sessionorc.agent_common import WORK_SETTLE
from sessionorc.client import LocalClient
from sessionorc.models import MailEntry, Session

T0 = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _e(id: str) -> dict:
    return {"id": id, "title": id, "priority": "medium", "owner": "grinder", "kind": "build", "pickable": "yes"}


def _rec(name: str, team: str = "g", **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="exited",
        team=team, unattended=True, supervised=True, pane=False, lane=["free-pick"],
    )  # fmt: skip
    return Session(**{**base, **kw})


def _killed(by: str, at: datetime, why: str | None = None) -> dict:
    return {"how": "kill", "at": _iso(at), "by": by, **({"why": why} if why else {})}


def _ask(seat: Session, n: int = 1) -> None:
    for i in range(n):
        mid = f"m-{seat.name}-{len(seat.inbox)}-{i}"
        seat.inbox.append(MailEntry(id=mid, from_="ao-x", to=[seat.id], at=_iso(T0), kind="ask", text="q"))


def _team(agent, tmp_path, by: str = "person", entries: tuple[str, ...] = (), **member) -> tuple[Session, Session]:
    """A stopped team `g`: one member and a techlead seat, both ended by `by` at T0, the seat asked once."""
    repo = str(tmp_path)
    agent._repos[repo] = {"name": "r", "root": repo, "ledger": {"entries": [_e(i) for i in entries]}}
    why = "stop time" if by == "tick" else None
    m = _rec("g1", ended=_killed(by, T0, why), lane_seen={"at": "x", "ids": []}, repo=repo, **member)
    tl = _rec("tl", seat={"trigger": "asks"}, lane=[], ended=_killed(by, T0, why), repo=repo)
    m.host = tl.host = agent.host
    agent.sessions[m.id], agent.sessions[tl.id] = m, tl
    _ask(tl)
    return m, tl


def _mark(agent) -> dict | None:
    return ((agent._host_rec.get("teams") or {}).get("g") or {}).get("work_waiting")


@pytest.mark.parametrize("on_work", ["ask", "start"])
async def test_a_question_on_a_held_seat_makes_a_held_only_mark_that_starts_nothing(
    agent, tmp_path, monkeypatch, on_work
):
    await park_ticks(agent)
    replays: list = []

    async def replay(*a, **k):
        replays.append(a)

    monkeypatch.setattr(agent, "_replay", replay)
    settings_mod.save({"teams": {"g": {"on_work": on_work}}})
    _, tl = _team(agent, tmp_path)
    now = datetime.now(UTC)
    await agent._work_marks(now)
    mark = _mark(agent)
    assert mark["members"] == {} and mark["repo"] == str(tmp_path), "held-only: no lane ids, the seat's repo"
    assert mark["seats_held"] == {"ao-t-tl": 1} and mark["seats_held_by"] == "person"
    assert mark["stopped"]["by"] == "person" and "held" not in mark and "questions" not in mark
    at, since = mark["at"], mark["seats_held_at"]
    assert replays == [], "questions alone start no team"
    # a rising count keeps both instants; the person's own Start is the only press that starts it
    _ask(tl, 2)
    await agent._work_marks(now + timedelta(minutes=1))
    mark = _mark(agent)
    assert mark["seats_held"] == {"ao-t-tl": 3} and (mark["at"], mark["seats_held_at"]) == (at, since)
    async with LocalClient() as person:
        got = await person.call("work_start", team="g")
        assert got["started"] is False and got["ids"] == [], "answered before the stopped mark is refused"
        assert (await person.call("clear_work", team="g"))["cleared"] is False
    assert _mark(agent)["seats_held"] == {"ao-t-tl": 3}, "neither press takes the held part away"
    assert replays == []
    # the questions close: the mark goes with them
    for e in tl.inbox:
        e.closed_by, e.closed_at = "m-r", _iso(T0)
    await agent._work_marks(now + timedelta(minutes=2))
    assert _mark(agent) is None


async def test_under_off_nothing_is_written_and_a_seat_with_nothing_waiting_is_not_keyed(agent, tmp_path):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "off"}}})
    _team(agent, tmp_path)
    await agent._work_marks(datetime.now(UTC))
    assert _mark(agent) is None
    settings_mod.save({"teams": {"g": {"on_work": "ask"}}})
    idle = _rec("fc", seat={"trigger": "asks"}, lane=[], ended=_killed("person", T0), repo=str(tmp_path))
    idle.host = agent.host
    agent.sessions[idle.id] = idle
    await agent._work_marks(datetime.now(UTC))
    assert _mark(agent)["seats_held"] == {"ao-t-tl": 1}, "the fact-check seat has nothing waiting"


async def test_a_crash_holds_nothing_so_no_held_part(agent, tmp_path):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "ask"}}})
    m, tl = _team(agent, tmp_path)
    for r in (m, tl):
        r.ended = {"how": "pane", "at": _iso(T0), "code": 1}
    await agent._work_marks(datetime.now(UTC))
    assert _mark(agent) is None


async def test_lane_news_carries_the_held_part_and_news_after_dismiss_is_aged_from_itself(agent, tmp_path):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "ask"}}})
    _team(agent, tmp_path, entries=("TD-001",))
    now = datetime.now(UTC)
    await agent._work_marks(now)
    held_only = _mark(agent)
    assert held_only["members"] == {}, "the news is still settling: the held part alone"
    held_only["at"] = OLD = "2026-01-01T00:00:00Z"
    await agent._work_marks(now + WORK_SETTLE)
    mark = _mark(agent)
    assert mark["members"] == {"g1": ["TD-001"]} and mark["seats_held"] == {"ao-t-tl": 1}
    assert mark["seats_held_at"] == held_only["seats_held_at"]
    assert mark["at"] != OLD, "news coming to a held-only mark takes its own instant"
    # Dismiss clears the entries and leaves the held part, `stopped` with it
    async with LocalClient() as person:
        got = await person.call("clear_work", team="g")
    assert got["cleared"] is True and got["ids"] == ["TD-001"]
    left = _mark(agent)
    assert left["members"] == {} and left["seats_held"] == {"ao-t-tl": 1} and left["stopped"]["by"] == "person"
    assert left["seats_held_at"] == held_only["seats_held_at"], "kept through Dismiss"
    left["at"] = OLD
    # a later entry is news again, aged from the tick that read it, never the held part's instant
    agent._repos[str(tmp_path)]["ledger"]["entries"].append(_e("TD-002"))
    later = now + 2 * WORK_SETTLE
    await agent._work_marks(later)
    await agent._work_marks(later + WORK_SETTLE)
    mark = _mark(agent)
    assert mark["members"] == {"g1": ["TD-002"]} and mark["at"] != OLD


async def test_a_wound_down_teams_held_only_mark_carries_no_stopped(agent, tmp_path):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "start"}}})
    out = {"at": _iso(T0 - timedelta(minutes=5)), "why": "nothing pickable"}
    _team(agent, tmp_path, out_of_work=out)
    await agent._work_marks(datetime.now(UTC))
    mark = _mark(agent)
    assert mark["seats_held_by"] == "person" and "stopped" not in mark and mark["members"] == {}
    async with LocalClient() as person:
        assert (await person.call("work_start", team="g"))["started"] is False
    assert _mark(agent)["seats_held"] == {"ao-t-tl": 1}


async def test_telegram_tells_an_until_hold_on_its_own_row_and_a_persons_never(agent, tmp_path):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "start"}}})
    _, tl = _team(agent, tmp_path, by="tick", entries=("TD-001",))
    fc = _rec("fc", seat={"trigger": "asks"}, lane=[], ended=_killed("tick", T0, "stop time"), repo=str(tmp_path))
    fc.host = agent.host
    agent.sessions[fc.id] = fc
    _ask(fc)
    now = datetime.now(UTC)
    await agent._work_marks(now)
    await agent._work_marks(now + WORK_SETTLE)
    mark = _mark(agent)
    assert mark["seats_held_by"] == "until" and mark["members"] == {"g1": ["TD-001"]}
    rows = agent._notify_rows()
    row = rows["held:g"]
    assert row.line == "shiftlead · g · stopped at its stop time · 2 questions wait on fc and tl"
    assert (row.began, row.link, row.snooze) == (mark["seats_held_at"], "work:g", "work:g|work")
    assert "work:g" in rows, "the lanes keep their own row"
    # a person's stop: never told
    for r in agent.sessions.values():
        r.ended = _killed("person", T0)
    await agent._work_marks(now + 2 * WORK_SETTLE)
    assert _mark(agent)["seats_held_by"] == "person"
    assert "held:g" not in agent._notify_rows()


def test_the_held_line_counts_one_question_in_the_singular():
    assert notify.held_line("g", 1, ["tl"]) == "shiftlead · g · stopped at its stop time · 1 question waits on tl"
