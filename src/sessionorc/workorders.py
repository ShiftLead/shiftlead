"""Work orders (design §4.4 *Board write-back*, §6 rule 6, TD-380; built — TD-384): every open
*decided* line of a repo's attention board, listed by the repo reading beside the ledger's entries
as **`board:<key>`** — the first eight hex digits of a sha256 of the line's `item_key()`, which a
snooze, a reply and the decide itself leave unchanged — pickable, High, in every `free-pick` lane
of a team servicing the repo, and counted by rule 8, until a session closes the line.

The board is read in-process through the vendored `ledgerboard.py` (design §8 *Which side a thing
lives on*, ADR 2026-10-12, TD-585): its `parse_board`, `item_record`, `item_key` and line shapes,
never a second parser here and no agent-cadence script, so a repo with a board needs no agent-cadence.
Origin's side is this module's own fetch (`_against_origin`, §4.5 screen 6 *Boards are read against
origin*): a board merely behind origin is read from origin. A `fyi` line and a closed line are never
work orders; a line whose `Decided:` is gone leaves on the next reading.

The board itself is read once, into the repo reading's `boards` (`read_boards`, design §4.4 *Each
reading has one owner*, TD-615), and the orders are a filter over that reading (`orders`)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from sessionorc import gitinfo, ledgerboard, paths, reports

BOARD = Path("docs") / "user_attention.md"  # `board:`'s default (§5 *The seams*)
NO_BOARD = "no board: the Inbox is the person's channel"  # the seam's fixed words (§5)
PREFIX = "board:"
PR_PREFIX = "pr:"  # a red PR nobody holds (§4.4, TD-613)
FETCH_TIMEOUT = 45.0  # the fetch's bound; a fetch past it is a plain read, *fetch skipped (timeout)*
READ_TIMEOUT = 20.0
TERM_GRACE = 2.0  # a fetch past its bound is sent SIGTERM, then SIGKILL after this
HEAD_MOST = 120
_REF_RE = re.compile(r"board:[0-9a-f]{8}")
_PR_REF_RE = re.compile(r"pr:\d{1,6}")
NO_LINE = "no line {ref} on the board — reworded or closed"
# what a read against origin found (§4.5 screen 6): skipped — no comparison (`why` says why) · none —
# origin has no board · matches · behind — only origin moved, its copy is read · local — only this
# checkout moved · both — both moved, or no common history to tell
FETCH_CASES = ("skipped", "none", "matches", "behind", "local", "both")
# The board's sweep stamps (cadence §3.10), the cadence reader's own (agent-cadence `nudge_user_attention.py`
# `SWEEP_RE` and `SWEEP_DEEP_RE`), ported verbatim so the sweep seat and `/attention` never disagree on
# whether a board is swept (design §4.9b *The sweep*, TD-1090)
SWEEP_RE = re.compile(r"^Swept:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<meta>[^)]*)\))?", re.MULTILINE)
SWEEP_DEEP_RE = re.compile(r"^Swept-deep:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<meta>[^)]*)\))?", re.MULTILINE)


def is_work_order(ref: str) -> bool:
    """Whether a reference names a board line's work order: `board:` and eight hex digits."""
    return bool(_REF_RE.fullmatch(str(ref)))


def is_pr_order(ref: str) -> bool:
    """Whether a reference names a red PR's work order: `pr:` and the PR's number (TD-613)."""
    return bool(_PR_REF_RE.fullmatch(str(ref)))


def key(text: str) -> str:
    """`board:<key>` for an open item's text as the reading gives it — its line less the open tick."""
    return PREFIX + hashlib.sha256(ledgerboard.item_key(f"- [ ] {text}").encode("utf-8")).hexdigest()[:8]


def ref(root: str | Path, text: str) -> str:
    """`board:<key>` for a line of the board under `root` — **every board line's id** (design §4.4
    *A board line's id*, TD-603): the one derivation the Inbox's board rows, the write-back's presses,
    `ao board show`, `ao repo` and the work orders all use, ledgerboard's `item_key` in every repo —
    or empty for no text. `text` is the item less its tick."""
    if not text:
        return ""
    try:
        return key(text)
    except Exception:  # noqa: BLE001 — a line the key cannot take has no reference
        return ""


