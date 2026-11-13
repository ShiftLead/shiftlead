"""The host agent runs the repo's start hooks before the pane of a tool that runs none of its own, and puts
their output into the first prompt after the brief (design §4.3 *The repo's start hooks*, *Before the pane*,
*Into the first prompt*, TD-1637)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from _stubs import ComposerStub
from conftest import wait_for

from sessionorc import adapters, mail, start_hooks
from sessionorc.adapters import LaunchSpec
from sessionorc.client import LocalClient

pytestmark = pytest.mark.integration

BRIEF = "You are a grinder. Read the ledger, then pick one entry."
PIN = '[agent-cadence]\nsource = "https://example.invalid/agent-cadence.git"\nref = "abc"\n'
STUB = """#!/bin/sh
here=$(dirname "$0")
cat > "$here/stdin"
env > "$here/env"
printf '\\033[31mhooked\\033[0m\\r\\n'
"""


class NoContextStub(ComposerStub):
    """A tool with no start context that runs an agent: its launch's prompt is handed back as the first prompt."""

    start_context = False

    def __init__(self) -> None:
        super().__init__(0)
        self.name = "nocontext0"

    def launch(self, *, profile, resume, prompt, unattended, cwd, name=""):
        spec = super().launch(profile=profile, resume=resume, prompt=None, unattended=unattended, cwd=cwd, name=name)
        return LaunchSpec(argv=spec.argv, first_prompt=prompt, adapter_id="11111111-2222-3333-4444-555555555555")


@pytest.fixture
def nocontext(monkeypatch):
    adapters.load_all()
    stub = NoContextStub()
    monkeypatch.setitem(adapters._REGISTRY, stub.name, stub)
    return stub


def _repo(tmp_path):
    repo = tmp_path / "w"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "cadence.toml").write_text(PIN)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
    return repo


def _launcher(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "agent-cadence").write_text(STUB)
    (bin_ / "agent-cadence").chmod(0o755)
    return bin_


async def _create(agent, c, repo, **kw) -> str:
    sid = (await c.call("create", name="w", dir=str(repo), adapter="nocontext0", unattended=True, **kw))["id"]

    async def painted() -> bool:
        return any(t.startswith(">>") for t in await agent.rpc_tail(sid, 3))

    assert await wait_for(painted, timeout=5), "the composer child never painted its prompt"
    return sid


async def test_the_hooks_output_follows_the_brief_in_the_pane_s_environment(agent, nocontext, tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    bin_ = _launcher(tmp_path)
    # the launcher is on the tmux server's PATH alone, as on a machine whose host agent runs under systemd
    agent.tmux.run("set-environment", "-g", "PATH", f"{bin_}:/usr/bin:/bin")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/nowhere")  # the host agent's own: never handed on
    async with LocalClient() as c:
        sid = await _create(agent, c, repo, prompt=BRIEF)
    rec = agent.sessions[sid]
    # the escapes and the carriage return stripped, the separator after the brief
    assert rec.first_prompt == f"{BRIEF}\n\n{mail.START_HOOKS_LINE}\nhooked"
    seen = dict(line.split("=", 1) for line in (bin_ / "env").read_text().splitlines() if "=" in line)
    assert seen["SHIFTLEAD_SESSION"] == sid and seen["CADENCE_ATTENTION_SCOPE"] == "own"
    assert "CLAUDE_PROJECT_DIR" not in seen
    assert json.loads((bin_ / "stdin").read_text()) == {
        "cwd": str(repo),
        "session_id": "11111111-2222-3333-4444-555555555555",
        "source": "startup",
    }


async def test_a_launch_with_no_first_prompt_runs_no_hooks(agent, nocontext, tmp_path):
    repo = _repo(tmp_path)
    bin_ = _launcher(tmp_path)
    agent.tmux.run("set-environment", "-g", "PATH", f"{bin_}:/usr/bin:/bin")
    async with LocalClient() as c:
        sid = await _create(agent, c, repo)
    assert agent.sessions[sid].first_prompt is None
    assert not (bin_ / "stdin").exists()


async def test_a_pinned_repo_with_no_launcher_says_so_and_an_unhooked_one_adds_nothing(agent, nocontext, tmp_path):
    repo = _repo(tmp_path)  # pinned, no launcher on the server's PATH: the install notice is the text
    agent.tmux.run("set-environment", "-g", "PATH", "/usr/bin:/bin")
    async with LocalClient() as c:
        sid = await _create(agent, c, repo, prompt=BRIEF)
    assert agent.sessions[sid].first_prompt == f"{BRIEF}\n\n{mail.START_HOOKS_LINE}\n{start_hooks.NO_LAUNCHER}"
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "w").mkdir()
    async with LocalClient() as c:
        sid = (
            await c.call("create", name="u", dir=str(plain / "w"), adapter="nocontext0", unattended=True, prompt=BRIEF)
        )["id"]
    assert agent.sessions[sid].first_prompt == BRIEF  # no runner, nothing printed: the brief alone


