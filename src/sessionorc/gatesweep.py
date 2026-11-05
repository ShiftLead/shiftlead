"""The event runner (design §4.4 *An entry says what it waits for*, TD-1376): once a UTC day the home's tick
sweeps each registered repo that pins agent-cadence and keeps a split ledger.

What the sweep decides is ledgerboard's `sweep()`, called here on the vendored module; the I/O around it is
the home's, as cadence §2.14 lays it out and the pinned `gate_sweep.py --apply` does by hand, with the same
branch names and idempotence rules so a by-hand sweep and the home never write twice:

- **What it reads.** The repo's ledger and archive, its board and every other registered repo's board (with
  their archives), each from its clone's `origin/<default>` as last fetched.
- **The checks.** Each open `event (<name>)` gate's typed check through the pinned `event_checks.py --json`,
  run in a detached worktree of `origin/<default>`; a gate it gives no answer for is left out of `sweep()`'s
  results (never lifted, never filed as broken).
- **The writes**, each from a worktree of its own at `origin/<default>`, never the registered checkout: each
  lift its own PR on `lift/TD-n/<gate>`, written by the pinned `ledger.py lift`; this repo's board items and
  closes one PR on `sweep/<UTC date>`. The home opens them and merges none: they take ordinary review
  (cadence §2.14, §4). A lift whose PR is open, merged, or already made by another open PR is not made
  again; one whose PR was closed unmerged is never reopened, and an `act` item asks why, once; nothing more
  is filed while an earlier `sweep/` PR is open. Items for another repo's board are not written yet (said in
  the run's lines; TD-1376's second slice).

`due`, `lift_branch` and `summary` are pure; the rest shells out and is called in a thread."""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from sessionorc import cadence
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb
from sessionorc.ledgerboard import board as lb_board

LEDGER = "docs/ledger"  # a split ledger: the sweep reads no v1 file here
SWEEP_BRANCH = "sweep/"  # the board PR's branch: sweep/<UTC date>
LIFT_BRANCH = "lift/"  # a lift PR's: lift/TD-n/<event name> | until
SESSION = "gate-sweep"  # the session an item the sweep files names
GIT_TIMEOUT = 60.0
GH_TIMEOUT = 60.0
SCRIPT_TIMEOUT = 600.0  # one pinned script: `event_checks.py`'s forge calls (30 s each), or one `ledger.py lift`


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


def plan(root: Path | str, others: list[Path | str], *, today_utc: date, today_local: date) -> dict[str, Any]:
    """The sweep's plan for the repo at `root`: `sweep()`'s `{to_file, to_close, lifts}` with `repo`, `base`,
    `boards` (each board read, by its sweep name) and `checks`. Raises SweepError when it cannot be made."""
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
    for other in others:
        key = lb.origin_key(origin_url(other)) or str(Path(other).resolve())
        if key in seen:
            continue  # another worktree or clone of a repo already read
        if (b := board_of(other)) is not None:
            seen.add(key)
            boards.append(b)
    with Tree(root, base) as tree:
        rows = checks(tree)
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
        "checks": rows,
        **out,
    }


# ── writing ───────────────────────────────────────────────────────────────────────────────────


def _gh(root: Path | str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT,
        cwd=str(root),
        check=False,
        stdin=subprocess.DEVNULL,
    )


def prs(root: Path | str, *narrow: str) -> list[dict[str, Any]]:
    """The repo's pull requests, every state, as `[{number, state (open|merged|closed), head, files}]`: the
    newest 300, or with `narrow` (`--head <branch>`, `--search <q>`) those it matches."""
    cp = _gh(
        root, "pr", "list", "--state", "all", "--limit", "300", *narrow, "--json", "number,state,headRefName,files"
    )
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


def _own_board(
    root: Path | str,
    p: dict[str, Any],
    items: list[dict],
    keys: list[str],
    opened: list[dict],
    today_utc: date,
    today_local: date,
    by: str,
) -> str:
    earlier = [q for q in opened if q["state"] == "open" and q["head"].startswith(SWEEP_BRANCH)]
    if earlier:
        return (
            f"board: an earlier sweep PR #{earlier[0]['number']} is open — {len(items)} to file, "
            f"{len(keys)} to close wait for it"
        )
    branch = f"{SWEEP_BRANCH}{today_utc.isoformat()}"
    with Tree(root, p["base"], branch) as tree:
        board = str(tree / lb.BOARD_PATH)
        for it in items:
            lb_board.apply(
                lb_board.plan_add(
                    board,
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
            text = lb_board.read(board)
            lines = text.splitlines()
            for it in lb.parse_board(text, warn=False):
                raw = lines[it.line - 1]
                if lb.item_key(raw) == key:
                    m = lb.ITEM_RE.match(raw)
                    expect = m.group("text")[:60] if m else raw.strip()[:60]
                    lb_board.apply(
                        lb_board.plan_edit(
                            board,
                            "done",
                            it.line,
                            expect,
                            today=today_local,
                            why="the gate sweep: its condition no longer holds",
                            tool="gate-sweep",
                        )
                    )
                    closed += 1
                    break
        subject = f"board: gate sweep {today_utc.isoformat()} — {len(items)} filed, {closed} closed (TD-1376)"
        body = "\n".join(
            ["The home's gate sweep (design §4.4, TD-1376) on this repo's own board.", ""]
            + [f"- file: [{it['kind']}] {it['text']} — Context: {it['context']}" for it in items]
            + [f"- close: {k}" for k in keys]
            + ["", "Review it like any PR (cadence §4)."]
        )
        url = _ship(root, tree, branch, p["base"].removeprefix("origin/"), subject, body)
    return f"board: opened {url}"


def apply(root: Path | str, p: dict[str, Any], *, today_utc: date, today_local: date, by: str) -> list[str]:
    """Make the plan's writes: each lift its own PR, this repo's board items and closes one sweep PR. One line
    each of what was done or skipped; a step that fails stops only itself."""
    said: list[str] = []
    others = sorted({*p["to_file"], *p["to_close"]} - {p["own"]})
    for board in others:
        n, k = len(p["to_file"].get(board, [])), len(p["to_close"].get(board, []))
        if n or k:
            said.append(
                f"board {board}: not done — another repo's board is written by hand until TD-1376's "
                f"second slice ({n} to file, {k} to close)"
            )
    items, keys = list(p["to_file"].get(p["own"], [])), list(p["to_close"].get(p["own"], []))
    if not (p["lifts"] or items or keys):
        return said
    try:
        opened = prs(root)
    except (SweepError, OSError, subprocess.SubprocessError) as e:
        return [*said, f"not done — {e}"]
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
            said.append(_own_board(root, p, items + extra, keys, opened, today_utc, today_local, by))
        except (SweepError, lb.Refused, OSError, subprocess.SubprocessError) as e:
            said.append(f"board: not done — {e}")
    return said


def sweep(
    root: Path | str, others: list[Path | str], *, today_utc: date, today_local: date, by: str
) -> tuple[dict[str, Any] | None, str | None]:
    """One sweep of `root`: `(reading, None)` — the plan with `applied`, its lines — or `(None, why)`."""
    try:
        p = plan(root, others, today_utc=today_utc, today_local=today_local)
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
