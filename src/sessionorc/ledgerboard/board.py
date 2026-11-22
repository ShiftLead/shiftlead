# ledgerboard v3.5 sha256:44953e3dc48bef1de7186970bfb46aab7bb1daf182742cda5a9447719904680a
# SYNCED FILE — canonical copy: ShiftLead/ledgerboard ledgerboard/board.py (vendored by agent-cadence as files/scripts/ledgerboard/board.py)
# Edit it there and release; an edit made in a consumer's copy is overwritten by the next vendor or sync.
"""The board and rank writer: the module's board edits, read from and written to files (SPEC *The board writer*).

    python3 -m ledgerboard.board list    --board PATH [--today D]
    python3 -m ledgerboard.board show    --board PATH [--today D] [--hidden]
    python3 -m ledgerboard.board add     --board PATH --text T [--id ID] [--due D] [--context C] [--kind K]
                                         [--answer A]... [--default N] [--lift A]... [--detail JSON]
                                         [--session S [--host H]] [--said WORDS --by NAME]
                                         [--decided WORDS [--by NAME]]
                                         [--parts TD-a,TD-b]... [--ledger DIR]   (a decide's snapshot)
                                         [--doer REPO | --doer "team NAME"]       (an act's doer)
                                         [--scope NAME]                           (a decide's scope, v3.4)
    python3 -m ledgerboard.board snooze  --board PATH --id ID --to D   (hide until D)
    python3 -m ledgerboard.board due     --board PATH --id ID --to D   (move Due: to D)
    python3 -m ledgerboard.board done    --board PATH --id ID [--why TEXT]
    python3 -m ledgerboard.board decide  --board PATH --id ID --answer TEXT [--by NAME] [--ledger DIR | --board-only]
                                         [--delegate NAME]   (a delegated answer for --by, v3.4)
    python3 -m ledgerboard.board reply   --board PATH --id ID --text TEXT --by NAME
    python3 -m ledgerboard.board fmt     --board PATH
    python3 -m ledgerboard.board split   --board PATH.md [--archive PATH]   (a v2 board into its directory)
    python3 -m ledgerboard.board rank    --rank PATH --action rank|join|prune [--set TD-n=KEY]... [--drop TD-n]...
    python3 -m ledgerboard.board rank    --rank PATH --action respace --ledger PATH [--fixed KEY]... [--repo NAME]
        [--tool NAME] [--session NAME] [--today D] [--plan] [--json]

The board is a v3 directory of item files (``--board`` the directory, or the stub beside it); ``list`` and ``show``
also read a v2 board file, and every write refuses one. Every write reads the board (``load_board()``), applies the
module's edit (``item_file``, ``decided_file``, ``edit_item``, ``canonical_item_file``, ``set_rank``), and writes the
files back, all or none: ``done``, and a ``decide`` that closes, write the item's archived file
(``archive/<YYYY-MM>/<id>.md``) and remove its open one. A write prints the commit subject the module gives and the
paths it changed (``--json``: one object, naming the item's ``id``); ``--plan`` prints the changes as JSON (each path
with its new text, or null for a removal) and writes nothing. It never runs git, the network or anything of a
consumer's: the caller passes who replies or answers (``--by``), the date (``--today``, default the local clock), the
id (``add --id``, else drawn at random) and the tool and session the subject names, and makes the commit itself. A
write that leaves an open item (``add``, ``snooze``, ``due``, ``decide``, ``reply``) also reports its notes
(``item_notes()`` at ``--today``): ``item_notes`` in ``--json`` and ``--plan``, and on stderr as ``<id>: ℹ <note>``
otherwise; a note never changes the exit code. A ``decide --board-only`` whose lifting answer leaves a listed entry
still carrying the gate writes nothing (v2.7): it reports ``left_open`` and prints ``left open: <ids> still carry
<gate>`` on stderr in every mode. ``split`` (v3.0) is the one write that needs a v2 board: it writes the directory
beside it (``split_board()``), replaces the v2 file with ``board_stub()`` and removes its archive, as one write, and
prints ``split_board_notes()``'s lines as warnings (``warnings`` in ``--json``).

Exit, the package's one table (``ledger.py`` shares it): 0 written (or nothing to change); 1 refused; 2 usage
(a bad ``--today`` among it), or (``decide`` and ``add --parts``) the ledger cannot be used as asked; 4 a write failed (every file restored). 3 is ``ledger.py``'s
``needs`` and never the board writer's.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from . import (
    BOARD_ARCHIVE,
    BOARD_MAJOR,
    BOARD_README,
    QUEUE_ACTIONS,
    Board,
    BoardItem,
    Refused,
    _carried,
    _declared_major,
    _item_gate,
    _lifting,
    _num,
    answered_by,
    archive_path,
    board_delegates,
    board_people,
    board_problems,
    board_stub,
    canonical_item_file,
    closes,
    decide_lift,
    decided_file,
    delegate_problem,
    edit_item,
    entries,
    fill_form,
    is_item_id,
    is_person,
    item_file,
    item_id,
    item_notes,
    item_path,
    item_record,
    load,
    load_board,
    parse_item,
    parts_problems,
    people_problems,
    queue_subject,
    respace,
    set_rank,
    show_board,
    split_board,
    split_board_notes,
    subject,
    version_problem,
)

ACTIONS = ("list", "show", "add", "snooze", "due", "done", "decide", "reply", "fmt", "split", "rank")
EDITS = ("snooze", "due", "done", "decide", "reply")
TOOL = "ledgerboard"


@dataclass
class Plan:
    """A write, built and not yet made: each path's new text (or None, removed), the commit subject, and what
    the action reports."""

    action: str
    subject: str | None
    changes: dict[str, str | None] = field(default_factory=dict)  # None: the file is removed
    info: dict = field(default_factory=dict)
    warn: list[str] = field(default_factory=list)  # lines for stderr in every mode, never in the JSON

    def as_json(self) -> dict:
        return {"action": self.action, "subject": self.subject,
                "changes": [{"path": p, "text": t} for p, t in self.changes.items()], **self.info}


# -- files --------------------------------------------------------------------------------------------

def read(path: str, missing_ok: bool = False) -> str:
    """The file's text, line endings as written; Refused when it cannot be read or declares a newer major."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        if missing_ok:
            return ""
        raise Refused(f"{path}: no such file") from None
    except OSError as e:
        raise Refused(f"{path}: cannot be read: {e}") from None
    why = version_problem(text)
    if why:
        raise Refused(f"{path}: {why}")
    return text


