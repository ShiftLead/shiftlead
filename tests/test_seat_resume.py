"""TD-1455 (build 1 of TD-1435), design §4.9b *A seat stays a seat when it is resumed*, §4.9c *Switching*:
a Resume of an ended seat keeps its `seat` on the record and the launch record; Hand back (`set_mode` to
unattended) writes `unattended` and the usage gate's texts on the launch record too, mending one a Resume
left attended; and Apply restores a member's `seat` that differs from the definition, a seat-only Apply
writing the launch record and the record alone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import park_ticks

from sessionorc import paths
from sessionorc.client import AgentError, LocalClient
from shiftlead import teamrun, teams

SEAT = {"trigger": "asks"}
SHELL = {"adapter": "shell", "argv": ["bash", "--norc", "--noprofile"]}


def _launch(sid: str) -> dict:
    return json.loads((paths.launch_dir() / f"{sid}.json").read_text())


async def _ended_seat(c: LocalClient, tmp_path: Path, conversation: str = "cc-seat") -> dict:
    """An unattended, supervised seat record that ran a conversation and ended, gated as a team's is."""
    s = await c.call(
        "create",
        name="tl",
        dir=str(tmp_path),
        adapter="hookstub",
        unattended=True,
        supervised=True,
        seat=SEAT,
        pause_prompt="pause",
        resume_prompt="go on",
        prompt="the brief",
    )
    await c.call("hook", session=s["id"], adapter_id=conversation)
    await c.call("kill", id=s["id"])
    return s


