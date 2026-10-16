"""TD-720 slice 2, design §4.1 *A launch whose hook never comes is recovered* and §6 rule 1 *A lost brief*
(TD-717): a supervised record marked *no hook since launch*, a seat included, is closed by the tick and
replayed once, `why: lost-brief`, its mail kept and each sender of an open `ask` or `steer` told; a
second loss is not replayed and is the person's (*brief lost twice*); a person's own session is left to
its cure, a send."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import agent_common, paths
from sessionorc.agent import RESTART_SETTLE
from sessionorc.agent_tick import FILLED_FOR
from sessionorc.client import LocalClient
from sessionorc.models import SYSTEM, MailEntry
from shiftlead.ui import cards, inbox

pytestmark = pytest.mark.integration


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


async def _create(person, tmp_path, name: str, **kw) -> str:
    (tmp_path / name).mkdir()
    return (
        await person.call(
            "create", name=name, dir=str(tmp_path / name), adapter="shell", argv=["bash", "--norc", "--noprofile"],
            unattended=True, **kw,
        )
    )["id"]  # fmt: skip


def _lose(agent, sid: str) -> None:
    """What `_send_first_prompts` writes at `FIRST_PROMPT_BOUND` on a launch no hook reached (§4.1)."""
    rec = agent.sessions[sid]
    rec.state, rec.first_prompt_error = "working", agent_common.FIRST_PROMPT_NO_HOOK
    agent.store.save(rec)


def _system(agent, sid: str) -> list[str]:
    return [e.text for e in agent.sessions[sid].inbox if e.from_ == SYSTEM]


async def test_a_marked_member_is_replayed_once_its_ask_moved_and_its_sender_told(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        asker = await _create(person, tmp_path, "asker")
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief", lane=["TD-1"])
        old = agent.sessions[sid]
        now = datetime.now(UTC)
        old.inbox.append(MailEntry(id="m-a1", from_=asker, to=[sid], at=_iso(now), kind="ask", text="read #7", pr=7))
        old.inbox.append(MailEntry(id="m-n1", from_=asker, to=[sid], at=_iso(now), kind="note", text="fyi"))
        _lose(agent, sid)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not old, "closed and replayed in place under its name"
        assert (old.closer["by"], old.closer["why"], old.closed_for["why"]) == ("tick", "lost-brief", "lost-brief")
        assert [r["why"] for r in new.restarts] == ["lost-brief"] and "error" not in new.restarts[0]
        assert new.first_prompt_error is None
        assert [e.id for e in new.inbox] == ["m-a1", "m-n1"], "the mail moves with the replay"
        told = _system(agent, asker)
        assert len(told) == 1 and told[0].startswith("the brief of w was lost at its launch; it was relaunched at ")
        assert told[0].endswith("and reads your ask now")
        # counted in RESTART_CEILING as every replay is
        assert len(agent_common._counted(new.restarts, now)) == 1
        await person.call("kill", id=sid)


async def test_a_second_loss_is_not_replayed_and_reads_brief_lost_twice(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        asker = await _create(person, tmp_path, "g")
        sid = await _create(
            person, tmp_path, "tl", supervised=True, prompt="the seat's brief", seat={"trigger": "asks"}
        )
        now = datetime.now(UTC)
        ask = MailEntry(id="m-a1", from_=asker, to=[sid], at=_iso(now), kind="ask", text="read #7", pr=7)
        agent.sessions[sid].inbox.append(ask)
        _lose(agent, sid)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert [r["why"] for r in new.restarts] == ["lost-brief"], "the closed seat, its ask open, is not filled too"
        assert [e.id for e in new.inbox] == ["m-a1"] and len(_system(agent, asker)) == 1
        _lose(agent, sid)
        later = now + RESTART_SETTLE + timedelta(seconds=1)
        await agent._keep_running(later)
        assert agent.sessions[sid] is new and not new.superseded_by, "a second loss is not replayed"
        assert new.restart_ceiling["why"] == "lost-brief" and new.restart_ceiling["count"] == 1
        assert new.first_prompt_error == agent_common.FIRST_PROMPT_NO_HOOK, "the mark stays"
        view = await person.call("get", id=sid)
        at, words = inbox.restart_mark(view)
        assert at == new.restart_ceiling["at"] and words.startswith("brief lost twice") and "1" not in words
        new.first_prompt_error, new.state, new.pane = None, "exited", False  # ended: the ceiling's words are the card's
        slot = cards.view(await person.call("get", id=sid))["slot"]
        assert slot["text"] == "brief lost twice" and "fills exhausted" not in slot["full"]
        # the ceiling is no fill's: a fellow seat's fill ceiling does not read it as tripped
        await agent._keep_running(later + timedelta(seconds=1))
        assert agent.sessions[sid] is new
        await person.call("kill", id=sid)


async def test_a_seats_replay_repeats_its_fills_context(agent, tmp_path):
    """The fill's *why it came* line, kept in the launch record's prompt, and `seat_filled`, as rule 3's
    fill wrote them; `lost-brief` is not a fill, so the fill ceiling does not count it."""
    await park_ticks(agent)
    line = f"{FILLED_FOR}asks — m-q1"
    async with LocalClient() as person:
        asker = await _create(person, tmp_path, "asker")
        sid = await _create(
            person, tmp_path, "mgr", supervised=True, prompt=f"the seat's brief\n\n{line}", seat={"trigger": "team"}
        )
        old = agent.sessions[sid]
        filled = [{"by": "asks", "ask": "m-q1", "at": _iso(datetime.now(UTC))}]
        old.seat_filled = list(filled)
        # the question it was filled for, still open: due again the moment the seat is closed
        old.inbox.append(MailEntry(id="m-q1", from_=asker, to=[sid], at=filled[0]["at"], kind="ask", text="why?"))
        _lose(agent, sid)
        await agent._keep_running(datetime.now(UTC))
        new = agent.sessions[sid]
        assert new is not old and [r["why"] for r in new.restarts] == ["lost-brief"]
        assert new.seat_filled == filled
        assert [r["why"] for r in agent.sessions[sid].restarts] == ["lost-brief"], "the closed seat is not filled too"
        launch = json.loads((paths.launch_dir() / f"{sid}.json").read_text())
        assert launch["prompt"] == f"the seat's brief\n\n{line}", "the line once, never stripped nor doubled"
        assert [e for e in new.restarts if e.get("why") == "fill"] == []
        await person.call("kill", id=sid)


async def test_what_the_lost_brief_replay_leaves_alone(agent, tmp_path):
    """A person's own session (unsupervised) is left to its cure; so is an interactive one, and a
    supervised record whose brief failed for another reason (the composer did not take it)."""
    await park_ticks(agent)
    async with LocalClient() as person:
        own = await _create(person, tmp_path, "own", prompt="the brief")
        ia = await _create(person, tmp_path, "ia", supervised=True, prompt="the brief")
        other = await _create(person, tmp_path, "o", supervised=True, prompt="the brief")
        for sid in (own, ia):
            _lose(agent, sid)
        agent.sessions[ia].unattended = False
        agent.sessions[other].first_prompt_error = "prompt-stuck: the composer kept it"
        recs = {sid: agent.sessions[sid] for sid in (own, ia, other)}
        await agent._keep_running(datetime.now(UTC))
        for sid, rec in recs.items():
            assert agent.sessions[sid] is rec and rec.restarts == [] and rec.state != "closed", sid
        for sid in recs:
            await person.call("kill", id=sid)


# -- TD-732: the guards, the ceiling, the senders told and the failed close, each held by a test ----------


@pytest.mark.parametrize(
    "why",
    ["wrapup_at", "wrapup_sent_at", "suspended", "sit_out", "run_until", "gated", "exited"],
)
async def test_a_marked_record_the_replay_must_not_touch_is_left_as_it_is(agent, tmp_path, why):
    """Wound down, suspended, sat out, past its stop time, gated or already ended: no relaunch and no
    ceiling — each is another rule's, or the person's."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief")
        _lose(agent, sid)
        rec, now = agent.sessions[sid], datetime.now(UTC)
        if why == "run_until":
            rec.run_until = _iso(now - timedelta(minutes=1))
        elif why == "exited":
            rec.state = "exited"
        elif why in ("wrapup_at", "wrapup_sent_at"):
            setattr(rec, why, _iso(now))
        else:
            setattr(rec, why, {"at": _iso(now), "by": "person", "why": "test"})
        assert await agent._lost_brief(rec, now) is False
        assert agent.sessions[sid] is rec and rec.restarts == [] and rec.restart_ceiling is None
        assert rec.state != "closed" and rec.closer is None
        await person.call("kill", id=sid)


