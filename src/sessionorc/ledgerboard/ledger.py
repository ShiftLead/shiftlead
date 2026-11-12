# ledgerboard v2.7 sha256:a027e395cd516cdc674ff4a1718aa6463c66e96f576cf77df9e37157cd95653c
# SYNCED FILE — canonical copy: ShiftLead/ledgerboard ledgerboard/ledger.py (vendored by agent-cadence as files/scripts/ledgerboard/ledger.py)
# Edit it there and release; an edit made in a consumer's copy is overwritten by the next vendor or sync.
"""The ledger writer: the module's ledger edits, read from and written to files (SPEC *The ledger writer*).

    python3 -m ledgerboard.ledger --pickable | --list | --counts F[,F] | --fields | --summary | --check
                                  [--ledger PATH] [--archive PATH] [--base PATH] [--where F=V]...
                                  [--type T] [--owner O] [--kind K] [--pickable yes|no]
    python3 -m ledgerboard.ledger fmt  [TD-n ...] [--check]
    python3 -m ledgerboard.ledger new  --id TD-n --title T --priority P --why FILE|- [--fix FILE|-]
                                       [--done-when FILE|-] [--type ...] [--added D] [--owner O] [--kind K]
                                       [--status S] [--blocked-by B] [--part-of TD-n] [--location L]
                                       [--field NAME=VALUE]... [--take NONCE]
                                       [--by WHO --session S --words W [--while ID]]
    python3 -m ledgerboard.ledger set  TD-n --FIELD VALUE ... [--field NAME=VALUE]...
                                       [--by WHO [--answer L] [--board R | --no-board-item | --shared-item]
                                        | --by WHO --override WHY | --by WHO --why W]
    python3 -m ledgerboard.ledger split [--archive FILE] [--to DIR] [--also FILE...]
    python3 -m ledgerboard.ledger relink FILE... [--was FILE]
    python3 -m ledgerboard.ledger lift TD-n --gate G --by WHO [--answer L] [--evidence E]
                                       [--board R | --no-board-item | --shared-item] [--people P,...]
                                       [--answered-by owner|any]
    python3 -m ledgerboard.ledger note TD-n "words"
    python3 -m ledgerboard.ledger edit TD-n --section NAME --from FILE|-
    python3 -m ledgerboard.ledger archive TD-n --why W [--pr N] [--pointer P] [--as-is]
                                          [--superseded-by ID | --dropped] [--also FILE...]
    python3 -m ledgerboard.ledger reopen TD-n --why W [--also FILE...]
    python3 -m ledgerboard.ledger renumber TD-n --id TD-m [--take NONCE] [--also FILE...]
    python3 -m ledgerboard.ledger migrate [TD-n ...] --release X.Y [--closed-dates FILE] [--stage-kind WORD=KIND]...
                                          [--as TD-n=FORM]... [--plan | --dry-run] [--ledger DIR] [--today D] [--json]
        every command: [--ledger PATH] [--resolved FILE] [--today D] [--json]; a write: [--base PATH] [--plan]

A report reads a v1 ledger file or a v2 directory through ``load()``; a write takes a v2 directory and
refuses a v1 file (*split first*). Every write reads the files, applies the module's edit
(``entry_text()``, ``edit_entry()``, ``canonical()``) and writes the files back, both or neither, then
prints the paths it changed (``--json``: one object; a ledger edit has no commit subject of its own, so
``subject`` is null — except ``migrate``'s, which names ``migrate_subject()``). ``--plan`` prints the changes as JSON (a removed file's text null) and writes nothing.
A move (``archive``, ``reopen``, ``renumber``) writes the new file and removes the old, its relative links
rewritten for its new directory and every link to it, in the ledger and in ``--also``'s files, repointed.

A write is refused when the ledger after it has a ``check()`` error the ledger before it does not, both
checked against one base: ``--base`` (the ledger where the change started, a v1 file or a v2 directory,
as the caller reads it from its default branch), else the ledger as it stands. So a fault already there
never blocks an unrelated write. ``cross-repo`` and every ℹ the write brings are notes, never refusals.
``migrate`` (v2.7) is the exception: it writes the ledger ``check()`` will grade, is refused only by a stop of
``migrate_entry()``, takes neither ``--base`` nor ``--resolved``, and the caller runs ``--check`` on the result.

It never runs git, the network or anything of a consumer's. The caller passes what lies outside the
files: the entry's id (``new --id``, taken from its counter), who filed it (``--by``, ``--session``), the
date (``--today``, else the UTC clock) and the state of other repos' entries (``--resolved``, a JSON object
from ``<repo>#TD-n`` to ``{"state": "open" | "archived" | "unresolved", "status", "successor", "why"}``).
An id the run needs that the file does not hold stops it: exit 3, ``needs: <ids>`` (``--json``: ``needs``),
nothing written — resolve them and run again with ``--resolved``.

Exit: 0 written, or nothing to change (``--check``: no error stands); 1 refused (``--check``: an error
stands; ``fmt``: an entry refused, or under ``--check`` one would change); 2 usage, or the ledger or an id
in it cannot be used as asked; 3 ``needs``; 4 a write failed, every file restored.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone

from . import (
    CADENCE_FIELDS,
    ENTRY_FILE_RE,
    ID_ITEM_RE,
    LEDGER_ARCHIVE,
    MIGRATE_DECIDED_RE,
    STAGE_WORDS,
    XREPO_ITEM_RE,
    Refused,
    Resolve,
    _archived_status,
    _chain,
    _left_with_open_parts,
    _num,
    _real_day,
    archive_path,
    archive_plan,
    canonical,
    check,
    edit_entry,
    entries,
    entry_path,
    entry_text,
    field_key,
    first_word,
    heading_nums,
    lift_gate,
    load,
    migrate_entry,
    migrate_subject,
    parse_gates,
    pickable,
    rank,
    rank_path,
    reassign_gate,
    set_rank,
    split,
    utc_day,
    v2_problems,
    version_problem,
)
from .board import Plan, write

LEDGER_DIR, LEDGER_FILE = "docs/ledger", "docs/technical_debt.md"  # the defaults, relative to the working directory
ALIASES = ("type", "owner", "kind")  # --type X is --where type=X, and so on
WRITES = ("fmt", "new", "set", "note", "edit", "archive", "reopen", "renumber", "lift", "split", "relink", "migrate")
RELEASE_RE = re.compile(r"[0-9]{1,9}\.[0-9]{1,9}")  # migrate's --release: migrate_subject()'s major.minor
# `new`'s and `set`'s header flags, in the canonical order: (option dest, field name)
FIELDS = (("priority", "Priority"), ("type", "Type"), ("added", "Added"), ("owner", "Owner"), ("kind", "Kind"),
          ("status", "Status"), ("blocked_by", "Blocked by"), ("part_of", "Part of"), ("location", "Location"))


class Unusable(Refused):
    """The ledger, or an id in it, cannot be used as asked (exit 2): a v1 file for a write, an id in neither
    directory, an archived entry, a ledger that cannot be read or declares a newer major."""


class Needs(Exception):
    """The run needs other repos' entries the caller has not resolved (exit 3)."""

    def __init__(self, ids: Sequence[str]) -> None:
        super().__init__(", ".join(ids))
        self.ids = list(ids)


# -- files --------------------------------------------------------------------------------------------

def _join(path: str, name: str) -> str:
    return f"{path.rstrip('/')}/{name}" if path else name


