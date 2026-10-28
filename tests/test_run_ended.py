"""A run-only member's run ends (design §4.9 *A member started from the form*, §6 rules 2 and 8, TD-1166
slice 1): any Close of it marks `closed_for: {why: run_ended}` — the retry of a closed one too, a session's
close too, a node member's on the home's copy — but a person's Restart's own close, so its create supersedes
the record or leaves it pressable; a `run_ended` record is refused a Restart, read as sat out, drawn *run
ended*, and rule 8 replays no run-only record at all."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from conftest import park_ticks, wait_for
from test_cli_teams import creates, started, world  # noqa: F401 — the fixture, by name
from test_person_restart import CLEAN, _member, _painted, _state

from sessionorc import agent_common, work
from sessionorc.client import AgentError, LocalClient
from shiftlead import cli
from shiftlead.ui import cards


def _ended(rec) -> bool:
    return isinstance(rec.closed_for, dict) and rec.closed_for.get("why") == "run_ended"


@pytest.mark.unit
def test_sat_out_reads_run_ended_and_the_card_draws_it():
    assert work.sat_out({"closed_for": {"why": "run_ended"}}) and work.sat_out({"closed_for": {"why": "sit_out"}})
    assert not work.sat_out({"closed_for": {"why": "wanted"}})
    mark = cards.flow_mark({"id": "ao-x-w", "team": "t", "closed_for": {"why": "run_ended"}})
    assert mark["text"] == "run ended" and "does not come back" in mark["full"]


async def test_any_close_of_a_run_only_member_marks_its_run_ended(agent, tmp_path):
    await park_ticks(agent)
    shell = {"dir": str(tmp_path), "adapter": "shell", "argv": ["bash", "--norc"]}
    async with LocalClient() as person:
        plain = await person.call("create", name="plain", **shell)
        extra = await person.call("create", name="extra", run_only=True, **shell)
        for s in (plain, extra):
            await person.call("close", id=s["id"])
        assert agent.sessions[plain["id"]].closed_for is None
        rec = agent.sessions[extra["id"]]
        assert rec.closed_for == {"why": "run_ended", "closed_at": rec.closed_at}
        rec.closed_for = None  # the retry of a closed record marks it as well
        await person.call("close", id=extra["id"])
        assert _ended(rec)
        # the tick's restart writes its own mark after its close, over the close's (§6 rule 2)
        agent._mark_closed(rec, "wanted")
        assert rec.closed_for["why"] == "wanted"
        # a restart's flag is honoured only from no session caller: a manager's close still ends the run
        (tmp_path / "third").mkdir()
        mgr = await person.call("create", name="mgr", capabilities=["control"], **{**shell, "adapter": "agentshell"})
        third = await person.call(
            "create", name="third", run_only=True, unattended=True, controllers=[mgr["id"]],
            **{**shell, "adapter": "agentshell", "dir": str(tmp_path / "third")},
        )  # fmt: skip
        async with LocalClient(caller=mgr["id"]) as manager:
            await manager.call("close", id=third["id"], restart=True)
        assert _ended(agent.sessions[third["id"]])
        await person.call("kill", id=mgr["id"])


@pytest.mark.integration
async def test_a_persons_restart_keeps_a_run_only_member_run_only_and_refuses_one_whose_run_ended(
    agent, composerstubs, tmp_path, monkeypatch
):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path, run_only=True, team="g")
        old = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        await person.call("restart", id=sid)
        new = agent.sessions[sid]
        assert new is not old and old.state == "closed" and not _ended(old), "the restart's own close ends no run"
        assert new.run_only is True, "its successor is run-only, from the launch record"
        assert await wait_for(lambda: _painted(agent, sid), timeout=5)
        # a create that fails leaves the record pressable again: its close wrote no run_ended
        await agent.rpc_hook(sid, state="idle")
        new.git = dict(CLEAN)

        async def boom(**_kw):
            raise RuntimeError("no tmux")

        monkeypatch.setattr(agent, "rpc_create", boom)
        with pytest.raises(AgentError, match="the restart of w failed: no tmux"):
            await person.call("restart", id=sid)
        assert agent.sessions[sid] is new and new.state == "closed" and not _ended(new)
        monkeypatch.undo()
        # a person's own Close ends its run, and a Restart is then refused with its words
        await person.call("close", id=sid)
        assert _ended(new)
        with pytest.raises(AgentError, match="its run ended: start the team, or add one from the form"):
            await person.call("restart", id=sid)
        with pytest.raises(AgentError, match="its run ended: start the team"):
            await person.call("relaunch", id=sid, launch={"prompt": "x"})  # Apply's words are not the flow's


@pytest.mark.integration
async def test_rule_8_never_replays_a_run_only_member_an_exited_one_included(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        kept = await _member(agent, person, tmp_path, name="kept", team="g")
        extra = await _member(agent, person, tmp_path, name="extra", team="g", run_only=True)
        for sid in (kept, extra):
            await person.call("kill", id=sid)
            assert await wait_for(lambda sid=sid: _state(agent, sid, "exited"), timeout=5)
    got = [r.id for r in agent._work_replays(list(agent.sessions.values()), datetime.now(UTC))]
    assert got == [kept], "an exited run-only member, which no Close reached, is never replayed"


class Node:
    """A node's link that takes a close and answers as the node's `_close` does."""

    def __init__(self):
        self.acts = []

    async def request(self, method, timeout=None, **params):
        self.acts.append((params["rpc"], params["params"]))
        return {"result": {}}

    async def notify(self, method, **params):
        pass

    def close(self, why="closed"):
        pass


async def test_a_node_members_close_is_marked_on_the_homes_copy(agent):
    from test_link import record

    await park_ticks(agent)
    agent._take_records("laptop", [record(team="g", run_only=True)], whole=True)
    agent._link_muxes["laptop"] = node = Node()
    try:
        held = agent.remote["laptop"]["ao-x-w"]
        await agent._route_act("close", {"id": "ao-x-w@laptop", "reap": False, "restart": True}, None, "laptop")
        assert node.acts[-1] == ("close", {"id": "ao-x-w", "reap": False, "restart": True})
        assert not _ended(held), "a person's Restart's own close ends no run, at the home either"
        async with LocalClient() as person:
            await person.call("close", id="ao-x-w@laptop")
        assert _ended(held), "the home writes the mark on its copy: `closed_for` is the home's"
    finally:
        del agent._link_muxes["laptop"]


# ── slice 2: the team's run ends, the rename check, `ao team add` ──────────────────────────────────────


def _team(lead: str = "idle", **extra):
    """A team `g` under its manager: a kept member and a run-only one (`test_finished_tick`'s records)."""
    from test_finished_tick import _manager, _rec

    return _rec("g1"), _rec("extra", run_only=True, **extra), _manager(state=lead)


@pytest.mark.unit
def test_a_live_run_only_member_is_crew_and_alone_keeps_its_team_from_winding_down_or_concluding():
    g1, extra, manager = _team(out_of_work=None, state="working")
    g1.set_state("closed", confidence="scraped")
    assert extra in work.crew([g1, extra, manager])
    assert work.team_wound_down([g1, extra, manager]) is None
    reading = work.finished([g1, extra, manager])
    assert reading is not None and "extra working" in reading["why"], "rule 9 counts it as any member"
    extra.out_of_work, extra.state = {"at": "2026-09-28T07:00:00Z"}, "idle"
    assert work.finished([g1, extra, manager])["why"] == [], "concluded once it too has finished"


async def test_the_team_s_shape_samples_a_live_run_only_member(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path)
    agent._repos[root] = {"name": "repo", "ledger": {"entries": []}}
    g1, extra, manager = _team(lead="closed", role="grinder", lane=["free-pick"], repo=root)
    g1.state = "closed"
    for r in (g1, extra, manager):
        r.host, r.adapter = agent.host, "composer0"
        agent.sessions[r.id] = r
    now = datetime.now().astimezone()
    assert agent._shape_pass(now), "a team whose one live crew record is run-only is running"
    assert extra.id in agent._shape["days"][now.date().isoformat()]["g"]["records"]


async def test_a_team_with_nobody_live_marks_its_dead_run_only_records_and_rule_8_passes_them_over(agent):
    await park_ticks(agent)
    g1, extra, manager = _team()
    gone = _team()[1]
    gone.id, gone.name, gone.superseded_by, gone.state = "ao-t-gone", "gone", "ao-t-extra", "closed"
    for r in (g1, extra, manager, gone):
        r.host = agent.host
        agent.sessions[r.id] = r
    extra.set_state("exited", confidence="scraped")
    now = datetime.now(UTC)
    await agent._work_marks(now)
    assert extra.closed_for is None, "its team still runs: an exited run-only member waits for the run's end"
    g1.set_state("closed", confidence="scraped")
    manager.set_state("closed", confidence="scraped")
    agent._mark_closed(manager, "wanted")  # mid-restart: never its run's end
    manager.run_only = True
    await agent._work_marks(now)
    assert _ended(extra) and extra.closed_for["closed_at"] == extra.since, "an exit: the time it exited"
    assert g1.closed_for is None and gone.closed_for is None, "a kept member, and a superseded record, unmarked"
    assert manager.closed_for["why"] == "wanted", "the tick's restart mark stands"
    assert extra not in agent._work_replays(list(agent.sessions.values()), now)
    assert cards.flow_mark(extra.view())["text"] == "run ended"
    g1.closed_at, extra.closed_at = "2026-09-28T07:00:00+00:00", "2026-09-28T09:00:00+00:00"
    unmarked = dataclasses.replace(extra, closed_for=None)
    assert work.stopped_by([g1, unmarked])["at"] == g1.closed_at, "a run-only record's end is not the team's"


async def test_rule_9_s_conclusion_marks_an_exited_run_only_member(agent, monkeypatch):
    from test_finished_tick import _Home

    await park_ticks(agent)
    g1, extra, manager = _team()
    home = _Home(agent, monkeypatch, g1, extra, manager)
    late = _team()[1]
    late.id, late.name = "ao-t-late", "late"
    late.host = agent.host
    late.set_state("exited", confidence="scraped")
    agent.sessions[late.id] = late
    now = datetime.now(UTC)
    await agent._finished_pass(now)
    await agent._finished_pass(now + agent_common.FINISHED_SETTLE)
    assert home.closed == ["g1", "extra"] and manager.state == "idle", "the manager is told, still live"
    assert _ended(late), "the conclusion marks the dead run-only record no Close reached"


def _plan():
    from test_cli_teams import HOST

    from shiftlead import org as orgmod
    from shiftlead import teamrun, teams

    org = orgmod.with_home_settings(orgmod.load())
    return teams.plan(org, "ao-grind", HOST, files=teamrun.files_via(cli.call_sync)), teamrun, org


def test_the_rename_check_passes_over_a_run_only_member_live_or_exited(world, tmp_path):  # noqa: F811
    _, state = world
    started(state)
    plan, teamrun, _ = _plan()
    one = next(s for s in state["sessions"] if s["name"] == "grind-1")
    extra = {**one, "id": "ao-shiftlead-grind-3", "name": "grind-3", "run_only": True}
    for how in ("idle", "exited"):
        assert teamrun.renames(plan, [*state["sessions"], {**extra, "state": how}]) == ([], []), how
    # a renamed line still pairs its kept records, never the run-only one
    one.update(name="old-grind", role="grinder")
    pairs, removals = teamrun.renames(plan, [*state["sessions"], {**extra, "role": "grinder"}])
    assert [(r["name"], x.name) for r, x in pairs] == [("old-grind", "grind-1")] and removals == []


def test_ao_team_add_is_refused_on_a_team_not_running_and_to_a_session(world, capsys, monkeypatch):  # noqa: F811
    _, state = world
    for keep in ([], ["--keep"]):
        assert cli.main(["team", "add", "ao-grind", "grind", *keep]) == 1
        assert "ao-grind is not running: start it first" in capsys.readouterr().err
    assert not creates(state) and "teams" not in state, "nothing started and no size written"
    started(state)
    for s in state["sessions"]:
        if s["name"] == "orc-ao":
            s["state"] = "closed"  # its manager gone, and not a seat on call
    assert cli.main(["team", "add", "ao-grind", "grind"]) == 1
    assert "not running" in capsys.readouterr().err
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-shiftlead-grind-1")
    assert cli.main(["team", "add", "ao-grind", "grind"]) == 1
    assert "refused to a session" in capsys.readouterr().err and not creates(state)


def test_ao_team_add_starts_a_run_only_member_and_with_keep_raises_the_size(world, capsys):  # noqa: F811
    _, state = world
    started(state)
    capsys.readouterr()
    assert cli.main(["team", "add", "ao-grind", "grind"]) == 0
    assert capsys.readouterr().out.strip() == "started grind-3"
    (made,) = creates(state)
    assert made["name"] == "grind-3" and made["run_only"] is True and "teams" not in state, "no setting written"
    state["calls"].clear()
    assert cli.main(["team", "add", "ao-grind", "hunt", "--keep"]) == 0
    assert capsys.readouterr().out.startswith("hunt: 2 (file says 1)")
    assert state["teams"] == {"ao-grind": {"size": {"hunt": 2}}}
    assert [(p["name"], "run_only" in p) for p in creates(state)] == [("hunt-2", False)]


def test_a_team_a_person_leads_is_running_while_any_crew_record_is_live(world):  # noqa: F811
    from shiftlead import org as orgmod
    from shiftlead import teamrun

    team = orgmod.TeamDef(name="g", manager=orgmod.ManagerDef(role=orgmod.PERSON, name="paul"))
    rec = {"team": "g", "name": "w", "unattended": True, "state": "idle"}
    assert teamrun.not_running(team, [rec]) == ""
    assert teamrun.not_running(team, [{**rec, "state": "closed"}]) == "g is not running: start it first"
    assert teamrun.not_running(team, [{**rec, "unattended": False}]) != "", "a person's own session keeps nothing"