def head(text: str) -> str:
    """A line's head text, the work order's title: its bold head where it has one, else what
    follows the `(session …) —` lead, clipped."""
    out = ledgerboard.bold_head(text) or text.split(" — ", 1)[-1]
    out = " ".join(out.split()).rstrip(" .")
    return out if len(out) <= HEAD_MOST else out[: HEAD_MOST - 1].rstrip() + "…"


@dataclass
class Origin:
    """What one board's read against origin found: `case` (`FETCH_CASES`), `note` — the sentence for
    people, in the phrases the Inbox's origin note reads (§4.5a **origin note**) — `why` for a skip,
    `content`/`source` when origin's copy is the one to read (*behind*), and `theirs`, origin's copy in
    every case that read it, whichever copy is shown — the sweep stamp is read from it (§4.9b *The sweep*)."""

    case: str
    note: str
    why: str | None = None
    content: str | None = None
    source: str | None = None
    theirs: str | None = None


def _git(root: Path, args: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    """One git call under `root`, bounded: never a prompt, ssh in batch mode; past `timeout` its
    process group — git and the ssh or helper it started, which hold the pipes — is sent SIGTERM,
    then SIGKILL, and `TimeoutExpired` raised."""
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=5",
        **(gitinfo.READ_ONLY_ENV if args[:1] == ["status"] else {}),
    }
    argv = ["git", "-C", str(root), *args]
    with subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        start_new_session=True,
    ) as p:  # fmt: skip
        try:
            out, err = p.communicate(timeout=max(timeout, 0.0))
        except subprocess.TimeoutExpired:
            # the group this call started, and nothing else: SIGTERM, a grace for git, then SIGKILL to
            # whatever of the group is left — an ssh that ignored the SIGTERM outlives git otherwise
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                if sig == signal.SIGTERM:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        p.wait(timeout=TERM_GRACE)
            p.wait()
            raise subprocess.TimeoutExpired(argv, timeout) from None
        return subprocess.CompletedProcess(argv, p.returncode, out, err)


def default_branch(root: Path) -> str:
    """The repo's default branch: the first of origin/HEAD's target, `init.defaultBranch`, `main`
    and `master` that origin has, else `main` (agent-cadence's rule, cadence §9)."""
    got = _git(root, ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], READ_TIMEOUT)
    named = got.stdout.decode().strip().removeprefix("origin/") if got.returncode == 0 else ""
    cfg = _git(root, ["config", "init.defaultBranch"], READ_TIMEOUT)
    configured = cfg.stdout.decode().strip() if cfg.returncode == 0 else ""
    for b in (named, configured, "main", "master"):
        if b and _git(root, ["rev-parse", "--verify", "-q", f"refs/remotes/origin/{b}"], READ_TIMEOUT).returncode == 0:
            return b
    return "main"


def _against_origin(root: Path, board: Path, timeout: float = FETCH_TIMEOUT) -> Origin:
    """The checkout's board against `origin/<default>` (§4.5 screen 6 *Boards are read against
    origin*), never raising: one fetch of the default branch alone — never `--prune`, no local
    branch or working file moved — then the three-way compare of the checkout's file, origin's and
    their merge-base's. Merely behind (the checkout's untouched since the merge-base) reads origin's
    copy; anything else reads the checkout's and says which way it differs."""

    def blob(at: str, rel: str) -> str | None:
        got = _git(root, ["show", f"{at}:{rel}"], READ_TIMEOUT)
        return got.stdout.decode("utf-8", errors="replace") if got.returncode == 0 else None

    try:
        branch = default_branch(root)
        have = _git(root, ["rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}"], READ_TIMEOUT)
        # an explicit refspec: `fetch origin <branch>` moves only FETCH_HEAD where remote.origin.fetch is narrowed
        spec = [f"+refs/heads/{branch}:refs/remotes/origin/{branch}"] if have.returncode == 0 else []
        got = _git(root, ["fetch", "-q", "--no-prune", "origin", *spec], timeout)
        if got.returncode != 0:
            err = got.stderr.decode("utf-8", errors="replace").strip().splitlines()
            why = err[-1] if err else "git fetch failed"
            return Origin("skipped", f"fetch skipped ({why})", why=why)
        at = f"origin/{branch}"
        rel = (board.relative_to(root) if board.is_relative_to(root) else board_rel(root)).as_posix()
        theirs = blob(at, rel)
        if theirs is None:
            return Origin("none", f"fetched; no board at {at}")
        ours = board.read_text(encoding="utf-8", errors="replace") if board.is_file() else ""
        if theirs == ours:
            return Origin("matches", f"fetched; board matches {at}", theirs=theirs)
        mb = _git(root, ["merge-base", "HEAD", at], READ_TIMEOUT)
        if mb.returncode != 0:
            note = f"fetched; board DIFFERS from {at} (no common history to compare) — showing local"
            return Origin("both", note, theirs=theirs)
        base = blob(mb.stdout.decode().strip(), rel) or ""
        if ours == base:
            note = f"fetched; local clone is behind — showing {at}'s board"
            return Origin("behind", note, content=theirs, source=at, theirs=theirs)
        if theirs == base:
            return Origin("local", f"fetched; board DIFFERS from {at} (local edits not pushed)", theirs=theirs)
        return Origin("both", f"fetched; board DIFFERS from {at} (both sides changed) — showing local", theirs=theirs)
    except subprocess.TimeoutExpired:
        return Origin("skipped", "fetch skipped (timeout)", why="timeout")
    except Exception as e:  # noqa: BLE001 — a board read without origin beats no board
        return Origin("skipped", f"fetch skipped ({e})", why=str(e))


