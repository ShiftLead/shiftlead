"""The promote's readings and its intent files (design §6 *Promote*, §5 `promote:`, TD-132 slice 1).

A repo's live copy is made from `main` by a person's press or the home's policy, never by a
session. This module is the part that runs in a thread and returns plain data: the repo's
`promote:` block (the one key of `.shiftlead.yml` the host agent reads, by key alone), the three
readings — **live** from `check`, **main** after the home's own `git fetch origin main`, **checks**
from `gh` — the three preconditions as one function, and the run itself, detached, with its intent
file written before it starts. The agent's `PromoteMixin` decides when; nothing here keeps state
beyond the files under `~/.shiftlead/promotes/<repo>/`.

A rollback (§6 *A rollback*, TD-226) is the same run started in a detached worktree of the checkout at
an older commit of main, `~/.shiftlead/promotes/<repo>/tree`, so the person's checkout is never moved;
one that concludes writes `held.json`, and the policy starts nothing for the repo while it stands.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from sessionorc import build, cadence, paths, reports

PROMOTE_EVERY = 300.0  # seconds between full readings: the reports' cadence (§6)
PROMOTE_WATCH = 15.0  # seconds between `check` reads while a run is in flight
PROMOTE_SETTLE = 600.0  # main must stand still this long before `auto` promotes (§6)
PROMOTE_MAX_WAIT = 1800.0  # or main has been ahead of live this long, still or not (§6, TD-581)
PROMOTE_BOUND = 1200.0  # a run past this is killed and failed (§6)
PRECHECK_BOUND = 1200.0  # a precheck on main's head past this is killed (§6 *The precheck on main*)
PRECHECK_GRACE = 5.0  # seconds between the TERM to a precheck's group and the KILL
SMOKE_BOUND = 600.0  # a smoke past this is killed and failed; from its start, the only clock (§6 *The smoke*)
CHECK_TIMEOUT = 60.0
GIT_TIMEOUT = 60.0
GH_TIMEOUT = 30.0
KEYS = ("run", "check")
OPTIONAL = ("smoke",)  # run once `check` reads the commit (§6 *The smoke*, TD-804)
SMOKE_MARK = "── smoke ──"
SMOKE_TOLD = "smoke passed; "  # a passing smoke's last line, what it told after it, rides the note (TD-881)
TOLD_CAP = 1000  # the most of it a note carries
SMOKE_LAST = 20  # the smoke's last non-empty lines its wrapper keeps in `smoke.json` (TD-1032)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_RE = re.compile(r"^[0-9a-f]{7,40}$")  # a rollback's commit: its hex in full or a prefix of seven or more
# a check run's conclusions that are not a pass; `neutral` and `skipped` are
# this agent's own runs by pid: held so `subprocess` never reaps one behind `alive`'s back (a
# dropped Popen is reaped by the next `subprocess.run` and its status lost), polled for `exit`
_procs: dict[int, subprocess.Popen[bytes]] = {}
_exits: dict[int, int] = {}
PRECHECK_CONTEXT = reports.PRECHECK_CONTEXT  # the status `precheck.py` records (design §6 *The precheck on main*)
FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}
# the verdicts on main's head's failing jobs, by checkout: `{head, read}` (`reports.classify_failing`,
# TD-686) — one sha's per checkout, so a job is read once and a new head reads afresh
_jobs: dict[str, dict[str, Any]] = {}


def block(root: str | Path) -> dict[str, str] | None:
    """The checkout's `promote: {run, check[, smoke]}`, or None when its `.shiftlead.yml` has no such key.
    Raises ValueError, saying why, when the file or the block cannot be used — the caller logs it
    and skips the repo; it is never fatal to the tick. The rest of the file is the clients'."""
    f = paths.repo_file(root)
    try:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"{f} cannot be read: {type(e).__name__}") from None
    if not isinstance(doc, dict) or doc.get("promote") is None:
        return None
    value = doc["promote"]
    if not isinstance(value, dict):
        raise ValueError(f"{f}: promote must be a mapping (run, check)")
    out = {k: value.get(k).strip() for k in KEYS + OPTIONAL if isinstance(value.get(k), str) and value.get(k).strip()}
    missing = [k for k in KEYS if k not in out]
    if missing:
        raise ValueError(f"{f}: promote needs {' and '.join(missing)} (design §5)")
    return out


def _git(root: str | Path, *args: str, timeout: float = GIT_TIMEOUT) -> tuple[str | None, str]:
    """`(stdout stripped, "")` or `(None, why)`."""
    try:
        cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"git {args[0]}: {type(e).__name__}"
    if cp.returncode != 0:
        # git's first `fatal:`/`error:` line says what went wrong; its last may be advice (*… and the
        # repository exists.*, TD-322), so it is kept only when no line carries either prefix
        lines = [ln.strip() for ln in (cp.stderr or "").splitlines() if ln.strip()] or ["failed"]
        why = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))), lines[-1])
        return None, f"git {args[0]}: {why[:200]}"
    return cp.stdout.strip(), ""