def write(changes: Mapping[str, str | None]) -> list[str]:
    """Write every path's new text, or remove it (None), both or neither: each text to a temporary file beside
    it (its directory made when missing), then each renamed into place, then each removal; when a step
    fails, the files already replaced or removed are put back, the directories made are removed, and
    OSError is raised."""
    temps: list[tuple[str, str]] = []
    made: list[str] = []
    try:
        for path, text in changes.items():
            if text is None:
                continue
            d = os.path.dirname(os.path.abspath(path))
            missing = []
            while not os.path.isdir(d):
                missing.append(d)
                d = os.path.dirname(d)
            for m in reversed(missing):
                os.mkdir(m)
                made.append(m)
            fd, tmp = tempfile.mkstemp(prefix=".ledgerboard-", dir=os.path.dirname(os.path.abspath(path)))
            temps.append((path, tmp))
            with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                f.write(text)
            if os.path.exists(path):
                os.chmod(tmp, os.stat(path).st_mode & 0o7777)
            else:  # a new file takes the umask's mode, as open() would give it, not mkstemp's 0600
                mask = os.umask(0)
                os.umask(mask)
                os.chmod(tmp, 0o666 & ~mask)
        olds: dict[str, tuple[bytes, int] | None] = {}
        for p in changes:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    olds[p] = (f.read(), os.stat(p).st_mode & 0o7777)
            else:
                olds[p] = None
        done: list[str] = []
        try:
            for path, tmp in temps:
                os.replace(tmp, path)
                done.append(path)
            for path, text in changes.items():
                if text is None and olds[path] is not None:
                    os.unlink(path)
                    done.append(path)
        except OSError:
            for path in done:
                if olds[path] is None:
                    os.unlink(path)
                else:
                    with open(path, "wb") as f:
                        f.write(olds[path][0])
                    os.chmod(path, olds[path][1])
            raise
    except OSError:
        for _, tmp in temps:
            if os.path.exists(tmp):
                os.unlink(tmp)
        for m in reversed(made):
            try:
                os.rmdir(m)
            except OSError:
                pass
        raise
    finally:
        for _, tmp in temps:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return list(changes)


# -- the board on disk ---------------------------------------------------------------------------------

def fs_ls(path: str) -> list[str] | None:
    """A directory's entries, sorted, each subdirectory's name ending `/` (the ``ls`` ``load_board()`` takes);
    None when ``path`` is no directory."""
    if not os.path.isdir(path):
        return None
    return sorted(n + "/" if os.path.isdir(os.path.join(path, n)) else n for n in os.listdir(path))


def fs_read(path: str) -> str | None:
    """A file's text, line endings as written; None when it is missing or cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
            return f.read()
    except OSError:
        return None


def _norm(board: str) -> str:
    """``--board`` as one path: ``docs/user_attention/`` and ``docs/user_attention`` name one board (v3.0)."""
    return os.path.normpath(board)


def board_dir(board: str) -> str:
    """The directory a v3 board's files are in: ``board`` itself, or the directory beside a stub."""
    path = _norm(board)
    return path if os.path.isdir(path) or not path.endswith(".md") else path[:-3]


def _load(board: str, ls=fs_ls, rd=fs_read) -> Board:
    """The board at ``board`` read whole (``load_board()``), Refused when it declares a newer major."""
    path = _norm(board)
    got = load_board(path, ls, rd)
    why = version_problem(got)
    if why:
        where = os.path.join(board_dir(path), BOARD_README) if got.form == "dir" else path
        raise Refused(f"{where}: {why}")
    return got


def read_board(board: str) -> Board:
    """The board for a read (``list``, ``show``): a v3 board or a v2 one; Refused only when there is none."""
    got = _load(board)
    if got.form is None:
        raise Refused(f"{_norm(board)}: no such board")
    return got


def v3_problem(board: Board, ls=fs_ls) -> str | None:
    """Why a write may not go to ``board`` (v3.0, SPEC *The board writer*), or None: a write needs a v3 board, a
    directory whose `README.md` exists and itself declares `Ledgerboard: 3`."""
    if board.form is None:
        return "no such board"
    if board.form != "dir":
        return "a v2 board (split first: board.py split)"
    if BOARD_README not in (ls(board_dir(board.path)) or []):
        return f"no {BOARD_README}"
    if any(p == BOARD_README and why.startswith("unreadable") for p, why in board.problems):
        return f"{BOARD_README} unreadable"
    declared = _declared_major(board.preamble, False)
    if declared is None:
        return f"{BOARD_README} declares no Ledgerboard"
    if declared != BOARD_MAJOR:
        return f"{BOARD_README} declares Ledgerboard: {declared}"
    return None


def load_v3(board: str, ls=fs_ls, rd=fs_read) -> Board:
    """The board for a write: read (``_load()``), then Refused unless it is a v3 board (``v3_problem()``)."""
    got = _load(board, ls, rd)
    why = v3_problem(got, ls)
    if why:
        raise Refused(f"{_norm(board)}: not a v3 board: {why}")
    return got


def held(board: Board, ls=fs_ls) -> set[str]:
    """Every id whose name is taken on ``board`` (v3.0, D3): an open or closed item's id, and the stem of every
    `<id>.md` in the directory or under any `archive/<YYYY-MM>/`, read or not."""
    out = {it.id for it in [*board.items, *board.closed] if it.id is not None}
    d = board_dir(board.path)
    names = [n for n in ls(d) or [] if not n.endswith("/")]
    for month in ls(os.path.join(d, BOARD_ARCHIVE)) or []:
        if month.endswith("/"):
            names += [n for n in ls(os.path.join(d, BOARD_ARCHIVE, month[:-1])) or [] if not n.endswith("/")]
    return out | {n[:-3] for n in names if n.endswith(".md") and is_item_id(n[:-3])}


