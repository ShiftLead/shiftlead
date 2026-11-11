"""td-max's seat half, the readings (design §6 rule 3 *An extra seat*, §4.9 *A scaled seat holds its review stage*;
TD-1547 slice 1): rule 3's cause pass never fills an extra seat and the `asks` linger never closes one; a seat's
extras' fills are a `FILL_CEILING` group apart from the seats sharing their controller; and the shape samples a live
extra seat in its seat's review stage, the stage's queue the union of the seat's records' waiting asks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import park_ticks

from sessionorc.agent_common import FILL_CEILING, SEAT_ASK_LINGER
from sessionorc.models import MailEntry, Session

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def _z(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def _seat(agent, name, state="closed", line=None, **kw) -> Session:
    s = Session(id=f"ao-x-{name}", name=name, kind="interactive", adapter="claude-code", dir=f"/w/{name}")
    s.seat, s.supervised, s.unattended, s.state, s.host = {"trigger": "asks"}, True, True, state, agent.host
    s.controllers = ["ao-x-mgr"]
    if line:
        s.scale = {"line": line}
    for k, v in kw.items():
        setattr(s, k, v)
    agent.sessions[s.id] = s
    return s


def _ask(to: Session, n: int = 1, pr: int | None = None, at: datetime = NOW) -> MailEntry:
    e = MailEntry(id=f"m-{to.name}-{n}", from_="ao-x-g1", to=[to.id], at=_z(at), kind="ask", text="read it")
    e.pr = pr
    to.inbox.append(e)
    return e


def _spy(agent, monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fill(s, now, records):
        calls.append(("fill", s.id))

    async def close(sid, **kw):
        calls.append(("close", sid))

    monkeypatch.setattr(agent, "_fill", fill)
    monkeypatch.setattr(agent, "rpc_close", close)
    return calls


async def test_the_cause_pass_never_fills_an_extra_seat_and_fills_the_seat_itself(agent, monkeypatch):
    await park_ticks(agent)
    calls = _spy(agent, monkeypatch)
    own = _seat(agent, "tl")
    extra = _seat(agent, "tl-2", line="tl")
    _ask(own)
    _ask(extra)  # an ask left on a held extra is the mover's (a later slice), never rule 3's cause
    records = list(agent.sessions.values())
    await agent._seat_pass(extra, NOW, records)
    assert extra.seat_due is None and calls == []
    await agent._seat_pass(own, NOW, records)
    assert own.seat_due and own.seat_due["by"] == "asks" and calls == [("fill", own.id)]


async def test_the_asks_linger_never_closes_an_extra_seat(agent, monkeypatch):
    await park_ticks(agent)
    calls = _spy(agent, monkeypatch)
    idle = {"state": "idle", "confidence": "hook", "git": {"dirty": 0, "unpushed": 0}}
    since = _z(NOW - SEAT_ASK_LINGER - timedelta(minutes=5))
    own = _seat(agent, "tl", since=since, **idle)
    extra = _seat(agent, "tl-2", line="tl", since=since, **idle)
    records = list(agent.sessions.values())
    await agent._seat_pass(extra, NOW, records)
    assert calls == []  # past the linger, clean and idle: an extra stays open until a start needs its slot
    await agent._seat_pass(own, NOW, records)
    assert calls == [("close", own.id)]  # the seat's own record lingers and closes as it always has


async def test_a_seats_extras_fills_never_count_toward_its_own_fill_ceiling(agent, monkeypatch):
    await park_ticks(agent)
    replays: list[str] = []

    async def replay(s, *a, **kw):
        replays.append(s.id)

    monkeypatch.setattr(agent, "_replay", replay)
    own = _seat(agent, "tl", seat_due={"at": _z(NOW), "by": "asks"})
    fills = [{"at": _z(NOW - timedelta(minutes=i + 1)), "why": "fill"} for i in range(FILL_CEILING)]
    _seat(agent, "tl-2", line="tl", restarts=fills)  # a full hour of fills, the extras' own group
    await agent._fill(own, NOW, list(agent.sessions.values()))
    assert replays == [own.id] and own.restart_ceiling is None
    # the same fills on a fellow seat under the same controller are the group's, and refuse it
    _seat(agent, "audit", restarts=list(fills))
    replays.clear()
    await agent._fill(own, NOW, list(agent.sessions.values()))
    assert replays == [] and own.restart_ceiling and own.restart_ceiling["why"] == "fill"


async def test_the_shape_samples_a_live_extra_seat_in_its_seats_stage_and_adds_its_queue(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "repo")
    agent._repos[root] = {"name": "repo", "ledger": {"entries": []}}

    def rec(name, role, **kw):
        s = Session(id=f"ao-x-{name}", name=name, kind="interactive", adapter="claude-code", dir=f"/w/{name}")
        s.team, s.role, s.unattended, s.state, s.repo, s.host = "grind", role, True, "idle", root, agent.host
        for k, v in kw.items():
            setattr(s, k, v)
        agent.sessions[s.id] = s
        return s

    mgr = rec("mgr", "manager", seat={}, capabilities=["control"])
    rec("g1", "grinder", lane=["free-pick"], controllers=[mgr.id], review={"reader": "tl", "held": ["**"]})
    tl = rec("tl", "techlead", seat={"trigger": "asks"}, controllers=[mgr.id], state="working")
    extra = rec("tl-2", "techlead", seat={"trigger": "asks"}, controllers=[mgr.id], scale={"line": "tl"})
    held = rec("tl-3", "techlead", seat={"trigger": "asks"}, controllers=[mgr.id], scale={"line": "tl"})
    held.state = "closed"
    _ask(tl, 1, pr=9, at=NOW - timedelta(hours=1))
    _ask(extra, 1, pr=10, at=NOW - timedelta(hours=3))
    _ask(held, 1, pr=11, at=NOW - timedelta(minutes=30))  # left on a held extra: still the seat's queue
    gone = rec("tl-4", "techlead", seat={"trigger": "asks"}, controllers=[mgr.id], scale={"line": "tl"})
    gone.state, gone.superseded_by = "closed", "ao-x-tl-9"
    _ask(gone, 1, pr=12, at=NOW - timedelta(hours=9))  # a superseded record's mail is its successor's
    assert agent._shape_pass(NOW) is True
    day = agent._shape["days"][NOW.astimezone().date().isoformat()]["grind"]
    assert day["records"][extra.id]["minutes"] == {"idle_with_work": 1}  # sampled in the review stage
    assert held.id not in day["records"]  # a held extra, with no pane, is not sampled
    review = day["queues"]["review"]
    assert review["depth_sum"] == 3 and review["past_bound"] == 1  # three records' asks; the extra's 3h one past 2h
    assert review["oldest_max"] == 3 * 3600  # the oldest of the union, the extra's


async def test_an_idle_extra_seat_is_nudged_for_the_asks_waiting_on_it(agent):
    await park_ticks(agent)
    extra = _seat(agent, "tl-2", state="idle", line="tl", confidence="hook")
    assert agent._nudge_line(extra) is None
    _ask(extra)
    assert "1 questions waiting" in (agent._nudge_line(extra) or "")  # no `seat_due`, and still named
