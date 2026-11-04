"""A sender withdraws its own open question to the person (design §4.10 *Withdrawing a question*,
TD-1382): `msg_withdraw` closes it `withdrawn` on every copy and tells nobody; its refusals in the
section's order; the person's controls on a withdrawn entry refused in its words; Delete removing it."""

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import mail
from sessionorc.client import AgentError, LocalClient

pytestmark = pytest.mark.integration


def _mk(person, tmp_path):
    async def mk(n: str, **kw):
        d = tmp_path / n  # one directory each (§9 invariant 2)
        d.mkdir(exist_ok=True)
        return (await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))[
            "id"
        ]

    return mk


def _copies(agent, mid):
    out = [e for e in agent.person_inbox if e.id == mid]
    for s in agent.sessions.values():
        out += [e for e in [*s.inbox, *s.outbox] if e.id == mid]
    return out


async def test_a_sender_withdraws_its_own_ask_and_steer_and_nobody_is_told(agent, tmp_path):
    async with LocalClient() as person:
        w = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=w) as c:
            ask = (await c.call("msg", to="person", text="merge it?", kind="ask"))["entry"]["id"]
            steer = (await c.call("msg", to="person", text="fmt?", kind="steer", default="black"))["entry"]["id"]
            await person.call("inbox_pause", msg=steer)
            notes_before = len(agent.sessions[w].inbox)
            got = await c.call("msg_withdraw", id=ask)
            assert set(got) == {"id", "msg", "closed_reason", "closed_at"}
            assert (got["id"], got["msg"], got["closed_reason"]) == ("person", ask, "withdrawn") and got["closed_at"]
            again = await c.call("msg_withdraw", id=ask)  # a retry after a lost reply is not a failure
            assert again == got
            paused = await c.call("msg_withdraw", id=steer)
            assert paused["closed_reason"] == "withdrawn"
            for mid in (ask, steer):
                copies = _copies(agent, mid)
                assert len(copies) >= 2, "the person's copy and the sender's outbox"
                assert all(e.closed_reason == "withdrawn" and e.closed_at and not e.open for e in copies)
                assert all(e.paused_at is None for e in copies), "a pause is cleared"
            # the pause wrote its own `system` note; the withdraws wrote none
            assert len(agent.sessions[w].inbox) == notes_before
            # it owes no outcome: the existing words meet it
            with pytest.raises(AgentError, match="closed as withdrawn: nothing is owed"):
                await c.call("msg", to="person", text="done", outcome="done", for_=ask)
        # the person's controls on it are refused in the withdraw's words, first
        words = "was withdrawn by its sender at .*: nothing waits on an answer"
        with pytest.raises(AgentError, match=words):
            await person.call("msg", text="yes", kind="reply", reply_to=ask)
        for rpc, kw in (
            ("inbox_go_with_it", {}),
            ("inbox_pause", {}),
            ("inbox_resume", {}),
            ("inbox_snooze", {"until": "2026-12-01T08:00:00Z"}),
            ("inbox_hand", {"seat": "nobody"}),
        ):
            with pytest.raises(AgentError, match=words):
                await person.call(rpc, msg=steer, **kw)
        with pytest.raises(AgentError, match=words):
            await person.call("inbox_snooze", msg=ask, until="2026-12-01T08:00:00Z")
        # Delete (and Dismiss) takes the closed branch and says how it had closed
        got = await person.call("inbox_delete", msg=ask)
        assert got["declined"] is False and got["closed_reason"] == "withdrawn"
        assert not [e for e in agent.person_inbox if e.id == ask]
        await person.call("inbox_dismiss", msg=steer)
        await person.call("kill", id=w)


