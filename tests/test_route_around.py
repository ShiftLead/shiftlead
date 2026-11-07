"""A seat that cannot answer is routed around at the send (design §4.9b *A seat that cannot answer is routed
around*, TD-1443, built by TD-1473 slice 2): a new `ask` naming one `asks` seat that `seat_able` reads unable
goes to its team's able techlead seat, else to the person, carrying `routed`; a reader's `ask` (carrying `pr`)
goes to the person, with no suggested answers, and owes no outcome."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc.client import LocalClient
from sessionorc.models import PERSON

pytestmark = pytest.mark.integration


async def _team(agent, tmp_path, person):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        kw.setdefault("unattended", True)
        return (await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))[
            "id"
        ]

    tl = await mk("tl", team="beta", seat={"trigger": "asks", "tags": True})
    rv = await mk("rv", team="beta", seat={"trigger": "asks"})
    w = await mk("w", team="beta")
    return tl, rv, w


def _limited(agent, sid: str, reset: datetime | None = None) -> None:
    rec = agent.sessions[sid]
    rec.state = "limited"
    rec.limited_reset = reset.isoformat().replace("+00:00", "Z") if reset else None


def _in_person(agent, mid: str):
    return next((e for e in agent.person_inbox if e.id == mid), None)


async def test_a_general_ask_to_an_unable_review_seat_goes_to_the_techlead_carrying_routed(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        _limited(agent, rv)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="which test covers this?", kind="ask")
        assert got["entry"]["to"] == [tl]
        assert got["routed"]["seat"] == rv and got["routed"]["name"] == "rv" and got["routed"]["why"] == "limited"
        held = next(e for e in agent.sessions[tl].inbox if e.id == got["entry"]["id"])
        assert held.routed == got["routed"] and held.bound, "a seat's own bound where it lands on a seat"


async def test_a_general_ask_to_an_unable_techlead_goes_to_the_person_with_its_answers_and_no_bound(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        _limited(agent, tl)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=tl, text="may I drop it?", kind="ask", answers=["yes", "no"])
        assert got["entry"]["to"] == [PERSON], "never to another asks seat"
        e = _in_person(agent, got["entry"]["id"])
        assert e is not None and e.routed["seat"] == tl and e.bound is None and e.answers == ["yes", "no"]


async def test_a_seat_limited_with_a_near_reset_still_takes_it_and_a_passed_reset_is_routed(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        _limited(agent, tl, now + timedelta(minutes=10))
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=tl, text="first?", kind="ask")
            assert got["entry"]["to"] == [tl] and "routed" not in got
            agent.sessions[tl].inbox[-1].closed_reason = "expired"  # frees the sender's one open question
            _limited(agent, tl, now - timedelta(minutes=1))
            got = await c.call("msg", to=tl, text="second?", kind="ask")
        assert got["entry"]["to"] == [PERSON] and got["routed"]["why"].startswith("limited, resets ")


async def test_a_readers_ask_to_a_stalled_reader_goes_to_the_person_with_no_answers_and_owes_nothing(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        rec = agent.sessions[rv]
        rec.state, rec.stalled_ticks = "stalled?", 2
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="#12: the fix", kind="ask", pr=12, answers=["pass", "findings"])
        assert got["entry"]["to"] == [PERSON], "a reader's ask is never re-seated"
        e = _in_person(agent, got["entry"]["id"])
        assert e.routed["why"] == "stalled?" and e.pr == 12 and e.answers == []
        await person.call("msg", text="read it: pass", kind="reply", reply_to=e.id)
        e = _in_person(agent, got["entry"]["id"])
        assert e.closed_reason == "replied" and not e.owes, "the person's reply is the PR's read"


async def test_one_stalled_tick_or_an_able_seat_moves_nothing_and_a_reply_is_never_routed(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        rec = agent.sessions[tl]
        rec.state, rec.stalled_ticks = "stalled?", 1
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=tl, text="q?", kind="ask")
        assert got["entry"]["to"] == [tl] and "routed" not in got
        _limited(agent, tl)
        async with LocalClient(caller=tl) as t:  # the seat's own reply goes to its asker as ever
            back = await t.call("msg", text="yes", kind="reply", reply_to=got["entry"]["id"])
        assert back["entry"]["to"] == [w] and "routed" not in back


async def test_the_techleads_own_ask_to_an_unable_review_seat_goes_to_the_person_never_back_to_it(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        _limited(agent, rv)
        async with LocalClient(caller=tl) as c:
            got = await c.call("msg", to=rv, text="did #12 pass?", kind="ask")
        assert got["entry"]["to"] == [PERSON] and got["routed"]["seat"] == rv, "never back to its own sender"