class _Tmux:
    def __init__(self, glob, names):
        self.glob, self.names = glob, names

    def global_environment(self):
        return self.glob

    def update_environment(self):
        return self.names


@pytest.mark.unit
def test_pane_env_follows_tmux_s_order():
    own = {"SSH_AUTH_SOCK": "/own/sock", "PATH": "/own/bin", "CLAUDE_PROJECT_DIR": "/p", "HOMEONLY": "1"}
    glob = {"PATH": "/srv/bin", "DISPLAY": ":9", "KEEP": "k"}
    env = start_hooks.pane_env(_Tmux(glob, ["SSH_AUTH_SOCK", "DISPLAY"]), own, {"SHIFTLEAD_SESSION": "s"}, ["KEEP"])
    # the server's, then update-environment's names from the host agent's own (DISPLAY absent there: removed),
    # then the attempt's, then the unset names; nothing else of the host agent's
    assert env == {"PATH": "/srv/bin", "SSH_AUTH_SOCK": "/own/sock", "SHIFTLEAD_SESSION": "s"}
    # the option unread: tmux's default list
    env = start_hooks.pane_env(_Tmux(glob, None), own, {})
    assert env["SSH_AUTH_SOCK"] == "/own/sock" and "DISPLAY" not in env
    # the server unread: the host agent's own with the attempt's over it, CLAUDE_PROJECT_DIR dropped
    env = start_hooks.pane_env(_Tmux(None, None), own, {"PATH": "/a"})
    assert env == {"SSH_AUTH_SOCK": "/own/sock", "PATH": "/a", "HOMEONLY": "1"}


def test_tmux_s_default_update_environment_is_the_list(agent):
    names = agent.tmux.update_environment()
    assert names is not None and set(start_hooks.TMUX_UPDATE_ENVIRONMENT) <= set(names)


@pytest.mark.unit
def test_the_text_is_cleaned_and_capped():
    raw = "\x1b[1;31mred\x1b[0m \x1b]0;title\x07ok\r\n\x9b2Jbell\x07\x7f\tend"
    assert start_hooks.clean(raw) == "red ok\n2Jbell\tend"
    big = "é" * (start_hooks.START_HOOKS_TEXT_MAX)  # two bytes each: twice the cap
    cut = start_hooks.clean(big)
    body, line = cut.rsplit("\n", 1)
    assert line == start_hooks.CUT_LINE and len(body.encode()) <= start_hooks.START_HOOKS_TEXT_MAX
    assert body == "é" * (start_hooks.START_HOOKS_TEXT_MAX // 2)  # on a character boundary
    assert start_hooks.with_hooks(BRIEF, " \x1b[0m\r\n ") == BRIEF  # empty once cleaned: nothing added


@pytest.mark.unit
def test_os_environ_is_untouched_by_pane_env():
    before = dict(os.environ)
    start_hooks.pane_env(_Tmux({"X": "1"}, []), os.environ, {"Y": "2"}, ["PATH"])
    assert dict(os.environ) == before
