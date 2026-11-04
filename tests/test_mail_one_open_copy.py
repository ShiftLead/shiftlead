"""One open copy of a question to the person (design §4.10 *One open copy of a question*, TD-1383): an
`ask` or a `steer` to the person is refused while the same sender — along the `superseded_by` chain —
has an open question there on the same `about` and `subject` (with no `about`, the same text), naming
the first; a `note`, a `reply`, an outcome, a pass-up and another sender's question are not read."""

import re
from pathlib import Path

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


def _held(agent, sender):
    return [e.id for e in agent.person_inbox if e.from_ == sender]


async def test_a_second_question_on_the_same_matter_is_refused_naming_the_first(agent, tmp_path):
    async with LocalClient() as person:
        w = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=w) as c:
            first = (await c.call("msg", to="person", text="merge it?", kind="ask", about="TD-9", subject="Merge #1"))[
                "entry"
            ]["id"]
            words = f'you have {first} open to the person on TD-9, "Merge #1": wait for its answer, or withdraw it'
            for kind, kw in (("ask", {}), ("steer", {"default": "yes"})):
                with pytest.raises(AgentError, match=words) as got:
                    await c.call("msg", to="person", text="merge?", kind=kind, about="TD-9", subject="Merge #1", **kw)
                assert f"ao msg --withdraw {first}" in str(got.value)
            # case and runs of white space fold, on `about` and `subject` alike
            with pytest.raises(AgentError, match=f"you have {first} open"):
                await c.call("msg", to="person", text="x", kind="ask", about="td-9", subject="  merge   #1 ")
            # another matter lands: another `about`, another subject
            await c.call("msg", to="person", text="merge?", kind="ask", about="TD-10", subject="Merge #1")
            await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9", subject="Merge #2")
            # an open steer refuses an ask on its matter
            st = (
                await c.call(
                    "msg", to="person", text="fmt?", kind="steer", default="black", about="TD-9", subject="Fmt"
                )
            )["entry"]["id"]
            with pytest.raises(AgentError, match=f"you have {st} open"):
                await c.call("msg", to="person", text="fmt?", kind="ask", about="TD-9", subject="fmt")
            # once the first is closed, the matter is free again
            await c.call("msg_withdraw", id=first)
            await c.call("msg", to="person", text="merge it?", kind="ask", about="TD-9", subject="Merge #1")
        await person.call("kill", id=w)


async def test_another_sender_and_a_resumed_sender(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        old, new, other = await mk("old", unattended=True), await mk("new", unattended=True), await mk("o")
        async with LocalClient(caller=old) as c:
            first = (await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9", subject="Merge"))[
                "entry"
            ]
        async with LocalClient(caller=other) as c:  # two askers, two answers to weigh
            await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9", subject="Merge")
        agent.sessions[old].superseded_by = new
        try:
            async with LocalClient(caller=new) as c:
                with pytest.raises(AgentError, match=f"you have {first['id']} open"):
                    await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9", subject="Merge")
        finally:
            agent.sessions[old].superseded_by = None
        for sid in (old, new, other):
            await person.call("kill", id=sid)


async def test_with_no_about_the_text_must_match_too(agent, tmp_path):
    async with LocalClient() as person:
        w = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=w) as c:
            first = (await c.call("msg", to="person", text="Rebase it onto main?", kind="ask", subject="Rebase"))[
                "entry"
            ]
            assert not first["about"], "an unclaimed agentshell has no `about` to default to"
            await c.call("msg", to="person", text="Rebase it onto dev?", kind="ask", subject="Rebase")
            with pytest.raises(AgentError) as got:
                await c.call("msg", to="person", text="rebase  it onto MAIN?", kind="ask", subject="rebase")
            assert str(got.value).startswith(f'you have {first["id"]} open to the person, "Rebase": wait')
        await person.call("kill", id=w)