def _read_raw(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
            return f.read()
    except OSError as e:
        raise Unusable(f"{path}: cannot be read: {e}") from None


class Ledger:
    """A ledger's files in memory, keyed by path: a v2 directory's ``README.md``, entry files, ``archive/``
    entry files and ``rank.yml``, or a v1 file, its archive and its rank file. ``ls``/``read`` serve
    ``load()``; ``overlay()`` is the same ledger with some files written (a text) or removed (None)."""

    def __init__(self, path: str, files: Mapping[str, str], v2: bool, archive: str | None = None) -> None:
        self.path, self.files, self.v2, self.archive = path, dict(files), v2, archive

    @classmethod
    def open(cls, path: str, archive: str | None = None) -> Ledger:
        """The ledger at ``path``: a v2 directory, or a v1 file with ``archive`` (default: the one beside it)."""
        if os.path.isdir(path):
            if archive is not None:
                raise Unusable("--archive is a v1 ledger's; a v2 directory holds its archive/")
            files = {}
            for d in (path, _join(path, LEDGER_ARCHIVE)):
                if os.path.isdir(d):
                    try:
                        names = sorted(os.listdir(d))
                    except OSError as e:
                        raise Unusable(f"{d}: cannot be listed: {e}") from None
                    for n in names:
                        p = _join(d, n)
                        if os.path.isfile(p):
                            files[p] = _read_raw(p)
            led = cls(path, files, True)
            why = "; ".join(v2_problems(path, led.ls, led.read))
            if why:
                raise Unusable(f"{path}: not read — {why}")
        elif os.path.isfile(path):
            arch = archive or (path[:-3] + "_archive.md" if path.endswith(".md") else path + "_archive.md")
            files = {path: _read_raw(path)}
            for p in (arch, rank_path(path)):
                if os.path.isfile(p):
                    files[p] = _read_raw(p)
            led = cls(path, files, False, arch)
        else:
            raise Unusable(f"{path}: no such ledger")
        for p, why in ((p, version_problem(t)) for p, t in led.files.items()):
            if why:
                raise Unusable(f"{p}: not read — {why}")
        return led

    def ls(self, path: str) -> list[str] | None:
        d = os.path.normpath(path)
        names = sorted(os.path.basename(p) for p in self.files if os.path.normpath(os.path.dirname(p)) == d)
        if not self.v2:
            return None
        if names or d == os.path.normpath(self.path):
            return names
        return None

    def read(self, path: str) -> str | None:
        text = self.files.get(path)
        if text is None:
            text = next((t for p, t in self.files.items() if os.path.normpath(p) == os.path.normpath(path)), None)
        return None if text is None else text.replace("\r\n", "\n").replace("\r", "\n")

    def texts(self) -> tuple[str, str]:
        """(ledger text, archive text), as ``load()`` reads them."""
        if self.v2:
            return load(self.path, self.ls, self.read)
        return self.read(self.path) or "", self.read(self.archive) or ""

    def rank(self) -> str | None:
        return self.read(rank_path(self.path))

    def overlay(self, changes: Mapping[str, str | None]) -> Ledger:
        files = dict(self.files)
        for p, t in changes.items():
            if t is None:
                files.pop(p, None)
            else:
                files[p] = t
        return Ledger(self.path, files, self.v2, self.archive)

    def entry_file(self, tid: str) -> tuple[str, bool]:
        """(the file holding ``tid``, whether it is archived); Unusable when it is in neither directory."""
        found = entry_path(self.path, tid, self.ls)
        if found is None:
            raise Unusable(f"{tid} is in neither {self.path} nor its archive")
        arch = os.path.normpath(os.path.dirname(found)) == os.path.normpath(_join(self.path, LEDGER_ARCHIVE))
        return found, arch


def _today(today: str | date | datetime | None) -> str:
    """A ledger date (the UTC date): ``today`` as given, else the UTC clock's."""
    if today is None:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return utc_day(today, "--today")
    except Refused as e:
        raise Unusable(str(e)) from None


def tid_of(tid: str) -> str:
    """An id at the ledger's width, ``TD-`` and at least three digits (``TD-3`` is ``TD-003``)."""
    if not ID_ITEM_RE.match(tid or "") or int(tid[3:]) < 1:
        raise Unusable(f"an entry's id is TD-n, n from 1, not {tid!r}")
    return f"TD-{int(tid[3:]):03d}"


# -- links ---------------------------------------------------------------------------------------------

# An inline link's destination (bare, or <in brackets>) and its title ("…", '…' or (…)), kept as written;
# and a reference definition's destination.
LINK_RE = re.compile(r"(\]\()(<[^<>\n]*>|[^)\s<]+)((?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?[ \t]*\))")
REF_DEF_RE = re.compile(r"^( {0,3}\[[^\]\n]+\]:[ \t]*)(<[^<>\n]*>|\S+)()", re.MULTILINE)
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")  # a fenced code block's opening or closing line, a list item's too
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Where ``text`` is code, not prose: each inline span and each fenced block (to the end when unclosed)."""
    spans = [m.span() for m in CODE_SPAN_RE.finditer(text)]
    at, opened = 0, None
    for line in text.splitlines(keepends=True):
        m = FENCE_RE.match(line)
        if m and opened is None:
            opened = (at, m.group(1))
        elif m and opened is not None and m.group(1)[0] == opened[1][0] and len(m.group(1)) >= len(opened[1]) \
                and not line[m.end():].strip():
            spans.append((opened[0], at + len(line)))
            opened = None
        at += len(line)
    if opened is not None:
        spans.append((opened[0], len(text)))
    return spans


ANCHOR_RE = re.compile(r"td-0*(\d+)(?:-|$)", re.IGNORECASE)  # an entry heading's slug: `## TD-21: x` is #td-21-x


def relink(text: str, src: str, dst: str, moved: Mapping[str, str] | None = None, *,
           gone: Mapping[str, str] | None = None, targets: Mapping[int, str] | None = None,
           here: str | None = None, warns: list[str] | None = None) -> str:
    """``text``'s relative links (inline, ``](path)`` or ``](<path>)`` with any title, and reference
    definitions, ``[ref]: path``), written from directory ``src``, rewritten to resolve from directory ``dst``,
    and a link to a file in ``moved`` (old path → new path) pointed at its new path; its anchor and title
    kept. A URL, an absolute path, a plain anchor and a link inside a code span or a fenced block are left (an
    indented code block is not told from prose), and so is every link when ``src`` is ``dst`` and nothing it
    names moved.

    A split's links: ``gone`` maps each v1 file the split removes to the directory replacing it, and
    ``targets`` each entry's number to its new file. A link into a gone file whose anchor is an entry
    heading's slug (``#td-21-…``) points at that entry's file, as does a bare ``#td-…`` anchor in a text that
    came from the gone file ``here``; one with no anchor points at the directory; any other anchor into a gone
    file is left, and said in ``warns``. Pure: paths are compared as text, so a link that named no file
    before names none after."""
    spans = _code_spans(text)
    moved = {os.path.abspath(k): os.path.abspath(v) for k, v in (moved or {}).items()}
    gone = {os.path.abspath(k): os.path.abspath(v) for k, v in (gone or {}).items()}
    targets = {n: os.path.abspath(v) for n, v in (targets or {}).items()}
    here = os.path.abspath(here) if here else None
    src_a, dst_a = os.path.abspath(src or "."), os.path.abspath(dst or ".")

    def rel(to: str, slash: bool) -> str:
        return os.path.relpath(to, dst_a).replace(os.sep, "/") + ("/" if slash else "")

    def fix(m: re.Match) -> str:
        target = m.group(2)
        bracketed = target.startswith("<")
        path, hash_, frag = (target[1:-1] if bracketed else target).partition("#")
        wrap = (lambda d: f"{m.group(1)}{f'<{d}>' if bracketed else d}{m.group(3)}")  # noqa: E731
        if URL_RE.match(path) or path.startswith("/") or any(a <= m.start() < b for a, b in spans):
            return m.group(0)
        old = os.path.normpath(os.path.join(src_a, path)) if path else here
        if old is None:
            return m.group(0)
        if old in gone:
            a = ANCHOR_RE.match(frag)
            if hash_ and a and int(a.group(1)) in targets:
                return wrap(rel(targets[int(a.group(1))], False))
            if not hash_:
                return wrap(rel(gone[old], True))
            if warns is not None:
                warns.append(f"{target}: an anchor into {os.path.basename(old)}, which the split removes — point it "
                             "at the entry's file by hand" + ("" if path else f" (in a text from {os.path.basename(old)})"))
            return m.group(0)
        if not path:
            return m.group(0)
        new = moved.get(old, old)
        if new == old and src_a == dst_a:
            return m.group(0)
        return wrap(f"{rel(new, path.endswith('/'))}{hash_}{frag}")

    return REF_DEF_RE.sub(fix, LINK_RE.sub(fix, text))


# -- the resolver --------------------------------------------------------------------------------------

class Resolved:
    """A resolver over the caller's answers (``--resolved``): an id it holds is answered; one it does not is
    recorded in ``needs`` and read as unresolved for this run, which then stops with exit 3."""

    def __init__(self, answers: Mapping[str, Mapping] | None = None) -> None:
        self.answers = {k.lower(): v for k, v in (answers or {}).items()}
        self.needs: list[str] = []

    def __call__(self, item: str) -> dict:
        got = self.answers.get(item.lower())
        if got is not None:
            return dict(got)
        if item not in self.needs:
            self.needs.append(item)
        return {"state": "unresolved", "why": "not resolved yet"}

    @classmethod
    def from_file(cls, path: str | None) -> Resolved:
        if path is None:
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise Unusable(f"--resolved {path}: not a JSON file: {e}") from None
        if not isinstance(data, dict) or not all(
                isinstance(k, str) and XREPO_ITEM_RE.match(k) and isinstance(v, dict) and isinstance(v.get("state"), str)
                for k, v in data.items()):
            raise Unusable(f"--resolved {path}: an object from <repo>#TD-n to {{\"state\": …}}")
        return cls(data)


# -- the gate ------------------------------------------------------------------------------------------

def _flags(led: Ledger, old: str | None, resolve: Resolve | None, today: str) -> list[dict]:
    text, arch = led.texts()
    return check(text, arch, old, resolve, led.rank(), today=today)


def _same(r: dict) -> tuple:
    """A flag as the gate compares it: its kind, entry and words, without its ⚠ or ℹ mark, which ``check()``
    sets by whether the entry changed — so a fault already on the entry a write edits is the same fault."""
    return r["kind"], r["id"], r["text"].lstrip("⚠ℹ ")


def gate(led: Ledger, changes: Mapping[str, str | None], *, base: Ledger | None = None,
         resolve: Resolve | None = None, today: str | None = None) -> list[str]:
    """The two-level refusal: Refused naming each ``check()`` error the ledger after ``changes`` has that the
    ledger before them does not (``cross-repo`` aside), both checked against one ``old``, ``base``'s ledger
    text, else the ledger before the write. The notes the write brings (each new ℹ, and ``cross-repo``)
    are returned."""
    day = _today(today)
    old = (base or led).texts()[0]
    before = {_same(r) for r in _flags(led, old, resolve, day)}
    after = _flags(led.overlay(changes), old, resolve, day)
    new = [r for r in after if _same(r) not in before and not r.get("standing")]
    refuse = [r for r in new if r["level"] == "error" and r["kind"] != "cross-repo"]
    if refuse:
        raise Refused("; ".join(r["text"] for r in refuse))
    return [r["text"] for r in new if r not in refuse]


def _writable(led: Ledger) -> None:
    if not led.v2:
        raise Unusable(f"{led.path} is a v1 ledger: the writers write a v2 directory — split it first")


# -- the writes, each a Plan ---------------------------------------------------------------------------

def plan_new(led: Ledger, tid: str, title: str, fields: Sequence[tuple[str, str]],
             sections: Sequence[tuple[str, str]], *, take: str | None = None, filed: Mapping | None = None,
             base: Ledger | None = None, resolve: Resolve | None = None, today: str | None = None) -> Plan:
    """A new entry, ``<ledger>/TD-NNN.md`` (``entry_text()``): ``fields`` as (name, value) pairs, ``take`` the
    counter take's nonce (``Id take``), ``filed`` the Log's first line ({who, session, words, while}). The
    id is the caller's, from its counter, and is refused when the ledger or its archive holds it. Added
    defaults to today, Status to Open. A ``Location`` among ``fields`` is written as the ``**Location:**``
    body section after the Why (v2.7), never as a header field."""
    _writable(led)
    tid = tid_of(tid)
    text, arch = led.texts()
    files = {int(m.group(1)) for p in led.files if (m := ENTRY_FILE_RE.match(os.path.basename(p)))}
    if int(tid[3:]) in heading_nums(text) | heading_nums(arch) | files:
        raise Unusable(f"{tid} is in the ledger or its archive already")
    day = _today(today)
    if sum(field_key(n) == "location" for n, _ in fields) > 1:
        raise Unusable("a field is given twice: location")
    loc = [v for n, v in fields if field_key(n) == "location" and str(v or "").strip()]
    fields = [(n, v) for n, v in fields if field_key(n) != "location"]  # v2.7: a body section, not a header field
    given = {field_key(n) for n, _ in fields}
    out = list(fields)
    if "added" not in given:
        out.insert(0, ("Added", day))
    if "status" not in given:
        out.append(("Status", "Open"))
    if take is not None:
        if "id take" in given:
            raise Unusable("the take's nonce is given twice: --take and --field 'Id take=…'")
        out.append(("Id take", take))
    keys = [field_key(n) for n, _ in out]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise Unusable(f"a field is given twice: {', '.join(dup)}")
    if not sections or sections[0][0] != "Why" or not str(sections[0][1]).strip():
        raise Refused("an entry needs its Why: the Why is the point of an entry")
    if loc:  # after the Why and before every other section, where edit --section puts it
        sections = [sections[0], ("Location", str(loc[0]).strip()), *sections[1:]]
    entry = entry_text(tid, title, out, sections, filed=dict(filed, today=day) if filed is not None else None)
    path = _join(led.path, f"{tid}.md")
    notes = gate(led, {path: entry}, base=base, resolve=resolve, today=day)
    return Plan("new", None, {path: entry}, {"id": tid, "notes": notes})


def _open_entry(led: Ledger, tid: str, why: str = "it is edited only once reopened") -> tuple[str, str]:
    """(path, raw text) of open entry ``tid``; Unusable for one archived or in neither directory."""
    _writable(led)
    path, archived = led.entry_file(tid)
    if archived:
        raise Unusable(f"{tid} is archived ({path}): {why}")
    return path, led.files[path]


def _decisions(value: str | None) -> list[str]:
    """The ``decision (<person>)`` gates of a Blocked by value, as written."""
    return [f"decision ({p})" for p in parse_gates(value)["decisions"]]


def _gate_route(text: str, fields: Mapping[str, str], day: str, *, by: str | None, answer: str | None,
                suffix: str | None, override: str | None, why: str | None) -> str:
    """``text`` with the decisions ``set``'s Blocked by drops or swaps written as the module writes them, before
    the fields are set (SPEC *The ledger writer*, the set route): a decision removed is lifted (``lift_gate()``,
    ``by`` the gate's person and ``answer``, default ``Go``; or with ``override``, ``by`` anyone), and one
    decision replaced by another is reassigned (``reassign_gate()``, ``by`` and ``why``). Who may do either is
    the caller's to check; the writer records ``by``."""
    given = {k for k, v in (("--by", by), ("--answer", answer), ("a board flag", suffix), ("--override", override),
                            ("--why", why)) if v is not None}
    value = next((v for k, v in fields.items() if field_key(k) == "blocked by"), None)
    if value is None:
        if given:
            raise Unusable(f"{', '.join(sorted(given))}: set takes them only with --blocked-by that drops a decision")
        return text
    raw = entries(text)[0]["blocked_raw"]
    held = parse_gates(raw)["old_form"]
    if held and " ".join(f"decision ({held[0]})".split()).lower() not in {
            " ".join(g.split()).lower() for g in _decisions(value)}:
        raise Refused(f"the Blocked by holds decision ({held[0]}) in the old form, which set cannot lift or drop — "
                      f"migrate it first (decision ({held[0]}) with its text in **Ask:**), then lift it")
    was = _decisions(raw)
    now = {" ".join(g.split()).lower() for g in _decisions(value)}
    gone = [g for g in was if " ".join(g.split()).lower() not in now]
    added = [g for g in _decisions(value) if " ".join(g.split()).lower() not in {" ".join(x.split()).lower() for x in was}]
    if not gone:
        if given:
            raise Unusable(f"{', '.join(sorted(given))}: this Blocked by drops no decision")
        return text
    if by is None:
        raise Refused(f"removing {', '.join(gone)} through set needs --by <person>: the gate's person, who answered "
                      "(or --override with its why)")
    if added:
        if len(gone) != 1 or len(added) != 1:
            raise Unusable("a reassign replaces one decision by one other: set them one at a time")
        if answer is not None or suffix is not None or override is not None:
            raise Unusable("a reassign takes --by and --why, no --answer, board flag or --override")
        frm, to = parse_gates(gone[0])["decisions"][0], parse_gates(added[0])["decisions"][0]
        return reassign_gate(text, frm, to, by=by, why=why or "", today=day)
    if why is not None:
        raise Unusable("--why is a reassign's: a lift takes --answer, or --override with its why")
    for g in gone:
        if override is not None:
            if answer is not None or suffix is not None:
                raise Unusable("an override lift takes --by and its why, no --answer or board flag")
            text = lift_gate(text, g, by, override=override, today=day)
        else:
            text = lift_gate(text, g, by, answer=answer or "Go", suffix=suffix, today=day)
    return text


def plan_edit(led: Ledger, action: str, tid: str, *, fields: Mapping[str, str] | None = None,
              words: str | None = None, section: str | None = None, by: str | None = None,
              answer: str | None = None, suffix: str | None = None, override: str | None = None,
              why: str | None = None, base: Ledger | None = None, resolve: Resolve | None = None,
              today: str | None = None) -> Plan:
    """One edit of an open entry (``edit_entry()``): ``set`` (``fields``, an empty value removing one), ``note``
    (``words``, a dated Log line) or ``edit`` (``section`` replaced by ``words``). A ``set`` whose Blocked by
    drops a decision lifts it (``by``, ``answer``, ``suffix``, or ``override``) or, swapping it for another,
    reassigns it (``by``, ``why``): ``_gate_route()``."""
    if action not in ("set", "note", "edit"):
        raise Unusable(f"an entry edit is set, note or edit, not {action!r}")
    path, text = _open_entry(led, tid)
    day = _today(today)
    route = {"by": by, "answer": answer, "suffix": suffix, "override": override, "why": why}
    if action != "set" and any(v is not None for v in route.values()):
        raise Unusable(f"{action} takes no gate route: --by, --answer, --override and --why are set's")
    if action == "set":
        lifted = _gate_route(text, dict(fields or {}), day, **route)
        out = edit_entry(lifted, "set", fields=dict(fields or {}), today=day)  # v2.5: dates a gate it adds
    else:
        kw: dict = {"words": words} if action == "note" else {"section": section, "words": words}
        kw["today"] = day  # note's date; edit's (v2.5) only to date a host-log check it makes a new wait
        out = edit_entry(text, action, **kw)
    if out == text:
        return Plan(action, None, {}, {"id": entries(out)[0]["id"], "notes": []})
    notes = gate(led, {path: out}, base=base, resolve=resolve, today=day)
    return Plan(action, None, {path: out}, {"id": entries(out)[0]["id"], "notes": notes})


def plan_lift(led: Ledger, tid: str, gate_: str, by: str, *, answer: str | None = None, evidence: str | None = None,
              suffix: str | None = None, people: Sequence[str] | None = None, answered_by: str | None = None,
              base: Ledger | None = None, resolve: Resolve | None = None, today: str | None = None) -> Plan:
    """One gate lifted from open entry ``tid`` (``lift_gate()``, SPEC *Lifting a gate*): a decision by its person's
    ``answer`` (``suffix`` at most one of ``board <repo>``, ``no board item``, ``shared board item left open``;
    anyone on ``people`` with ``answered_by`` ``any``), an event by a person's ``answer`` (``by`` on ``people``) or a
    host's ``evidence``, or ``until`` with none of them. Its inputs match one shape exactly; the override and the
    reassign are ``set``'s."""
    path, text = _open_entry(led, tid)
    day = _today(today)
    out = lift_gate(text, gate_, by, answer=answer, evidence=evidence, suffix=suffix, today=day,
                    people=list(people) if people is not None else None, answered_by=answered_by)
    notes = gate(led, {path: out}, base=base, resolve=resolve, today=day)
    return Plan("lift", None, {path: out}, {"id": entries(out)[0]["id"], "notes": notes})


def _why(why: str | None) -> str:
    if not why or not why.strip():
        raise Unusable("--why is required: one line, why it moves")
    return why


def _also(also: Mapping[str, str] | None, led: Ledger) -> dict[str, str]:
    """The caller's other files (``--also``), each path and its text; one inside the ledger is refused."""
    out = dict(also or {})
    for p in out:
        if os.path.abspath(p) in {os.path.abspath(q) for q in led.files}:
            raise Unusable(f"{p}: a file of the ledger, which the writer reads already — name only files outside it")
    return out


def _relinked(led: Ledger, changes: dict[str, str | None], also: Mapping[str, str], moved: Mapping[str, str]
              ) -> dict[str, str | None]:
    """``changes`` with every other file's links to a moved file pointed at its new path: the ledger's own
    files (as ``changes`` leaves them) and the caller's ``also``. A file whose links do not change is left."""
    out = dict(changes)
    for p, text in [*led.files.items(), *also.items()]:
        if p in moved or (p in out and out[p] is None):
            continue
        cur = out.get(p, text)
        new = relink(cur, os.path.dirname(p), os.path.dirname(p), moved)
        if new != cur:
            out[p] = new
    return out


def _gated(led: Ledger, changes: Mapping[str, str | None], also: Mapping[str, str], **kw) -> list[str]:
    """``gate()`` over the ledger's part of ``changes``: the caller's other files are not the ledger."""
    return gate(led, {p: t for p, t in changes.items() if p not in also}, **kw)


def _parts_left(led: Ledger, changes: Mapping[str, str | None]) -> None:
    """Refused when the write takes an entry out of the ledger while an open entry is still Part of it,
    judged against the ledger as it stands (``check()`` judges it against the base only)."""
    left = _left_with_open_parts(led.texts()[0], led.overlay(changes).texts()[0])
    if left:
        raise Refused("; ".join(r["text"] for r in left))


def plan_archive(led: Ledger, tid: str, why: str, *, pr: int | None = None, pointer: str | None = None,
                 as_is: bool = False, superseded_by: str | None = None, dropped: bool = False,
                 also: Mapping[str, str] | None = None, base: Ledger | None = None, resolve: Resolve | None = None,
                 today: str | None = None) -> Plan:
    """Open entry ``tid`` archived (``edit_entry()``'s archived form, ``archive_plan()`` first): Resolved (``pr``,
    ``pointer``, ``as_is``), Superseded by ``superseded_by`` (followed to the end of its chain, and each
    dependent's Blocked by rewired to it) or ``dropped`` (refused while an entry is Blocked by it). The file
    moves to ``archive/``, its relative links rewritten for there, and every link to it, in the ledger and
    in ``also`` (path → text, the caller's other files), pointed at its new path."""
    path, text = _open_entry(led, tid, "archived already")
    tid = entries(text)[0]["id"] if entries(text) else tid
    also = _also(also, led)
    day = _today(today)
    if superseded_by is not None and ID_ITEM_RE.match(superseded_by):
        superseded_by = tid_of(superseded_by)  # a local successor at the ledger's width
    ledger_text, arch = led.texts()
    plan = archive_plan(ledger_text, arch, tid, superseded_by=superseded_by, dropped=dropped, resolve=resolve)
    kw = {k: v for k, v in (("pr", pr), ("pointer", pointer), ("as_is", as_is or None),
                            ("superseded_by", plan["successor"]), ("dropped", dropped or None)) if v is not None}
    dst = _join(_join(led.path, LEDGER_ARCHIVE), os.path.basename(path))
    if dst in led.files:
        raise Unusable(f"{dst} exists already")
    out = relink(edit_entry(text, "archive", today=day, why=_why(why), **kw), os.path.dirname(path),
                 os.path.dirname(dst), {path: dst})
    changes: dict[str, str | None] = {path: None, dst: out}
    for dep in plan["rewire"]:
        p, _ = led.entry_file(dep)
        changes[p] = edit_entry(led.files[p], "rename_ref", old=tid, new=plan["successor"])
    changes = _relinked(led, changes, also, {path: dst})
    _parts_left(led, changes)
    notes = _gated(led, changes, also, base=base, resolve=resolve, today=day)
    return Plan("archive", None, changes, {"id": tid, "moved": {"from": path, "to": dst}, "successor": plan["successor"],
                                           "rewired": plan["rewire"], "notes": notes})


def plan_reopen(led: Ledger, tid: str, why: str, *, also: Mapping[str, str] | None = None,
                base: Ledger | None = None, resolve: Resolve | None = None, today: str | None = None) -> Plan:
    """Archived entry ``tid`` reopened (``edit_entry()``'s reopened form) and moved back into the ledger, its
    links rewritten as ``plan_archive()`` rewrites them."""
    _writable(led)
    path, archived = led.entry_file(tid)
    if not archived:
        raise Unusable(f"{tid} is open ({path}): only an archived entry is reopened")
    text = led.files[path]
    tid = entries(text)[0]["id"] if entries(text) else tid
    also = _also(also, led)
    day = _today(today)
    dst = _join(led.path, os.path.basename(path))
    if dst in led.files:
        raise Unusable(f"{dst} exists already")
    out = relink(edit_entry(text, "reopen", today=day, why=_why(why)), os.path.dirname(path), os.path.dirname(dst),
                 {path: dst})
    changes = _relinked(led, {path: None, dst: out}, also, {path: dst})
    notes = _gated(led, changes, also, base=base, resolve=resolve, today=day)
    return Plan("reopen", None, changes, {"id": tid, "moved": {"from": path, "to": dst}, "notes": notes})


def _mentions(tid: str, files: Mapping[str, str | None]) -> list[str]:
    """Each line of ``files`` that names ``tid`` in prose (``TD-7`` is ``TD-007``), as ``path:line: text``."""
    rx = re.compile(rf"(?<![A-Za-z0-9_#/.-])TD-0*{int(tid[3:])}(?!\d)")
    return [f"{p}:{n}: {ln.strip()[:200]}" for p, t in sorted(files.items()) if t
            for n, ln in enumerate(t.splitlines(), 1) if rx.search(ln)]


def plan_renumber(led: Ledger, tid: str, new: str, *, take: str | None = None, also: Mapping[str, str] | None = None,
                  base: Ledger | None = None, resolve: Resolve | None = None, today: str | None = None) -> Plan:
    """Open entry ``tid`` given the id ``new`` (the caller's, from its counter; ``take`` its nonce, written as
    ``Id take``): its heading and file, every entry's Blocked by, Part of and Log ``while`` naming it, its rank
    line, and every link to its file, in the ledger and in ``also``. The lines that still name the old id in
    prose are listed (``mentions``), for the caller to judge; prose is never rewritten."""
    path, text = _open_entry(led, tid, "an archived entry is not renumbered")
    old = entries(text)[0]["id"] if entries(text) else tid
    new = tid_of(new)
    also = _also(also, led)
    day = _today(today)
    ledger_text, arch = led.texts()
    files = {int(m.group(1)) for p in led.files if (m := ENTRY_FILE_RE.match(os.path.basename(p)))}
    if int(new[3:]) in heading_nums(ledger_text) | heading_nums(arch) | files:
        raise Unusable(f"{new} is in the ledger or its archive already")
    out = edit_entry(text, "renumber", new=new)
    if take is not None:
        out = edit_entry(out, "set", fields={"Id take": take})
    dst = _join(os.path.dirname(path), f"{new}.md")
    out = relink(out, os.path.dirname(path), os.path.dirname(dst), {path: dst})
    changes: dict[str, str | None] = {path: None, dst: out}
    rx = re.compile(rf"TD-0*{int(old[3:])}(?!\d)")
    for p, t in sorted(led.files.items()):
        if p == path or not ENTRY_FILE_RE.match(os.path.basename(p)) or not rx.search(t):
            continue
        try:
            got = edit_entry(t, "rename_ref", old=old, new=new)
            same = got == canonical(t)
        except Refused as e:
            fields = entries(t)[0]["fields"] if entries(t) else {}
            if not any(rx.search(fields.get(k) or "") for k in ("blocked by", "part of")):
                continue  # names it in prose only, which is listed below
            raise Refused(f"{p} names {old}, and {e}") from None
        if not same:
            changes[p] = got
    rank_file = rank_path(led.path)
    rank_text = led.read(rank_file)
    key = rank(rank_text)[0].get(old) if rank_text else None
    if key is not None:
        changes[rank_file] = set_rank(led.files.get(rank_file, rank_text), {old: None, new: key})
    changes = _relinked(led, changes, also, {path: dst})
    _parts_left(led, changes)
    notes = _gated(led, changes, also, base=base, resolve=resolve, today=day)
    after = {**{p: t for p, t in led.files.items() if p != path}, **also, **changes}
    return Plan("renumber", None, changes, {"id": new, "was": old, "moved": {"from": path, "to": dst},
                                            "mentions": _mentions(old, after), "notes": notes})


def _split_targets(out: str, rels) -> dict[int, str]:
    return {int(m.group(1)): _join(out, r) for r in rels if (m := ENTRY_FILE_RE.match(os.path.basename(r)))}


def plan_split(led: Ledger, to: str | None = None, *, also: Mapping[str, str] | None = None) -> Plan:
    """A v1 ledger split into its v2 directory (``split()``, SPEC *The ledger as a directory*): every file the
    module gives written under ``to`` (default ``ledger/`` beside the v1 file), the v1 file and its archive
    removed and the rank file moved to ``rank.yml``, as one write. Each file's relative links are rewritten
    for where it now lives, and a link into the v1 files, in the new files and in ``also``, points at the
    entry's file (an entry heading's anchor) or the directory (no anchor) — ``relink()``'s split. An anchor
    it cannot place is left and listed in ``warnings``. ``to`` must not exist."""
    if led.v2:
        raise Unusable(f"{led.path} is a v2 directory already")
    out = to or _join(os.path.dirname(led.path), "ledger")
    if os.path.lexists(out):
        raise Unusable(f"{out} exists: split writes a new directory")
    up = os.path.dirname(os.path.abspath(out))
    while not os.path.lexists(up):
        up = os.path.dirname(up)
    if not os.path.isdir(up):
        raise Unusable(f"{out}: {os.path.relpath(up)} is a file, so the directory cannot be made")
    also = _also(also, led)
    text, arch = led.texts()
    files = split(text, arch)
    targets = _split_targets(out, files)
    gone = {led.path: out, led.archive: _join(out, LEDGER_ARCHIVE)}
    warns: list[str] = []
    changes: dict[str, str | None] = {}
    for rel_path, body in files.items():
        came = led.archive if rel_path.startswith(f"{LEDGER_ARCHIVE}/") else led.path
        dst = _join(out, rel_path)
        changes[dst] = relink(body, os.path.dirname(came), os.path.dirname(dst), gone=gone, targets=targets,
                              here=came, warns=warns)
    changes[led.path] = None
    if led.archive in led.files:
        changes[led.archive] = None
    rank_file = rank_path(led.path)
    if rank_file in led.files:
        changes[rank_path(out)] = led.files[rank_file]
        changes[rank_file] = None
    for p, body in also.items():
        new = relink(body, os.path.dirname(p), os.path.dirname(p), gone=gone, targets=targets, warns=warns)
        if new != body:
            changes[p] = new
    n_arch = sum(r.startswith(f"{LEDGER_ARCHIVE}/") for r in files if ENTRY_FILE_RE.match(os.path.basename(r)))
    return Plan("split", None, changes, {"to": out, "open": len(targets) - n_arch, "archived": n_arch,
                                         "warnings": warns})


def plan_relink(led: Ledger, also: Mapping[str, str], was: str | None = None) -> Plan:
    """The caller's files' links into a v1 ledger already split into ``led`` (``was``, default
    ``technical_debt.md`` beside the directory, and its archive) pointed at the entry files, as ``plan_split()``
    points them: for the files a split did not see."""
    _writable(led)
    if not also:
        raise Unusable("relink takes the files to rewrite")
    also = _also(also, led)
    was = was or _join(os.path.dirname(led.path.rstrip("/")), os.path.basename(LEDGER_FILE))
    gone = {was: led.path, archive_path(was): _join(led.path, LEDGER_ARCHIVE)}
    rels = [os.path.relpath(p, led.path) for p in led.files]
    targets = _split_targets(led.path, rels)
    warns: list[str] = []
    changes: dict[str, str | None] = {}
    for p, body in also.items():
        new = relink(body, os.path.dirname(p), os.path.dirname(p), gone=gone, targets=targets, warns=warns)
        if new != body:
            changes[p] = new
    return Plan("relink", None, changes, {"was": was, "warnings": warns})


def plan_fmt(led: Ledger, ids: Sequence[str] = ()) -> Plan:
    """Each entry named (else every one, open and archived) in canonical form (``canonical()``); an entry it
    refuses is reported with why and left alone. A format pass has no commit subject: the caller names it."""
    _writable(led)
    if ids:
        paths = [led.entry_file(tid_of(t))[0] for t in ids]
    else:
        paths = [p for d in (led.path, _join(led.path, LEDGER_ARCHIVE)) for p in sorted(
            (p for p in led.files if os.path.normpath(os.path.dirname(p)) == os.path.normpath(d)
             and ENTRY_FILE_RE.match(os.path.basename(p))),
            key=lambda p: int(ENTRY_FILE_RE.match(os.path.basename(p)).group(1)))]
    changes: dict[str, str] = {}
    refused = []
    for p in paths:
        text = led.files[p]
        try:
            if any("\udc80" <= c <= "\udcff" for c in text):
                raise Refused("not UTF-8: fix it by hand")
            out = canonical(text)
        except Refused as e:
            refused.append({"path": p, "why": str(e)})
            continue
        if out != text:
            changes[p] = out
    return Plan("fmt", None, changes, {"entries": len(paths), "formatted": list(changes), "refused": refused})


def _entry_paths(led: Ledger) -> list[tuple[str, bool]]:
    """Every entry file, open then archived, each in number order: (path, archived)."""
    return [(p, d != led.path) for d in (led.path, _join(led.path, LEDGER_ARCHIVE)) for p in sorted(
        (p for p in led.files if os.path.normpath(os.path.dirname(p)) == os.path.normpath(d)
         and ENTRY_FILE_RE.match(os.path.basename(p))),
        key=lambda p: int(ENTRY_FILE_RE.match(os.path.basename(p)).group(1)))]


def _released(texts: tuple[str, str]) -> dict[str, dict[str, str]]:
    """Each open entry's blockers' chain end states (``_chain()``, no other repo resolved), by entry id."""
    ledger_text, arch = texts
    live = entries(ledger_text)
    live_nums, gone = {_num(e["id"]) for e in live}, _archived_status(arch)
    return {e["id"]: {b: _chain(b, live_nums, gone, None)[1] for b in parse_gates(e["blocked_raw"])["ids"]}
            for e in live if e["blocked_raw"]}


def plan_migrate(led: Ledger, release: str, ids: Sequence[str] = (), *, closed_dates: Mapping[str, str] | None = None,
                 kinds: Mapping[str, str] | None = None, decided: Mapping[str, str] | None = None,
                 today: str | None = None) -> Plan:
    """``migrate_entry()`` over each entry named, else every entry, open and archived (v2.7, SPEC *Migrating to
    v2.7*). ``closed_dates`` and ``decided`` are keyed by id, matched by number; ``kinds`` is the stage words' map.
    Any stop stops the run: the plan is empty and ``info["stopped"]`` true. ``info["entries"]`` maps each entry
    changed, listed or stopped to its ``{changes, listed, stops}``; ``info["reblocked"]`` each open entry a
    blocker of which flips between released and not, to ``[{blocker, before, after}]``. The subject is
    ``migrate_subject(release, <entries changed>)``, None when nothing changed. Not gated on ``check()``."""
    _writable(led)
    if not RELEASE_RE.fullmatch(release or ""):
        raise Unusable(f"--release is <major>.<minor>, not {release!r}")
    day = _today(today)
    every = _entry_paths(led)
    if ids:
        want = {int(tid_of(t)[3:]) for t in ids}
        held = {int(ENTRY_FILE_RE.match(os.path.basename(p)).group(1)) for p, _ in every}
        missing = sorted(want - held)
        if missing:
            raise Unusable(f"not in the ledger or its archive: {', '.join(f'TD-{n:03d}' for n in missing)}")
        every = [(p, a) for p, a in every if int(ENTRY_FILE_RE.match(os.path.basename(p)).group(1)) in want]
    by_num = {int(ENTRY_FILE_RE.match(os.path.basename(p)).group(1)): (p, a) for p, a in every}
    for k in decided or {}:
        if int(tid_of(k)[3:]) not in by_num:
            raise Unusable(f"--as names {k}, which is not among the entries the run reads")
    dates = {int(tid_of(k)[3:]): v for k, v in (closed_dates or {}).items()}
    answers = {int(tid_of(k)[3:]): v for k, v in (decided or {}).items()}
    changes: dict[str, str] = {}
    report: dict[str, dict] = {}
    stopped = False
    for n, (p, archived) in sorted(by_num.items(), key=lambda x: (x[1][1], x[0])):
        text = led.files[p]
        got = migrate_entry(text, archived=archived, today=day, closed_date=dates.get(n), kinds=kinds,
                            decided=answers.get(n))
        if got["changes"] or got["listed"] or got["stops"]:
            found = entries(text)
            report[found[0]["id"] if found else f"TD-{n:03d}"] = {k: got[k] for k in ("changes", "listed", "stops")}
        stopped = stopped or bool(got["stops"])
        if got["changes"] and got["text"] != text:
            changes[p] = got["text"]
    if stopped:
        return Plan("migrate", None, {}, {"stopped": True, "entries": report, "reblocked": {}})
    before, after = _released(led.texts()), _released(led.overlay(changes).texts())
    reblocked: dict[str, list[dict]] = {}
    for tid, states in after.items():
        for b, now in states.items():
            was = before.get(tid, {}).get(b, now)
            if (was == "resolved") != (now == "resolved"):
                reblocked.setdefault(tid, []).append({"blocker": b, "before": was, "after": now})
    count = sum(1 for r in report.values() if r["changes"])
    return Plan("migrate", migrate_subject(release, count) if count else None, changes,
                {"stopped": False, "entries": report, "reblocked": reblocked})


def apply(plan: Plan) -> list[str]:
    """Make the plan's writes, both or neither; the paths written."""
    return write(plan.changes) if plan.changes else []


# -- the reports ---------------------------------------------------------------------------------------

def value_of(rec: dict, key: str) -> str:
    """What a filter or a count reads: the derived Type and Priority, else the field's first word."""
    if key == "type":
        return rec["type"]
    if key == "priority":
        return rec["priority"].lower()
    return first_word(rec["fields"].get(key))


def select(recs: list[dict], where: Sequence[tuple[str, str]], want_pickable: bool | None) -> list[dict]:
    return [r for r in recs if (want_pickable is None or r["pickable"] == want_pickable)
            and all(value_of(r, k) == v for k, v in where)]


def counts(recs: list[dict], by: Sequence[str]) -> list[dict]:
    """One row per combination of values of the ``by`` fields, most entries first; an absent field is ``(none)``."""
    c = Counter(tuple(value_of(r, k) or "(none)" for k in by) for r in recs)
    return [dict(zip(by, vals), count=n)
            for vals, n in sorted(c.items(), key=lambda kv: (-kv[1], [(v == "(none)", v) for v in kv[0]]))]


def field_summary(res: dict) -> list[dict]:
    """Every field any entry carries, with how many carry it, the values seen, and its vocabulary."""
    seen: dict[str, Counter] = {}
    for r in res["entries"]:
        for k, v in r["fields"].items():
            seen.setdefault(k, Counter())[first_word(v) or "(empty)"] += 1
    keys = [k for k in CADENCE_FIELDS if k in seen] + sorted(k for k in seen if k not in CADENCE_FIELDS)
    keys += [k for k in res["declared"] if k not in seen]
    return [{"field": k, "defined_by": "cadence" if k in CADENCE_FIELDS else
             ("preamble" if k in res["declared"] else "undeclared"),
             "entries": sum(seen.get(k, Counter()).values()), "declared": res["declared"].get(k),
             "values": dict(sorted(seen.get(k, Counter()).items(), key=lambda kv: (-kv[1], kv[0])))} for k in keys]


def archive_loss(led: Ledger, base: Ledger) -> list[dict]:
    """The archive only grows: an id archived in ``base`` that is now in neither the ledger nor the archive
    is lost (an error, ``archive-loss``); one back in the ledger is reopened (ℹ, ``archive-reopened``)."""
    text, arch = led.texts()
    was = heading_nums(base.texts()[1])
    if not was:
        return []
    now, live = heading_nums(arch), heading_nums(text)
    lost, back = sorted(was - now - live), sorted((was - now) & live)
    ids = lambda ns: ", ".join(f"TD-{n:03d}" for n in ns)  # noqa: E731
    out = []
    if lost:
        out.append({"level": "error", "id": None, "field": None, "kind": "archive-loss", "standing": False,
                    "text": f"⚠ the archive lost {ids(lost)}: an archived entry is never removed, so restore "
                            "it from the base"})
    if back:
        out.append({"level": "info", "id": None, "field": None, "kind": "archive-reopened", "standing": False,
                    "text": f"ℹ {ids(back)} left the archive for the ledger: reopened, not lost"})
    return out


def not_canonical(led: Ledger, base: Ledger) -> list[dict]:
    """An error for each entry file of a v2 ledger that differs from ``base``'s (or is new) and is not in
    canonical form, naming ``fmt``; a file ``canonical()`` refuses names its hand fix. An entry the change
    did not touch is never judged."""
    if not led.v2:
        return []
    then = {os.path.relpath(p, base.path): t for p, t in base.files.items()} if base.v2 else {}
    out = []
    for p, text in sorted(led.files.items()):
        m = ENTRY_FILE_RE.match(os.path.basename(p))
        if not m or then.get(os.path.relpath(p, led.path)) == text:
            continue
        tid = os.path.basename(p)[:-3]
        try:
            ok, why = canonical(text) == text, ""
        except Refused as e:
            ok, why = False, f"{e}; fix it by hand, then `fmt {tid}`"
        if not ok:
            out.append({"level": "error", "id": tid, "field": None, "kind": "not-canonical", "standing": False,
                        "text": f"⚠ {tid}: " + (why or f"{p} is not in canonical form — `fmt {tid}` writes it")})
    return out


def report_check(led: Ledger, base: Ledger | None, resolve: Resolve | None, today: str) -> list[dict]:
    """``--check``'s flags: ``check()`` (against ``base``'s ledger text when given), and with a base the
    archive's losses and the changed entry files not in canonical form."""
    recs = _flags(led, base.texts()[0] if base else None, resolve, today)
    if base is not None:
        recs += archive_loss(led, base) + not_canonical(led, base)
    return recs


def _held_by(r: dict) -> str:
    why = [", ".join(r["blocked_by"])] if r["blocked_by"] else []
    if r.get("parts_open"):
        why.append(f"parts open: {', '.join(r['parts_open'])}")
    return "; ".join(why)


def _row(r: dict) -> str:
    return f"  {r['id']:<7} {r['priority']:<7} {r['type']:<8} {r['title']}"


# -- the command line -------------------------------------------------------------------------------

def _field_flags(ap: argparse.ArgumentParser, helps: Mapping[str, str]) -> None:
    for dest, name in FIELDS:
        ap.add_argument(f"--{dest.replace('_', '-')}", dest=dest, metavar=name.upper().replace(" ", "_"),
                        help=helps.get(dest, f"the {name} field"))
    ap.add_argument("--field", action="append", default=[], metavar="NAME=VALUE", help="a repo's own field; repeatable")


def _fields_given(a: argparse.Namespace) -> list[tuple[str, str]]:
    out = [(name, getattr(a, dest)) for dest, name in FIELDS if getattr(a, dest) is not None]
    for f in a.field:
        k, eq, v = f.partition("=")
        if not eq or not k.strip():
            raise Unusable(f"--field takes NAME=VALUE, not {f!r}")
        out.append((k.strip(), v))
    keys = [field_key(n) for n, _ in out]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise Unusable(f"a field is given twice: {', '.join(dup)}")
    return out


def _read_src(flag: str, src: str) -> str:
    try:
        if src == "-":
            return sys.stdin.read()
        with open(src, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Unusable(f"{flag}: cannot read {src} ({e.__class__.__name__})") from None


def _common(ap: argparse.ArgumentParser, write_cmd: bool) -> None:
    ap.add_argument("--ledger", help=f"a v2 directory or a v1 file; default: {LEDGER_DIR} when it is a directory, "
                                     f"else {LEDGER_FILE}")
    ap.add_argument("--resolved", metavar="FILE", help="other repos' entries: a JSON object from <repo>#TD-n to its state")
    ap.add_argument("--today", help="the date the write records and pickable reads, YYYY-MM-DD (default: the UTC clock)")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    if write_cmd:
        ap.add_argument("--base", help="the ledger where the change started (a v2 directory or a v1 file); "
                                       "default: the ledger as it stands")
        ap.add_argument("--plan", action="store_true", help="print the changes as JSON and write nothing")


def _write_parser(cmd: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=f"ledgerboard.ledger {cmd}", description={
        "fmt": "write each entry of a v2 ledger in canonical form",
        "new": "file a new entry in a v2 ledger, in canonical form, under an id the caller took",
        "set": "set an open entry's header fields (an empty value removes one)",
        "note": "append a dated line to an open entry's Log",
        "edit": "replace one section of an open entry (or add it where SPEC puts it)",
        "archive": "archive an open entry (Resolved, Superseded or Dropped) and move its file to archive/",
        "reopen": "reopen an archived entry and move its file back into the ledger",
        "renumber": "give an open entry the id the caller took: its file, heading, the fields naming it, its rank line",
        "lift": "lift one gate from an open entry and log it in one of the fixed gate lifted shapes",
        "split": "split a v1 ledger file into its v2 directory, its links rewritten",
        "relink": "point the given files' links into a split v1 ledger at its entry files"}[cmd])
    if cmd == "fmt":
        ap.add_argument("ids", nargs="*", metavar="TD-n", help="the entries to format; default: every entry")
        ap.add_argument("--check", action="store_true", help="list the entries that would change; write nothing")
    elif cmd == "split":
        ap.add_argument("--archive", help="the v1 ledger's archive; default: <stem>_archive.md beside it")
        ap.add_argument("--to", metavar="DIR", help="the new directory; default: ledger/ beside the v1 file")
        ap.add_argument("--also", nargs="+", action="extend", default=[], metavar="FILE",
                        help="other files whose links into the v1 files are rewritten")
    elif cmd == "relink":
        ap.add_argument("files", nargs="+", metavar="FILE", help="the files whose links into the v1 ledger are rewritten")
        ap.add_argument("--was", metavar="FILE", help="the v1 ledger file it was split from; default: "
                                                      "technical_debt.md beside the directory")
    elif cmd == "new":
        ap.add_argument("--id", required=True, metavar="TD-n", help="the entry's id, taken by the caller")
        ap.add_argument("--title", required=True)
        _field_flags(ap, {"added": "default: today", "status": "default: Open",
                          "location": "the **Location:** body section, after the Why (v2.7: not a header field)"})
        for s in ("why", "fix", "done-when"):
            ap.add_argument(f"--{s}", metavar="FILE", help=f"the {s.replace('-', ' ').capitalize()} section from a "
                                                           "file, or - for stdin")
        ap.add_argument("--take", metavar="NONCE", help="the counter take's nonce, written as Id take")
        ap.add_argument("--by", help="who filed it: the Log's filed by line (with --session and --words)")
        ap.add_argument("--session", help="the session that filed it")
        ap.add_argument("--words", help="the filed by line's words")
        ap.add_argument("--while", dest="while_", metavar="ID", help="the entry being worked on when this one was found")
    else:
        ap.add_argument("id", metavar="TD-n")
        if cmd == "set":
            _field_flags(ap, {"location": "empty only: removes a header Location (v2.7: write the body section with "
                                          "edit --section Location)"})
            ap.add_argument("--by", help="who lifts or reassigns a decision the new Blocked by drops (the caller has "
                                         "checked who ran it)")
            ap.add_argument("--answer", help="the lifting answer's label (default Go)")
            _board_flags(ap)
            ap.add_argument("--override", metavar="WHY", help="lift the dropped decision by override: by anyone, with its why")
            ap.add_argument("--why", help="a reassign's why (the new Blocked by swaps one decision for another)")
        elif cmd == "lift":
            ap.add_argument("--gate", required=True, help='the gate: "decision (<person>)", "event (<name>)" or "until D"')
            ap.add_argument("--by", required=True, help="who lifts it: a person, or a host's token with --evidence or until")
            ap.add_argument("--answer", help="a person's lifting answer (a decision, or an event from a sweep item)")
            ap.add_argument("--evidence", help="a host's event lift: <repo>#<n> (pr-merged), <repo>@<sha> (file-contains, ref-includes), "
                                                    "or <source>/<id> or <source>@<YYYYMMDDTHHMMSSZ> (host-log)")
            _board_flags(ap)
            ap.add_argument("--people", help="the board's People:, comma-separated")
            ap.add_argument("--answered-by", choices=("owner", "any"), help="the board's Answered by:")
        elif cmd == "note":
            ap.add_argument("words", help="the note, one line")
        elif cmd == "edit":
            ap.add_argument("--section", required=True, help="the section's name: Why, Fix, Done when, …")
            ap.add_argument("--from", dest="src", required=True, metavar="FILE", help="its new text from a file, or - for stdin")
        elif cmd in ("archive", "reopen"):
            ap.add_argument("--why", required=True, help="one line: why it is archived, or open again")
            if cmd == "archive":
                ap.add_argument("--pr", type=int, help="Resolved: the PR that resolved it, as the forge numbered it")
                ap.add_argument("--pointer", help="Resolved: where its lasting content now lives")
                ap.add_argument("--as-is", action="store_true", help="Resolved: keep the Fix, the Resolved line after it")
                how = ap.add_mutually_exclusive_group()
                how.add_argument("--superseded-by", metavar="ID", help="Superseded by that entry (TD-n or <repo>#TD-n), "
                                                                       "its dependents rewired to it")
                how.add_argument("--dropped", action="store_true", help="Dropped: decided not to do it")
        else:
            ap.add_argument("--id", required=True, dest="new", metavar="TD-n", help="the new id, taken by the caller")
            ap.add_argument("--take", metavar="NONCE", help="the counter take's nonce, written as Id take")
        if cmd in ("archive", "reopen", "renumber"):
            ap.add_argument("--also", nargs="+", action="extend", default=[], metavar="FILE",
                            help="other files whose links to the moved file are rewritten")
    _common(ap, write_cmd=cmd not in ("fmt", "split", "relink"))
    if cmd in ("split", "relink"):
        ap.add_argument("--plan", action="store_true", help="print the changes as JSON and write nothing")
    return ap


def _board_flags(ap: argparse.ArgumentParser) -> None:
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--board", metavar="REPO", help="the covering item is on that repo's board: logs ; board <repo>")
    g.add_argument("--no-board-item", action="store_true", help="no item covers the gate: logs ; no board item")
    g.add_argument("--shared-item", action="store_true", help="the covering item is a parent snapshot left open")


def _suffix(a: argparse.Namespace) -> str | None:
    if a.board is not None:
        return f"board {a.board}"
    return "no board item" if a.no_board_item else "shared board item left open" if a.shared_item else None


def _ledger_arg(a: argparse.Namespace) -> str:
    if a.ledger:
        return a.ledger
    return LEDGER_DIR if os.path.isdir(LEDGER_DIR) else LEDGER_FILE


def _build(cmd: str, a: argparse.Namespace, resolve: Resolved) -> Plan:
    if cmd == "split":
        led = Ledger.open(a.ledger or LEDGER_FILE, a.archive)
        return plan_split(led, a.to, also={p: _read_raw(p) for p in dict.fromkeys(a.also)})
    led = Ledger.open(_ledger_arg(a))
    if cmd == "relink":
        return plan_relink(led, {p: _read_raw(p) for p in dict.fromkeys(a.files)}, a.was)
    if cmd == "fmt":
        return plan_fmt(led, a.ids)
    base = Ledger.open(a.base) if a.base else None
    if cmd in ("new", "set"):
        loc = [f for f in a.field if field_key(f.partition("=")[0]) == "location"]
        if cmd == "new" and loc:
            raise Unusable("--field Location=… is not a header field from v2.7: give --location, which writes "
                           "the **Location:** body section")
        if cmd == "set" and ((a.location or "").strip() or any(f.partition("=")[2].strip() for f in loc)):
            raise Unusable(f"Location is not a header field from v2.7: write the body section with edit {a.id} "
                           "--section Location (an empty --location still removes the header field)")
    if cmd == "new":
        if not a.priority:
            raise Unusable("--priority is required (High, Medium or Low)")
        if not a.why:
            raise Unusable("--why is required: the Why is the point of an entry")
        if [a.why, a.fix, a.done_when].count("-") > 1:
            raise Unusable("only one section can come from stdin")
        sections = []
        for name, src in (("Why", a.why), ("Fix", a.fix), ("Done when", a.done_when)):
            body = _read_src(f"--{name.lower().replace(' ', '-')}", src).strip() if src is not None else ""
            if body:
                sections.append((name, body))
        filed = None
        parts = {"who": a.by, "session": a.session, "words": a.words}
        if any(v is not None for v in parts.values()) or a.while_ is not None:
            missing = [f"--{'by' if k == 'who' else k}" for k, v in parts.items() if v is None]
            if missing:
                raise Unusable(f"the filed by line needs --by, --session and --words: {', '.join(missing)} missing")
            filed = dict(parts, **({"while": a.while_} if a.while_ else {}))
        return plan_new(led, a.id, a.title, _fields_given(a), sections, take=a.take, filed=filed, base=base,
                        resolve=resolve, today=a.today)
    if cmd == "set":
        fields = dict(_fields_given(a))
        if not fields:
            raise Unusable("give at least one field to set")
        return plan_edit(led, "set", tid_of(a.id), fields=fields, by=a.by, answer=a.answer, suffix=_suffix(a),
                         override=a.override, why=a.why, base=base, resolve=resolve, today=a.today)
    if cmd == "lift":
        people = [x.strip() for x in a.people.split(",") if x.strip()] if a.people is not None else None
        return plan_lift(led, tid_of(a.id), a.gate, a.by, answer=a.answer, evidence=a.evidence, suffix=_suffix(a),
                         people=people, answered_by=a.answered_by, base=base, resolve=resolve, today=a.today)
    if cmd == "note":
        return plan_edit(led, "note", tid_of(a.id), words=a.words, base=base, resolve=resolve, today=a.today)
    if cmd in ("archive", "reopen", "renumber"):
        also = {p: _read_raw(p) for p in dict.fromkeys(a.also)}
        kw = {"also": also, "base": base, "resolve": resolve, "today": a.today}
        if cmd == "renumber":
            return plan_renumber(led, tid_of(a.id), a.new, take=a.take, **kw)
        if cmd == "reopen":
            return plan_reopen(led, tid_of(a.id), a.why, **kw)
        if (a.superseded_by or a.dropped) and (a.pr is not None or a.pointer is not None or a.as_is):
            raise Unusable("--pr, --pointer and --as-is are a Resolved archive's: a superseded or dropped entry "
                           "keeps its Why and Fix")
        return plan_archive(led, tid_of(a.id), a.why, pr=a.pr, pointer=a.pointer, as_is=a.as_is,
                            superseded_by=a.superseded_by, dropped=a.dropped, **kw)
    words = _read_src("--from", a.src).strip()
    if not words:
        raise Unusable("--from is empty: a section is never emptied by edit")
    return plan_edit(led, "edit", tid_of(a.id), section=a.section, words=words, base=base, resolve=resolve,
                     today=a.today)


def _say(a: argparse.Namespace, cmd: str, obj: dict, text: str, code: int) -> int:
    if a.json or getattr(a, "plan", False):
        print(json.dumps({"action": cmd, **obj}, ensure_ascii=False))
    else:
        print(f"ledgerboard.ledger: {text}", file=sys.stderr)
    return code


def run_write(cmd: str, argv: list[str]) -> int:
    ap = _write_parser(cmd)
    a = ap.parse_args(argv)
    try:
        resolve = Resolved.from_file(getattr(a, "resolved", None))
        try:
            plan = _build(cmd, a, resolve)
        except Refused:
            if resolve.needs:
                raise Needs(resolve.needs) from None
            raise
        if resolve.needs:
            raise Needs(resolve.needs)
    except Needs as e:
        return _say(a, cmd, {"needs": e.ids}, f"needs: {', '.join(e.ids)}", 3)
    except Unusable as e:
        return _say(a, cmd, {"unusable": str(e)}, f"{cmd}: {e}", 2)
    except Refused as e:
        return _say(a, cmd, {"refused": str(e)}, f"{cmd}: refused, nothing written — {e}", 1)
    check_only = cmd == "fmt" and a.check
    if getattr(a, "plan", False) or check_only:
        if check_only and not a.json:
            for p in plan.info["formatted"]:
                print(f"would change: {p}")
            for r in plan.info["refused"]:
                print(f"{r['path']}: refused, left alone — {r['why']}", file=sys.stderr)
        else:
            print(json.dumps(plan.as_json(), ensure_ascii=False))
        return 1 if cmd == "fmt" and (plan.info["refused"] or (check_only and plan.changes)) else 0
    try:
        paths = apply(plan)
    except OSError as e:
        return _say(a, cmd, {"failed": str(e)}, f"{cmd}: the write failed, every file restored: {e}", 4)
    if a.json:
        print(json.dumps({"action": plan.action, "subject": plan.subject, "paths": paths, **plan.info},
                         ensure_ascii=False))
    else:
        for p in paths:
            print(p)
        for n in plan.info.get("notes", []):
            print(f"note — {n}", file=sys.stderr)
        for w in plan.info.get("warnings", []):
            print(f"note — a link left as it was: {w}", file=sys.stderr)
        for m in plan.info.get("mentions", []):
            print(f"check — names {plan.info['was']} in prose: {m}", file=sys.stderr)
        for r in plan.info.get("refused", []):
            print(f"{r['path']}: refused, left alone — {r['why']}", file=sys.stderr)
    return 1 if cmd == "fmt" and plan.info["refused"] else 0


def migrate_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ledgerboard.ledger migrate", description=(
        "migrate each entry named, else every entry, open and archived, to v2.7's forms (migrate_entry()); "
        "any stop stops the run and writes nothing"))
    ap.add_argument("ids", nargs="*", metavar="TD-n", help="the entries to migrate; default: every entry")
    ap.add_argument("--release", required=True, metavar="X.Y", help="the release migrated to: the commit subject's")
    ap.add_argument("--closed-dates", metavar="FILE", help="the caller's archiving dates: a JSON object from TD-n to "
                                                           "YYYY-MM-DD")
    ap.add_argument("--stage-kind", action="append", default=[], metavar="WORD=KIND",
                    help="the Kind an open entry's retired stage word becomes; repeatable")
    ap.add_argument("--as", dest="as_", action="append", default=[], metavar="TD-n=FORM",
                    help="a person's decision for a stopped Status: resolved, dropped, superseded <id> or open; repeatable")
    ap.add_argument("--plan", action="store_true", help="print the changes and the entries as JSON and write nothing")
    ap.add_argument("--dry-run", action="store_true", help="print the entries as text and write nothing")
    ap.add_argument("--ledger", help=f"the v2 directory; default: {LEDGER_DIR}")
    ap.add_argument("--today", help="the date the Log lines record, YYYY-MM-DD (default: the UTC clock)")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    return ap


