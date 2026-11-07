"""Routing within a pool comes first (design §4.9b *A seat as an ordered pool*, *Routing within the pool comes
first*; TD-1476, built by TD-1521): a general question to a pool member that cannot answer goes to the first able
member after it in pool order — never an earlier one, never the sender, a member whose counts refuse it passed
over — carrying `routed`, at the send and on the tick's move; only with none able does it take TD-1443's road (the
team's able techlead, else the person). A reader's `ask` never moves within a pool. `--team` reads a pool as one
candidate, its first member, able when any member is."""

from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.client import LocalClient
from sessionorc.models import PERSON

pytestmark = pytest.mark.integration


async def _team(agent, tmp_path, person, members: int = 3):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        kw.setdefault("unattended", True)
        kw.setdefault("supervised", True)
        return (await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))[
            "id"
        ]

    tl = await mk("tl", team="beta", seat={"trigger": "asks", "tags": True})
    pool = []
    for k in range(1, members + 1):
        name = "qa" if k == 1 else f"qa-p{k}"
        pool.append(await mk(name, team="beta", seat={"trigger": "asks", "pool": "qa", "rank": k}))
    w = await mk("w", team="beta")
    return tl, pool, w


def _limited(agent, *sids: str) -> None:
    for sid in sids:
        rec = agent.sessions[sid]
        rec.state, rec.limited_reset = "limited", None  # its reset unknown: past the wait


def _open_on(agent, sid: str, root: str):
    return [e for e in agent.sessions[sid].inbox if e.root == root and e.open]


async def _ask(agent, sender: str, to: str, text: str = "is this figure right?", **kw):
    async with LocalClient(caller=sender) as c:
        return await c.call("msg", to=to, text=text, kind="ask", **kw)


async def test_an_ask_to_an_unable_first_member_goes_to_the_second_carrying_routed(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, m1)
        got = await _ask(agent, w, m1)
        assert got["entry"]["to"] == [m2]
        assert got["routed"]["seat"] == m1 and got["routed"]["name"] == "qa" and got["routed"]["why"] == "limited"
        held = next(e for e in agent.sessions[m2].inbox if e.id == got["entry"]["id"])
        assert held.routed == got["routed"] and held.bound, "a seat's own bound where it lands on a member"


async def test_unable_members_are_passed_in_order_then_the_techlead_then_the_person(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, m1, m2)
        got = await _ask(agent, w, m1, "first?")
        assert got["entry"]["to"] == [m3] and got["routed"]["seat"] == m1
        _limited(agent, m3)
        got = await _ask(agent, w, m1, "second?")
        assert got["entry"]["to"] == [tl], "every member unable: TD-1443's road"
        _limited(agent, tl)
        got = await _ask(agent, w, m1, "third?")
        assert got["entry"]["to"] == [PERSON]


async def test_an_ask_to_an_unable_later_member_never_goes_back_to_an_earlier_one(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, m2)
        got = await _ask(agent, w, m2)
        assert got["entry"]["to"] == [m3], "member 1 is able, and never taken"
        _limited(agent, m3)
        got = await _ask(agent, w, m2, "again?")
        assert got["entry"]["to"] == [tl], "no member after it is able: the techlead, not member 1"


