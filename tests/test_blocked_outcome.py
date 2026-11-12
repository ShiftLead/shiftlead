"""TD-1694, design §4.10 *Outcomes*: a `blocked` outcome is never a question's stand-in — refused when it
names the caller's own open question to the person (or the rerouted original of one), or while the caller
holds an open question on the outcome's own thread; warned when the caller holds one it does not name — and
it is not the last word: a newer `done` or `dropped`, or a question on its thread, takes its place, kept
as `was`."""

from __future__ import annotations

import pytest

from sessionorc.client import AgentError, LocalClient
from sessionorc.models import PERSON, MailEntry


def _mk(person, tmp_path):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        return (await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))[
            "id"
        ]

    return mk


async def _answered(w, person, worker, text="rebase or merge?"):
    q = (await w.call("msg", to=PERSON, text=text, kind="ask"))["entry"]
    await person.call("msg", to=worker, text="merge it", kind="reply", reply_to=q["id"])
    return q


def _held(agent, mid):
    return next(e for e in agent.person_inbox if e.id == mid)


@pytest.mark.integration
async def test_a_blocked_outcome_naming_the_callers_open_question_is_refused(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        worker, other = await mk("w", unattended=True), await mk("o", unattended=True)
        async with LocalClient(caller=worker) as w, LocalClient(caller=other) as o:
            q = await _answered(w, person, worker)
            fresh = (await w.call("msg", to=PERSON, text="which base?", kind="ask"))["entry"]
            steer = (await w.call("msg", to=PERSON, text="go on?", kind="steer", default="yes", bound=3600))["entry"]
            theirs = (await o.call("msg", to=PERSON, text="theirs", kind="ask"))["entry"]
            for named in (fresh["id"], steer["id"]):
                with pytest.raises(AgentError, match=f"{named} is your open question to the person") as no:
                    await w.call(
                        "msg", to=PERSON, text=f"waits on {named}", outcome="blocked", for_=q["id"], kind="note"
                    )
                assert f"--thread {q['id']}" in str(no.value) and f"ao msg --withdraw {named}" in str(no.value)
            assert _held(agent, q["id"]).outcome is None, "nothing is written on a refusal"
            # another sender's open ask names no question of the caller's: it lands, warned of the caller's own
            got = await w.call(
                "msg", to=PERSON, text=f"waits on {theirs['id']}", outcome="blocked", for_=q["id"], kind="note"
            )
            warned = [x for x in got["warnings"] if x.startswith("you hold open question")]
            assert {fresh["id"], steer["id"]} == {x.split()[4] for x in warned}
            assert all(f"--thread {q['id']}" in x for x in warned)
            assert _held(agent, q["id"]).outcome["state"] == "blocked"
        await person.call("kill", id=worker)
        await person.call("kill", id=other)


@pytest.mark.integration
async def test_an_answered_question_a_superseded_records_and_a_rerouted_original(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        old, worker = await mk("old", unattended=True), await mk("w", unattended=True)
        async with LocalClient(caller=old) as o, LocalClient(caller=worker) as w:
            before = (await o.call("msg", to=PERSON, text="asked before the resume", kind="ask"))["entry"]
            q = await _answered(w, person, worker)
            past = await _answered(w, person, worker, "an answered one")
            agent.sessions[old].superseded_by = worker
            with pytest.raises(AgentError, match=f"{before['id']} is your open question"):
                await w.call("msg", to=PERSON, text=f"see {before['id']}", outcome="blocked", for_=q["id"])
            # the original of a question rerouted to the person names the moved copy
            moved = (await w.call("msg", to=PERSON, text="moved here", kind="ask"))["entry"]
            orig = MailEntry(id="m-0123456789ab", from_=worker, to=["ao-tl"], at=moved["at"], kind="ask", text="?")
            orig.root, orig.closed_reason = moved["root"], "rerouted"
            agent.sessions[worker].outbox.append(orig)
            with pytest.raises(AgentError, match=f"{moved['id']} is your open question"):
                await w.call("msg", to=PERSON, text="waits on m-0123456789ab", outcome="blocked", for_=q["id"])
            # a past, answered question refuses nothing
            await person.call("msg", to=old, text="withdrawn", kind="reply", reply_to=before["id"])
            await person.call("msg", to=worker, text="x", kind="reply", reply_to=moved["id"])
            got = await w.call("msg", to=PERSON, text=f"as in {past['id']}", outcome="blocked", for_=q["id"])
            assert not [x for x in got["warnings"] if x.startswith("you hold open question")]
        await person.call("kill", id=worker)
        await person.call("kill", id=old)


@pytest.mark.integration
async def test_a_blocked_outcome_is_replaced_and_kept_as_was(agent, tmp_path):
    async with LocalClient() as person:
        worker = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=worker) as w:
            q = await _answered(w, person, worker)
            await w.call("msg", to=PERSON, text="waits on the vendor", outcome="blocked", for_=q["id"])
            with pytest.raises(AgentError, match="is settled"):
                await w.call("msg", to=PERSON, text="still", outcome="blocked", for_=q["id"])
            # the other order: a fresh question while the blocked outcome is open is warned
            got = await w.call("msg", to=PERSON, text="something else?", kind="ask")
            assert f"your blocked outcome on {q['id']} is open: if this follows it, ask on its thread instead" in (
                " ".join(got["warnings"])
            )
            done = await w.call("msg", to=PERSON, text="done: #12", outcome="done", for_=q["id"])
            out = _held(agent, q["id"]).outcome
            assert out["state"] == "done" and out["by"] == done["entry"]["id"]
            assert out["was"]["state"] == "blocked" and out["was"]["text"] == "waits on the vendor"
            with pytest.raises(AgentError, match="is settled"):
                await w.call("msg", to=PERSON, text="more", outcome="dropped", for_=q["id"])
            q2 = await _answered(w, person, worker, "second")
            await w.call("msg", to=PERSON, text="waits", outcome="blocked", for_=q2["id"])
            again = await w.call("msg", to=PERSON, text="which vendor?", kind="ask", thread=q2["id"])
            assert not [x for x in again["warnings"] if "your blocked outcome" in x], "on its thread: no warning"
            out = _held(agent, q2["id"]).outcome
            assert out["state"] == "asked_again" and out["was"]["state"] == "blocked"
        await person.call("kill", id=worker)


@pytest.mark.integration
async def test_a_handed_entry_waits_on_its_own_thread_and_owes_again_after_a_question(agent, tmp_path):
    async with LocalClient() as person:
        sid = await _mk(person, tmp_path)("tl", unattended=True)
        handed = MailEntry(id="m-entry", from_=PERSON, to=[sid], at="2026-11-12T10:00:00Z", kind="ask", text="fix it")
        handed.handed, handed.entry = True, {"repo": "shiftlead", "type": "debt"}
        agent.sessions[sid].inbox.append(handed)
        async with LocalClient(caller=sid) as tl:
            await tl.call("msg", to=PERSON, text="waits on the person's key", outcome="blocked", for_="m-entry")
            assert handed.outcome["state"] == "blocked" and not handed.owes
            q = (await tl.call("msg", to=PERSON, text="which key?", kind="ask", thread="m-entry"))["entry"]
            assert handed.outcome is None and handed.was["state"] == "blocked" and handed.owes
            for text in (f"waits on {q['id']}", "still blocked"):  # named or not, its own thread's open question
                with pytest.raises(AgentError, match=f"{q['id']} is your open question on this thread: wait"):
                    await tl.call("msg", to=PERSON, text=text, outcome="blocked", for_="m-entry")
            await person.call("msg", to=sid, text="the blue one", kind="reply", reply_to=q["id"])
            await tl.call("msg", to=PERSON, text="done: TD-9", outcome="done", for_="m-entry")
            assert handed.outcome["state"] == "done" and handed.outcome["was"]["state"] == "blocked"
            assert handed.was is None
        await person.call("kill", id=sid)
