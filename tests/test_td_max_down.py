"""Rule 14's down half (design §6 rule 14 *Scale with the work*; td-max, TD-1546 slice 2): a worker extra that
declares out of work is closed back to held at the first tick it is clean — no idle timer — its claims not `done`
dropped *extra closed*; an open PR of its own (one handed to a reader included) or unread mail holds it open with
no bound; one `exited` after declaring is held, never restarted; a kept member's declaration is not rule 14's."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import work
from sessionorc.client import LocalClient
from sessionorc.models import SYSTEM, MailEntry, ProgressEntry, now_iso

pytestmark = pytest.mark.integration

AGENT = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"]}


def _idle(rec, dirty: int = 0) -> None:
    rec.state, rec.confidence, rec.pending = "idle", "hook", None
    rec.git = {"dirty": dirty, "unpushed": 0}


async def _rec(person, agent, tmp_path, name: str, scale: bool = True):
    (tmp_path / name).mkdir()
    sid = (
        await person.call(
            "create", name=name, dir=str(tmp_path / name), unattended=True, supervised=True, prompt="p", **AGENT
        )
    )["id"]
    rec = agent.sessions[sid]
    if scale:
        rec.scale = {"line": "grind"}
    return sid, rec


def _out(rec) -> None:
    rec.out_of_work = {"at": now_iso(), "why": "nothing pickable"}


async def test_an_out_of_work_extra_is_back_to_held_at_the_first_clean_tick_its_kept_sibling_runs_on(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        kid, kept = await _rec(person, agent, tmp_path, "grind-1", scale=False)
        sid, rec = await _rec(person, agent, tmp_path, "grind-3")
        rec.progress = [ProgressEntry(ref="TD-9", status="claimed"), ProgressEntry(ref="TD-8", status="done", pr=3)]
        _idle(kept)
        _idle(rec, dirty=1)
        _out(rec)
        _out(kept)
        now = datetime.now(UTC)
        await agent._keep_running(now)
        assert rec.state == "idle", "work left: open, with no bound"
        _idle(rec)
        await agent._keep_running(now + timedelta(seconds=1))
        assert rec.state == "closed" and agent.sessions.get(sid) is rec, "held: the record stays, with its scale"
        assert work.held_extra(rec) and not work.sat_out(rec)
        assert rec.scale["line"] == "grind"
        assert rec.scale["last"]["did"] == "hold" and rec.scale["last"]["why"] == "back to held: out of work"
        assert [(e.ref, e.status, e.why) for e in rec.progress] == [
            ("TD-9", "dropped", "extra closed"),
            ("TD-8", "done", None),
        ]
        assert kept.state == "idle", "a kept member's declaration is not rule 14's"
        assert await agent._scale_down(kept, now) is False


async def test_an_open_pr_of_its_own_or_unread_mail_holds_it_open(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _rec(person, agent, tmp_path, "grind-3")
        rec.progress = [ProgressEntry(ref="TD-9", status="claimed", review_pr=3383)]  # handed to its reader
        _idle(rec)
        _out(rec)
        now = datetime.now(UTC)
        for k in range(3):  # no bound: tick after tick, and the rest of the pass reaches it
            assert await agent._scale_down(rec, now + timedelta(hours=k * 3)) is False
            assert rec.state == "idle"
        # the PR merged: the claim reads done, and the reader's reply waits unread
        rec.progress[0].status = "done"
        rec.inbox.append(MailEntry(id="m-1", from_=SYSTEM, to=[sid], at=now_iso(), kind="reply", text="merged"))
        assert await agent._scale_down(rec, now) is False
        assert rec.state == "idle", "the reply reaches the live record holding the work's context"
        rec.inbox[-1].read_at = now_iso()
        assert await agent._scale_down(rec, now) is True
        assert rec.state == "closed"
        assert rec.progress[0].status == "done", "a done claim is never dropped"


async def test_an_extra_exited_after_declaring_is_held_and_never_restarted(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _rec(person, agent, tmp_path, "grind-3")
        rec.progress = [ProgressEntry(ref="TD-9", status="claimed")]
        _out(rec)
        rec.state, rec.pane, rec.git = "exited", True, {"dirty": 0, "unpushed": 0}
        now = datetime.now(UTC)
        await agent._keep_running(now)
        assert agent.sessions.get(sid) is rec and not rec.superseded_by and not rec.restarts, "never restarted"
        assert rec.scale["last"]["why"] == "back to held: out of work"
        assert rec.progress[0].why == "extra closed"
        rec.scale = {**rec.scale, "last": {**rec.scale["last"], "why": "seen"}}
        await agent._keep_running(now + timedelta(seconds=5))
        assert rec.scale["last"]["why"] == "seen", "written once for its declaration"


async def test_a_held_extra_with_no_declaration_is_left_to_the_fill(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        _, rec = await _rec(person, agent, tmp_path, "grind-3")
        _idle(rec)
        assert await agent._scale_down(rec, datetime.now(UTC)) is False
        rec.scale = {**rec.scale, "drop": True}
        _out(rec)
        assert await agent._scale_down(rec, datetime.now(UTC)) is False, "a dropped extra is _extra_drop's"


async def test_a_live_subagent_holds_it_open(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        _, rec = await _rec(person, agent, tmp_path, "grind-3")
        _idle(rec)
        _out(rec)
        rec.subagents, rec.subagent_at = 1, now_iso()
        assert await agent._scale_down(rec, datetime.now(UTC)) is False and rec.state == "idle"
        rec.subagents = 0
        assert await agent._scale_down(rec, datetime.now(UTC)) is True and rec.state == "closed"


async def test_an_extra_exited_with_work_left_is_kept_as_it_stands(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _rec(person, agent, tmp_path, "grind-3")
        rec.progress = [ProgressEntry(ref="TD-9", status="claimed")]
        _out(rec)
        rec.state, rec.pane, rec.git = "exited", True, {"dirty": 2, "unpushed": 0}
        await agent._keep_running(datetime.now(UTC))
        assert agent.sessions.get(sid) is rec and not rec.restarts, "never restarted"
        assert rec.progress[0].status == "claimed" and "last" not in rec.scale, "a person's to read"


async def test_rule_6_never_tells_an_extra_of_new_work(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        _, rec = await _rec(person, agent, tmp_path, "grind-3")
        repo = tmp_path / "repo"
        repo.mkdir()
        rec.repo, rec.lane = str(repo), ["free-pick"]
        agent._repos[str(repo)] = {"name": "r", "root": str(repo), "ledger": {"entries": []}}
        _idle(rec)
        _out(rec)
        await agent._lane_news(rec, datetime.now(UTC))
        assert rec.lane_seen is None
        rec.scale = None  # the same record as a kept member: rule 6 writes its baseline
        await agent._lane_news(rec, datetime.now(UTC))
        assert rec.lane_seen is not None
