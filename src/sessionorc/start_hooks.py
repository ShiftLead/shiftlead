"""The repo's start hooks, run for a session whose tool runs none of its own (design §4.3 *The repo's start
hooks*, *A repo's start hooks are every adapter's to run*, TD-035, TD-1637).

One runner, two callers: Gemini CLI's `SessionStart` hook, inside the pane, and the host agent's create and
resume before the pane of an adapter `adapters.core_runs_start_hooks` names. It reads only its parameters —
the payload, the project, the environment — never the process's own, so the host agent can hand it the
environment the pane gets.

In a pinned repo (`cadence.hook_pinned`) it runs `agent-cadence hook session-start` from `env`'s PATH, as
Claude Code's layer line does (`CADENCE_HOOK_LINE`); otherwise the main checkout's copied runner. The payload
goes on the run's stdin in both modes, never the caller's own stdin.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# agent-cadence's copied runner (design §4.3 *A repo's start hooks are every adapter's to run*), the main checkout's
START_HOOKS = ("scripts", "cadence_hooks.sh")
START_HOOKS_TIMEOUT = 150  # seconds: the runner's own bound, > 5 children × its 25 s child timeout
GIT_TIMEOUT = 10  # seconds: each `git worktree list` read, `hook_pinned`'s and the copied mode's
# the bound on the whole run at a launch (design §4.3 *Before the pane*): create is bounded at `CALL_TIMEOUT`
START_HOOKS_LAUNCH_TIMEOUT = 60
DRAIN_TIMEOUT = 2  # seconds: the pipes read after a lapsed run's group is killed
# a pinned repo's (design §4.2, TD-1023): the launcher's word, from PATH, and the two sentences agent-cadence's
# seed line prints when it cannot run the pin (exit 2) or there is none, copied from the seed (a parity test)
PINNED_HOOK = ("agent-cadence", "hook", "session-start")
PIN_FAILED = (
    "agent-cadence: the launcher could not run the pin in docs/cadence.toml (it said why above), "
    "so the cadence session-start hooks did not run (TD-129)"
)
NO_LAUNCHER = (
    "agent-cadence: this repo pins agent-cadence in docs/cadence.toml but no agent-cadence launcher is on PATH, "
    "so the cadence session-start hooks did not run; install it once per machine: clone agent-cadence at its "
    "latest tag, then run: install -m 755 launcher/agent_cadence.py ~/.local/bin/agent-cadence"
)
# what a run bounded by a deadline returns when any of its calls lapses (design §4.3 *Before the pane*): the
# same words in both modes, since a copied-runner repo has no `agent-cadence` command
START_HOOKS_TIMED_OUT = "The repo's start hooks did not finish in time; run them yourself."

_TODAY = object()  # `on_timeout`'s default: today's behaviour, "" in the copied mode and `PIN_FAILED` pinned


class _Lapsed(Exception):
    """A call of a run bounded by a deadline ran past what was left of it; `out` what it printed."""

    def __init__(self, out: str = "") -> None:
        super().__init__("lapsed")
        self.out = out


def start_hooks(
    payload: Mapping[str, Any],
    *,
    project: Path | str,
    env: Mapping[str, str],
    deadline: float | None = None,
    on_timeout: Any = _TODAY,
) -> str:
    """Run the repo's start hooks for the session `payload` names (its `cwd`, the run's directory), and
    return what they printed.

    Pinned (`cadence.hook_pinned(project)`): the launcher's stdout whatever its exit, then `PIN_FAILED`
    after an exit 2, and `NO_LAUNCHER` with none on `env`'s PATH — never "" (design §4.2, TD-1023).
    Otherwise the main checkout's runner — the first entry of `git worktree list` — else the project's own
    copy, only where it is executable; its stdout, or "" when there is none or it failed.

    `deadline` (seconds) bounds the whole run: every call takes the lesser of its own bound and what is
    left, and a lapse in any of them returns what the run printed, then `on_timeout`
    (`START_HOOKS_TIMED_OUT` at a launch). With none, each call keeps its own bound, and a lapse is
    today's: `PIN_FAILED` alone in the pinned mode, "" in the copied one."""
    end = None if deadline is None else time.monotonic() + deadline
    cwd = Path(str(payload.get("cwd") or project))
    pinned = False  # a lapse in `hook_pinned`'s own read is the copied mode's, as an unread list was
    try:
        pinned = _hook_pinned(Path(project), end)
        if pinned:
            return _pinned_hooks(payload, cwd, env, end)
        return _copied_hooks(payload, Path(project), cwd, env, end)
    except _Lapsed as lapse:
        notice = (PIN_FAILED if pinned else "") if on_timeout is _TODAY else str(on_timeout)
        return "\n".join(x for x in (lapse.out.rstrip("\n"), notice) if x)


def _left(own: float, end: float | None) -> float:
    """A call's bound: its own, or less where a deadline leaves less; a deadline spent is a lapse."""
    if end is None:
        return own
    left = end - time.monotonic()
    if left <= 0:
        raise _Lapsed()
    return min(own, left)


def _hook_pinned(project: Path, end: float | None) -> bool:
    from sessionorc import cadence

    if end is None:
        return cadence.hook_pinned(project)
    try:
        return cadence.hook_pinned(project, timeout=_left(GIT_TIMEOUT, end), lapse=True)
    except subprocess.TimeoutExpired:
        raise _Lapsed() from None


def _main_checkout(project: Path, end: float | None) -> Path:
    """The first entry of `git worktree list`, else `project`."""
    try:
        listed = subprocess.run(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=_left(GIT_TIMEOUT, end),
        ).stdout
    except subprocess.TimeoutExpired:
        if end is not None:
            raise _Lapsed() from None
        listed = ""
    except (OSError, subprocess.SubprocessError, ValueError):
        listed = ""
    first = listed.splitlines()[0] if listed else ""
    return Path(first.removeprefix("worktree ")) if first.startswith("worktree ") else project


