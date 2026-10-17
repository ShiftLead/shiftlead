"""TD-706 slice 2, design §4.9 *A member renamed or removed in the definition*: the home's half. A
relaunch handing `name` marks the record, and its next replay creates under the new name with
`succeeds: <old id>` — the old record's mail moved, `superseded_by` written on it, its claims in
progress and `lane_seen` copied, every record's and launch record's `controllers` naming the old
address rewritten, its launch record dropped. A removal is the sit-out form with `dropped`, which
marks a seat too, and rule 3 never fills a sat-out seat."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import naming, paths
from sessionorc.client import AgentError, LocalClient

SHELL = {"adapter": "shell", "argv": ["bash", "--norc", "--noprofile"]}
AGENT = {**SHELL, "adapter": "agentshell"}  # a session: the person's own shell passes as the person (TD-802)


def _launch(address: str) -> dict:
    return json.loads((paths.launch_dir() / f"{address}.json").read_text())


def _idle(rec) -> None:
    rec.state, rec.confidence, rec.pending = "idle", "hook", None
    rec.git = {"dirty": 0, "unpushed": 0}


def _own(tmp_path, n: str) -> str:  # one directory each: the anchor rule (§9 invariant 2)
    (tmp_path / n).mkdir(exist_ok=True)
    return str(tmp_path / n)


async def _kill_all(person, agent) -> None:
    for sid in list(agent.sessions):
        with contextlib.suppress(Exception):
            await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_renamed_live_member_relaunches_under_the_new_name_with_its_mail(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        lead = (await person.call("create", name="lead", dir=_own(tmp_path, "l"), unattended=True, **SHELL))["id"]
        params = {"dir": _own(tmp_path, "w"), "unattended": True, "supervised": True, "prompt": "p", **SHELL}
        params["adapter"] = "agentshell"  # mail is read only by an agent (§4.3)
        sid = (await person.call("create", name="grinder-dc-1", controllers=[lead], lane=["TD-1"], **params))["id"]
        async with LocalClient(caller=lead) as boss:
            note = (await boss.call("msg", to=sid, text="carry on"))["entry"]
        old = agent.sessions[sid]
        view = await person.call("relaunch", id=sid, launch={"prompt": "p2", "name": "dc-grinder"})
        assert view["relaunch"]["name"] == "dc-grinder" and _launch(sid)["name"] == "dc-grinder"
        assert _launch(sid)["dir"] == params["dir"]  # the rest of the launch record stands
        _idle(old)
        await agent._keep_running(datetime.now(UTC))
        nid = naming.base_id(params["dir"], None, "dc-grinder")
        new = agent.sessions[nid]
        assert new.name == "dc-grinder" and [r["why"] for r in new.restarts] == ["flow"]
        assert old.superseded_by == nid and old.state == "closed" and agent.sessions[sid] is old
        assert {"id": sid, "mail": True, "at": new.created} in new.supersedes
        assert [e.id for e in new.inbox] == [note["id"]] and old.inbox == []  # the mail moved
        assert new.controllers == [lead] and new.relaunch is None
        assert not (paths.launch_dir() / f"{sid}.json").exists()  # the launch record moved to the new id
        assert _launch(nid)["name"] == "dc-grinder" and _launch(nid)["prompt"] == "p2"
        # every later tick passes the old record over: it is superseded
        await agent._keep_running(datetime.now(UTC))
        assert agent.sessions[sid] is old and old.superseded_by == nid
        await _kill_all(person, agent)


@pytest.mark.integration
async def test_a_stopped_teams_renamed_manager_keeps_its_claims_lane_seen_and_members(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        base = {"unattended": True, "supervised": True, "prompt": "p", **SHELL}
        mgr = (await person.call("create", name="manager-dc-1", dir=_own(tmp_path, "m"), **base))["id"]
        w = (await person.call("create", name="grinder", dir=_own(tmp_path, "w"), controllers=[mgr], **base))["id"]
        assert mgr in agent.sessions[w].controllers and mgr in _launch(w)["controllers"]
        await person.call("progress", id=mgr, ref="TD-001", status="claimed")
        await person.call("relaunch", id=mgr, launch={"name": "dc-manager"})
        await person.call("kill", id=mgr)
        old = agent.sessions[mgr]
        old.state, old.lane_seen = "closed", {"at": "2026-10-14T08:00:00Z", "ids": ["TD-001", "TD-002"]}
        # rule 8's start of a stopped team replays it: the create under the new name succeeds it
        await agent._replay(agent.sessions[mgr], "work", keep_mail=True)
        nid = naming.base_id(_own(tmp_path, "m"), None, "dc-manager")
        assert old.superseded_by == nid and agent._work_replays(list(agent.sessions.values()), datetime.now(UTC)) == []
        new = agent.sessions[nid]
        assert [(e.ref, e.status) for e in new.progress] == [("TD-001", "claimed")]  # the lease holds
        assert new.lane_seen == {"at": "2026-10-14T08:00:00Z", "ids": ["TD-001", "TD-002"]}
        assert nid in agent.sessions[w].controllers and mgr not in agent.sessions[w].controllers
        assert nid in _launch(w)["controllers"] and mgr not in _launch(w)["controllers"]
        await _kill_all(person, agent)


@pytest.mark.integration
async def test_succeeds_is_refused_touching_nothing(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        base = {"unattended": True, "supervised": True, "prompt": "p", **SHELL}
        live = (await person.call("create", name="a", dir=_own(tmp_path, "a"), **base))["id"]
        ended = (await person.call("create", name="b", dir=_own(tmp_path, "b"), **base))["id"]
        await person.call("kill", id=ended)
        stranger = (await person.call("create", name="s", dir=_own(tmp_path, "s"), capabilities=["control"], **AGENT))[
            "id"
        ]
        new = {"dir": _own(tmp_path, "n"), **base}
        refusals = [
            ({"name": "n", "succeeds": live}, "is a record that has ended|has ended"),
            ({"name": "n", "succeeds": "ao-nope"}, "no record"),
            ({"name": "b", "dir": _own(tmp_path, "b"), "succeeds": ended}, "holds this name already"),
            ({"name": "n", "succeeds": ended, "keep_mail": True}, "not beside resume, keep_mail"),
        ]
        for kw, words in refusals:
            with pytest.raises(AgentError, match=words):
                await person.call("create", **{**new, **kw})
        async with LocalClient(caller=stranger) as s:
            with pytest.raises(AgentError, match="is not a controller of"):
                await s.call("create", name="n", succeeds=ended, **new)
        assert agent.sessions[ended].superseded_by is None
        assert not any(r.name == "n" for r in agent.sessions.values())
        await _kill_all(person, agent)


@pytest.mark.integration
async def test_a_relaunchs_name_and_dropped_are_refused_out_of_place(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        params = {"dir": _own(tmp_path, "a"), "unattended": True, "supervised": True, "prompt": "p", **SHELL}
        sid = (await person.call("create", name="a", **params))["id"]
        with pytest.raises(AgentError, match="never blank"):
            await person.call("relaunch", id=sid, launch={"name": " "})
        with pytest.raises(AgentError, match="the sit-out form's"):
            await person.call("relaunch", id=sid, launch={"prompt": "x"}, dropped=True)
        # the same name handed is no rename
        view = await person.call("relaunch", id=sid, launch={"prompt": "x", "name": "a"})
        assert "name" not in view["relaunch"]
        # a second Apply before the replay keeps the first one's rename, handed again or not
        assert (await person.call("relaunch", id=sid, launch={"name": "b"}))["relaunch"]["name"] == "b"
        assert (await person.call("relaunch", id=sid, launch={"name": "b"}))["relaunch"]["name"] == "b"
        assert (await person.call("relaunch", id=sid, launch={"prompt": "y"}))["relaunch"]["name"] == "b"
        # and one that hands the record's own name back cancels it
        assert "name" not in (await person.call("relaunch", id=sid, launch={"name": "a"}))["relaunch"]
        await _kill_all(person, agent)


@pytest.mark.integration
async def test_a_seat_the_definition_drops_is_marked_and_never_filled(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        params = {"dir": _own(tmp_path, "t"), "unattended": True, "supervised": True, "prompt": "p", **SHELL}
        sid = (await person.call("create", name="t", seat={"trigger": "asks"}, **params))["id"]
        with pytest.raises(AgentError, match="is a seat"):  # a flow never sits one out
            await person.call("relaunch", id=sid, sit_out=True)
        view = await person.call("relaunch", id=sid, sit_out=True, dropped=True)
        assert view["sit_out"]["dropped"] is True
        await person.call("kill", id=sid)
        rec = agent.sessions[sid]
        rec.state = "closed"
        fills: list[str] = []

        async def fill(s, now, records):
            fills.append(s.id)

        monkeypatch.setattr(agent, "_fill", fill)
        monkeypatch.setattr(agent, "_seat_due", lambda s, now, records: {"why": "asks", "at": "t"})
        await agent._keep_running(datetime.now(UTC))
        assert fills == [] and rec.closed_for and rec.closed_for["why"] == "sit_out"
        await _kill_all(person, agent)
