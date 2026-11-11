"""Stuck work, open asks (design §6 rule 13 *Stuck work*, TD-1470, built by TD-1496 slice 1): an open `ask` to a
session that no addressee has been able to act on for longer than `STUCK_ASK_AFTER` is kept on `host.json` as
`stuck`, its reason the first actor's and its clock the newest moment anything moved; it drops the tick an
actor acts. A steer, an ask to the person and one a seat passed up are never read; a person's own session is
passed over."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import mail, models, stuck
from sessionorc.client import LocalClient
from sessionorc.store import HostStore

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
WAIT = mail.STUCK_ASK_AFTER


def _z(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def rec(n: str = "tl", state: str = "idle", **kw) -> models.Session:
    s = models.Session(id=f"ao-{n}", name=n, kind="claude", adapter="claude-code", dir="/w", state=state)
    s.supervised, s.unattended, s.team = True, True, "beta"
    s.since = _z(NOW - timedelta(hours=3))
    s.created = _z(NOW - timedelta(hours=5))
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def ask(mid: str = "m-1", to: tuple[str, ...] = ("ao-tl",), kind: str = "ask", **kw) -> models.MailEntry:
    e = models.MailEntry(id=mid, from_="ao-w", to=list(to), at=_z(NOW - timedelta(hours=2)), kind=kind, text="q")
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def judge(r, stamp, *, unfillable=None, open_at=None, clock=None):
    return stuck.judge(
        r,
        r.id if r is not None else "ao-gone",
        stamp,
        unfillable=unfillable or {},
        open_at=open_at or NOW - timedelta(hours=2),
        idle_clock=clock,
        now=NOW,
    )


@pytest.mark.unit
def test_open_asks_reads_asks_to_sessions_once_and_never_a_steer_a_person_ask_or_a_passed_up_one():
    a, b = rec("a"), rec("b")
    both = ask("m-both", to=("ao-a", "ao-b"))
    a.inbox = [both, ask("m-steer", kind="steer"), ask("m-person", to=(models.PERSON,)), ask("m-up", passed_up="T")]
    b.inbox = [both, ask("m-closed", closed_reason="replied")]
    assert [e.id for e in stuck.open_asks({"ao-a": a, "ao-b": b})] == ["m-both"]


@pytest.mark.unit
def test_a_working_actor_acts_and_an_idle_one_with_a_live_shell_acts():
    assert judge(rec(state="working"), {"state": "working"}).acting
    shell = rec(shells=[{"id": "b1", "since": _z(NOW - timedelta(minutes=5))}])
    assert judge(shell, {"state": "idle"}).acting, "a live background shell is working on its own (§4.2)"


@pytest.mark.unit
def test_an_idle_actor_is_clocked_from_its_read_and_reads_its_own_idle_start():
    r = rec()
    read = NOW - timedelta(minutes=90)
    a = judge(r, {"state": "idle"}, clock=read)
    assert not a.acting and a.since == read
    assert a.reason == {"state": "idle", "since": r.since}, "the words name its own idle start"
    ended = rec(shells_at=_z(NOW - timedelta(minutes=1)))
    assert judge(ended, {"state": "idle"}, clock=read).since == NOW - timedelta(minutes=1), "a shell's grace"


@pytest.mark.unit
def test_a_stall_needs_two_ticks_and_is_clocked_from_when_nothing_new_began():
    assert judge(rec(state="stalled?", stalled_ticks=1), {"state": "working"}).acting
    began = NOW - timedelta(minutes=20)
    a = judge(rec(state="stalled?", stalled_ticks=2, work_at=_z(began), screen_at=_z(began)), {"state": "working"})
    assert not a.acting and a.reason == {"state": "stalled", "since": _z(began)} and a.since == began


@pytest.mark.unit
def test_a_fillable_ended_seat_acts_and_an_unfillable_one_reads_its_word():
    seat = rec(state="exited", seat={"trigger": "asks"})
    assert judge(seat, {"state": "ended"}).acting, "rule 3 fills it for the question"
    a = judge(seat, {"state": "ended"}, unfillable={"ao-tl": "restart ceiling"})
    assert not a.acting and a.reason == {"state": "unfillable", "why": "restart ceiling"}
    held = rec(state="exited", seat={"trigger": "asks"}, stop_held={"at": "T", "team": "beta"})
    assert not judge(held, {"state": "held"}).acting


@pytest.mark.unit
def test_a_reason_is_the_stamp_and_every_figure_is_floored_at_the_open_time():
    r = rec(state="limited", since=_z(NOW - timedelta(hours=9)))
    a = judge(r, {"state": "limited", "by": "ao-tl"})
    assert a.reason["state"] == "limited" and a.since == NOW - timedelta(hours=2)
    gone = judge(None, {"state": "gone", "by": "ao-gone"})
    assert gone.reason["state"] == "gone" and gone.since == NOW - timedelta(hours=2)


@pytest.mark.unit
def test_reading_is_stuck_past_the_wait_with_the_first_actor_and_never_for_the_persons_own_alone():
    lim = judge(rec("a", state="limited"), {"state": "limited"})
    gone = judge(None, {"state": "gone"})
    got = stuck.reading([lim, gone], NOW, WAIT)
    assert got["reason"]["state"] == "limited" and got["actor"]["id"] == "ao-a" and got["actor"]["more"] == 1
    assert got["since"] == _z(NOW - timedelta(hours=2))
    assert stuck.reading([lim], NOW - timedelta(minutes=61), WAIT) is None, "not yet past the wait"
    own = rec("me", team=None, unattended=False, supervised=False, by_person=True)
    assert stuck.reading([judge(own, {"state": "idle"})], NOW, WAIT) is None, "the person is already there"
    got = stuck.reading([judge(own, {"state": "idle"}), lim], NOW, WAIT)
    assert got["actor"]["id"] == "ao-a" and got["actor"]["more"] == 0, "a person's own session is passed over"
    assert stuck.reading([lim, judge(rec("w", state="working"), {"state": "working"})], NOW, WAIT) is None


@pytest.mark.unit
def test_a_fresh_fills_copy_is_clocked_from_its_created_and_an_unread_copy_from_since():
    fill = rec(created=_z(NOW - timedelta(minutes=10)))
    fill.inbox = [ask(read_at=_z(NOW - timedelta(hours=2)))]
    assert stuck.ask_idle_clock(fill, "m-1") == NOW - timedelta(minutes=10)
    unread = rec()
    unread.inbox = [ask()]
    assert stuck.ask_idle_clock(unread, "m-1") == NOW - timedelta(hours=3)


@pytest.mark.unit
def test_host_store_drops_a_malformed_stuck_or_stuck_open_entry(tmp_path):
    store = HostStore(tmp_path / "host.json")
    good = {"since": "2026-11-11T10:00:00Z", "reason": {"state": "limited"}, "actor": {"id": "ao-a"}}
    store.save(
        {
            "teams": {},
            "stuck": {"ask:m-1": good, "ask:m-2": {"since": 3}, "pr:9": good, "board:k": good},
            "stuck_open": {
                "board:k": {"at": "2026-11-11T10:00:00Z", "repo": "shiftlead", "holder": True},
                "board:j": {"at": "nope", "repo": "shiftlead"},
                "board:h": {"at": "2026-11-11T10:00:00Z", "repo": "shiftlead", "asked": "yes"},
            },
        }
    )
    got = store.load()
    assert list(got["stuck"]) == ["ask:m-1"], "a board entry carries its repo; no key but ask: and board:"
    assert list(got["stuck_open"]) == ["board:k"]


async def _seat_and_worker(person, tmp_path):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        kw.setdefault("unattended", True)
        got = await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw)
        return got["id"]

    return await mk("rv", team="beta", seat={"trigger": "asks"}), await mk("w", team="beta")


@pytest.mark.integration
async def test_the_pass_keeps_a_stuck_ask_and_drops_it_the_tick_its_seat_acts(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        rv, w = await _seat_and_worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="which test covers this?", kind="ask", about="TD-9")
        mid = got["entry"]["id"]
        seat = agent.sessions[rv]
        seat.state, seat.limited_reset = "limited", None
        later = datetime.now(UTC) + WAIT + timedelta(minutes=1)
        await agent._stuck_pass(datetime.now(UTC))
        assert "stuck" not in agent._host_rec, "not past the wait"
        await agent._stuck_pass(later)
        row = agent._host_rec["stuck"][f"ask:{mid}"]
        assert row["reason"]["state"] == "limited" and row["actor"]["id"] == rv and row["actor"]["more"] == 0
        assert HostStore(agent.host_store.path).load()["stuck"][f"ask:{mid}"]["since"] == row["since"], "on disk"
        assert (await agent.rpc_host())["stuck"][f"ask:{mid}"]["reason"]["state"] == "limited", "served"
        seat.state = "working"
        await agent._stuck_pass(later)
        assert "stuck" not in agent._host_rec, "dropped the tick an actor acts"


@pytest.mark.integration
async def test_the_pass_reads_no_steer_and_keeps_a_board_entry_as_stored(agent, tmp_path):
    await park_ticks(agent)
    board = {"since": "2026-11-11T10:00:00Z", "reason": {"state": "no_lane"}, "repo": "shiftlead"}
    agent._host_rec["stuck"] = {"board:abc": board}
    async with LocalClient() as person:
        rv, w = await _seat_and_worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            await c.call("msg", to=rv, text="dropping it", kind="steer", default="drop it")
        agent.sessions[rv].state = "limited"
        await agent._stuck_pass(datetime.now(UTC) + timedelta(hours=3))
        assert agent._host_rec["stuck"] == {"board:abc": board}