def board_path(root: Path | str) -> tuple[str, Path | None]:
    """The checkout's board (§5 *The seams* `board:`, TD-587): `("set", path)` for its `.shiftlead.yml`
    `board:`, relative to `root`; `("defaulted", BOARD)` when the key is unset and `docs/user_attention.md`
    exists; `("absent", None)` otherwise — the person's channel is the Inbox alone. A file that cannot be
    read, or a key that is not a non-empty string or is not a path inside the repo (absolute, or with a
    `..`: the write-back edits it in a tree of its own), is the key unset: the clients
    (`shiftlead.repoconfig`) refuse such a file by name."""
    try:
        doc = yaml.safe_load(paths.repo_file(root).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        doc = None
    got = doc.get("board") if isinstance(doc, dict) else None
    if isinstance(got, str) and got.strip() and inside(Path(got.strip())):
        return "set", Path(got.strip())
    if (Path(root) / BOARD).is_file():
        return "defaulted", BOARD
    return "absent", None


def inside(rel: Path) -> bool:
    """Whether `rel` is a path from a repo's root that stays inside it: relative, with no `..`."""
    return not rel.is_absolute() and ".." not in rel.parts


def board_rel(root: Path | str) -> Path:
    """The board's path under `root` that the write-back edits on origin's head: `board_path`'s, else
    `docs/user_attention.md` — the checkout may lack a file origin holds."""
    return board_path(root)[1] or BOARD


def _stamp(rx: re.Pattern[str], content: str) -> str | None:
    """The first line of `content` that `rx` matches with a date, as `YYYY-MM-DD` — None when there is
    none, or its date is not a calendar date (it reads as absent: the sweep rewrites it)."""
    m = rx.search(content)
    if m is None:
        return None
    try:
        return date.fromisoformat(m.group("date")).isoformat()
    except ValueError:
        return None


def swept(content: str) -> dict[str, str | None]:
    """A board's sweep stamps (design §4.9b *The sweep*, TD-1090): `{at, deep_at}`, each the date of
    the first `Swept:` / `Swept-deep:` line carrying one, or None — `{at: None}` is a board never swept."""
    return {"at": _stamp(SWEEP_RE, content), "deep_at": _stamp(SWEEP_DEEP_RE, content)}


def board_items(content: str, today: date) -> list[dict[str, Any]]:
    """The open items of a board's text, each ledgerboard's `item_record` with its id as `key`."""
    out: list[dict[str, Any]] = []
    for it in ledgerboard.parse_board(content, warn=False):
        out.append({**ledgerboard.item_record(it, today), "key": ref("", it.text)})
    return out


def read_boards(root: str | Path, *, fetch: bool = True, board: str | Path | None = None) -> dict[str, Any]:
    """The repo's board as the host agent keeps it (design §4.4 *Each reading has one owner*, *The
    boards*, TD-615), read in-process through ledgerboard (TD-585): `{boards: [...], today}`, each
    board `{label, board, root, source, fetch_note, fetch_case, fetch_why, items}` — and `swept`, once
    it was read against origin (below) — and each open item
    ledgerboard's record of it (line, text, due, answers, decided, refs, session, detail, …) with its
    id beside it as `key` (`board:<key>`, *A board line's id*) — or `{error}` when the board could
    not be read. No board is no boards and no error. `fetch` reads against origin (`_against_origin`,
    *Boards are read against origin*); a fetch that fails or passes its bound reads the checkout's
    file, its `fetch_note` *fetch skipped (<why>)*, so the page says origin could not be reached.

    `board` reads that file in place of the checkout's, named as the checkout's board read from
    origin: the host agent's own tree after a write-back (`board.tree_dir`), which is origin's head
    with the press landed, so the press is in the reading before the checkout pulls it.

    `swept` (§4.9b *The sweep*, TD-1090) is the stamp of origin's copy, whichever copy is shown: written
    only by a read against origin — `{at, deep_at}` (`swept`), or None when origin holds no board — and
    by `board`, the tree a write-back pushed. A read of the checkout alone (no fetch, or a fetch
    skipped) has no `swept` key, and the caller carries the last one forward."""
    root = Path(root)
    rel = board_path(root)[1]
    if rel is None:
        return {"boards": []}  # NO_BOARD (§5 *The seams*)
    checkout = root / rel
    path = Path(board) if board is not None else checkout
    if not path.is_file():
        return {"boards": []}
    today = datetime.now().date()  # the board's dates are civil dates, local
    found = _against_origin(root, checkout) if fetch and board is None else None
    try:
        content = found.content if found is not None and found.content is not None else path.read_text(encoding="utf-8")
        items = board_items(content, today)
    except (OSError, UnicodeDecodeError) as e:
        return {"error": f"{path} could not be read ({type(e).__name__})"}
    b: dict[str, Any] = {
        "label": root.name,
        "board": str(checkout),
        "root": str(root),
        "source": found.source if found is not None else None,
        "fetch_note": found.note if found is not None else None,
        "fetch_case": found.case if found is not None else None,
        "fetch_why": found.why if found is not None else None,
        "items": items,
    }
    if found is not None and found.case != "skipped":
        b["swept"] = swept(found.theirs) if found.theirs is not None else None
    if board is not None:
        # as the checkout's board, read from origin: the *behind* case (§4.5a **origin note**)
        b.update(source="origin", fetch_case="behind", swept=swept(content))
    return {"boards": [b], "today": today.isoformat()}


def orders(reading: dict[str, Any]) -> list[dict[str, Any]]:
    """The work orders of a `read_boards` reading — its open decided lines that are not `fyi`, each
    `{id, title, text, line, decided: {text, date}, refs, session, kind}` — a filter over the one
    reading, never a second read of the board (§4.4 *The boards*)."""
    out: list[dict[str, Any]] = []
    for b in reading.get("boards") or []:
        for it in (b.get("items") or []) if isinstance(b, dict) else []:
            if not isinstance(it, dict) or not isinstance(it.get("decided"), dict) or it.get("kind") == "fyi":
                continue
            if not it.get("key") or not it.get("text"):
                continue
            out.append(
                {
                    "id": it["key"],
                    "title": head(str(it["text"])),
                    "text": str(it["text"]),
                    "line": it.get("line"),
                    "decided": {"text": str(it["decided"].get("text") or ""), "date": it["decided"].get("date")},
                    "refs": [str(r) for r in it.get("refs") or []],
                    "session": it.get("session"),
                    "kind": it.get("kind"),
                }
            )
    return out


def read(root: str | Path, *, fetch: bool = True) -> dict[str, Any]:
    """The repo's work orders: `{orders: [...]}` (`orders`), or `{error}` when the board could not be
    read — `read_boards` and its filter, for a caller that wants the orders alone."""
    got = read_boards(root, fetch=fetch)
    return got if "error" in got else {"orders": orders(got)}


def entry(order: dict[str, Any]) -> dict[str, Any]:
    """A work order as the lanes and the pages read an entry (§4.4 *Repo facts*): High, pickable,
    `free-pick`'s kind, no owner — `owner:<word>` never narrows one out (§6 rule 6) — and marked
    `work_order`, so a reader that counts the ledger's priorities can leave it out."""
    return {
        "id": order["id"],
        "title": order.get("title") or "",
        "priority": "High",
        "owner": "",
        "kind": "",
        "type": "debt",
        "blocked_by": [],
        "pickable": "yes",
        "for_page": "pickable",
        "work_order": True,
        "decided": order.get("decided"),
        "refs": order.get("refs") or [],
        "session": order.get("session"),
        "line": order.get("line"),
        "text": order.get("text") or "",
    }


def board_lines(root: str | Path, *, fetch: bool = True) -> tuple[list[str], str]:
    """The board under the checkout `root` as lines, and where they were read: origin's default
    branch after a fetch (`origin/<branch>`), else the checkout's file (`checkout`) — design §4.7
    `ao board show`. No board is `([], "")`."""
    root = Path(root)
    rel = board_path(root)[1]
    if rel is None:
        return [], ""
    if fetch:
        try:
            # a fetch that failed leaves origin's ref as stale as the checkout: the checkout it is
            fetched = subprocess.run(
                ["git", "-C", str(root), "fetch", "-q", "origin"], capture_output=True, timeout=FETCH_TIMEOUT
            )
            cp = subprocess.run(
                ["git", "-C", str(root), "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"],
                capture_output=True, text=True, timeout=READ_TIMEOUT,
            )  # fmt: skip
            heads = [cp.stdout.strip()] if cp.stdout.strip() else ["origin/main", "origin/master"]
            for head in heads if fetched.returncode == 0 else ():
                cp = subprocess.run(
                    ["git", "-C", str(root), "show", f"{head}:{rel.as_posix()}"],
                    capture_output=True, text=True, errors="replace", timeout=READ_TIMEOUT,
                )  # fmt: skip
                if cp.returncode == 0:
                    return cp.stdout.splitlines(), head
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        return (root / rel).read_text(encoding="utf-8").splitlines(), "checkout"
    except OSError:
        return [], ""


def show(root: str | Path, want: str, *, fetch: bool = True) -> dict[str, Any] | None:
    """The line of the board under `root` whose id is `want` (design §4.7 `ao board show`): `{key,
    line, text, detail, open, source}` — `text` the whole line less its tick, `detail` its detail
    block — open or closed, the first that holds it; None when no line does. The line shapes are
    ledgerboard's (design §8): none is written here."""
    lines, source = board_lines(Path(root), fetch=fetch)
    for n, ln in enumerate(lines, 1):
        m = ledgerboard.ITEM_RE.match(ln) or ledgerboard.CLOSED_ITEM_RE.match(ln)
        if m is None or ref(root, m.group("text")) != want:
            continue
        return {
            "key": want,
            "line": n,
            "text": m.group("text").strip(),
            "detail": ledgerboard.detail_block(lines, n),
            "open": m.re is ledgerboard.ITEM_RE,
            "source": source,
        }
    return None


# -- a red PR nobody holds (design §4.4 *A red PR nobody holds is a work order*, TD-613) -----------


def holds_pr(record: Any, pr: dict[str, Any]) -> bool:
    """Whether a live record holds an open PR: not `exited` or `closed`, not superseded, no
    `out_of_work`, and either a `progress` entry names it (`pr:<n>` or its `pr`, claimed or done) or
    its checkout's branch is the PR's head."""
    if record.state in ("exited", "closed") or record.superseded_by or record.out_of_work:
        return False
    n = pr.get("number")
    if any(e.ref == f"{PR_PREFIX}{n}" or e.pr == n for e in record.progress):
        return True
    branch = (record.git or {}).get("branch")
    return bool(branch) and branch == pr.get("branch")


def red_holders(
    open_prs: list[dict[str, Any]], records: list[Any], now: datetime, after: timedelta
) -> dict[str, list[str]]:
    """Who holds each red PR past `after`, by number as a string: the names of the live records
    `holds_pr` finds, for the pages' *held by <name>* (TD-652; the reading carries them, so no page
    re-derives the test). A PR nobody holds, or not yet red for `after`, is not listed."""
    out: dict[str, list[str]] = {}
    for pr in open_prs:
        since = pr.get("red_since") if isinstance(pr, dict) else None
        if not since or not isinstance(pr.get("number"), int):
            continue
        try:
            red_since = datetime.fromisoformat(str(since))
        except ValueError:
            continue
        if red_since.tzinfo is None:  # a stamp with no offset is UTC, as every stamp in the store is
            red_since = red_since.replace(tzinfo=UTC)
        if now - red_since < after:
            continue
        if held := [str(r.name or r.id) for r in records if holds_pr(r, pr)]:
            out[str(pr["number"])] = held
    return out


def is_sync_order(pr: dict[str, Any]) -> bool:
    """A sync PR the reading can order (design §4.4 *A sync PR is the team's at once*, TD-684): any
    `checks` but *pending*, and *not_run* (CI that never started is the person's, TD-686), which wait —
    unless it is conflicting, when no check will run and a team can cure that part — and one the home
    holds (`sync.mark`'s `sync_home`, §6 *Sync*, TD-685). Every other is an order."""
    waits = pr.get("checks") in ("pending", "not_run") and not pr.get("conflicting")
    # the home's: merged at its head, or green with no verdict there while the switch is on (§6 *Sync*, TD-685)
    waits = waits or bool(pr.get("sync_home"))
    return bool(pr.get("sync")) and bool(pr.get("sync_since")) and not waits


def sync_reason(pr: dict[str, Any]) -> str:
    """Why a sync PR waits on someone, in its order's words: the failing checks, *conflicting*,
    *draft*, else *green: review and merge it* — or, where the home judged it (§6 *Sync*), its verdict's `why`."""
    if pr.get("sync_why"):
        return str(pr["sync_why"])
    why = [*(pr.get("failing") or []), *(["conflicting"] if pr.get("conflicting") else [])]
    why += ["CI never ran"] if pr.get("checks") == "not_run" else []
    why += ["draft"] if pr.get("draft") else []
    return ", ".join(why) or "green: review and merge it"


def pr_note(pr: dict[str, Any]) -> str:
    """The one line an idle holder of a red PR, or of a sync PR, is told."""
    if is_sync_order(pr):
        return (
            f"sync PR #{pr['number']} has been open since {pr.get('sync_since')}: {sync_reason(pr)} — fix it or say why"
        )
    why = ", ".join(pr.get("failing") or []) or ("conflicting with its base" if pr.get("conflicting") else "red")
    return f"PR #{pr['number']} has been red since {pr.get('red_since')}: {why} — fix it or say why"


def pr_order(pr: dict[str, Any]) -> dict[str, Any]:
    """A red PR nobody holds as the lanes and the pages read an entry: `pr:<n>`, the PR's title, High,
    pickable, its `Context` the URL and the failing checks. `pr_order` marks it, and every `free-pick`
    lane takes it: the grinders' pick list (§4.9b *No anchor seat*, TD-757). A sync PR's (TD-684) is marked `sync`, with
    `sync_since` and its `reason` (`sync_reason`), which is its `Context` beside the URL."""
    failing = list(pr.get("failing") or [])
    sync = is_sync_order(pr)
    why = sync_reason(pr) if sync else ""
    red = [", ".join(failing), "conflicting" * bool(pr.get("conflicting"))]
    red += ["CI never ran"] if pr.get("checks") == "not_run" else []  # ordered by its conflict alone (TD-686)
    context = " · ".join(filter(None, [str(pr.get("url") or ""), *([why] if sync else red)]))
    return {
        "id": f"{PR_PREFIX}{pr['number']}",
        "title": str(pr.get("title") or ""),
        "priority": "High",
        "owner": "",
        "kind": "",
        "type": "debt",
        "blocked_by": [],
        "pickable": "yes",
        "for_page": "pickable",
        "work_order": True,
        "pr_order": True,
        "pr": pr["number"],
        "url": str(pr.get("url") or ""),
        "author": str(pr.get("author") or ""),
        "checks": pr.get("checks"),
        "failing": failing,
        "conflicting": bool(pr.get("conflicting")),
        "red_since": pr.get("red_since"),
        "context": context,
        "refs": [],
        "text": "",
        **({"sync": True, "sync_since": pr.get("sync_since"), "reason": why} if sync else {}),
    }


def red_prs(
    open_prs: list[dict[str, Any]],
    records: list[Any],
    now: datetime,
    told: dict[str, dict[str, str]],
    after: timedelta,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], list[tuple[str, dict[str, Any]]]]:
    """A repo's red PRs read against its live records: the `pr:<n>` orders, the memory of whom was
    told (`{n: {red_since, at}}`, one per red spell), and the notes to send now `(record id, pr)`.

    A PR red or conflicting for `after` (from `red_since`) with no holder is an order. Held, and
    every holder `idle`: each is told once, and `after` later, still red and the holders still idle,
    they no longer count and it is an order. A holder at work keeps it off the list.

    A sync PR (`is_sync_order`, TD-684) is an order from the first reading, with no `after`: unheld,
    at once, whatever its checks but *pending*; its idle holders are told and passed over as a red
    PR's, keyed on `sync_since` in place of `red_since`. Sync orders come first in the list.

    A draft (the reading's `draft`) that `is_sync_order` does not order is no order and no note, however
    long it is red (design §4.4 *A draft is no work order*, TD-745); its spell's memory is kept, so a PR
    marked ready red past `after` is an order at once and a holder told before the draft is not told again.

    A fork's PR (the reading's `fork`) is no order and no note either (design §4.4 *A fork's PR is no work
    order*, TD-1285): its fix is its author's, and running its code here is the person's call."""
    orders: list[dict[str, Any]] = []
    kept: dict[str, dict[str, str]] = {}
    notes: list[tuple[str, dict[str, Any]]] = []
    for pr in open_prs:
        if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
            continue
        sync = is_sync_order(pr)
        since = pr.get("sync_since") if sync else pr.get("red_since")
        if not since:
            continue
        try:
            red_since = datetime.fromisoformat(str(since))
        except ValueError:
            continue
        if red_since.tzinfo is None:  # a stamp with no offset is UTC, as every stamp in the store is
            red_since = red_since.replace(tzinfo=UTC)
        key = str(pr["number"])
        # the memory's key is `red_since` whatever the spell: a sync PR's is its `sync_since`
        was = told.get(key) if (told.get(key) or {}).get("red_since") == since else None
        if was:
            kept[key] = was  # this red spell's memory stays while it lasts
        if pr.get("draft") and not sync:
            continue  # a draft is no order and no note, its memory kept for when it is ready (TD-745)
        if pr.get("fork") and not sync:
            continue  # a fork's PR is no order and no note: its precheck is the person's (TD-1285)
        holders = [r for r in records if holds_pr(r, pr)]
        if not holders and sync:
            orders.append(pr_order(pr))
            continue
        if now - red_since < after:
            continue
        if not holders:
            orders.append(pr_order(pr))
            continue
        if any(r.state != "idle" for r in holders):
            continue
        if was is None:
            kept[key] = {"red_since": since, "at": now.isoformat()}
            notes.extend((r.id, pr) for r in holders)
        elif now - datetime.fromisoformat(was["at"]) >= after:
            orders.append(pr_order(pr))
    orders.sort(key=lambda o: not o.get("sync"))  # a sync order first (a stable sort)
    return orders, kept, notes


