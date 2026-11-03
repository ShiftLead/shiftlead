# ledgerboard v2.3 sha256:9f6025cbc9757f6529b230ad78ee7e816b53dec470212dad60e63dcb6207d7fc
# SYNCED FILE — canonical copy: ShiftLead/ledgerboard ledgerboard/board.py (vendored by agent-cadence as files/scripts/ledgerboard/board.py)
# Edit it there and release; an edit made in a consumer's copy is overwritten by the next vendor or sync.
"""The board and rank writer: the module's board edits, read from and written to files (SPEC *The board writer*).

    python3 -m ledgerboard.board list    --board PATH [--today D]
    python3 -m ledgerboard.board add     --board PATH --text T [--due D] [--context C] [--kind K]
                                         [--answer A]... [--default N] [--lift A]... [--detail JSON]
                                         [--session S [--host H]] [--said WORDS --by NAME]
                                         [--decided WORDS [--by NAME]] [--under HEADING]
    python3 -m ledgerboard.board snooze  --board PATH --line N --expect HEAD --to D   (hide until D)
    python3 -m ledgerboard.board due     --board PATH --line N --expect HEAD --to D   (move Due: to D)
    python3 -m ledgerboard.board done    --board PATH --line N --expect HEAD [--why TEXT]
    python3 -m ledgerboard.board decide  --board PATH --line N --expect HEAD --answer TEXT [--by NAME]
    python3 -m ledgerboard.board reply   --board PATH --line N --expect HEAD --text TEXT --by NAME
    python3 -m ledgerboard.board archive --board PATH --archive PATH
    python3 -m ledgerboard.board fmt     --board PATH
    python3 -m ledgerboard.board rank    --rank PATH --action rank|join|prune [--set TD-n=KEY]... [--drop TD-n]...
    python3 -m ledgerboard.board rank    --rank PATH --action respace --ledger PATH [--fixed KEY]... [--repo NAME]
        [--tool NAME] [--session NAME] [--today D] [--plan] [--json]

Every write reads its files, applies the module's edit (``edit_line``, ``item_line``, ``decided_line``,
``archive_closed``, ``canonical_item``, ``set_rank``), and writes the files back, both or neither. It
prints the commit subject the module gives and the paths it changed (``--json``: one object);
``--plan`` prints the changes as JSON (each path with its new text) and writes nothing. It never runs
git, the network or anything of a consumer's: the caller passes who replies or answers (``--by``), the date
(``--today``, default the local clock) and the tool and session the subject names, and makes the
commit itself.

Exit: 0 written (or nothing to change); 1 a write failed (every file restored); 2 usage; 3 refused.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from . import (
    ITEM_RE,
    QUEUE_ACTIONS,
    Refused,
    archive_closed,
    archive_subject,
    board_people,
    board_problems,
    canonical_item,
    closed_items,
    decided_line,
    edit_line,
    is_item,
    is_person,
    item_line,
    item_record,
    load,
    parse_board,
    people_problems,
    queue_subject,
    respace,
    set_rank,
    subject,
    version_problem,
)

ACTIONS = ("list", "add", "snooze", "due", "done", "decide", "reply", "archive", "fmt", "rank")
EDITS = ("snooze", "due", "done", "decide", "reply")
TOOL = "ledgerboard"
NEEDS = "## Needs the user"  # where an add goes by default (cadence's board convention), a heading's words


@dataclass
class Plan:
    """A write, built and not yet made: each path's new text, the commit subject, and what the action reports."""

    action: str
    subject: str | None
    changes: dict[str, str] = field(default_factory=dict)
    info: dict = field(default_factory=dict)

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


