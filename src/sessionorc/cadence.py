"""Design §6 *Keeping a team running*, rule 10 (TD-247, TD-258): the cadence check as a policy of
the tick. The script's verdict needs no reader — `scripts/check_cadence.py --pr <n> --json` gives a
status per row — so the home runs it on every `done` a supervised member reports with a PR, keeps
what it read on the record's `checks`, and tells the member in fixed words. Nothing here is typed
by a session, and the words name the script's `rule` field, never its `detail`.

The gate is dev-cadence's script (§5 *The seams*, TD-1011): there is no `gate:` key, and in
dev-cadence's own source it is the script under `files/`. A checkout without it has no gate and is
unserved (§5): the home runs nothing there and writes nothing on the record.

A repo that pins dev-cadence (`docs/cadence.toml`'s `[dev-cadence]`, dev-cadence TD-129) carries no copy:
its gate is the pinned tree's script, run through **the resolver** (`command`, §5 *How the readers find
dev-cadence*, TD-1014), which calls the launcher this build vendors (`sessionorc/dev_cadence.py`) with the
host agent's own Python. While a repo still has the lock, its copy's paths are read.

The reads (`head`, `check`, `tree`) shell out and are called in a thread; the rest is pure."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sessionorc import naming
from sessionorc.models import PERSON, Session

SCRIPT = "scripts/check_cadence.py"
VERDICTS = ("pass", "fail", "unknown")
SOURCE_SCRIPT = f"files/{SCRIPT}"
DEFAULT_GATE = f"python3 {SCRIPT} --pr {{pr}} --json"
SOURCE_GATE = f"python3 {SOURCE_SCRIPT} --pr {{pr}} --json"
# The oldest dev-cadence commit whose files this build reads (§5 *Which dev-cadence*, TD-1012): dev-cadence
# TD-106 (#241), the vendoring of ledgerboard v1.0, from which its scripts read and write the ledger and the
# board in the ledgerboard format `seams.ledger` reads. Raised only by the PR that needs a newer one, and only
# once every registered consumer's lock is at or after it (a raise past the roster unserves it).
OLDEST = "6d92209da67410546a258a467e3ff292fb20166d"
LOCK = "docs/cadence-sync.lock"  # the copy's lock, while a repo still has one (`sync.LOCK`)
PIN = "docs/cadence.toml"  # the pin's file: `[dev-cadence]`'s `source` and `ref` (dev-cadence TD-129)
# dev-cadence's launcher, vendored frozen from its `launcher/dev_cadence.py` at LAUNCHER_COMMIT (TD-1014); a
# pinned tree names the lowest launcher interface it runs under, so a newer one is a ShiftLead release
LAUNCHER = Path(__file__).with_name("dev_cadence.py")
LAUNCHER_COMMIT = "8008a10e50e9b70cd571984bb2810d79d59c94c7"
TREE_TIMEOUT = 330.0  # one resolve: the launcher's first clone or fetch of a source is bounded at 300 s
GATE_SCRIPT = "check_cadence.py"  # the gate, as the pinned tree's `files/scripts/` holds it
PINNED_GATE = f"dev-cadence run {GATE_SCRIPT} --pr {{pr}} --json"
TREE_FOR = 60.0  # one resolve answers every reader of one reading: a launcher that cannot fetch is asked once
_trees: dict[tuple[str, tuple[str, str] | None], tuple[float, tuple[Path | None, str | None]]] = {}


def is_source(root: Path | str) -> bool:
    """Whether `root` is dev-cadence's own source (§5 *The seams*): a root holding `sync.sh` and `files/`,
    which carries no lock and whose every dev-cadence path is under `files/`."""
    return (Path(root) / "sync.sh").is_file() and (Path(root) / "files").is_dir()


class PinError(ValueError):
    """A `docs/cadence.toml` whose `[dev-cadence]` the launcher would refuse, in its words."""


def pin(root: Path | str) -> tuple[str, str] | None:
    """`(source, ref)` from the root's `docs/cadence.toml` `[dev-cadence]`, as the launcher reads it, or
    None where there is no pin; one it would refuse raises `PinError`."""
    from sessionorc import dev_cadence as launcher

    try:
        return launcher.read_pin(str(root))
    except launcher.Refusal as e:
        raise PinError(str(e)) from None


def pinned(root: Path | str) -> bool:
    """Whether the repo runs dev-cadence through its pin (§5 *How the readers find dev-cadence*): a
    `[dev-cadence]` table in its `docs/cadence.toml` and no lock — while it still has the lock, its copy
    is read — and never dev-cadence's source, which runs from its own tree."""
    root = Path(root)
    if is_source(root) or (root / LOCK).is_file() or not (root / PIN).is_file():
        return False
    try:
        return pin(root) is not None
    except PinError:
        return True


