"""Board write-back (design §4.4, TD-069 step 3): **Snooze**, **Done**, **Reply** (TD-142) and
**Decide** (TD-255) on one item of a repo's `docs/user_attention.md`, made by the host agent — and
its three **adds**, *Put on the board* (TD-140), an orphaned question's answer (TD-216) and the
person's answer to a ledger entry that waits on them (TD-565), the only lines this system ever adds
to a board.

A board is in ledgerboard's format and every line of it is read and written through the vendored
`ledgerboard.py` (ADR 2026-10-12, TD-585) — its `edit_line`, `item_line`, `decided_line` and
`subject("shiftlead", …)`, with no line shape of its own here; this module only edits the one item it
is pointed at, and only while origin's board still holds the item
the person was shown, open, word for word. **The edit is made on origin's head and landed there**
(TD-222, built by TD-264): in the host agent's own detached tree for the repo
(`~/.shiftlead/boards/<repo>/tree`), reset to `origin/<default>` at every press, committed with a
fixed message, pushed on a branch of its own and carried onto the default branch by a pull request
it opens and squash-merges at once — cadence §4.5's tool-made board edit. The person's checkout is
never written, so its branch, a dirty file or a rebase under way refuses nothing; it catches up by
the pull (design §6 *Pull*). Origin unreachable, a line only the checkout holds, and a line that
moved are each refused in words, with nothing landed.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sessionorc import gitinfo, ledgerboard, paths, workorders

BOARD = workorders.BOARD
ACTIONS = ("snooze", "done", "reply", "decide")
TOOL = "shiftlead"  # the `<tool>:` of every board commit's subject (ledgerboard's `subject`)
HEAD_MAX = 60
ANSWER_MAX = 80  # an answer in a commit subject
SUBJECT_MAX = 250  # a board commit's subject, which is its PR's title
GIT_TIMEOUT = 20.0
# One edit at a time on this host: each is a read, a write and a commit, and two interleaved would
# leave a commit saying *done* over a file where the other's write undid it (review of PR #474).
_EDIT = threading.Lock()


class Refused(Exception):
    """The edit was not made, and why, in words a person reads on the Inbox."""


def reply_tail(reply: str, by: str, today: str) -> str:
    """The words **Reply** appends to an item's own line (design §4.4, TD-142): ` — <by>, <date>:
    <reply>`. On the line, not under it: an item is one line, and the reader and the SessionStart
    hook read lines, so a reply typed over several lines is joined onto it with spaces. Refused for
    a reply that is empty."""
    words = " ".join(str(reply or "").split())
    if not words:
        raise Refused("a reply needs its text: what the next session should do")
    return f" — {by}, {today}: {words}"


def _day(today: str) -> date:
    return date.fromisoformat(today) if today else date.today()


def edit_line(
    line: str,
    text: str,
    action: str,
    due: str | None = None,
    *,
    reply: str = "",
    by: str = "",
    today: str = "",
    answer: str = "",
) -> str:
    """`line` with the item done (ticked, `Closed: <today>.`), snoozed to `due`, replied to (`reply`,
    by `by` on `today`) or decided (`answer`, on `today`) — ledgerboard's `edit_line`, which re-reads
    every edit and refuses one the reader would not read back. Refused unless `line` is an open item
    whose text is exactly `text` — the item the person was shown, not whatever moved onto that line —
    and, in front of the call, a decide on a line already decided (§4.4 *Decide*), which ledgerboard
    would rewrite, or with an answer carrying a field's name."""
    m = ledgerboard.ITEM_RE.match(line.rstrip("\n"))
    if m is None or m.group("text").strip() != text.strip():
        raise Refused(MOVED)
    end = "\n" if line.endswith("\n") else ""
    body = line.rstrip("\n")
    if action not in ACTIONS:
        raise Refused(f"unknown board action {action!r}: {' or '.join(ACTIONS)}")
    if action == "reply" and not " ".join(str(reply or "").split()):
        raise Refused("a reply needs its text: what the next session should do")
    if action == "decide":
        if not " ".join(str(answer or "").split()):
            raise Refused("a decide needs its answer: one of the item's Answers:")
        if ledgerboard.FIELD_NAME_RE.search(answer):
            # ledgerboard v1.0 reads such a line back unchanged, but the next reader of the words would
            # take the field for one (review of PR #861): refused here, in front of the call
            raise Refused("an answer may not carry Context:, Answers:, Decided: or Closed: — say it in other words")
        if ledgerboard.parse_decided(m.group("text")) is not None:
            raise Refused("this item is already decided: Reply says more to its session, Done closes it")
    to = None
    if action == "snooze":
        try:
            to = date.fromisoformat(str(due))
        except ValueError:
            raise Refused(f"a snooze needs a date as YYYY-MM-DD, not {due!r}") from None
    try:
        return ledgerboard.edit_line(body, action, to=to, answer=answer, reply=reply, by=by, today=_day(today)) + end
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


def message(text: str, action: str, due: str | None = None, *, answer: str = "", session: str = "") -> str:
    """The fixed commit message (design §4.4, cadence §4's carve-out): ledgerboard's
    `subject("shiftlead", …)` — the action, the item's head and the session that raised it, what a
    reviewer greps for; `append` for an add."""
    said = " ".join(str(answer or "").split())
    if len(said) > ANSWER_MAX:  # a *Not right:* carries a sentence; the subject is also the PR's title
        said = said[: ANSWER_MAX - 1].rstrip() + "…"
    try:
        got = ledgerboard.subject(TOOL, action, text, to=due, answer=said, session=session or None)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None
    # a forge's title holds 256 characters: a session name past that clips, keeping `(session …)` whole
    if len(got) > SUBJECT_MAX:
        head, _, who = got.rpartition(" (session ")
        who = who.removesuffix(")")[: max(8, SUBJECT_MAX - len(head) - 12)]
        got = f"{head[: SUBJECT_MAX - len(who) - 12]} (session {who})"
    return got


def _git(
    root: Path, *args: str, timeout: float = GIT_TIMEOUT, c_locale: bool = False
) -> subprocess.CompletedProcess[str]:
    """One git call; a git that cannot be run or does not finish is a refusal, never a raw error.
    `c_locale` runs it under `LC_ALL=C` on the rest of the environment, so its own words are English."""
    try:
        env = gitinfo.read_only_env() if args[:1] == ("status",) else None
        if c_locale:
            env = {**(os.environ if env is None else env), "LC_ALL": "C"}
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout, check=False, env=env
        )
    except subprocess.TimeoutExpired:
        raise Refused(f"git {args[0]} did not finish in {timeout:g} s in {root}") from None
    except OSError as e:
        raise Refused(f"git could not be run in {root}: {e}") from None


def default_branch(root: Path) -> str:
    """`origin`'s default branch as this clone last saw it, else `main`."""
    cp = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    ref = cp.stdout.strip() if cp.returncode == 0 else ""
    return ref.split("/", 1)[1] if "/" in ref else "main"


BUSY = ("index.lock", "MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")


def busy(root: Path) -> list[str]:
    """The git operations under way in the checkout — a merge, rebase, cherry-pick or index lock —
    by their marker's name; read by the pull (design §6 *Pull*). A board edit no longer reads it:
    the edit is made in the host agent's own tree, never in the checkout (§4.4, TD-264)."""
    gitdir = Path(_git(root, "rev-parse", "--absolute-git-dir").stdout.strip())
    return [n for n in BUSY if (gitdir / n).exists()]


def author(root: Path) -> str:
    """Who a reply is signed by: the checkout's git `user.name` — the name the commit is authored
    under — else *the person*."""
    try:
        name = _git(root, "config", "user.name").stdout.strip()
    except Refused:
        name = ""
    return name or "the person"


# -- origin's head (design §4.4 *The edit is made on origin's head, and landed there*, TD-264) ----

BOUND = 40.0  # seconds from the fetch to the merge (§4.4)
MOVED = "that line of the board no longer holds this item: reload the Inbox and try again"
NOT_ON_ORIGIN = "this line is not on origin yet: push the checkout first"
PR_BODY = "shiftlead's board write-back: one line of the board, at the person's press (cadence §4.5)."
RANK_BODY = (
    "shiftlead's rank flush: the rank file's lines of the person's moves on the Queue (design §4.4 *A move lands*)."
)


def unreachable(why: str) -> Refused:
    return Refused(f"origin could not be reached ({why}): the edit was not made")


def refused_push(reason: str) -> Refused:
    return Refused(f"origin refused the push ({reason}): the edit was not made")


_REJECTED = re.compile(r"^\s*! \[(?:remote )?rejected\](?:.*\(([^()]*)\))?")


def _push_refusal(cp: subprocess.CompletedProcess[str]) -> str | None:
    """The forge's reason when a failed push reached it and was refused (§4.4): the first `remote: error:`
    line, else the parenthesis ending a `! [remote rejected]` or `! [rejected]` line, else git's last line;
    None when the output holds neither, so the push never reached a forge that could refuse it."""
    lines = (cp.stderr or cp.stdout or "").splitlines()
    for line in lines:
        head, sep, rest = line.strip().partition("remote: error:")
        if sep and not head:
            return rest.strip()[:200]
    rejected = [m for line in lines if (m := _REJECTED.match(line))]
    if not rejected:
        return None
    for m in rejected:
        if m.group(1):
            return m.group(1).strip()[:200]
    return _why(cp, "git push").removeprefix("git push: ")[:200]


class _Neighbour(Refused):
    """A squash the forge refused while origin moved under it and the item still holds: a neighbouring
    line's change, which refuses nothing (§4.4) — the press is made once more on origin's new head."""


def _twice(press: Any) -> dict[str, Any]:
    try:
        return press()
    except _Neighbour:
        return press()


def _identity(root: Path) -> list[str]:
    """The checkout's git identity as `-c` options for the tree's commit (§4.4): read where the
    checkout is, so an `includeIf "gitdir:…"` identity that does not reach the tree's path still
    authors the commit."""
    out: list[str] = []
    for key in ("user.name", "user.email"):
        with contextlib.suppress(Refused):
            v = _git(root, "config", key).stdout.strip()
            if v:
                out += ["-c", f"{key}={v}"]
    return out


class _Clock:
    """The press's one bound, shared by every git and forge call in it."""

    def __init__(self, bound: float = BOUND) -> None:
        self.end = time.monotonic() + bound

    def left(self, step: str) -> float:
        left = self.end - time.monotonic()
        if left <= 0:
            raise unreachable(f"{step}: the {BOUND:g} s bound ran out")
        return min(left, GIT_TIMEOUT)


def _why(cp: subprocess.CompletedProcess[str], what: str) -> str:
    lines = (cp.stderr or cp.stdout or "").strip().splitlines()
    return f"{what}: {lines[-1][:200] if lines else f'exit {cp.returncode}'}"


def tree_dir(root: Path) -> Path:
    """The host agent's own tree for the repo at `root`: `~/.shiftlead/boards/<repo>/tree` (§4.4)."""
    return paths.home() / "boards" / Path(root).name / "tree"


def _tree(root: Path, clock: _Clock) -> tuple[Path, str]:
    """Fetch origin's default branch and give the tree at its head: kept between presses, made as
    the rollback's tree is (§6 *A rollback*) when it is missing, and remade once when it cannot be
    reset. Raises the unreachable refusal when the fetch fails."""
    if _git(root, "rev-parse", "--show-toplevel").returncode != 0:
        raise Refused(f"{root} is not a git checkout")
    want = default_branch(root)
    if _git(root, "remote", "get-url", "origin").returncode != 0:
        raise unreachable(f"{root} has no origin")
    cp = _git(root, "fetch", "-q", "origin", want, timeout=clock.left("git fetch"))
    if cp.returncode != 0:
        raise unreachable(_why(cp, "git fetch"))
    t = tree_dir(root)
    common = _common_dir(root)
    why = ""
    for _ in range(2):
        if not (t / ".git").exists() or _common_dir(t) != common:
            # missing, broken, or another clone's of the same name: this checkout's own, made afresh
            _drop_tree(root, t)
            t.parent.mkdir(parents=True, exist_ok=True)
            cp = _git(root, "worktree", "add", "-q", "--detach", str(t), f"origin/{want}", timeout=clock.left("tree"))
            if cp.returncode != 0:
                why = _why(cp, "git worktree add")
                continue
        cp = _git(t, "reset", "-q", "--hard", f"origin/{want}", timeout=clock.left("tree"))
        if cp.returncode == 0:
            return t, want
        why = _why(cp, "git reset")
        _drop_tree(root, t)
    raise Refused(f"the board's own tree {t} cannot be made or reset ({why}): the edit was not made")


def _common_dir(root: Path) -> str:
    cp = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return cp.stdout.strip() if cp.returncode == 0 else ""


def _drop_tree(root: Path, t: Path) -> None:
    if t.exists():
        _git(root, "worktree", "remove", "--force", str(t))
        if t.exists():
            shutil.rmtree(t, ignore_errors=True)
    _git(root, "worktree", "prune")


def _reset(t: Path, want: str) -> None:
    """The tree back at origin's head after a failure: what it held is never the next press's."""
    with contextlib.suppress(Refused):
        _git(t, "reset", "-q", "--hard", f"origin/{want}")


def _find(lines: list[str], line: int | None, text: str, key: str = "", root: Path | None = None) -> int | None:
    """The index of the open item the press is about: with a `key` (§4.4 *A board line's id*), the
    open item whose id it is, by the repo's own reader under `root`; then the item whose text is
    `text`, word for word — the reader's line first, then the whole file, since origin's lines may
    sit elsewhere than the checkout's (§4.4)."""
    if key and root is not None:
        found = []
        for i, ln in enumerate(lines):
            m = ledgerboard.ITEM_RE.match(ln.rstrip("\n"))
            if m is not None and workorders.ref(root, m.group("text").strip()) == key:
                found.append((i, m.group("text").strip()))
        # two open lines share an id only when their date, session and words do: the one the
        # person was shown, word for word, before the first (review of #1606)
        same = [i for i, t in found if text.strip() and t == text.strip()]
        if same or found:
            return (same or [found[0][0]])[0]

    def holds(ln: str) -> bool:
        m = ledgerboard.ITEM_RE.match(ln.rstrip("\n"))
        return m is not None and bool(text.strip()) and m.group("text").strip() == text.strip()

    if isinstance(line, int) and 1 <= line <= len(lines) and holds(lines[line - 1]):
        return line - 1
    return next((i for i, ln in enumerate(lines) if holds(ln)), None)


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as e:
        raise Refused(f"cannot read {path}: {e}") from None


def _gh(t: Path, clock: _Clock, step: str, *args: str) -> subprocess.CompletedProcess[str]:
    gh = shutil.which("gh")
    if gh is None:
        raise unreachable("gh is not installed")
    try:
        return subprocess.run(
            [gh, *args], cwd=str(t), capture_output=True, text=True, timeout=clock.left(step), check=False
        )
    except subprocess.TimeoutExpired:
        raise unreachable(f"{step} did not finish within the bound") from None
    except OSError as e:
        raise unreachable(f"gh could not be run: {e}") from None


def _land(
    root: Path,
    t: Path,
    want: str,
    msg: str,
    clock: _Clock,
    still: Any,
    *,
    rel: str | None = None,
    body: str = PR_BODY,
    prefix: str = "board",
) -> dict[str, Any]:
    """Commit the tree's board (or the file at `rel`: a rank file, §4.4 *A move lands*) and land it on
    `origin/<want>` by the one road the forge's rule allows (§4.4): a branch of the host agent's own, a PR
    it opens and squash-merges at once. A refused merge closes the PR and deletes the branch, and refuses
    the press as a moved line when `still()` — origin's board read again — no longer holds the item, else
    as unreachable."""
    base = _git(t, "rev-parse", "HEAD").stdout.strip()
    rel = rel or str(workorders.board_rel(root))
    cp = _git(
        t,
        *_identity(root),
        "commit",
        "--quiet",
        "-m",
        msg,
        "--only",
        "--",
        rel,
        timeout=clock.left("git commit"),
    )
    if cp.returncode != 0:
        _reset(t, want)
        raise Refused(f"the commit failed, and the board is as it was: {_why(cp, 'git commit')}")
    sha = _git(t, "rev-parse", "HEAD").stdout.strip()
    branch = f"{prefix}/{Path(root).name}/{datetime.now(UTC):%Y%m%d%H%M%S}-{sha[:7]}"
    pushed = False
    try:
        cp = _git(
            t, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", timeout=clock.left("git push"), c_locale=True
        )
        if cp.returncode != 0:
            reason = _push_refusal(cp)
            raise unreachable(_why(cp, "git push")) if reason is None else refused_push(reason)
        pushed = True
        cp = _gh(
            t,
            clock,
            "gh pr create",
            "pr",
            "create",
            "--base",
            want,
            "--head",
            branch,
            "--title",
            msg,
            "--body",
            body,
        )
        if cp.returncode != 0:
            raise unreachable(_why(cp, "gh pr create"))
        url = (cp.stdout or "").strip().splitlines()
        try:
            n = int(url[-1].rstrip("/").rsplit("/", 1)[1])
        except (IndexError, ValueError):
            raise unreachable(
                f"gh pr create: no pull request number in {url[-1][:120] if url else 'its output'!r}"
            ) from None
        try:
            cp = _gh(t, clock, "gh pr merge", "pr", "merge", str(n), "--squash")
        except Refused as e:  # timed out: it may have landed all the same, so it is read below
            cp = subprocess.CompletedProcess([], 1, "", str(e))
        if cp.returncode != 0:
            why = _why(cp, "gh pr merge")
            # a merge that failed after the forge took it (a timeout, an error on the reply) landed,
            # and a retried add must not write twice: the forge's own word on the PR first, since
            # origin's board may have changed elsewhere in the same moment; origin's board else
            state = _pr_state(t, n)
            landed = state == "MERGED"
            moved = shifted = False
            with contextlib.suppress(Refused):
                if not landed and _git(t, "fetch", "-q", "origin", want, timeout=GIT_TIMEOUT).returncode == 0:
                    landed = _git(t, "diff", "--quiet", sha, f"origin/{want}", "--", rel).returncode == 0
                    moved = not landed and not still()
                    # the forge's own word that it did not merge, and origin's board changed under it: never a
                    # retry on a forge that could not be asked (an add might write twice) or a move elsewhere
                    shifted = (
                        state in ("OPEN", "CLOSED")
                        and _git(t, "diff", "--quiet", base, f"origin/{want}", "--", rel).returncode != 0
                    )
            if not landed:
                _gh_quiet(t, "pr", "close", str(n))
                if moved:
                    raise Refused(MOVED)
                # origin moved under the squash and the item still holds: a neighbouring line's change
                raise _Neighbour(str(unreachable(why))) if shifted else unreachable(why)
    except Refused:
        if pushed:
            _git_quiet(t, "push", "-q", "origin", "--delete", branch)
        _reset(t, want)
        raise
    _git_quiet(t, "push", "-q", "origin", "--delete", branch)  # a repo that auto-deletes has done it
    _git_quiet(t, "fetch", "-q", "origin", want)
    head = _git(t, "rev-parse", "--short", f"origin/{want}").stdout.strip()
    _reset(t, want)
    return {"commit": head, "message": msg, "pr": n}


def _pr_state(t: Path, n: int) -> str | None:
    """The forge's word on pull request `n` — `OPEN`, `CLOSED` or `MERGED` — or None when it cannot be
    asked."""
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        cp = subprocess.run(
            [gh, "pr", "view", str(n), "--json", "state", "--jq", ".state"],
            cwd=str(t),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    state = cp.stdout.strip()
    return state if cp.returncode == 0 and state in ("OPEN", "CLOSED", "MERGED") else None


def _git_quiet(t: Path, *args: str) -> None:
    with contextlib.suppress(Refused):
        _git(t, *args)


def _gh_quiet(t: Path, *args: str) -> None:
    gh = shutil.which("gh")
    if gh is None:
        return
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run([gh, *args], cwd=str(t), capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)


def write_back(
    root: str | Path,
    line: int | None,
    text: str,
    action: str,
    due: str | None = None,
    *,
    reply: str = "",
    answer: str = "",
    key: str = "",
) -> dict[str, Any]:
    """Make one Snooze, Done, Reply or Decide on the board on origin's head and land it there (§4.4):
    in the host agent's own tree for the repo of the checkout `root`, which is never written.
    `key` is the line's id (`board:<key>`, §4.4 *A board line's id*), tried before the line and
    its text, and refused in its own words when no open line holds it.
    Returns `{commit, message, pr}` — `commit` origin's head after the merge; raises `Refused`
    with nothing changed on origin."""
    root = Path(root)
    if action not in ACTIONS:
        raise Refused(f"unknown board action {action!r}: {' or '.join(ACTIONS)}")
    with _EDIT:
        clock = _Clock()
        return _twice(lambda: _write_back(root, line, text, action, due, reply, answer, clock, key))


def _write_back(
    root: Path,
    line: int,
    text: str,
    action: str,
    due: str | None,
    reply: str = "",
    answer: str = "",
    clock: _Clock | None = None,
    key: str = "",
) -> dict[str, Any]:
    if key and not workorders.is_work_order(key):
        raise Refused(f"{key!r} is not a board line's id: board: and eight hex digits (design §4.4)")
    if not isinstance(line, int) and not key:
        raise Refused(MOVED)
    clock = clock or _Clock()
    if shutil.which("gh") is None:
        raise unreachable("gh is not installed")
    t, want = _tree(root, clock)
    rel = workorders.board_rel(root)
    path = t / rel
    lines = _read_lines(path) if path.exists() else []
    at = _find(lines, line, text, key, root)
    if at is None:
        if text and _ahead(root, want, line, text):
            raise Refused(NOT_ON_ORIGIN)
        raise Refused(workorders.NO_LINE.format(ref=key) if key else MOVED)
    # found by its id, the line's own text is the item's — a snooze or a reply since the page drew
    # it changes the text and never the id (§4.4 *A board line's id*)
    text = ledgerboard.ITEM_RE.match(lines[at].rstrip("\n")).group("text").strip()  # type: ignore[union-attr]
    by = author(root) if action == "reply" else ""
    lines[at] = edit_line(lines[at], text, action, due, reply=reply, by=by, answer=answer)
    msg = message(text, action, due, answer=answer)
    path.write_text("".join(lines), encoding="utf-8")

    def still() -> bool:
        return _find(_read_origin(t, want, rel), None, text) is not None

    return {**_land(root, t, want, msg, clock, still), "line": at + 1, "text": text}


def _ahead(root: Path, want: str, line: int | None, text: str) -> bool:
    """Whether the checkout holds the item where origin does not because the checkout's board is
    *ahead* — an uncommitted edit, or a board commit origin lacks — rather than behind: a checkout
    that has not pulled still shows a line origin has since done or replied to, which is a moved
    line, not an unpushed one."""
    rel = workorders.board_rel(root)
    mine = _read_lines(root / rel) if (root / rel).exists() else []
    if _find(mine, line, text) is None:
        return False
    if _git(root, "status", "--porcelain", "--", str(rel)).stdout.strip():
        return True
    last = _git(root, "log", "-1", "--format=%H", "--", str(rel)).stdout.strip()
    return bool(last) and _git(root, "merge-base", "--is-ancestor", last, f"origin/{want}").returncode != 0


def _read_origin(t: Path, want: str, rel: Path) -> list[str]:
    cp = _git(t, "show", f"origin/{want}:{rel.as_posix()}")
    return cp.stdout.splitlines(keepends=True) if cp.returncode == 0 else []


def item_line(text: str, due: str, today: str, session: str | None, host: str | None, context: str | None) -> str:
    """The one line *Put on the board* writes (design §4.5a), in the board's own `Format:` —
    ledgerboard's `item_line`: `- [ ] <today> (session `<name>` on <host>, or n/a) — <text>. Context:
    <about>. Due: <date>.` Refused for text that is empty or more than one line: an item is one line."""
    try:
        return ledgerboard.item_line(text, due, today, session, host, context)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


NEEDS = "## Needs the user"  # the board's section for the person's lines (cadence §3), a heading's words


def _top_of_needs(lines: list[str]) -> int:
    """Where the add goes: above the first item **of the *Needs the user* section** — another
    section's items (a board's parked in-flight work) are never where a person's line lands — or,
    when that section holds none, right under its heading and blank line. A board with no such
    heading takes it above its first item, else at the end."""
    head = next((i for i, ln in enumerate(lines) if ln.split()[:4] == NEEDS.split()), None)
    if head is None:
        return next((i for i, ln in enumerate(lines) if ledgerboard.is_item(ln)), len(lines))
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    first = next((i for i in range(head + 1, end) if ledgerboard.is_item(lines[i])), None)
    if first is not None:
        return first
    at = head + 1
    while at < end and not lines[at].strip():
        at += 1
    return at


def add(
    root: str | Path,
    text: str,
    due: str,
    *,
    session: str | None = None,
    host: str | None = None,
    context: str | None = None,
    today: str | None = None,
    answer: str | None = None,
) -> dict[str, Any]:
    """**Put on the board** (design §4.4, the write-back's first add; TD-140): one new line at the top
    of the open items of the board on origin's head for the checkout `root`'s repo, committed in the
    host agent's own tree as ledgerboard's `shiftlead: append <item head> (session <name>)` and landed
    by its own PR, as an edit is; the checkout is never written. Refused on the same conditions as an
    edit, touching nothing on origin. Returns `{commit, message, pr, line}` — `line` the new item's
    line number.

    With `answer`, the **second add** (§4.4, §4.10 *A question about a reference outlives its asker*,
    TD-216): `text` is the orphaned question's first paragraph and the person's answer follows it on
    the line as a reply does (` — <name>, <date>: <answer>`), committed by the same `append`."""
    root = Path(root)
    today = today or date.today().isoformat()
    words = text
    if answer is not None:
        words = " ".join(str(text or "").split()).rstrip(".") + reply_tail(answer, author(root), today)
    line = item_line(words, due, today, session, host, context)
    # the subject is the line's without the answer: a person's words stay on the board (ledgerboard's `subject`)
    bare = item_line(text, due, today, session, host, context) if answer is not None else line
    return _insert(root, line, message(ledgerboard.ITEM_RE.match(bare.rstrip("\n"))["text"], "append"))


def decided_line(title: str, ref: str, answers: list[str], default: int | None, words: str, today: str) -> str:
    """The one line the person's answer to a ledger entry writes (design §4.5 screen 6 *The ledger's
    entries that wait on you*, TD-565): ledgerboard's `decided_line`, a decided `decide` line in the
    board's own format, its `Answers:` the entry's with `(default)` on the one marked —
    `- [ ] decide <today> (person) — <title>. Context: <ref>. Due: <today>. Answers: a | b (default).
    Decided: <words> (<today>).` — so it is a work order at once (§4.4, §6 rule 6). Refused for empty
    words, words carrying a field's name, or a line the board's reader would not read back."""
    try:
        return ledgerboard.decided_line(title, ref, answers, default, words, today)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


def add_decided(root: str | Path, line: str, session: str = "") -> dict[str, Any]:
    """The third add (design §4.4 *Board write-back*, TD-565): `line` (`decided_line`) at the top of
    the open items of the board on origin's head, by the second add's road, committed by the same
    `append` — its session *n/a*, the person's, or `session`'s name for a road a person's session
    pressed (§4.8 *A person's session passes one of them*, TD-1117). Returns `{commit, message, pr, line}`."""
    text = ledgerboard.ITEM_RE.match(line.rstrip("\n"))["text"]
    return _insert(Path(root), line, message(text, "append", session=session))


def _insert(root: Path, line: str, msg: str) -> dict[str, Any]:
    """An add's press: `line` above the first item of the board's open items on origin's head, in
    the host agent's own tree, landed by its own PR as an edit is."""
    with _EDIT:
        clock = _Clock()
        if shutil.which("gh") is None:
            raise unreachable("gh is not installed")

        def press() -> dict[str, Any]:
            t, want = _tree(root, clock)
            path = t / workorders.board_rel(root)
            lines = _read_lines(path)
            at = _top_of_needs(lines)
            if lines and not lines[-1].endswith("\n") and at == len(lines):
                lines[-1] += "\n"
            lines.insert(at, line)
            path.write_text("".join(lines), encoding="utf-8")
            # an add moves no line, so a refused merge is never a moved line: unreachable, or made once more
            return {**_land(root, t, want, msg, clock, lambda: True), "line": at + 1}

        return _twice(press)


# -- a session's own edit, on its branch (design §4.7 `ao board edit`, TD-587) --------------------------

BRANCH_ACTIONS = ("done", "snooze")  # decide and reply are the person's words: the write-back's alone

board_path = workorders.board_path


def _default_names(root: Path) -> set[str]:
    """The branch names a session's board edit is never committed on: origin's default branch, and
    where the clone does not know it (no origin, or no `origin/HEAD`), `main`, `master` and git's
    `init.defaultBranch` — a guess that refuses too much rather than commit to a default branch."""
    cp = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    ref = cp.stdout.strip() if cp.returncode == 0 else ""
    if "/" in ref:
        return {ref.split("/", 1)[1]}
    init = _git(root, "config", "init.defaultBranch").stdout.strip()
    return {"main", "master", *([init] if init else [])}


def branch_edit(
    cwd: Path | str,
    action: str,
    *,
    line: int | None = None,
    expect: str = "",
    key: str = "",
    why: str = "",
    until: str = "",
    board: str | Path | None = None,
    today: str = "",
) -> dict[str, Any]:
    """`ao board edit done|snooze` (design §4.7, TD-587): a session's own edit of one line of the board
    **on the branch it is on**, in the tree `cwd` is in — ledgerboard's `edit_line` (`done` with `why`,
    `snooze` to `until`), committed on that branch with ledgerboard's `subject("shiftlead", …)`,
    touching nothing else, never pushed. The line is `line` opening with `expect` (its text or the
    raw line), or the open line whose id is `key` (§4.4 *A board line's id*). Refused on origin's
    default branch or a detached head (a session's board edit is a PR, never a commit to main), with
    a staged change or an uncommitted edit of the board (the commit would carry it), and for
    `decide` and `reply`, the person's words (cadence §3.5). Returns `{board, line, action, key,
    text, commit, message}`; needs no host agent."""
    if action not in BRANCH_ACTIONS:
        raise Refused(
            f"ao board edit makes {' or '.join(BRANCH_ACTIONS)}: {action!r} is the person's words, "
            "written by the write-back alone (cadence §3.5, design §4.7)"
        )
    to = None
    if action == "snooze":
        try:
            to = date.fromisoformat(str(until))
        except ValueError:
            raise Refused(f"a snooze needs --until as YYYY-MM-DD, not {until!r}") from None
    elif until:
        raise Refused("--until is for snooze only")
    if action != "done" and why:
        raise Refused("--why is for done only")
    if key and (line is not None or expect):
        raise Refused("name the line by --key, or by --line and --expect, not both")
    if not key and (line is None or not str(expect).strip()):
        raise Refused('name the line: --line <n> --expect "<its first words>", or --key board:<key>')
    if key and not workorders.is_work_order(key):
        raise Refused(f"{key!r} is not a board line's id: board: and eight hex digits (design §4.4)")
    top = _git(Path(cwd), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise Refused(f"{cwd} is not in a git work tree")
    root = Path(top.stdout.strip())
    if board is None:
        _, rel = board_path(root)
        if rel is None:
            raise Refused(
                f"no board here: {BOARD} does not exist and .shiftlead.yml names no board: (design §5 *The seams*)"
            )
        path = root / rel
    else:
        path = Path(board) if Path(board).is_absolute() else Path(cwd) / board
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise Refused(f"{path} is not in this work tree ({root})")
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not branch:
        raise Refused("HEAD is detached: a session's board edit is committed on its work branch, in its PR")
    if branch in _default_names(root):
        raise Refused(
            f"this is {branch}, a default branch: a session's board edit goes in the PR that did "
            "the work, never a commit to it (design §4.7)"
        )
    if _git(root, "diff", "--cached", "--quiet").returncode != 0:
        raise Refused("the index has staged changes: the board edit commits one file — commit or unstage them first")
    if _git(root, "status", "--porcelain", "--", str(path)).stdout.strip():
        raise Refused(f"{path.relative_to(root.resolve())} has uncommitted changes: the commit would carry them")
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise Refused(f"cannot read {path}: {e}") from None
    lines = raw.decode("utf-8", errors="surrogateescape").splitlines(keepends=True)
    if key:
        at = _find(lines, None, "", key, root)
        if at is None:
            raise Refused(workorders.NO_LINE.format(ref=key))
    else:
        if not 1 <= int(line) <= len(lines):
            raise Refused(f"line {line} is outside the board ({len(lines)} lines)")
        at = int(line) - 1
    body = lines[at].rstrip("\r\n")
    eol = lines[at][len(body) :]
    m = ledgerboard.ITEM_RE.match(body)
    if m is None:
        raise Refused(f"line {at + 1} is not an open item: {body[:80]!r}")
    text = m.group("text").strip()
    exp = str(expect).strip()
    if exp and not (text.startswith(exp) or body.lstrip().startswith(exp)):
        raise Refused(f"line {at + 1} no longer starts with the expected item — the board moved; re-read it. "
                      f"Line {at + 1} is: {body[:80]!r}")  # fmt: skip
    try:
        new = ledgerboard.edit_line(body, action, to=to, why=why or None, today=_day(today))
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None
    msg = message(text, action, to.isoformat() if to else None)
    lines[at] = new + eol
    path.write_bytes("".join(lines).encode("utf-8", errors="surrogateescape"))
    cp = _git(root, "commit", "-q", "-m", msg, "--", str(path))
    if cp.returncode != 0:
        path.write_bytes(raw)
        raise Refused(f"{_why(cp, 'git commit failed')} — the board is restored")
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return {
        "board": str(path),
        "line": at + 1,
        "action": action,
        "key": workorders.ref(root, text),
        "text": new,
        "commit": sha,
        "message": msg,
        "branch": branch,
    }


def land_rank(root: str | Path, rel: str, lines: dict[str, str | None], msg: str) -> dict[str, Any] | None:
    """Write `lines` (`{TD-n: key}`, None removing one) on origin's rank file at `rel` in the host agent's own
    tree for the checkout `root`, and land it by the board's road (§4.4 *A move lands*): a branch, a PR titled
    `msg` (ledgerboard's `queue_subject`), squash-merged at once. Two flushes conflict only on one line, and
    the later is made once more on origin's new head. Returns `{commit, message, pr}`, or None when origin's
    file already says every line; raises `Refused` with nothing changed on origin."""
    root = Path(root)
    with _EDIT:
        clock = _Clock()
        return _twice(lambda: _land_rank(root, rel, lines, msg, clock))


def _land_rank(root: Path, rel: str, lines: dict[str, str | None], msg: str, clock: _Clock) -> dict[str, Any] | None:
    if shutil.which("gh") is None:
        raise unreachable("gh is not installed")
    t, want = _tree(root, clock)
    path = t / rel
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as e:
        raise Refused(f"{rel} on origin cannot be read: {e}") from None
    try:
        new = ledgerboard.set_rank(text, lines)
    except ledgerboard.Refused as e:
        raise Refused(f"{rel}: {e}") from None
    if new == text:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    _git(t, "add", "--", rel, timeout=clock.left("git add"))  # a first rank file is new to the tree
    return _land(root, t, want, msg, clock, lambda: True, rel=rel, body=RANK_BODY, prefix="queue")
