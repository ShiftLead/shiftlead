"""A live extra past a lowered `max` (design §4.9 *Scaling with the work*, td-max; TD-1545): `relaunch` `drop_extra`
sends it the wrap-up and marks `scale.drop`; the tick closes it once settled, drops its claims in progress *extra
closed* and forgets the record — never a sit-out, never a kill. One with unread mail is closed and kept."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import work
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import SYSTEM, WRAPUP_PROMPT, MailEntry, ProgressEntry

AGENT = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"]}  # the wrap-up is typed into an agent


def _idle(rec) -> None:
    rec.state, rec.confidence, rec.pending = "idle", "hook", None
    rec.git = {"dirty": 0, "unpushed": 0}


async def _extra(person, agent, tmp_path, name="grind-3"):
    (tmp_path / name).mkdir()
    sid = (
        await person.call(
            "create", name=name, dir=str(tmp_path / name), unattended=True, supervised=True, prompt="p", **AGENT
        )
    )["id"]
    rec = agent.sessions[sid]
    rec.scale = {"line": "grind"}
    return sid, rec


@pytest.mark.integration
async def test_a_live_extra_is_wound_down_and_forgotten_once_closed_its_claims_dropped(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _extra(person, agent, tmp_path)
        rec.progress = [ProgressEntry(ref="TD-9"), ProgressEntry(ref="TD-8", status="done", pr=3)]
        view = await person.call("relaunch", id=sid, drop_extra=True)
        assert view["scale"]["line"] == "grind" and view["scale"]["drop"]
        assert rec.wrapup_at and rec.sends[-1].text == WRAPUP_PROMPT and rec.sit_out is None  # never a sit-out
        again = await person.call("relaunch", id=sid, drop_extra=True)  # said twice: nothing more is sent
        assert again["scale"] == view["scale"] and len(rec.sends) == 1
        # settled with work left: it stays open, tick after tick
        _idle(rec)
        rec.git = {"dirty": 1, "unpushed": 0}
        now = datetime.now(UTC)
        await agent._keep_running(now)
        assert agent.sessions.get(sid) is rec and rec.state == "idle"
        # pushed: closed, its claim in progress dropped, and forgotten
        rec.git = {"dirty": 0, "unpushed": 0}
        await agent._keep_running(now + timedelta(seconds=1))
        assert sid not in agent.sessions
        assert [(e.ref, e.status, e.why) for e in rec.progress] == [
            ("TD-9", "dropped", "extra closed"),
            ("TD-8", "done", None),
        ]
        assert not work.sat_out(rec)


@pytest.mark.integration
async def test_an_extra_with_unread_mail_is_closed_and_kept(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _extra(person, agent, tmp_path)
        rec.inbox.append(MailEntry(id="m-1", from_=SYSTEM, to=[sid], at="2026-11-11T08:00:00Z", kind="note", text="x"))
        await person.call("relaunch", id=sid, drop_extra=True)
        _idle(rec)
        await agent._keep_running(datetime.now(UTC))
        assert agent.sessions.get(sid) is rec and rec.state == "closed" and rec.scale["drop"]  # its mail waits
        rec.inbox[0].read_at = "2026-11-11T08:05:00Z"
        await agent._keep_running(datetime.now(UTC) + timedelta(seconds=1))
        assert sid not in agent.sessions  # read: forgotten at the next tick


@pytest.mark.integration
async def test_drop_extra_is_refused_touching_nothing(agent, tmp_path):
    from sessionorc.models import Pending

    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _extra(person, agent, tmp_path)
        (tmp_path / "plain").mkdir()
        plain = (
            await person.call("create", name="plain", dir=str(tmp_path / "plain"), unattended=True, prompt="p", **AGENT)
        )["id"]
        with pytest.raises(AgentError, match="is no extra"):
            await person.call("relaunch", id=plain, drop_extra=True)
        with pytest.raises(AgentError, match="takes nothing else"):
            await person.call("relaunch", id=sid, drop_extra=True, sit_out=True)
        rec.pending = Pending(kind="question", text="q")
        with pytest.raises(AgentError, match="the wrap-up could not be sent"):
            await person.call("relaunch", id=sid, drop_extra=True)
        assert "drop" not in rec.scale and not rec.sends
        rec.pending = None
        for x in (sid, plain):
            with contextlib.suppress(Exception):
                await person.call("kill", id=x)