def ci_not_run(repos: dict[str, dict[str, Any]], promotes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Everything the home's registry holds whose CI never started, by account (design §4.4 *The person
    is told once per account*, TD-686): `repos` the repo readings by root (each open PR reading
    `checks: not_run`), `promotes` the promote readings by repo (each default branch whose reading
    carries `checks_not_run`). Keyed by the `origin` owner in lower case — a GitHub login, else the
    repo is left out — each `{owner, reason, kind, items}`, `reason` and `kind` the first item's and
    each item `{repo, root, runs}` with `pr` and `url` for a PR or `main` (its sha) for a default
    branch. TD-687's Inbox row and Telegram line read it."""
    out: dict[str, dict[str, Any]] = {}

    def add(owner: str | None, why: dict[str, Any], item: dict[str, Any]) -> None:
        if not owner:
            return
        got = out.setdefault(owner.lower(), {"owner": owner, "reason": "", "kind": "", "items": []})
        if not got["items"]:
            got["reason"], got["kind"] = str(why.get("reason") or ""), str(why.get("kind") or "other")
        got["items"].append({**item, "runs": list(why.get("runs") or [])})

    for root in sorted(repos):
        reading = repos[root] if isinstance(repos[root], dict) else {}
        for pr in (reading.get("prs") or {}).get("open") or []:
            if not isinstance(pr, dict) or pr.get("checks") != "not_run" or not isinstance(pr.get("not_run"), dict):
                continue
            url = str(pr.get("url") or "")
            m = re.search(r"github\.com/[^/]+/([^/]+)/pull/", url)
            repo = m[1] if m else Path(root).name
            item = {"repo": repo, "root": root, "pr": pr.get("number"), "url": url}
            add(reports.github_owner(url), pr["not_run"], item)
    for name in sorted(promotes):
        r = promotes[name] if isinstance(promotes[name], dict) else {}
        if isinstance(r.get("checks_not_run"), dict) and r.get("main"):
            item = {"repo": name, "root": str(r.get("root") or ""), "main": r["main"]}
            add(reports.github_owner(r.get("origin")), r["checks_not_run"], item)
    return out