def _migrate_args(a: argparse.Namespace) -> dict:
    """migrate's flags checked and read: Unusable (exit 2) for any outside its shape."""
    if a.plan and a.dry_run:
        raise Unusable("--plan and --dry-run are one or the other")
    if not RELEASE_RE.fullmatch(a.release):
        raise Unusable(f"--release is <major>.<minor>, each one to nine digits, not {a.release!r}")
    dates: dict[str, str] = {}
    if a.closed_dates is not None:
        try:
            raw = json.loads(_read_src("--closed-dates", a.closed_dates))
        except ValueError as e:
            raise Unusable(f"--closed-dates is a JSON object: {e}") from None
        if not isinstance(raw, dict):
            raise Unusable("--closed-dates is a JSON object from TD-n to YYYY-MM-DD")
        for k, v in raw.items():
            if not ID_ITEM_RE.fullmatch(k) or not isinstance(v, str) or not _real_day(v):
                raise Unusable(f"--closed-dates maps TD-n to a real YYYY-MM-DD, not {k!r}: {v!r}")
            if tid_of(k) in dates:
                raise Unusable(f"--closed-dates names {tid_of(k)} twice")
            dates[tid_of(k)] = v
    kinds: dict[str, str] = {}
    for x in a.stage_kind:
        w, eq, k = x.partition("=")
        w = w.strip().lower()
        if not eq or w not in STAGE_WORDS:
            raise Unusable(f"--stage-kind takes WORD=KIND, WORD one of {', '.join(STAGE_WORDS)}, not {x!r}")
        if w in kinds:
            raise Unusable(f"--stage-kind names {w} twice")
        if not k.strip() or "\n" in k or "\r" in k:
            raise Unusable(f"--stage-kind {w}: KIND is one line of text")
        kinds[w] = k.strip()
    decided: dict[str, str] = {}
    for x in a.as_:
        t, eq, form = x.partition("=")
        if not eq or not ID_ITEM_RE.fullmatch(t.strip()) or not MIGRATE_DECIDED_RE.fullmatch(form.strip()):
            raise Unusable(f"--as takes TD-n=FORM, FORM resolved, dropped, superseded <id> or open, not {x!r}")
        if tid_of(t.strip()) in decided:
            raise Unusable(f"--as names {tid_of(t.strip())} twice")
        decided[tid_of(t.strip())] = form.strip()
    return {"closed_dates": dates, "kinds": kinds or None, "decided": decided}


