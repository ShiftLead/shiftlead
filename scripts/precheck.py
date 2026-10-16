#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/precheck.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""precheck: run the repo's own checks on a PR's head, in a clean worktree, and record the
verdict on the PR (TD-117, cadence.md §4.12).

    precheck.py --pr N          run the repo's `precheck` command (docs/cadence.toml) on PR N's
                                head commit, then record a `cadence/precheck` commit status on it
    precheck.py --pr N --no-record
                                run it and record nothing (a trial)

The merge gate runs it: the session that runs the cadence check (docs/procedures/cadence.md)
runs this first when `precheck` is set, and check_cadence.py's ci row reads the status. A
`--no-verify` push or a cloud session's push skips a hook; it cannot skip the gate.

The command is the repo's, read from the checkout this runs in (its docs/cadence.toml, never
the PR's — a PR cannot change the check it is judged by before it merges). It runs with bash
from the root of a detached worktree at the head commit, fetched from origin as the forge
serves it (a fork's head included), stdin closed, its output streamed; that worktree is
removed afterwards. A fresh worktree has no installed dependencies, so the command sets up
what it needs (`pdm install && pdm run test`).

The status is a commit status, not a CI run: it uses no Actions minutes, and it stays on the
commit after the session ends. Its description names the command's exit code, the time it
took and the host it ran on.

Exit: 0 the command passed and the status is recorded (or --no-record); 1 it failed (a failure
status is recorded); 2 nothing ran — no `precheck` set, the PR is not open, its head cannot
be fetched, or a usage error; 3 it passed but the status could not be recorded (the ci row
will not see it). Stdlib only.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cadence_config as C  # noqa: E402
import forge as F  # noqa: E402

CONTEXT = "cadence/precheck"   # parity (cadence.md §7.9): check_cadence.py's row_ci reads this name


def git(*args: str, cwd: str | Path, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, check=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the repo's precheck on a PR's head (TD-117).")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--no-record", action="store_true", help="run it, record no status")
    a = ap.parse_args(argv)

    root = C.repo_root(".")
    if not root:
        print("precheck: not in a git repository", file=sys.stderr)
        return 2
    try:
        cmd, _ = C.resolve("precheck", C.sources(root))
    except C.ConfigError as e:
        print(f"precheck: {e}", file=sys.stderr)
        return 2
    if not cmd:
        print("precheck: no `precheck` in docs/cadence.toml — nothing to run (cadence.md §4.12)")
        return 2
    cmd = str(cmd)   # resolve() typed it object; a repo key is a checked non-empty string

    try:
        fg = F.backend(root)
        pr = fg.pr(a.pr)
    except F.ForgeUnreadable as e:
        print(f"precheck: cannot read PR {a.pr}: {e}", file=sys.stderr)
        return 2
    sha = pr.get("head_sha")
    if pr.get("state") != "open" or not sha:
        print(f"precheck: PR {a.pr} is {pr.get('state') or 'unreadable'} — only an open PR's head is checked",
              file=sys.stderr)
        return 2

    try:
        f = git("fetch", "-q", "origin", fg.head_ref(a.pr), cwd=root)
        have = f.returncode == 0 and git("cat-file", "-e", f"{sha}^{{commit}}", cwd=root).returncode == 0
        why = (f.stderr.strip().splitlines() or ["not served"])[-1]
    except subprocess.TimeoutExpired:
        have, why = False, "git fetch timed out"
    if not have:
        print(f"precheck: cannot fetch PR {a.pr}'s head {sha[:7]} from origin ({why})", file=sys.stderr)
        return 2

    tmp = tempfile.mkdtemp(prefix=f"precheck-{a.pr}-")
    wt = Path(tmp) / "head"
    try:
        w = git("worktree", "add", "-q", "--detach", str(wt), sha, cwd=root)
        if w.returncode != 0:
            print(f"precheck: cannot make a worktree at {sha[:7]}: {w.stderr.strip()}", file=sys.stderr)
            return 2
        print(f"precheck: PR {a.pr} at {sha[:7]}: {cmd}", flush=True)
        t0 = time.monotonic()
        rc = subprocess.run(["bash", "-c", cmd], cwd=wt, stdin=subprocess.DEVNULL, check=False).returncode
        took = time.monotonic() - t0
    finally:
        if wt.exists():
            git("worktree", "remove", "--force", str(wt), cwd=root)
        shutil.rmtree(tmp, ignore_errors=True)

    ok = rc == 0
    verdict = "passed" if ok else f"failed (exit {rc})"
    print(f"precheck: {verdict} in {took:.0f}s")
    if a.no_record:
        return 0 if ok else 1
    desc = f"{'passed' if ok else f'exit {rc}'} in {took:.0f}s on {socket.gethostname()}: {cmd}"
    try:
        fg.set_status(sha, ok, CONTEXT, desc)
    except F.ForgeUnreadable as e:
        print(f"precheck: {verdict}, but the {CONTEXT} status could not be recorded on {sha[:7]}: {e}",
              file=sys.stderr)
        return 3 if ok else 1
    print(f"precheck: recorded {CONTEXT} = {'success' if ok else 'failure'} on {sha[:7]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
