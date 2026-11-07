"""A stand-in for the forge's `gh` in the board write-back's tests (design §4.4, TD-264): `pr create`
records a pull request against the bare origin the working directory's `origin` names, `pr merge
--squash` squashes its branch onto the base there by pushing, as GitHub would, `pr view` reads its
state, `pr list` lists them (`--head`, and a `--search` of one quoted phrase in the body, narrow it),
and `pr close` closes it. `FAKE_GH_FAIL=create|merge` makes that step fail; `merge-after` merges and
fails the reply, and `merge-after-moved` also changes origin's board elsewhere right after;
`FAKE_GH_VIEW_FAIL` makes `pr view` fail. State lives beside the bare origin, with every call's argv in
`calls`.

**One call at a time** (TD-1472): every call reads the state, changes it and writes it back, and the agent's
own tick calls `gh` too (the gate sweep's `pr list` and `repo view`) while a test's write-back runs. Without
a lock, a call that read the state before `pr create` wrote it back after, losing PR 1 (`gh pr merge:
KeyError: '1'`), and two writes interleaved into one file (`JSONDecodeError: Extra data`). Each call now
holds an exclusive lock beside the state for its whole run, and each write replaces the file whole."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _write(state_file: Path, state: dict) -> None:
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, state_file)


def main(argv: list[str]) -> int:
    origin = git("remote", "get-url", "origin").stdout.strip()
    if not origin:
        print("no origin", file=sys.stderr)
        return 1
    with open(Path(origin) / "fake-gh.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _call(argv, origin, Path(origin) / "fake-gh.json")


def _call(argv: list[str], origin: str, state_file: Path) -> int:
    state = json.loads(state_file.read_text()) if state_file.exists() else {"prs": {}}
    fail = os.environ.get("FAKE_GH_FAIL", "")
    state.setdefault("calls", []).append(argv)  # every call, so a test can read what each one named
    _write(state_file, state)
    if argv[:2] == ["pr", "create"]:
        if fail == "create":
            print("could not create the pull request", file=sys.stderr)
            return 1
        opts = dict(zip(argv[2::2], argv[3::2], strict=False))
        n = len(state["prs"]) + 1
        state["prs"][str(n)] = {
            "base": opts["--base"],
            "head": opts["--head"],
            "title": opts["--title"],
            "body": opts.get("--body", ""),
            "state": "open",
        }
        _write(state_file, state)
        print(f"https://github.com/o/r/pull/{n}")
        return 0
    if argv[:2] == ["pr", "merge"]:
        pr = state["prs"][argv[2]]
        if fail == "merge":
            print("Pull request is not mergeable", file=sys.stderr)
            return 1
        with tempfile.TemporaryDirectory() as tmp:
            work = str(Path(tmp) / "w")
            git("clone", "-q", "-b", pr["base"], origin, work)
            ident = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
            git("fetch", "-q", "origin", pr["head"], cwd=work)
            if git(*ident, "merge", "-q", "--squash", "FETCH_HEAD", cwd=work).returncode != 0:
                print("Pull request is not mergeable: the merge commit cannot be cleanly created", file=sys.stderr)
                return 1
            git(*ident, "commit", "-q", "-m", f"{pr['title']} (#{argv[2]})", cwd=work)
            if git("push", "-q", "origin", pr["base"], cwd=work).returncode != 0:
                print("push failed", file=sys.stderr)
                return 1
        pr["state"] = "merged"
        _write(state_file, state)
        if fail == "merge-after-moved":  # merged, then origin's board changed elsewhere at once
            with tempfile.TemporaryDirectory() as tmp:
                work = str(Path(tmp) / "w")
                git("clone", "-q", "-b", pr["base"], origin, work)
                board = Path(work) / "docs" / "user_attention.md"
                board.write_text(board.read_text() + "\nA neighbour's edit.\n")
                ident = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
                git(*ident, "commit", "-q", "-am", "a neighbour", cwd=work)
                git("push", "-q", "origin", pr["base"], cwd=work)
        if fail.startswith("merge-after"):  # merged, and the reply lost: what a timeout looks like
            print("Post https://api.github.com/graphql: context deadline exceeded", file=sys.stderr)
            return 1
        return 0
    if argv[:2] == ["pr", "view"]:
        pr = state["prs"].get(argv[2])
        if pr is None or os.environ.get("FAKE_GH_VIEW_FAIL"):
            print("no pull requests found", file=sys.stderr)
            return 1
        print(pr["state"].upper())  # what `--json state --jq .state` prints
        return 0
    if argv[:2] == [
        "pr",
        "list",
    ]:  # the gate sweep's read (TD-1376): every PR, as `--json number,state,headRefName,files`
        opts = dict(zip(argv[2::2], argv[3::2], strict=False))
        want = (opts.get("--search") or "").split('"')
        rows = [
            {
                "number": int(n),
                "state": pr["state"].upper(),
                "headRefName": pr["head"],
                "files": [],
                "body": pr.get("body", ""),
                "closedAt": pr.get("closed_at"),
                "mergedAt": pr.get("merged_at"),
            }
            for n, pr in state["prs"].items()
            if opts.get("--head") in (None, pr["head"])
            and (len(want) < 2 or want[1] in pr.get("body", ""))
            and opts.get("--state") in (None, "all", pr["state"])
        ]
        print(json.dumps(rows))
        return 0
    if argv[:2] == ["repo", "view"]:  # the gate sweep's visibility read (TD-1376): `--json visibility --jq …`
        print(state.get("visibility", "PRIVATE"))
        return 0
    if argv[:2] == ["pr", "diff"]:
        return 0
    if argv[:2] == ["pr", "close"]:
        state["prs"][argv[2]]["state"] = "closed"
        _write(state_file, state)
        return 0
    print(f"fake gh: {argv}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