def _dry_run_text(plan: Plan) -> str:
    out = []
    for tid, r in plan.info["entries"].items():
        out.append(tid)
        out += [f"  {w}: {x}" for w, k in (("change", "changes"), ("listed", "listed"), ("stop", "stops"))
                for x in r[k]]
    if not any(r["changes"] for r in plan.info["entries"].values()):
        out.append("nothing to migrate")
    if plan.info["reblocked"]:
        out.append("reblocked:")
        out += [f"  {tid}: {r['blocker']} {r['before']} → {r['after']}"
                for tid, rs in plan.info["reblocked"].items() for r in rs]
    return "\n".join(out)


def run_migrate(argv: list[str]) -> int:
    ap = migrate_parser()
    a = ap.parse_args(argv)
    try:
        kw = _migrate_args(a)
        plan = plan_migrate(Ledger.open(a.ledger or LEDGER_DIR), a.release, a.ids, today=a.today, **kw)
    except Unusable as e:
        return _say(a, "migrate", {"unusable": str(e)}, f"migrate: {e}", 2)
    except Refused as e:
        return _say(a, "migrate", {"unusable": str(e)}, f"migrate: {e}", 2)
    info = {"entries": plan.info["entries"], "reblocked": plan.info["reblocked"]}
    if plan.info["stopped"]:
        if a.json or a.plan:
            print(json.dumps({"action": "migrate", "plan": {}, **info}, ensure_ascii=False))
        else:
            for tid, r in info["entries"].items():
                if r["stops"]:
                    print(f"{tid}: {'; '.join(r['stops'])}", file=sys.stderr)
        return 1
    if a.plan or (a.dry_run and a.json):
        print(json.dumps({"action": "migrate", "subject": plan.subject, "plan": plan.changes, **info},
                         ensure_ascii=False))
        return 0
    if a.dry_run:
        print(_dry_run_text(plan))
        return 0
    try:
        paths = apply(plan)
    except OSError as e:
        return _say(a, "migrate", {"failed": str(e)}, f"migrate: the write failed, every file restored: {e}", 4)
    if a.json:
        print(json.dumps({"action": "migrate", "subject": plan.subject, "paths": paths, **info}, ensure_ascii=False))
    else:
        for p in paths:
            print(p)
    return 0