async def test_a_clipped_subject_compares_as_stored(agent, tmp_path):
    long = "word " * 40
    async with LocalClient() as person:
        w = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=w) as c:
            first = (await c.call("msg", to="person", text="a?", kind="ask", about="TD-9", subject=long + "one"))[
                "entry"
            ]
            assert len(first["subject"]) <= mail.SUBJECT_CHARS
            with pytest.raises(AgentError, match=f"you have {first['id']} open"):
                await c.call("msg", to="person", text="b?", kind="ask", about="TD-9", subject=long + "two")
        await person.call("kill", id=w)


async def test_a_note_a_reply_and_an_outcome_on_the_same_matter_land(agent, tmp_path):
    async with LocalClient() as person:
        w = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=w) as c:
            ask = (await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9", subject="Merge"))["entry"]
            await c.call("msg", to="person", text="merge?", kind="note", about="TD-9", subject="Merge")
            theirs = (await person.call("msg", to=w, text="merge?", kind="ask", about="TD-9"))["entry"]
            await c.call("msg", text="merge?", kind="reply", reply_to=theirs["id"], about="TD-9", subject="Merge")
            await person.call("msg", text="yes", kind="reply", reply_to=ask["id"])
            await c.call("msg", to="person", text="merged", outcome="done", for_=ask["id"], about="TD-9")
            # answered, a question is closed: the same one asked again on its thread lands
            again = (await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9", subject="Merge"))[
                "entry"
            ]
            await person.call("msg", text="no", kind="reply", reply_to=again["id"])
            await c.call(
                "msg", to="person", text="merge?", kind="ask", thread=again["id"], about="TD-9", subject="Merge"
            )
        await person.call("kill", id=w)


async def test_a_passed_up_copy_is_its_askers_open_question(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w, tl = await mk("w", team="t", unattended=True), await mk("tl", team="t", unattended=True)
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc:
            # sent to the seat with no --subject: the copy stores none, and is read by its text's
            q = (await wc.call("msg", to=tl, text="Rename the flag? It reads badly.", kind="ask"))["entry"]["id"]
            await tc.call("pass_up", id=q, recommend="keep it")  # the seat's act, never the asker's send
            assert not next(e for e in agent.person_inbox if e.id == q).subject
            with pytest.raises(AgentError, match=re.escape(f'you have {q} open to the person, "Rename the flag?"')):
                await wc.call("msg", to="person", text="Rename the flag? It reads badly.", kind="ask")
        for sid in (w, tl):
            await person.call("kill", id=sid)


async def test_a_refused_send_lands_nothing_counts_nothing_and_takes_nothing_up(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w, tl = await mk("w", team="t", unattended=True), await mk("tl", team="t", unattended=True)
        async with LocalClient(caller=w) as wc:
            text = "Rename the flag?"
            first = (await wc.call("msg", to="person", text=text, kind="ask"))["entry"]["id"]
            q = (await wc.call("msg", to=tl, text=text, kind="ask"))["entry"]["id"]
            me = agent.sessions[w]
            before = (len(me.outbox), {k: t.count for k, t in me.threads.items()}, _held(agent, w))
            # a --thread send taking up the question put to the seat meets the rule on the other open one
            with pytest.raises(AgentError, match=f"you have {first} open"):
                await wc.call("msg", to="person", text=text, kind="ask", thread=q)
            assert (len(me.outbox), {k: t.count for k, t in me.threads.items()}, _held(agent, w)) == before
            seat = next(e for e in agent.sessions[tl].inbox if e.id == q)
            assert seat.open and seat.closed_reason is None, "the seat's question is not taken up"
        for sid in (w, tl):
            await person.call("kill", id=sid)


def test_the_skill_names_the_rule_beside_the_verb():
    skill = (Path(__file__).parents[1] / "src" / "shiftlead" / "skill.md").read_text()
    line = next(x for x in skill.splitlines() if "--withdraw" in x)
    assert "same" in line and "refused" in line