def _overlay(changes: Mapping[str, str | None], ls=fs_ls, rd=fs_read):
    """An ``ls`` and a ``read`` of the disk with ``changes`` (path to text, None removed) put in, nothing written."""
    want = {os.path.abspath(p): t for p, t in changes.items()}

    def read2(path: str) -> str | None:
        p = os.path.abspath(path)
        return want[p] if p in want else rd(path)

    def ls2(path: str) -> list[str] | None:
        p = os.path.abspath(path)
        names = set(ls(path) or [])
        there = ls(path) is not None
        for q, t in want.items():
            if os.path.dirname(q) == p:
                there = there or t is not None
                (names.add if t is not None else names.discard)(os.path.basename(q))
            elif t is not None and q.startswith(p + os.sep):
                there = True
                names.add(q[len(p) + 1:].split(os.sep, 1)[0] + "/")
        return sorted(names) if there else None
    return ls2, read2


def _gate(board: str, old: Board, changes: Mapping[str, str | None]) -> None:
    """Refused when the write leaves an open item the writers would not write (``board_problems()`` of the board
    the write leaves, against ``old``); its notes (``ℹ``) are no fault. Each fault is named by its path in the
    board's directory."""
    ls2, rd2 = _overlay(changes)
    new = load_board(old.path, ls2, rd2)
    bad = [(p, why) for p, why in board_problems(new, old) if not why.startswith("ℹ")]
    if bad:
        raise Refused(f"{_norm(board)}: " + "; ".join(f"{p}: {why}" for p, why in bad))


def _find(board: Board, id: str) -> BoardItem:
    """The open item ``id`` names, Refused when no open item has it."""
    got = next((it for it in board.items if it.id == id), None)
    if got is None:
        raise Refused(f"{_norm(board.path)}: no open item has the id {id}")
    return got


# -- the actions, each a Plan ---------------------------------------------------------------------------

class BadToday(Refused):
    """A ``--today`` that is not a YYYY-MM-DD date: exit 2, as the ledger writer gives it."""


def _today(today: str | date | None) -> date:
    if today is None:
        return date.today()  # noqa: DTZ011  # the board's dates are the local clock's (target design §1.1)
    if isinstance(today, date):
        return today
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise BadToday(f"--today is YYYY-MM-DD, not {today!r}")
    try:
        return date.fromisoformat(today)
    except ValueError:
        raise BadToday(f"--today {today} is not a date") from None


def items(board: str, today: str | date | None = None) -> list[dict]:
    """Every open item's record (``item_record()``) at `today`, in the board's order: a v3 board or a v2 one."""
    day = _today(today)
    return [item_record(i, day) for i in read_board(board).items]


def show(board: str, today: str | date | None = None, hidden: bool = False) -> str:
    """The board for a person (``show_board()``): a v3 board or a v2 one."""
    day = _today(today)
    return show_board(read_board(board), day, hidden=hidden)


def who_answered(board: Board, by: str | None) -> str:
    """Who gave an answer on this board (v2.3, target design §6.2): on a board whose ``People:`` lists one
    name, `by` defaults to it; otherwise `by` is required. A `by` off the ``People:`` list (compared
    case-insensitively) is refused, and one on it is written as ``People:`` spells it. On a board with no
    ``People:`` line, `by` is checked against the person grammar only. A ``People:`` line the gate faults
    (``people_problems()``) refuses every answer: nobody can be checked against it."""
    by = " ".join((by or "").split()) or None
    people = board_people(board)
    if people is None:
        if by is None:
            raise Refused("this board has no People: line, so an answer needs --by, who gave it")
        if not is_person(by):
            raise Refused(f"--by {by!r} is not a person's name (letters, digits, `_`, `-`, dot-separated)")
        return by
    bad = [why for _, why in people_problems(board) if not why.startswith("ℹ")]
    if bad:
        raise Refused("the board's People: line is not one the writers read: " + "; ".join(bad))
    if by is None:
        if len(people) == 1:
            return people[0]
        raise Refused(f"--by: who gave the answer — the board's People: lists {', '.join(people)}")
    named = next((x for x in people if x.lower() == by.lower()), None)
    if named is None:
        raise Refused(f"--by {by} is not on the board's People: ({', '.join(people)})")
    return named


DOER_DECIDED = "--doer is an act's, who does its step: a decided item is a decide and takes none"
SCOPE_DECIDED = "--scope is an asked decide's, the kind of decision it is: an item raised already answered takes none"
DELEGATE_NOT_DECIDE = "--delegate is a decide's"
DELEGATE_BOARD_ONLY = "--delegate writes its own ledger half, never --board-only"
DRAWS = 8  # an add draws a nonce at most this many times in all (D3)


def _draw() -> str:
    return secrets.token_hex(4)


def _new_id(board: Board, day: str, given: str | None) -> str:
    """The new item's id: ``given`` (``--id``), refused when it is no id, its date is not the item's `Added`, or
    it is held; else a nonce drawn (``secrets.token_hex(4)``) and drawn again while the id is held, at most
    ``DRAWS`` times in all."""
    taken = held(board)
    name = _norm(board.path)
    if given is not None:
        if not is_item_id(given):
            raise Refused(f"--id {given!r} is no item id: YYYY-MM-DD-<8 hex>, a day of the calendar")
        if given[:10] != day:
            raise Refused(f"--id {given}: its date is not the item's Added, {day}")
        if given in taken:
            raise Refused(f"{name}: {given} is held")
        return given
    for _ in range(DRAWS):
        got = item_id(day, _draw())
        if got not in taken:
            return got
    raise Refused(f"{name}: no free id after {DRAWS} draws")


def _one_line(value: str) -> bool:
    """Whether ``value`` holds no character ``str.splitlines()`` splits on."""
    return not value or value.splitlines() == [value]