async def test_a_working_member_is_able_and_the_sender_is_skipped(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        agent.sessions[m2].state = "working"
        _limited(agent, m1)
        got = await _ask(agent, w, m1)
        assert got["entry"]["to"] == [m2], "a pool is a fallback, never a share: a working member takes it"
        got = await _ask(agent, m2, m1, "from a member")
        assert got["entry"]["to"] == [m3], "never to its own sender"


async def test_a_member_whose_mailbox_is_full_is_passed_over(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        await person.call("msg", to=m2, text="fyi", kind="note")
        monkeypatch.setattr(mail, "MAILBOX_DEPTH", 1)
        _limited(agent, m1)
        got = await _ask(agent, w, m1)
        assert got["entry"]["to"] == [m3]


async def test_a_readers_ask_to_an_unable_member_goes_to_the_person(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, m1)
        got = await _ask(agent, w, m1, "#12: the fix", pr=12)
        assert got["entry"]["to"] == [PERSON], "a reader's ask never moves within a pool"


async def test_the_team_address_reads_a_pool_as_its_first_member_able_when_any_member_is(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, tl)
        assert (await agent._question_seat(team="beta")).id == m1
        _limited(agent, m1)
        assert (await agent._question_seat(team="beta")).id == m1, "member 2 is able"
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", team="beta", text="which test covers this?")
            assert got["entry"]["to"] == [m2] and got["routed"]["seat"] == m1, "the send moves it within the pool"
            pr = await c.call("msg", team="beta", text="#12: the fix", kind="ask", pr=12)
            assert pr["entry"]["to"] == [PERSON], "a reader's ask resolves to member 1 and never moves within it"
        _limited(agent, m2, m3)
        assert (await agent._question_seat(team="beta")).id == tl, "every member unable: the techlead seat"


async def test_a_pool_whose_first_member_is_sat_out_is_no_candidate(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, tl)
        rec = agent.sessions[m1]
        rec.state, rec.closed_for = "closed", {"why": "sit_out"}
        assert (await agent._question_seat(team="beta")).id == tl, "member 2 is able, but never a candidate alone"


async def test_a_waiting_ask_moves_to_the_next_member_on_the_tick_it_turns_unable(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        first = (await _ask(agent, w, m1))["entry"]
        assert first["to"] == [m1]
        _limited(agent, m1)
        await agent._reroute_waiting(datetime.now(UTC))
        moved = _open_on(agent, m2, first["root"])
        assert len(moved) == 1 and moved[0].routed["seat"] == m1 and moved[0].from_ == w
        assert not _open_on(agent, m1, first["root"]) and not _open_on(agent, tl, first["root"])
        agent.sessions[m1].state = "idle"  # able again: nothing moved comes back
        await agent._reroute_waiting(datetime.now(UTC))
        assert len(_open_on(agent, m2, first["root"])) == 1 and not _open_on(agent, m1, first["root"])


async def test_a_waiting_ask_passes_a_full_member_on_the_tick_and_writes_no_wait(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        first = (await _ask(agent, w, m1))["entry"]
        await person.call("msg", to=m2, text="fyi", kind="note")
        monkeypatch.setattr(mail, "MAILBOX_DEPTH", 1)
        _limited(agent, m1)
        await agent._reroute_waiting(datetime.now(UTC))
        assert len(_open_on(agent, m3, first["root"])) == 1
        assert not _open_on(agent, m2, first["root"])
        assert not any(e.waits for r in agent.sessions.values() for e in r.inbox if e.root == first["root"])


async def test_a_member_holding_the_senders_open_question_is_passed_over(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        outsider = (
            await person.call(
                "create", name="x", dir=str(tmp_path), adapter="agentshell", argv=["bash", "--norc"], unattended=True
            )
        )["id"]
        assert (await _ask(agent, outsider, m2, "first?"))["entry"]["to"] == [m2]
        _limited(agent, m1)
        got = await _ask(agent, outsider, m1, "second?")
        assert got["entry"]["to"] == [m3], "one open question per sender per seat: member 2 is passed over"


async def test_an_on_call_member_is_able_unless_rule_3_would_not_fill_it(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        agent.sessions[m2].state = "closed"
        _limited(agent, m1)
        assert (await _ask(agent, w, m1, "first?"))["entry"]["to"] == [m2], "on call, rule 3 fills it"
        agent.unfillable = {**(agent.unfillable or {}), m2: "fill ceiling"}
        assert (await _ask(agent, w, m1, "second?"))["entry"]["to"] == [m3], "the fill ceiling skips it"


async def test_the_persons_question_to_an_unable_member_moves_within_the_pool_and_else_stays(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)
        _limited(agent, m1)
        got = await person.call("msg", to=m1, text="is this figure right?", kind="ask")
        first = got["entry"]
        assert first["to"] == [m1] and "routed" not in got, "the person's sends are never routed at the send"
        await agent._reroute_waiting(datetime.now(UTC))
        moved = _open_on(agent, m2, first["root"])
        assert len(moved) == 1 and moved[0].from_ == PERSON and moved[0].routed["seat"] == m1
        _limited(agent, m1, m2, m3)
        third = (await person.call("msg", to=m1, text="and that one?", kind="ask"))["entry"]
        await agent._reroute_waiting(datetime.now(UTC))
        assert len(_open_on(agent, tl, third["root"])) == 1, "no member able: the team's able techlead"
        _limited(agent, tl)
        again = (await person.call("msg", to=m1, text="and this one?", kind="ask"))["entry"]
        await agent._reroute_waiting(datetime.now(UTC))
        assert len(_open_on(agent, m1, again["root"])) == 1, "no member and no techlead able: it stays"
        assert not any(e.root == again["root"] for e in agent.person_inbox), "never to the person"


async def test_the_views_routed_around_line_names_the_next_able_member_before_the_techlead(agent, tmp_path):
    """§4.5a card **routed around** line, §4.9b *How it is drawn* (TD-1476, built by TD-1522): an unable member's
    `seat_routed_to` names the member a general question from no sender would go to — the next able member after
    it, never an earlier one — and only with none able today's *the techlead*, else *you*."""
    await park_ticks(agent)
    async with LocalClient() as person:
        tl, (m1, m2, m3), w = await _team(agent, tmp_path, person)

        def seen(sid):
            v = next(x for x in agent._views() if x["id"] == sid)
            return v["seat_unable"], v["seat_routed_to"]

        assert seen(m1) == (None, None)
        _limited(agent, m1)
        assert seen(m1) == ("limited", "qa-p2")
        _limited(agent, m2)
        assert seen(m1) == ("limited", "qa-p3") and seen(m2) == ("limited", "qa-p3")
        _limited(agent, m3)
        assert seen(m3) == ("limited", "the techlead"), "the last member: no later one, so today's road"
        assert seen(m1) == ("limited", "the techlead")
        _limited(agent, tl)
        assert seen(m1) == ("limited", "you")
