"""The Tools page's tools shell (design §4.2b *The tools shell*, §4.1, §9 invariants 3 and 11, TD-1972): a `shell`
session with no parent, its id `ao--tools-…`, no run log, its pane read by the person alone, a send keeping no
text, and nothing of its pane captured by the tick, a composer read, a wake or a hook."""

import asyncio
from pathlib import Path

import pytest
from conftest import park_ticks, wait_for

from sessionorc import naming, paths
from sessionorc.agent import RpcError
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Session


def test_the_ids_no_name_can_yield():
    assert naming.tools_id("claude-code", "Paul_K") == "ao--tools-claude-code-paul-k"
    assert naming.tools_install_id("gemini") == "ao--tools-install-gemini"
    assert naming.is_tools("ao--tools-install-gemini") and naming.is_tools("ao--tools-grok-x@node")
    assert not naming.is_tools("ao-tools-x") and not naming.is_tools("ao-shiftlead-tools")
    # `slug` strips a leading `-`, so neither a directory nor a name ever gives `ao--` (§4.1's reservation)
    for scope, name in (("tools", "x"), ("-tools-", "-tools-install-x"), ("--", "--tools")):
        assert not naming.base_id(Path("/tmp") / scope, None, name).startswith(naming.TOOLS_PREFIX)
    assert naming.adopted_name("ao--tools-grok-paul") == "tools-grok-paul"
    assert naming.adopted_name("ao-shiftlead-x") == "shiftlead-x"


def test_the_capture_reads_nothing_of_a_tools_shell_unless_asked_for_the_person():
    from sessionorc.tmux import Tmux

    t = Tmux.__new__(Tmux)
    calls = []
    t.run = lambda *a, **k: calls.append(a) or type("R", (), {"returncode": 0, "stdout": "secret\n"})()
    assert t.capture_tail("ao--tools-install-gemini", 5) == [] and not calls
    assert t.capture_tail("ao--tools-install-gemini", 5, tools=True) == ["secret"] and calls


def test_a_tools_shell_is_never_rung():
    from sessionorc.agent import HostAgent

    s = Session(
        id="ao--tools-claude-code-paul", name="tools-claude-code-paul", kind="interactive", adapter="shell", dir=""
    )
    assert HostAgent._bell_blocked(HostAgent.__new__(HostAgent), s, None) == "a tools shell"


pytestmark = pytest.mark.integration


