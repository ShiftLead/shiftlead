#!/usr/bin/env python3
"""The adapter conformance suite's live walk (design §4.3 *The conformance suite*, TD-784).

    pdm run conformance claude-code --profile conformance [--capture]

Walks the life a session has with the real tool: a launch with the id the adapter chose, the first
hook, a short prompt (`working` → `idle`), a `send` the composer confirms, a permission seen as
`needs-you`, a doorbell ringing for a mail the walk sends as the person, a resume with the same id,
and the transcript read back. Each step prints `ok` or `FAIL` with what it read; the exit is 0 only
when every step held.

**Two homes.** A scratch `SHIFTLEAD_HOME` under a short path (a unix socket's path is capped), where the
walk starts its own host agent on a private tmux socket and stops it by the pid it holds, never by a
name; and the *tool's* home, the named profile's `config_dir`, signed in, where the tool writes its
chats. The profile is read from the live home's `profiles.yml` (read, never written) and declared in
the scratch home with `permission_prompts: ask`, so the unattended launch asks its permissions. The
session runs in a scratch directory.

It spends a few requests of the profile it names, so it refuses to run in CI (`CI` set), without
`--profile`, and on a profile with no `config_dir` of its own — none, the tool's default, or one another
profile names (that is the person's own tool home).

`--capture` writes what the tool handed the adapter's hook — the hook payloads and the status line's —
under `tests/conformance/fixtures/<adapter>/captured/`, with the pane titles the tool set: the fixtures
the offline suite reads once they are named in its manifest.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(SRC))

import look_home  # noqa: E402 — the scratch home's helpers: the refusal of the live home, the agent child

WALK_NAME = "conformance-walk"
FIRST_HOOK_WAIT = 120.0  # the tool's start, its first hook, the record `idle` by hook
TURN_WAIT = 300.0  # one short turn
SESSION_END_WAIT = 15.0  # a killed tool's own end hook
PERMISSION_PROMPT = "Use your shell tool to run exactly this command, then stop: touch conformance-permission.txt"
SHORT_PROMPT = "Reply with the one word: ready. Use no tools."
MAIL_TEXT = "The conformance walk's mail. Read it with `ao inbox`, then stop; nothing else is asked."
# The launch arguments that make each tool ask every permission, whatever its own default: Claude Code's
# is `auto` (2.1.302), whose classifier allowed the walk's `touch` before any hook saw a permission (TD-784).
ASKING_ARGS = {"claude-code": ["--permission-mode", "manual"]}


class Refused(Exception):
    pass


class StepFailed(Exception):
    pass


def refusal(env: dict[str, str], profile: str | None) -> str | None:
    """Why the walk may not run here, or None: never in CI, never without a profile named."""
    if env.get("CI"):
        return "CI is set: the live walk spends a profile's requests and never runs in CI"
    if not profile:
        return "--profile is required: the walk runs only on a profile set aside for it"
    return None


def scratch_profile(adapter: str, name: str, live_profiles: Path) -> dict[str, Any]:
    """The named profile's entry from the live home's `profiles.yml`, as the scratch home declares it:
    `permission_prompts: ask` and the tool's asking arguments (`ASKING_ARGS`), so the walk sees a permission. Refused when it is not there, names
    another adapter, or has no `config_dir` of its own."""
    import yaml

    from shiftlead import profiles

    try:
        known, _default = profiles.load(live_profiles)
    except (OSError, ValueError) as e:
        raise Refused(f"{live_profiles}: {e}") from None
    prof = known.get(name)
    if prof is None or not live_profiles.is_file():
        raise Refused(f"no profile {name!r} in {live_profiles} (known: {sorted(known)})")
    if prof.adapter != adapter:
        raise Refused(f"profile {name!r} runs {prof.adapter}, not {adapter}")
    if prof.config_dir is None:
        raise Refused(f"profile {name!r} names no config_dir: it is the person's own tool home, never walked")
    mine = prof.config_dir.expanduser().resolve()
    defaults = {
        Path(d).expanduser().resolve() for d in ("~/.claude", os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    }
    shared = sorted(
        n for n, p in known.items() if n != name and p.config_dir and p.config_dir.expanduser().resolve() == mine
    )
    if mine in defaults or shared:
        why = f"shares it with {', '.join(shared)}" if shared else "is the tool's default home"
        raise Refused(f"profile {name!r}'s config_dir {prof.config_dir} {why}: a walk takes a home of its own")
    raw = (yaml.safe_load(live_profiles.read_text(encoding="utf-8")) or {}).get("profiles", {})[name] or {}
    extra = [*(raw.get("extra_args") or []), *ASKING_ARGS.get(adapter, [])]
    return {
        **raw,
        "config_dir": str(prof.config_dir),
        "permission_prompts": "ask",
        **({"extra_args": extra} if extra else {}),
    }


def write_home(home: Path, name: str, entry: dict[str, Any]) -> Path:
    """The scratch home's `profiles.yml` and the walk's directory; returns the directory."""
    import yaml

    (home / "profiles.yml").write_text(yaml.safe_dump({"default": name, "profiles": {name: entry}}), encoding="utf-8")
    work = home / "walk"
    work.mkdir()
    git = ["git", "-C", str(work), "-c", "user.name=walk", "-c", "user.email=walk@localhost"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "walk"], check=True)
    return work


def agent_env(home: Path, sock: str, capture: Path | None) -> dict[str, str]:
    """The host agent's environment, which its private tmux server and every pane inherit: the
    scratch home, this checkout's code ahead of the install's (the hook too: the interpreter's own
    bin directory first on `PATH`), and the capture directory. Never a `CLAUDE_CONFIG_DIR`: the
    tool's home is the profile's, which the launch names."""
    from sessionorc.adapters import CAPTURE_ENV

    env = look_home.child_env(home, sock)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    if capture is not None:
        env[CAPTURE_ENV] = str(capture)
    return env


def poll(read: Callable[[], dict[str, Any]], cond: Callable[[dict[str, Any]], bool], timeout: float) -> dict[str, Any]:
    """Read the record until `cond` holds; the last reading either way."""
    end = time.monotonic() + timeout
    rec = read()
    while not cond(rec) and time.monotonic() < end:
        time.sleep(1.0)
        rec = read()
    return rec


def by_hook(rec: dict[str, Any], state: str) -> bool:
    return rec.get("state") == state and rec.get("confidence") == "hook"


def describe(rec: dict[str, Any]) -> str:
    pending = rec.get("pending") or {}
    return f"state {rec.get('state')} ({rec.get('confidence')})" + (
        f", pending {pending.get('kind')}: {pending.get('text')}" if pending else ""
    )


class Walk:
    """The steps, in order, against a host agent already up on the scratch home."""

    def __init__(self, adapter: str, profile: str, work: Path, call: Callable[..., Any], out=print):
        self.adapter, self.profile, self.work, self.call, self.out = adapter, profile, work, call, out
        self.id = ""
        self.adapter_id = ""
        self.results: list[tuple[str, bool, str]] = []

    def get(self) -> dict[str, Any]:
        return self.call("get", id=self.id)

    def step(self, name: str, fn: Callable[[], str]) -> bool:
        try:
            said, ok = fn(), True
        except StepFailed as e:
            said, ok = str(e), False
        except Exception as e:  # noqa: BLE001 — a step that breaks is a failed step, said, and the walk stops
            said, ok = f"{type(e).__name__}: {e}", False
        self.results.append((name, ok, said))
        self.out(f"{'ok  ' if ok else 'FAIL'}  {name}: {said}")
        return ok

    def launch(self) -> str:
        rec = self.call(
            "create", name=WALK_NAME, dir=str(self.work), adapter=self.adapter, profile=self.profile, unattended=True
        )
        self.id, self.adapter_id = rec["id"], rec.get("adapter_id") or ""
        if not self.adapter_id:
            raise StepFailed(f"{self.id} launched with no adapter_id: the tool's session id was not chosen at launch")
        return f"{self.id}, the tool's session id {self.adapter_id}"

    def first_hook(self) -> str:
        rec = poll(self.get, lambda r: by_hook(r, "idle") or r.get("state") in ("needs-you", "exited"), FIRST_HOOK_WAIT)
        if not by_hook(rec, "idle"):
            raise StepFailed(f"no hook-confirmed idle within {FIRST_HOOK_WAIT:.0f}s: {describe(rec)}")
        if rec.get("adapter_id") != self.adapter_id:
            raise StepFailed(f"the hook reported the tool's session as {rec.get('adapter_id')}, not {self.adapter_id}")
        return describe(rec)

    def prompt(self) -> str:
        # `send --wait` returns once this prompt's turn started and settled: the composer emptied
        # (`prompt-stuck` otherwise) and the session went working and back (`prompt-stalled` otherwise)
        rec = self.call("send", id=self.id, text=SHORT_PROMPT, wait=True, timeout=TURN_WAIT)
        if not by_hook(rec, "idle"):
            raise StepFailed(f"the turn settled as {describe(rec)}, not idle by hook")
        sends = rec.get("sends") or []
        return f"working → idle by hook; the send recorded as {sends[-1] if sends else 'nothing'}"

    def permission(self) -> str:
        self.call("send", id=self.id, text=PERMISSION_PROMPT)
        # the record reads the last turn's `idle` until the prompt's own hook lands: an `idle` counts
        # as the turn's end only once something else was read since the send
        busy = False

        def settled(r: dict[str, Any]) -> bool:
            nonlocal busy
            busy = busy or not by_hook(r, "idle")
            return r.get("state") == "needs-you" or (busy and by_hook(r, "idle"))

        rec = poll(self.get, settled, TURN_WAIT)
        pending = rec.get("pending") or {}
        if rec.get("state") != "needs-you" or pending.get("kind") != "permission":
            raise StepFailed(f"no permission was seen: {describe(rec)}")
        said = f"needs-you, {pending.get('text')}"
        if pending.get("tool_use_id"):  # the hook channel answers it (`permission_channel`); else the terminal does
            self.call("decide", id=self.id, tool_use_id=pending["tool_use_id"], behavior="allow")
            said += "; allowed through the hook channel"
        else:
            raise StepFailed(f"{said}; no tool_use_id, so nothing but the terminal answers it")
        rec = poll(self.get, lambda r: by_hook(r, "idle"), TURN_WAIT)
        if not by_hook(rec, "idle"):
            raise StepFailed(f"{said}; then {describe(rec)}, not idle by hook")
        if not (self.work / "conformance-permission.txt").exists():
            raise StepFailed(f"{said}; but the command never ran")
        return said

    def doorbell(self) -> str:
        sent = self.call("msg", text=MAIL_TEXT, to=[self.id], kind="note")
        mid = ((sent or {}).get("entry") or {}).get("id", "?")
        end, allowed, rec = time.monotonic() + TURN_WAIT, [], {}
        while time.monotonic() < end:
            rec = self.get()
            pending = rec.get("pending") or {}
            if rec.get("state") == "needs-you" and pending.get("kind") == "permission" and pending.get("tool_use_id"):
                # the tool asks to run `ao inbox` under `permission_prompts: ask`: the walk is its person
                self.call("decide", id=self.id, tool_use_id=pending["tool_use_id"], behavior="allow")
                allowed.append(pending.get("text", ""))
            elif by_hook(rec, "idle") and (rec.get("wakes") or []) and not rec.get("unread"):
                tail = f" (allowed: {'; '.join(allowed)})" if allowed else ""
                return f"mail {mid} rung, read and idle again{tail}"
            time.sleep(1.0)
        raise StepFailed(f"mail {mid} not read within {TURN_WAIT:.0f}s: {describe(rec)}, wakes {rec.get('wakes')}")

    def resume(self) -> str:
        self.call("kill", id=self.id)
        rec = poll(self.get, lambda r: r.get("state") in ("exited", "closed"), 30)
        if rec.get("state") not in ("exited", "closed"):
            raise StepFailed(f"the kill left it {describe(rec)}")
        # the killed process's own `SessionEnd` lands after the kill; the host agent drops it once a resume
        # has taken the id (TD-822), and the walk still waits for it, a while at most, as belt and braces
        poll(self.get, lambda r: by_hook(r, "exited"), SESSION_END_WAIT)
        rec = self.call(
            "create",
            name=WALK_NAME,
            dir=str(self.work),
            adapter=self.adapter,
            profile=self.profile,
            unattended=True,
            resume=self.adapter_id,
        )
        self.id = rec["id"]
        rec = poll(self.get, lambda r: by_hook(r, "idle") or r.get("state") in ("needs-you", "exited"), FIRST_HOOK_WAIT)
        if not by_hook(rec, "idle"):
            raise StepFailed(f"the resume settled as {describe(rec)}")
        if rec.get("adapter_id") != self.adapter_id:
            raise StepFailed(f"resumed as {rec.get('adapter_id')}, not {self.adapter_id}")
        return f"{self.id} on the same tool session {self.adapter_id}, idle by hook"

    def transcript(self) -> str:
        got = self.call("transcript", id=self.id, turns=20)
        entries = got.get("entries") or []
        prompts = [e.get("text") or "" for e in entries if e.get("kind") == "prompt"]
        missing = [p for p in (SHORT_PROMPT, PERMISSION_PROMPT) if not any(p in t for t in prompts)]
        if missing:
            raise StepFailed(f"{len(entries)} entries, and the walk's prompts {missing} are not among them")
        kinds = sorted({e.get("kind") for e in entries})
        return f"{len(entries)} entries ({', '.join(map(str, kinds))}), the walk's prompts among them"

    def run(self) -> bool:
        for name, fn in (
            ("launch", self.launch),
            ("first hook", self.first_hook),
            ("a short prompt", self.prompt),
            ("a permission", self.permission),
            ("a doorbell", self.doorbell),
            ("a resume", self.resume),
            ("the transcript", self.transcript),
        ):
            if not self.step(name, fn):
                return False
        return True


def save_capture(capture: Path, dest: Path, sock: str) -> list[Path]:
    """The capture directory's files, and the pane titles on the walk's tmux server, into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(capture.glob("*.jsonl")):
        shutil.copy2(f, dest / f.name)
        out.append(dest / f.name)
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        titles = subprocess.run(
            ["tmux", "-L", sock, "list-panes", "-a", "-F", "#{pane_title}"], capture_output=True, text=True, timeout=5
        ).stdout.splitlines()
        (dest / "titles.json").write_text(json.dumps(titles, indent=1) + "\n", encoding="utf-8")
        out.append(dest / "titles.json")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="conformance", description=__doc__.split("\n\n")[0])
    ap.add_argument("adapter", help="the adapter to walk, e.g. claude-code")
    ap.add_argument("--profile", help="the profile set aside for the walk (required)")
    ap.add_argument("--capture", action="store_true", help="record the hook and status-line payloads as fixtures")
    args = ap.parse_args(argv)
    if why := refusal(dict(os.environ), args.profile):
        print(f"conformance: refused — {why}", file=sys.stderr)
        return 2

    from sessionorc import adapters, paths

    adapters.load_all()
    if args.adapter not in adapters.names() or not adapters.has_agent(args.adapter):
        print(f"conformance: refused — {args.adapter!r} is no agent adapter ({adapters.names()})", file=sys.stderr)
        return 2
    try:
        entry = scratch_profile(args.adapter, args.profile, paths.home() / "profiles.yml")
    except Refused as e:
        print(f"conformance: refused — {e}", file=sys.stderr)
        return 2

    home = Path(tempfile.mkdtemp(prefix="aoc-", dir="/tmp"))
    sock = f"ao-conf-{uuid.uuid4().hex[:8]}"
    capture = home / "captured" if args.capture else None
    env = agent_env(home, sock, capture)
    agent: subprocess.Popen | None = None

    def on_signal(signum, _frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    try:
        work = write_home(home, args.profile, entry)
        if capture is not None:
            capture.mkdir()
        agent = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "look_home.py"), "--agent", sock], env=env)
        if not look_home.wait_for(lambda: (home / "agent.sock").exists() or agent.poll() is not None, 15):
            print("conformance: the host agent never opened its socket", file=sys.stderr)
            return 1
        if agent.poll() is not None:
            print(f"conformance: the host agent exited {agent.returncode}", file=sys.stderr)
            return 1
        os.environ.update({k: env[k] for k in ("SHIFTLEAD_HOME", "SHIFTLEAD_TMUX_SOCKET")})
        os.environ.pop("SHIFTLEAD_SESSION", None)  # the walk is the person
        from sessionorc.client import call_sync

        print(f"conformance: walking {args.adapter} on profile {args.profile} (SHIFTLEAD_HOME={home}, tmux -L {sock})")
        walk = Walk(args.adapter, args.profile, work, lambda m, **p: call_sync(m, **p))
        ok = walk.run()
        if capture is not None:
            dest = ROOT / "tests" / "conformance" / "fixtures" / args.adapter / "captured"
            for f in save_capture(capture, dest, sock):
                print(f"captured: {f.relative_to(ROOT)}")
        held = sum(1 for _n, good, _s in walk.results if good)
        print(f"conformance: {args.adapter} {'passed' if ok else 'FAILED'} — {held} of 7 steps held")
        return 0 if ok else 1
    except KeyboardInterrupt:
        print("conformance: stopped", file=sys.stderr)
        return 1
    finally:
        look_home.stop(agent)
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, timeout=5)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(f"/tmp/tmux-{os.getuid()}/{sock}")
        look_home.remove_home(home)


if __name__ == "__main__":
    sys.exit(main())
