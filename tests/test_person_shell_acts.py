"""The person's own shell is the person (design §4.8 *The person's own shell is the person*, TD-801,
TD-802): `mail.as_person` passes it wherever a person passes an act — the acting gate, the usage gate's
`send`, a create's creator and the checks beside it, a suspended name, `set_start` at the ceiling,
`host_files`, the wake-budget refill. Each RPC is called with `caller=<the shell's id>`, as
`tests/test_person_only.py` does, never through the identity machinery."""

from __future__ import annotations

import subprocess

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.agent_common import RpcError
from sessionorc.client import LocalClient
from sessionorc.models import Session

SHELL = {"adapter": "shell", "argv": ["bash", "--norc", "--noprofile"]}


def _rec(sid: str, **kw) -> Session:
    base = {"name": sid, "kind": "interactive", "adapter": "shell", "dir": "/tmp", "state": "idle"}
    return Session(id=sid, **{**base, **kw})


def _not_shells() -> list[Session]:
    """Each still a session: an unattended shell, a shell with a controller, a role or a team, an agent."""
    return [
        _rec("ao-u", unattended=True),
        _rec("ao-c", controllers=["ao-x"]),
        _rec("ao-r", role="manager"),
        _rec("ao-t", team="t"),
        _rec("ao-a", adapter="claude-code"),
    ]


@pytest.mark.unit
def test_the_shell_passes_every_acting_rpc_and_each_near_miss_is_still_a_session():
    person_pane = _rec("ao-p")  # a person's interactive session: §9 invariant 5 refuses it to every session
    worker = _rec("ao-w", unattended=True, controllers=["ao-lead"])
    shell = _rec("ao-sh")
    records = {s.id: s for s in (person_pane, worker, shell, *_not_shells())}
    assert mail.as_person(None, records) and mail.as_person("ao-sh", records)
    assert not mail.as_person("ao-gone", records) and not mail.as_person(0, records)
    for method in sorted(mail.ACTING_RPCS):
        for target in ("ao-p", "ao-w", "ao-sh"):
            assert mail.act_gate(records, "ao-sh", method, {"id": target}) is None, (method, target)
    assert mail.act_gate(records, "ao-sh", "create", {"capabilities": ["control"]}) is None  # not attenuated
    for s in _not_shells():
        assert not mail.as_person(s.id, records)
        for method in ("send", "kill", "create", "decide"):
            assert mail.act_gate(records, s.id, method, {"id": "ao-p"}), (s.id, method)


async def _shell(person, tmp_path, name="sh") -> str:
    """What **Open shell here** makes: a person's create of a shell, interactive, controlling nobody."""
    d = tmp_path / name
    d.mkdir()
    return (await person.call("create", name=name, dir=str(d), **SHELL))["id"]


async def _kill_all(agent) -> None:
    async with LocalClient() as person:
        for s in list(agent.sessions.values()):
            if s.pane:
                await person.call("kill", id=s.id)


