"""**Not clear** on a question to the person (design §4.10 *Text a person reads is checked at its writer*, rule 6;
§4.5a row **Not clear**; TD-1853): `inbox_not_clear` closes a question its writer asked and notes the asker,
undoes a pass-up and notes the passer, closes an orphan with no note, and is refused in the section's order."""

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc.client import AgentError, LocalClient
from sessionorc.models import SYSTEM

pytestmark = pytest.mark.integration

QUESTION = "Should the old flag be dropped?"


async def _mk(person, tmp_path, n: str, **kw):
    d = tmp_path / n  # one directory each (§9 invariant 2)
    d.mkdir(exist_ok=True)
    kw.setdefault("unattended", True)
    return (await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))["id"]


def _copies(agent, mid):
    out = [e for e in agent.person_inbox if e.id == mid]
    for s in agent.sessions.values():
        out += [e for e in [*s.inbox, *s.outbox] if e.id == mid]
    return out


def _notes(agent, sid, mid):
    return [e for e in agent.sessions[sid].inbox if e.from_ == SYSTEM and e.reply_to == mid]


async def test_a_question_its_writer_asked_closes_not_clear_and_its_asker_is_told(agent, tmp_path):
    async with LocalClient() as person:
        w = await _mk(person, tmp_path, "w")
        async with LocalClient(caller=w) as c:
            ask = (await c.call("msg", to="person", text="merge it?", kind="ask"))["entry"]["id"]
            steer = (await c.call("msg", to="person", text="fmt?", kind="steer", default="black", bound=60))["entry"]
            await person.call("inbox_pause", msg=steer["id"])
            got = await person.call("inbox_not_clear", msg=ask)
            assert got == {"writer": "w", "kind": "ask", "repo": "-"}
            assert (await person.call("inbox_not_clear", msg=steer["id"]))["kind"] == "steer"
            for mid in (ask, steer["id"]):
                copies = _copies(agent, mid)
                assert len(copies) >= 2 and all(e.closed_reason == "not_clear" and not e.open for e in copies)
                assert not any(e.owes for e in copies), "nobody answered: nothing is owed"
                (note,) = _notes(agent, w, mid)
                assert "the person marked this Not clear: rewrite it for them and ask again." in note.text
                assert note.root == mid
            # a steer so closed, paused or not, takes no default at its bound
            await agent._sweep_mail(datetime.now(UTC) + timedelta(hours=1))
            assert next(e for e in agent.person_inbox if e.id == steer["id"]).closed_reason == "not_clear"
            with pytest.raises(AgentError, match="nothing is owed|owes no outcome|not answered|closed as not_clear"):
                await c.call("msg", to="person", text="done", outcome="done", for_=ask)
            # the rewrite is let in: one open copy again
            await c.call("msg", to="person", text="Should I merge it now?", kind="ask")
        await person.call("kill", id=w)


async def test_its_refusals_and_a_session_caller(agent, tmp_path):
    async with LocalClient() as person:
        w = await _mk(person, tmp_path, "w")
        async with LocalClient(caller=w) as c:
            gone = (await c.call("msg", to="person", text="merge?", kind="ask"))["entry"]["id"]
            await c.call("msg_withdraw", id=gone)
            with pytest.raises(AgentError, match="was withdrawn by its sender"):
                await person.call("inbox_not_clear", msg=gone)
            note = (await c.call("msg", to="person", text="fyi", kind="note"))["entry"]["id"]
            with pytest.raises(AgentError, match="is a note"):
                await person.call("inbox_not_clear", msg=note)
            done = (await c.call("msg", to="person", text="squash?", kind="ask"))["entry"]["id"]
            await person.call("inbox_delete", msg=done)  # declined
            with pytest.raises(AgentError, match=r"already closed \(declined\)"):
                await person.call("inbox_not_clear", msg=done)
            mine = (await c.call("msg", to="person", text="rebase?", kind="ask"))["entry"]["id"]
            with pytest.raises(AgentError, match="the person"):
                await c.call("inbox_not_clear", msg=mine)
            assert next(e for e in agent.person_inbox if e.id == mine).open
        await person.call("kill", id=w)


async def _passed(person, agent, tmp_path, *, kind="ask", question=QUESTION, **kw):
    w = await _mk(person, tmp_path, "w", team="t")
    tl = await _mk(person, tmp_path, "tl", team="t")
    async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc:
        q = (await wc.call("msg", to=tl, text="rename the flag?", kind=kind, **kw))["entry"]["id"]
        await tc.call("pass_up", id=q, recommend="Keep it — a session keeps the flag", question=question)
    return w, tl, q