def read_live(root: str | Path, check: str) -> tuple[str | None, str]:
    """`check` run in the checkout: one full commit on stdout and exit 0 → `(sha, "")`; anything
    else → `(None, why)`, the reason its stderr gives (§5: *live: unknown — <reason>*)."""
    try:
        cp = subprocess.run(
            check, shell=True, cwd=str(root), capture_output=True, text=True, timeout=CHECK_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"check could not run: {type(e).__name__}"
    if cp.returncode != 0:
        return None, ((cp.stderr or "").strip().splitlines() or [f"check exited {cp.returncode}"])[-1][:200]
    sha = (cp.stdout or "").strip().lower()
    if not SHA_RE.match(sha):
        return None, "check did not print one full commit"
    return sha, ""


def read_main(root: str | Path, fetch_why: str | None = None) -> dict[str, Any]:
    """After the home's own `git fetch origin main` (a policy that acts is not hostage to whoever
    last fetched): `main` (origin/main's head), `moved` (its committer time — when main last moved,
    for the settle and the row's age; a squash merge on GitHub stamps it), and `tree`, None when
    the checkout is on main's head with a clean tree (precondition 1) or the text of why not. A
    failed fetch is `fetch_why` beside the last-fetched main, never a missing one. Reads only:
    no checkout, no reset. `fetch_why` is the pull's own fetch of main this pass (§6 *Pull*: one
    fetch per repo per pass), `""` when it went through; None fetches here."""
    out: dict[str, Any] = {}
    why = fetch_why if fetch_why is not None else _git(root, "fetch", "-q", "origin", "main")[1]
    if why:
        out["fetch_why"] = why
    line, why = _git(root, "log", "-1", "--format=%H %cI", "origin/main")
    if line is None or " " not in line:
        return {**out, "main": None, "main_why": why or "origin/main has no commit"}
    out["main"], out["moved"] = line.split(" ", 1)
    head, why = _git(root, "rev-parse", "HEAD")
    status, why2 = _git(root, "status", "--porcelain")
    if head is None or status is None:
        out["tree"] = f"the checkout cannot be read: {why or why2}"
    elif head != out["main"]:
        branch, _ = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        out["tree"] = f"the checkout is on {branch or head[:7]} at {head[:7]}, not main's head {out['main'][:7]}"
    elif status:
        n = len(status.splitlines())
        out["tree"] = f"the checkout has {n} uncommitted change{'' if n == 1 else 's'}"
    else:
        out["tree"] = None
    return out


def ahead(root: str | Path, live: str | None, main: str | None) -> int | None:
    """How many commits main holds that live does not; None when it cannot be said."""
    if not live or not main:
        return None
    n, _ = _git(root, "rev-list", "--count", f"{live}..{main}")
    return int(n) if n and n.isdigit() else None


def promoter(last_run: dict[str, Any]) -> str:
    """What a concluded run went live by, as the Repo page's divider words it (§6 *Promote*, TD-904):
    *rollback* for a rollback (a `last.json` from before `kind` was kept: one a failed smoke started),
    *auto* for the policy, *you* for a press — a person's, or a person's own shell by its name."""
    if last_run.get("kind") == "rollback" or last_run.get("by") == "smoke":
        return "rollback"
    return "auto" if last_run.get("by") == "auto" else "you"


def read_since(root: str | Path, live: str | None, main: str | None, repo: str | None = None) -> dict[str, Any]:
    """The build chip's readings (§6 *Promote*, §4.5a; TD-539) and the live divider's (TD-904): `live_at`, live's
    committer time; `pending`, every commit of main past live as `{sha, subject}`, newest first, up to
    `build.PENDING_CAP` with `pending_more` 1 past it (the chip lists the first `build.PENDING_SHOWN`) — empty
    when live is main's head; and `promoted`, `{sha, subject, at, by}`: the live commit and its subject, with
    when and by what it went live from `repo`'s `last.json` when that names the live commit, else `at` and `by`
    None, as for a copy installed by hand. A failed read, or an unknown live or main, leaves a field absent."""
    out: dict[str, Any] = {}
    at, subject = build.commit_at(str(root), live)
    if at:
        out["live_at"] = at
        done = (last(repo) if repo else None) or {}
        mine = bool(done.get("sha")) and done.get("sha") == live
        out["promoted"] = {
            "sha": live,
            "subject": subject,
            "at": done.get("at") if mine else None,
            "by": promoter(done) if mine else None,
        }
    got = build.pending(str(root), live, main)
    if got is not None:
        out["pending"], out["pending_more"] = got
    return out


def read_ahead_since(root: str | Path, live: str | None, main: str | None) -> str | None:
    """`ahead_since` (§6 *Promote*, TD-581): when main first moved past the live commit — the
    committer time of the oldest commit on main's first-parent line that live does not hold (a squash
    merge stamps it), so the cap, like the settle, survives a restart of the home. None when live is
    main's head, either is unknown, or git cannot say."""
    if not live or not main or live == main:
        return None
    out, _ = _git(root, "log", "--first-parent", "--format=%cI", f"{live}..{main}")
    lines = (out or "").splitlines()
    return lines[-1].strip() if lines else None


def _gh_json(root: str | Path, path: str) -> tuple[Any, str | None]:
    """`gh api <path>`'s JSON, or `(None, why)`."""
    try:
        cp = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, timeout=GH_TIMEOUT, cwd=str(root),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return None, ((cp.stderr or "").strip().splitlines() or ["gh api failed"])[-1][:200]
    try:
        return json.loads(cp.stdout or "{}"), None
    except json.JSONDecodeError:
        return None, "gh api printed something that is not JSON"


def read_checks(root: str | Path, sha: str, keep: bool = True) -> tuple[str, str, dict[str, Any] | None, str | None]:
    """The CI verdict on `sha`: the check runs of `commits/<sha>/check-runs` and the commit statuses of
    `commits/<sha>/status` (its `statuses`, never its combined `state`) folded — `green` when every run
    and status has concluded and none failed (a status's `failure` or `error` fails it, `pending` keeps
    it pending), `pending`, `failed`, or `unknown` with why (no `gh`, no remote, a rate limit, no run and
    no status at all — a commit nothing has looked at is not a green one) — then `checks_not_run`, then
    `precheck` (design §6 *Promote*, TD-1033). Failing runs that are all Actions jobs that never started
    read `unknown`, *CI never ran: <reason>*, with `{reason, kind, runs}` as the third; a real failure
    beside them is still `failed` (§4.4 *CI that never started is the person's*, TD-686). The jobs'
    verdicts are kept per sha (`_jobs`), so a job is read once.

    Main's head (`keep`) where the repo sets `precheck` (`cadence.precheck_command` on `origin/main`) is
    green only when it also carries a `cadence/precheck` that succeeded, which outranks never-started runs
    (then no `checks_not_run`); `precheck` is what the status read found — `absent`, `success`, `failure`,
    `pending` or `unread` — and None where `precheck` is unset or `docs/cadence.toml` does not parse (the
    reading `unknown` with that why). `keep=False` (a rollback's commit) neither reads `precheck` nor reads
    or replaces main's kept verdicts. Only a checkout whose `origin` is GitHub reads its jobs."""
    command, toml_why = None, None
    if keep:
        from sessionorc import board  # the checkout's default branch, as the pull reads it

        command, toml_why = cadence.precheck_command(root, f"origin/{board.default_branch(Path(root))}")
    if toml_why:
        return "unknown", toml_why, None, None
    got, why = _gh_json(root, f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100")
    unread = "unread" if command else None  # the status read never made: what it would find is not known
    if why:
        return "unknown", why, None, unread
    runs = got.get("check_runs") if isinstance(got, dict) else None
    if not isinstance(runs, list):
        return "unknown", "gh api printed something that is not the check runs", None, unread
    got, why = _gh_json(root, f"repos/{{owner}}/{{repo}}/commits/{sha}/status?per_page=100")
    statuses = got.get("statuses") if isinstance(got, dict) else None
    if not why and not isinstance(statuses, list):
        why = "gh api printed something that is not the commit statuses"
    if why:
        return "unknown", why, None, unread
    runs = [r for r in runs if isinstance(r, dict)]
    statuses = [s for s in statuses if isinstance(s, dict)]
    precheck: str | None = None
    if command:
        mine = [s for s in statuses if s.get("context") == PRECHECK_CONTEXT]
        state = str(mine[0].get("state") or "") if mine else ""  # newest first, one per context
        precheck = "failure" if state == "error" else state if state in ("success", "failure", "pending") else "absent"
    if not runs and not statuses and precheck != "absent":
        return "unknown", f"no check runs on {sha[:7]}", None, precheck
    failing = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") in FAILED]
    not_run = None
    if failing and reports.GITHUB_ORIGIN.search(reports.git_origin(root)):
        items = []
        for r in failing:  # a check run's id is its job's; its run is in the job's URL
            m = reports.JOB_URL.search(str(r.get("details_url") or r.get("html_url") or ""))
            job = r.get("id") if m and isinstance(r.get("id"), int) else None
            items.append({"name": str(r.get("name") or ""), "run": int(m[1]) if m else None, "job": job})
        kept = _jobs.get(str(root)) if keep else None
        not_run, _, jobs = reports.classify_failing(root, items, sha, kept, GH_TIMEOUT)
        if keep:
            _jobs[str(root)] = jobs
    if not_run and precheck == "success":  # the precheck is the check: never-started runs checked nothing
        failing, not_run = [], None
    if (failing and not_run is None) or any(s.get("state") in ("failure", "error") for s in statuses):
        return "failed", "", None, precheck
    if not_run:
        return "unknown", f"CI never ran: {not_run['reason']}", not_run, precheck
    if precheck == "absent":
        return "unknown", f"no {PRECHECK_CONTEXT} on {sha[:7]}", None, precheck
    if any(r.get("status") != "completed" for r in runs) or any(s.get("state") == "pending" for s in statuses):
        return "pending", "", None, precheck
    return "green", "", None, precheck


def unmet(reading: dict[str, Any], press: bool = False, kind: str = "promote") -> tuple[str, str] | None:
    """The first of §6's three preconditions the reading does not meet, as `(name, text)`, or None.
    (1) `tree` — the checkout on main's head with a clean tree; (2) `checks` — green, which a
    person's press goes through (`press=True` skips it; the reply says what the checks read);
    (3) `inflight` / `failed` — nothing in flight and no failure standing for the repo. Then the
    rollback's `held`, which stops the policy and never a press (§6 *The hold*). A `rollback` is
    asked neither (1), since the checkout's tree is not what it installs, nor `failed`, since a
    failed promote is the first reason to go back (§6 *What stands in its way*)."""
    if not reading.get("main"):
        return "main", f"main cannot be read: {reading.get('main_why') or 'unknown'}"
    if kind == "promote":
        if "tree" not in reading:
            return "tree", "the checkout has not been read yet"
        if reading["tree"]:
            return "tree", str(reading["tree"])
    if not press and reading.get("checks") != "green":
        why = reading.get("checks_why")
        return "checks", f"checks on main are {reading.get('checks') or 'unknown'}" + (f": {why}" if why else "")
    if reading.get("inflight"):
        f = reading["inflight"]
        what = "rollback" if f.get("kind") == "rollback" else "promote"
        return "inflight", f"a {what} of {str(f.get('sha', ''))[:7]} is in flight"
    if kind == "promote" and reading.get("failed"):
        return "failed", f"the promote of {str(reading['failed'].get('sha', ''))[:7]} failed and is not cleared"
    if not press and (h := reading.get("held")):
        return "held", (
            f"live was rolled back to {str(h.get('sha', ''))[:7]} from {str(h.get('from') or 'unknown')[:7]}: "
            "nothing is promoted by itself until the person promotes or clears it"
        )
    return None


def resolve(root: str | Path, commit: str) -> tuple[str | None, str]:
    """A rollback's commit, resolved in the checkout after the home's fetch (§6 *Which commit*):
    `(full sha, "")`, or `(None, why)` when it is not hex (a branch, a tag or `HEAD~1` would be read
    in the person's checkout, not on main), names no commit or more than one, or is not an ancestor
    of `origin/main` (a branch is never promoted). Whether it is live already is the caller's."""
    x = (commit or "").strip().lower()
    if not HEX_RE.match(x):
        return None, (
            f"{commit!r} is not a commit's hex (seven to forty of 0-9a-f): a branch, a tag or HEAD~n would be "
            "read in the checkout, not on main"
        )
    sha, _ = _git(root, "rev-parse", "--verify", "--quiet", f"{x}^{{commit}}")
    if not sha:
        objs, _ = _git(root, "rev-parse", f"--disambiguate={x}")
        commits = [o for o in (objs or "").split() if _git(root, "cat-file", "-t", o)[0] == "commit"]
        if len(commits) > 1:
            return None, f"{x} names {len(commits)} commits: give more of it"
        return None, f"{x} names no commit in {root}"
    try:
        cp = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "origin/main"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"git merge-base: {type(e).__name__}"
    if cp.returncode == 1:
        return None, f"{sha[:7]} is not on main: a branch is never promoted (a hotfix is a merge, then a press)"
    if cp.returncode != 0:
        return None, "git merge-base: " + ((cp.stderr or "").strip().splitlines() or ["failed"])[-1][:200]
    return sha, ""


# -- the intent files (§6: `~/.shiftlead/promotes/<repo>/`) ---------------------------------------


def repo_dir(repo: str) -> Path:
    return paths.home() / "promotes" / repo


def _read(f: Path) -> dict[str, Any] | None:
    try:
        v = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def _write(f: Path, value: dict[str, Any]) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1), encoding="utf-8")
    tmp.replace(f)