def write(changes: Mapping[str, str]) -> list[str]:
    """Write every path's new text, both or neither: each to a temporary file beside it, then each renamed
    into place; when a rename fails, the files already replaced are put back and OSError is raised."""
    temps: list[tuple[str, str]] = []
    try:
        for path, text in changes.items():
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
        olds: dict[str, bytes | None] = {}
        for p in changes:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    olds[p] = f.read()
            else:
                olds[p] = None
        done: list[str] = []
        try:
            for path, tmp in temps:
                os.replace(tmp, path)
                done.append(path)
        except OSError:
            for path in done:
                if olds[path] is None:
                    os.unlink(path)
                else:
                    with open(path, "wb") as f:
                        f.write(olds[path])
            raise
    finally:
        for _, tmp in temps:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return list(changes)


# -- the actions, each a Plan ---------------------------------------------------------------------------

def _today(today: str | date | None) -> date:
    if today is None:
        return date.today()  # noqa: DTZ011  # the board's dates are the local clock's (target design §1.1)
    if isinstance(today, date):
        return today
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise Refused(f"--today is YYYY-MM-DD, not {today!r}")
    try:
        return date.fromisoformat(today)
    except ValueError:
        raise Refused(f"--today {today} is not a date") from None


def items(board: str, today: str | date | None = None) -> list[dict]:
    """Every open item's record (``item_record()``) at `today`, in board order."""
    return [item_record(i, _today(today)) for i in parse_board(read(board), warn=False)]


def _under(lines: list[str], heading: str | None) -> int:
    """Where an add goes: above the first item of the section `heading` opens (a line whose words begin
    with the heading's), or right under the heading and its blank lines when that section holds none;
    with no such heading, above the board's first item; with no item, at the end."""
    want = heading.split() if heading else []
    head = next((i for i, ln in enumerate(lines) if want and ln.split()[:len(want)] == want), None)
    if head is None:
        return next((i for i, ln in enumerate(lines) if is_item(ln)), len(lines))
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    first = next((i for i in range(head + 1, end) if is_item(lines[i])), None)
    if first is not None:
        return first
    at = head + 1
    while at < end and not lines[at].strip():
        at += 1
    return at


def _gate(path: str, old: str, new: str) -> None:
    """Refused when the write adds an open line the writers would not write (``board_problems()``); its
    notes (``ℹ``, a board with no ``People:``) are no fault."""
    bad = [(n, why) for n, why in board_problems(new, old) if not why.startswith("ℹ")]
    if bad:
        raise Refused(f"{path}: " + "; ".join(f"line {n}: {why}" for n, why in bad))


def who_answered(board_text: str, by: str | None) -> str:
    """Who gave an answer on this board (v2.3, target design §6.2): on a board whose ``People:`` lists one
    name, `by` defaults to it; otherwise `by` is required. A `by` off the ``People:`` list (compared
    case-insensitively) is refused, and one on it is written as ``People:`` spells it. On a board with no
    ``People:`` line, `by` is checked against the person grammar only. A ``People:`` line the gate faults
    (``people_problems()``) refuses every answer: nobody can be checked against it."""
    by = " ".join((by or "").split()) or None
    people = board_people(board_text)
    if people is None:
        if by is None:
            raise Refused("this board has no People: line, so an answer needs --by, who gave it")
        if not is_person(by):
            raise Refused(f"--by {by!r} is not a person's name (letters, digits, `_`, `-`, dot-separated)")
        return by
    bad = [why for _, why in people_problems(board_text) if not why.startswith("ℹ")]
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


