"""A run-only member (design §4.9 *A team's size*, *A member started from the form*, TD-1164 slice 3):
`run_only` on the record and its launch record, carried by a replay, and cleared by the `keep` act — a
home-owned edit as `set_mode` is (§4.4a), on a node's member applied to the home's copy once the node has
taken it, and refused while the link is down."""

from __future__ import annotations

import json

import pytest
from conftest import park_ticks

from sessionorc import link, paths
from sessionorc.agent_common import LAUNCH_KEYS, launch_params
from sessionorc.client import AgentError, LocalClient


def _launch(address: str):
    return paths.launch_dir() / f"{address}.json"


class Node:
    """A node's link that takes a home-owned edit and answers as the node's RPC does."""

    def __init__(self, down: bool = False):
        self.down, self.acts = down, []

    async def request(self, method, timeout=None, **params):
        if self.down:
            raise link.LinkError("unreachable")
        self.acts.append((params["rpc"], params["params"]))
        return {"result": {}}

    async def notify(self, method, **params):
        pass

    def close(self, why="closed"):
        pass


def test_a_launch_record_carries_run_only():
    assert "run_only" in LAUNCH_KEYS
    assert launch_params({"name": "w", "run_only": True, "caller": "x"}) == {"name": "w", "run_only": True}


async def test_a_run_only_create_writes_it_on_the_record_and_the_launch_record_and_keep_clears_both(agent, tmp_path):
    shell = {"dir": str(tmp_path), "adapter": "shell", "argv": ["bash", "--norc"]}
    async with LocalClient() as person:
        plain = await person.call("create", name="plain", supervised=True, **shell)
        assert plain["run_only"] is False and "run_only" not in json.loads(_launch(plain["id"]).read_text())
        s = await person.call("create", name="extra", supervised=True, run_only=True, team="t", **shell)
        assert s["run_only"] is True
        rec = json.loads(_launch(s["id"]).read_text())
        assert rec["run_only"] is True and rec["team"] == "t"
        assert agent._read_launch(s["id"])["run_only"] is True  # what a replay hands `create` again
        kept = await person.call("keep", id=s["id"])
        assert kept["run_only"] is False
        rec = json.loads(_launch(s["id"]).read_text())
        assert "run_only" not in rec and rec["team"] == "t" and rec["name"] == "extra"  # the rest kept
        for sid in (plain["id"], s["id"]):
            await person.call("kill", id=sid)


async def test_keep_is_an_act_a_session_needs_control_for(agent, tmp_path):
    shell = {"dir": str(tmp_path), "adapter": "shell", "argv": ["bash", "--norc"]}
    async with LocalClient() as person:
        s = await person.call("create", name="extra", supervised=True, run_only=True, **shell)
        other = await person.call("create", name="other", **{**shell, "adapter": "agentshell"})
        async with LocalClient(caller=other["id"]) as stranger:
            with pytest.raises(AgentError, match="needs the control grant"):
                await stranger.call("keep", id=s["id"])
        assert (await person.call("get", id=s["id"]))["run_only"] is True
        for sid in (s["id"], other["id"]):
            await person.call("kill", id=sid)


async def test_keep_on_a_node_member_lands_on_the_homes_copy_once_the_node_took_it(agent):
    from test_link import record

    await park_ticks(agent)
    agent._take_records("laptop", [record(team="grind", supervised=True, run_only=True)], whole=True)
    paths.launch_dir().mkdir(parents=True, exist_ok=True)
    _launch("ao-x-w@laptop").write_text(json.dumps({"name": "w", "team": "grind", "run_only": True}))
    agent._link_muxes["laptop"] = node = Node(down=True)
    try:
        async with LocalClient() as person:
            with pytest.raises(AgentError, match="unreachable"):
                await person.call("keep", id="ao-x-w@laptop")
            assert agent.remote["laptop"]["ao-x-w"].run_only is True  # refused, never left to diverge
            assert json.loads(_launch("ao-x-w@laptop").read_text())["run_only"] is True
            node.down = False
            got = await person.call("keep", id="ao-x-w@laptop")
        assert node.acts == [("keep", {"id": "ao-x-w"})]  # the node's replica first, in its own form
        assert got["run_only"] is False and agent.remote["laptop"]["ao-x-w"].run_only is False
        rec = json.loads(_launch("ao-x-w@laptop").read_text())
        assert "run_only" not in rec and rec["team"] == "grind"
    finally:
        del agent._link_muxes["laptop"]
