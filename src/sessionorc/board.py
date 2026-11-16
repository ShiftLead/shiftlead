"""Board write-back (design §4.4, TD-069 step 3): **Snooze**, **Done**, **Reply** (TD-142) and
**Decide** (TD-255) on one item of a repo's `docs/user_attention.md`, made by the host agent — and
its three **adds**, *Put on the board* (TD-140), an orphaned question's answer (TD-216) and the
person's answer to a ledger entry that waits on them (TD-565), the only lines this system ever adds
to a board.

A board is in ledgerboard's format and every line of it is read through the vendored `ledgerboard`
package (ADR 2026-10-12, TD-585) and **written through its board writer, `ledgerboard.board`** (ADR
2026-11-03, TD-1330) — `plan_edit` for an edit, `plan_add` for an add, `apply` to write the file —
with no line shape of its own here. What ShiftLead keeps is its own (ledgerboard's target design §1.1
*What the consumer keeps*): the lock, the temporary worktree, the commit and its subject, the push and
the PR. This module only edits the one item it is pointed at, and only while origin's board still holds the item
the person was shown, open, word for word. **The edit is made on origin's head and landed there**
(TD-222, built by TD-264): in the host agent's own detached tree for the repo
(`~/.shiftlead/boards/<repo>/tree`), reset to `origin/<default>` at every press, committed with a
fixed message, pushed on a branch of its own and carried onto the default branch by a pull request
it opens and squash-merges at once — cadence §4.5's tool-made board edit. The person's checkout is
never written, so its branch, a dirty file or a rebase under way refuses nothing; it catches up by
the pull (design §6 *Pull*). Origin unreachable, a line only the checkout holds, and a line that
moved are each refused in words, with nothing landed.

Since ledgerboard v3.0 (TD-1881) the board is a directory, one file per item (`docs/user_attention/<id>.md`,
closed ones under `archive/<YYYY-MM>/`, the stub `docs/user_attention.md` naming it): every read is the `Board`
`load_board()` gives, an item is found by its reference (`board:<8 hex>`, its id's last eight) and written by its
id (`plan_edit(board, action, id, …)`), and a commit stages the board's directory and stub whole. The writer
refuses a v2 board file, and that refusal is the press's, in its words.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sessionorc import gitinfo, ledgerboard, paths, workorders
from sessionorc import ledger as ledger_mod
from sessionorc.ledgerboard import board as lb_board
from sessionorc.ledgerboard import ledger as lb_ledger

BOARD = workorders.BOARD
ACTIONS = ("snooze", "due", "done", "reply", "decide")  # `due` (v2.3) moves Due:; `snooze` writes `Hide until:`
TOOL = "shiftlead"  # the `<tool>:` of every board commit's subject (ledgerboard's `subject`)
HEAD_MAX = 60
ANSWER_MAX = 80  # an answer in a commit subject
SUBJECT_MAX = 250  # a board commit's subject, which is its PR's title
GIT_TIMEOUT = 20.0
# One edit at a time on this host: each is a read, a write and a commit, and two interleaved would
# leave a commit saying *done* over a file where the other's write undid it (review of PR #474).
_EDIT = threading.Lock()

# **Have a session do it** (TD-1543, built by TD-1624; §4.5 screen 12 *Three verbs: Have a session do it*, §4.4
# *Decide*): the fixed answer an open `act` line's press writes, exactly as the page sends it, and the asker's mark
# that a step is the person's alone, which the page's draw and the agent's check both read by `marked_for_person`
HAVE_A_SESSION = "have a session do it"
ONLY_YOU = "only you can do this"
# where a line's own words end (§4.5 screen 12): ledgerboard's field names, `Doer:` (TD-1661's) and `Due:` in any case
_MARK_END_RE = re.compile(r"\b(?:Context|Parts|Doer|Hide until|Answers|Lifts|Decided|Closed):|\b(?i:due):")
WORD_FOR_WORD = "a decide records one of the item's own answers, word for word: anything else is a Reply (design §4.4)"
NOT_ACTS_ANSWER = "have a session do it is an act line's answer: this item's answers are its own"
MARKED = "this step is marked only you can do this: Done closes it once you have"
# the kinds a live look is written as: `look` since dev-cadence TD-082, `watch` before it (TD-292); moved here from
# the page's inbox so the Reply's form reading and the page's draw read one pair (TD-1698)
LOOK_KINDS = ("look", "watch")
WORKS = "Works"  # a live look's first answer, cadence §3.5's word (the second is the `Not right: <what>` form)
WHY_ON_DONE = "a why is a Done's alone: it is written in the line's Closed: field (design §4.4)"
NO_DOER = "this line names no Doer: Have a session do it hands it to this repo's lane"


def item_ref(item: ledgerboard.BoardItem) -> str:
    """`board:<8 hex>` of a board item (§4.4 *A board line's id*, TD-1881): its id's last eight hex digits, the
    reference every reader and press names it by. A split v2 item's nonce is its old line's `board:<key>`, so a
    reference persisted before the split names it still; "" for an item with no id."""
    return workorders.PREFIX + item.id[-8:] if item.id else ""


def _words(text: str | ledgerboard.BoardItem) -> str:
    """An item's words: a BoardItem's `words` (an item file's heading, ledgerboard v3.0), else `text` as given."""
    return text.words if isinstance(text, ledgerboard.BoardItem) else str(text or "")


def own_text(text: str | ledgerboard.BoardItem) -> str:
    """A board item's own words (§4.5 screen 12 *Have a session do it*, TD-1624, TD-1660): a BoardItem's `words`
    (ledgerboard v3.0, TD-1881: an item file's heading holds no lead, field or reply), its ends stripped. A string
    is read as a v2 line was: its words after its `(session …) —` lead (from its start where it has none) and
    before its first field, any reply cut first — bold kept, never clipped."""
    if isinstance(text, ledgerboard.BoardItem):
        return text.words.strip()
    t = str(text or "")
    if (m := ledgerboard.ITEM_RE.match(t)) is not None:
        t = m.group("text")
    if span := ledgerboard.reply_span(t):
        t = t[: span[0]]
    if (h := ledgerboard.HEAD_RE.match(t)) is not None and (i := t.find(" — ", h.end())) >= 0:
        t = t[i + 3 :]
    if f := _MARK_END_RE.search(t):
        t = t[: f.start()]
    return t.strip()


def marked_for_person(text: str | ledgerboard.BoardItem) -> bool:
    """Whether a board item is marked for the person (§4.5 screen 12 *Have a session do it*, TD-1624): its own
    words (`own_text`), its spaces collapsed, its case folded and a trailing `.` or `!` dropped, end with *only
    you can do this*. `text` is the item (TD-1881), or a v2 item's text or whole `- [ ]` line."""
    words = " ".join(own_text(text).split()).casefold().rstrip(".!").rstrip()
    return words.endswith(ONLY_YOU)


def _answers(item: str | ledgerboard.BoardItem) -> list[str]:
    return list(item.answers) if isinstance(item, ledgerboard.BoardItem) else ledgerboard.parse_answers(item)


def _kind(item: str | ledgerboard.BoardItem) -> str | None:
    if isinstance(item, ledgerboard.BoardItem):
        return item.kind.lower() if item.kind else None
    km = ledgerboard.KIND_RE.match(item)
    return km.group("kind").lower() if km else None


def session_do(text: str | ledgerboard.BoardItem, answer: str) -> bool:
    """Whether a decide of `answer` on the item `text` is **Have a session do it**'s (TD-1624): the fixed text, and
    not one of the item's own `Answers:` (an answer the item offers is decided as any other)."""
    said = " ".join(str(answer or "").split())
    own = {" ".join(a.split()) for a in _answers(text)}
    return said == HAVE_A_SESSION and said not in own


class Refused(Exception):
    """The edit was not made, and why, in words a person reads on the Inbox."""


def reply_tail(reply: str, by: str, today: str) -> str:
    """The words **Reply** appends to an item (design §4.4, TD-142), as a v2 line wrote them: ` — <by>, <date>:
    <reply>`; ledgerboard v3.0 writes them as a Log line of the item's file (TD-1881), so this is now the check
    and the words an add's answer is read by. A reply typed over several lines is joined with spaces. Refused
    for a reply that is empty."""
    words = " ".join(str(reply or "").split())
    if not words:
        raise Refused("a reply needs its text: what the next session should do")
    return f" — {by}, {today}: {words}"


def _day(today: str) -> date:
    return date.fromisoformat(today) if today else date.today()


def edit_item(
    item: ledgerboard.BoardItem,
    action: str,
    due: str | None = None,
    *,
    reply: str = "",
    by: str = "",
    today: str = "",
    answer: str = "",
    why: str = "",
) -> str:
    """The item file of `item` with the item done (`Closed: <today>`, or `Closed: <today> — <why>` with `why`, a
    Done's alone), snoozed to `due` (`Hide until:`), its `Due:` moved (`due`), replied to (`reply`, by `by` on
    `today`, a Log line) or decided (`answer`, on `today`) — ledgerboard v3.0's `edit_item`, which re-reads every
    edit and refuses one the reader would not read back (TD-1881; v2's `edit_line` of one line). Refused, in front
    of the call, for an item that is closed (§4.4 *Board write-back*), a decide on an item already decided (§4.4
    *Decide*), which ledgerboard would rewrite, and a decide its kind refuses (`_session_check`)."""
    if action not in ACTIONS:
        raise Refused(f"unknown board action {action!r}: {' or '.join(ACTIONS)}")
    if item.closed is not None:
        raise Refused(MOVED)
    if not item.path:
        raise Refused("a v2 board's item: ledgerboard v3.0 writes item files alone — split the board first")
    if action == "reply" and not " ".join(str(reply or "").split()):
        raise Refused("a reply needs its text: what the next session should do")
    if why and action != "done":
        raise Refused(WHY_ON_DONE)
    if action == "decide":
        if not " ".join(str(answer or "").split()):
            raise Refused("a decide needs its answer: one of the item's Answers:")
        if item.decided is not None:
            raise Refused("this item is already decided: Reply says more to its session, Done closes it")
        _session_check(item, answer)
    to = None
    if action in ("snooze", "due"):
        try:
            to = date.fromisoformat(str(due))
        except ValueError:
            raise Refused(f"a {action} needs a date as YYYY-MM-DD, not {due!r}") from None
    try:
        return ledgerboard.edit_item(
            item.raw, action, to=to, answer=answer or None, reply=reply or None, by=by or None,
            today=_day(today), why=why or None,
        )  # fmt: skip
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


def live_look_pair(kind: str, answers: Any) -> bool:
    """Whether `answers` are cadence's fixed pair for a live look (§3.5, design §4.5a **Works** / **Not right…**) on
    a line of `kind`: a kind in `LOOK_KINDS`, and exactly *Works* and the form *Not right: <what>*. A third answer,
    another kind, another form or a complete *Not right: wrong repo* is not the pair."""
    said = [" ".join(str(a).split()) for a in answers or ()]
    return (
        str(kind or "").lower() in LOOK_KINDS
        and len(said) == 2
        and said[0] == WORKS
        and ledgerboard.is_not_right_form(said[1])
    )


def reply_decides(kind: str, answers: Any, decided: bool) -> bool:
    """Whether a Reply on a line can decide it (§4.4 *A Reply that fills a form decides*, TD-1698): undecided, a
    `decide` or `look` line, or a `watch` carrying the look's pair, whose answers offer a form. `reply_fills` reads a
    found line by it, and the page's reader hands it as `reply_decides`, which the reply box's foot is drawn on."""
    said = [str(a) for a in answers or ()]
    k = str(kind or "").lower()
    return (
        not decided
        and any(ledgerboard.is_form(a) for a in said)
        and (k in ("decide", "look") or (k == "watch" and live_look_pair(k, said)))
    )


def reply_fills(text: str | ledgerboard.BoardItem, reply: str) -> str | None:
    """The answer a Reply's words write as the item's decide (§4.4 *A Reply that fills a form decides*, TD-1698), or
    None where they stay a Reply: on an open, undecided `decide` or `look` item, or a `watch` carrying the look's
    pair, whose `Answers:` offer a form, words that begin with one of its forms' heads and a colon (any case) are that
    form's press, filled through ledgerboard (`<head>: <words>`, one line). An empty fill — the head alone, or the
    head with a placeholder — is refused with *<head> needs its words*. Read from the found item itself (a
    BoardItem, TD-1881; a v2 line's text is still read), never from anything the page sent."""
    answers = _answers(text)
    decided = (
        text.decided is not None
        if isinstance(text, ledgerboard.BoardItem)
        else ledgerboard.parse_decided(text) is not None
    )
    if not reply_decides(_kind(text) or "", answers, decided):
        return None
    try:
        return ledgerboard.fill_form(" ".join(str(reply or "").split()), answers)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


def _session_check(text: str | ledgerboard.BoardItem, answer: str) -> None:
    """The kind check of a decide (§4.4 *Decide*, TD-1624), read from the found item whatever the page sent: an
    answer that is not one of the item's own `Answers:` is refused on an `act` item unless it is *have a session do
    it* on one with no `Answers:` that is not marked for the person; the fixed text on any other item is refused."""
    said = " ".join(str(answer or "").split())
    own = _answers(text)
    if said in {" ".join(a.split()) for a in own}:
        return
    try:
        if own and ledgerboard.fill_form(said, own):
            return  # a form among them, filled, is one of the item's own answers too (TD-1698)
    except ledgerboard.Refused:
        pass
    kind = _kind(text)
    if said == HAVE_A_SESSION:
        if kind != "act" or own:
            raise Refused(NOT_ACTS_ANSWER)
        if marked_for_person(text):
            raise Refused(MARKED)
    elif kind == "act":
        raise Refused(WORD_FOR_WORD)


def message(text: str, action: str, due: str | None = None, *, id: str, answer: str = "", session: str = "") -> str:
    """The fixed commit message (design §4.4, cadence §4's carve-out): ledgerboard v3.0's
    `subject("shiftlead", …)` — the action, the item's `id` (TD-1881), its words' head and the session (`session`:
    the press's, else the item's own `Session`, else *n/a*), what a reviewer greps for; `append` for an add.
    `text` is the item's words."""
    said = " ".join(str(answer or "").split())
    if len(said) > ANSWER_MAX:  # a *Not right:* carries a sentence; the subject is also the PR's title
        said = said[: ANSWER_MAX - 1].rstrip() + "…"
    try:
        got = ledgerboard.subject(TOOL, action, text, id=id, to=due, answer=said, session=session or None)
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


def answerer(root: Path, board: ledgerboard.Board) -> str | None:
    """Who a decide's answer is from (ledgerboard v2.3's `who_answered`): None on a board whose `People:`
    names one person, who is then the answerer; else the checkout's git `user.name` as a person's name
    (spaces joined by `-`) — on a `People:` of several names, that name or its first word as listed — or
    `person`. ledgerboard refuses a name its `People:` does not list, in its own words. `board` is the
    `Board` `load_board()` gives (ledgerboard v3.0, TD-1881: its `README.md` holds `People:`)."""
    people = ledgerboard.board_people(board)
    if people is not None and len(people) == 1:
        return None
    words = author(root).split()
    name = "-".join(words)
    # on a People: line of several names, the user's name as listed (whole, or its first word), if it is there
    for want in (name, words[0] if words else ""):
        got = next((p for p in people or () if want and p.lower() == want.lower()), None)
        if got:
            return got
    return name if ledgerboard.is_person(name) else "person"


def _plan(fn: Any, *args: Any, **kw: Any) -> lb_board.Plan:
    try:
        return fn(*args, **kw)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


def _apply(plan: lb_board.Plan) -> None:
    try:
        lb_board.apply(plan)
    except OSError as e:
        raise Refused(f"the board could not be written, and is as it was: {e}") from None


# -- origin's head (design §4.4 *The edit is made on origin's head, and landed there*, TD-264) ----

BOUND = 40.0  # seconds from the fetch to the merge (§4.4)
REREAD_FAILED = "the press landed, and origin could not be re-read"  # §4.4 *Every write the home lands is read at once*
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
    cp = _fetch(root, root, want, clock.left("git fetch"))
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


def _fetch(root: Path, at: Path, want: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """`git fetch` of origin's `want` in `at` (the checkout `root` or its tree, one repository's refs), with the
    explicit refspec so `origin/<want>` moves even where `remote.origin.fetch` is narrowed, under the home's one
    fetch lock of `root` (`workorders.fetch_lock`, §4.4 *The ledger is read against origin*, TD-1471)."""
    with workorders.fetch_lock(root):
        return _git(at, "fetch", "-q", "origin", workorders.refspec(want), timeout=timeout)


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


def board_files(rel: Path | str) -> list[str]:
    """The paths a v3 board is under `rel` (the stub or the directory, ledgerboard v3.0, TD-1881), POSIX: the
    directory — its `README.md`, every open item file and `archive/<YYYY-MM>/` — and the stub beside it, what a
    write's commit stages whole (`git add -A`: a closing `done` moves an item's file into the archive)."""
    r = Path(rel).as_posix().rstrip("/")
    if r.endswith(".md"):
        return [r[:-3], r]
    return [r]


def _board(at: Path, rel: Path | str) -> ledgerboard.Board:
    """The board at `rel` under `at` (a checkout or the host agent's tree) as `load_board()` reads it (ledgerboard
    v3.0, TD-1881): through the stub into its directory, or a v2 file read-only."""
    return ledgerboard.load_board(Path(rel).as_posix(), *ledger_mod.fs_io(at))


def _text_ref(text: str) -> str:
    """The `board:<8 hex>` a v2 item's `text` keeps once split (ledgerboard v3.0's `key_id` of its `item_key`,
    TD-1881), or "" for none: a press sent with a v2 line's text still finds the item it was."""
    t = str(text or "").strip()
    if not t:
        return ""
    try:
        return workorders.PREFIX + ledgerboard.key_id(ledgerboard.item_key(f"- [ ] {t}"))
    except Exception:  # noqa: BLE001 — a text the key cannot take names no item
        return ""


def _by_ref(items: list[ledgerboard.BoardItem], ref: str) -> list[ledgerboard.BoardItem]:
    nonce = str(ref or "").removeprefix(workorders.PREFIX)
    return [it for it in items if nonce and it.id and it.id.endswith("-" + nonce)]


def _find(board: ledgerboard.Board, key: str = "", text: str = "") -> ledgerboard.BoardItem | None:
    """The open item the press is about (§4.4 *A board line's id*, TD-1881): with a `key` (`board:<8 hex>`), the
    open item whose id ends with its eight hex digits — of two, the one whose words are `text`, word for word —;
    else (or when no open item has it) the open item whose words are `text`, or whose v2 reference `text`
    derives (`_text_ref`). None when no open item is it."""
    want = " ".join(str(text or "").split())
    if key:
        got = _by_ref(board.items, key)
        same = [it for it in got if want and " ".join(it.words.split()) == want]
        if same or got:
            return (same or got)[0]
    if not want:
        return None
    same = [it for it in board.items if " ".join(it.words.split()) == want]
    if same:
        return same[0]
    derived = _by_ref(board.items, _text_ref(text))
    return derived[0] if derived else None


def _closed(board: ledgerboard.Board, key: str = "", text: str = "") -> ledgerboard.BoardItem | None:
    """The closed item `key` (else `text`'s v2 reference) names, when no open one does (contract 2, TD-1881)."""
    got = _by_ref(board.closed, key) or _by_ref(board.closed, _text_ref(text))
    return got[0] if got else None


def _none_open(board: ledgerboard.Board, key: str, text: str = "") -> Refused:
    """The refusal for a press whose item no open item of `board` is: closed, said so with its date; else the
    reader's *no line* for a `key`, the moved-item words for a text."""
    shut = _closed(board, key, text)
    if shut is not None:
        day = shut.closed[0].isoformat() if shut.closed and shut.closed[0] else "already"
        return Refused(f"{item_ref(shut)} was closed {day}: {MOVED}")
    return Refused(workorders.NO_LINE.format(ref=key) if key else MOVED)


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
    also: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Commit the tree's board — its directory and stub whole (`board_files`, `git add -A`: an item file added,
    edited or moved into the archive, ledgerboard v3.0, TD-1881) — or the file at `rel` (a rank file, §4.4 *A move
    lands*), and the files `also` names beside it (a decide lift's ledger entries, TD-1375), and land them on
    `origin/<want>` by the one road the forge's rule allows (§4.4): a branch of the host agent's own, a PR
    it opens and squash-merges at once. A refused merge closes the PR and deletes the branch, and refuses
    the press as a moved line when `still()` — origin's board read again — no longer holds the item, else
    as unreachable."""
    base = _git(t, "rev-parse", "HEAD").stdout.strip()
    paths = [rel] if rel else [p for p in board_files(workorders.board_rel(root)) if (t / p).exists()]
    paths += [p for p in also if p not in paths]
    cp = _git(t, "add", "-A", "--", *paths, timeout=clock.left("git add"))
    if cp.returncode == 0:
        cp = _git(
            t,
            *_identity(root),
            "commit",
            "--quiet",
            "-m",
            msg,
            "--",
            *paths,
            timeout=clock.left("git commit"),
        )
    if cp.returncode != 0:
        _reset(t, want)
        raise Refused(f"the commit failed, and the board is as it was: {_why(cp, 'git commit')}")
    sha = _git(t, "rev-parse", "HEAD").stdout.strip()
    branch = f"{prefix}/{Path(root).name}/{datetime.now(UTC):%Y%m%d%H%M%S}-{sha[:7]}"
    pushed = False
    try:
        cp = _git(t, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", timeout=clock.left("git push"), c_locale=True)
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
                if not landed and _fetch(root, t, want, GIT_TIMEOUT).returncode == 0:
                    landed = _git(t, "diff", "--quiet", sha, f"origin/{want}", "--", *paths).returncode == 0
                    moved = not landed and not still()
                    # the forge's own word that it did not merge, and origin's board changed under it: never a
                    # retry on a forge that could not be asked (an add might write twice) or a move elsewhere
                    shifted = (
                        state in ("OPEN", "CLOSED")
                        and _git(t, "diff", "--quiet", base, f"origin/{want}", "--", *paths).returncode != 0
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
    # the merge brought in (§4.4 *Every write the home lands is read at once*, TD-1471): checked, and `commit`
    # reported only from a fetch that moved the ref; one that failed is the re-read failing
    try:
        cp = _fetch(root, t, want, GIT_TIMEOUT)
        why = "" if cp.returncode == 0 else _why(cp, "git fetch")
    except Refused as e:
        why = str(e)
    head = _git(t, "rev-parse", f"origin/{want}").stdout.strip()
    _reset(t, want)
    if why or not head or head == base:
        why = why or f"origin/{want} did not move"
        return {"commit": "", "message": msg, "pr": n, "reread_error": f"{REREAD_FAILED} ({why})"}
    return {"commit": _git(t, "rev-parse", "--short", head).stdout.strip(), "message": msg, "pr": n}


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
    why: str = "",
    on_decide: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Make one Snooze, Done, Reply or Decide on the board on origin's head and land it there (§4.4):
    in the host agent's own tree for the repo of the checkout `root`, which is never written.
    The item is named by `key`, its reference (`board:<8 hex>`, §4.4 *A board line's id*): the open item whose
    id ends with it (ledgerboard v3.0, TD-1881), else by `text` — the item's words, or a v2 line's text, whose
    reference the split item keeps — and refused in its own words when no open item is it (a closed one is said
    so). `line` is kept for its callers and read no more: a v3 board has no line numbers.
    Returns `{commit, message, pr, id, key, text, due}` — `commit` origin's head after the merge, `id` the item's,
    `key` its reference, `text` its words, `due` the date written; raises `Refused` with nothing changed on
    origin. A `snooze` sent with no date is the Inbox fold's *now* (§4.4 *Board write-back*, TD-1349): the host
    agent's own today, computed once here, is its `Hide until:` — the calendar its reader decides `hidden` by —
    and its commit subject's date. An item that already said so is answered as done with origin's head, no commit
    and no `pr`.
    A `reply` whose words fill a form on the found item (`reply_fills`, §4.4 *A Reply that fills a form decides*,
    TD-1698) is that form's decide, read here under the lock after the fetch: written and landed as a decide, by the
    person as its answerer, and answered with `decided`; `on_decide` is called with the filled answer when the
    reading so turns it (idempotent: a second reading calls it again)."""
    root = Path(root)
    if action not in ACTIONS:
        raise Refused(f"unknown board action {action!r}: {' or '.join(ACTIONS)}")
    if why and action != "done":
        raise Refused(WHY_ON_DONE)
    if action == "snooze" and not due:
        due = _day("").isoformat()
    with _EDIT:
        clock = _Clock()
        return _twice(lambda: _write_back(root, text, action, due, reply, answer, clock, key, why, on_decide))


def _write_back(
    root: Path,
    text: str,
    action: str,
    due: str | None,
    reply: str = "",
    answer: str = "",
    clock: _Clock | None = None,
    key: str = "",
    why: str = "",
    on_decide: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if key and not workorders.is_work_order(key):
        raise Refused(f"{key!r} is not a board line's id: board: and eight hex digits (design §4.4)")
    if not key and not str(text or "").strip():
        raise Refused(MOVED)
    clock = clock or _Clock()
    if shutil.which("gh") is None:
        raise unreachable("gh is not installed")
    t, want = _tree(root, clock)
    rel = workorders.board_rel(root)
    stub = t / rel
    old = _board(t, rel)
    if old.form == "file":  # the writer refuses a v2 board, in its own words (*split first*, TD-1881)
        _plan(lb_board.load_v3, str(stub))
    it = _find(old, key, text)
    if it is None:
        if (key or text) and _ahead(root, want, key, text):
            raise Refused(NOT_ON_ORIGIN)
        raise _none_open(old, key, text)
    # found by its id, the item's own words are its words now — a snooze or a reply since the page drew it
    # changes the file and never the id (§4.4 *A board line's id*)
    text = it.words
    decided = None
    if action == "reply" and (decided := reply_fills(it, reply)):
        # the Reply fills a form: it is that form's decide, in this same write (§4.4 *A Reply that fills a form
        # decides*, TD-1698) — the person its answerer, the lift and the decide's subject, no reply trail
        action, answer, reply = "decide", decided, ""
        if on_decide is not None:
            on_decide(decided)
    by = author(root) if action == "reply" else ""
    reply = " ".join(str(reply or "").split())  # a reply typed over several lines is one Log line (§4.4, TD-142)
    # ShiftLead's own checks first (a closed item, a decide on a decided item, its kind), then ledgerboard's
    edit_item(it, action, due, reply=reply, by=by, answer=answer, why=why)
    lifts = None
    only = False
    if action == "decide":
        by = answerer(root, old) or ""
        lifts = _lift_ledger(t, it)
        # Have a session do it writes the board half alone, never the decide lift, whatever the Context names, so
        # the item stays open (§4.4 *Decide*, TD-1624): the ledger passed with `board_only` where a gate would lift
        only = session_do(it, answer) and lifts is not None
    plan = _plan(
        lb_board.plan_edit, str(stub), action, it.id,
        to=due if action in ("snooze", "due") else None, answer=answer or None, text=reply or None,
        by=by or None, tool=TOOL, ledger=lifts, board_only=only, why=why or None,
    )  # fmt: skip
    msg = message(text, action, due, id=it.id or "", answer=answer, session=it.session or "")
    found = {"id": it.id, "key": item_ref(it), "text": text, "due": due}
    if plan.info.get("left_open"):
        # ledgerboard v2.7: a board-only decide whose lifting answer leaves a listed entry still carrying the gate
        # writes nothing, and says which (its TD-067 *Consumers*): nothing is landed, and the press is answered
        # with what it left open, never as a plain done (TD-1709)
        head = _git(t, "rev-parse", "--short", f"origin/{want}").stdout.strip()
        _reset(t, want)
        gate = ledgerboard._item_gate(it)[1]
        return {"commit": head, "message": msg, **found, "left_open": list(plan.info["left_open"]), "gate": gate,
                **({"decided": decided} if decided else {})}  # fmt: skip
    if all(v is not None and _same(Path(p), v) for p, v in plan.changes.items()):
        # the edit changed nothing — a *now* whose date the item already holds (the day turned under an open
        # page, so it was no longer hidden): nothing is landed, and the press is answered as done (TD-1349)
        head = _git(t, "rev-parse", "--short", f"origin/{want}").stdout.strip()
        _reset(t, want)
        return {"commit": head, "message": msg, **found, **({"decided": decided} if decided else {})}
    _apply(plan)
    under = [(t / p).resolve() for p in board_files(rel)]
    also = sorted(
        os.path.relpath(p, t)
        for p in plan.changes
        if not any(Path(p).resolve() == u or Path(p).resolve().is_relative_to(u) for u in under)
    )
    open_file = f"{board_files(rel)[0]}/{it.path}"

    def still() -> bool:
        # origin's board still holds the item open: its file is where the press found it (TD-1881)
        return _git(t, "cat-file", "-e", f"origin/{want}:{open_file}").returncode == 0

    landed = _land(root, t, want, msg, clock, still, also=also)
    return {
        **landed, **found,
        **({"entries": plan.info["entries"]} if also else {}), **({"decided": decided} if decided else {}),
    }  # fmt: skip


def _same(path: Path, text: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == text
    except OSError:
        return False


def find_line(root: str | Path, line: int | None, key: str) -> dict[str, Any]:
    """**`board_find`** (§4.5 screen 12 *Three verbs: Have a session do it*, TD-1660): the open item whose
    reference is `key` (`board:<8 hex>`, §4.4 *A board line's id*: its id ends with them, ledgerboard v3.0,
    TD-1881), found on origin's head as the write-back finds it, under the board's write lock held for the find
    alone, and read with ledgerboard's `load_board`. Refused unless it is open, undecided, of kind `act`, without
    `Answers:`, not marked for the person, and names a `Doer:`; whatever the page sent. `line` is kept for its
    callers and read no more. Returns `{doer, text, context, session, due, context_refs, refs, key, id}`: `doer`
    the field's value as written, `text` the item's words (`own_text`), `context` the detail block's Context bullet
    without its label ("" where none), `session` the item's session (None where it names none), `due` its `Due:`,
    `context_refs` every ref of its `Context:` as written, `refs` its entry refs (`TD-n`, `<repo>#TD-n`), the
    item's reference as `key` and its id as `id`."""
    root = Path(root)
    if not workorders.is_work_order(str(key or "")):
        raise Refused(f"{key!r} is not a board line's id: board: and eight hex digits (design §4.4)")
    with _EDIT:
        clock = _Clock()
        t, _ = _tree(root, clock)
        b = _board(t, workorders.board_rel(root))
        item = _find(b, key)
    if item is None:
        raise _none_open(b, key)
    if item.decided is not None:
        raise Refused("this item is already decided: Reply says more to its session, Done closes it")
    if item.kind != "act":
        raise Refused(NOT_ACTS_ANSWER)
    if item.answers:
        raise Refused(NOT_ACTS_ANSWER)
    if marked_for_person(item):
        raise Refused(MARKED)
    if item.doer is None:
        raise Refused(NO_DOER)
    context = ""
    for i, ln in enumerate(item.detail):
        m = re.match(r"^-\s+\*\*Context:\*\*\s*", ln)
        if m is None:
            continue
        words = [ln[m.end() :].strip()]
        for more in item.detail[i + 1 :]:
            if not more.startswith(" "):
                break
            words.append(more.strip().removeprefix("- ").strip())
        context = " ".join(w for w in words if w)
        break
    every = ledgerboard.context_refs(item.context or "")
    return {
        "doer": item.doer[2],
        "text": own_text(item),
        "context": context,
        "session": item.session,
        "due": item.due.isoformat() if item.due else None,
        "context_refs": every,
        "refs": [r for r in every if not r.startswith(("PR #", "branch "))],
        "key": item_ref(item),
        "id": item.id,
    }


def _lift_ledger(t: Path, item: ledgerboard.BoardItem) -> str | None:
    """The ledger a decide on `item` writes beside its board item (§4.4 *Board write-back*, TD-1375):
    the tree's ledger, where the item's Context names one of this repo's entries and one gate — ledgerboard
    v2.4's decide lift, which lifts the gate on a lifting answer, or logs *kept waiting*, in the same write as
    the board item — else None, a decide on the board alone. A v1 ledger is passed as it is, and ledgerboard
    refuses the lift there in its own words."""
    ref, gate = ledgerboard._item_gate(item)
    if ref is None or gate is None or "#" in ref:
        return None
    return str(t / ledger_mod.ledger_path(t))


def _ahead(root: Path, want: str, key: str, text: str) -> bool:
    """Whether the checkout holds the item where origin does not because the checkout's board is
    *ahead* — an uncommitted edit, or a board commit origin lacks — rather than behind: a checkout
    that has not pulled still shows an item origin has since done or replied to, which is a moved
    item, not an unpushed one. Read through `load_board()` (TD-1881); the board's every file is looked at."""
    rel = workorders.board_rel(root)
    if _find(_board(root, rel), key, text) is None:
        return False
    files = [p for p in board_files(rel) if (root / p).exists()]
    if not files:
        return False
    if _git(root, "status", "--porcelain", "--", *files).stdout.strip():
        return True
    last = _git(root, "log", "-1", "--format=%H", "--", *files).stdout.strip()
    return bool(last) and _git(root, "merge-base", "--is-ancestor", last, f"origin/{want}").returncode != 0


def item_file(text: str, due: str, today: str, session: str | None, host: str | None, context: str | None) -> str:
    """The item file *Put on the board* writes (design §4.5a): ledgerboard v3.0's `item_file` (TD-1881; v2's
    `item_line`) — `## <text>`, then `Added: <today>`, its `Session` (`<name> on <host>`) where there is one, its
    `Context` and its `Due`. Refused for text that is empty or more than one line."""
    try:
        return ledgerboard.item_file(text, due or None, today, session, host, context)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


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
    """**Put on the board** (design §4.4, the write-back's first add; TD-140): one new item file (ledgerboard
    v3.0's `plan_add`, its id drawn, TD-1881) on the board on origin's head for the checkout `root`'s repo,
    committed in the host agent's own tree as ledgerboard's `shiftlead: append <id> <head> (session <name>)` and
    landed by its own PR, as an edit is; the checkout is never written. Refused on the same conditions as an
    edit, touching nothing on origin; a v2 board is refused by the writer, in its words (*split first*). Returns
    `{commit, message, pr, id, key}` — the new item's id and its reference.

    With `answer`, the **second add** (§4.4, §4.10 *A question about a reference outlives its asker*,
    TD-216): `text` is the orphaned question's first paragraph and the person's answer is the item's first
    Log line (`- <date>: <name>: <answer>`), committed by the same `append`."""
    root = Path(root)
    today = today or date.today().isoformat()
    by = None
    if answer is not None:
        reply_tail(answer, "x", today)  # an empty answer is refused in our words, before the tree is touched
        by = author(root)
    # the file first, so words the board refuses refuse the press before origin is fetched
    item_file(text, due, today, session, host, context)
    return _insert(
        root,
        lambda stub: _plan(
            lb_board.plan_add,
            str(stub),
            text,
            due=due or None,
            context=context,
            session=session,
            host=host,
            said=answer,
            by=by,
            today=today,
            tool=TOOL,
        ),  # fmt: skip
        # the subject is the item's words without the answer: a person's words stay on the board
        lambda p: message(text, "append", id=p.info["id"], session=session or ""),
    )


def decided_file(title: str, ref: str, answers: list[str], default: int | None, words: str, today: str) -> str:
    """The item file the person's answer to a ledger entry writes (design §4.5 screen 6 *The ledger's
    entries that wait on you*, TD-565): ledgerboard v3.0's `decided_file` (TD-1881; v2's `decided_line`), a
    decided `decide` item, its `Context` the ref, `Due` today, its `Answers:` the entry's with `(default)` on the
    one marked and `Decided: <today> — <words>` — so it is a work order at once (§4.4, §6 rule 6). Refused for
    empty words, a value of more than one line, or a file the board's reader would not read back."""
    try:
        return ledgerboard.decided_file(title, ref, answers, default, words, today)
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None


def add_decided(
    root: str | Path,
    title: str,
    ref: str,
    answers: list[str],
    default: int | None,
    words: str,
    today: str,
    session: str = "",
) -> dict[str, Any]:
    """The third add (design §4.4 *Board write-back*, TD-565): the decided item `decided_file` gives for
    these fields, written by ledgerboard's `plan_add` (its `decided`, who answered as `answerer` says) on the
    board on origin's head, by the second add's road, committed by the same `append` — its session *n/a*, the
    person's, or `session`'s name for a road a person's session pressed (§4.8 *A person's session passes one of
    them*, TD-1117). Returns `{commit, message, pr, id, key}`."""
    root = Path(root)
    decided_file(title, ref, answers, default, words, today)  # refused in our words before origin
    head = " ".join(str(title or "").split()) or ref

    def plan(stub: Path) -> lb_board.Plan:
        b = ledgerboard.load_board(str(stub), lb_board.fs_ls, lb_board.fs_read)
        return _plan(
            lb_board.plan_add, str(stub), title, context=ref, answers=list(answers), default=default,
            decided=words, by=answerer(root, b), today=today, tool=TOOL,
        )  # fmt: skip

    return _insert(root, plan, lambda p: message(head, "append", id=p.info["id"], session=session))


def _insert(root: Path, plan: Any, msg: Callable[[lb_board.Plan], str]) -> dict[str, Any]:
    """An add's press: `plan(stub)` — ledgerboard's `plan_add` on the board whose stub is `stub` in the host
    agent's own tree, reset to origin's head — written there, committed under `msg(plan)` (the subject carries
    the drawn id, TD-1881) and landed by its own PR as an edit is."""
    with _EDIT:
        clock = _Clock()
        if shutil.which("gh") is None:
            raise unreachable("gh is not installed")

        def press() -> dict[str, Any]:
            t, want = _tree(root, clock)
            p = plan(t / workorders.board_rel(root))
            subject = msg(p)
            _apply(p)
            new = str(p.info["id"])
            # an add moves no item, so a refused merge is never a moved one: unreachable, or made once more
            landed = _land(root, t, want, subject, clock, lambda: True)
            return {**landed, "id": new, "key": workorders.PREFIX + new[-8:]}

        return _twice(press)


# -- Lift the hold is a lift on the press (design §4.4 *Board write-back*, TD-1829, built by TD-1831) -----------

LIFT_BODY = (
    "shiftlead's lift on the press: the person's Lift the hold lifts `decision (<p>)` on one entry (design §4.4 "
    "*Board write-back*: *Lift the hold is a lift on the press*)."
)
# the why a covering decided item is closed with (`Closed: … — lifted.`, ledgerboard's `_lifted_close`)
LIFTED = "lifted"


def only_lifts(p: str) -> str:
    return f"only {p} lifts {p}'s hold"


def _held_words(key: str, holder: dict[str, Any]) -> str:
    name = str(holder.get("name") or holder.get("id") or "a session")
    return f"{key} is being acted on by {name}: lift the hold once it lands, or tell {name}"


def _person_gate(text: str) -> str | None:
    """The `decision (<p>)` the open entry `text` carries for the home's person, as it spells it, else None."""
    ents = ledgerboard.entries(text)
    if not ents or ledgerboard.first_word(ents[0]["fields"].get("status")) in ledgerboard.ARCHIVED_WORDS:
        return None
    for g in ledgerboard.gate_items(ledgerboard.parse_gates(ents[0]["blocked_raw"])):
        m = ledgerboard.GATE_DECISION_RE.match(g)
        if m and m.group("who").strip().lower() == ledger_mod.PERSON_OWNER:
            return g
    return None


def _lists_other(it: ledgerboard.BoardItem, tid: str, gate: str, led: Any) -> bool:
    """Whether a covering item lists another entry that still carries the gate (§4.4 *The suffix*): its `Context:`
    entry (the parent, where it covers through `Part of`) or a `Parts:` id — a bare id, this repo's, never a
    `<repo>#TD-n` — open in the tree's ledger, not the pressed entry, carrying the same gate."""
    ref, _ = ledgerboard._item_gate(it)
    want = ledgerboard._num(tid)
    for x in [ref, *it.parts]:
        if not x or "#" in x:
            continue
        try:
            if ledgerboard._num(x) == want:
                continue
            path, archived = led.entry_file(lb_ledger.tid_of(x))
        except (ledgerboard.Refused, ValueError):
            continue
        if not archived and ledgerboard._carried(led.read(path), gate) is not None:
            return True
    return False


def lift_on_press(
    root: str | Path,
    id: str,
    answer: str = "go ahead",
    held: dict[str, dict[str, Any]] | None = None,
    entry_holder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """**Lift the hold** (design §4.4 *Board write-back*: *Lift the hold is a lift on the press*, TD-1829): the
    entry `id`'s `decision (<p>)` (`<p>` the home's person) lifted by ledgerboard's `plan_lift`, `answer` its Log's
    answer (*go ahead* from the press, the picked label from §4.10's lifting answer), and any covering decided
    item closed `— lifted.` beside it, in one commit of the host agent's tree on origin's head, landed by its own
    PR as every press's — subject and title `shiftlead: lift decision (<p>) on TD-n (session n/a)`. No work order
    is written. `held` maps each `board:<key>` a live session holds to its holder (`{id, name}`), and
    `entry_holder` is the pressed entry's, read in case (b) alone.

    Returns `{gone: true}` (nothing written) where the entry is archived or no longer carries the gate, else
    `{lifted: true, commit, message, pr, suffix}`; raises `Refused` in its words — *only <p> lifts <p>'s hold*,
    case (d)'s *TD-n's hold is asked on board:<key>: answer it there*, case (b)'s holder, or ledgerboard's own."""
    root = Path(root)
    try:
        tid = lb_ledger.tid_of(str(id or "").upper())
    except ledgerboard.Refused as e:
        raise Refused(str(e)) from None
    if shutil.which("gh") is None:
        raise unreachable("gh is not installed")
    with _EDIT:
        clock = _Clock()
        return _twice(lambda: _lift_on_press(root, tid, answer, dict(held or {}), entry_holder, clock))


def _lift_on_press(
    root: Path,
    tid: str,
    answer: str,
    held: dict[str, dict[str, Any]],
    entry_holder: dict[str, Any] | None,
    clock: _Clock,
) -> dict[str, Any]:
    t, want = _tree(root, clock)
    try:
        led = lb_ledger.Ledger.open(str(t / ledger_mod.ledger_path(t)))
    except ledgerboard.Refused as e:
        _reset(t, want)
        raise Refused(str(e)) from None

    def gone() -> dict[str, Any]:
        _reset(t, want)
        return {"gone": True}

    try:
        path, archived = led.entry_file(tid)
    except ledgerboard.Refused:
        return gone()
    text = led.read(path) or ""
    gate = None if archived else _person_gate(text)
    if gate is None:
        return gone()
    p = ledgerboard.GATE_DECISION_RE.match(gate).group("who").strip()
    rel = workorders.board_rel(root)
    stub = t / rel
    b = _board(t, rel)
    try:
        by = lb_board.who_answered(b, answerer(root, b))
    except ledgerboard.Refused as e:
        _reset(t, want)
        raise Refused(str(e)) from None
    if by.lower() != p.lower():
        _reset(t, want)
        raise Refused(only_lifts(p))
    url = _git(root, "remote", "get-url", "origin").stdout.strip()
    repo = ledgerboard.origin_path(url) or root.name
    try:
        cov = [
            (it, state) for _, it, state in ledgerboard.covers(text, gate, [(url, root.name, b)], repo)
            if state in ("open", "decided")
        ]  # fmt: skip
    except ledgerboard.Refused as e:
        _reset(t, want)
        raise Refused(str(e)) from None
    shared = [it for it, _ in cov if _lists_other(it, tid, gate, led)]
    alone = [(it, s) for it, s in cov if not any(it is x for x in shared)]
    asked = [it for it, s in alone if s == "open"]
    if asked:  # (d)
        _reset(t, want)
        raise Refused(f"{tid}'s hold is asked on {item_ref(asked[0])}: answer it there")
    closes = [it for it, s in alone if s == "decided"]
    suffix = None
    if closes:  # (b)
        for it in closes:
            if (h := held.get(item_ref(it))) is not None:
                _reset(t, want)
                raise Refused(_held_words(item_ref(it), h))
        if entry_holder is not None:
            _reset(t, want)
            raise Refused(_held_words(item_ref(closes[0]), entry_holder))
    elif shared:  # (c)
        suffix = "shared board item left open"
    else:  # (a)
        suffix = "no board item"
    plan = _plan(lb_ledger.plan_lift, led, tid, gate, by, answer=answer, suffix=suffix)
    try:
        lb_ledger.apply(plan)
    except OSError as e:
        _reset(t, want)
        raise Refused(f"the ledger could not be written, and is as it was: {e}") from None
    try:
        for it in closes:
            _apply(_plan(lb_board.plan_edit, str(stub), "done", it.id, why=LIFTED, tool=TOOL))
    except Refused:
        _reset(t, want)  # the ledger's half is written already: the tree goes back whole
        raise
    msg = f"{TOOL}: lift decision ({p}) on {tid} (session n/a)"
    entry_rel = os.path.relpath(path, t)

    def still() -> bool:
        # origin's ledger still holds the entry open where the press found it
        return _git(t, "cat-file", "-e", f"origin/{want}:{entry_rel}").returncode == 0

    landed = _land(root, t, want, msg, clock, still, body=LIFT_BODY, also=[entry_rel])
    return {**landed, "lifted": True, "suffix": suffix or "", "closed": [item_ref(it) for it in closes]}


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
    """`ao board edit done|snooze` (design §4.7, TD-587): a session's own edit of one item of the board
    **on the branch it is on**, in the tree `cwd` is in — ledgerboard's `plan_edit` (`done` with `why`,
    `snooze` to `until`), committed on that branch with ledgerboard's `subject("shiftlead", …)`,
    touching nothing else, never pushed. The item is the open one whose reference is `key` (`board:<8 hex>`, or
    its whole id, §4.4 *A board line's id*); ledgerboard v3.0 names an item by its id alone, so `line` and
    `expect` are refused by name (TD-1881). Refused on origin's default branch or a detached head (a session's
    board edit is a PR, never a commit to main), with a staged change or an uncommitted edit of the board's files
    (the commit would carry it), on a v2 board (the writer's *split first*), and for `decide` and `reply`, the
    person's words (cadence §3.5). The commit stages the board's directory and stub whole (`board_files`): a
    `done` moves the item's file into `archive/<YYYY-MM>/`. Returns `{board, line, id, action, key, text, commit,
    message, branch}` — `line` None, `text` the item's words; needs no host agent."""
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
    if line is not None or str(expect or "").strip():
        raise Refused(
            "a board item is named by its id since ledgerboard v3.0, not by --line and --expect: "
            "--key board:<8 hex>, as `ao board show` prints it"
        )
    key = str(key or "").strip()
    if not key:
        raise Refused("name the item: --key board:<8 hex>")
    if ledgerboard.is_item_id(key):
        key = workorders.PREFIX + key[-8:]
    if not workorders.is_work_order(key):
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
        raise Refused("the index has staged changes: the board edit commits the board alone — commit or unstage them")
    rel_path = path.relative_to(root.resolve())
    files = [p for p in board_files(rel_path) if (root / p).exists()]
    if files and _git(root, "status", "--porcelain", "--", *files).stdout.strip():
        raise Refused(f"{rel_path} has uncommitted changes: the commit would carry them")
    b = _plan(lb_board.load_v3, str(path))  # a v2 board is refused here, in the writer's words (TD-1881)
    it = _find(b, key)
    if it is None:
        raise _none_open(b, key)
    plan = _plan(
        lb_board.plan_edit, str(path), action, it.id, to=to.isoformat() if to else None, why=why or None,
        today=_day(today), tool=TOOL,
    )  # fmt: skip
    msg = message(it.words, action, to.isoformat() if to else None, id=it.id or "", session=it.session or "")
    olds = {p: (Path(p).read_bytes() if Path(p).exists() else None) for p in plan.changes}
    _apply(plan)
    files = [p for p in board_files(rel_path) if (root / p).exists()]
    cp = _git(root, "add", "-A", "--", *files)
    if cp.returncode == 0:
        cp = _git(root, "commit", "-q", "-m", msg, "--", *files)
    if cp.returncode != 0:
        _git(root, "reset", "-q", "--", *files)
        for p, old in olds.items():
            if old is None:
                Path(p).unlink(missing_ok=True)
            else:
                Path(p).parent.mkdir(parents=True, exist_ok=True)
                Path(p).write_bytes(old)
        raise Refused(f"{_why(cp, 'git commit failed')} — the board is restored")
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return {
        "board": str(path),
        "line": None,
        "id": it.id,
        "action": action,
        "key": item_ref(it),
        "text": it.words,
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
