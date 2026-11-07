"""A seat that cannot answer (design §4.9b *A seat that cannot answer is routed around*, TD-1443, TD-1473
slice 1): `seat_able`'s predicate over a record's replica, the order `_one_seat` picks in, and the words
rule 3's pass writes to the home's `unfillable` for an ended seat it would not fill."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from conftest import park_ticks

from sessionorc import agent_mail, models
from sessionorc.agent_mail import seat_able, seat_unable
from sessionorc.client import LocalClient

NOW = datetime(2026, 11, 7, 2, 0, tzinfo=UTC)


def _z(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def rec(n: str = "techlead", state: str = "idle", tags: bool = True, **kw) -> models.Session:
    s = models.Session(id=f"ao-{n}", name=n, kind="claude", adapter="claude-code", dir="/w", state=state)
    s.seat = {"trigger": "asks", **({"tags": True} if tags else {})}
    s.supervised, s.unattended = True, True
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.mark.unit
def test_a_live_seat_is_able_and_a_stall_needs_two_ticks():
    assert seat_able(rec(), NOW)
    assert seat_able(rec(state="working"), NOW)
    assert seat_able(rec(state="stalled?", stalled_ticks=1), NOW), "one slow turn does not move a question"
    assert seat_unable(rec(state="stalled?", stalled_ticks=2), NOW) == "stalled?"


@pytest.mark.unit
def test_limited_is_waited_out_only_when_its_reset_is_near_and_still_ahead():
    assert seat_unable(rec(state="limited"), NOW) == "limited", "no reset known"
    soon = _z(NOW + timedelta(minutes=10))
    assert seat_able(rec(state="limited", limited_reset=soon), NOW), "a reset ten minutes away is waited out"
    far = _z(NOW + timedelta(hours=6))
    assert seat_unable(rec(state="limited", limited_reset=far), NOW) == "limited, resets 08:00Z"
    edge = _z(NOW + timedelta(minutes=30))
    assert seat_able(rec(state="limited", limited_reset=edge), NOW), "ROUTE_AROUND_AFTER itself is still waited"
    past = _z(NOW - timedelta(minutes=5))
    assert seat_unable(rec(state="limited", limited_reset=past), NOW) == "limited, resets 01:55Z", (
        "a reset passed while the state stays limited: a box nobody answered"
    )


@pytest.mark.unit
def test_a_seat_the_usage_gate_paused_is_able_only_with_its_next_near():
    gated = {"profile": "p", "label": "5h", "pct": 90, "line": 80, "since": _z(NOW)}
    assert seat_unable(rec(gated=gated), NOW) == "paused by the usage gate"
    near = {**gated, "next": _z(NOW + timedelta(minutes=15))}
    assert seat_able(rec(gated=near), NOW)
    far = {**gated, "next": _z(NOW + timedelta(hours=2))}
    assert seat_unable(rec(gated=far), NOW) == "paused by the usage gate, until 04:00Z"


@pytest.mark.unit
def test_an_ended_seat_is_able_where_rule_3_would_fill_it():
    for state in ("exited", "closed"):
        assert seat_able(rec(state=state), NOW), "empty before the first tick: fillable"
        assert seat_able(rec(state=state), NOW, {"ao-other": "suspended"})
        for word in ("suspended", "sat out", "restart ceiling", "profile gated", "fill ceiling"):
            assert seat_unable(rec(state=state), NOW, {"ao-techlead": word}) == word
        assert seat_unable(rec(state=state, supervised=False), NOW) == "not supervised"
        assert seat_unable(rec(state=state, unattended=False), NOW) == "not supervised"
    # a live seat's stale word is not read: rule 3 only fills an ended one
    assert seat_able(rec(), NOW, {"ao-techlead": "fill ceiling"})


@pytest.mark.unit
def test_one_seat_takes_an_able_record_first_then_the_techlead_then_live_over_ended():
    one = agent_mail.MailMixin._one_seat
    lead = rec("lead", state="limited")
    review = rec("review", tags=False)
    assert one("t", [lead, review], NOW) is review, "an able record before the techlead seat"
    live_lead = rec("lead")
    assert one("t", [live_lead, review], NOW) is live_lead, "both able: the techlead seat"
    closed, exited = rec("c", state="closed"), rec("e", state="exited")
    assert one("t", [closed, exited], NOW, {"ao-e": "restart ceiling"}) is closed, "the able one, though closed"
    assert one("t", [closed, exited], NOW) is exited, "both able: on call over closed"
    stalled = rec("s", state="stalled?", stalled_ticks=3)
    assert one("t", [stalled], NOW) is stalled, "one record is the seat, able or not (routing is the send's)"


@pytest.mark.integration
async def test_rule_3_writes_why_it_would_not_fill_an_ended_seat(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        d = tmp_path / "lead"
        d.mkdir()
        sid = (
            await person.call(
                "create", name="lead", dir=str(d), adapter="agentshell", argv=["bash", "--norc"], unattended=True,
                team="t", project="P", seat={"trigger": "asks", "tags": True}, supervised=True, prompt="brief",
            )
        )["id"]  # fmt: skip
        await person.call("close", id=sid)
        s = agent.sessions[sid]
        now = datetime.now(UTC)
        records = list(agent.sessions.values())
        await agent._seat_pass(s, now, records)
        assert sid not in agent.unfillable and seat_able(s, now, agent.unfillable), "a closed seat rule 3 fills"
        s.restart_ceiling = {"at": _z(now), "count": 3, "why": "crash"}
        await agent._seat_pass(s, now, records)
        assert agent.unfillable[sid] == "restart ceiling"
        s.restart_ceiling = {"at": _z(now), "count": 6, "why": "fill"}
        await agent._seat_pass(s, now, records)
        assert agent.unfillable[sid] == "fill ceiling"
        s.restart_ceiling = None
        s.suspended = {"at": _z(now)}
        await agent._seat_pass(s, now, records)
        assert agent.unfillable[sid] == "suspended" and seat_unable(s, now, agent.unfillable) == "suspended"
        s.suspended = None
        s.sit_out = {"at": _z(now)}
        await agent._seat_pass(s, now, records)
        assert agent.unfillable[sid] == "sat out"
        s.sit_out = None
        await agent._seat_pass(s, now, records)
        assert sid not in agent.unfillable, "each pass writes it afresh"
        await person.call("kill", id=sid)


@pytest.mark.unit
def test_a_gated_next_exactly_thirty_minutes_away_is_waited_and_one_past_it_is_not():
    edge = {"next": _z(NOW + timedelta(minutes=30))}
    assert seat_able(rec(gated=edge), NOW), "ROUTE_AROUND_AFTER itself is still waited"
    over = {"next": _z(NOW + timedelta(minutes=30, seconds=1))}
    assert seat_unable(rec(gated=over), NOW) == "paused by the usage gate, until 02:30Z"


@pytest.mark.unit
def test_a_reset_in_another_zone_reads_as_its_instant_and_an_unreadable_one_as_unknown():
    soon = (NOW + timedelta(minutes=10)).astimezone(timezone(timedelta(hours=2))).isoformat()
    assert soon.endswith("+02:00") and seat_able(rec(state="limited", limited_reset=soon), NOW)
    for bad in ("not a time", "2026-11-07T02:10:00"):  # garbage, and a time with no zone
        assert seat_unable(rec(state="limited", limited_reset=bad), NOW) == "limited"
        assert seat_unable(rec(gated={"next": bad}), NOW) == "paused by the usage gate"


@pytest.mark.unit
def test_two_able_techlead_seats_live_alike_are_refused_naming_both():
    one = agent_mail.MailMixin._one_seat
    with pytest.raises(agent_mail.RpcError, match="t has 2 question seats: a, b"):
        one("t", [rec("a"), rec("b")], NOW)
    assert one("t", [rec("a"), rec("b", state="limited")], NOW).name == "a", "the able one of two tagged"