def plan_add(board: str, text: str, *, due: str | None = None, context: str | None = None,
             kind: str | None = None, answers: Sequence[str] | None = None, default: int | None = None,
             detail: Mapping | None = None, session: str | None = None, host: str | None = None,
             decided: str | None = None, said: str | None = None, by: str | None = None,
             under: str | None = NEEDS, today: str | date | None = None, tool: str = TOOL,
             hide_until: str | None = None, lifts: Sequence[str] | None = None) -> Plan:
    """A new item at the top of the section `under` names (``item_line()``); with `said`, a question that
    was already answered, `by` and its words following the text as ` — <by>, <today>: <said>` (the
    subject keeps them out); with `decided`, an item already decided by the person (``decided_line()``:
    `text` its title, `context` its ref, `by` who answered, as ``who_answered()`` resolves it)."""
    day = _today(today).isoformat()
    bare = None
    if decided is not None:
        if any(v is not None for v in (due, kind, detail, session, host, said, hide_until, lifts)):
            raise Refused("a decided item takes its title, context, answers, default, words and who gave them alone")
        new = decided_line(text, context or "", list(answers or []), default, decided, day,
                           by=who_answered(read(board), by))
    else:
        words = text
        if said is not None or by is not None:
            said_words = " ".join(str(said or "").split())
            if not said_words or not (by and by.strip()):
                raise Refused("an answered item needs both --said, the answer's words, and --by, who said it")
            words = " ".join(str(text or "").split()).rstrip(".") + f" — {' '.join(by.split())}, {day}: {said_words}"
        def compose(t: str) -> str:
            return item_line(t, due, day, session, host, context, kind=kind,
                             answers=list(answers) if answers is not None else None, default=default, detail=detail,
                             hide_until=hide_until, lifts=list(lifts) if lifts is not None else None)

        new = compose(words)
        if said is not None:
            bare = compose(text)
    old = read(board)
    lines = old.splitlines(keepends=True)
    nl = "\r\n" if "\r\n" in old else "\n"
    if nl != "\n":
        new = new.replace("\n", nl)
    at = _under(lines, under)
    if lines and not lines[-1].endswith("\n") and at == len(lines):
        lines[-1] += nl
    lines.insert(at, new)
    out = "".join(lines)
    _gate(board, old, out)
    first = (bare or new).split("\n", 1)[0].rstrip("\r")  # a person's words stay on the board, never in the subject
    msg = subject(tool, "append", ITEM_RE.match(first).group("text"))
    return Plan("add", msg, {board: out}, {"line": at + 1})


def _find(lines: list[str], line: int, expect: str) -> tuple[str, str]:
    """(body, line ending) of open item `line` (1-based), Refused when it is not one or no longer starts with `expect`."""
    if not expect or not expect.strip():
        raise Refused("--expect is empty: pass the item's text as it was last shown")
    if not 1 <= line <= len(lines):
        raise Refused(f"line {line} is outside the board ({len(lines)} lines)")
    raw = lines[line - 1]
    body = raw.rstrip("\r\n")
    m = ITEM_RE.match(body)
    if not m:
        raise Refused(f"line {line} is not an open item: {body[:80]!r}")
    exp = expect.strip()
    if not (m.group("text").strip().startswith(exp) or body.lstrip().startswith(exp)):
        raise Refused(f"line {line} no longer starts with the expected item (the board moved; read it again). "
                      f"Line {line} is: {body[:80]!r}")
    return body, raw[len(body):]


def plan_edit(board: str, action: str, line: int, expect: str, *, to: str | None = None,
              why: str | None = None, answer: str | None = None, text: str | None = None,
              by: str | None = None, today: str | date | None = None, tool: str = TOOL,
              session: str | None = None) -> Plan:
    """One of the five edits (``edit_line()``) of open item `line`, which must still start with `expect`; a
    decide's `by`, who answered, as ``who_answered()`` resolves it."""
    if action not in EDITS:
        raise Refused(f"an edit is one of {', '.join(EDITS)}, not {action!r}")
    day = _today(today)
    when = None
    if action in ("snooze", "due"):
        if not to:
            raise Refused(f"a {action} needs --to")
        when = _today(to)
    if action == "reply" and not (by and by.strip()):
        raise Refused("a reply needs --by, who says it")
    old = read(board)
    lines = old.splitlines(keepends=True)
    body, eol = _find(lines, line, expect)
    if action == "decide":
        by = who_answered(old, by)
    new = edit_line(body, action, to=when, answer=answer, why=why, reply=text, by=by, today=day)
    lines[line - 1] = new + eol
    msg = subject(tool, action, ITEM_RE.match(body).group("text").strip(),
                  to=when, answer=answer, session=session)
    return Plan(action, msg, {board: "".join(lines)}, {"line": line})