def plan_add(board: str, text: str, *, due: str | None = None, context: str | None = None,
             kind: str | None = None, answers: Sequence[str] | None = None, default: int | None = None,
             detail: Mapping | None = None, session: str | None = None, host: str | None = None,
             decided: str | None = None, said: str | None = None, by: str | None = None,
             today: str | date | None = None, tool: str = TOOL, id: str | None = None,
             hide_until: str | None = None, lifts: Sequence[str] | None = None,
             parts: Sequence[str] | None = None, ledger: str | None = None, doer: str | None = None,
             scope: str | None = None) -> Plan:
    """A new item file at ``<board>/<id>.md`` (``item_file()``), its id ``id`` or drawn (``_new_id()``); with
    `said`, a question that was already answered, `said` its first reply, a Log line ``- <today>: <by>: <said>``;
    with `decided`, an item already decided by the person (``decided_file()``: `text` its title, `context` its ref,
    `by` who answered, as ``who_answered()`` resolves it). With `parts` (v2.6), a decide's `Parts:` snapshot
    (``item_file(parts=)``), checked against the ledger (`ledger`, else ``ledger/`` beside the board when it is a
    directory) by ``parts_problems()`` before the board's gate. With `doer` (v2.8), an act's `Doer:`; with `scope`
    (v3.4), a decide's `Scope`."""
    day = _today(today).isoformat()
    if ledger is not None and parts is None:
        raise Refused("--ledger on an add is the ledger a --parts snapshot is checked against: give --parts too")
    if decided is not None:
        if parts is not None:
            raise Refused("--parts is a decide's snapshot, asked as a question: a decided item takes none")
        if doer is not None:
            raise Refused(DOER_DECIDED)
        if scope is not None:
            raise Refused(SCOPE_DECIDED)
        if any(v is not None for v in (due, kind, detail, session, host, said, hide_until, lifts)):
            raise Refused("a decided item takes its title, context, answers, default, words and who gave them alone")
    elif said is not None or by is not None:
        if said is None or by is None:
            raise Refused("an answered item needs both --said, the answer's words, and --by, who said it")
    old = load_v3(board)
    new_id = _new_id(old, day, id)
    if decided is not None:
        new = decided_file(text, context or "", list(answers or []), default, decided, day,
                           by=who_answered(old, by))
    else:
        new = item_file(text, due, day, session, host, context, kind=kind,
                        answers=list(answers) if answers is not None else None, default=default, detail=detail,
                        hide_until=hide_until, lifts=list(lifts) if lifts is not None else None,
                        parts=list(parts) if parts is not None else None, doer=doer, scope=scope)
        if said is not None:
            if not _one_line(said):
                raise Refused("--said is one line: it holds a line break")
            said_words = " ".join(said.split())
            who = " ".join(by.split())
            if not said_words or not who:
                raise Refused("an answered item needs both --said, the answer's words, and --by, who said it")
            if ":" in who or len(who) > 40:
                raise Refused(f"--by {who!r} is a Log name: no `:`, at most 40 characters")
            new = edit_item(new, "reply", reply=said_words, by=who, today=_today(today))
        if parts is not None:
            _check_parts(board, new, ledger)
    d = board_dir(old.path)
    path = os.path.join(d, item_path(new_id))
    changes: dict[str, str | None] = {path: new}
    _gate(board, old, changes)
    got = parse_item(new, item_path(new_id))
    msg = subject(tool, "append", got.words, session=session, id=new_id)
    after = load_board(old.path, *_overlay(changes))
    return Plan("add", msg, changes, {"id": new_id, "item_notes": _id_notes(after, new_id, _today(today))})


def _ledger_beside(board_path: str) -> str | None:
    """``ledger/`` beside the board (its normalised path), when it is a directory."""
    beside = os.path.normpath(os.path.join(os.path.dirname(_norm(board_path)) or ".", "ledger"))
    return beside if os.path.isdir(beside) else None


def _check_parts(board_path: str, new: str, ledger: str | None) -> None:
    """A new item's `Parts:` snapshot against the ledger (v2.6, SPEC *The board writer*): the ledger found
    (`ledger`, else ``ledger/`` beside the board when it is a directory; none is Refused), opened as a decide's
    ledger half opens it (one that cannot be used is Unusable, exit 2), and the open and archived texts of the
    Context entry and of each part handed to ``parts_problems()``, the archived ones named in ``archived``;
    Refused, with every problem, when it names any."""
    from . import ledger as L  # the ledger writer imports this module, so it is loaded here, when needed
    path = ledger or _ledger_beside(board_path)
    if path is None:
        raise Refused("a --parts snapshot is checked against the ledger: pass --ledger (the v2 directory), or "
                      "keep it as ledger/ beside the board")
    led = L.Ledger.open(path)
    L._writable(led)
    it = parse_item(new)
    ref, _ = _item_gate(it)
    texts: dict[str, str] = {}
    gone: list[str] = []
    for x in [ref, *it.parts]:
        if x is None:
            continue
        try:
            p, archived = led.entry_file(L.tid_of(x))
        except Refused:
            continue  # in neither directory, or no id the ledger holds (TD-0): parts_problems() says missing
        got = entries(led.files[p])
        tid = got[0]["id"] if got else L.tid_of(x)
        texts.setdefault(tid, led.files[p])
        if archived:
            gone.append(tid)
    problems = parts_problems(new, texts, gone)
    if problems:
        raise Refused("the snapshot does not match the ledger: " + "; ".join(problems))


def _id_notes(board: Board, id: str, today: date) -> list[dict]:
    """The notes (``item_notes()`` at `today`) of the open item ``id`` as the write leaves the board, each
    naming the id; ``[]`` when no open item has it (a close)."""
    got = next((it for it in board.items if it.id == id), None)
    return [{"id": id, "note": n} for n in item_notes(got, today)] if got else []


