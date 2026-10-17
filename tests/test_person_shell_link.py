"""The person's own shell is the person across the link (design §4.8 *The person's own shell is the
person*, §4.4a, TD-801, TD-802 slice 2): every act from it routed to a node is forwarded with no caller,
so the node seeds no creator, spends a ceiling and records *person*; a create from it lifts a suspended
name as a person's does; a shell at a node is bound to its node as a person there is, and acts on its
node's sessions with the link up or down. Each call names `caller=<the shell's id>`, never through the
identity machinery."""

from __future__ import annotations

import pytest
from conftest import park_ticks

from sessionorc import modes
from sessionorc.models import Session

SHELL = {"adapter": "shell", "argv": ["bash", "--norc", "--noprofile"]}


class Node:
    """A node's link at the home that takes each routed act and answers with the record it is given."""

    def __init__(self, reply=None):
        self.acts, self.reply = [], reply or {}

    async def request(self, method, timeout=None, **params):
        self.acts.append(params)
        return self.reply

    async def notify(self, method, **params):
        pass

    def close(self, why="closed"):
        pass


def _record(rid: str, **kw) -> dict:
    base = dict(id=rid, name=rid.removeprefix("ao-x-"), kind="interactive", adapter="shell", dir="/tmp/x")
    return Session(**{**base, "host": "laptop", "state": "idle", **kw}).to_dict()


def _home_shell(agent, sid: str = "ao-sh", **kw) -> str:
    agent.sessions[sid] = Session(
        id=sid, name=sid, kind="interactive", adapter="shell", dir="/tmp", host=agent.host, **kw
    )
    return sid


def _linked(agent, node: Node) -> None:
    agent._link_muxes["laptop"] = node
    agent.links["laptop"] = {"up": True, "since": "t", "why": "linked"}


@pytest.mark.unit
def test_offline_a_nodes_shell_acts_on_its_sessions_and_each_near_miss_is_still_gated():
    records = {
        "ao-sh": Session(id="ao-sh", name="sh", kind="interactive", adapter="shell", dir="/tmp"),
        "ao-u": Session(id="ao-u", name="u", kind="interactive", adapter="shell", dir="/tmp", unattended=True),
        "ao-c": Session(id="ao-c", name="c", kind="interactive", adapter="shell", dir="/tmp", controllers=["ao-x"]),
        "ao-r": Session(id="ao-r", name="r", kind="interactive", adapter="shell", dir="/tmp", role="manager"),
        "ao-t": Session(id="ao-t", name="t", kind="interactive", adapter="shell", dir="/tmp", team="t"),
        "ao-a": Session(id="ao-a", name="a", kind="interactive", adapter="claude-code", dir="/tmp"),
    }
    where = {"host": "laptop", "home": "kmaster", "records": records}
    for method in sorted(modes.NODE_ACTS - {"seen", "hook"}):
        assert modes.offline_refusal(method, "ao-sh", {"id": "ao-w"}, **where) is None, method
    for caller in ("ao-u", "ao-c", "ao-r", "ao-t", "ao-a", "ao-gone"):
        assert "gated at the home" in modes.offline_refusal("kill", caller, {"id": "ao-w"}, **where), caller
    # what is the home's stays the home's, the shell's call or not
    assert "the mailbox is at the home" in modes.offline_refusal("msg", "ao-sh", {}, **where)
    assert "waits for the link" in modes.offline_refusal("set_grants", "ao-sh", {"id": "ao-w"}, **where)
    # with no records given, a caller is a session, as before the argument
    assert modes.offline_refusal("kill", "ao-sh", {"id": "ao-w"}, host="laptop", home="kmaster")


@pytest.mark.integration
async def test_a_nodes_shell_kills_its_nodes_sessions_link_down_or_up_and_an_agent_there_may_not(
    agent, tmp_path, monkeypatch
):
    await park_ticks(agent)
    made = {}
    for name, extra in (("sh", {}), ("w", {"unattended": True}), ("x", {"unattended": True})):
        (tmp_path / name).mkdir()
        made[name] = (await agent.rpc_create(name=name, dir=str(tmp_path / name), **extra, **SHELL))["id"]
    agent.mode, agent.home = "node", "kmaster"  # a node whose home cannot be reached
    try:
        assert not agent.home_reachable()
        got = await agent._dispatch({"id": 1, "method": "kill", "params": {"id": made["w"]}, "caller": made["x"]})
        assert "gated at the home" in got["error"] and agent.sessions[made["w"]].pane
        got = await agent._dispatch({"id": 2, "method": "kill", "params": {"id": made["w"]}, "caller": made["sh"]})
        assert "error" not in got, got
        assert agent.sessions[made["w"]].state == "exited"
        # the link up: served here as a person's act is, never handed to the home
        forwarded = []

        async def forward(*args):
            forwarded.append(args)
            return {"error": "forwarded"}

        monkeypatch.setattr(agent, "home_reachable", lambda: True)
        monkeypatch.setattr(agent, "_forward", forward)
        got = await agent._dispatch({"id": 3, "method": "kill", "params": {"id": made["x"]}, "caller": made["sh"]})
        assert "error" not in got and not forwarded, got
        assert agent.sessions[made["x"]].state == "exited"
    finally:
        agent.mode, agent.home = "home", agent.host
        for s in list(agent.sessions.values()):
            if s.pane:
                await agent.rpc_kill(id=s.id)


