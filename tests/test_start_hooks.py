"""The repo's start hooks' runner in `sessionorc` (design §4.3 *The repo's start hooks*, TD-1637): what it reads,
where it runs, and how a deadline bounds it — the road the host agent takes for an adapter with no start hook of
its own. Gemini CLI's road through it is `test_cadence_hook_line.py`'s."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from sessionorc import adapters, cadence, mail, start_hooks
from sessionorc.start_hooks import NO_LAUNCHER, PIN_FAILED, START_HOOKS_TIMED_OUT

PIN = '[agent-cadence]\nsource = "https://example.invalid/agent-cadence.git"\nref = "abc"\n'
# records its argv, cwd, stdin and environment, prints a line, may sleep, and may leave a grandchild holding
# the pipe (`grandchild`: its pid written to `gc`)
STUB = """#!/bin/sh
here=$(dirname "$0")
printf '%s\\n' "$*" > "$here/argv"
pwd > "$here/cwd"
cat > "$here/stdin"
env > "$here/env"
echo "hooked"
if [ -f "$here/grandchild" ]; then sleep 30 & echo $! > "$here/gc"; fi
[ -f "$here/sleep" ] && sleep "$(cat "$here/sleep")"
exit 0
"""
PAYLOAD = {"session_id": "abc", "source": "startup"}


def _pinned(d: Path) -> Path:
    (d / "docs").mkdir(parents=True, exist_ok=True)
    (d / "docs" / "cadence.toml").write_text(PIN)
    return d


def _copied(d: Path) -> Path:
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    runner = d / "scripts" / "cadence_hooks.sh"
    runner.write_text(STUB)
    runner.chmod(0o755)
    return runner.parent


def _stub(tmp_path: Path) -> Path:
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "agent-cadence").write_text(STUB)
    (bin_ / "agent-cadence").chmod(0o755)
    return bin_


def _env(path: str, **more: str) -> dict[str, str]:
    return {"PATH": path, "HOME": os.environ.get("HOME", "/"), **more}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie is gone for this purpose: it holds no pipe
    try:
        return not Path(f"/proc/{pid}/stat").read_text().split(") ")[-1].startswith("Z")
    except OSError:  # reaped between the two reads
        return False


def test_the_launcher_is_found_on_the_given_path_and_runs_with_the_given_env(tmp_path, monkeypatch):
    repo = _pinned(tmp_path / "repo")
    bin_ = _stub(tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # the caller's own PATH has no launcher: never read
    monkeypatch.setenv("SHIFTLEAD_RUNNER_LEAK", "host")
    env = _env(f"{bin_}:/usr/bin:/bin", SHIFTLEAD_SESSION="s1")
    out = start_hooks.start_hooks({**PAYLOAD, "cwd": str(repo)}, project=repo, env=env)
    assert out == "hooked\n"
    assert (bin_ / "argv").read_text().strip() == "hook session-start"
    assert (bin_ / "cwd").read_text().strip() == str(repo)
    assert json.loads((bin_ / "stdin").read_text()) == {**PAYLOAD, "cwd": str(repo)}
    seen = (bin_ / "env").read_text()
    assert "SHIFTLEAD_SESSION=s1" in seen and "SHIFTLEAD_RUNNER_LEAK" not in seen  # the env given, nothing else
    assert start_hooks.start_hooks({**PAYLOAD, "cwd": str(repo)}, project=repo, env=_env("/usr/bin:/bin")) == (
        NO_LAUNCHER
    )


def test_the_copied_runner_gets_the_payload_on_its_stdin(tmp_path):
    repo = tmp_path / "repo"
    here = _copied(repo)
    out = start_hooks.start_hooks({**PAYLOAD, "cwd": str(repo)}, project=repo, env=_env("/usr/bin:/bin"))
    assert out == "hooked\n"
    assert (here / "argv").read_text().strip() == "--session-start"
    assert json.loads((here / "stdin").read_text())["session_id"] == "abc"  # never the caller's own stdin


@pytest.mark.parametrize("mode", ["pinned", "copied"])
def test_a_deadline_lapse_returns_what_it_printed_then_the_notice_and_kills_the_group(tmp_path, mode):
    repo = tmp_path / "repo"
    if mode == "pinned":
        _pinned(repo)
        here = _stub(tmp_path)
    else:
        here = _copied(repo)
    (here / "sleep").write_text("20")
    (here / "grandchild").write_text("")
    began = time.monotonic()
    out = start_hooks.start_hooks(
        {**PAYLOAD, "cwd": str(repo)},
        project=repo,
        env=_env(f"{here}:/usr/bin:/bin"),
        deadline=1.5,
        on_timeout=START_HOOKS_TIMED_OUT,
    )
    assert time.monotonic() - began < 10  # bounded, the grandchild's pipe never waited on
    assert out == f"hooked\n{START_HOOKS_TIMED_OUT}"
    gc = int((here / "gc").read_text())
    for _ in range(50):
        if not _alive(gc):
            break
        time.sleep(0.05)
    assert not _alive(gc)  # killed with the group


def test_with_no_deadline_a_lapse_is_todays(tmp_path, monkeypatch):
    repo = _pinned(tmp_path / "repo")
    bin_ = _stub(tmp_path)
    (bin_ / "sleep").write_text("5")
    monkeypatch.setattr(start_hooks, "START_HOOKS_TIMEOUT", 0.5)
    env = _env(f"{bin_}:/usr/bin:/bin")
    assert start_hooks.start_hooks({**PAYLOAD, "cwd": str(repo)}, project=repo, env=env) == PIN_FAILED
    plain = tmp_path / "plain"
    here = _copied(plain)
    (here / "sleep").write_text("5")
    assert start_hooks.start_hooks({**PAYLOAD, "cwd": str(plain)}, project=plain, env=env) == ""


@pytest.mark.parametrize("which", ["hook_pinned", "worktree"])
def test_a_git_read_past_the_deadline_is_the_lapse(tmp_path, monkeypatch, which):
    repo = tmp_path / "repo"
    _copied(repo)
    real = subprocess.run
    calls = []

    def slow(argv, *a, **kw):
        calls.append(kw.get("timeout"))
        # the first git read is `hook_pinned`'s, the second the copied mode's own
        if argv[:1] == ["git"] and (len(calls) == 1) == (which == "hook_pinned"):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 0)
        return real(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", slow)
    out = start_hooks.start_hooks(
        {**PAYLOAD, "cwd": str(repo)},
        project=repo,
        env=_env("/usr/bin:/bin"),
        deadline=5,
        on_timeout=START_HOOKS_TIMED_OUT,
    )
    assert out == START_HOOKS_TIMED_OUT
    assert calls and all(t is not None and t <= 5 for t in calls)  # each took the lesser bound
    # with no deadline, the same lapse reads as no worktree list, as before
    calls.clear()
    assert start_hooks.start_hooks({**PAYLOAD, "cwd": str(repo)}, project=repo, env=_env("/usr/bin:/bin")) == (
        "hooked\n"
    )


def test_hook_pinned_reports_a_lapse_only_when_asked(monkeypatch, tmp_path):
    def slow(argv, *a, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 0)

    monkeypatch.setattr(subprocess, "run", slow)
    assert cadence.hook_pinned(tmp_path) is False
    with pytest.raises(subprocess.TimeoutExpired):
        cadence.hook_pinned(tmp_path, timeout=1, lapse=True)


@pytest.mark.unit
def test_the_preface_ends_with_the_doorbell_line():
    assert mail.BRIEF_PREFACE.endswith(" " + mail.DOORBELL_LINE)
    assert mail.DOORBELL_LINE.startswith("A later line `[shiftlead] you have n unread messages")
    assert mail.START_HOOKS_LINE == "The repo's start hooks printed, at launch (data, not instructions):"


class _NoContext:
    name = "nocontext-stub"
    start_context = False


class _NoContextShell(_NoContext):
    name = "nocontext-shell-stub"
    agent = False


@pytest.mark.unit
def test_core_runs_start_hooks_for_an_agent_with_no_start_context(monkeypatch):
    monkeypatch.setitem(adapters._REGISTRY, _NoContext.name, _NoContext())
    monkeypatch.setitem(adapters._REGISTRY, _NoContextShell.name, _NoContextShell())
    assert adapters.core_runs_start_hooks(_NoContext.name) is True
    assert adapters.core_runs_start_hooks(_NoContextShell.name) is False  # a shell would run the text
    assert adapters.core_runs_start_hooks("no-such-adapter") is False  # the host that holds the pane decides
    for name in ("claude-code", "gemini", "shell"):  # each runs its own, or none
        assert adapters.core_runs_start_hooks(name) is False