def inflight(repo: str) -> dict[str, Any] | None:
    return _read(repo_dir(repo) / "inflight.json")


def failed(repo: str) -> dict[str, Any] | None:
    return _read(repo_dir(repo) / "failed.json")


def last(repo: str) -> dict[str, Any] | None:
    """`last.json` `{sha, from, at, by, kind}`: the promote that last concluded, `from` what `check` read
    before it — where `--back` goes (§6 *Which commit*)."""
    return _read(repo_dir(repo) / "last.json")


def held(repo: str) -> dict[str, Any] | None:
    """`held.json` `{sha, from, main, at}`, with `by` and `why` when a failed smoke started the rollback:
    a rollback concluded, and the policy waits for the person."""
    return _read(repo_dir(repo) / "held.json")


def drop_tree(root: str | Path, repo: str) -> None:
    """Remove the worktree an earlier run left (§6 *How it reaches `run`*): it stays until the next
    promote or rollback of the repo starts, since what was installed from it may name it."""
    t = repo_dir(repo) / "tree"
    if t.exists():
        _git(root, "worktree", "remove", "--force", str(t))
        if t.exists():  # not the checkout's worktree any more, or never was: the directory alone
            shutil.rmtree(t, ignore_errors=True)
    _git(root, "worktree", "prune")


def make_tree(root: str | Path, repo: str, sha: str) -> Path:
    """A detached worktree of the checkout at `sha`: the one write a rollback makes to a repo — an
    entry in its worktree list, touching no branch, no index and no file of the person's tree.
    Raises ValueError, saying why, when git cannot make it."""
    t = repo_dir(repo) / "tree"
    t.parent.mkdir(parents=True, exist_ok=True)
    _, why = _git(root, "worktree", "add", "-q", "--detach", str(t), sha, timeout=CHECK_TIMEOUT * 5)
    if why:
        raise ValueError(f"the rollback's worktree cannot be made: {why}")
    return t


def clear(repo: str, which: str) -> None:
    with suppress(FileNotFoundError):
        (repo_dir(repo) / f"{which}.json").unlink()


def start(
    root: str | Path,
    repo: str,
    sha: str,
    run: str,
    by: str,
    n: int | None,
    kind: str = "promote",
    frm: str | None = None,
    why: str | None = None,
) -> dict[str, Any]:
    """Start `run` detached from the agent's process group (for this repo the run restarts the agent
    that started it), output to `<sha>.log`: in the checkout for a promote, in a detached worktree
    at `sha` for a `rollback` (§6 *How it reaches `run`*), a tree an earlier run left removed first
    either way. `run` is handed `SHIFTLEAD_PROMOTE_SHA`, `_FROM` (`frm`, what is live; empty when
    unread) and `_ROOT` (the checkout). The intent file is written **before** the start and gains
    the pid after, so an agent that dies in between still finds it; `n` is how many commits it
    makes live, for the note. `smoke` is read here from the tree the run starts in and kept on the
    intent (§6 *The smoke*), so a pull of the checkout mid-run changes nothing; `why` is a failed smoke's,
    on the rollback it starts. Returns the intent. Raises ValueError when the worktree cannot be made,
    OSError when `run` cannot be spawned."""
    d = repo_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    drop_tree(root, repo)
    tree = make_tree(root, repo, sha) if kind == "rollback" else None
    log_path = d / f"{sha}.log"
    intent: dict[str, Any] = {"sha": sha, "at": datetime.now(UTC).isoformat(), "pid": None, "log": str(log_path)}
    intent |= {"by": by, "ahead": n, "kind": kind, "from": frm, "tree": str(tree) if tree else None}
    intent |= _smoke_of(root, tree, sha)
    if why:
        intent["why"] = why
    _write(d / "inflight.json", intent)
    env = {**os.environ, "SHIFTLEAD_PROMOTE_SHA": sha, "SHIFTLEAD_PROMOTE_FROM": frm or ""}
    env["SHIFTLEAD_PROMOTE_ROOT"] = str(root)
    with open(log_path, "ab") as out:
        p = subprocess.Popen(
            run, shell=True, cwd=str(tree or root), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, env=env,
        )  # fmt: skip
    intent["pid"], intent["started"] = p.pid, proc_start(p.pid)
    _procs[p.pid] = p
    _write(d / "inflight.json", intent)
    return intent