def _copied_hooks(
    payload: Mapping[str, Any], project: Path, cwd: Path, env: Mapping[str, str], end: float | None
) -> str:
    runner = _main_checkout(project, end).joinpath(*START_HOOKS)
    if not (runner.is_file() and os.access(runner, os.X_OK)):
        return ""
    try:
        done = _run([str(runner), "--session-start"], payload, cwd, env, end)
    except _Lapsed:
        if end is not None:
            raise
        return ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return done[1]


def _pinned_hooks(payload: Mapping[str, Any], cwd: Path, env: Mapping[str, str], end: float | None) -> str:
    """The seed line's pinned mode: the launcher's `hook session-start` and what it printed."""
    launcher = shutil.which(PINNED_HOOK[0], path=env.get("PATH", ""))
    if launcher is None:
        return NO_LAUNCHER
    try:
        rc, out = _run([launcher, *PINNED_HOOK[1:]], payload, cwd, env, end)
    except _Lapsed:
        if end is not None:
            raise
        return PIN_FAILED  # a first fetch can outlast the bound
    except (OSError, subprocess.SubprocessError, ValueError):
        return PIN_FAILED
    if rc == 2:
        return "\n".join(x for x in (out.rstrip("\n"), PIN_FAILED) if x)
    return out


def _run(
    argv: list[str], payload: Mapping[str, Any], cwd: Path, env: Mapping[str, str], end: float | None
) -> tuple[int, str]:
    """One run in a group of its own, the payload on its stdin: a lapse kills the group and drains the
    pipes, so no grandchild holding a pipe outlives the bound (`subprocess.run(timeout=)` kills the child
    alone, then waits on the pipes). `_Lapsed` carries what the run printed before it. A deadline already
    spent starts nothing."""
    timeout = _left(START_HOOKS_TIMEOUT, end)
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd if cwd.is_dir() else None,
        env=dict(env),
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(json.dumps(dict(payload)), timeout=timeout)
    except subprocess.TimeoutExpired as e:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        # what was read before the lapse, kept should the drain not end (a grandchild of another session
        # holding the pipe): `TimeoutExpired.output` is the raw bytes even in text mode
        got = e.output
        out = got.decode(errors="replace") if isinstance(got, bytes) else (got or "")
        with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
            out, _ = proc.communicate(timeout=DRAIN_TIMEOUT)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=DRAIN_TIMEOUT)
        for pipe in (proc.stdout, proc.stderr):
            with contextlib.suppress(OSError):
                pipe.close()
        raise _Lapsed(out or "") from None
    return proc.returncode, out


# --- at a launch: the host agent's road (design §4.3 *The repo's start hooks*, *Into the first prompt*) ---

# tmux's documented default `update-environment`, used where reading the option alone fails
TMUX_UPDATE_ENVIRONMENT = (
    "DISPLAY",
    "KRB5CCNAME",
    "SSH_ASKPASS",
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",
    "SSH_CONNECTION",
    "WINDOWID",
    "XAUTHORITY",
)
START_HOOKS_TEXT_MAX = 16 * 1024  # bytes of UTF-8 the first prompt carries of the hooks' output
CUT_LINE = "… (the start hooks' output was cut at 16 KiB)"
# an escape sequence whole — CSI, OSC (ended by BEL or ST) and the two-byte forms — then any control
# character left but newline and tab: C0, DEL and C1 (an 8-bit CSI among them)
_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-Z\\-_]")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x80-\x9f]")


def pane_env(
    tmux: Any, own: Mapping[str, str], attempt: Mapping[str, str], unset: tuple[str, ...] | list[str] = ()
) -> dict[str, str]:
    """The environment the pane gets, built in tmux's own order (`new-session` execs the argv with its `-e`
    pairs over it, spawning no shell): the server's global environment; then the names `update-environment`
    lists, each set from the host agent's own (`own`) or removed where absent there; then the attempt's
    env; then `unset`'s names removed. Where the global read fails, `own` with the attempt's env over it.
    `CLAUDE_PROJECT_DIR` is dropped either way: the runner is given its project."""
    base = tmux.global_environment()
    if base is None:
        env = {**own, **attempt}
    else:
        env = dict(base)
        names = tmux.update_environment()
        for name in TMUX_UPDATE_ENVIRONMENT if names is None else names:
            if name in own:
                env[name] = own[name]
            else:
                env.pop(name, None)
        env.update(attempt)
    for name in unset:
        env.pop(name, None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def clean(text: str) -> str:
    """The hooks' output made safe for a bracketed paste and capped: escapes and control characters out,
    surrounding whitespace trimmed, cut at `START_HOOKS_TEXT_MAX` bytes on a character boundary with
    `CUT_LINE` after it (outside the cap)."""
    text = _CONTROLS.sub("", _ESCAPES.sub("", text)).strip()
    raw = text.encode("utf-8")
    if len(raw) <= START_HOOKS_TEXT_MAX:
        return text
    return raw[:START_HOOKS_TEXT_MAX].decode("utf-8", errors="ignore").rstrip() + "\n" + CUT_LINE


def with_hooks(first_prompt: str, text: str) -> str:
    """The launch's first prompt with the hooks' output after the brief, under `mail.START_HOOKS_LINE`; a text
    empty once cleaned adds nothing, not even the separator."""
    from sessionorc.mail import START_HOOKS_LINE

    told = clean(text)
    return f"{first_prompt}\n\n{START_HOOKS_LINE}\n{told}" if told else first_prompt