def plan_archive(board: str, archive: str, *, tool: str = TOOL, session: str | None = None) -> Plan:
    """Every closed item, with its detail block and any open twin, moved to the archive's end (``archive_closed()``)."""
    if os.path.abspath(board) == os.path.abspath(archive):
        raise Refused("the board and its archive are one file")
    old = read(board)
    arch = read(archive, missing_ok=True)
    count = len(closed_items(old))
    new_board, new_arch = archive_closed(old, arch)
    # the archive is written first: a crash between the renames leaves an item twice, never nowhere
    return Plan("archive", archive_subject(tool, count, session), {archive: new_arch, board: new_board},
                {"moved": count})


def plan_fmt(board: str) -> Plan:
    """Every open item line at column 0 rewritten into the writers' form where ``canonical_item()`` can do it
    without changing its key; the lines it cannot are reported, each with why, and kept as they are.
    A format pass has no commit subject of its own: the caller names its commit."""
    old = read(board)
    lines = old.splitlines(keepends=True)
    fixed, refused = [], []
    for n, ln in enumerate(lines, 1):
        if not ln.startswith("- [ ]"):
            continue
        try:
            new = canonical_item(ln)
        except Refused as e:
            refused.append({"line": n, "why": str(e)})
            continue
        if new != ln:
            lines[n - 1] = new
            fixed.append(n)
    out = "".join(lines)
    return Plan("fmt", None, {board: out} if fixed else {}, {"fixed": fixed, "refused": refused})


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


