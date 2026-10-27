"""TD-1078, design §4.9b *An answer waiting counts too* and *A member's question stays the member's*:
the unread `reply` that closed a question a seat itself sent, or the `system` note of its lapse, *Go
with it* or decline, counts toward `asks_waiting` by the question's id, so a closed seat is filled
when the answer lands and its first `ao inbox` ends the count; `read_when` says *fills this seat* for
a reply to the seat's own question."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.client import LocalClient
from sessionorc.models import PERSON, SYSTEM, MailEntry, Session, wake_digest

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _seat(state: str = "closed") -> Session:
    return Session(
        id="ao-tl", name="tl", kind="interactive", adapter="claude-code", dir="/r", state=state,
        unattended=True, seat={"trigger": "asks"},
    )  # fmt: skip


def _asked(s: Session, mid: str = "m-q", kind: str = "steer", to: str = PERSON, root: str = "") -> MailEntry:
    q = MailEntry(id=mid, from_=s.id, to=[to], at="2026-10-26T11:00:00Z", kind=kind, text="which way?")
    q.root = root or mid
    s.outbox.append(q)
    return q


def _answer(s: Session, q: MailEntry, mid: str = "m-a", sender: str = PERSON) -> MailEntry:
    a = MailEntry(id=mid, from_=sender, to=[s.id], at="2026-10-26T11:10:00Z", kind="reply", text="this way")
    a.reply_to, a.root = q.id, q.root
    q.closed_reason, q.closed_by = "replied", mid
    s.inbox.append(a)
    return a


def _note(s: Session, q: MailEntry, reason: str, mid: str = "m-n") -> MailEntry:
    n = MailEntry(id=mid, from_=SYSTEM, to=[s.id], at="2026-10-26T11:10:00Z", kind="note", text=f"{q.id} {reason}")
    n.reply_to, n.root = q.id, q.root
    q.closed_reason = reason
    s.inbox.append(n)
    return n


@pytest.mark.unit
def test_an_unread_answer_to_the_seats_own_question_counts_by_the_questions_id_until_read():
    s = _seat()
    q = _asked(s)
    assert s.asks_waiting() == 0, "an open question of its own waits on the person, not on the seat"
    a = _answer(s, q)
    assert s.asks_ids() == ["m-q"] and s.asks_waiting() == 1
    assert s.asks_waiting(handed_only=True) == 0
    a.read_at = "2026-10-26T11:20:00Z"
    assert s.asks_waiting() == 0, "the fill's first `ao inbox` ends the count"


@pytest.mark.unit
@pytest.mark.parametrize("reason", ["lapsed", "go_with_it", "declined"])
def test_the_homes_note_ending_the_question_counts_and_any_other_note_does_not(reason):
    s = _seat()
    q = _asked(s, kind="ask" if reason == "declined" else "steer")
    _note(s, q, reason)
    assert s.asks_ids() == ["m-q"]
    plain = MailEntry(id="m-p", from_="ao-w", to=[s.id], at="2026-10-26T11:30:00Z", kind="note", text="fyi")
    plain.reply_to = "m-q"  # a session's note naming it is no answer
    t = _seat()
    tq = _asked(t)
    tq.closed_reason = reason
    t.inbox.append(plain)
    assert t.asks_waiting() == 0


@pytest.mark.unit
def test_a_second_reply_on_a_closed_question_and_a_reply_to_another_ones_question_count_nothing():
    s = _seat()
    q = _asked(s)
    first = _answer(s, q)
    first.read_at = "2026-10-26T11:20:00Z"
    late = MailEntry(id="m-late", from_=PERSON, to=[s.id], at="2026-10-26T11:30:00Z", kind="reply", text="also")
    late.reply_to, late.root = q.id, q.root
    s.inbox.append(late)
    assert s.asks_waiting() == 0, "the question was closed by the first reply"
    # a reply to a question the seat did not send — another session's, copied to it — counts nothing
    other = MailEntry(id="m-o", from_="ao-w", to=[PERSON], at="2026-10-26T11:00:00Z", kind="ask", text="?")
    s.outbox.append(other)  # not this seat's own (its `from` is another record)
    r = MailEntry(id="m-r", from_=PERSON, to=[s.id], at="2026-10-26T11:40:00Z", kind="reply", text="no")
    r.reply_to = "m-o"
    other.closed_reason, other.closed_by = "replied", "m-r"
    s.inbox.append(r)
    assert s.asks_waiting() == 0


@pytest.mark.unit
def test_a_second_answer_on_another_question_fills_again():
    s = _seat()
    _answer(s, _asked(s, "m-q1"), "m-a1").read_at = "2026-10-26T11:20:00Z"
    assert s.asks_ids() == []
    _answer(s, _asked(s, "m-q2"), "m-a2")
    assert s.asks_ids() == ["m-q2"]


@pytest.mark.unit
def test_a_handed_entry_with_the_seats_own_steer_on_its_thread_waits_and_counts_once_answered():
    s = _seat()
    h = MailEntry(id="m-entry", from_=PERSON, to=[s.id], at="2026-10-26T10:00:00Z", kind="ask", text="the parser …")
    h.handed, h.entry = True, {"repo": "shiftlead", "type": "debt"}
    s.inbox.append(h)
    q = _asked(s, kind="steer", root="m-entry")
    assert s.asks_waiting() == 0, "the seat's own steer on the thread waits on the person"
    _answer(s, q)
    assert s.asks_ids() == ["m-entry"], "the handed entry counts again, and the answer on its thread not twice"


@pytest.mark.unit
def test_the_wake_digest_reads_whether_an_answer_waits():
    s = _seat()
    q = _asked(s)
    before = wake_digest(s.view())
    _answer(s, q)
    assert s.view()["asks_waiting"] == 1 and wake_digest(s.view()) != before


@pytest.mark.unit
def test_read_when_says_fills_this_seat_for_a_reply_to_its_own_question_and_waits_for_a_note():
    seat = _seat("exited")
    assert mail.read_when(seat, "reply", NOW, refills=True).startswith("fills this seat")
    assert mail.read_when(seat, "note", NOW).startswith("waits in the seat's mailbox")


async def _make_seat(person, tmp_path) -> str:
    return (
        await person.call(
            "create", name="tl", dir=str(tmp_path), adapter="agentshell", argv=["bash", "--norc", "--noprofile"],
            unattended=True, supervised=True, prompt="the seat's brief", seat={"trigger": "asks"},
        )  # fmt: skip
    )["id"]


def _end(agent, sid: str) -> None:
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.exit_code = "exited", True, 0
    agent.store.save(rec)


@pytest.mark.integration
async def test_a_person_reply_to_the_seats_own_steer_fills_the_closed_seat_once(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _make_seat(person, tmp_path)
        async with LocalClient(caller=sid) as tl:
            q = (await tl.call("msg", to=PERSON, kind="steer", default="A", text="A or B?"))["entry"]
        _end(agent, sid)
        rec = agent.sessions[sid]
        now = datetime.now(UTC)
        await agent._keep_running(now)
        assert agent.sessions[sid] is rec and rec.seat_due is None, "its own question out: nothing due"
        mine = (await person.call("inbox"))["entries"]
        assert next(e for e in mine if e["id"] == q["id"])["on_handed"] is True, "Reply reads *fills this seat*"
        got = await person.call("msg", to=sid, kind="reply", reply_to=q["id"], text="B")
        assert got["read_when"][sid].startswith("fills this seat")
        agent._profile_gated = lambda *a: True  # due, held: the due names the question
        await agent._keep_running(now)
        assert rec.seat_due["by"] == "asks" and rec.seat_due["ask"] == q["id"]
        del agent._profile_gated
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not rec, "the answer fills the seat"
        await agent._keep_running(now)
        assert agent.sessions[sid] is new, "and only once"
        async with LocalClient(caller=sid) as tl:
            await tl.call("inbox", unread=True)
        assert new.asks_waiting() == 0
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_sessions_reply_closing_the_seats_own_ask_fills_it(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _make_seat(person, tmp_path)
        (tmp_path / "w").mkdir()
        w = (
            await person.call(
                "create", name="w", dir=str(tmp_path / "w"), adapter="agentshell",
                argv=["bash", "--norc", "--noprofile"], unattended=True,
            )  # fmt: skip
        )["id"]
        await person.call("set_controllers", id=w, add=[sid])
        async with LocalClient(caller=sid) as tl:
            q = (await tl.call("msg", to=w, kind="ask", text="which branch?"))["entry"]
        _end(agent, sid)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=sid, kind="reply", reply_to=q["id"], text="td1-x")
        assert got["read_when"][sid].startswith("fills this seat")
        assert agent.sessions[sid].asks_ids(home=agent.host) == [q["id"]]
        for x in (sid, w):
            await person.call("kill", id=x)


@pytest.mark.integration
@pytest.mark.parametrize("how", ["lapse", "go_with_it", "decline"])
async def test_the_homes_note_carries_the_questions_thread_and_fills_the_seat(agent, tmp_path, how):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _make_seat(person, tmp_path)
        async with LocalClient(caller=sid) as tl:
            if how == "decline":
                q = (await tl.call("msg", to=PERSON, kind="ask", text="may I?"))["entry"]
            else:
                bound = 0.2 if how == "lapse" else None
                q = (await tl.call("msg", to=PERSON, kind="steer", default="A", text="A?", bound=bound))["entry"]
        _end(agent, sid)
        rec = agent.sessions[sid]
        if how == "lapse":
            await asyncio.sleep(0.3)
            await agent._sweep_mail(datetime.now(UTC))
        elif how == "go_with_it":
            await person.call("inbox_go_with_it", msg=q["id"])
        else:
            await person.call("inbox_delete", msg=q["id"])
        note = next(e for e in rec.inbox if e.from_ == SYSTEM)
        assert (note.reply_to, note.root) == (q["id"], q["id"])
        assert note.uncharged is (how == "lapse")
        assert rec.asks_ids(home=agent.host) == [q["id"]]
        await agent._keep_running(datetime.now(UTC))
        assert agent.sessions[sid] is not rec, "the note fills the seat"
        await person.call("kill", id=sid)
