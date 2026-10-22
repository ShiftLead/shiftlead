#!/usr/bin/env python3
"""TD-947 probe: a subagent's permission on a scratch home, under the walk's capture.

    python subagent_probe.py <worktree> --profile conformance --mode background|foreground

Launches Claude Code on the walk's profile (permission_prompts: all, permission_wait 90), asks it to
start a subagent that runs one shell command, and records every second: the record's state, pending,
subagents, and the pane at chosen moments — while the hook blocks and after it falls through. Then
denies through the hook channel if it is still waiting, and saves the hook payloads.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("worktree")
ap.add_argument("--profile", required=True)
ap.add_argument("--mode", choices=("background", "foreground", "main"), required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--wait", type=int, default=90)
args = ap.parse_args()

ROOT = Path(args.worktree).resolve()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import conformance  # noqa: E402
import look_home  # noqa: E402

from sessionorc import adapters, paths  # noqa: E402

if os.environ.get("CI"):
    sys.exit("refused: CI")
adapters.load_all()
entry = conformance.scratch_profile("claude-code", args.profile, paths.home() / "profiles.yml")
entry["permission_wait"] = args.wait

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
home = Path(tempfile.mkdtemp(prefix="aop-", dir="/tmp"))
sock = f"ao-probe-{uuid.uuid4().hex[:8]}"
capture = home / "captured"
env = conformance.agent_env(home, sock, capture)
agent = None
log = open(out / "timeline.jsonl", "w")  # noqa: SIM115 — closed in the finally below

if args.mode == "background":
    PROMPT = (
        "Use the Agent tool with run_in_background set to true and subagent_type general-purpose. Give it "
        "this task: 'Use your Bash tool to run exactly this command and nothing else, then stop: "
        "touch probe-subagent.txt'. After launching it, end your turn at once without waiting for it."
    )
elif args.mode == "main":
    PROMPT = "Use your Bash tool to run exactly this command, then stop: touch probe-main.txt"
else:
    PROMPT = (
        "Use the Agent tool (not in the background) with subagent_type general-purpose. Give it this task: "
        "'Use your Bash tool to run exactly this command and nothing else, then stop: touch probe-subagent.txt'. "
        "Wait for it, then reply with one word: done."
    )


import itertools  # noqa: E402

SEQ = itertools.count(1)


def pane(name: str, sid: str) -> None:
    with contextlib.suppress(Exception):
        p = conformance.save_pane(capture, sock, int(time.time()), name, sid)
        shutil.copy2(p, out / f"pane-{next(SEQ):02d}-{name}.txt")


try:
    work = conformance.write_home(home, args.profile, entry)
    capture.mkdir()
    agent = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "look_home.py"), "--agent", sock], env=env)
    if not look_home.wait_for(lambda: (home / "agent.sock").exists() or agent.poll() is not None, 15):
        sys.exit("no socket")
    os.environ.update({k: env[k] for k in ("SHIFTLEAD_HOME", "SHIFTLEAD_TMUX_SOCKET")})
    os.environ.pop("SHIFTLEAD_SESSION", None)
    from sessionorc.client import call_sync

    rec = call_sync("create", name="probe", dir=str(work), adapter="claude-code", profile=args.profile, unattended=True)
    sid = rec["id"]
    get = lambda: call_sync("get", id=sid)  # noqa: E731
    r = conformance.poll(get, lambda r: conformance.by_hook(r, "idle"), 120)
    print("first hook:", conformance.describe(r), flush=True)
    call_sync("send", id=sid, text=PROMPT)
    t0 = time.monotonic()
    first_needs = None
    shots = {5, 20, 45}
    decided = False
    answered_at = 0.0
    done_shots: set[str] = set()
    while time.monotonic() - t0 < args.wait + 240:
        r = get()
        el = time.monotonic() - t0
        row = {
            "t": round(el, 1),
            "state": r.get("state"),
            "conf": r.get("confidence"),
            "pending": r.get("pending"),
            "subagents": r.get("subagents"),
            "subagent_at": r.get("subagent_at"),
        }
        log.write(json.dumps(row) + "\n")
        log.flush()
        if r.get("state") == "needs-you" and first_needs is None:
            first_needs = el
            print(f"needs-you at {el:.0f}s: {r.get('pending')}", flush=True)
            pane("needs-0s", sid)
        if first_needs is not None:
            since = el - first_needs
            for s in sorted(shots):
                if since >= s:
                    pane(f"needs-{s}s", sid)
                    shots.discard(s)
            if since >= args.wait + 15 and not decided:
                pane("after-fallthrough", sid)
                decided = True
                call_sync("keys", id=sid, keys=["Enter"])  # the person answers the drawn dialog: 1. Yes
                answered_at = el
            if decided and el - answered_at >= 5 and "ans5" not in done_shots:
                pane("answered-5s", sid)
                done_shots.add("ans5")
            if decided and el - answered_at >= 60:
                break
        if first_needs is None and el > 240:
            pane("no-needs-you", sid)
            break
        time.sleep(1.0)
    pane("end", sid)
finally:
    log.close()
    for f in sorted(capture.glob("*.jsonl")):
        shutil.copy2(f, out / f.name)
    look_home.stop(agent)
    with contextlib.suppress(Exception):
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, timeout=5)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(f"/tmp/tmux-{os.getuid()}/{sock}")
    look_home.remove_home(home)
    print("saved to", out, flush=True)