def _smoke_of(root: str | Path, tree: Path | None, sha: str) -> dict[str, Any]:
    """`{smoke}` read from the run's tree (the checkout for a promote), with `smoke_note` — *no smoke
    in `<sha7>`* where the checkout's block names one and the tree's does not, *no smoke read in
    `<sha7>`: <why>* where the tree's cannot be read — for the note the run concludes with."""
    try:
        b = block(tree or root)
    except ValueError as e:
        return {"smoke": None, "smoke_note": f"no smoke read in `{sha[:7]}`: {e}"}
    if b and b.get("smoke"):
        return {"smoke": b["smoke"]}
    try:
        named = tree is not None and bool((block(root) or {}).get("smoke"))
    except ValueError:
        named = False
    return {"smoke": None} | ({"smoke_note": f"no smoke in `{sha[:7]}`"} if named else {})


def start_smoke(root: str | Path, repo: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Start the intent's `smoke` detached in the run's tree, its output appended to the run's log
    after `── smoke ──`, through a wrapper that writes `{sha, exit, at}` to `smoke.json` when it ends
    (§6 *The smoke*): an agent restarted mid-smoke reads the result, not a lost child's exit. The
    intent gains `phase: smoke`, `smoke_pid`, `smoke_started` and `smoke_at`, and is written."""
    d = repo_dir(repo)
    clear(repo, "smoke")
    sha = str(intent.get("sha"))
    env = {**os.environ, "SHIFTLEAD_PROMOTE_SHA": sha, "SHIFTLEAD_PROMOTE_FROM": intent.get("from") or ""}
    env |= {"SHIFTLEAD_PROMOTE_ROOT": str(root), "SHIFTLEAD_PROMOTE_KIND": str(intent.get("kind") or "promote")}
    log_path = Path(str(intent.get("log")))
    with open(log_path, "a", encoding="utf-8") as out:
        out.write(f"{SMOKE_MARK}\n")
    with open(log_path, "ab") as out:
        p = subprocess.Popen(
            [sys.executable, "-c", SMOKE_WRAPPER, str(intent["smoke"]), str(d / "smoke.json"), sha, str(SMOKE_LAST)],
            cwd=str(intent.get("tree") or root), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, env=env,
        )  # fmt: skip
    _procs[p.pid] = p
    intent |= {"phase": "smoke", "smoke_pid": p.pid, "smoke_started": proc_start(p.pid)}
    intent["smoke_at"] = datetime.now(UTC).isoformat()
    _write(d / "inflight.json", intent)
    return intent


# the smoke's wrapper: the command through the shell, its output copied to the log and its last
# non-empty lines kept (each capped), then its result written beside the intent with those lines
# (TD-1032); the result waits on the shell, not the pipe, which a child it left behind may hold open
SMOKE_WRAPPER = """
import collections, json, os, subprocess, sys, threading
from datetime import UTC, datetime
p = subprocess.Popen(sys.argv[1], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
last = collections.deque(maxlen=int(sys.argv[4]))
def copy():
    for line in p.stdout:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
        if line.strip():
            last.append(line.decode("utf-8", "replace").strip()[:2000])
t = threading.Thread(target=copy, daemon=True)
t.start()
code = p.wait()
t.join(5)
f = sys.argv[2]
with open(f + ".tmp", "w") as out:
    json.dump({"sha": sys.argv[3], "exit": code, "at": datetime.now(UTC).isoformat(), "last": list(last)}, out)
os.replace(f + ".tmp", f)
sys.exit(code)
"""


def proc_start(pid: int) -> int | None:
    """The process's start time in clock ticks since boot (`/proc/<pid>/stat` field 22), which with
    the pid names one process: a pid read back from a file after a restart of the home may since
    have been taken by another. None where it cannot be read."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def alive(pid: Any, started: Any = None) -> bool:
    """Whether the run's process is still there. This agent's own child is polled, which reaps it,
    so an exited child reads gone and leaves its exit status; another agent's is signalled, and is
    the run's only while its start time is still `started` (when the intent recorded one)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid not in _procs and isinstance(started, int) and proc_start(pid) not in (started, None):
        return False  # the number was taken again by another process
    if pid in _procs:
        code = _procs[pid].poll()
        if code is None:
            return True
        _exits[pid] = code
        del _procs[pid]
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill(pid: Any, started: Any = None) -> None:
    """The run's whole process group, as the stop time kills: it was started in a session of its own.
    Only while `alive` still reads it as the run, so a reused pid's group is never killed."""
    if alive(pid, started):
        with suppress(OSError):
            os.killpg(pid, signal.SIGKILL)
        p = _procs.pop(pid, None)
        if p is not None:  # this agent's own: reaped, so a killed run leaves no zombie
            with suppress(subprocess.TimeoutExpired):
                _exits[pid] = p.wait(timeout=5)


def fail(repo: str, intent: dict[str, Any], why: str, code: int | None = None) -> dict[str, Any]:
    """Move the intent to `failed.json` `{sha, at, log, exit, why}`: nothing further is promoted for
    the repo until the person clears it. `exit` is the run's, or `code` (a smoke's) when given."""
    out = {"sha": intent.get("sha"), "at": datetime.now(UTC).isoformat(), "log": intent.get("log")}
    run_exit = _exits.pop(intent.get("pid"), None)  # None: not ours
    out |= {"exit": run_exit if code is None else code, "why": why, "by": intent.get("by")}
    _write(repo_dir(repo) / "failed.json", out)
    clear(repo, "inflight")
    return out


def tail(log_path: Any, lines: int = 20) -> list[str]:
    """The log's last lines, for the failure's row."""
    try:
        text = Path(str(log_path)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


# -- the precheck on main (design §6 *The precheck on main*, TD-1038) ------------------------------


def precheck_run(repo: str) -> dict[str, Any] | None:
    """`precheck.json` `{sha, at, pid, started, log}`, with `exit` and `last` once this home saw the run
    end: main's last run, kept after it ends (how *has run on that commit* is known) and replaced only
    by the next sha's."""
    return _read(repo_dir(repo) / "precheck.json")


def precheck_pr_run(repo: str) -> dict[str, Any] | None:
    """`precheck-pr.json`: the sync pass's run on a mechanical PR (§6 *Sync* step 4, TD-1039), read
    here only so the two never run at once."""
    return _read(repo_dir(repo) / "precheck-pr.json")


def _going(f: dict[str, Any] | None) -> bool:
    return bool(f) and alive(f.get("pid"), f.get("started"))


def start_precheck(root: str | Path, repo: str, sha: str) -> tuple[dict[str, Any] | None, str | None]:
    """Start dev-cadence's `precheck.py --commit <sha>` in the checkout, located by
    `cadence.precheck_script` — `(file, None)`, or `(None, why)` with nothing started where the script is
    absent. Stdin closed, in a session of its own (`pdm run test` is a grandchild, and the bound kills
    the group), output to `precheck-<sha7>.log`; `precheck.json` is written **before** the start, so a
    home that dies in between finds a `pid: null` file, and gains the pid and its start time after.
    Raises OSError when the script cannot be spawned."""
    return _spawn_precheck(root, repo, "precheck", {"sha": sha}, ["--commit", sha], f"precheck-{sha[:7]}.log")


def start_precheck_pr(root: str | Path, repo: str, pr: int, sha: str) -> tuple[dict[str, Any] | None, str | None]:
    """The sync pass's `precheck.py --pr <pr>` on a mechanical PR at head `sha` (§6 *Sync* step 4,
    TD-1039), started as main's run is, its file `precheck-pr.json` `{pr, sha, at, pid, started, log}`
    and its output `precheck-pr<pr>-<sha7>.log`. The caller holds the agent's promote lock."""
    return _spawn_precheck(
        root, repo, "precheck-pr", {"pr": pr, "sha": sha}, ["--pr", str(pr)], f"precheck-pr{pr}-{sha[:7]}.log"
    )


def _spawn_precheck(
    root: str | Path, repo: str, name: str, f: dict[str, Any], args: list[str], log_name: str
) -> tuple[dict[str, Any] | None, str | None]:
    script, why = cadence.precheck_script(root)
    if script is None:
        return None, why
    argv, env = script
    d = repo_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    log_path = d / log_name
    f = {**f, "at": datetime.now(UTC).isoformat(), "pid": None, "started": None, "log": str(log_path)}
    _write(d / f"{name}.json", f)
    with open(log_path, "ab") as out:
        p = subprocess.Popen(
            [*argv, *args], cwd=str(root), stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, env=env,
        )  # fmt: skip
    f["pid"], f["started"] = p.pid, proc_start(p.pid)
    _procs[p.pid] = p
    _write(d / f"{name}.json", f)
    return f, None


def kill_precheck(root: str | Path, f: dict[str, Any]) -> None:
    """The bound's kill: the run's process group TERM, then KILL after `PRECHECK_GRACE`, only while
    `alive` reads it as the run; then what `precheck.py`'s own cleanup would have removed (§6) — a
    `--pr` run's (`f` carries `pr`) by its prefix, `precheck-<pr>-`."""
    pid, started = f.get("pid"), f.get("started")
    if alive(pid, started):
        with suppress(OSError):
            os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + PRECHECK_GRACE
        while alive(pid, started) and time.monotonic() < deadline:
            time.sleep(0.2)
        # the group's KILL whether or not its leader went on the TERM: a grandchild deaf to it (the
        # suite) outlives a leader that obeyed; the group was read as the run's a grace ago
        with suppress(OSError):
            os.killpg(pid, signal.SIGKILL)
        kill(pid, started)
    pr = f.get("pr")
    drop_precheck_tree(root, str(f.get("sha") or ""), f"precheck-{pr}-" if isinstance(pr, int) else None)


def precheck_pr_bound(root: str | Path, repo: str, now: datetime) -> None:
    """The readings' pass judges the sync pass's run's bound as it does main's (§6 *Sync* step 4 *Who
    ends it*), so a run outlives no bound when the sync pass skips the repo: one going past
    `PRECHECK_BOUND` is killed and its file kept, saying why, for the sync pass to count."""
    f = precheck_pr_run(repo)
    if f and f.get("pid") is not None and _going(f) and (_age(f.get("at"), now) or 0) >= PRECHECK_BOUND:
        kill_precheck(root, f)
        f["why"] = f"killed at the {int(PRECHECK_BOUND // 60)}-minute bound"
        _write(repo_dir(repo) / "precheck-pr.json", f)


def drop_precheck_tree(root: str | Path, sha: str, prefix: str | None = None) -> None:
    """A killed run's worktree: the `git worktree list --porcelain` entry at `sha` whose path is
    `<temp root>/<prefix>*/head` (`precheck-<sha7>-` for a `--commit` run), removed with `git worktree
    remove --force`; any **empty** directory with that prefix removed (a kill between `mkdtemp` and the
    `worktree add` leaves one; a non-empty one the list does not name is a session's own run, left
    alone); then `git worktree prune`."""
    if not SHA_RE.match(sha):
        return
    prefix = prefix or f"precheck-{sha[:7]}-"
    tmp = Path(tempfile.gettempdir())
    listing, _ = _git(root, "worktree", "list", "--porcelain")
    for entry in (listing or "").split("\n\n"):
        fields = dict(line.split(" ", 1) for line in entry.splitlines() if " " in line)
        path = Path(fields.get("worktree") or "/")
        if (
            fields.get("HEAD") == sha
            and path.name == "head"
            and path.parent.parent == tmp
            and path.parent.name.startswith(prefix)
        ):
            _git(root, "worktree", "remove", "--force", str(path))
            if not path.exists():
                with suppress(OSError):
                    path.parent.rmdir()
    for d in tmp.glob(f"{prefix}*"):
        with suppress(OSError):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    _git(root, "worktree", "prune")


def precheck_on_main(root: str | Path, repo: str, r: dict[str, Any], now: datetime) -> None:
    """The home's own precheck on main's head (design §6 *The precheck on main*, TD-1038), on a pass that
    read the checks: `r` is the reading, with `live`, `tree`, `inflight`, `failed` and `held` read. Where
    the repo sets `precheck` (`r["precheck"]` not None), `auto` on or off: a run past `PRECHECK_BOUND` is
    killed; a status on main's head is the verdict whatever the file says; with none (`absent`), main's
    run on the head reads `pending`, *prechecking <sha7>* while it goes, `unknown`, *precheck on <sha7>
    ended and recorded nothing*, once it has gone, and is never run again on that commit; else one is
    started when live is not main's head, (1) and (3) hold, no hold stands and neither file shows a run
    going — the caller holds the agent's promote lock. A `pid: null` file is started again while its sha
    is main's head, dropped once not. Sets `prechecking` (the sha) while main's run goes on its head,
    and `precheck_failed` `{sha, log, tail}` while a failed status stands on main's head."""
    r["prechecking"], r["precheck_failed"] = None, None
    pre, sha = r.get("precheck"), r.get("main")
    if pre is None or not sha:
        return
    d = repo_dir(repo)
    f = precheck_run(repo)
    if f and f.get("pid") is not None and _going(f) and (_age(f.get("at"), now) or 0) >= PRECHECK_BOUND:
        kill_precheck(root, f)
        f["why"] = f"killed at the {int(PRECHECK_BOUND // 60)}-minute bound"
    if f and f.get("pid") is not None and not _going(f) and "exit" not in f:
        f["exit"] = _exits.pop(f.get("pid"), None)  # None: not this home's child, or not seen ending
        f["last"] = (tail(f.get("log"), 1) or [""])[0]
        _write(d / "precheck.json", f)
    if f and f.get("pid") is None and f.get("sha") != sha:
        clear(repo, "precheck")  # a run that never started, on a commit that is no longer main's head
        f = None
    if pre == "failure":
        mine = f if f and f.get("sha") == sha else {}
        r["precheck_failed"] = {"sha": sha, "log": mine.get("log"), "tail": tail(mine.get("log"))}
        return
    if pre != "absent":
        return  # a status on the sha ends it, whatever the file says; `unread` starts nothing
    if f and f.get("sha") == sha and f.get("pid") is not None:
        if _going(f):
            r["checks"], r["checks_why"], r["prechecking"] = "pending", f"prechecking {sha[:7]}", sha
            return
        why = f"precheck on {sha[:7]} ended and recorded nothing"
        if isinstance(f.get("exit"), int):
            why += f" (exit {f['exit']}" + (f": {f['last']}" if f.get("last") else "") + ")"
        elif f.get("why"):
            why += f" ({f['why']})"
        r["checks"], r["checks_why"] = "unknown", why
        return
    if _going(f) or _going(precheck_pr_run(repo)):
        return  # one at a time per repo: main's reading stays `unknown`, *no cadence/precheck on <sha7>*
    if r.get("live") == sha or r.get("tree") is not None or r.get("inflight") or r.get("failed") or r.get("held"):
        return
    try:
        started, why = start_precheck(root, repo, sha)
    except OSError as e:
        started, why = None, f"precheck.py could not be started: {e}"
    if started is None:
        r["checks"], r["checks_why"] = "unknown", why
        return
    r["checks"], r["checks_why"], r["prechecking"] = "pending", f"prechecking {sha[:7]}", sha


# -- one pass over the registry (the home's tick, detached) ---------------------------------------


def _age(at: Any, now: datetime) -> float | None:
    """Seconds since an ISO time, or None when it is not one."""
    try:
        t = datetime.fromisoformat(str(at))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return (now - t).total_seconds()


def settled(moved: Any, now: datetime) -> bool:
    """Main has stood still for `PROMOTE_SETTLE`: a burst of merges is one promote."""
    age = _age(moved, now)
    return age is not None and age >= PROMOTE_SETTLE


def waited(ahead_since: Any, now: datetime) -> bool:
    """Main has been ahead of live for `PROMOTE_MAX_WAIT`, still or not (§6, TD-581): the settle is
    a batching rule, never a hold without limit."""
    age = _age(ahead_since, now)
    return age is not None and age >= PROMOTE_MAX_WAIT


def acts(r: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """When the home will act on a reading under `auto: true` (§4.5a *Inbox row: promote*, TD-581),
    for the Inbox row, the build chip's hover and `ao promote status`: `{"waiting": "live"}` while
    `check` is not answering, `{"checks": <verdict>}` while they are not green, `{"settles_in": s}`
    — the sooner of the settle's remainder and the cap's — or `{"at": "next tick"}` once either has
    run out. None when `auto` is off, main is not ahead, a run is in flight, or something else the
    policy waits on stands (the row says that in its own words)."""
    if not r.get("auto") or not r.get("main") or r.get("live") == r.get("main") or r.get("inflight"):
        return None
    if not r.get("live") or r.get("live_why"):
        return {"waiting": "live"}
    if r.get("failed") or r.get("held"):  # the policy promotes nothing while either stands, checks or not
        return None
    u = unmet(r)
    if u is not None and u[0] != "checks":
        return None
    if u is not None and r.get("prechecking") == r.get("main"):
        return {"prechecking": str(r["main"])[:7]}  # the home's own precheck runs on main's head (TD-1038)
    if u is not None:
        return {"checks": str(r.get("checks") or "unknown")}
    left = [
        limit - age
        for limit, at in ((PROMOTE_SETTLE, r.get("moved")), (PROMOTE_MAX_WAIT, r.get("ahead_since")))
        if (age := _age(at, now)) is not None
    ]
    if not left:  # neither clock can be read: `survey` will not act on one it cannot read
        return None
    if min(left) <= 0:
        return {"at": "next tick"}
    return {"settles_in": round(min(left))}


def acts_words(a: Any) -> str:
    """The `acts` reading in the row's words: *settles in m min*, *promotes at the next tick*,
    *checks pending — promotes when green*, *waiting for a live reading*; "" for none."""
    if not isinstance(a, dict):
        return ""
    if isinstance(a.get("settles_in"), int | float):
        return f"settles in {max(1, -(-int(a['settles_in']) // 60))} min"
    if a.get("at"):
        return "promotes at the next tick"
    if a.get("prechecking"):
        return f"prechecking {a['prechecking']} — promotes when green"
    if a.get("checks"):
        return f"checks {a['checks']} — promotes when green"
    if a.get("waiting"):
        return "waiting for a live reading"
    return ""


def note_text(repo: str, intent: dict[str, Any], behind: int | None = None) -> str:
    """The `system` note a concluded run files: *promoted `<repo>` `<sha7>` — n commits*, or for a
    rollback *rolled back `<repo>` to `<sha7>` from `<sha7>` — main is n commits ahead* (§6), or for
    the one a failed smoke started *rolled back `<repo>` to `<sha7>`: the smoke failed on `<sha7>` —
    <why>* (§6 *The smoke*)."""
    if intent.get("kind") == "rollback" and intent.get("by") == "smoke":
        frm = str(intent.get("from") or "")[:7]
        line = str(intent.get("why") or "").split(": ", 1)[-1]
        return f"rolled back `{repo}` to `{str(intent.get('sha') or '')[:7]}`: the smoke failed on `{frm}` — {line}"
    if intent.get("kind") == "rollback":
        frm = str(intent.get("from") or "")[:7] or "an unread live"
        text = f"rolled back `{repo}` to `{str(intent.get('sha') or '')[:7]}` from `{frm}`"
        return text + (
            f" — main is {behind} commit{'' if behind == 1 else 's'} ahead" if isinstance(behind, int) else ""
        )
    n = intent.get("ahead")
    count = f" — {n} commit{'' if n == 1 else 's'}" if isinstance(n, int) else ""
    return f"promoted `{repo}` `{str(intent.get('sha') or '')[:7]}`{count}"


def _conclude(
    repo: str, r: dict[str, Any], now: datetime, run: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """The run's outcome, read from `check` and never from its exit code (for this repo the agent
    judging it need not be the one that started it): `(failed or None, note or None)`, clearing
    the intent file whichever way it ended. Still running and inside the bound: `(None, None)`.
    It concludes, or starts the intent's `smoke`, only on a pass whose `check` reads its commit
    **and** whose run has ended (§6 *The smoke*, *When and where*; TD-1041): a `run` may write what
    `check` reads before it restarts what serves. The first reading writes `last.json` (and a
    rollback's hold) once, and `read_at` on the intent; after it a live `check` cannot read waits
    within the bound. `run` is the checkout's, for the rollback a failed smoke starts."""
    intent = r["inflight"]
    if intent.get("phase") == "smoke":
        return _judge_smoke(repo, r, intent, now, run)
    pid, sha7 = intent.get("pid"), str(intent.get("sha"))[:7]
    reads = r.get("live") == intent.get("sha") and not r.get("live_why")
    if reads and not intent.get("read_at"):
        _concluded(repo, intent, r.get("main"), now)
        intent["read_at"] = now.isoformat()
        _write(repo_dir(repo) / "inflight.json", intent)
    ended = not alive(pid, intent.get("started"))  # reaped if it was this agent's child: no zombie
    if reads and ended:
        _exits.pop(pid, None)
        if intent.get("smoke"):
            try:
                start_smoke(r["root"], repo, intent)
            except OSError as e:
                return _smoke_failed(repo, r, intent, f"smoke failed on {sha7}: {e}", None, run)
            return None, None
        return None, _passed(repo, r, intent)
    try:
        at = datetime.fromisoformat(str(intent.get("at")))
    except ValueError:
        at = now
    past = (now - at).total_seconds() > PROMOTE_BOUND
    if ended and intent.get("read_at") and r.get("live_why"):  # read once: an unread pass waits for a reading
        if not past:
            return None, None
        return fail(repo, intent, f"live still unknown after {PROMOTE_BOUND / 60:g} minutes — {r['live_why']}"), None
    if ended:
        live = r.get("live_why") and f"live unknown — {r['live_why']}" or f"live is {str(r.get('live'))[:7]}"
        return fail(repo, intent, f"the run ended and {live}, not {sha7}"), None
    if past:
        kill(pid, intent.get("started"))
        read = f" (live read `{sha7}`)" if intent.get("read_at") else ""
        return fail(repo, intent, f"still running after {PROMOTE_BOUND / 60:g} minutes: killed{read}"), None
    return None, None


def _passed(repo: str, r: dict[str, Any], intent: dict[str, Any], took: float | None = None, told: str = "") -> str:
    """A run concluded — on `check`'s reading, or its smoke's pass (`took`, its seconds, and `told`, what
    its last line told beside the pass): a plain promote's hold ended, the intent and the smoke's result
    cleared, and the note."""
    if intent.get("kind") != "rollback":
        clear(repo, "held")
    clear(repo, "inflight")
    clear(repo, "smoke")
    behind = ahead(r["root"], intent.get("sha"), r.get("main")) if intent.get("kind") == "rollback" else None
    note = note_text(repo, intent, behind)
    if took is not None:
        return f"{note} · smoke passed in {round(took)} s" + (f"; {told}" if told else "")
    return f"{note} · {intent['smoke_note']}" if intent.get("smoke_note") else note


def _judge_smoke(
    repo: str, r: dict[str, Any], intent: dict[str, Any], now: datetime, run: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    """A smoke in flight: its result in `smoke.json` for the intent's commit, exit 0 a pass and any
    other a failure; gone with no result, or past `SMOKE_BOUND` (killed, while the pid is still the
    smoke), a failure. Its why is *smoke failed on <sha7>: <the smoke's last line>*, from `smoke.json`
    where the wrapper kept it, else the log's."""
    sha7 = str(intent.get("sha"))[:7]
    pid, started = intent.get("smoke_pid"), intent.get("smoke_started")

    def result() -> dict[str, Any] | None:
        got = _read(repo_dir(repo) / "smoke.json")
        return got if got and got.get("sha") == intent.get("sha") else None

    res = result()
    if res is None and not alive(pid, started):
        res = result()  # it may have written its result and ended between the two reads
        if res is None:
            _log_line(intent, "the smoke ended with no result written")
            return _smoke_failed(repo, r, intent, f"smoke failed on {sha7}: {_last_line(intent)}", None, run)
    if res is None:
        if (_age(intent.get("smoke_at"), now) or 0.0) <= SMOKE_BOUND:
            return None, None
        kill(pid, started)
        _log_line(intent, f"the smoke was still running after {SMOKE_BOUND / 60:g} minutes: killed")
        return _smoke_failed(repo, r, intent, f"smoke failed on {sha7}: {_last_line(intent)}", None, run)
    alive(pid, started)  # reaped if it was this agent's child
    _exits.pop(pid, None)
    code = res.get("exit")
    if code == 0:
        took = _age(intent.get("smoke_at"), _when(res.get("at")) or now)
        last = _said(intent, res, TOLD_CAP + len(SMOKE_TOLD))  # what it told: a page over budget, a reach refused
        told = last[len(SMOKE_TOLD) :] if last.startswith(SMOKE_TOLD) else ""
        return None, _passed(repo, r, intent, took if took is not None else 0.0, told)
    line = _said(intent, res) or f"it exited {code}"
    return _smoke_failed(repo, r, intent, f"smoke failed on {sha7}: {line}", code, run)


def _smoke_failed(
    repo: str, r: dict[str, Any], intent: dict[str, Any], why: str, code: int | None, run: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    """A failed smoke puts back what was live before, at once (§6 *The smoke*): a rollback to the
    intent's `from` with `by: smoke` and the why. Never for a rollback's own smoke, an unread `from`,
    or a `from` that is the commit itself — those stand as a failure, live left where it is; so does
    a rollback that cannot start, with both reasons."""
    clear(repo, "smoke")
    _exits.pop(intent.get("smoke_pid"), None)  # a killed or vanished smoke of ours left its status
    frm, sha = intent.get("from"), intent.get("sha")
    if intent.get("kind") == "rollback" or not frm or frm == sha or not run:
        return fail(repo, intent, why, code), None
    try:
        start(r["root"], repo, str(frm), run, "smoke", None, "rollback", str(sha), why)
    except (ValueError, OSError) as e:  # no tree, or the run cannot be spawned in it
        return fail(repo, intent, f"{why}; its rollback could not start: {e}", code), None
    return None, None


def _when(at: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(at))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _log_line(intent: dict[str, Any], line: str) -> None:
    with suppress(OSError), open(str(intent.get("log")), "a", encoding="utf-8") as out:
        out.write(line + "\n")


def _said(intent: dict[str, Any], res: dict[str, Any] | None, cap: int = 200) -> str:
    """The smoke's own last non-empty line, as its wrapper kept it in `smoke.json`, its first `cap`
    characters, "" when it kept none (the smoke said nothing): whatever else writes to the run's log
    after the smoke cannot stand in for it. A result with no `last` at all (a wrapper before TD-1032)
    falls back to the log's last line."""
    last = (res or {}).get("last")
    if isinstance(last, list):
        return str(last[-1])[:cap] if last else ""
    return _last_line(intent, cap)


def _last_line(intent: dict[str, Any], cap: int = 200) -> str:
    """The smoke's last non-empty line in the run's log, after `── smoke ──`, its first `cap` characters;
    "" when it said nothing."""
    lines = tail(intent.get("log"), 200)
    if SMOKE_MARK in lines:
        lines = lines[len(lines) - lines[::-1].index(SMOKE_MARK) :]
    said = [ln.strip() for ln in lines if ln.strip()]
    return said[-1][:cap] if said else ""


def _concluded(repo: str, intent: dict[str, Any], main: str | None, now: datetime) -> None:
    """What a run that reached its commit leaves, written once, on the first pass whose `check` reads it
    (`read_at`; before the run's end and a smoke):
    `last.json` for every promote; a rollback writes the hold, with `by` and `why` when a failed smoke
    started it, and a second one under a hold keeps its `from` — what the person first went back from
    is what the row goes on naming. A plain promote ends the hold when it concludes (`_passed`)."""
    d = repo_dir(repo)
    at = now.isoformat()
    kind = intent.get("kind") or "promote"  # the Repo page's *by rollback* (TD-904)
    _write(
        d / "last.json",
        {"sha": intent.get("sha"), "from": intent.get("from"), "at": at, "by": intent.get("by"), "kind": kind},
    )
    if intent.get("kind") == "rollback":
        frm = (held(repo) or {}).get("from") or intent.get("from")
        hold = {"sha": intent.get("sha"), "from": frm, "main": main, "at": at}
        if intent.get("by") == "smoke":
            hold |= {"by": "smoke", "why": intent.get("why")}
        _write(d / "held.json", hold)


def survey(
    roots: list[str],
    prev: dict[str, dict[str, Any]],
    full: bool,
    auto: dict[str, bool],
    now: datetime,
    fetched: dict[str, str] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, str]]:
    """One pass, in a thread: every registered checkout whose `.shiftlead.yml` carries `promote:`,
    keyed by the repo's name — `(readings, notes, bad)`. `full` takes all three readings (the
    reports' cadence); otherwise only `check`, and only for a repo with a run in flight. A run in
    flight is concluded, and under `auto: true` one is started when live ≠ main, the three
    preconditions hold and main has settled or been ahead for `PROMOTE_MAX_WAIT`. `notes` are the
    *promoted …* lines for the person inbox; `bad` names each checkout whose block could not be
    used, with why. `fetched` holds the pull's fetch of main for each root it fetched this pass
    (`pulls`), which `read_main` reuses."""
    readings: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    bad: dict[str, str] = {}
    stamp = now.isoformat()
    for root in roots:
        repo = Path(root).name
        try:
            b = block(root)
        except ValueError as e:
            bad[root] = str(e)
            continue
        if b is None:
            continue
        old = prev.get(repo) or {}
        r: dict[str, Any] = {k: v for k, v in old.items() if k not in ("inflight", "failed", "unmet")}
        r["root"] = str(root)
        r["inflight"], r["failed"] = inflight(repo), failed(repo)
        first = not old
        if full or first:
            main = read_main(root, (fetched or {}).get(str(root)))
            for k in ("fetch_why", "main_why", "moved"):
                r.pop(k, None)
            r.update(main)
            if r.get("main"):
                r["checks"], why, r["checks_not_run"], r["precheck"] = read_checks(root, r["main"])
                r["checks_why"] = why or None
                r["origin"] = reports.git_origin(root)  # whose account `ci_not_run` groups it under (TD-686)
            r["at"] = stamp
        if full or first or r["inflight"]:
            sha, why = read_live(root, b["check"])
            if sha:
                r["live"], r["live_why"] = sha, None
            else:
                r.setdefault("live", None)
                r["live_why"] = why
            r["ahead"] = ahead(root, r.get("live"), r.get("main"))
            r["ahead_since"] = read_ahead_since(root, r.get("live"), r.get("main"))
            for k in ("live_at", "pending", "pending_more", "promoted"):
                r.pop(k, None)
            r.update(read_since(root, r.get("live"), r.get("main"), repo))
        if r["inflight"]:
            fl, note = _conclude(repo, r, now, b["run"])
            if note:  # a promote or rollback that succeeds clears a failure standing, as Dismiss does (§6)
                notes.append(note)
                clear(repo, "failed")
                r["failed"] = None
            elif fl:
                r["failed"] = fl
            r["inflight"] = inflight(repo)
        r["held"] = held(repo)
        if full or first:  # the checks were read this pass (TD-1038)
            precheck_on_main(root, repo, r, now)
            precheck_pr_bound(root, repo, now)
        r["auto"] = bool(auto.get(repo))
        behind = bool(r.get("main")) and r.get("live") != r["main"]
        # `auto` acts only on a live it has read (§6, Paul 2026-09-28): a `check` that is not
        # answering is *unknown*, not behind — even with a last good reading kept beside its why —
        # and the row still offers the person's press
        read = bool(r.get("live")) and not r.get("live_why")
        clock = settled(r.get("moved"), now) or waited(r.get("ahead_since"), now)
        if r["auto"] and behind and read and unmet(r) is None and clock:
            r["inflight"] = start(root, repo, r["main"], b["run"], "auto", r.get("ahead"), frm=r.get("live"))
        u = unmet(r)
        r["unmet"] = {"name": u[0], "text": u[1]} if u else None
        r["acts"] = acts(r, now)
        if r["failed"]:
            r["failed"] = {**r["failed"], "tail": tail(r["failed"].get("log"))}
        readings[repo] = r
    return readings, notes, bad


# ── the pull: the main checkout follows origin (design §6 *Pull*, TD-263) ──────────────────────
PULL_OUTCOMES = ("current", "pulled", "waiting", "refused", "off")


def _git_why(root: str | Path, *args: str) -> tuple[bool, str]:
    """`(True, "")` or `(False, why)` — git's own first line, its `error:`/`fatal:` prefix dropped: a
    refused fast-forward's last line is *Aborting*, its first says what would be overwritten."""
    try:
        cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git {args[-1]}: {type(e).__name__}"
    if cp.returncode == 0:
        return True, ""
    lines = [ln.strip() for ln in (cp.stderr or cp.stdout or "").splitlines() if ln.strip()]
    first = re.sub(r"^(error|fatal|hint): ", "", lines[0]) if lines else "git failed"
    return False, first[:200]


def pull(root: str | Path, on: bool, occupant: str | None, now: datetime) -> tuple[dict[str, Any], str | None]:
    """One registered checkout's pull, in a thread: `(reading, fetch_why)`. The reading is `{at,
    outcome, why, from, to, commits, occupant}`, `outcome` one of `PULL_OUTCOMES`; `fetch_why` is
    this pass's fetch of `main` for the promote to reuse — `""` when it went through, None when no
    fetch of `main` was made here. `occupant` is the caller's read of the root (§6 *Pull* (2)):
    None when every session there is at rest, a name when one is mid-turn, `""` when one's state
    cannot be read. Only ever `git fetch` and `git merge --ff-only`: no checkout, reset, rebase or
    stash, and never a push."""
    r: dict[str, Any] = {k: None for k in ("why", "from", "to", "commits", "occupant")}
    r["at"] = now.isoformat()
    if not on:
        return {**r, "outcome": "off"}, None

    def refused(why: str) -> dict[str, Any]:
        return {**r, "outcome": "refused", "why": why}

    from sessionorc import board  # the checkout's default branch and git's busy markers, shared

    default = board.default_branch(Path(root))
    _, fetch_why = _git(root, "fetch", "-q", "origin", default)
    main_fetch = fetch_why if default == "main" else None
    if fetch_why:
        return refused(fetch_why), main_fetch
    head, why = _git(root, "rev-parse", "HEAD")
    to, why2 = _git(root, "rev-parse", f"origin/{default}")
    if head is None or to is None:
        return refused(why or why2), main_fetch
    branch, _ = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    if branch != default:
        return refused(f"on {branch or 'a detached HEAD'}"), main_fetch
    r["from"], r["to"] = head, to
    if head == to:
        return {**r, "outcome": "current"}, main_fetch
    try:
        under_way = board.busy(Path(root))
    except board.Refused as e:
        return refused(str(e)), main_fetch
    if under_way:
        return refused(f"a git operation under way ({', '.join(under_way)})"), main_fetch
    if inflight(Path(root).name):
        return refused("a promote in flight"), main_fetch
    mine, _ = _git(root, "rev-list", "--count", f"origin/{default}..HEAD")
    if mine and mine != "0":
        n = int(mine)
        return refused(
            f"{n} commit{'' if n == 1 else 's'} of its own, not on origin — the person's to push"
        ), main_fetch
    if occupant is not None:
        return {
            **r,
            "outcome": "waiting",
            "occupant": occupant or None,
            "why": "unreadable" if not occupant else None,
        }, main_fetch
    n, _ = _git(root, "rev-list", "--count", f"HEAD..origin/{default}")
    # `merge.autoStash` off whatever the person's config says: the pull never stashes (§6 *Pull*)
    ok, why = _git_why(root, "-c", "merge.autoStash=false", "merge", "--ff-only", "-q", f"origin/{default}")
    if not ok:
        return refused(why), main_fetch
    return {**r, "outcome": "pulled", "commits": int(n) if n and n.isdigit() else None}, main_fetch


def pulls(
    roots: list[str], on: dict[str, bool], occupants: dict[str, str | None], now: datetime
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """The pull's pass over every registered checkout, `promote:` block or not, in a thread:
    `(readings by repo name, fetched)` — `fetched` maps each root whose `main` this pass fetched to
    that fetch's why (`""` when it went through), for `survey` to reuse. `on` is
    `repos.<repo>.pull` (absent is true); `occupants` is the caller's read of each root."""
    readings: dict[str, dict[str, Any]] = {}
    fetched: dict[str, str] = {}
    for root in roots:
        repo = Path(root).name
        try:
            reading, main_fetch = pull(root, on.get(repo, True), occupants.get(str(root)), now)
        except Exception as e:  # noqa: BLE001 — one checkout never stops the pass over the others
            reading, main_fetch = (
                {"at": now.isoformat(), "outcome": "refused", "why": f"{type(e).__name__}: {e}"[:200]},
                None,
            )
        readings[repo] = reading
        if main_fetch is not None:
            fetched[str(root)] = main_fetch
    return readings, fetched