async def test_a_resume_of_an_ended_seat_keeps_its_seat_on_the_record_and_the_launch_record(agent, hookstub, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        old = await _ended_seat(person, tmp_path)
        # the one-press Resume: no seat, no unattended, no gate texts (`resume_create`)
        new = await person.call("create", name="tl", dir=str(tmp_path), adapter="hookstub", resume="cc-seat")
        assert new["id"] == old["id"] and new["seat"] == SEAT and new["unattended"] is False
        got = _launch(new["id"])
        assert got["seat"] == SEAT and got["unattended"] is False and "pause_prompt" not in got
        assert agent.sessions[new["id"]].by_person is False  # a seat, so no person's own (§4.10)
        # Hand back: the launch record every replay reads is unattended and gated again
        await person.call("set_mode", id=new["id"], unattended=True, pause_prompt="pause", resume_prompt="go on")
        got = _launch(new["id"])
        assert (got["unattended"], got["pause_prompt"], got["resume_prompt"], got["seat"]) == (
            True,
            "pause",
            "go on",
            SEAT,
        )
        await person.call("kill", id=new["id"])


async def test_a_seat_the_resume_gives_wins(agent, hookstub, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        await _ended_seat(person, tmp_path)
        given = {"trigger": "prs", "after": "3"}
        new = await person.call(
            "create", name="tl", dir=str(tmp_path), adapter="hookstub", resume="cc-seat", seat=given
        )
        assert new["seat"] == given and _launch(new["id"])["seat"] == given
        await person.call("kill", id=new["id"])


async def test_a_resume_under_another_name_holding_the_seats_conversation_carries_no_seat(agent, hookstub, tmp_path):
    await park_ticks(agent)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    async with LocalClient() as person:
        await _ended_seat(person, tmp_path / "a")
        other = await person.call("create", name="other", dir=str(tmp_path / "b"), adapter="hookstub", resume="cc-seat")
        assert other["seat"] is None
        await person.call("kill", id=other["id"])


async def test_set_mode_unattended_mends_a_launch_record_a_resume_left_attended(agent, hookstub, tmp_path):
    """`ao mode <id> unattended` on a record already unattended mends its launch record, key by key."""
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await _ended_seat(person, tmp_path)
        rec = agent.sessions[s["id"]]
        # the launch record as a Resume and a Hand back before this build left it
        launch = {k: v for k, v in _launch(s["id"]).items() if k not in ("id", "at")}
        launch.update(unattended=False)
        launch.pop("pause_prompt")
        launch.pop("resume_prompt")
        agent._write_launch(s["id"], rec, launch)
        assert rec.unattended is True
        stamp = rec.mode_at
        # ended: the mend reaches the record rule 3 replays
        await person.call("set_mode", id=s["id"], unattended=True, pause_prompt="pause", resume_prompt="")
        got = _launch(s["id"])
        assert got["unattended"] is True and got["pause_prompt"] == "pause" and "resume_prompt" not in got
        assert rec.mode_at == stamp  # no change of mode, so no new stamp
        # a text not handed leaves the launch record's as it was
        await person.call("set_mode", id=s["id"], unattended=True)
        assert _launch(s["id"])["pause_prompt"] == "pause"


async def test_set_mode_on_a_record_with_no_launch_record_writes_none(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        loose = await person.call("create", name="loose", dir=str(tmp_path), adapter="agentshell")
        await person.call("set_mode", id=loose["id"], unattended=True, pause_prompt="pause")
        assert agent.sessions[loose["id"]].unattended is True
        assert not (paths.launch_dir() / f"{loose['id']}.json").exists()
        await person.call("kill", id=loose["id"])


async def test_set_mode_to_interactive_leaves_a_seats_launch_record(agent, hookstub, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await _ended_seat(person, tmp_path)
        before = _launch(s["id"])
        await person.call("set_mode", id=s["id"], unattended=False)
        assert _launch(s["id"]) == before


async def test_a_controller_without_the_control_grant_is_refused_the_set_mode(agent, hookstub, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        mgr = (await person.call("create", name="mgr", dir=str(tmp_path / ".."), adapter="agentshell"))["id"]
        s = await _ended_seat(person, tmp_path)
        agent.sessions[s["id"]].controllers = [mgr]
        before = _launch(s["id"])
        async with LocalClient(caller=mgr) as m:
            with pytest.raises(AgentError, match="control"):
                await m.call("set_mode", id=s["id"], unattended=True)
        assert _launch(s["id"]) == before
        await person.call("kill", id=mgr)


async def test_a_seat_only_relaunch_writes_the_seat_alone_and_leaves_a_pending_brief_change(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create", name="tl", dir=str(tmp_path), unattended=True, supervised=True, prompt="p", lane=[], **SHELL
            )
        )["id"]
        rec = agent.sessions[sid]
        assert rec.seat is None  # the seat a Resume lost
        rec.brief_changed = {"at": "2026-11-06T07:00:00Z", "paths": ["/r/b.md"]}
        launch = {"prompt": "p", "prompt_from": None, "lane": [], "review": None, "profile": "", "seat": SEAT}
        view = await person.call("relaunch", id=sid, launch=launch)
        assert view["seat"] == SEAT and rec.seat == SEAT and _launch(sid)["seat"] == SEAT
        assert rec.relaunch is None and rec.brief_changed  # no mark, the pending change stands
        # a member the definition gives no seat: handed None, removed from both, its due with it
        rec.seat_due = {"at": "2026-11-06T07:00:00Z", "by": "asks"}
        await person.call("relaunch", id=sid, launch={**launch, "seat": None})
        assert rec.seat is None and rec.seat_due is None and "seat" not in _launch(sid)
        assert rec.relaunch is None
        # a prompt composed differently is a real difference: the mark is written as before
        await person.call("relaunch", id=sid, launch={**launch, "prompt": "new"})
        assert rec.relaunch and rec.seat == SEAT
        with pytest.raises(AgentError, match="seat"):
            await person.call("relaunch", id=sid, launch={**launch, "seat": {"after": "1"}})
        await person.call("kill", id=sid)


async def test_a_seat_only_relaunch_leaves_a_pending_rename_standing(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create", name="tl", dir=str(tmp_path), unattended=True, supervised=True, prompt="p", lane=[], **SHELL
            )
        )["id"]
        rec = agent.sessions[sid]
        base = {"prompt": "p", "prompt_from": None, "lane": [], "review": None, "profile": ""}
        await person.call("relaunch", id=sid, launch={**base, "name": "tl2"})
        assert rec.relaunch and rec.relaunch.get("name") == "tl2"
        mark = dict(rec.relaunch)
        await person.call("relaunch", id=sid, launch={**base, "seat": SEAT})
        assert rec.relaunch == mark and _launch(sid)["name"] == "tl2" and rec.seat == SEAT
        await person.call("kill", id=sid)


# ── the client's half: the difference and Apply's launch (teamrun) ──


def _x(name: str, *, trigger: dict | None = None, host: str = "") -> teams.Launch:
    return teams.Launch(
        name=name,
        role=name,
        home="r",
        dir=Path("/r"),
        team="t",
        project="p",
        seat=trigger is not None,
        trigger=trigger,
        host=host,
    )


def _rec(name: str, state: str = "idle", **extra) -> dict:
    return {"id": f"ao-{name}", "name": name, "team": "t", "state": state, "unattended": True, **extra}


def _plan(*launches: teams.Launch, flow: str | None = None) -> teams.Plan:
    return teams.Plan(team="t", members=list(launches), flow=flow)


def test_a_record_that_lost_its_seat_reads_a_seat_line_written_now():
    x = _x("tl", trigger={"trigger": "asks"})
    for flow in (None, "td"):
        diffs = teamrun.differences(_plan(x, flow=flow), [_rec("tl")])
        assert [d.what for d in diffs] == [["seat none → asks"]]
        assert diffs[0].definition and diffs[0].line(flow) == "tl: seat none → asks (written now)"
        assert teamrun.definition_changed([d.as_dict(flow) for d in diffs], flow)


def test_a_seat_line_is_read_on_an_ended_or_closed_record_and_a_stray_seat_reads_none():
    x = _x("g")
    live = _rec("w", trigger=None)
    for state in ("exited", "closed"):
        for flow in (None, "td"):
            sessions = [_rec("g", state, seat={"trigger": "asks"}), live]
            diffs = teamrun.differences(_plan(x, _x("w"), flow=flow), sessions)
            assert [d.what for d in diffs] == [["seat asks → none"]], (state, flow)


def test_a_node_members_seat_line_and_one_beside_a_profile_read_next_restart():
    x = _x("tl", trigger={"trigger": "asks"}, host="node1")
    (d,) = teamrun.differences(_plan(x), [_rec("tl")])
    assert d.line(None) == "tl: seat none → asks (next restart)"
    y = teams.Launch(**{**_x("tl", trigger={"trigger": "asks"}).__dict__, "profile": "opus"})
    (d,) = teamrun.differences(_plan(y), [_rec("tl")])
    assert d.what == ["seat none → asks", "profile default → opus"]
    assert d.definition and d.line(None).endswith("(next restart)")


def test_an_unchanged_team_and_a_persons_record_read_no_seat_line():
    x = _x("tl", trigger={"trigger": "asks"})
    assert teamrun.differences(_plan(x), [_rec("tl", seat={"trigger": "asks"})]) == []
    worker = _rec("w")
    assert teamrun.differences(_plan(x, _x("w")), [_rec("tl", unattended=False), worker]) == []


def test_apply_hands_the_definitions_whole_seat_or_none():
    x = _x("tl", trigger={"trigger": "asks"})
    x.tags = True
    assert teamrun.relaunch_params(x)["seat"] == {"trigger": "asks", "tags": True}
    assert x.create_params([])["seat"] == teamrun.relaunch_params(x)["seat"]
    assert teamrun.relaunch_params(_x("w"))["seat"] is None