@pytest.mark.integration
async def test_the_usage_gate_and_a_create_from_the_shell_are_the_persons(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sh = await _shell(person, tmp_path)
        assert mail.person_shell(agent.sessions[sh])
        (tmp_path / "lead").mkdir()
        lead = (await person.call("create", name="lead", dir=str(tmp_path / "lead"), unattended=True, **SHELL))["id"]
        await person.call("set_grants", id=lead, add=["control"])
        (tmp_path / "w").mkdir()
        w = (
            await person.call("create", name="w", dir=str(tmp_path / "w"), unattended=True, controllers=[lead], **SHELL)
        )["id"]
        agent.sessions[w].gated = {"profile": "", "label": "wk", "pct": 90, "line": 70}
        agent._gate(sh, "send", {"id": w, "text": "go"})  # a person's send is the way past the gate
        with pytest.raises(RpcError, match="paused by the usage gate"):
            agent._gate(lead, "send", {"id": w, "text": "go"})
        agent.sessions[w].gated = None
        # a create from the shell: no creator in the child's list, the grants it asked for
        (tmp_path / "c").mkdir()
        got = await agent.rpc_create(name="c", dir=str(tmp_path / "c"), capabilities=["control"], caller=sh, **SHELL)
        assert got["controllers"] == [] and got["capabilities"] == ["control"]
        (tmp_path / "d").mkdir()
        got = await agent.rpc_create(name="d", dir=str(tmp_path / "d"), controllers=[w], caller=sh, **SHELL)
        assert got["controllers"] == [w]
        (tmp_path / "e").mkdir()
        got = await agent.rpc_create(name="e", dir=str(tmp_path / "e"), caller=lead, **SHELL)
        assert got["controllers"] == [lead]  # a session's create still adds its creator
        # its send and keys refill the target's wake budget, as a person's do
        agent.sessions[w].wake_refilled_at = None
        await agent.rpc_send(id=w, text="echo hi", caller=sh)
        assert agent.sessions[w].wake_refilled_at
        agent.sessions[w].wake_refilled_at = None
        await agent.rpc_keys(id=w, keys=["Enter"], caller=sh)
        assert agent.sessions[w].wake_refilled_at
        agent.sessions[w].wake_refilled_at = None
        await agent.rpc_keys(id=w, keys=["Enter"], caller=lead)
        assert agent.sessions[w].wake_refilled_at is None
    await _kill_all(agent)


@pytest.mark.integration
async def test_the_shell_starts_keeps_succeeds_and_lifts_as_the_person_does(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sh = await _shell(person, tmp_path)
        base = {"unattended": True, "prompt": "p", **SHELL}
        # start_of: starting a scheduled record early is an act on it, open to the person
        (tmp_path / "s").mkdir()
        sched = await person.call("create", name="s", dir=str(tmp_path / "s"), start_at="2099-01-01T00:00:00Z", **base)
        got = await agent.rpc_create(name="s", dir=str(tmp_path / "s"), start_of=sched["id"], caller=sh, **base)
        assert got["id"] == sched["id"] and agent.sessions[sched["id"]].state != "scheduled"
        # keep_mail: a closed member's mailbox handed to its successor
        (tmp_path / "k").mkdir()
        k = (await person.call("create", name="k", dir=str(tmp_path / "k"), **base))["id"]
        await person.call("kill", id=k)
        got = await agent.rpc_create(name="k", dir=str(tmp_path / "k"), keep_mail=True, caller=sh, **base)
        assert got["id"] == k and agent.sessions[k].pane  # the name's id, started again
        # succeeds: a renamed member
        (tmp_path / "old").mkdir()
        old = (await person.call("create", name="old", dir=str(tmp_path / "old"), supervised=True, **base))["id"]
        await person.call("kill", id=old)
        (tmp_path / "new").mkdir()
        got = await agent.rpc_create(name="new", dir=str(tmp_path / "new"), succeeds=old, caller=sh, **base)
        assert agent.sessions[old].superseded_by == got["id"]
        # a suspended name: a create under it, and Forget
        (tmp_path / "x").mkdir()
        x = (await person.call("create", name="x", dir=str(tmp_path / "x"), **base))["id"]
        await person.call("suspend", id=x)
        got = await agent.rpc_create(name="x", dir=str(tmp_path / "x"), caller=sh, **base)
        assert got["name"] == "x"
        (tmp_path / "y").mkdir()
        y = (await person.call("create", name="y", dir=str(tmp_path / "y"), **base))["id"]
        await person.call("suspend", id=y)
        await agent.rpc_remove(id=y, caller=sh)
        assert y not in agent.sessions
        # set_start at the restart ceiling: the person's new time spends the ceiling
        (tmp_path / "t").mkdir()
        t = await person.call("create", name="t", dir=str(tmp_path / "t"), start_at="2099-01-01T00:00:00Z", **base)
        agent.sessions[t["id"]].restart_ceiling = {"count": 5, "at": "2026-10-16T00:00:00Z"}
        await agent.rpc_set_start(id=t["id"], start_at="2099-01-02T00:00:00Z", caller=sh)
        assert agent.sessions[t["id"]].restart_ceiling is None
        # host_files: a person's read of a checkout, with no control grant on the shell
        (tmp_path / "repo").mkdir()
        (tmp_path / "repo" / "brief.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
        got = await agent.rpc_host_files(host=agent.host, dir=str(tmp_path / "repo"), paths=["brief.md"], caller=sh)
        assert "hello" in str(got)
        # the shell with a controller is a session again, on its next call
        await person.call("set_controllers", id=sh, add=[old])
        with pytest.raises(RpcError, match="needs the control grant"):
            await agent.rpc_host_files(host=agent.host, dir=str(tmp_path / "repo"), paths=["brief.md"], caller=sh)
    await _kill_all(agent)