def plan_edit(board: str, action: str, id: str, *, to: str | None = None,
              why: str | None = None, answer: str | None = None, text: str | None = None,
              by: str | None = None, today: str | date | None = None, tool: str = TOOL,
              session: str | None = None, ledger: str | None = None, board_only: bool = False,
              delegate: str | None = None) -> Plan:
    """One of the five edits (``edit_item()``) of the open item ``id``; a decide's `by`, who answered, as
    ``who_answered()`` resolves it. A decide on an item naming one entry and one gate is the two-file decide lift
    (``_decide_ledger()``): the item file, closed per ``closes()``, and the entries ``decide_lift()`` changes in
    ``ledger``, both or neither; ``board_only`` writes the board half alone. ``done``, and a decide that closes,
    write the archived file (``item_path(id, closed)``) and remove the open one in one write. With ``delegate``
    (v3.4), a delegated answer for ``by``: refused with ``board_only`` and on any action but a decide, then, once
    ``by`` is resolved, with ``delegate_problem()``'s message; written in the delegated form, the delegate as the
    grant spells it, its ledger half by the decide lift in the delegated Log form."""
    if action not in EDITS:
        raise Refused(f"an edit is one of {', '.join(EDITS)}, not {action!r}")
    day = _today(today)
    when = None
    if action in ("snooze", "due"):
        if not to:
            raise Refused(f"a {action} needs --to")
        when = _today(to)
    old = load_v3(board)
    it = _find(old, id)
    if action == "reply" and not (by and by.strip()):  # the edit's own refusals, after the id's (D7)
        raise Refused("a reply needs --by, who says it")
    if (ledger is not None or board_only) and action != "decide":
        raise Refused("--ledger and --board-only are a decide's")
    if delegate is not None and action != "decide":
        raise Refused(DELEGATE_NOT_DECIDE)
    if delegate is not None and board_only:
        raise Refused(DELEGATE_BOARD_ONLY)
    if action == "done" and why is not None:
        why = re.sub(r"[\s.?!]+\Z", "", " ".join(why.split()))  # collapsed, then stripped, as v2.x's edit_line() did (D7)
    if action == "decide" and isinstance(answer, str) and answer.strip():
        answer = fill_form(answer, it.answers) or answer  # v2.8: filled once, so board, ledger and subject agree
    if action == "decide":
        by = who_answered(old, by)
    scope = None
    if delegate is not None:  # v3.4: D3's rules, before the item edit and the ledger half
        delegate = " ".join(delegate.split())
        fault = delegate_problem(old, it, delegate, by)
        if fault is not None:
            raise Refused(fault)
        delegate = next(d for d, p, _ in board_delegates(old) or [] if p is not None and d.lower() == delegate.lower()
                        and p.lower() == by.lower())  # as the grant spells it
        scope = it.scope
    edit_item(it.raw, action, to=when, answer=answer, why=why or None, reply=text, by=by, today=day,
              delegate=delegate)  # its refusals first
    changes: dict[str, str | None] = {}
    info: dict = {"id": id}
    close = False
    if action == "decide":
        close, changes, extra = _decide_ledger(board, old, it, answer, by, day, ledger, board_only, today,
                                               delegate=delegate, scope=scope)
        info = {"id": id, **extra}
        if "left_open" in info:  # v2.7: a --board-only lift that does not close the item writes nothing
            gate_ = info.pop("gate")
            info["item_notes"] = _id_notes(old, id, day)
            return Plan("decide", None, {}, info,
                        [f"left open: {', '.join(info['left_open'])} still carry {gate_}"])
    new = edit_item(it.raw, action, to=when, answer=answer, why=why or None, reply=text, by=by, today=day,
                    close=close, delegate=delegate)
    d = board_dir(old.path)
    here = os.path.join(d, it.path)
    shut = parse_item(new).closed
    if shut is not None:
        there = os.path.join(d, item_path(id, shut[0].isoformat()))
        if os.path.exists(there):
            raise Refused(f"{_norm(board)}: {item_path(id, shut[0].isoformat())} exists")
        files: dict[str, str | None] = {there: new, here: None}  # the archived file first, then the removal
    else:
        files = {here: new}
    changes = {**files, **changes}
    _gate(board, old, changes)
    if action != "done":  # a done leaves no open item; a decide that closes reports [] (D7)
        info["item_notes"] = _id_notes(load_board(old.path, *_overlay(changes)), id, day)
    msg = subject(tool, action, it.words, to=when, answer=answer, session=session or it.session, id=id)
    return Plan(action, msg, changes, info)


def _may_answer(board: Board, gate_: str, by: str) -> None:
    """``decide_lift()``'s People: and Answered by: checks, for an item it does not lift (another repo's entry):
    the gate's person and who answered are on `People:`, and under `owner` a decision is answered by its person."""
    people = board_people(board)
    if people is None:
        return
    on = {x.lower() for x in people}
    person = gate_[len("decision ("):-1] if gate_.startswith("decision") else None
    if person is not None and person.lower() not in on:
        raise Refused(f"the gate's person {person} is not on the board's People: ({', '.join(people)})")
    if by.lower() not in on:
        raise Refused(f"{by} is not on the board's People: ({', '.join(people)}) — only a listed person answers")
    if person is not None and (answered_by(board) or "owner").lower() == "owner" and by.lower() != person.lower():
        raise Refused(f"only {person} answers for {gate_} on a board whose Answered by is owner, not {by}")


def _decide_ledger(board_path: str, board: Board, item: BoardItem, label: str | None, by: str, day: date,
                   ledger: str | None, board_only: bool, today: str | date | None, *, delegate: str | None = None,
                   scope: str | None = None) -> tuple[bool, dict[str, str | None], dict]:
    """A decide's ledger half (v2.4, SPEC *The board writer*): (whether the answer closes the item, the ledger
    files it changes, what it reports). An item whose Context names one bare ``TD-n`` and one gate is the
    decide lift: ``decide_lift()`` on the ledger's base texts of that entry and its `Parts:` (a listed id only the
    archive holds passed as an id in ``archived``, never as a text, v2.6), judged as the ledger writer judges a
    write, then ``closes()`` on the texts after. With ``board_only`` (the ``set by=`` route, which has written the
    ledger already) nothing is written there, and ``closes()`` reads the ledger as it stands; a lifting answer
    that does not close the item (a listed entry still carries the gate) reports ``left_open``, those ids as the
    item spells them in its order, and the gate, and the board is not written (v2.7). An item naming another
    repo's entry is answered on the board alone and stays open."""
    file = item.raw
    ref, gate_ = _item_gate(item)
    if ref is None or gate_ is None:
        if ledger is not None or board_only:
            raise Refused("--ledger and --board-only are for a decide item whose Context names one entry and one gate")
        return closes(file, label or "", {}), {}, {}  # a waiting-only answer on a gate item still closes it
    if "#" in ref:
        if ledger is not None:
            raise Refused(f"{ref} is another repo's entry: its lift is a tool PR there, so no --ledger here")
        _may_answer(board, gate_, by)
        return closes(file, label or "", {}), {}, {"entries": [], "board_only": True}
    from . import ledger as L  # the ledger writer imports this module, so it is loaded here, when needed
    path = ledger or _ledger_beside(board_path)
    if path is None:
        raise Refused(f"the item lifts {gate_} on {ref}: pass --ledger (the v2 directory), or --board-only when "
                      "the ledger is written already")
    try:
        led = L.Ledger.open(path)
        L._writable(led)
        ids = [ref, *[x for x in item.parts if "#" not in x]]
        found = {}
        gone = []  # each listed id only the archive holds, as its heading spells it: an id, never a text (v2.6)
        for x in ids:
            try:
                p, archived = led.entry_file(L.tid_of(x))
            except Refused:
                continue
            tid = entries(led.files[p])[0]["id"]
            if archived:
                gone.append(tid)
            else:
                found[tid] = p
        base = {tid: led.files[p] for tid, p in found.items()}
        if board_only:
            shut = closes(file, label or "", base)
            if not shut and _lifting(label or "", item.lifts, item.answers):  # v2.7: write it only when it closes
                by_num = {_num(t): x for t, x in base.items()}
                left = [x for x in ids if _carried(by_num.get(_num(x)), gate_) is not None]
                return False, {}, {"entries": [], "board_only": True, "left_open": left, "gate": gate_}
            return shut, {}, {"entries": [], "board_only": True}
        ledger_day = L._today(today)
        got = decide_lift(file, base, label or "", by, ledger_day, board_people(board), answered_by(board),
                          archived=gone, delegate=delegate, scope=scope)
        changes: dict[str, str | None] = {found[tid]: text for tid, text in got.items()}
        notes = L.gate(led, changes, today=ledger_day) if changes else []
    except L.Unusable as e:
        raise L.Unusable(f"the ledger half: {e}") from None
    except Refused as e:
        raise Refused(f"the ledger half: {e}") from None
    after = {**base, **got}
    return closes(file, label or "", after), changes, {"entries": sorted(got), "notes": notes}


