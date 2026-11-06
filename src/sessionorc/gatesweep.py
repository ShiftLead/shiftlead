"""The event runner (design §4.4 *An entry says what it waits for*, TD-1376): once a UTC day the home's tick
sweeps each registered repo that pins agent-cadence and keeps a split ledger.

What the sweep decides is ledgerboard's `sweep()`, called here on the vendored module; the I/O around it is
the home's, as cadence §2.14 lays it out and the pinned `gate_sweep.py --apply` does by hand, with the same
branch names and idempotence rules so a by-hand sweep and the home never write twice:

- **What it reads.** The repo's ledger and archive, its board and every other registered repo's board (with
  their archives), each from its clone's `origin/<default>` as last fetched.
- **The checks.** Each open `event (<name>)` gate's typed check through the pinned `event_checks.py --json`,
  run in a detached worktree of `origin/<default>`; a gate it gives no answer for is left out of `sweep()`'s
  results (never lifted, never filed as broken). A `host-log` gate is answered by the home itself (§4.4 *The
  check*, TD-1388): agent-cadence's reader, `hostlog.py check`, run per gate with the home's own host file,
  in place of whatever `event_checks.py` said of it.
- **The writes**, each from a worktree of its own at `origin/<default>`, never the registered checkout: each
  lift its own PR on `lift/TD-n/<gate>`, written by the pinned `ledger.py lift`; this repo's board items and
  closes one PR on `sweep/<UTC date>`. The home opens them and merges none: they take ordinary review
  (cadence §2.14, §4). A lift whose PR is open, merged, or already made by another open PR is not made
  again; one whose PR was closed unmerged is never reopened, and an `act` item asks why, once; nothing more
  is filed while an earlier `sweep/` PR is open. Items for another registered repo's board go to that repo as one
  PR on `notices/<this repo>-sweep-<UTC date>`, from a worktree of its clone: nothing while an earlier one from
  this repo is open there, no item a notices PR from this repo merged or closed within the re-ask window
  already filed, and nothing on a board more visible than this repo (its items carry this repo's words, an
  `@name` in the PR body in a code span), each said in the run's lines. Every `gh` call names its repo
  (`--repo`, from the clone's origin) where the origin names one, never the remote `gh` would infer.

`due`, `lift_branch` and `summary` are pure; the rest shells out and is called in a thread."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sessionorc import cadence, reports
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb
from sessionorc.ledgerboard import board as lb_board

log = logging.getLogger("shiftlead.agent")

LEDGER = "docs/ledger"  # a split ledger: the sweep reads no v1 file here
SWEEP_BRANCH = "sweep/"  # the board PR's branch: sweep/<UTC date>
LIFT_BRANCH = "lift/"  # a lift PR's: lift/TD-n/<event name> | until
SESSION = "gate-sweep"  # the session an item the sweep files names
GIT_TIMEOUT = 60.0
GH_TIMEOUT = 60.0
SCRIPT_TIMEOUT = 600.0  # one pinned script: `event_checks.py`'s forge calls (30 s each), or one `ledger.py lift`
HOSTLOG_TIMEOUT = 120.0  # one `hostlog.py check`: a fixed hard bound over the reader's own (at most 90 s)
LOG_SOURCES = "docs/ledger/log-sources.toml"  # the repo's host-log sources, read where its ledger was


class SweepError(Exception):
    """A step that could not be made: the run's line says why."""


def due(last: date | None, today_utc: date) -> bool:
    """Whether a repo whose last run was on `last` (None: none since the agent started) is swept today."""
    return last is None or last < today_utc


def lift_branch(tid: str, gate: str) -> str:
    """cadence §2.14's key, as `gate_sweep.py` writes it: `lift/TD-n/<event name>`, `…/until`."""
    if gate.startswith("event ("):
        return f"{LIFT_BRANCH}{tid}/{gate[len('event (') : -1]}"
    if gate.startswith("until "):
        return f"{LIFT_BRANCH}{tid}/until"
    return f"{LIFT_BRANCH}{tid}/decision-{gate[gate.index('(') + 1 : -1].lower()}"


def eligible(root: Path | str) -> tuple[bool, str | None]:
    """Whether the home sweeps `root`: `(True, None)`, or `(False, why)` — not pinned (agent-cadence's own
    source sweeps by hand), no split ledger, or a pinned tree that cannot be made or holds no script."""
    if not cadence.pinned(root):
        return False, "not pinned"
    if not (Path(root) / LEDGER / "README.md").is_file():
        return False, f"no {LEDGER}/README.md"
    payload, why = cadence.tree(root)
    if payload is None:
        return False, f"pinned, no tree: {why}"
    for script in ("event_checks.py", "ledger.py"):
        if not (payload / "scripts" / script).is_file():
            return False, f"no scripts/{script} in the pinned tree"
    return True, None