@pytest.mark.integration
async def test_every_act_from_the_shell_crosses_with_no_caller_and_a_create_from_it_lifts_a_suspended_name(agent):
    await park_ticks(agent)
    sh = _home_shell(agent)
    lead = _home_shell(agent, "ao-lead", unattended=True, capabilities=["control"])
    agent._take_records(
        "laptop",
        [
            _record("ao-x-w", unattended=True, controllers=[f"{lead}@{agent.host}"]),
            _record(
                "ao-x-t",
                unattended=True,
                state="scheduled",
                start_at="2099-01-01T00:00:00Z",
                restart_ceiling={"count": 3, "at": "2026-10-16T00:00:00Z"},
            ),
        ],
        whole=True,
    )
    node = Node()
    _linked(agent, node)
    try:
        # a send and a kill on the node's session: forwarded as the person's, typed by *person* there
        for method, extra in (("send", {"text": "echo hi"}), ("keys", {"keys": ["Enter"]})):
            got = await agent._dispatch(
                {"id": 1, "method": method, "params": {"id": "ao-x-w@laptop", **extra}, "caller": sh}
            )
            assert "error" not in got, got
            assert node.acts[-1]["rpc"] == method and node.acts[-1]["caller"] is None
        # a session's act still crosses as that session
        got = await agent._dispatch(
            {"id": 2, "method": "send", "params": {"id": "ao-x-w@laptop", "text": "x"}, "caller": lead}
        )
        assert "error" not in got, got
        assert node.acts[-1]["caller"] == f"{lead}@{agent.host}"
        # set_start at the ceiling on a node's record: the node is told by the person, the home's copy spent
        got = await agent._dispatch(
            {
                "id": 3,
                "method": "set_start",
                "params": {"id": "ao-x-t@laptop", "start_at": "2099-01-02T00:00:00Z"},
                "caller": sh,
            }
        )
        assert "error" not in got, got
        assert node.acts[-1]["rpc"] == "set_start" and node.acts[-1]["caller"] is None
        assert agent.remote["laptop"]["ao-x-t"].restart_ceiling is None
        # a create under a suspended name: no creator crosses, and the supersession it made lifts the mark
        agent.remote["laptop"]["ao-x-w"].state = "closed"
        agent.remote["laptop"]["ao-x-w"].suspended = {"at": "t", "by": "person", "why": "claimed another id"}
        fresh = Session.from_dict(_record("ao-x-w", unattended=True))
        fresh.supersedes = [{"id": "ao-x-w", "at": fresh.created}]
        fresh.suspended = {"at": "t", "by": "person", "why": "claimed another id"}
        node.reply = {"record": fresh.to_dict(), "result": {"id": "ao-x-w", "host": "laptop"}}
        got = await agent._dispatch(
            {
                "id": 4,
                "method": "create",
                "params": {"name": "w", "dir": "/tmp/x", "host": "laptop", "unattended": True, **SHELL},
                "caller": sh,
            }
        )
        assert "error" not in got, got
        assert node.acts[-1]["rpc"] == "create" and node.acts[-1]["caller"] is None
        assert not node.acts[-1]["params"].get("controllers")  # the child's list holds only what was asked
        assert agent.remote["laptop"]["ao-x-w"].suspended is None
    finally:
        del agent._link_muxes["laptop"]


@pytest.mark.integration
async def test_a_shell_at_a_node_is_bound_to_its_node_as_a_person_there_is(agent):
    await park_ticks(agent)
    lead = _home_shell(agent, "ao-lead", unattended=True)
    agent._take_records(
        "laptop",
        [_record("ao-x-sh"), _record("ao-x-w", unattended=True), _record("ao-x-a", adapter="claude-code")],
        whole=True,
    )
    node = Node()
    _linked(agent, node)
    try:
        home_lead = f"{lead}@{agent.host}"
        for caller in ("ao-x-sh", None):  # the node's shell, as a person at the node
            got = await agent._forwarded(
                "laptop", {"rpc": "set_grants", "params": {"id": home_lead, "add": ["control"]}, "caller": caller}
            )
            assert "a person at laptop may set_grants only laptop's sessions" in got["error"], caller
        assert agent.sessions[lead].capabilities == []
        # an agent session at the node is no person: the gate refuses it before any bound
        got = await agent._forwarded(
            "laptop", {"rpc": "set_grants", "params": {"id": "ao-x-w", "add": ["control"]}, "caller": "ao-x-a"}
        )
        assert "error" in got and "a person at laptop" not in got["error"]
        # its node's own session: passed, and routed to the node as the person's
        got = await agent._forwarded(
            "laptop", {"rpc": "set_grants", "params": {"id": "ao-x-w", "add": ["control"]}, "caller": "ao-x-sh"}
        )
        assert "error" not in got, got
        assert node.acts[-1]["rpc"] == "set_grants" and node.acts[-1]["caller"] is None
        assert agent.remote["laptop"]["ao-x-w"].capabilities == ["control"]
        # a create from it lands on its own node, and one for another host is refused
        got = await agent._forwarded(
            "laptop",
            {
                "rpc": "create",
                "params": {"name": "c", "dir": "/tmp/x", "host": agent.host, **SHELL},
                "caller": "ao-x-sh",
            },
        )
        assert "a person at laptop may create only laptop's sessions" in got["error"]
    finally:
        del agent._link_muxes["laptop"]