def plan_fmt(board: str) -> Plan:
    """Every open item file (each ``*.md`` directly in the board's directory but `README.md`) rewritten into the
    writers' form (``canonical_item_file()``); a file it cannot, and an ``*.md`` whose name is no id, reported
    with why and kept. A format pass has no commit subject of its own: the caller names its commit."""
    old = load_v3(board)
    d = board_dir(old.path)
    changes: dict[str, str | None] = {}
    fixed, refused = [], []
    for n in fs_ls(d) or []:
        if n.endswith("/") or not n.endswith(".md") or n == BOARD_README:
            continue
        stem = n[:-3]
        if not is_item_id(stem):
            refused.append({"id": stem, "why": "not an item file name"})
            continue
        text = fs_read(os.path.join(d, n))
        if text is None:
            refused.append({"id": stem, "why": "unreadable"})
            continue
        try:
            new = canonical_item_file(text)
        except Refused as e:
            refused.append({"id": stem, "why": str(e)})
            continue
        if new != text:
            changes[os.path.join(d, n)] = new
            fixed.append(stem)
    return Plan("fmt", None, changes, {"fixed": fixed, "refused": refused})


def _title(text: str, path: str) -> str:
    """A v2 board's title: its first `# ` line's text, else the file's name without `.md`."""
    for ln in text.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return os.path.basename(path).removesuffix(".md")


def plan_split(board_path: str, archive_path_: str | None = None, read=fs_read, exists=os.path.exists) -> Plan:
    """A v2 board split into its directory (v3.0, SPEC *The board writer*, ``split``): every file
    ``split_board()`` gives written into the directory beside the board, named the board's name less `.md`, the
    v2 file replaced by ``board_stub()`` and the archive (``archive_path_``, default ``<stem>_archive.md`` beside
    it, none when that is absent) removed, as one write. Its gate is the reverse of a write's, each Refused before
    anything is written: a newer major, a stub whose directory is missing, no board, a v3 board, a ``--board`` not
    ending `.md`, an ``--archive`` given that does not exist, ``split_board()``'s refusals, then the directory
    existing. ``split_board_notes()``'s lines are warnings."""
    path = _norm(board_path)
    got = _load(path, rd=read)
    if got.form is None and got.major is not None and got.problems:
        raise Refused(f"{path}: a v3 stub whose directory is missing")
    if got.form is None:
        raise Refused(f"{path}: no such board")
    if got.form == "dir":
        raise Refused(f"{path}: already a v3 board")
    if not path.endswith(".md"):
        raise Refused(f"{path}: not a v2 board file (.md)")
    default = archive_path(path)
    arch = _norm(archive_path_) if archive_path_ is not None else default
    if archive_path_ is not None and not exists(arch):
        raise Refused(f"{arch}: no such file")
    text = read(path) or ""
    archive = read(arch) if exists(arch) else None
    try:
        files = split_board(text, archive or "")
        notes = split_board_notes(files, text, archive or "")
    except Refused as e:
        raise Refused(f"{path}: {e}") from None
    d = path[:-3]
    if exists(d):
        raise Refused(f"{path}: {d}/ exists")
    changes: dict[str, str | None] = {os.path.join(d, rel): t for rel, t in files.items()}
    written = list(changes)
    changes[path] = board_stub(_title(text, path), os.path.basename(d))
    if archive is not None:
        changes[arch] = None
    warnings = [{"path": arch if p == "(archive)" else os.path.join(d, p), "line": n, "text": ln, "why": why}
                for p, n, ln, why in notes]
    if arch != default and exists(default):
        warnings.append({"path": default, "line": None, "text": "", "why": "default archive left in place"})
    warn = [f"{w['path']}:{w['line']}: ⚠ {w['why']}" if w["line"] is not None else f"{w['path']}: ⚠ {w['why']}"
            for w in warnings]
    return Plan("split", None, changes, {"files": written, "removed": [arch] if archive is not None else [],
                                         "warnings": warnings}, warn)


def read_ledger(path: str) -> str:
    """The open entries' text of the ledger at `path`, a v1 file or a v2 directory (``load()``)."""
    def ls(p: str) -> list[str] | None:
        return sorted(n for n in os.listdir(p) if os.path.isfile(os.path.join(p, n))) if os.path.isdir(p) else None

    def rd(p: str) -> str | None:
        return read(p) if os.path.isfile(p) else None
    if not os.path.exists(path):
        raise Refused(f"{path}: no such ledger")
    return load(path, ls, rd)[0]


def plan_respace(rank_file: str, ledger: str, *, fixed: Sequence[str] = (), repo: str = "", tool: str = TOOL) -> Plan:
    """The rank file's keys shortened without moving anything relative to a key it does not own (``respace()``):
    the ledger's un-lined entries' implicit keys, and `fixed`, another repo's keys a caller sorts beside them."""
    old = read(rank_file, missing_ok=True)
    new, ids = respace(old, read_ledger(ledger), fixed=list(fixed), repo=repo)
    if not ids:
        return Plan("rank", None)  # every key already as short as its gap allows: nothing to write
    return Plan("rank", queue_subject(tool, "respace", ids), {rank_file: new}, {"respaced": ids})