# ── reading ───────────────────────────────────────────────────────────────────────────────────


def _git(cwd: Path | str, *args: str, ident: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *(ident or []), "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _words(cp: subprocess.CompletedProcess[str], what: str) -> str:
    lines = (cp.stderr or cp.stdout or "").strip().splitlines()
    return f"{what}: {lines[-1][:200] if lines else f'exit {cp.returncode}'}"


def _show(root: Path | str, ref: str, path: str) -> str | None:
    cp = _git(root, "show", f"{ref}:{path}")
    return cp.stdout if cp.returncode == 0 else None


def origin_url(root: Path | str) -> str:
    cp = _git(root, "remote", "get-url", "origin")
    return cp.stdout.strip() if cp.returncode == 0 else ""


def board_of(root: Path | str) -> tuple[str, str, str, str] | None:
    """`(origin_url, basename, text, archive_text)` of the board at `root`'s `origin/<default>`, as `sweep()`
    takes it; None where it has no such ref or no board there."""
    ref = ledger_mod.default_ref(root)
    if ref is None:
        return None
    text = _show(root, ref, lb.BOARD_PATH)
    if text is None:
        return None
    return origin_url(root), Path(root).name, text, _show(root, ref, lb.BOARD_ARCHIVE_PATH) or ""


class Tree:
    """A temporary worktree of `root` at `base`, on a new `branch` (None: detached), removed on leaving."""

    def __init__(self, root: Path | str, base: str, branch: str | None = None) -> None:
        self.root, self.base, self.branch = Path(root), base, branch
        self.dir = Path(tempfile.mkdtemp(prefix="ao-gate-sweep-"))
        self.made = False

    def __enter__(self) -> Path:
        if self.branch and _git(self.root, "rev-parse", "--verify", "-q", f"refs/heads/{self.branch}").returncode == 0:
            self.__exit__()
            raise SweepError(f"a local branch {self.branch} exists — someone's work: left alone")
        how = ["-b", self.branch] if self.branch else ["--detach"]
        cp = _git(self.root, "worktree", "add", "-q", *how, str(self.dir), self.base)
        if cp.returncode != 0:
            self.__exit__()
            raise SweepError(_words(cp, "git worktree add"))
        self.made = True
        return self.dir

    def __exit__(self, *_: object) -> None:
        for args in (("worktree", "remove", "--force", str(self.dir)), ("worktree", "prune")):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                _git(self.root, *args)
        shutil.rmtree(self.dir, ignore_errors=True)
        if self.made and self.branch:  # pushed or not, the branch is the PR's, never a save-point
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                _git(self.root, "branch", "-D", self.branch)


def _script(tree: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """The pinned agent-cadence's `script`, resolved from `tree`'s own pin, run there."""
    argv, env = cadence.command(tree, "run", script, *args)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT,
        cwd=str(tree),
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def checks(tree: Path) -> list[dict[str, Any]]:
    """Each open event gate's check as `event_checks.py --json` answers it in `tree`: `[{id, name, outcome,
    evidence, why}]`. Exit 1 (a check errored) is an answer; anything else that is not the script's JSON
    raises, since no gate may then be read as anything."""
    try:
        cp = _script(tree, "event_checks.py", "--json")
    except subprocess.TimeoutExpired:
        raise SweepError(f"event_checks.py: timed out after {SCRIPT_TIMEOUT:.0f}s") from None
    if cp.returncode not in (0, 1):
        raise SweepError(_words(cp, "event_checks.py"))
    try:
        rows = json.loads(cp.stdout)["checks"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise SweepError(f"event_checks.py: exit {cp.returncode}, output is not its --json") from None
    return [r for r in rows if isinstance(r, dict) and r.get("id") and r.get("name")]


# ── host-log: the home's own reader run (§4.4 *The check*, TD-1388) ──────────────────────────────


def host_log_gates(text: str) -> list[dict[str, Any]]:
    """Every open entry's event gate whose section's check is `host-log`, in ledger order: `{id, name, check,
    since}`, `check` the vendored `parse_check()` reading and `since` the gate's `gate_added()` day (None when it
    gives none). A gate whose section is missing or unreadable is not here: `event_checks.py` reports it."""
    out = []
    for tid, body in lb._entry_texts(text).items():
        found = lb.entries(body)
        if not found or lb.first_word(found[0]["fields"].get("status")) in lb.ARCHIVED_WORDS:
            continue
        secs = lb.event_sections(body)
        for name in dict.fromkeys(lb.parse_gates(found[0]["blocked_raw"])["events"]):
            mine = [x for x in secs if x["name"] == name]
            if len(mine) != 1 or mine[0]["problem"] or (mine[0]["check"] or {}).get("type") != "host-log":
                continue
            added = lb.gate_added(body, f"event ({name})")
            out.append(
                {"id": tid, "name": name, "check": mine[0]["check"], "since": added.isoformat() if added else None}
            )
    return out


def check_line(c: dict[str, Any]) -> str:
    """A `host-log` check as `parse_check()` read it, written back as one argument: `host-log <source> [kind
    <kind>] [times <N>] "<text>"`."""
    words = ["host-log", c["source"]] + (["kind", c["kind"]] if c.get("kind") else [])
    words += ["times", str(c["times"])] if c.get("times", 1) != 1 else []
    return " ".join([*words, f'"{c["text"]}"'])


def forge_visibility(root: Path | str, remote: str) -> str | None:
    """The repo's visibility on its forge, lower case (`private`, `internal`, `public`), or None when it could not
    be read: GitHub's `gh repo view --json visibility` run in `root` (never `isPrivate`, true for an internal repo
    too), GitLab's project `visibility` through `glab api`."""
    kind, where = reports.forge_of(remote)
    try:
        if kind == "gitlab":
            host, _, path = where.partition("/")
            got, why = reports._glab_api(root, host, f"projects/{quote(path, safe='')}", GH_TIMEOUT)
            word = str(got.get("visibility") or "") if isinstance(got, dict) and why is None else ""
        elif kind == "github":
            cp = _gh(root, "repo", "view", "--json", "visibility", "--jq", ".visibility")
            word = cp.stdout.strip() if cp.returncode == 0 else ""
        else:
            word = ""
    except (OSError, subprocess.SubprocessError):
        word = ""
    word = word.lower()
    return word if word in ("private", "internal", "public") else None


def host_log(root: Path | str, gate: dict[str, Any], *, conf: str, host: dict[str, Any]) -> dict[str, Any]:
    """One `host-log` gate's `{outcome, evidence, why}` from agent-cadence's reader, run through `root`'s pin as
    the home runs every agent-cadence word, with `conf` (the repo's `log-sources.toml`) on standard input and
    `host`'s `repo` id, `visibility` and `host_file`. The reader's `none` is outcome None (left out of the sweep's
    results); a non-zero exit, output that is not one JSON object, or no answer in HOSTLOG_TIMEOUT is `error`, as
    is a repo the reader cannot run for: neither pinned nor agent-cadence's source, no `<repo>` id, no tree."""

    def err(why: str) -> dict[str, Any]:
        return {"outcome": "error", "evidence": None, "why": why}

    if not (cadence.pinned(root) or cadence.is_source(root)):
        return err("the repo neither pins agent-cadence nor is its source, so hostlog.py cannot run for it")
    if not host.get("repo"):
        return err("the repo's origin gives no <repo> id")
    payload, why = cadence.tree(root)
    if payload is None:
        return err(f"agent-cadence's pinned tree could not be made: {why}")
    args = ["--repo-config", "-", "--host-config", str(host["host_file"]), "--repo", str(host["repo"])]
    args += ["--visibility", "private" if host.get("visibility") == "private" else "public"]
    args += ["--since", gate["since"]] if gate.get("since") else []
    argv, env = cadence.command(root, "run", "hostlog.py", "check", *args, check_line(gate["check"]))
    try:
        cp = subprocess.run(
            argv,
            input=conf,
            capture_output=True,
            text=True,
            timeout=HOSTLOG_TIMEOUT,
            cwd=str(root),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return err(f"hostlog.py gave no answer in {HOSTLOG_TIMEOUT:.0f} s")
    except OSError as e:
        return err(f"hostlog.py could not run: {e}")
    try:
        out = json.loads(cp.stdout) if cp.returncode == 0 else None
    except ValueError:
        out = None
    if not isinstance(out, dict) or out.get("outcome") not in (*lb.CHECK_OUTCOMES, "none"):
        return err(f"hostlog.py gave no outcome (exit {cp.returncode}): {(cp.stderr or '').strip()[:200]}")
    problem = out.get("problem")
    if out["outcome"] == "none":
        return {"outcome": None, "evidence": None, "why": problem or "this host serves no such source"}
    if out["outcome"] == "passed":
        return {"outcome": "passed", "evidence": out.get("evidence"), "why": None}
    return {"outcome": out["outcome"], "evidence": None, "why": problem or f"{out.get('count', 0)} counted"}


def host_log_rows(
    root: Path | str, base: str, text: str, rows: list[dict[str, Any]], host: dict[str, Any]
) -> list[dict[str, Any]]:
    """`rows` (`event_checks.py`'s answers) with each `host-log` gate's answer replaced by the home's own,
    one gate at a time, the reader given the repo's `log-sources.toml` from `base` (empty when it has none);
    each answer's `why` (the reader's `problem`) goes to the home's log, never the board."""
    gates = host_log_gates(text)
    if not gates:
        return rows
    mine = {(g["id"], g["name"]) for g in gates}
    out = [r for r in rows if (r.get("id"), r.get("name")) not in mine]
    conf = _show(root, base, LOG_SOURCES) or ""
    for g in gates:
        got = host_log(root, g, conf=conf, host=host)
        if got["why"]:
            log.info("%s: %s event (%s), host-log %s — %s", root, g["id"], g["name"], got["outcome"], got["why"])
        out.append({"id": g["id"], "name": g["name"], **got})
    return out


def plan(
    root: Path | str,
    others: list[Path | str],
    *,
    today_utc: date,
    today_local: date,
    host: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The sweep's plan for the repo at `root`: `sweep()`'s `{to_file, to_close, lifts}` with `repo`, `base`,
    `boards` (each board read, by its sweep name) and `checks`. With `host` (`{repo, visibility, host_file}`,
    the home's) each `host-log` gate is answered by the home's own reader run (`host_log_rows`). Raises
    SweepError when it cannot be made."""
    base = ledger_mod.default_ref(root)
    if base is None:
        raise SweepError("no origin/<default>")
    io = ledger_mod.git_io(root, base, "docs")
    if io is None:
        raise SweepError(f"{base}'s tree could not be listed")
    _, text, archive, faults = ledger_mod.read_pair(LEDGER, io)
    if text is None:
        raise SweepError(ledger_mod.fault_words(LEDGER, faults) if faults else f"no {LEDGER} on {base}")
    own = board_of(root)
    if own is None:
        raise SweepError(f"no {lb.BOARD_PATH} on {base}: the sweep's event items go on this repo's own board")
    url = own[0]
    repo = lb.origin_path(url) or Path(root).name
    boards, seen = [own], {lb.origin_key(url) or str(Path(root).resolve())}
    roots: dict[str, str] = {}  # each other board's clone, by the name sweep() files it under
    for other in others:
        key = lb.origin_key(origin_url(other)) or str(Path(other).resolve())
        if key in seen:
            continue  # another worktree or clone of a repo already read
        if (b := board_of(other)) is not None:
            seen.add(key)
            boards.append(b)
            roots.setdefault(lb.origin_key(b[0]) or b[1], str(other))
    with Tree(root, base) as tree:
        rows = checks(tree)
    if host is not None:
        rows = host_log_rows(root, base, text, rows, host)
    results = {(r["id"], r["name"]): (r.get("outcome"), r.get("evidence")) for r in rows if r.get("outcome")}
    try:
        out = lb.sweep([text, archive or ""], boards, results, today_utc, today_local, repo=repo)
    except lb.Refused as e:
        raise SweepError(f"sweep() refused: {e}") from None
    return {
        "repo": repo,
        "base": base,
        "own": lb.origin_key(url) or Path(root).name,
        "boards": [lb.origin_key(b[0]) or b[1] for b in boards],
        "roots": roots,
        "checks": rows,
        **out,
    }


# ── writing ───────────────────────────────────────────────────────────────────────────────────


def gh_repo(root: Path | str) -> str | None:
    """`root`'s repo as `gh` names it, `<host>/<owner>/<repo>` from its origin; None for an origin that names
    none (a local path), where `gh` infers it from the directory as before."""
    return lb.origin_key(origin_url(root))


def _gh(root: Path | str, *args: str) -> subprocess.CompletedProcess[str]:
    """`gh` in `root`, aimed at `root`'s origin by `--repo` (`repo view`: its argument) rather than whatever
    remote `gh` would infer, which may be an upstream. An origin that names no repo (a local path) has no forge
    repo to name, and `gh` infers there as before."""
    if (slug := gh_repo(root)) is not None:
        args = (*args[:2], slug, *args[2:]) if args[:2] == ("repo", "view") else (*args, "--repo", slug)
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT,
        cwd=str(root),
        check=False,
        stdin=subprocess.DEVNULL,
    )


def prs(root: Path | str, *narrow: str, state: str = "all", extra: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """The repo's pull requests in `state` (`all` or `open`), as `[{number, state (open|merged|closed), head,
    files}]` and each of `extra`'s fields (a string, empty when the forge gave none): the newest 300, or with
    `narrow` (`--head <branch>`, `--search <q>`) those it matches. A one-open rule reads `open`, so an open PR
    older than the newest 300 of every state still counts."""
    fields = ",".join(["number", "state", "headRefName", "files", *extra])
    cp = _gh(root, "pr", "list", "--state", state, "--limit", "300", *narrow, "--json", fields)
    if cp.returncode != 0:
        raise SweepError(_words(cp, "gh pr list"))
    try:
        rows = json.loads(cp.stdout or "[]")
    except json.JSONDecodeError:
        raise SweepError("gh pr list: output is not JSON") from None
    return [
        {
            "number": int(r["number"]),
            "state": str(r.get("state") or "").lower(),
            "head": str(r.get("headRefName") or ""),
            "files": [str(f.get("path") or "") for f in r.get("files") or [] if isinstance(f, dict)],
            **{k: str(r.get(k) or "") for k in extra},
        }
        for r in rows
        if isinstance(r, dict) and "number" in r
    ]


def _ship(root: Path | str, tree: Path, branch: str, base: str, subject: str, body: str) -> str:
    """Commit everything in `tree`, push `branch`, open its PR against `base`; the PR's URL. A push is never
    forced, and a PR the forge would not open has its pushed branch deleted again."""
    ident = []
    for key in ("user.name", "user.email"):
        if v := _git(root, "config", key).stdout.strip():
            ident += ["-c", f"{key}={v}"]
    for args in (("add", "-A"), ("commit", "-q", "-m", subject)):
        cp = _git(tree, *args, ident=ident)
        if cp.returncode != 0:
            raise SweepError(_words(cp, f"git {args[0]}"))
    cp = _git(tree, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    if cp.returncode != 0:
        raise SweepError(_words(cp, f"git push {branch}") + f" — if origin holds {branch} with no PR, delete it")
    cp = _gh(tree, "pr", "create", "--base", base, "--head", branch, "--title", subject, "--body", body)
    if cp.returncode != 0:
        gone = _git(tree, "push", "-q", "origin", "--delete", branch).returncode == 0
        raise SweepError(_words(cp, "gh pr create") + (f"; {branch} deleted again" if gone else f"; {branch} left"))
    return (cp.stdout.strip().splitlines() or [""])[-1]


def _swept_about(root: Path | str, ctx: str) -> bool:
    """Whether a `sweep/` PR open or merged names `Context: <ctx>` in its body — an item filed since the
    clone last fetched (gate_sweep.py's `prs_naming` rule)."""
    hits = prs(root, "--search", f'"Context: {ctx}" in:body')
    return any(q["head"].startswith(SWEEP_BRANCH) and q["state"] in ("open", "merged") for q in hits)


def _contexts(board: str, archive: str) -> set[str]:
    """Every item's `Context:` on the board and its archive, open or closed, folded as `gate_sweep.py` does."""
    text = board + "\n" + archive
    return {
        " ".join(c.group("ctx").split()).rstrip(".").lower()
        for it in lb.parse_board(text, warn=False) + lb.parse_closed_items(text)
        for c in [lb.CONTEXT_RE.search(it.text)]
        if c
    }


def _lift(
    root: Path | str,
    p: dict[str, Any],
    x: dict[str, Any],
    opened: list[dict],
    asked: set[str],
    extra: list[dict],
    by: str,
) -> str:
    tid, gate = x["id"], x["gate"]
    branch, path, base = lift_branch(tid, gate), f"{LEDGER}/{tid}.md", p["base"]
    for q in opened:  # first, as gate_sweep.py: a lift another open PR already makes is never made again
        if q["state"] == "open" and q["head"] != branch and path in q["files"]:
            cp = _gh(root, "pr", "diff", str(q["number"]))
            if cp.returncode == 0 and re.search(rf"^\+.*gate lifted: {re.escape(gate)} ", cp.stdout, re.M):
                return f"lift {tid} {gate}: PR #{q['number']} already lifts it — nothing to do"
    mine = [q for q in opened if q["head"] == branch] or prs(root, "--head", branch)  # an old one too
    if any(q["state"] == "open" for q in mine):
        return f"lift {tid} {gate}: PR #{mine[0]['number']} is open — nothing to do"
    if any(q["state"] == "merged" for q in mine):
        return f"lift {tid} {gate}: its PR merged and {base} still carries the gate — fetch, then sweep"
    if closed := [q for q in mine if q["state"] == "closed"]:
        ctx = f"{tid} {gate} lift"
        n = closed[0]["number"]
        if ctx.lower() in asked or _swept_about(root, ctx):
            return f"lift {tid} {gate}: its PR #{n} was closed unmerged — not reopened; asked on the board already"
        extra.append(
            {
                "text": f"Lift of {gate} on {tid} was closed",
                "context": ctx,
                "kind": "act",
                "answers": None,
                "default": None,
                "detail": None,
                "lifts": None,
            }
        )
        return f"lift {tid} {gate}: its PR #{n} was closed unmerged — not reopened; an act item asks why"
    with Tree(root, base, branch) as tree:
        args = ["lift", tid, "--gate", gate, "--by", by, "--ledger", str(tree / LEDGER)]
        if x.get("kind") == "event" and x.get("evidence"):
            args += ["--evidence", str(x["evidence"])]
        cp = _script(tree, "ledger.py", *args)
        if cp.returncode != 0:
            raise SweepError(_words(cp, "ledger.py lift"))
        why = "date reached" if x.get("kind") == "until" else f"its check passed: {x.get('evidence')}"
        url = _ship(
            root,
            tree,
            branch,
            base.removeprefix("origin/"),
            f"{tid}: lift {gate} — {why} (gate sweep)",
            f"The home's gate sweep (design §4.4, TD-1376) lifts `{gate}` from {tid}: {why}.\n\n"
            "A reviewer re-runs the check from the evidence in the Log line before merging (a lifted "
            "gate never re-arms).",
        )
    return f"lift {tid} {gate}: opened {url}"


def _write_board(path: str, items: list[dict], keys: list[str], today_local: date, by: str, why: str) -> int:
    """File `items` on, and close the open items keyed `keys` on, the board at `path` through the vendored
    writer, each item due today under the session `SESSION`; how many it closed."""
    for it in items:
        lb_board.apply(
            lb_board.plan_add(
                path,
                it["text"],
                due=today_local.isoformat(),
                context=it["context"],
                kind=it["kind"],
                answers=it["answers"],
                default=it["default"],
                detail=it["detail"],
                lifts=it["lifts"],
                session=SESSION,
                host=by,
                today=today_local,
                tool="gate-sweep",
            )
        )
    closed = 0
    for key in keys:  # one at a time: each close may move the lines below it
        text = lb_board.read(path)
        lines = text.splitlines()
        for it in lb.parse_board(text, warn=False):
            raw = lines[it.line - 1]
            if lb.item_key(raw) == key:
                m = lb.ITEM_RE.match(raw)
                expect = m.group("text")[:60] if m else raw.strip()[:60]
                lb_board.apply(
                    lb_board.plan_edit(path, "done", it.line, expect, today=today_local, why=why, tool="gate-sweep")
                )
                closed += 1
                break
    return closed


def _own_board(
    root: Path | str,
    p: dict[str, Any],
    items: list[dict],
    keys: list[str],
    today_utc: date,
    today_local: date,
    by: str,
) -> str:
    earlier = [q for q in prs(root, state="open") if q["head"].startswith(SWEEP_BRANCH)]
    if earlier:
        return (
            f"board: an earlier sweep PR #{earlier[0]['number']} is open — {len(items)} to file, "
            f"{len(keys)} to close wait for it"
        )
    branch = f"{SWEEP_BRANCH}{today_utc.isoformat()}"
    with Tree(root, p["base"], branch) as tree:
        board = str(tree / lb.BOARD_PATH)
        closed = _write_board(board, items, keys, today_local, by, "the gate sweep: its condition no longer holds")
        subject = f"board: gate sweep {today_utc.isoformat()} — {len(items)} filed, {closed} closed (TD-1376)"
        body = "\n".join(
            ["The home's gate sweep (design §4.4, TD-1376) on this repo's own board.", ""]
            + [f"- file: [{it['kind']}] {it['text']} — Context: {it['context']}" for it in items]
            + [f"- close: {k}" for k in keys]
            + ["", "Review it like any PR (cadence §4)."]
        )
        url = _ship(root, tree, branch, p["base"].removeprefix("origin/"), subject, body)
    return f"board: opened {url}"


NOTICES_BRANCH = "notices/"  # a PR on another repo's board: notices/<this repo>-sweep-<UTC date> (gate_sweep.py's)
# a repo's visibility on its forge, least visible first: an item never goes to a board more visible than its words' repo
VISIBILITY = {"PRIVATE": 0, "INTERNAL": 1, "PUBLIC": 2}


def visibility(root: Path | str) -> str:
    """The repo's visibility on its forge (`forge_visibility`: `gh repo view`, or GitLab's through `glab api`),
    `PRIVATE`, `INTERNAL` or `PUBLIC`; SweepError when it cannot be read — an unread visibility writes nothing."""
    got = forge_visibility(root, origin_url(root))
    if got is None:
        raise SweepError(f"{Path(root).name}: its visibility on its forge could not be read")
    return got.upper()


# a code span (left as it is: an `@name` inside one notifies nobody), else an `@name` or `@org/team` outside one
MENTION = re.compile(r"(`+)(?:.*?)\1|(?<![\w`])@([A-Za-z0-9][\w-]*(?:/[\w.-]+)?)", re.S)


def unmention(text: str) -> str:
    """`text` with each `@name` (and `@org/team`) outside a code span put in one, so a PR body copying it notifies
    nobody; a span already there is left as it is."""
    return MENTION.sub(lambda m: m.group(0) if m.group(1) else f"`@{m.group(2)}`", str(text))


def _held_by_notices(there: Path | str, mark: re.Pattern[str], ctx: str, today_utc: date) -> int | None:
    """The number of a notices PR from this repo (its branch matching `mark`) merged or closed within the re-ask window
    (`lb.SWEEP_REASK_DAYS`) whose body files an item with `Context: <ctx>`, else None: a closed one is the
    person's no for that window, and a merged one the clone has not fetched yet would file the item twice. A
    PR whose date the forge did not give holds it too."""
    line = re.compile(rf"— Context: {re.escape(ctx)}$", re.M)
    for q in prs(there, "--search", f'"Context: {ctx}" in:body', extra=("body", "closedAt", "mergedAt")):
        if not mark.match(q["head"]) or q["state"] not in ("merged", "closed") or not line.search(q["body"]):
            continue
        when = q["mergedAt"] or q["closedAt"]
        try:
            day = date.fromisoformat(when[:10]) if when else None
        except ValueError:
            day = None
        if day is None or (today_utc - day).days <= lb.SWEEP_REASK_DAYS:
            return q["number"]
    return None


def _qualify(repo: str, it: dict[str, Any]) -> dict[str, Any]:
    """The item with a bare `TD-n` in its words and detail written `<repo>#TD-n`, the id its `Context:` names:
    on another repo's board a bare id is that repo's own (gate_sweep.py's rule)."""
    m = re.match(r"\S+#(TD-\d+)\b", str(it.get("context") or ""))
    if not m:
        return it
    bare = re.compile(rf"(?<![#\w]){re.escape(m.group(1))}\b")

    def fix(x: str) -> str:
        return bare.sub(f"{repo.lower()}#{m.group(1)}", x)

    detail = it.get("detail")
    if isinstance(detail, dict):
        detail = {k: [fix(x) for x in v] if isinstance(v, list) else fix(v) for k, v in detail.items()}
    return {**it, "text": fix(str(it["text"])), "detail": detail or None}


def _other_board(
    root: Path | str,
    p: dict[str, Any],
    board: str,
    there: str | None,
    items: list[dict],
    keys: list[str],
    today_utc: date,
    today_local: date,
    by: str,
) -> str:
    """File `items` on, and close `keys` on, another registered repo's `board` by one PR in that repo, as the
    pinned `gate_sweep.py` does (cadence §2.14, TD-229): a temporary worktree of its clone `there` at its
    `origin/<default>`, the branch `notices/<this repo>-sweep-<UTC date>`, opened on its forge and merged by none.
    Nothing while an earlier such PR from this repo is open there, and nothing on a board more visible than this
    repo, since its items carry this repo's entries' words. One line: what was done."""
    n = f"{len(items)} to file, {len(keys)} to close"
    if not there:
        return f"board {board}: not done — no registered clone of it ({n})"
    mine, theirs = visibility(root), visibility(there)
    if VISIBILITY[theirs] > VISIBILITY[mine]:
        return (
            f"board {board}: not written — it is {theirs.lower()}, more visible than this repo ({mine.lower()}), "
            f"and its items carry this repo's entries' words ({n})"
        )
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", p["repo"]).strip("-")
    prefix = f"{NOTICES_BRANCH}{slug}-sweep-"
    mark = re.compile(rf"{re.escape(prefix)}\d{{4}}-\d\d-\d\d$")  # never a notices branch of a repo named <x>-sweep
    earlier = [q for q in prs(there, state="open") if mark.match(q["head"])]
    if earlier:
        return f"board {board}: an earlier sweep PR #{earlier[0]['number']} from this repo is open there — {n} wait"
    held = {}
    for it in items:
        if (num := _held_by_notices(there, mark, str(it["context"]), today_utc)) is not None:
            held[str(it["context"])] = num
    if held:
        items = [it for it in items if str(it["context"]) not in held]
        heard = "; ".join(f"{c} by #{num}" for c, num in held.items())
        if not items and not keys:
            return f"board {board}: nothing to file — held by a notices PR merged or closed there: {heard}"
        n = f"{len(items)} to file, {len(keys)} to close; held by a notices PR merged or closed there: {heard}"
    base = ledger_mod.default_ref(there)
    if base is None:
        return f"board {board}: not done — its clone has no origin/<default> ({n})"
    branch = f"{prefix}{today_utc.isoformat()}"
    with Tree(there, base, branch) as tree:
        path = str(tree / lb.BOARD_PATH)
        closed = _write_board(path, [_qualify(p["repo"], it) for it in items], keys, today_local, by,
                              f"the gate sweep of {p['repo']}: its condition no longer holds")  # fmt: skip
        subject = f"board: {p['repo']}'s gate sweep {today_utc.isoformat()} — {len(items)} filed, {closed} closed"
        body = "\n".join(
            [
                f"The home's gate sweep of {p['repo']} (design §4.4, TD-1376) found items that belong on this "
                "repo's board, whose `People:` names the person.",
                "",
            ]
            + [f"- file: [{it['kind']}] {unmention(it['text'])} — Context: {unmention(it['context'])}" for it in items]
            + [f"- close: {unmention(k)}" for k in keys]
            + ["", "Review it like any PR (cadence §4)."]
        )
        url = _ship(there, tree, branch, base.removeprefix("origin/"), subject, body)
    return f"board {board}: opened {url}"


def apply(root: Path | str, p: dict[str, Any], *, today_utc: date, today_local: date, by: str) -> list[str]:
    """Make the plan's writes: each lift its own PR, this repo's board items and closes one sweep PR, then each
    other registered repo's board one notices PR there. One line each of what was done or skipped; a step that
    fails stops only itself."""
    said: list[str] = []
    items, keys = list(p["to_file"].get(p["own"], [])), list(p["to_close"].get(p["own"], []))
    if p["lifts"] or items or keys:
        said += _apply_own(root, p, items, keys, today_utc, today_local, by)
    for board in sorted({*p["to_file"], *p["to_close"]} - {p["own"]}):
        got, ks = list(p["to_file"].get(board, [])), list(p["to_close"].get(board, []))
        if got or ks:
            there = (p.get("roots") or {}).get(board)
            try:
                said.append(_other_board(root, p, board, there, got, ks, today_utc, today_local, by))
            except Exception as e:  # noqa: BLE001 — one board's failure never stops another's
                said.append(f"board {board}: not done — {e}")
    return said


def _apply_own(
    root: Path | str, p: dict[str, Any], items: list[dict], keys: list[str], today_utc: date, today_local: date, by: str
) -> list[str]:
    """The lifts and this repo's own board (`apply`)."""
    said: list[str] = []
    try:
        opened = prs(root)
    except (SweepError, OSError, subprocess.SubprocessError) as e:
        return [f"not done — {e}"]
    own = board_of(root)
    asked = _contexts(own[2], own[3]) if own else set()
    extra: list[dict] = []
    for x in p["lifts"]:
        try:
            said.append(_lift(root, p, x, opened, asked, extra, by))
        except (SweepError, lb.Refused, OSError, subprocess.SubprocessError) as e:
            said.append(f"lift {x['id']} {x['gate']}: not done — {e}")
    if items or keys or extra:
        try:
            said.append(_own_board(root, p, items + extra, keys, today_utc, today_local, by))
        except (SweepError, lb.Refused, OSError, subprocess.SubprocessError) as e:
            said.append(f"board: not done — {e}")
    return said


def sweep(
    root: Path | str,
    others: list[Path | str],
    *,
    today_utc: date,
    today_local: date,
    by: str,
    host: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """One sweep of `root`: `(reading, None)` — the plan with `applied`, its lines — or `(None, why)`."""
    try:
        p = plan(root, others, today_utc=today_utc, today_local=today_local, host=host)
    except (SweepError, lb.Refused, OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    return {**p, "applied": apply(root, p, today_utc=today_utc, today_local=today_local, by=by)}, None


def summary(got: dict[str, Any]) -> str:
    """One log line for a reading: what it checked and planned, and each write's line."""
    filed = sum(len(v) for v in got["to_file"].values())
    closed = sum(len(v) for v in got["to_close"].values())
    lifts = ", ".join(f"{x['id']} {x['gate']}" for x in got["lifts"]) or "none"
    line = f"{len(got['checks'])} event check(s); lifts: {lifts}; {filed} item(s) to file, {closed} to close"
    return line + "".join(f"\n  → {a}" for a in got.get("applied") or [])


ELIGIBLE, SWEEP = eligible, sweep  # the real functions, which the test suite's guard replaces (tests/conftest.py)