async def test_restart_ceiling_replays_in_the_window_stop_the_replay_with_no_why(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief")
        _lose(agent, sid)
        rec, now = agent.sessions[sid], datetime.now(UTC)
        rec.restarts = [{"at": _iso(now - timedelta(minutes=i + 1)), "why": "crash"} for i in range(3)]
        assert await agent._lost_brief(rec, now) is False
        assert agent.sessions[sid] is rec and rec.state != "closed"
        assert rec.restart_ceiling["count"] == 3 and "why" not in rec.restart_ceiling, "the ceiling's, not a loss's"
        await person.call("kill", id=sid)


async def test_a_failed_lost_brief_entry_is_no_second_loss(agent, tmp_path):
    """A `lost-brief` entry carrying `error` (its close failed, the record not closed) is retried, not read
    as *brief lost twice*."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief")
        _lose(agent, sid)
        rec, now = agent.sessions[sid], datetime.now(UTC)
        rec.restarts = [{"at": _iso(now), "why": "lost-brief", "error": "close: boom"}]
        assert await agent._lost_brief(rec, now) is True
        new = agent.sessions[sid]
        assert new is not rec and new.restart_ceiling is None
        assert [r["why"] for r in new.restarts] == ["lost-brief", "lost-brief"]
        await person.call("kill", id=sid)


async def test_each_open_asker_is_told_once_and_the_person_and_the_system_never(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        a = await _create(person, tmp_path, "a")
        b = await _create(person, tmp_path, "b")
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief")
        rec, now = agent.sessions[sid], datetime.now(UTC)
        at = _iso(now)
        rec.inbox += [
            MailEntry(id="m-1", from_=a, to=[sid], at=at, kind="ask", text="one"),
            MailEntry(id="m-2", from_=a, to=[sid], at=at, kind="steer", text="two", default="go"),
            MailEntry(id="m-3", from_="person", to=[sid], at=at, kind="ask", text="the person's"),
            MailEntry(id="m-4", from_=SYSTEM, to=[sid], at=at, kind="ask", text="the system's"),
            MailEntry(id="m-5", from_=b, to=[sid], at=at, kind="ask", text="answered", closed_reason="replied"),
            MailEntry(id="m-6", from_=b, to=[sid], at=at, kind="note", text="a note asks nothing"),
        ]
        _lose(agent, sid)
        told: list[str] = []
        monkeypatch.setattr(agent, "_system_note", lambda to, text, **kw: told.append(to))
        assert await agent._lost_brief(rec, now) is True
        assert told == [a], "one note for two open asks; none to the person, the system or a closed ask's sender"
        await person.call("kill", id=sid)


async def test_a_close_that_fails_is_a_failed_replay_and_the_next_tick_replays(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief")
        _lose(agent, sid)
        rec, now = agent.sessions[sid], datetime.now(UTC)
        real, closes = agent.rpc_close, []

        async def refused(id, **kw):
            closes.append(id)
            raise RuntimeError("boom")

        monkeypatch.setattr(agent, "rpc_close", refused)
        assert await agent._lost_brief(rec, now) is False, "nothing closed: the pass goes on"
        assert rec.state != "closed" and rec.closed_for is None
        assert [(r["why"], r["error"]) for r in rec.restarts] == [("lost-brief", "close: boom")]
        monkeypatch.setattr(agent, "rpc_close", real)
        assert await agent._lost_brief(rec, now + timedelta(seconds=1)) is True
        new = agent.sessions[sid]
        assert new is not rec and [r["why"] for r in new.restarts] == ["lost-brief", "lost-brief"]
        assert new.restart_ceiling is None
        await person.call("kill", id=sid)


async def test_a_close_that_closed_then_failed_is_replayed_next_tick_without_a_second_close(
    agent, tmp_path, monkeypatch
):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w", supervised=True, prompt="the brief")
        _lose(agent, sid)
        rec, now = agent.sessions[sid], datetime.now(UTC)
        real, closes = agent.rpc_close, []

        async def closed_then_failed(id, **kw):
            closes.append(id)
            await real(id, **kw)
            raise RuntimeError("after the close")

        monkeypatch.setattr(agent, "rpc_close", closed_then_failed)
        assert await agent._lost_brief(rec, now) is True, "closed: the rest of the pass leaves it"
        assert rec.state == "closed" and rec.closed_for["why"] == "lost-brief"
        assert [r.get("error") for r in rec.restarts] == ["close: after the close"]
        assert await agent._lost_brief(rec, now + timedelta(seconds=1)) is True
        new = agent.sessions[sid]
        assert closes == [sid], "the retry replays the closed run without closing it again"
        assert new is not rec and [r["why"] for r in new.restarts] == ["lost-brief", "lost-brief"]
        await person.call("kill", id=sid)


async def test_two_records_marked_in_one_tick_are_each_replayed_once(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        ids = [await _create(person, tmp_path, n, supervised=True, prompt="the brief") for n in ("w1", "w2")]
        olds = {sid: agent.sessions[sid] for sid in ids}
        for sid in ids:
            _lose(agent, sid)
        await agent._keep_running(datetime.now(UTC))
        for sid in ids:
            new = agent.sessions[sid]
            assert new is not olds[sid] and [r["why"] for r in new.restarts] == ["lost-brief"], sid
        for sid in ids:
            await person.call("kill", id=sid)


async def test_the_closed_run_is_left_by_the_rest_of_the_pass(agent, tmp_path):
    """A seat still due when its brief was lost (an `every` seat keeps its `seat_due`) is replayed, and
    the rest of the tick's pass leaves its closed run alone: no fill on top of the replay."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(
            person, tmp_path, "lead", supervised=True, prompt="the brief", seat={"trigger": "every", "after": "1h"}
        )
        rec, now = agent.sessions[sid], datetime.now(UTC)
        rec.seat_due = {"at": _iso(now), "by": "every"}
        _lose(agent, sid)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not rec and [r["why"] for r in new.restarts] == ["lost-brief"]
        assert rec.restarts == [], "the closed run is not filled on top of its replay"
        await person.call("kill", id=sid)
