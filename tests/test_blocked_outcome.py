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


@pytest.mark.integration
async def test_the_first_named_id_is_refused_and_a_lead_routed_or_embedded_id_refuses_nothing(agent, tmp_path):
    async with LocalClient() as person:
        worker = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=worker) as w:
            q = await _answered(w, person, worker)
            a = (await w.call("msg", to=PERSON, text="first?", kind="ask"))["entry"]
            b = (await w.call("msg", to=PERSON, text="second?", kind="ask"))["entry"]
            with pytest.raises(AgentError, match=f"^{b['id']} is your open question") as no:
                await w.call("msg", to=PERSON, text=f"on {b['id']} and {a['id']}", outcome="blocked", for_=q["id"])
            assert a["id"] not in str(no.value).split(":")[0]
            # a rerouted original whose copy went to a lead holds no question to the person
            lead = MailEntry(id="m-abcdefabcdef", from_=worker, to=["ao-tl"], at=q["at"], kind="ask", text="?")
            lead.root, lead.closed_reason = "m-elsewhere000", "rerouted"
            agent.sessions[worker].outbox.append(lead)
            for gone in (a, b):
                await w.call("msg_withdraw", id=gone["id"])
            # an id inside a longer hex run, or glued to a word, names nothing: it lands, warned of c
            c = (await w.call("msg", to=PERSON, text="third?", kind="ask"))["entry"]
            got = await w.call(
                "msg", to=PERSON, text=f"waits on m-abcdefabcdef, x{c['id']} and {c['id']}ff", outcome="blocked",
                for_=q["id"],
            )  # fmt: skip
            assert _held(agent, q["id"]).outcome["state"] == "blocked"
            assert any(x.startswith(f"you hold open question {c['id']}") for x in got["warnings"])
        await person.call("kill", id=worker)


@pytest.mark.integration
async def test_a_handed_entrys_blocked_outcome_is_replaced_once_and_was_never_nests(agent, tmp_path):
    async with LocalClient() as person:
        sid = await _mk(person, tmp_path)("tl", unattended=True)
        handed = MailEntry(id="m-entry", from_=PERSON, to=[sid], at="2026-11-12T10:00:00Z", kind="ask", text="fix it")
        handed.handed, handed.entry = True, {"repo": "shiftlead", "type": "debt"}
        agent.sessions[sid].inbox.append(handed)
        async with LocalClient(caller=sid) as tl:
            await tl.call("msg", to=PERSON, text="first block", outcome="blocked", for_="m-entry")
            with pytest.raises(AgentError, match="is settled"):
                await tl.call("msg", to=PERSON, text="again", outcome="blocked", for_="m-entry")
            q = (await tl.call("msg", to=PERSON, text="which?", kind="ask", thread="m-entry"))["entry"]
            await person.call("msg", to=sid, text="that one", kind="reply", reply_to=q["id"])
            await tl.call("msg", to=PERSON, text="second block", outcome="blocked", for_="m-entry")
            assert handed.outcome["was"]["text"] == "first block"
            await tl.call("msg", to=PERSON, text="done: TD-9", outcome="done", for_="m-entry")
            assert handed.outcome["was"]["text"] == "second block" and "was" not in handed.outcome["was"]
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_the_persons_reply_on_a_blocked_outcome_is_recorded_and_ends_its_row(agent, tmp_path):
    """§4.10 *`blocked` is not a dead end* (TD-1694): a reply to the question or to its outcome's note
    writes `replied` on every copy, a first one only; a reply elsewhere on the thread stamps nothing; a
    replied outcome raises no `blocked:` row."""
    async with LocalClient() as person:
        worker = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=worker) as w:
            q = await _answered(w, person, worker)
            note = (await w.call("msg", to=PERSON, text="waits on a key", outcome="blocked", for_=q["id"]))["entry"]
            assert f"blocked:{q['id']}" in agent._notify_rows()
            await person.call("msg", to=worker, text="what key?", kind="reply", reply_to=note["id"])
            first = _held(agent, q["id"]).outcome["replied"]
            assert first["by"] and _held(agent, q["id"]).outcome["state"] == "blocked"
            mine = next(e for e in agent.sessions[worker].outbox if e.id == q["id"])
            assert mine.outcome["replied"] == first, "on every copy"
            assert f"blocked:{q['id']}" not in agent._notify_rows()
            await person.call("msg", to=worker, text="again", kind="reply", reply_to=q["id"])
            assert _held(agent, q["id"]).outcome["replied"] == first, "a second reply leaves the first standing"
            # a reply to another entry on the thread stamps nothing
            q2 = await _answered(w, person, worker, "second")
            await w.call("msg", to=PERSON, text="waits", outcome="blocked", for_=q2["id"])
            other = (await w.call("msg", to=PERSON, text="fyi", kind="note", about="TD-1"))["entry"]
            await person.call("msg", to=worker, text="ok", kind="reply", reply_to=other["id"])
            assert "replied" not in _held(agent, q2["id"]).outcome
        await person.call("kill", id=worker)