def report_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ledgerboard.ledger", description=__doc__.split("\n", 1)[0])
    ap.add_argument("--pickable", nargs="?", const=True, default=None, metavar="yes|no",
                    help="alone: the pick order, the blocked entries and the flags; with --list/--counts: keep only "
                         "entries whose derived pickable is yes (or no)")
    ap.add_argument("--list", action="store_true", help="every entry the filters keep, in pick order")
    ap.add_argument("--counts", metavar="FIELD[,FIELD]", help="count the kept entries per value of one or two fields")
    ap.add_argument("--fields", action="store_true", help="every field the entries carry, and each one's vocabulary")
    ap.add_argument("--check", action="store_true", help="only the flags; exit 1 when an error (⚠) stands")
    ap.add_argument("--summary", action="store_true", help="the summary table: one row per entry in pick order")
    ap.add_argument("--base", help="with --check: the ledger where the change started; only what changed since counts")
    ap.add_argument("--where", action="append", default=[], metavar="FIELD=VALUE",
                    help="keep entries whose FIELD's first word is VALUE (FIELD= : absent or empty); repeatable")
    for name in ALIASES:
        ap.add_argument(f"--{name}", metavar=name.upper(), help=f"same as --where {name}=VALUE")
    ap.add_argument("--archive", help="a v1 ledger's archive; default: <stem>_archive.md beside it")
    _common(ap, write_cmd=False)
    return ap