async def test_a_passed_up_copy_undoes_the_pass_and_its_passer_can_pass_it_up_again(agent, tmp_path):
    async with LocalClient() as person:
        w, tl, q = await _passed(person, agent, tmp_path)
        got = await person.call("inbox_not_clear", msg=q)
        assert got == {"writer": "tl", "kind": "ask", "repo": "-"}
        assert not [e for e in agent.person_inbox if e.id == q], "the person's copy is dropped"
        copies = _copies(agent, q)
        assert copies and all(e.open and e.passed_up is None and e.recommend is None for e in copies)
        (note,) = _notes(agent, tl, q)
        assert "marked your pass-up Not clear: rewrite your --question and pass it up again." in note.text
        assert not _notes(agent, w, q), "the asker is told nothing: its question waits on the passer again"
        assert agent.sessions[tl].asks_waiting() >= 1, "open in the passer's inbox again"
        async with LocalClient(caller=tl) as tc:
            await tc.call("pass_up", id=q, recommend="Keep it — a session keeps the flag", question=QUESTION)
        assert [e for e in agent.person_inbox if e.id == q]
        for sid in (w, tl):
            await person.call("kill", id=sid)


async def test_a_pass_made_before_its_question_was_carried_is_noted_in_its_own_words(agent, tmp_path):
    async with LocalClient() as person:
        w, tl, q = await _passed(person, agent, tmp_path)
        for e in _copies(agent, q):
            if e.recommend:
                e.recommend = {k: v for k, v in e.recommend.items() if k != "question"}
        await person.call("inbox_not_clear", msg=q)
        (note,) = _notes(agent, tl, q)
        assert "could not follow the question you passed up: pass it up again with --question." in note.text
        for sid in (w, tl):
            await person.call("kill", id=sid)


async def test_a_paused_passed_up_steer_is_resumed_by_the_undo_and_lapses_at_its_moved_bound(agent, tmp_path):
    async with LocalClient() as person:
        w, tl, q = await _passed(person, agent, tmp_path, kind="steer", default="keep", bound=600)
        await person.call("inbox_pause", msg=q)
        held = datetime.now(UTC) - timedelta(minutes=30)
        for e in _copies(agent, q):
            e.paused_at = held.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        before = next(e for e in agent.sessions[w].outbox if e.id == q).bound
        await person.call("inbox_not_clear", msg=q)
        copies = _copies(agent, q)
        assert all(e.paused_at is None and e.open for e in copies)
        after = copies[0].bound
        moved = datetime.fromisoformat(after.replace("Z", "+00:00")) - datetime.fromisoformat(
            before.replace("Z", "+00:00")
        )
        assert moved >= timedelta(minutes=29), "the bound moved later by the time held"
        resumed = [n for n in agent.sessions[w].inbox if n.from_ == SYSTEM and "resumed by the person" in n.text]
        assert resumed and not resumed[-1].uncharged
        await agent._sweep_mail(datetime.fromisoformat(before.replace("Z", "+00:00")) + timedelta(minutes=1))
        assert all(e.open for e in _copies(agent, q)), "not at its old bound"
        await agent._sweep_mail(datetime.fromisoformat(after.replace("Z", "+00:00")) + timedelta(minutes=1))
        assert all(e.closed_reason == "lapsed" for e in _copies(agent, q)), "it lapses at its moved bound"
        for sid in (w, tl):
            await person.call("kill", id=sid)


async def test_a_closed_passer_gets_it_back_and_a_gone_one_closes_it_for_its_asker(agent, tmp_path):
    async with LocalClient() as person:
        w, tl, q = await _passed(person, agent, tmp_path)
        agent.sessions[tl].state = "closed"  # closed, no successor: it still holds a record
        got = await person.call("inbox_not_clear", msg=q)
        assert got["writer"] == "tl" and all(e.open for e in _copies(agent, q))
        assert _notes(agent, tl, q)
        async with LocalClient(caller=w) as wc:
            q2 = (await wc.call("msg", to=tl, text="and the other flag?", kind="ask"))["entry"]["id"]
        agent.sessions[tl].state = "idle"
        async with LocalClient(caller=tl) as tc:
            await tc.call("pass_up", id=q2, recommend="Keep it — a session keeps the flag", question=QUESTION)
        gone = agent.sessions.pop(tl)  # no record at the end of its chain: nobody to rewrite it
        try:
            got = await person.call("inbox_not_clear", msg=q2)
        finally:
            agent.sessions[tl] = gone
        assert got == {"writer": "w", "kind": "ask", "repo": "-"}
        held = [e for e in _copies(agent, q2) if e not in gone.inbox]  # the gone record's copy was out of reach
        assert held and all(e.closed_reason == "not_clear" for e in held)
        (note,) = _notes(agent, w, q2)
        assert "rewrite it for them and ask again." in note.text
        for sid in (w, tl):
            await person.call("kill", id=sid)


async def test_an_orphaned_question_closes_with_no_note_and_its_passer_is_told_nothing(agent, tmp_path):
    async with LocalClient() as person:
        w, tl, q = await _passed(person, agent, tmp_path)
        for e in _copies(agent, q):
            e.orphaned = {"how": "closed", "ref": "TD-1", "name": "gone-w"}
        got = await person.call("inbox_not_clear", msg=q)
        assert got == {"writer": "gone-w", "kind": "ask", "repo": "-"}
        assert all(e.closed_reason == "not_clear" for e in _copies(agent, q))
        assert not _notes(agent, tl, q) and not _notes(agent, w, q)
        for sid in (w, tl):
            await person.call("kill", id=sid)
