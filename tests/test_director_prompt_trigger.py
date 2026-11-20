"""TD-642 slice 2, design §6 rule 3 and §4.9b *The director seat*: the `prompt` trigger. The org's director
seat is due while a prompt no rule answered is pending on an unattended supervised record of the org whose
adapter has a permission channel, filled once per prompt (`seat_filled`), also due by `asks`, never for an
interactive record's prompt, a question or its own; and with a director seat the manager on call's `pending`
cause stands aside for an unattended member — one judge, not two."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import reports
from sessionorc.agent_tick import filled_for
from sessionorc.client import LocalClient
from sessionorc.models import Pending

pytestmark = pytest.mark.integration

SHELL = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"], "unattended": True, "supervised": True}


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch):
    monkeypatch.setattr(reports, "merged_prs", lambda *a, **kw: None)


async def _make(person, tmp_path, name: str, **kw) -> str:
    (tmp_path / name).mkdir(exist_ok=True)
    params = {"name": name, "dir": str(tmp_path / name)}
    return (await person.call("create", **{**SHELL, **params, **kw}))["id"]


def _end(agent, sid: str) -> None:
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.exit_code = "exited", True, 0
    agent.store.save(rec)


def _ask(rec, what: str = "Bash(curl example.com)") -> None:
    rec.state, rec.confidence, rec.pending = "needs-you", "hook", Pending("permission", what)


def test_a_fill_for_a_prompt_names_the_member():
    assert filled_for({"by": "prompt", "member": "ao-x-w"}).endswith("prompt — ao-x-w")


async def test_the_director_is_filled_once_per_unanswered_prompt_of_an_unattended_record(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        d = await _make(person, tmp_path, "director", prompt="the director's brief", seat={"trigger": "prompt"})
        first = agent.sessions[d]
        _end(agent, d)
        w = await _make(person, tmp_path, "w")
        hand = await _make(person, tmp_path, "hand", unattended=False, supervised=False)
        rw, rh = agent.sessions[w], agent.sessions[hand]
        await agent._keep_running(now)
        assert agent.sessions[d] is first and first.seat_due is None, "no prompt pending, nothing due"
        # a question is a person's, an interactive session's permission is the person's, and so is its own
        rw.state, rw.confidence, rw.pending = "needs-you", "hook", Pending("question", "which?")
        _ask(rh)
        await agent._keep_running(now)
        assert agent.sessions[d] is first and first.seat_due is None
        # a screen guess is no reading: only the tool's own word fills a seat
        rw.state, rw.confidence, rw.pending = "needs-you", "screen", Pending("permission", "Bash(curl)")
        await agent._keep_running(now)
        assert agent.sessions[d] is first and first.seat_due is None
        # an unattended member's permission no rule answered fills it, naming the member
        _ask(rw)
        await agent._keep_running(now)
        second = agent.sessions[d]
        assert second is not first and first.seat_due == {**first.seat_due, "by": "prompt", "member": w}
        assert [(e["by"], e["member"]) for e in second.seat_filled] == [("prompt", w)]
        assert second.seat == {"trigger": "prompt"} and [r["why"] for r in second.restarts] == ["fill"]
        # it left the prompt and exited: the same standing prompt does not refill it
        _end(agent, d)
        await agent._keep_running(now + timedelta(minutes=3))
        assert agent.sessions[d] is second and second.seat_due is None
        # the prompt was answered: its entry goes, and a new prompt is a new cause
        rw.state, rw.pending = "working", None
        await agent._keep_running(now + timedelta(minutes=4))
        assert agent.sessions[d] is second and second.seat_filled == []
        _ask(rw, "Bash(curl example.org)")
        await agent._keep_running(now + timedelta(minutes=5))
        assert agent.sessions[d] is not second
        for sid in (w, hand, d):
            await person.call("kill", id=sid)


async def test_a_question_passed_up_to_the_director_is_due_before_a_prompt(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        d = await _make(person, tmp_path, "director", prompt="brief", seat={"trigger": "prompt"})
        w = await _make(person, tmp_path, "w")
        rd, rw = agent.sessions[d], agent.sessions[w]
        _ask(rw)
        rd.asks_ids = lambda **kw: ["m-1"]
        due = agent._seat_due(rd, datetime.now(UTC), [rd, rw])
        assert due["by"] == "asks" and due["ask"] == "m-1"
        assert agent._seat_done(rd) is True, "a seat with nothing due is done"
        rd.seat_due = due
        assert agent._seat_done(rd) is False, "a question waiting is the idle seat's own to read"
        rd.seat_due = {"at": "x", "by": "prompt", "member": w}
        assert agent._seat_done(rd) is True, "a prompt is read by a fill, which starts cold on it"
        for sid in (w, d):
            await person.call("kill", id=sid)


async def test_with_a_director_the_manager_leaves_an_unattended_members_prompt(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        mgr = await _make(person, tmp_path, "mgr", prompt="brief", seat={"trigger": "team"})
        w = await _make(person, tmp_path, "w", controllers=[mgr])
        rm, rw = agent.sessions[mgr], agent.sessions[w]
        _ask(rw)
        assert [c["by"] for c in agent._team_causes(rm, [rm, rw])] == ["pending"], "no director: the manager's"
        d = await _make(person, tmp_path, "director", prompt="brief", seat={"trigger": "prompt"})
        rd = agent.sessions[d]
        assert agent._team_causes(rm, [rm, rw, rd]) == [], "a director: one judge, not two"
        assert [c["by"] for c in agent._prompt_causes(rd, [rm, rw, rd])] == ["prompt"]
        # an interactive member's permission stays the manager's: the director never answers one
        h = await _make(person, tmp_path, "h", controllers=[mgr], unattended=False)
        rh = agent.sessions[h]
        _ask(rh)
        assert [c["member"] for c in agent._team_causes(rm, [rm, rw, rh, rd])] == [h]
        assert [c["member"] for c in agent._prompt_causes(rd, [rm, rw, rh, rd])] == [w]
        # a director that cannot be filled is passed by, and the manager reads its member again
        agent.unfillable[d] = "fill ceiling"
        assert [c["member"] for c in agent._team_causes(rm, [rm, rw, rd])] == [w]
        agent.unfillable.pop(d)
        rd.suspended = {"at": "x", "by": "person"}
        assert [c["by"] for c in agent._team_causes(rm, [rm, rw, rd])] == ["pending"]
        await person.call("kill", id=h)
        for sid in (w, mgr, d):
            await person.call("kill", id=sid)


async def test_a_second_prompt_raised_before_a_tick_saw_the_first_answered_fills_the_director_afresh(agent, tmp_path):
    """The techlead's note on #4264: a prompt is a cause by its own id (§6 rule 3), so a member that answered one
    prompt and raised the next between two ticks is not left on the first fill's `seat_filled` entry."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        d = await _make(person, tmp_path, "director", prompt="brief", seat={"trigger": "prompt"})
        _end(agent, d)
        w = await _make(person, tmp_path, "w")
        rw = agent.sessions[w]
        rw.state, rw.confidence = "needs-you", "hook"
        rw.pending = Pending("permission", "Bash(curl example.com)", tool_use_id="toolu_1")
        ended = agent.sessions[d]
        await agent._keep_running(now)
        first = agent.sessions[d]
        assert first is not ended and ended.seat_due["prompt"] == "toolu_1"
        assert [(e["member"], e["prompt"]) for e in first.seat_filled] == [(w, "toolu_1")]
        _end(agent, d)
        # the director answered it and the member asked again before any tick read it working
        rw.pending = Pending("permission", "Bash(curl example.com)", tool_use_id="toolu_2")
        await agent._keep_running(now + timedelta(minutes=1))
        second = agent.sessions[d]
        assert second is not first, "the new prompt fills the director afresh"
        assert [(e["member"], e["prompt"]) for e in second.seat_filled] == [(w, "toolu_2")]
        # with no tool_use_id the prompt's text is its id: the same text standing fills nothing more
        _end(agent, d)
        rw.pending = Pending("permission", "Bash(ls)")
        await agent._keep_running(now + timedelta(minutes=2))
        third = agent.sessions[d]
        assert third is not second and [e["prompt"] for e in third.seat_filled] == ["Bash(ls)"]
        _end(agent, d)
        await agent._keep_running(now + timedelta(minutes=3))
        assert agent.sessions[d] is third and third.seat_due is None
        for sid in (w, d):
            await person.call("kill", id=sid)