def run_report(argv: list[str]) -> int:
    ap = report_parser()
    a = ap.parse_args(argv)
    modes = [m for m in ("list", "counts", "fields", "check", "summary") if getattr(a, m)]
    if a.pickable is not None and not modes:
        if a.pickable is not True:
            ap.error("--pickable yes|no filters --list or --counts; alone, --pickable takes no value")
        modes = ["pickable"]
    if len(modes) != 1:
        ap.error("give exactly one of --pickable, --list, --counts, --fields, --check, --summary, "
                 f"or an action: {', '.join(WRITES)}")
    mode = modes[0]
    if a.base is not None and mode != "check":
        ap.error("--base applies to --check only")
    want = None
    if mode in ("list", "counts") and a.pickable is not None:
        if a.pickable is True or a.pickable.lower() == "yes":
            want = True
        elif a.pickable.lower() == "no":
            want = False
        else:
            ap.error(f"--pickable takes yes or no, not {a.pickable!r}")
    where = []
    for term in a.where + [f"{n}={getattr(a, n)}" for n in ALIASES if getattr(a, n) is not None]:
        k, eq, v = term.partition("=")
        if not eq or not field_key(k):
            ap.error(f"--where takes FIELD=VALUE, not {term!r}")
        where.append((field_key(k), first_word(v)))
    if (where or want is not None) and mode not in ("list", "counts"):
        ap.error("filters apply to --list and --counts only")
    by = [field_key(x) for x in (a.counts or "").split(",") if x.strip()]
    if mode == "counts" and not 1 <= len(by) <= 2:
        ap.error("--counts takes one or two fields, comma-separated")
    try:
        resolve = Resolved.from_file(a.resolved)
        day = _today(a.today)
        led = Ledger.open(_ledger_arg(a), a.archive)
        if mode == "check":
            recs = report_check(led, Ledger.open(a.base) if a.base else None, resolve, day)
        else:
            text, arch = led.texts()
            res = pickable(text, arch, resolve, rank_text=led.rank(), today=day)
        if resolve.needs:
            raise Needs(resolve.needs)
    except Needs as e:
        return _say(a, mode, {"needs": e.ids}, f"needs: {', '.join(e.ids)}", 3)
    except Refused as e:
        return _say(a, mode, {"unusable": str(e)}, str(e), 2)
    if mode == "check":
        errors = [r for r in recs if r["level"] == "error"]
        if a.json:
            print(json.dumps({"flags": recs, "errors": len(errors)}, ensure_ascii=False))
            return 1 if errors else 0
        for r in recs:
            if not r["standing"]:
                print(r["text"])
        standing = sum(r["standing"] for r in recs)
        print(f"ledger check: {len(errors)} error(s)"
              + (f"; {standing} standing flag(s) on entries unchanged since the base, not shown" if standing else ""))
        return 1 if errors else 0
    if a.json:
        keys = {"summary": ("entries", "flags"), "pickable": ("pickable", "blocked", "flags")}.get(mode)
        if keys:
            obj = {k: res[k] for k in keys}
        elif mode == "list":
            obj = {"entries": select(res["entries"], where, want), "flags": res["flags"]}
        elif mode == "counts":
            obj = {"by": by, "counts": counts(select(res["entries"], where, want), by), "flags": res["flags"]}
        else:
            obj = {"fields": field_summary(res), "flags": res["flags"]}
        print(json.dumps(obj, ensure_ascii=False))
        return 0
    if mode == "summary":
        print("| ID | Title | Priority | Type | State |\n|----|-------|----------|------|-------|")
        for r in res["entries"]:
            state = "pickable" if r["pickable"] else f"blocked by {_held_by(r)}"
            print(f"| {r['id']} | {r['title'].replace('|', '/')} | {r['priority']} | {r['type']} | {state} |")
    elif mode == "pickable":
        print(f"Pickable ({len(res['pickable'])}), in pick order:")
        for r in res["pickable"]:
            print(_row(r))
        if not res["pickable"]:
            print("  (none)")
        if res["blocked"]:
            print(f"Blocked ({len(res['blocked'])}):")
            for r in res["blocked"]:
                print(f"{_row(r)} — by {_held_by(r)}")
    elif mode == "list":
        kept = select(res["entries"], where, want)
        print(f"Entries ({len(kept)}), in pick order:")
        for r in kept:
            print(_row(r) + ("" if r["pickable"] else f" — blocked by {_held_by(r)}"))
        if not kept:
            print("  (none)")
    elif mode == "counts":
        rows = counts(select(res["entries"], where, want), by)
        for row in rows:
            print(f"  {row['count']:>4}  " + "  ".join(f"{k}={row[k]}" for k in by))
        if not rows:
            print("     0")
    else:
        for f in field_summary(res):
            vocab = f" — declared: {' | '.join(f['declared'])}" if f["declared"] else ""
            vals = ", ".join(f"{v} {n}" for v, n in f["values"].items())
            print(f"  {f['field']:<12} {f['defined_by']:<10} {f['entries']:>3} entries  {vals}{vocab}")
    for f in res["flags"]:
        print(f)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["migrate"]:
        return run_migrate(argv[1:])
    if argv[:1] and argv[0] in WRITES:
        return run_write(argv[0], argv[1:])
    return run_report(argv)


if __name__ == "__main__":
    sys.exit(main())