def plan_rank(rank_file: str, action: str, lines: Mapping[str, str | None], *, tool: str = TOOL) -> Plan:
    """The rank file with `lines` set (a key) or removed (None) (``set_rank()``), under its queue subject."""
    if action == "respace":
        raise Refused("a respace sets no lines of its own: use plan_respace()")
    if action not in QUEUE_ACTIONS:
        raise Refused(f"a rank write is one of {', '.join(QUEUE_ACTIONS)}, not {action!r}")
    if not lines:
        raise Refused("a rank write sets or drops at least one id")
    sets = [t for t, k in lines.items() if k is not None]
    if action == "prune" and sets:
        raise Refused(f"a prune removes lines and sets none: {', '.join(sets)}")
    if action != "prune" and len(sets) != len(lines):
        raise Refused(f"a {action} sets lines and removes none: {', '.join(t for t in lines if t not in sets)}")
    old = read(rank_file, missing_ok=True)
    new = set_rank(old, lines)
    if new == old:
        return Plan("rank", None)  # every line already says so: nothing to write, nothing to commit
    return Plan("rank", queue_subject(tool, action, list(lines)), {rank_file: new})


def apply(plan: Plan) -> list[str]:
    """Make the plan's writes, both or neither; the paths written."""
    return write(plan.changes) if plan.changes else []


# -- the command line -------------------------------------------------------------------------------