CI_SPELL_CLEAR = 2  # successful readings in a row that group nothing for an owner, with no re-run pending
RUN_DONE = "completed"  # an Actions run's `status` once it has ended; every other status is pending


def ci_failed_owners(repos: dict[str, dict[str, Any]]) -> set[str]:
    """The owners, in lower case, of every repo whose last PR read failed (design §4.4 *Its spell*): for
    them this reading is no reading, and their spells' clear counts are left as they were (TD-687)."""
    out: set[str] = set()
    for reading in repos.values():
        prs = (reading or {}).get("prs") if isinstance(reading, dict) else None
        if isinstance(prs, dict) and prs.get("error") and (owner := reports.github_owner(reading.get("remote"))):
            out.add(owner.lower())
    return out


def ci_rerun_pending(spell: dict[str, Any]) -> bool:
    """Whether any run a **Re-run** asked for is still queued or running, as last read (a failed read
    is pending, design §4.4 *A Re-run's runs are read*)."""
    return any(r.get("pending") for r in ((spell.get("rerun") or {}).get("runs") or []) if isinstance(r, dict))


def ci_spells(
    spells: dict[str, dict[str, Any]], grouped: dict[str, dict[str, Any]], failed: set[str], now: str
) -> dict[str, dict[str, Any]]:
    """One successful reading's step of every **spell** (design §4.4 *Its spell*, TD-687): `spells` as the
    home keeps them, `{<owner>: {owner, since, clear, row, rerun?}}`, keyed in lower case; `grouped`
    `ci_not_run`'s reading; `failed` the owners `ci_failed_owners` names. An owner grouped begins a spell
    at `now` or keeps its own, its `clear` back to 0 and its `row` the grouping's; one not grouped counts
    the reading toward `CI_SPELL_CLEAR` — unless its reading failed (no change) or a re-run's run is
    pending (back to 0) — and its spell ends at the count. Never mutates `spells`."""
    out: dict[str, dict[str, Any]] = {}
    for key, row in grouped.items():
        old = spells.get(key) or {"owner": row.get("owner") or key, "since": now}
        out[key] = {**old, "clear": 0, "row": {k: row.get(k) for k in ("owner", "reason", "kind", "items")}}
    for key, old in spells.items():
        if key in out:
            continue
        if key in failed:
            out[key] = dict(old)
            continue
        clear = 0 if ci_rerun_pending(old) else int(old.get("clear") or 0) + 1
        if clear < CI_SPELL_CLEAR:
            out[key] = {**old, "clear": clear}
    return out


def ci_rerun_runs(spell: dict[str, Any]) -> list[tuple[str, int]]:
    """Every `(root, run)` the spell's row names, once each and in the row's order: what **Re-run** asks
    GitHub to re-run (design §4.5a *Inbox row: CI not starting*)."""
    seen: dict[tuple[str, int], None] = {}
    for item in (spell.get("row") or {}).get("items") or []:
        if not isinstance(item, dict) or not item.get("root"):
            continue
        for run in item.get("runs") or []:
            with contextlib.suppress(TypeError, ValueError):
                seen.setdefault((str(item["root"]), int(run)), None)
    return list(seen)