def build(a: argparse.Namespace) -> Plan:
    if a.action == "add":
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
                        host=a.host, decided=a.decided, said=a.said, by=a.by, under=a.under,
                        today=a.today, tool=a.tool)
    if a.action in EDITS:
        if a.action == "decide" and len(a.answer) != 1:
            raise Refused("decide takes one --answer, the person's")
        answer = a.answer[0] if a.action == "decide" else None
        return plan_edit(a.board, a.action, a.line, a.expect, to=a.to, why=a.why, answer=answer,
                         text=a.text, by=a.by, today=a.today, tool=a.tool, session=a.session)
    if a.action == "archive":
        return plan_archive(a.board, a.archive, tool=a.tool, session=a.session)
    if a.action == "fmt":
        return plan_fmt(a.board)
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
    "add": {"board", "text", "due", "context", "kind", "answer", "default", "detail", "session", "host",
            "decided", "said", "by", "under", "today", "tool", "hide_until", "lift"},
    "snooze": {"board", "line", "expect", "to", "today", "tool", "session"},
    "due": {"board", "line", "expect", "to", "today", "tool", "session"},
    "done": {"board", "line", "expect", "why", "today", "tool", "session"},
    "decide": {"board", "line", "expect", "answer", "by", "today", "tool", "session"},
    "reply": {"board", "line", "expect", "text", "by", "today", "tool", "session"},
    "archive": {"board", "archive", "tool", "session"},
    "fmt": {"board"},
    "rank": {"rank", "queue", "set", "drop", "tool", "ledger", "fixed", "repo"},
}
NEEDS_OPT = {
    "list": ("board",), "add": ("board", "text"), "snooze": ("board", "line", "expect", "to"),
    "due": ("board", "line", "expect", "to"),
    "done": ("board", "line", "expect"), "decide": ("board", "line", "expect", "answer"),
    "reply": ("board", "line", "expect", "text", "by"), "archive": ("board", "archive"),
    "fmt": ("board",), "rank": ("rank", "queue"),
}
DEFAULTS = {"under": NEEDS, "tool": TOOL, "answer": [], "lift": [], "set": [], "drop": [], "fixed": []}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ledgerboard.board", description=__doc__.split("\n", 1)[0])
    ap.add_argument("action", choices=ACTIONS)
    ap.add_argument("--board", help="the board file")
    ap.add_argument("--archive", help="archive: the board's archive file (created when missing)")
    ap.add_argument("--rank", help="rank: the rank file (created when missing)")
    ap.add_argument("--action", dest="queue", help="rank: rank, join, prune or respace")
    ap.add_argument("--set", action="append", default=[], help="rank: TD-n=KEY, a line to set")
    ap.add_argument("--drop", action="append", default=[], help="rank: TD-n, a line to remove")
    ap.add_argument("--ledger", help="rank --action respace: the ledger (a file or a v2 directory)")
    ap.add_argument("--fixed", action="append", default=[],
                    help="rank --action respace: another repo's key sorted beside this file's (repeat)")
    ap.add_argument("--repo", help="rank --action respace: the last component of this repo's implicit keys")
    ap.add_argument("--line", type=int, help="an edit: the item's 1-based line")
    ap.add_argument("--expect", help="an edit: the start of the item's text as last shown")
    ap.add_argument("--to", help="snooze: the Hide until: date; due: the new Due: date")
    ap.add_argument("--why", help="done: why, for the Closed: field")
    ap.add_argument("--answer", action="append", default=[],
                    help="decide: the person's answer; add: one of the item's answers (repeat)")
    ap.add_argument("--lift", action="append", default=[],
                    help="add: a decide's answer that lifts its gate (repeat; none means Go)")
    ap.add_argument("--text", help="add: the item's text; reply: the reply's words")
    ap.add_argument("--by", help="reply, add --said: who says it; decide, add --decided: who answered (the one name "
                    "on the board's People: when it lists one)")
    ap.add_argument("--said", help="add: the answer already given, which follows the text on the line")
    ap.add_argument("--due", help="add: the item's Due: date")
    ap.add_argument("--hide-until", dest="hide_until", help="add: hide the new item until this date")
    ap.add_argument("--context", help="add: what the item refers to (TD-n, PR #n)")
    ap.add_argument("--kind", help="add: decide, act, look, watch or fyi")
    ap.add_argument("--default", type=int, help="add: the 0-based index of the default answer")
    ap.add_argument("--detail", help="add: the detail block's parts, a JSON object")
    ap.add_argument("--host", help="add: the host the item's session runs on")
    ap.add_argument("--decided", help="add: the person's words, for an item already decided")
    ap.add_argument("--under", default=NEEDS, help=f"add: the heading whose section takes the item ({NEEDS!r})")
    ap.add_argument("--session", help="add: the item's session; an edit or archive: the session the subject names")
    ap.add_argument("--tool", default=TOOL, help="the tool the commit subject names")
    ap.add_argument("--today", help="the date the write records, YYYY-MM-DD (default: the local clock)")
    ap.add_argument("--plan", action="store_true", help="print the changes as JSON and write nothing")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    a = ap.parse_args(argv)
    given = {k for k, v in vars(a).items()
             if k not in ("action", "plan", "json") and v is not None and v != DEFAULTS.get(k)}
    extra = sorted(given - TAKES[a.action])
    if extra:
        ap.error(f"{a.action} does not take {', '.join('--' + e for e in extra)}")
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
                    print(f"{r['line']}\t{r['due_tag'] or '-'}\t{r['text']}")
            return 0
        plan = build(a)
    except Refused as e:
        if a.json or a.plan:
            print(json.dumps({"action": a.action, "refused": str(e)}, ensure_ascii=False))
        else:
            print(f"ledgerboard.board: refused: {e}", file=sys.stderr)
        return 3
    if a.plan:
        print(json.dumps(plan.as_json(), ensure_ascii=False))
        return 0
    try:
        paths = apply(plan)
    except OSError as e:
        print(f"ledgerboard.board: the write failed, every file restored: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps({"action": plan.action, "subject": plan.subject, "paths": paths, **plan.info},
                         ensure_ascii=False))
    else:
        if plan.subject:
            print(plan.subject)
        for p in paths:
            print(p)
        for r in plan.info.get("refused", []):
            print(f"line {r['line']}: kept: {r['why']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