async def test_an_install_shell_end_to_end(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as c:
        s = await c.call("tools_install", tool="claude-code")
        sid = s["id"]
        assert sid == "ao--tools-install-claude-code" and s["name"] == "tools-install-claude-code"
        assert s["log"] is False and s["run_log"] is None and s["adapter"] == "shell"
        assert s["dir"] == str(Path.home()) and not s["controllers"] and not s["role"]
        assert not paths.runs_dir().exists() or not list(paths.runs_dir().glob(f"{sid}*"))
        line = agent.sessions[sid].sends[0]
        # the host agent's own typed command is recorded, by the system, and typed with no Enter
        assert line.from_ == "system" and line.text == adapters_install("claude-code")
        assert await wait_for(lambda: any(adapters_install("claude-code") in r for r in _person_tail(agent, sid)))

        # one of each: a second press reopens it
        again = await c.call("tools_install", tool="claude-code")
        assert again["id"] == sid and len(agent.sessions[sid].sends) == 1

        # every read of its pane is the person's
        assert any(adapters_install("claude-code") in r for r in await c.call("tail", id=sid, lines=5))
        async with LocalClient(caller="ao-repo-worker") as w:
            for method in ("tail", "explain"):
                with pytest.raises(AgentError, match="cannot"):
                    await w.call(method, id=sid)
            # a session cannot open one
            with pytest.raises(AgentError, match="cannot open an install shell"):
                await w.call("tools_install", tool="claude-code")
        # a send keeps no text: what the person types there (a pasted key) is never on the record
        await c.call("keys", id=sid, keys=["C-u"])
        assert agent.sessions[sid].sends[-1].text == ""

        with pytest.raises(AgentError, match="no adapter|unknown"):
            await c.call("tools_install", tool="no-such-tool")

    # the tick keeps nothing of its pane
    await agent.tick()
    rec = agent.sessions[sid]
    assert rec.tail == [] and rec.title is None and rec.screen_hash is None and rec.last_output is None
    assert rec.pane is True

    # a hook from it is dropped, a permission answered without a waiter
    before = (rec.state, rec.hook_seen_at)
    assert await agent.rpc_hook(sid, kind="permission", text="Bash(ls)") is None
    assert await agent.rpc_hook(sid, kind="stop") is None
    assert (rec.state, rec.hook_seen_at) == before and not rec.pendings


async def test_a_login_shell_passes_the_same_checks_on_a_fixture(agent, tmp_path):
    """A login's tools shell on a fixture home: the login's environment, the sign-in typed, no run log, and
    every read and send kept to the person (§4.2b)."""
    await park_ticks(agent)
    home = tmp_path / "claude-fixture"
    home.mkdir()
    s = await agent._login_shell("claude-code", "Fixture_Login", home)
    sid = s["id"]
    assert sid == "ao--tools-claude-code-fixture-login" and s["log"] is False and s["run_log"] is None
    assert agent.sessions[sid].sends[0].text == "claude" and agent.sessions[sid].sends[0].from_ == "system"
    env = await asyncio.to_thread(agent.tmux.run, "show-environment", "-t", f"={sid}", "CLAUDE_CONFIG_DIR")
    assert env.stdout.strip() == f"CLAUDE_CONFIG_DIR={home}"
    async with LocalClient(caller="ao-repo-worker") as w:
        for method in ("tail", "explain"):
            with pytest.raises(AgentError, match="cannot"):
                await w.call(method, id=sid)
    async with LocalClient() as c:
        await c.call("keys", id=sid, keys=["x"])
        assert agent.sessions[sid].sends[-1].text == ""
    await agent.tick()
    rec = agent.sessions[sid]
    assert rec.tail == [] and rec.title is None and rec.screen_hash is None
    assert await agent.rpc_hook(sid, kind="permission", text="Bash(ls)") is None and not rec.pendings


async def test_a_pane_with_the_prefix_and_no_record_is_adopted_as_a_tools_shell(agent, tmp_path):
    await park_ticks(agent)
    sid = "ao--tools-grok-paul"
    await asyncio.to_thread(agent.tmux.new_session, sid, tmp_path, ["bash", "--norc"], {})
    await agent.tick()
    rec = agent.sessions[sid]
    assert rec.name == "tools-grok-paul" and rec.log is False and rec.tail == [] and rec.title is None


async def test_a_session_in_a_directory_named_tools_is_untouched(agent, tmp_path):
    d = tmp_path / "tools"
    d.mkdir()
    async with LocalClient() as c:
        s = await c.call("create", name="tools", dir=str(d), adapter="shell", argv=["bash", "--norc"])
        assert not naming.is_tools(s["id"]) and s["log"] is True and s["run_log"]
        await c.call("send", id=s["id"], text="echo plain-shell-line")
        assert await wait_for(lambda: any("plain-shell-line" in r for r in _person_tail(agent, s["id"])))
        # a session reads it as ever, and its send is kept
        async with LocalClient(caller="ao-repo-worker") as w:
            rows = await w.call("tail", id=s["id"], lines=5)
        assert any("plain-shell-line" in r for r in rows)
        assert agent.sessions[s["id"]].sends[-1].text == "echo plain-shell-line"


async def test_a_tools_shell_refuses_an_id_not_its_own(agent):
    with pytest.raises(RpcError, match="not a tools shell"):
        await agent._tools_shell("ao-shiftlead-x", "", {})


def adapters_install(tool: str) -> str:
    from sessionorc import adapters

    return adapters.get(tool).install_command()


def _person_tail(agent, sid: str) -> list[str]:
    return agent.tmux.capture_tail(sid, 10, tools=naming.is_tools(sid))
