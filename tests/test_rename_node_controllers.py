"""TD-712: a node member's own record takes a renamed lead's new address in `controllers` at its node
(design §4.9 *A member renamed or removed in the definition*): the home routes `set_controllers` as a
person's edit is routed, since the field is the node's, and a node whose link is down is retried."""

from __future__ import annotations

import json

from conftest import park_ticks

from sessionorc import link, paths
from sessionorc.models import Session


class Node:
    """A node's link that takes `set_controllers` and answers as `rpc_set_controllers` does."""

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


def _lead(agent, rid: str, name: str, **kw) -> Session:
    s = Session(id=rid, name=name, kind="agent", adapter="claude-code", dir=f"/tmp/{name}", host=agent.host, **kw)
    agent.sessions[rid] = s
    return s


def _renamed(agent) -> tuple[str, str]:
    """The lead `ao-x-mgr` renamed `ao-x-boss`, as `_succeed` leaves the two records at the home."""
    _lead(agent, "ao-x-mgr", "mgr", state="closed", superseded_by="ao-x-boss")
    _lead(agent, "ao-x-boss", "boss", state="idle")
    return f"ao-x-mgr@{agent.host}", f"ao-x-boss@{agent.host}"


def _member(agent, launch: list[str] | None, controllers: list[str]) -> Session:
    from test_link import record

    agent._take_records("laptop", [record(controllers=controllers, team="grind")], whole=True)
    if launch is not None:
        paths.launch_dir().mkdir(parents=True, exist_ok=True)
        (paths.launch_dir() / "ao-x-w@laptop.json").write_text(json.dumps({"name": "w", "controllers": launch}))
    return agent.remote["laptop"]["ao-x-w"]


async def test_a_node_member_under_a_renamed_lead_names_the_new_one_at_its_node(agent):
    await park_ticks(agent)
    old, new = _renamed(agent)
    # `_carry` rewrote the launch record; the node's own record still names the old lead
    w = _member(agent, launch=[new, "ao-x-sib"], controllers=[old, "ao-x-sib"])
    agent._link_muxes["laptop"] = node = Node()
    agent.links["laptop"] = {"up": True, "since": "t", "why": "linked"}
    try:
        await agent._carry_controllers()
        assert node.acts == [("set_controllers", {"id": "ao-x-w", "add": [new], "remove": [old]})]
        assert w.controllers == ["ao-x-sib", new], "the home's copy carries the edit the node took"
        await agent._carry_controllers()
        assert len(node.acts) == 1, "nothing left to carry: never sent twice"
    finally:
        del agent._link_muxes["laptop"]


async def test_a_node_that_is_down_is_retried_on_the_next_tick(agent, caplog):
    await park_ticks(agent)
    old, new = _renamed(agent)
    w = _member(agent, launch=[new], controllers=[old])
    await agent._carry_controllers()  # no link at all: passed over
    assert w.controllers == [old]
    agent._link_muxes["laptop"] = node = Node(down=True)
    try:
        with caplog.at_level("WARNING", logger="shiftlead.agent"):
            await agent._carry_controllers()
        assert w.controllers == [old] and "the rename's controllers did not reach laptop" in caplog.text
        node.down = False
        await agent._carry_controllers()
        assert node.acts == [("set_controllers", {"id": "ao-x-w", "add": [new], "remove": [old]})]
        assert w.controllers == [new]
    finally:
        del agent._link_muxes["laptop"]


async def test_a_controller_no_launch_record_moves_is_left_alone(agent):
    """A resume under another id supersedes a record too, and rewrites no launch record: the carry is
    the rename's alone, so a member whose launch record still names the old lead keeps it."""
    await park_ticks(agent)
    old, new = _renamed(agent)
    w = _member(agent, launch=[old], controllers=[old])
    agent._link_muxes["laptop"] = node = Node()
    try:
        await agent._carry_controllers()
        assert node.acts == [] and w.controllers == [old]
        (paths.launch_dir() / "ao-x-w@laptop.json").unlink()
        await agent._carry_controllers()
        assert node.acts == [], "no launch record: nothing says the rename reached it"
    finally:
        del agent._link_muxes["laptop"]


async def test_a_lead_renamed_twice_is_carried_to_its_last_name(agent):
    await park_ticks(agent)
    old, mid = _renamed(agent)
    agent.sessions["ao-x-boss"].state, agent.sessions["ao-x-boss"].superseded_by = "closed", "ao-x-chief"
    last = f"ao-x-chief@{agent.host}"
    _lead(agent, "ao-x-chief", "chief", state="idle")
    w = _member(agent, launch=[last], controllers=[old])
    agent._link_muxes["laptop"] = node = Node()
    try:
        await agent._carry_controllers()
        assert node.acts == [("set_controllers", {"id": "ao-x-w", "add": [last], "remove": [old]})]
        assert w.controllers == [last] and mid not in w.controllers
    finally:
        del agent._link_muxes["laptop"]


async def test_the_tick_carries_them(agent, monkeypatch):
    await park_ticks(agent)
    seen = []

    async def carry():
        seen.append(True)

    monkeypatch.setattr(agent, "_carry_controllers", carry)
    await agent.tick()
    assert seen == [True]