async def test_a_withdraw_is_refused_in_the_sections_order(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w, w2 = await mk("w", unattended=True), await mk("w2", unattended=True)
        await person.call("set_controllers", id=w2, add=[w])
        async with LocalClient(caller=w) as c, LocalClient(caller=w2) as c2:
            ask = (await c.call("msg", to="person", text="merge?", kind="ask"))["entry"]["id"]
            note = (await c.call("msg", to="person", text="fyi", kind="note"))["entry"]["id"]
            other = (await c2.call("msg", to="person", text="theirs?", kind="ask"))["entry"]["id"]
            to_session = (await c.call("msg", to=w2, text="rebase?", kind="ask"))["entry"]["id"]
            closed = (await c.call("msg", to="person", text="squash?", kind="ask"))["entry"]["id"]
            await person.call("inbox_delete", msg=closed)  # declined
            with pytest.raises(AgentError, match="the person withdraws nothing"):
                await person.call("msg_withdraw", id=ask)
            async with LocalClient(caller="ao-nobody-here") as ghost:
                with pytest.raises(AgentError, match="no record of the caller"):
                    await ghost.call("msg_withdraw", id=ask)
            with pytest.raises(AgentError, match="takes back a question to the person"):
                await c.call("msg_withdraw", id=to_session)
            with pytest.raises(AgentError, match=f"{other} is {w2}'s question: only its asker withdraws it"):
                await c.call("msg_withdraw", id=other)
            with pytest.raises(AgentError, match="nothing waits on a note"):
                await c.call("msg_withdraw", id=note)
            with pytest.raises(AgentError, match=r"already closed \(declined\)"):
                await c.call("msg_withdraw", id=closed)
            # an orphaned question is nobody's to withdraw
            for e in agent.person_inbox:
                if e.id == other:
                    e.orphaned = {"asker": w2, "about": "TD-1"}
            with pytest.raises(AgentError, match="only its asker withdraws it"):
                await c2.call("msg_withdraw", id=other)
            for e in agent.person_inbox:
                if e.id == other:
                    e.orphaned = None
            assert next(e for e in agent.person_inbox if e.id == ask).open, "nothing refused closed it"
        for sid in (w, w2):
            await person.call("kill", id=sid)


async def test_a_resumed_sender_withdraws_what_it_asked_before_the_resume(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        old, new = await mk("old", unattended=True), await mk("new", unattended=True)
        async with LocalClient(caller=old) as c:
            ask = (await c.call("msg", to="person", text="merge?", kind="ask"))["entry"]["id"]
        agent.sessions[old].superseded_by = new
        async with LocalClient(caller=new) as c:
            assert (await c.call("msg_withdraw", id=ask))["closed_reason"] == "withdrawn"
        agent.sessions[old].superseded_by = None
        for sid in (old, new):
            await person.call("kill", id=sid)


async def test_a_withdrawn_entry_frees_the_slot_counts_as_an_fyi_and_the_sweep_passes_it(agent, tmp_path, monkeypatch):
    monkeypatch.setattr(mail, "PERSON_SENDER_DEPTH", 1)
    async with LocalClient() as person:
        w = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=w) as c:
            st = (await c.call("msg", to="person", text="fmt?", kind="steer", default="black", bound=60))["entry"]
            with pytest.raises(AgentError, match="open questions"):
                await c.call("msg", to="person", text="another?", kind="ask")
            await c.call("msg_withdraw", id=st["id"])
            fyis = [e for e in agent.person_inbox if not e.open and e.from_ == w]
            assert [e.id for e in fyis] == [st["id"]], "counted among the FYIs until retention"
            await c.call("msg", to="person", text="another?", kind="ask")  # the slot is free
            await agent._sweep_mail(datetime.now(UTC) + timedelta(hours=1))
            e = next(e for e in agent.person_inbox if e.id == st["id"])
            assert e.closed_reason == "withdrawn", "the lapse sweep passes it"
        await person.call("kill", id=w)


async def test_withdrawing_a_passed_up_question_closes_the_seats_copy_and_its_reply_is_refused(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w, tl = await mk("w", team="t", unattended=True), await mk("tl", team="t", unattended=True)
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc:
            q = (await wc.call("msg", to=tl, text="rename the flag?", kind="ask"))["entry"]["id"]
            await tc.call("pass_up", id=q, recommend="keep it")
            with pytest.raises(AgentError, match=f"{q} is {w}'s question"):
                await tc.call("msg_withdraw", id=q)  # the passer is not the asker
            await wc.call("msg_withdraw", id=q)
            seat = next(e for e in agent.sessions[tl].inbox if e.id == q)
            assert seat.closed_reason == "withdrawn"
            with pytest.raises(AgentError, match="was withdrawn by its sender"):
                await tc.call("msg", text="keep it", kind="reply", reply_to=q)
        for sid in (w, tl):
            await person.call("kill", id=sid)