def command(repo: Path | str, word: str, *args: str) -> tuple[list[str], dict[str, str]]:
    """The command to run dev-cadence's `word` for `repo` (§5 *How the readers find dev-cadence*): the
    argv and environment, `CADENCE_REPO_ROOT` included. The vendored launcher runs under this process's
    own Python (the host agent's venv), never one found on a login `PATH`."""
    argv = [sys.executable, str(LAUNCHER), "-C", str(repo), word, *args]
    return argv, {**os.environ, "CADENCE_REPO_ROOT": str(repo)}


def _launcher_words(text: str) -> str:
    """The launcher's refusal, its `dev-cadence: ` prefix dropped; an interface this build's launcher is
    too old for is said as what cures it, a newer ShiftLead."""
    why = (text.strip().splitlines() or ["no reason given"])[-1].removeprefix("dev-cadence: ").strip()
    if m := re.match(r"this pin needs launcher interface (\d+); this launcher is (\d+)", why):
        return f"it needs launcher interface {m[1]}, this build carries {m[2]} — a newer ShiftLead"
    return why


def tree(root: Path | str, timeout: float = TREE_TIMEOUT) -> tuple[Path | None, str | None]:
    """The pinned payload (the tree's `files/`) the resolver finds for `root`, or `(None, why)` in the
    launcher's words: a pin it cannot resolve (a fetch that failed, an interface too new) leaves the repo
    unserved by name (§5). A tree once made is cached by the launcher, so a read after the first is local;
    the answer for one root and pin is kept `TREE_FOR` seconds, so the readers of one reading ask once."""
    try:
        key = (str(root), pin(root))
    except PinError as e:
        return None, str(e)
    if (hit := _trees.get(key)) is not None and time.monotonic() - hit[0] < TREE_FOR:
        return hit[1]
    got = _tree(root, timeout)
    _trees[key] = (time.monotonic(), got)
    return got


def _tree(root: Path | str, timeout: float) -> tuple[Path | None, str | None]:
    argv, env = command(root, "path")
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, f"the launcher gave no answer in {timeout:.0f}s"
    except OSError as e:
        return None, f"the launcher could not run: {e.strerror or e}"
    out = cp.stdout.strip()
    if cp.returncode != 0:
        return None, _launcher_words(cp.stderr)
    if not out or not Path(out).is_dir():
        return None, f"the launcher named {out or 'no tree'}, which is not a directory here"
    return Path(out), None


def has_script(root: Path | str) -> bool:
    """Whether `root` is a checkout the home can see that carries the script (under `files/` in
    dev-cadence's source, in the pinned tree for a pinned repo): a repo not on dev-cadence, or a path
    that is not a directory here, gives no reading."""
    if pinned(root):
        payload, _ = tree(root)
        return payload is not None and (payload / "scripts" / GATE_SCRIPT).is_file()
    return (Path(root) / (SOURCE_SCRIPT if is_source(root) else SCRIPT)).is_file()


def gate(root: Path | str) -> str | None:
    """The checkout's merge gate (§5 *The seams*, TD-1011): dev-cadence's script, `SOURCE_GATE` in
    its source, `PINNED_GATE` (through the resolver) in a pinned repo and `DEFAULT_GATE` elsewhere, when
    the checkout holds it; None otherwise — the repo is then unserved. No key is read."""
    if not has_script(root):
        return None
    if is_source(root):
        return SOURCE_GATE
    return PINNED_GATE if pinned(root) else DEFAULT_GATE


