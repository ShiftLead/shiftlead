"""A live extra past a lowered `max` (design §4.9 *Scaling with the work*, td-max; TD-1545): `relaunch` `drop_extra`
sends it the wrap-up and marks `scale.drop`; the tick closes it once settled, drops its claims in progress *extra
closed* and forgets the record — never a sit-out, never a kill. One with unread mail is closed and kept."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import paths, work
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


@pytest.mark.integration
async def test_a_dropped_extra_is_never_restarted_by_rule_1_or_2(agent, tmp_path):
    """Review of slice 13: rule 2's `restart_wanted`, and an exit the wrap-up never reached, restart nothing."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _extra(person, agent, tmp_path)
        rec.restart_wanted = {"at": "2026-11-11T08:00:00Z", "why": "context bound"}
        await person.call("relaunch", id=sid, drop_extra=True)
        _idle(rec)
        await agent._keep_running(datetime.now(UTC))
        assert sid not in agent.sessions and rec.restarts == []  # dropped, never replayed
        other, ex = await _extra(person, agent, tmp_path, "grind-4")
        await person.call("relaunch", id=other, drop_extra=True)
        ex.state, ex.pane, ex.exit_code, ex.wrapup_at = "exited", True, 1, None  # crashed before the wrap-up
        ex.git = {"dirty": 2, "unpushed": 0}
        await agent._keep_running(datetime.now(UTC) + timedelta(seconds=1))
        assert agent.sessions.get(other) is ex and ex.state == "exited" and ex.restarts == []  # work left: kept
        ex.git = {"dirty": 0, "unpushed": 0}
        await agent._keep_running(datetime.now(UTC) + timedelta(seconds=2))
        assert other not in agent.sessions and ex.restarts == []


# ── the guards (TD-1620) and a resumed extra's mark (TD-1619): each fails with its line reverted ─────────────


@pytest.mark.integration
async def test_drop_extra_refuses_an_interactive_a_superseded_and_a_nodes_record_unmarked(agent, tmp_path):
    """`_drop_extra`'s three refusals: a team act never stops a person's session, a resumed record's successor is
    the one to drop, and an extra is dropped at the host it runs on — each touching nothing."""
    await park_ticks(agent)
    async with LocalClient() as person:
        (tmp_path / "mine").mkdir()
        mine = (await person.call("create", name="mine", dir=str(tmp_path / "mine"), prompt="p", **AGENT))["id"]
        agent.sessions[mine].scale = {"line": "grind"}
        with pytest.raises(AgentError, match="is interactive: a team act never stops a person's session"):
            await person.call("relaunch", id=mine, drop_extra=True)
        sid, rec = await _extra(person, agent, tmp_path)
        rec.superseded_by = "ao-x-grind-3b"
        with pytest.raises(AgentError, match="was resumed as ao-x-grind-3b: that is the record to drop"):
            await person.call("relaunch", id=sid, drop_extra=True)
        rec.superseded_by, home = None, rec.host
        rec.host = "laptop"
        with pytest.raises(AgentError, match="runs on laptop: an extra is dropped at the host it runs on"):
            await person.call("relaunch", id=sid, drop_extra=True)
        rec.host = home
        for r in (rec, agent.sessions[mine]):
            assert "drop" not in r.scale and not r.wrapup_at
        assert not rec.sends and not agent.sessions[mine].sends
        for x in (sid, mine):
            with contextlib.suppress(Exception):
                await person.call("kill", id=x)


@pytest.mark.integration
async def test_the_tick_leaves_a_marked_record_of_another_host_or_superseded_alone(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _extra(person, agent, tmp_path)
        _idle(rec)
        rec.scale = {"line": "grind", "drop": "2026-11-11T08:00:00Z"}
        rec.progress = [ProgressEntry(ref="TD-9")]
        home = rec.host
        rec.host = "laptop"
        assert await agent._extra_drop(rec) is False
        rec.host, rec.superseded_by = home, "ao-x-grind-3b"
        assert await agent._extra_drop(rec) is False
        assert agent.sessions.get(sid) is rec and rec.state == "idle" and rec.progress[0].status == "claimed"
        rec.superseded_by = None
        with contextlib.suppress(Exception):
            await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_dropped_extra_whose_forget_fails_is_kept_marked_and_saved(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _extra(person, agent, tmp_path)
        await person.call("kill", id=sid)
        rec.scale = {"line": "grind", "drop": "2026-11-11T08:00:00Z"}
        rec.git = {"dirty": 0, "unpushed": 0}
        rec.progress = [ProgressEntry(ref="TD-9")]

        async def refuse(_id, *a, **k):
            raise RuntimeError("suspended")

        saved = []
        real = agent._save
        monkeypatch.setattr(agent, "rpc_remove", refuse)
        monkeypatch.setattr(agent, "_save", lambda s, *a, **k: (saved.append(s.id), real(s, *a, **k))[1])
        assert await agent._extra_drop(rec) is True
        assert agent.sessions.get(sid) is rec and rec.scale["drop"]  # kept, the mark standing: tried next tick
        assert sid in saved  # the claim it dropped is written, not lost with the process
        assert (rec.progress[0].status, rec.progress[0].why) == ("dropped", "extra closed")


@pytest.mark.integration
async def test_a_resumed_extra_carries_its_line_alone_never_the_runs_drop_mark(agent, hookstub, tmp_path):
    """TD-1619: a person's Resume of a dropped extra is a new run, so its record and launch record carry
    `{line}` alone; the mark carried, the next tick would close and forget what the person just resumed."""
    await park_ticks(agent)
    async with LocalClient() as person:
        old = await person.call(
            "create", name="g-4", dir=str(tmp_path), adapter="hookstub", unattended=True, supervised=True,
            scale={"line": "g"},
        )  # fmt: skip
        await person.call("hook", session=old["id"], adapter_id="cc-extra")
        agent.sessions[old["id"]].scale = {"line": "g", "drop": "2026-11-11T08:00:00Z"}
        await person.call("kill", id=old["id"])
        new = await person.call("create", name="g-4", dir=str(tmp_path), adapter="hookstub", resume="cc-extra")
        assert new["scale"] == {"line": "g"}
        assert json.loads((paths.launch_dir() / f"{new['id']}.json").read_text())["scale"] == {"line": "g"}
        await person.call("kill", id=new["id"])


async def test_a_nodes_resumed_extra_launch_record_carries_its_line_alone(agent):
    """TD-1619, the node's road: the replica the node made carries its old run's `drop`; the home's launch
    record takes `{line}` alone, so a replay never brings back a run's mark."""
    from test_link import record
    from test_td_max_readings import _Node

    await park_ticks(agent)
    marked = {"line": "g", "drop": "2026-11-11T08:00:00Z"}
    agent._link_muxes["laptop"] = _Node(record(name="g-4", supervised=True, unattended=True, scale=marked))
    try:
        await agent._route_act("create", {"name": "g-4", "dir": "/tmp/x", "resume": "cc-extra"}, None, "laptop")
        made = json.loads((paths.launch_dir() / "ao-x-w@laptop.json").read_text())
        assert made["scale"] == {"line": "g"}
    finally:
        del agent._link_muxes["laptop"]