def _pairs(sets: Sequence[str], drops: Sequence[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for s in sets:
        tid, eq, key = s.partition("=")
        if not eq:
            raise Refused(f"--set is TD-n=KEY, not {s!r}")
        if tid in out:
            raise Refused(f"{tid} is set twice")
        out[tid] = key
    for tid in drops:
        if tid in out:
            raise Refused(f"{tid} is set or dropped twice")
        out[tid] = None
    return out


def _parts_given(values: Sequence[str]) -> list[str] | None:
    """The ids of every ``--parts`` value, each split on ``,`` and each piece trimmed; None when none was given.
    An empty piece (``TD-9,``) is refused."""
    if not values:
        return None
    out = []
    for v in values:
        for piece in v.split(","):
            if not piece.strip():
                raise Refused(f"--parts {v!r} holds an empty piece: give TD-a,TD-b")
            out.append(piece.strip())
    return out


def build(a: argparse.Namespace) -> Plan:
    if a.action == "add":
        if a.parts and a.decided is not None:  # step 1's order (SPEC *The board writer*): ahead of the pieces
            raise Refused("--parts is a decide's snapshot, asked as a question: a decided item takes none")
        if a.doer is not None and a.decided is not None:  # the same step (v2.8): a decided line is a decide
            raise Refused(DOER_DECIDED)
        if a.scope is not None and a.decided is not None:  # the same step (v3.4)
            raise Refused(SCOPE_DECIDED)
        parts = _parts_given(a.parts)
        detail = None
        if a.detail is not None:
            try:
                detail = json.loads(a.detail)
            except ValueError as e:
                raise Refused(f"--detail is a JSON object: {e}") from None
            if not isinstance(detail, dict):
                raise Refused("--detail is a JSON object")
        return plan_add(a.board, a.text, due=a.due, context=a.context, kind=a.kind, hide_until=a.hide_until,
                        answers=a.answer or None, default=a.default, lifts=a.lift or None, detail=detail, session=a.session,
                        host=a.host, decided=a.decided, said=a.said, by=a.by, id=a.id,
                        today=a.today, tool=a.tool, parts=parts, ledger=a.ledger, doer=a.doer, scope=a.scope)
    if a.action in EDITS:
        if a.action == "decide" and len(a.answer) != 1:
            raise Refused("decide takes one --answer, the person's")
        answer = a.answer[0] if a.action == "decide" else None
        return plan_edit(a.board, a.action, a.id, to=a.to, why=a.why, answer=answer,
                         text=a.text, by=a.by, today=a.today, tool=a.tool, session=a.session,
                         ledger=a.ledger, board_only=a.board_only or False, delegate=a.delegate)
    if a.action == "fmt":
        return plan_fmt(a.board)
    if a.action == "split":
        return plan_split(a.board, a.archive)
    if a.queue == "respace":
        if a.set or a.drop:
            raise Refused("a respace sets and drops no lines: it rewrites the keys itself")
        if not a.ledger:
            raise Refused("a respace needs --ledger, whose un-lined entries' keys it keeps in place")
        return plan_respace(a.rank, a.ledger, fixed=a.fixed, repo=a.repo or "", tool=a.tool)
    if a.ledger or a.fixed or a.repo:
        raise Refused("--ledger, --fixed and --repo are a respace's")
    return plan_rank(a.rank, a.queue, _pairs(a.set, a.drop), tool=a.tool)


# Which options each action takes; any other given is a usage error (exit 2).
TAKES = {
    "list": {"board", "today"},
    "show": {"board", "today", "hidden"},
    "add": {"board", "text", "due", "context", "kind", "answer", "default", "detail", "session", "host",
            "decided", "said", "by", "id", "today", "tool", "hide_until", "lift", "parts", "ledger",
            "doer", "scope"},
    "snooze": {"board", "id", "to", "today", "tool", "session"},
    "due": {"board", "id", "to", "today", "tool", "session"},
    "done": {"board", "id", "why", "today", "tool", "session"},
    "decide": {"board", "id", "answer", "by", "today", "tool", "session", "ledger", "board_only", "delegate"},
    "reply": {"board", "id", "text", "by", "today", "tool", "session"},
    "fmt": {"board"},
    "split": {"board", "archive"},
    "rank": {"rank", "queue", "set", "drop", "tool", "ledger", "fixed", "repo"},
}
NEEDS_OPT = {
    "list": ("board",), "show": ("board",), "add": ("board", "text"), "snooze": ("board", "id", "to"),
    "due": ("board", "id", "to"), "done": ("board", "id"), "decide": ("board", "id", "answer"),
    "reply": ("board", "id", "text", "by"),
    "fmt": ("board",), "split": ("board",), "rank": ("rank", "queue"),
}
DEFAULTS = {"tool": TOOL, "hidden": False, "answer": [], "lift": [], "parts": [], "set": [], "drop": [],
            "fixed": [], "board_only": False}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ledgerboard.board", description=__doc__.split("\n", 1)[0])
    ap.add_argument("action", choices=ACTIONS)
    ap.add_argument("--board", help="the board: a v3 directory, or the stub beside it (list and show: a v2 file too)")
    ap.add_argument("--archive", help="split: the v2 board's archive (default: <board>_archive.md beside it)")
    ap.add_argument("--id", help="an edit: the open item's id; add: the new item's id (default: drawn at random)")
    ap.add_argument("--hidden", action="store_true", help="show: the hidden open items too, after the rest")
    ap.add_argument("--rank", help="rank: the rank file (created when missing)")
    ap.add_argument("--action", dest="queue", help="rank: rank, join, prune or respace")
    ap.add_argument("--set", action="append", default=[], help="rank: TD-n=KEY, a line to set")
    ap.add_argument("--drop", action="append", default=[], help="rank: TD-n, a line to remove")
    ap.add_argument("--ledger", help="rank --action respace: the ledger (a file or a v2 directory); decide: the v2 "
                                     "ledger the lift writes; add --parts: the v2 ledger the snapshot is checked "
                                     "against (decide and add: default ledger/ beside the board, when it is a directory)")
    ap.add_argument("--board-only", action="store_true",
                    help="decide: write the board half alone (the set by= route, whose ledger is written already)")
    ap.add_argument("--fixed", action="append", default=[],
                    help="rank --action respace: another repo's key sorted beside this file's (repeat)")
    ap.add_argument("--repo", help="rank --action respace: the last component of this repo's implicit keys")
    ap.add_argument("--to", help="snooze: the Hide until: date; due: the new Due: date")
    ap.add_argument("--why", help="done: why, for the Closed: field")
    ap.add_argument("--answer", action="append", default=[],
                    help="decide: the person's answer; add: one of the item's answers (repeat)")
    ap.add_argument("--lift", action="append", default=[],
                    help="add: a decide's answer that lifts its gate (repeat; none means Go)")
    ap.add_argument("--parts", action="append", default=[],
                    help="add: a decide's Parts: snapshot, TD-a,TD-b (repeat; each part Part of the Context's "
                         "entry and carrying its gate)")
    ap.add_argument("--doer", help="add: an act's Doer:, who should do its step: a repo, or 'team <name>'")
    ap.add_argument("--scope", help="add: a decide's Scope, the kind of decision it is (v3.4)")
    ap.add_argument("--delegate", help="decide: the delegate answering for --by under the board's Delegates: (v3.4)")
    ap.add_argument("--text", help="add: the item's text; reply: the reply's words")
    ap.add_argument("--by", help="reply, add --said: who says it; decide, add --decided: who answered (the one name "
                    "on the board's People: when it lists one)")
    ap.add_argument("--said", help="add: the answer already given, the item's first reply in its Log")
    ap.add_argument("--due", help="add: the item's Due: date")
    ap.add_argument("--hide-until", dest="hide_until", help="add: hide the new item until this date")
    ap.add_argument("--context", help="add: what the item refers to (TD-n, PR #n)")
    ap.add_argument("--kind", help="add: decide, act, look, watch or fyi")
    ap.add_argument("--default", type=int, help="add: the 0-based index of the default answer")
    ap.add_argument("--detail", help="add: the detail block's parts, a JSON object (context, question, "
                                         "caveats, recommended, otherwise); on a decide with a default the writer opens "
                                         "Recommended with '<label> — ' itself, so recommended gives only the words after it")
    ap.add_argument("--host", help="add: the host the item's session runs on")
    ap.add_argument("--decided", help="add: the person's words, for an item already decided")
    ap.add_argument("--session", help="add: the item's session; an edit: the session the subject names")
    ap.add_argument("--tool", default=TOOL, help="the tool the commit subject names")
    ap.add_argument("--today", help="the date the write records, YYYY-MM-DD (default: the local clock)")
    ap.add_argument("--plan", action="store_true", help="print the changes as JSON and write nothing")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    a = ap.parse_args(argv)
    if a.action == "show" and (a.json or a.plan):
        ap.error("show prints the board as text: it takes no --json or --plan")
    given = {k for k, v in vars(a).items()
             if k not in ("action", "plan", "json") and v is not None and v != DEFAULTS.get(k)}
    extra = sorted(given - TAKES[a.action])
    if extra:
        ap.error(f"{a.action} does not take {', '.join('--' + e.replace('_', '-') for e in extra)}")
    missing = [o for o in NEEDS_OPT[a.action] if getattr(a, o) in (None, [])]
    if missing:
        ap.error(f"{a.action} needs {', '.join('--' + ('action' if o == 'queue' else o) for o in missing)}")
    try:
        if a.action == "list":
            got = items(a.board, a.today)
            if a.json:
                print(json.dumps({"action": "list", "items": got}, ensure_ascii=False, default=str))
            else:
                for r in got:
                    print(f"{r['id'] or '-'}\t{r['due_tag'] or '-'}\t{r['text']}")
            return 0
        if a.action == "show":
            sys.stdout.write(show(a.board, a.today, a.hidden))
            return 0
        plan = build(a)
    except Refused as e:
        from . import ledger as L  # loaded here, as in decide: the ledger writer imports this module
        code = 2 if isinstance(e, (BadToday, L.Unusable)) else 1  # 2 as ledger.py gives them
        if a.json or a.plan:
            print(json.dumps({"action": a.action, "refused": str(e)}, ensure_ascii=False))
        else:
            print(f"ledgerboard.board: refused: {e}", file=sys.stderr)
        return code
    for w in plan.warn:
        print(w, file=sys.stderr)
    if a.plan:
        print(json.dumps(plan.as_json(), ensure_ascii=False))
        return 0
    try:
        paths = apply(plan)
    except OSError as e:
        print(f"ledgerboard.board: the write failed, every file restored: {e}", file=sys.stderr)
        return 4
    if a.json:
        print(json.dumps({"action": plan.action, "subject": plan.subject, "paths": paths, **plan.info},
                         ensure_ascii=False))
    else:
        if plan.subject:
            print(plan.subject)
        for p in paths:
            print(p)
        for r in plan.info.get("refused", []):
            print(f"{r['id']}: kept: {r['why']}", file=sys.stderr)
        for r in plan.info.get("item_notes", []):
            print(f"{r['id']}: ℹ {r['note']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