@pytest.mark.integration
async def test_dismiss_tells_the_asker_of_an_unreplied_blocked_outcome_and_it_is_kept_until_then(agent, tmp_path):
    from datetime import UTC, datetime, timedelta

    async with LocalClient() as person:
        worker = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=worker) as w:
            q = await _answered(w, person, worker)
            await w.call("msg", to=PERSON, text="waits on a key", outcome="blocked", for_=q["id"])
            later = datetime.now(UTC) + timedelta(days=30)
            held, mine = _held(agent, q["id"]), next(e for e in agent.sessions[worker].outbox if e.id == q["id"])
            assert agent._keep(held, later, inbox=True, person=True) and agent._keep(mine, later, inbox=False)
            q2 = await _answered(w, person, worker, "second")
            note = (await w.call("msg", to=PERSON, text="waits", outcome="blocked", for_=q2["id"]))["entry"]
            await person.call("msg", to=worker, text="here", kind="reply", reply_to=note["id"])
            assert not agent._keep(_held(agent, q2["id"]), later, inbox=True, person=True), "replied: FYI's window"
            before = len(agent.sessions[worker].inbox)
            await person.call("inbox_dismiss", msg=[q["id"], q2["id"]])
            told = [e.text for e in agent.sessions[worker].inbox[before:] if e.from_ == "system"]
            assert told == [f"the person dismissed {q['id']}: they want nothing more on it"], "the replied one: silent"
            assert mine.outcome["state"] == "dismissed" and mine.outcome["was"]["state"] == "blocked"
        await person.call("kill", id=worker)


def test_the_thread_view_says_replied_and_was_blocked(monkeypatch, capsys):
    import argparse

    from shiftlead import cli

    got = {
        "id": "m-q",
        "root": "m-q",
        "entries": [
            {"id": "m-q", "from_role": "member", "from": "w", "to": ["person"], "kind": "ask", "at": "t",
             "text": "?", "outcome": {"state": "done", "was": {"state": "blocked", "text": "a key"}}},
            {"id": "m-r", "from_role": "member", "from": "w", "to": ["person"], "kind": "ask", "at": "t",
             "text": "?", "outcome": {"state": "blocked", "replied": {"at": "t", "by": "m-x"}}},
        ],
    }  # fmt: skip
    monkeypatch.setattr(cli, "call_sync", lambda *a, **k: got)
    cli._thread(argparse.Namespace(unread=False, sent=False, thread="m-q", json=False))
    out = capsys.readouterr().out
    assert "outcome: done · was blocked: a key" in out and "outcome: blocked · replied" in out


def test_a_replaced_blocked_outcomes_note_reads_after_the_answer_and_before_its_replacement():
    """TD-1734 (a): a thread's order puts a replaced `blocked` note (`was.by`) after the answer that closed
    the question and before the outcome that replaced it, even where `at` and the ids alone would put it first."""
    from sessionorc.agent_common import _oldest_first

    at = "2026-11-12T10:00:00Z"
    q = MailEntry(id="m-a", from_="w", to=[PERSON], at=at, kind="ask", text="rebase or merge?")
    note = MailEntry(id="m-b", from_="w", to=[PERSON], at=at, kind="note", text="waits on the vendor")
    answer = MailEntry(id="m-c", from_=PERSON, to=["w"], at=at, kind="reply", text="merge it", reply_to="m-a")
    done = MailEntry(id="m-d", from_="w", to=[PERSON], at=at, kind="note", text="done: #12")
    q.closed_by = "m-c"
    q.outcome = {"state": "done", "by": "m-d", "was": {"state": "blocked", "by": "m-b", "text": "waits on the vendor"}}
    found = {e.id: e for e in (q, note, answer, done)}
    assert [e.id for e in _oldest_first(found, [])] == ["m-a", "m-c", "m-b", "m-d"]


@pytest.mark.integration
async def test_a_replied_blocked_outcome_runs_fyis_window_from_the_reply(agent, tmp_path):
    """TD-1734 (b): a replied `blocked` outcome ages out of FYI on the retention window counted from
    `replied.at`, not from when the entry was read or closed."""
    from datetime import UTC, datetime

    from sessionorc import mail

    async with LocalClient() as person:
        worker = await _mk(person, tmp_path)("w", unattended=True)
        async with LocalClient(caller=worker) as w:
            q = await _answered(w, person, worker)
            note = (await w.call("msg", to=PERSON, text="waits on a key", outcome="blocked", for_=q["id"]))["entry"]
            await person.call("msg", to=worker, text="here", kind="reply", reply_to=note["id"])
            held = _held(agent, q["id"])
            later = datetime.now(UTC) + mail.MAIL_RETENTION * 2  # past the window from the read, whatever its length
            replied = later - mail.MAIL_RETENTION / 2
            held.outcome["replied"]["at"] = replied.strftime("%Y-%m-%dT%H:%M:%SZ")
            assert agent._keep(held, later, inbox=True, person=True), "inside the window from the reply"
            assert not agent._keep(held, later + mail.MAIL_RETENTION, inbox=True, person=True)
        await person.call("kill", id=worker)


@pytest.mark.integration
async def test_dismissing_a_handed_entrys_blocked_row_keeps_the_blocked_outcome_as_was(agent, tmp_path):
    """TD-1734 (c): the person's Dismiss of a handed entry's `blocked` row writes `dismissed` with the
    blocked outcome kept as `was`, and tells its holder."""
    async with LocalClient() as person:
        sid = await _mk(person, tmp_path)("tl", unattended=True)
        handed = MailEntry(id="m-entry", from_=PERSON, to=[sid], at="2026-11-12T10:00:00Z", kind="ask", text="fix it")
        handed.handed, handed.entry = True, {"repo": "shiftlead", "type": "debt"}
        agent.sessions[sid].inbox.append(handed)
        async with LocalClient(caller=sid) as tl:
            await tl.call("msg", to=PERSON, text="waits on the person's key", outcome="blocked", for_="m-entry")
        await person.call("inbox_dismiss", msg=["m-entry"])
        assert handed.outcome["state"] == "dismissed"
        assert (
            handed.outcome["was"]["state"] == "blocked" and handed.outcome["was"]["text"] == "waits on the person's key"
        )
        assert "was" not in handed.outcome["was"]
        told = [e.text for e in agent.sessions[sid].inbox if e.from_ == "system"]
        assert "the person dismissed m-entry: no outcome is owed on it" in told
        await person.call("kill", id=sid)
