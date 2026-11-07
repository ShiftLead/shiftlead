"""A question already waiting on a seat that turns unable is moved by the tick (design §4.9b *A seat that cannot
answer is routed around*, *A question already waiting*; TD-1443, built by TD-1480): a general question goes to its
team's able techlead, else to the person, and a reader's `ask` to the person; the original closes on every copy as
`rerouted`, its copy landing on the same thread carrying `routed`. A `steer` is left to lapse. Where a count would
refuse the landing it stays, saying *waits on <name>: …*, and moves once it can. A late reply on the rerouted
original closes nothing, and `--thread` follows the move."""

from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc.client import AgentError, LocalClient
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


def _limited(agent, sid: str) -> None:
    rec = agent.sessions[sid]
    rec.state, rec.limited_reset = "limited", None  # its reset unknown: past the wait


def _copies(agent, mid: str):
    return [e for r in agent.sessions.values() for e in r.holds(mid)] + [e for e in agent.person_inbox if e.id == mid]


async def _move(agent) -> None:
    await agent._reroute_waiting(datetime.now(UTC))


async def test_an_ask_waiting_on_a_seat_that_turns_limited_moves_to_the_techlead_on_its_thread(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="which test covers this?", kind="ask", about="TD-9")
        first = got["entry"]
        assert first["to"] == [rv]
        _limited(agent, rv)
        await _move(agent)
        olds = _copies(agent, first["id"])
        assert olds and all(e.closed_reason == "rerouted" and not e.open for e in olds), "closed on every copy"
        moved = [e for e in agent.sessions[tl].inbox if e.root == first["root"] and e.id != first["id"]]
        assert len(moved) == 1
        m = moved[0]
        assert m.open and m.from_ == w and m.text == first["text"] and m.about == "TD-9"
        assert m.routed["seat"] == rv and m.routed["why"] == "limited" and m.bound == first["bound"]
        assert any(e.id == m.id for e in agent.sessions[w].outbox), "the sender's Sent card holds the copy"
        await _move(agent)
        assert len([e for e in agent.sessions[tl].inbox if e.root == first["root"]]) == 1, "moved once"
        async with LocalClient(caller=rv) as r:  # the seat's late reply closes nothing
            await r.call("msg", text="test_x", kind="reply", reply_to=first["id"])
        assert next(e for e in agent.sessions[tl].inbox if e.id == m.id).open


async def test_a_steer_waiting_on_an_unable_seat_is_left_to_lapse(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="dropping it", kind="steer", default="drop it")
        _limited(agent, rv)
        await _move(agent)
        assert all(e.open and e.closed_reason is None for e in _copies(agent, got["entry"]["id"]))
        assert not agent.sessions[tl].inbox


async def test_an_ask_to_a_limited_techlead_goes_to_the_person_unbounded_and_waits_behind_an_open_one(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            asked = await c.call("msg", to=tl, text="may I drop it?", kind="ask", about="TD-9", answers=["yes", "no"])
            mine = await c.call("msg", to=PERSON, text="may I drop it?", kind="ask", about="TD-9")
        _limited(agent, tl)
        await _move(agent)
        held = _copies(agent, asked["entry"]["id"])
        assert all(e.open for e in held), "One open copy refuses the landing: it stays"
        assert all(e.waits and e.waits.startswith("waits on the person: you have ") for e in held)
        await person.call("msg", text="yes", kind="reply", reply_to=mine["entry"]["id"])
        await _move(agent)
        assert all(e.closed_reason == "rerouted" and e.waits is None for e in _copies(agent, asked["entry"]["id"]))
        m = next(e for e in agent.person_inbox if e.root == asked["entry"]["root"] and e.id != asked["entry"]["id"])
        assert m.bound is None and m.answers == ["yes", "no"] and m.routed["seat"] == tl
        assert m.subject, "mail the person reads carries a subject"


async def test_a_waits_line_clears_when_the_seat_is_able_again(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            asked = await c.call("msg", to=tl, text="q?", kind="ask", about="TD-9")
            await c.call("msg", to=PERSON, text="q?", kind="ask", about="TD-9")
        _limited(agent, tl)
        await _move(agent)
        assert all(e.waits for e in _copies(agent, asked["entry"]["id"]))
        agent.sessions[tl].state = "idle"
        await _move(agent)
        assert all(e.open and e.waits is None for e in _copies(agent, asked["entry"]["id"]))


async def test_a_readers_ask_moves_to_the_person_with_no_bound_and_no_answers(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="#12: the fix", kind="ask", pr=12, answers=["pass", "findings"])
        assert got["entry"]["to"] == [rv] and got["entry"]["bound"]
        rec = agent.sessions[rv]
        rec.state, rec.stalled_ticks = "stalled?", 2
        await _move(agent)
        m = next(e for e in agent.person_inbox if e.root == got["entry"]["root"])
        assert m.pr == 12 and m.bound is None and m.answers == [] and m.routed["why"] == "stalled?"
        assert not agent.sessions[tl].inbox, "a reader's ask is never re-seated"


async def test_thread_follows_the_move_and_is_refused_once_the_person_holds_it(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            to_rv = await c.call("msg", to=rv, text="first?", kind="ask", about="TD-1")
            to_tl = await c.call("msg", to=tl, text="second?", kind="ask", about="TD-2")
            _limited(agent, rv)
            await _move(agent)  # rv's goes to tl; tl's stays with tl
            moved = next(e for e in agent.sessions[tl].inbox if e.root == to_rv["entry"]["root"] and e.routed)
            up = await c.call("msg", to=PERSON, text="tl has not answered", kind="ask", thread=to_rv["entry"]["id"])
            assert up["entry"]["root"] == to_rv["entry"]["root"]
            assert next(e for e in agent.sessions[tl].inbox if e.id == moved.id).closed_reason == "asked_person"
            _limited(agent, tl)
            await _move(agent)  # tl's own question goes to the person
            with pytest.raises(AgentError, match="the person holds it"):
                await c.call("msg", to=PERSON, text="again", kind="ask", thread=to_tl["entry"]["id"])


async def test_a_readers_rerouted_ask_leaves_the_pr_asked_while_its_copy_is_out(agent, tmp_path):
    """§4.9b: the PR reads as asked while the ask is out — `pr_reads` reads a rerouted reader's ask through its
    moved copy, so `ao pr held` never tells the author to ask the unable reader again."""
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, rv, w = await _team(agent, tmp_path, person)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="#12: the fix", kind="ask", pr=12)
            rec = agent.sessions[rv]
            rec.state, rec.stalled_ticks = "stalled?", 2
            await _move(agent)
            reads = (await c.call("pr_reads", id=w, pr=12))["asks"]
        assert [(r["id"], r["to"], r["open"]) for r in reads] == [(got["entry"]["id"], [rv], True)]
        m = next(e for e in agent.person_inbox if e.root == got["entry"]["root"])
        await person.call("msg", text="read it: fine", kind="reply", reply_to=m.id)
        async with LocalClient(caller=w) as c:
            reads = (await c.call("pr_reads", id=w, pr=12))["asks"]
        assert len(reads) == 1 and reads[0]["open"] is False and reads[0]["replied_at"]