async def test_a_prompt_under_another_keeps_its_own_fill(agent, tmp_path):
    """Each open permission on a member's stack is a cause of its own (§6 rule 3): two parallel calls fill the
    director once each, and the first coming back to the top after the second is answered fills nothing more."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        d = await _make(person, tmp_path, "director", prompt="brief", seat={"trigger": "prompt"})
        _end(agent, d)
        w = await _make(person, tmp_path, "w")
        rw = agent.sessions[w]
        a = Pending("permission", "Bash(curl a)", tool_use_id="toolu_a")
        b = Pending("permission", "Bash(curl b)", tool_use_id="toolu_b")
        rw.state, rw.confidence, rw.pending, rw.pendings = "needs-you", "hook", a, [a]
        await agent._keep_running(now)
        first = agent.sessions[d]
        _end(agent, d)
        rw.pending, rw.pendings = b, [a, b]
        await agent._keep_running(now + timedelta(minutes=1))
        second = agent.sessions[d]
        assert second is not first
        assert sorted(e["prompt"] for e in second.seat_filled) == ["toolu_a", "toolu_b"]
        _end(agent, d)
        rw.pending, rw.pendings = a, [a]
        await agent._keep_running(now + timedelta(minutes=2))
        assert agent.sessions[d] is second and [e["prompt"] for e in second.seat_filled] == ["toolu_a"]
        for sid in (w, d):
            await person.call("kill", id=sid)
