"""A run-only member's run ends (design §4.9 *A member started from the form*, §6 rules 2 and 8, TD-1166
slice 1): any Close of it marks `closed_for: {why: run_ended}` — the retry of a closed one too, a session's
close too, a node member's on the home's copy — but a person's Restart's own close, so its create supersedes
the record or leaves it pressable; a `run_ended` record is refused a Restart, read as sat out, drawn *run
ended*, and rule 8 replays no run-only record at all."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import park_ticks, wait_for
from test_person_restart import CLEAN, _member, _painted, _state

from sessionorc import work
from sessionorc.client import AgentError, LocalClient
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