STATES = ("open", "merged", "closed")


def head(root: Path | str, pr: int, timeout: float = 20.0) -> tuple[str, str] | None:
    """The PR's head commit and its state — `open`, `merged` or `closed` — or None when `gh` could not
    say (no such PR, no network): an entry keeps the head it was read at, so a PR whose head moved is
    read again."""
    try:
        cp = subprocess.run(
            ["gh", "pr", "view", str(pr), "--json", "headRefOid,state"],
            capture_output=True, text=True, timeout=timeout, cwd=str(root),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    try:
        out = json.loads(cp.stdout or "{}")
    except json.JSONDecodeError:
        return None
    sha = out.get("headRefOid") if isinstance(out, dict) else None
    state = str(out.get("state") or "").lower() if isinstance(out, dict) else ""
    if not isinstance(sha, str) or not sha or state not in STATES:
        return None
    return sha, state


def head_from(reading: Any, pr: int) -> tuple[str, str] | None:
    """The PR's head and state from the repo's PR reading (`reports.pr_reading`, kept by the home's
    repo pass): its open PRs and every PR it saw close in the month — so a PR is asked of `gh` no
    more often than that reading reads it (TD-332). None for a reading that failed, or one that does
    not hold the PR or its head (a reading older than the PR, or written before it kept heads)."""
    if not isinstance(reading, dict) or "error" in reading:
        return None
    for row in (*(reading.get("open") or []), *(reading.get("recent") or [])):
        if isinstance(row, dict) and row.get("number") == pr:
            sha, state = str(row.get("head") or ""), str(row.get("state") or "")
            return (sha, state) if sha and state in STATES else None
    return None


def settled(old: dict[str, Any] | None) -> bool:
    """Whether an entry's PR no longer moves — merged, or closed unmerged — so its read stands until a
    new `done` names the PR (TD-332: a closed one was asked for its head on every pass)."""
    return bool(old and (old.get("merged") or old.get("closed")))


def check(root: Path | str, pr: int, timeout: float = 120.0) -> dict[str, Any] | None:
    """One run of the repo's gate on one PR in `root`: `{verdict, failed}`, or None for **no
    reading** — no gate, or a run that could not be made. `failed` is the `rule` of each row whose
    status is `fail`, in the script's order, and there is no reading for an exit of 2 (no such PR) or
    output that is not the script's."""
    if not has_script(root):
        return None
    if pinned(root):  # the pinned tree's script, through the resolver (TD-1014)
        argv, env = command(root, "run", GATE_SCRIPT, "--pr", str(pr), "--json")
    else:
        argv, env = ["python3", SOURCE_SCRIPT if is_source(root) else SCRIPT, "--pr", str(pr), "--json"], None
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(root), env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode == 2:
        return None
    return parse(cp.stdout, pr)


def parse(text: str, pr: int) -> dict[str, Any] | None:
    """`{verdict, failed}` from the script's `--json`, or None when it is not that."""
    try:
        out = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    prs = out.get("prs") if isinstance(out, dict) else None
    got = next((p for p in prs or [] if isinstance(p, dict) and p.get("pr") == pr), None)
    if got is None or got.get("verdict") not in VERDICTS:
        return None
    rows = [r for r in got.get("rows") or [] if isinstance(r, dict)]
    return {"verdict": got["verdict"], "failed": [str(r.get("rule")) for r in rows if r.get("status") == "fail"]}


def entry_of(checks: list[dict[str, Any]], pr: int) -> dict[str, Any] | None:
    return next((c for c in checks if c.get("pr") == pr), None)


def stale(old: dict[str, Any] | None, done_at: str) -> bool:
    """Whether the entry must be looked at again **without asking for the head**: never read, an
    `unknown` kept from the last cadence, or a `done` naming the PR after the read. A merged PR's
    head no longer moves, so a settled read of one stands."""
    return old is None or old.get("verdict") == "unknown" or done_at > str(old.get("at") or "")


def record(
    old: dict[str, Any] | None, pr: int, sha: str, merged: bool, got: dict[str, Any], at: str, *, closed: bool = False
) -> dict[str, Any]:
    """The entry one read leaves: `{pr, at, sha, verdict, failed}`, `merged` once the PR is (`closed`
    once it is closed unmerged), and
    the marks. **`pass`** removes `row` and `told`. **`fail`** on a merged PR — which no re-report
    cures — or read again after the member was told (`told`, whatever was read in between but a
    pass) sets `row`, the Inbox row's mark. **`unknown`** tells nothing and changes no mark.
    `read_by` is carried."""
    new: dict[str, Any] = {"pr": pr, "at": at, "sha": sha, "verdict": got["verdict"], "failed": list(got["failed"])}
    if merged:
        new["merged"] = True
    elif closed:
        new["closed"] = True
    for key in ("told", "row", "read_by"):
        if old and old.get(key):
            new[key] = old[key]
    if got["verdict"] == "pass":
        new.pop("row", None)
        new.pop("told", None)  # a fail after a pass is a first fail again, and told anew
    elif got["verdict"] == "fail" and (merged or new.get("told")):
        new.setdefault("row", at)
    return new


def rows(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The entries the **Inbox row: cadence check failed** draws (§4.5a): one row a PR."""
    return [c for c in checks if c.get("row")]


def dismiss(checks: list[dict[str, Any]], pr: int) -> tuple[list[dict[str, Any]], bool]:
    """Dismiss's write: `row` taken off the PR's entry, which stays as the record of the read —
    `told` kept, so a fail read later — at a new head, or after a new `done` names the PR — is
    the row again. The list, and whether
    a row stood."""
    stood = any(c.get("pr") == pr and c.get("row") for c in checks)
    return [{k: v for k, v in c.items() if k != "row"} if c.get("pr") == pr else c for c in checks], stood


def untold(c: dict[str, Any]) -> bool:
    """A first fail the member has not been told of. A merged PR's fail is the row's, not a line's."""
    return c.get("verdict") == "fail" and not c.get("told") and not c.get("merged")


def _what(c: dict[str, Any]) -> str:
    return ", ".join(str(r) for r in c.get("failed") or []) or "no row named"


def line(c: dict[str, Any], ref: str) -> str:
    """The fixed line typed into an idle member's composer."""
    return (
        f"[shiftlead] PR #{c['pr']} failed the cadence check: {_what(c)} — fix it, then report "
        f"`ao progress done {ref} --pr {c['pr']}` again"
    )


def clause(checks: list[dict[str, Any]]) -> str:
    """The clause at the end of every `ao` reply while an open PR of the member's fails: *PR #842
    fails the cadence check: review, ledger*. "" when none does."""
    return "; ".join(
        f"PR #{c['pr']} fails the cadence check: {_what(c)}"
        for c in checks
        if c.get("verdict") == "fail" and not c.get("merged")
    )


def read_by(s: Session, pr: int) -> str | None:
    """Who read the PR, as the home alone knows it (§4.9b *The reader*): the sender of a `reply` on
    the thread of an `ask` of this record's that carries `pr`, when that sender was one the ask
    named and is not the person. None otherwise — the `review` row is then *recorded*, the
    script's own word for a comment that was posted, and never *verified*."""
    asks = {e.root or e.id: e for e in s.outbox if e.kind == "ask" and e.pr == pr}
    for r in s.inbox:
        ask = asks.get(r.root) if r.kind == "reply" else None
        if ask is not None and r.from_ != PERSON and _bare(r.from_) in {_bare(x) for x in ask.to}:
            return r.from_
    return None


def _bare(address: str) -> str:
    return naming.split_address(address)[0]


def said(c: dict[str, Any]) -> str:
    """One check as `ao status -v` prints it: *#842 fail: review, ledger · review recorded*."""
    text = f"#{c.get('pr')} {c.get('verdict')}"
    if c.get("verdict") == "fail":
        text += f": {_what(c)}"
    who = c.get("read_by")
    return text + (f" · review read by {who}" if who else " · review recorded")
