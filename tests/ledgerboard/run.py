#!/usr/bin/env python3
"""Run every ledgerboard fixture against a copy of the ledgerboard package; exit 1 on any difference.

    python3 fixtures/run.py [--module PATH] [--write]
    python3 fixtures/run.py --check-header [--module PATH]
    python3 fixtures/run.py --stamp <x.y>
    (cd fixtures && git ls-files -z) | python3 fixtures/run.py --check-tracked

``--module`` is the copy to test (default: ../ledgerboard/ beside this directory), so a consumer
that vendors the package and these fixtures checks its own copy. It is the package's directory,
loaded as a package so its files' relative imports resolve (a single module file, a copy from
before the package, is loaded as a module). ``--write`` regenerates every expected ``*.json`` from
the module instead of comparing — for the ledgerboard repo only, after a deliberate format change;
review the diff. ``--check-header`` checks only the first line of every ``*.py`` file in the
package: a release's ``# ledgerboard v<x.y> sha256:<hex>`` whose hash is that of every byte after
the first line, the same release in each (exit 1 when one is not a release header, its hash does
not match, or two name different releases). It then checks this set's ``MANIFEST`` (v2.5): the release it
names and the sha256 of every other file here, which must match, with no file missing or added, and the same
release as the package (exit 1 on any difference). ``--stamp <x.y>`` writes that ``MANIFEST`` for this set,
and ``--check-tracked`` compares its paths with the NUL-separated paths on stdin (what git tracks, which
``release.sh`` pipes in; this file runs no git); ``release.sh`` runs both. Stdlib only.

Fixtures, each an invented input and its expected JSON:
- ``ledger/<case>.md`` (+ ``<case>.archive.md``, optional ``<case>.resolve.json`` mapping a
  ``<repo>#TD-NNN`` item to ``[state, why]``, optional ``<case>.rank.yml``, its rank file) →
  ``<case>.json``: ``pickable()`` and ``check()``. Its optional v2 twin, the directory
  ``<case>.v2/`` (``README.md``, ``TD-NNN.md``, ``archive/``, ``rank.yml``), is what ``split()``
  writes from the v1 texts, and ``load()`` of it gives the same ``<case>.json`` (v2.0).
- ``board/<case>.md`` → ``<case>.json``: the board read through ``load_board()`` (v3.0; a case directory,
  ``board/<case>/``, holds ``board.md`` and its archive ``board_archive.md`` beside it, and its ``expected.json``):
  every open and closed item's ``item_record()`` at ``TODAY``, each with its ``fields`` (``item_fields()``), the
  items' ids (open in the board's order, then closed), ``needs_you()`` at ``TODAY``, each row by id, and
  ``board_people()`` (v2.3). Its optional v3 twin, ``<case>.v3/`` beside it (v3.0), is what ``split_board()``
  writes from the case's texts, and ``load_board()`` of it reads as the same JSON, compared as SPEC's *Two reads
  of one board compared* says; ``board/split_notes.json`` holds ``split_board_notes()`` of each such split.
- ``board_split/<case>/`` (v3.0): ``board.md`` and an optional ``archive.md`` through ``split_board()`` — the
  files or the refusal, ``split_board_notes()`` of them, and whether each line's persisted key (the hash a
  consumer's ``board:<8 hex>`` holds) ends an id — against ``expected.json``.
- ``board_dir/<case>/`` (v3.0): ``board/`` (or ``case.json``'s ``path``, relative to the case, which need not
  exist; its ``unreadable`` paths read as None) through ``load_board()`` — its form, major, path and problems, its
  reads as ``board/``'s, ``board_dir_problems()`` and ``version_problem()``, and with ``since`` the ids such a read
  gives — against ``expected.json``.
- ``edit/cases.json`` → ``edit/expected.json``: the line predicates, the version reader (v1.0), and
  ``bold_head()`` (from v3.0 a heading too, read whole), ``is_not_right_form()`` and ``fill_not_right()`` (v1.1), and the rank —
  ``queue_subject()``, ``implicit_key()``, ``key_order()``, ``midpoint()``, ``rank()``, ``set_rank()``,
  ``rank_path()`` and ``components()`` of a ledger fixture's entries (v1.2), and ``respace()`` (v2.3), and
  ``split_notes()`` of a README and ``item_notes()`` of a line, or (v3.0) of an item file, at the file's ``today``
  (v2.4); ``item_key()`` of lines that carry a ``Hide until`` (v2.3); and answer forms (v2.8): ``is_form()``,
  ``form_head()`` and ``fill_form()``. v3.0 retired its groups of the v2 line writers (``edit_line()``,
  ``item_line()``, ``decided_line()``, ``item_problem()``, ``canonical_item()``, ``archive_subject()``); their
  item-file counterparts are ``item/``'s.
- ``item/cases.json`` → ``item/expected.json`` (v3.0): the board's item file — ``parse_item()`` of each file at its
  path, printed as ``item_attrs()`` and ``item_fields()``; ``item_file()`` and ``decided_file()``, every file they write
  judged by ``item_file_problem()``; ``edit_item()`` of each edit; ``item_file_problem()`` and ``canonical_item_file()``;
  the ids (``item_id()``, ``is_item_id()``, ``item_path()``, ``key_id()``, a raised ValueError recorded as
  ``{"raises": "ValueError"}``); and the commit subjects of a board write — ``subject()``, which takes an ``id``
  (v3.0 removed the form with none), and, of v2 and v3 subjects alike, ``subject_kind()``, ``edit_action()`` and ``subject_id()`` (``edit/``'s subject groups, moved here);
  the gate, ``board_problems()`` over ``Board``s (``gate``, each board a ``{path, files}`` read through
  ``load_board()``); and D7's one rule for a string, ``closes()`` and ``parts_problems()`` of an item file and of
  v2 strings (``strings``), which v3.0 takes as no item: ``closes()`` refuses one, ``parts_problems()`` gives ``[]``.
- ``sweep/cases.json`` → ``sweep/expected.json`` (v2.4): ``sweep()`` and ``covers()`` over ``sweep/``'s ledger and
  boards, each read whole through ``load_board()`` (v3.0: a board names its file, its archive beside it as
  ``<stem>_archive.md``, or a ``dir``; ``to_close`` lists ids, ``covers()`` names each item by id); the ``sets``,
  each its own boards over the same ledger; ``rerun``, over each v2 board's split (v3.0), the first run's closes and
  filings made there; and ``split``, a run with a v2 board replaced by its split, made in memory, compared as two
  reads of one board are; and ``parts_problems()`` (v2.6) of each ``parts_problems`` case's item file against its own entries and
  ``archived``, with, where the case asks, ``covers()`` of each listed part on a one-item board holding the line,
  and the ``decide_lift()`` cross-check of a ``Go``. From v2.7, a lifting answer closed with no lift (TD-224 to
  TD-269): the ``act`` that says its lift is owed, held entries, its close, and a run's own ``reask_days``.
- ``ledger/belowheader.md`` (TD-049): a ``decision`` gate below the header block — ``check()`` gives its ℹ and
  reads on, where v2.4 raised, so the next entry's reassign note still comes.
- ``ledger/parts.md`` (v2.1): ``Part of`` — a parent with open and with archived parts, the order,
  and each check; ``components()`` of it joins through the field.
- ``ledger_edit/cases.json`` (+ the entry files it names) → ``ledger_edit/expected.json`` (v2.2): one
  entry's writers — ``canonical()`` of each input (and whether a second pass changes it) and
  ``entry_text()`` of each new entry, and ``edit_entry()`` of each case's steps run in order, or why
  each is refused; and ``check()``'s Part of flags of a ledger before and after an archive
  (``check/``), ``archive-open-parts`` among them. From v2.4, the Log: ``entry_text(filed=)``, the
  writers' Log lines, and per ``log`` case ``log_lines()``, ``log_problems()``, ``status_notes_to_log()``
  and ``gate_age()`` of each gate the case names (from v2.5 ``gate_added()`` too, and a ``set`` step takes the
  case's own ``today`` when it gives one). Also from v2.4, ``archive_plan()`` of each ``archive_plan`` case
  (``plan/``: a supersede, its chain, each refusal, a chain ending in a Status word this reader does not know
  among them), the Dropped archive, and ``rename_ref`` keeping one copy. From v3.0, ``check()``'s ``retired``
  errors (``check/waits_*``, ``check/location_*``, ``check/*_untouched``): an error on every entry holding a retired
  field or the old decision form, whatever the edit, never ℹ. From v3.1, ``decision-missing`` given a base
  (``check/asks_*.md``: standing, a note, a lift, a direct drop, a new Ask, and an answered entry noted, respaced,
  relinked, renumbered and reopened), and ``edit_entry()``'s Ask refusals, its wider ``remove`` and ``set``'s
  header ``Ask``.
- ``ledger/supersede.md`` (v2.4): an archived blocker's Status read — Resolved, Superseded (by an open entry, a
  Resolved one, another repo's, a chain ending in Dropped, a loop, no successor) and Dropped, here and through the
  resolver's ``status`` and ``successor``.
- ``ledger/unknownstatus.md`` (v2.4, TD-039): an archived blocker whose Status word this reader does not know keeps
  the block and is flagged — here and through the resolver, at a chain's end, and each edge of the word rule: prose,
  punctuation kept on the word, a first run that strips to nothing, no first run, a known word in capitals, ``Open``.
- ``host-log-pure/cases.json`` → ``host-log-pure/expected.json`` (v2.5): a ``host-log`` check counted with no file —
  ``first_instant()`` of each date, and ``count_host_log()`` of each case's records (``at`` written
  ``YYYY-MM-DDTHH:MM:SSZ``, read with ``strptime``, never ``fromisoformat``, which refuses ``Z`` on 3.10), or why it
  is refused.
- ``verdict/cases.json`` → ``verdict/expected.json`` (v2.4): the merge gate's verdicts — ``lift_pr_verdict()``,
  ``tripwire()`` and ``uncovered_decisions()`` of each case's trees: ``base/`` under each case's
  ``cases/<name>/base/``, less its ``delete_base`` paths, then its ``cases/<name>/head/`` over that, less its
  ``delete`` paths (a path ending in ``/`` every path under it, v3.0); the board a v3 directory, and another
  repo's board under ``boards/`` a directory or a v2 file read through ``load_board()`` (v3.0).
- ``board_writer/<case>/`` (v2.3): the board writer, ``board.py`` — ``before/`` (the files a command
  starts from; from v3.0 the board a directory of item files, ``board/`` with its ``README.md``, or a v2 file
  for the reads and the refusals), ``cmd.json`` (``{"argv": [...]}``, run in a copy of ``before/``), ``after/``
  (every file as the command leaves it: a refusal or a ``--plan`` leaves ``before/``'s; a close's item file moved
  under ``archive/<YYYY-MM>/``) and ``expected.json`` (its exit code, argparse's 2 for a usage error, and the JSON
  it printed: the subject, the item's id and the paths, the plan, or why it refused). A case holding
  ``expected_stdout.txt`` (v3.0, ``show``) has its stdout compared with that file byte for byte, never stripped
  or parsed, and its ``expected.json``'s ``out`` is null. A ``before/`` holds no empty directory (git keeps
  none): an empty board is ``tests/``'.
- ``ledger_writer/<case>/`` (v2.4): the ledger writer, ``ledger.py`` — laid out as ``board_writer/``'s cases, each
  ``argv`` carrying ``--json`` so what it prints is one object: a report, the paths written, the plan, why it
  refused, or the ids it ``needs``. From v3.1, ``ask_*``: ``set --ask`` and ``new --ask`` and their refusals, the
  old two writes each refused, the writes over an ungated Ask (a standing one passes, a ``renumber`` or ``reopen``
  is refused), and ``--check`` of the ledger a decide lift left (``ask_check_after_decide``).
- ``status/cases.json`` → ``status/expected.json`` (v2.7; ``migrate/``'s ``status_problem`` group until v3.0, which
  removed ``migrate_entry()``): ``status_problem()`` of each form, in its place and out of it.
- ``person_text/cases.json`` → ``person_text/expected.json`` (v3.2): *Text a person reads* — each case a call
  (``fn``, ``args``, ``kwargs``) of ``code_tokens()``, ``sentence_problems()``, ``person_text_problems()`` or
  ``title_problems()``, its result the tokens, the problems as ``[rule, refuse, line]`` lists, or
  ``{"error": "ValueError"}``; or ``{"constant": name}``, its result the constant's value. The expected results
  are written from SPEC's text and its examples, never from the module's output.
- ``grammar/cases.json`` → ``grammar/expected.json`` (v2.3): SPEC's grammar appendix — per start symbol and
  production, strings that production's EBNF accepts and refuses, and the module's verdict on each:
  ``item_file_problem()`` of a whole item file (v3.0; v3.0 retired the ``item-line`` start, whose judge was
  ``item_problem()``), ``rank()``'s flags of a rank file, ``parse_gates()`` of a ``Blocked by`` (v2.4,
  whose ``person`` productions hold a person's name), ``parse_event_section()`` of an Event section (v2.4).
  ``tests/test_grammar.py`` checks the appendix's EBNF against these verdicts.
- ``origins/cases.json`` → ``origins/expected.json`` (v2.4): repos and origins — ``origin_key()`` and
  ``origin_path()`` of ssh, https and unreadable URLs; ``item_key()`` of two lines differing only in a repo's
  case (it stays byte-exact); ``item_refs()`` folding a repo's case and reading no ref from a bad repo; and
  ``parse_blocked()`` of ids whose repo is or is not the grammar; and ``item_file_problem()`` of a ``Parts`` naming one
  repo in two cases (v3.0; ``item_problem()`` of its line before it).
- ``ledger/gates.md`` (v2.4): ``Blocked by``'s gates at ``TODAY`` — an ``until`` past, reached and ahead, an
  ``event``, a decision with and without its Ask, each gate repeated, the retired words (``hold``, ``decision
  (designer)``, the old form, ``Waits``, ``Taken by``, a stage word in Status), a Priority outside the three,
  items the grammar does not read, the words in any case, and a parent's ``parts_gates``. From v3.1 (TD-112),
  ``decision-missing``: an Ask with no gate, only an ``until`` or an ``event``, or held in the header (each ℹ);
  answered by a lift or an override, or by one of two decisions with the other still carried (none); lifted and
  added again, a lift above a later-dated ``gate added``, or a Log with an unreadable line (ℹ); a retired item
  (``retired`` only), an unreadable ``decision (…)`` (beside ``blocked-item``), a qualified ``Ask (…)``, a lead in a
  code fence, and an archived entry (none); ``ledger/decision_missing_v1.md`` the same on a v1 ledger.
- ``ledger/events.md`` (v2.4): ``check()``'s events — a section whose text holds quotes, a gate with no section,
  sections whose gates are gone (one explained by its ``gate lifted`` Log line), a name twice, and each section
  the reader refuses.
- ``events/cases.json`` → ``events/expected.json`` (v2.4): ``parse_check()`` of each check type's value, every
  argument confinement refusal among them, and ``parse_event_section()`` of sections well and badly formed.
- ``lift/cases.json`` (+ ``lift/entries/``) → ``lift/expected.json`` (v2.4): lifting a gate — ``lift_gate()`` of
  each shape and each refusal, ``decide_lift()`` of a parent's go (a lift, a kept-waiting and a work-order answer,
  a skipped part, a parent without the gate, a person in another case, an emptied ``Blocked by``, two lifting
  labels, an event's three answers, each refusal; v3.0: each base item an item file, ``items``), the two compared
  byte for byte, ``reassign_gate()`` and
  ``reassigns()`` with ``check()``'s note, ``closes()``, ``edit_item(…, close=True)``, ``waiting_only()``,
  ``parse_closed_items()`` (its items' ``words``, v3.0), ``answered_by()`` and its problems of a v2 board read as a
  ``Board``, and the waiting-only label refused by ``item_file(lifts=)`` and ``item_file_problem()`` (v3.0; each
  item an item file where v2.x took a line).
- ``ids/cases.json`` → ``ids/expected.json`` (v2.4): the next id — ``parse_take()`` of takes, a range and commits
  that are not takes, ``next_id()`` over ``LAST``, ids and a floor, ``ids_held()`` of each layout, and
  ``judge_takes()`` of each id's ``Id take`` against a counter's takes (v3.0: a ``Taken by`` is no take).
- ``ledger/escaped.md`` (v2.2): ``Escaped from`` is the format's own field — a ledger with a
  ``Fields:`` line flags an undeclared field beside it, never it.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = date(2026, 1, 15)  # fixed: the fixtures' dates are inputs, not the run's clock


HEADER_RE = re.compile(rb"^# ledgerboard v(\d+)\.(\d+) sha256:([0-9a-f]{64})\n")


def header_problem(raw: bytes) -> str | None:
    """Why `raw` (a module's bytes) is not an intact release, or None."""
    m = HEADER_RE.match(raw)
    if not m:
        first = raw.split(b"\n", 1)[0].decode("utf-8", "replace")
        return f"the first line is not a release header: {first!r}"
    body = raw[m.end():]
    if hashlib.sha256(body).hexdigest() != m.group(3).decode():
        return "the header's sha256 does not match the rest of the file — edited after its release"
    return None


def package_files(path: Path) -> list[Path]:
    """The files that carry a release header: every ``*.py`` of a package directory, or the one module file."""
    return sorted(path.glob("*.py")) if path.is_dir() else [path]


def headers_problem(path: Path) -> str | None:
    """Why the package (or module file) at `path` is not one intact release, or None."""
    files = package_files(path)
    if not files:
        return f"{path} holds no *.py file"
    releases = set()
    for f in files:
        raw = f.read_bytes()
        why = header_problem(raw)
        if why:
            return f"{f.name}: {why}"
        releases.add(raw.split(b" ", 3)[2].decode())
    if len(releases) > 1:
        return f"the files name different releases: {', '.join(sorted(releases))}"
    return None


# The set's release (v2.5, TD-040): fixtures/MANIFEST, a release line and `<sha256>  <path>` for every other
# file of the set, sorted by the path's UTF-8 bytes. `--stamp` writes it, `--check-header` checks it beside the
# package's headers and `--check-tracked` compares it with what git tracks (piped in: this file runs no git).
MANIFEST = "MANIFEST"
RELEASE_LINE_RE = re.compile(r"# ledgerboard v([0-9]+\.[0-9]+) fixtures")
RELEASE_ARG_RE = re.compile(r"[0-9]+\.[0-9]+")
ENTRY_HEAD_RE = re.compile(r"[0-9a-f]{64}  ")
NO_MANIFEST = "no MANIFEST — this set names no release (a set from before v2.5 is its tag's)"
NOT_A_FILE = "MANIFEST is not a file"
NOT_LF_TEXT = "MANIFEST is not UTF-8 text with LF line endings and a final LF"


def _odd(path: str) -> str | None:
    """Why a relative path cannot be a manifest line's path (its name not UTF-8, or a newline, CR or
    backslash in it), or None."""
    try:
        os.fsencode(path).decode("utf-8")
    except UnicodeDecodeError:
        return "a name that is not UTF-8"
    if any(c in path for c in "\n\r\\"):
        return "a path holding a newline, a carriage return or a backslash"
    return None


def _shown(path: str) -> str:
    """A path as a problem line writes it: its ``repr`` when it is odd (``_odd``), else as it stands."""
    return repr(path) if _odd(path) else path


def _bkey(path: str) -> bytes:
    return os.fsencode(path)


def _walk(root: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """The set on disk: ``({path: file}, {path: problem})`` — every regular file under ``root`` but the
    top-level ``MANIFEST`` and anything under a ``__pycache__`` directory, by its ``/``-joined relative
    path, and each entry refused (not a regular file, a name not UTF-8, an odd path), one problem each.
    No symbolic link is followed; a link named ``__pycache__`` is a link, refused, not pruned."""
    files: dict[str, Path] = {}
    refused: dict[str, str] = {}
    top = str(root)
    def unreadable(err: OSError) -> None:  # a directory the walk cannot read is never silently left out
        raise err
    for d, dirnames, filenames in os.walk(top, onerror=unreadable, followlinks=False):
        rel_dir = os.path.relpath(d, top)
        parts = [] if rel_dir == "." else rel_dir.split(os.sep)
        if not parts:
            dirnames[:] = [n for n in dirnames if n != MANIFEST]
            filenames[:] = [n for n in filenames if n != MANIFEST]
        keep = []
        for n in dirnames:
            rel = "/".join([*parts, n])
            if os.path.islink(os.path.join(d, n)):
                refused[rel] = "not a regular file"
            elif n != "__pycache__":
                keep.append(n)
        dirnames[:] = keep
        for n in filenames:
            rel = "/".join([*parts, n])
            full = os.path.join(d, n)
            if not stat.S_ISREG(os.lstat(full).st_mode):
                refused[rel] = "not a regular file"
            elif _odd(rel):
                refused[rel] = _odd(rel)
            else:
                files[rel] = Path(full)
    return files, refused


def _refused_lines(refused: dict[str, str]) -> list[str]:
    return [f"{p!r}: {why}" for p, why in sorted(refused.items(), key=lambda kv: _bkey(kv[0]))]


def manifest_text(root: Path, release: str) -> str:
    """The manifest of the set at ``root`` for ``release``; ValueError (its ``args[0]`` the list of
    problems) when the set holds an entry the manifest cannot list."""
    files, refused = _walk(root)
    if refused:
        raise ValueError(_refused_lines(refused))
    lines = [f"{hashlib.sha256(files[p].read_bytes()).hexdigest()}  {p}\n" for p in sorted(files, key=_bkey)]
    return f"# ledgerboard v{release} fixtures\n" + "".join(lines)


def _read_manifest(root: Path) -> tuple[list[str], bool, str | None, list[tuple[str, str]]]:
    """``(problems, stopped, release, entries)`` of the manifest file itself (rule 3's first four bullets):
    ``stopped`` when a problem leaves nothing more to check."""
    m = root / MANIFEST
    if not os.path.lexists(m):
        return [NO_MANIFEST], True, None, []
    if not stat.S_ISREG(os.lstat(m).st_mode):
        return [NOT_A_FILE], True, None, []
    raw = m.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None or not raw or b"\r" in raw or not raw.endswith(b"\n") or b"\n\n" in raw:
        return [NOT_LF_TEXT], True, None, []
    lines = text.split("\n")[:-1]
    head = RELEASE_LINE_RE.fullmatch(lines[0])
    if not head:
        return [f"MANIFEST's first line is not a release line: {lines[0]!r}"], True, None, []
    problems: list[str] = []
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    prev: str | None = None
    for n, line in enumerate(lines[1:], start=2):
        if len(line) <= 66 or not ENTRY_HEAD_RE.match(line[:66]):
            problems.append(f"MANIFEST line {n} is not '<sha256>  <path>': {line!r}")
            continue
        path = line[66:]
        if path in seen:
            problems.append(f"MANIFEST lists {path} twice")
            continue
        if prev is not None and _bkey(path) < _bkey(prev):
            problems.append(f"MANIFEST line {n} is out of order")
        seen.add(path)
        prev = path
        entries.append((line[:64], path))
    return problems, False, head.group(1), entries


def manifest_file_problems(root: Path) -> list[str]:
    """The manifest file's own problems: none there, not a file, not LF text, a bad first line, and each
    malformed, repeated or out-of-order line."""
    return _read_manifest(root)[0]


def manifest_entries(root: Path) -> list[tuple[str, str]]:
    """``(sha256, path)`` of each well-formed later line, the first of each path, in file order; ``[]`` when
    a problem stops the check."""
    return _read_manifest(root)[3]


def manifest_release(root: Path) -> str | None:
    """The ``<x.y>`` the manifest names, when the file has no problem of its own; else None."""
    problems, _, release, _ = _read_manifest(root)
    return None if problems else release


def manifest_problems(root: Path) -> list[str]:
    """Every problem of the set's manifest but the release mismatch, each without its ``fixtures: ``
    prefix: the file's own, then each entry refused on disk, then each file missing, added or edited."""
    problems, stopped, _, entries = _read_manifest(root)
    if stopped:
        return problems
    files, refused = _walk(root)
    problems += _refused_lines(refused)
    listed = dict((p, h) for h, p in entries)
    diff = []
    for p in sorted(set(listed) | set(files), key=_bkey):
        if p in refused:
            continue
        if p not in files:
            diff.append(f"{p}: in MANIFEST but missing")
        elif p not in listed:
            diff.append(f"{p}: not in MANIFEST — added after its release")
        elif hashlib.sha256(files[p].read_bytes()).hexdigest() != listed[p]:
            diff.append(f"{p}: its sha256 does not match MANIFEST — edited after its release")
    return problems + diff


def _stamp(release: str) -> int:
    m = HERE / MANIFEST
    if os.path.lexists(m) and not stat.S_ISREG(os.lstat(m).st_mode):
        print(f"fixtures: {NOT_A_FILE}", file=sys.stderr)
        return 1
    try:
        text = manifest_text(HERE, release)
    except ValueError as why:
        for p in why.args[0]:
            print(f"fixtures: {p}", file=sys.stderr)
        return 1
    fd, tmp = tempfile.mkstemp(prefix=".MANIFEST.", dir=HERE)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp's 0600 would make a copy unreadable to others
        os.replace(tmp, m)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    print(f"stamped fixtures v{release} ({text.count(chr(10)) - 1} files)")
    return 0


def _check_tracked() -> int:
    problems = manifest_file_problems(HERE)
    if problems:
        for p in problems:
            print(f"fixtures: {p}", file=sys.stderr)
        return 1
    raw = sys.stdin.buffer.read().split(b"\0")
    if raw and raw[-1] == b"":
        raw.pop()
    tracked = {os.fsdecode(b) for b in raw}
    tracked = {p for p in tracked if p != MANIFEST and "__pycache__" not in p.split("/")[:-1]}
    listed = {p for _, p in manifest_entries(HERE)}
    diff = sorted(tracked ^ listed, key=_bkey)
    for p in diff:
        print(f"fixtures/ differs from what git tracks: {_shown(p)}", file=sys.stderr)
    return 1 if diff else 0


def _check_header(module: Path) -> int:
    why = headers_problem(module)
    package = None if why else package_files(module)[0].read_bytes().split(b" ", 3)[2].decode()
    print(f"header: {why}" if why else f"header: ok ({package})")
    problems = manifest_problems(HERE)
    for p in problems:
        print(f"fixtures: {p}")
    release = manifest_release(HERE)
    bad = bool(why or problems)
    if not problems:
        if not why and f"v{release}" != package:
            print(f"fixtures: MANIFEST names v{release}, the package {package}")
            bad = True
        else:
            print(f"fixtures: ok (v{release}, {len(manifest_entries(HERE))} files)")
    return 1 if bad else 0


def load(path: Path):
    """The package at directory `path` (its ``__init__.py``, with relative imports resolved inside it),
    or the module file at `path`."""
    if path.is_dir():
        spec = importlib.util.spec_from_file_location(
            "ledgerboard_under_test", path / "__init__.py", submodule_search_locations=[str(path)])
    else:
        spec = importlib.util.spec_from_file_location("ledgerboard_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


def _refused(fn):
    try:
        return {"ok": fn()}
    except Exception as e:  # noqa: BLE001  # the module's Refused, by name: a consumer's copy is another class
        if type(e).__name__ != "Refused":
            raise
        return {"refused": str(e)}


def fs_ls(path: str) -> list[str] | None:
    """``ls`` for ``load()`` and ``load_board()`` over the file system (SPEC *The ledger as a directory*): each
    subdirectory's name followed by ``/`` (v3.0)."""
    p = Path(path)
    return sorted(c.name + ("/" if c.is_dir() else "") for c in p.iterdir()
                  if c.is_file() or c.is_dir()) if p.is_dir() else None


def dict_ls(files: dict[str, str]):
    """``ls`` over a {relative path: text} mapping ("" is the root), each subdirectory once as ``<name>/``."""
    def ls(path: str) -> list[str] | None:
        pre = f"{path.rstrip('/')}/" if path else ""
        under = [k[len(pre):] for k in files if k.startswith(pre)]
        return sorted({x if "/" not in x else x.split("/", 1)[0] + "/" for x in under}) if under else None
    return ls


def record(L, item) -> dict:
    """An item's record (``item_record()``) and beside it its header fields (``item_fields()``, v3.0)."""
    return {**L.item_record(item, TODAY), "fields": item_fields(item)}


def board_read(L, board) -> dict:
    """What every reader reads of a ``Board`` (v3.0): its records, open and closed, its people, what needs the
    person (each row by id) and its items' ids (open in the board's order, then closed)."""
    return {"items": [record(L, i) for i in board.items],
            "people": L.board_people(board),
            "needs_you": [[i.id, cls, days] for i, cls, days in L.needs_you(board, TODAY)],
            "keys": [i.id for i in board.items + board.closed],
            "closed": [record(L, i) for i in board.closed]}


def fs_read(path: str) -> str | None:
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.is_file() else None


def v1_texts(md: Path) -> tuple[str, str, str | None]:
    """(ledger, archive, rank file or None) of a v1 case."""
    arch = md.with_name(md.stem + ".archive.md")
    rk = md.with_name(md.stem + ".rank.yml")
    return (md.read_text(encoding="utf-8"), arch.read_text(encoding="utf-8") if arch.exists() else "",
            rk.read_text(encoding="utf-8") if rk.exists() else None)


def v2_files(d: Path) -> dict[str, str]:
    """A v2 case directory as {relative path: text}, its rank file left out."""
    return {c.relative_to(d).as_posix(): c.read_text(encoding="utf-8")
            for c in sorted(d.rglob("*")) if c.is_file() and c.name != "rank.yml"}


def ledger_case(L, md: Path, texts: tuple[str, str, str | None] | None = None) -> dict:
    text, archive, rank_text = texts or v1_texts(md)
    res = md.with_name(md.stem + ".resolve.json")
    table = json.loads(res.read_text(encoding="utf-8")) if res.exists() else {}

    def resolve(item):
        if item not in table:
            return ("unresolved", f"{item} is not in the fixture's resolver")
        return table[item] if isinstance(table[item], dict) else tuple(table[item])  # v2.4: a mapping carries the Status
    p = L.pickable(text, archive, resolve, rank_text=rank_text, today=TODAY)
    return {"entries": p["entries"], "pickable": [e["id"] for e in p["pickable"]],
            "blocked": [e["id"] for e in p["blocked"]], "flags": p["flag_recs"],
            "declared": p["declared"], "rows": L.rows(text),
            "check": L.check(text, archive, resolve=resolve, rank_text=rank_text, today=TODAY),
            "check_since_empty": L.check(text, archive, old="", resolve=resolve, today=TODAY)}


def board_case(L, md: Path) -> dict:
    """A v2 board, ``<case>.md`` (or a case directory's ``board.md`` with ``board_archive.md`` beside it), read
    through ``load_board()`` (v3.0)."""
    path = md / "board.md" if md.is_dir() else md
    board = L.load_board(str(path), fs_ls, fs_read)
    got = board_read(L, board)
    for rec, it in zip(got["closed"], board.closed):
        rec["raw"] = it.raw  # a closed line as written (v3.0)
    return got


def _board_texts(md: Path) -> tuple[str, str]:
    """A v2 board case's board and archive texts: ``<case>.md`` with ``<case>_archive.md`` beside it, or a case
    directory's ``board.md`` with ``board_archive.md``."""
    path = md / "board.md" if md.is_dir() else md
    arch = Path(str(path)[:-3] + "_archive.md")
    return fs_read(str(path)) or "", fs_read(str(arch)) or ""


def _v3_dir(md: Path) -> Path:
    return md.with_name((md.name if md.is_dir() else md.stem) + ".v3")


def compared(got: dict) -> dict:
    """Two reads of one board as SPEC compares them (v3.0, *Two reads of one board compared*): records keyed by id,
    their ``path``, ``line`` and a closed record's ``raw`` left out; ``keys`` as a set; ``needs_you``'s tie groups
    (each run of one class and one days) each as a set, the groups in order."""
    def recs(rs: list[dict]) -> dict:
        return {r["id"]: {k: v for k, v in r.items() if k not in ("path", "raw")} for r in rs}
    groups: list[list] = []
    for iid, cls, days in got["needs_you"]:
        if groups and groups[-1][:2] == [cls, days]:
            groups[-1][2].append(iid)
        else:
            groups.append([cls, days, [iid]])
    return {"items": recs(got["items"]), "closed": recs(got["closed"]), "keys": sorted(got["keys"]),
            "people": got["people"], "needs_you": [[c, d, sorted(ids)] for c, d, ids in groups]}


def board_v3_case(L, md: Path) -> dict:
    """A v2 board case's split, ``<case>.v3/`` (v3.0): ``split_board()`` of the case's texts must give it file for
    file, and ``load_board()`` of it must read as the case's expected JSON, compared as ``compared()`` says."""
    d = _v3_dir(md)
    board, archive = _board_texts(md)
    got = compared(json.loads(json.dumps(board_read(L, L.load_board(str(d), fs_ls, fs_read)), default=str)))
    got["split_matches_dir"] = _refused(lambda: L.split_board(board, archive)) == {"ok": v2_files(d)}
    return got


def v3_expected(want: dict | None) -> dict | None:
    return None if want is None else dict(compared(want), split_matches_dir=True)


def board_split_notes(L, root: Path) -> dict:
    """``split_board_notes()`` of each ``fixtures/board/`` case that splits (v3.0), by case name."""
    out = {}
    for md in sorted([*(root / "board").glob("*.md"),
                      *(p for p in (root / "board").glob("*") if p.is_dir() and not p.name.endswith(".v3"))]):
        if _v3_dir(md).is_dir():
            board, archive = _board_texts(md)
            out[md.stem if not md.is_dir() else md.name] = [
                list(n) for n in L.split_board_notes(L.split_board(board, archive), board, archive)]
    return out


def _persisted(L, text: str) -> list[str]:
    """The hash ShiftLead's ``key()`` persisted for each item line of ``text``: the first 8 hex digits of the
    SHA-256 of ``item_key("- [ ] " + <the line's text>)``."""
    out = []
    for ln in text.splitlines():
        m = L.ITEM_RE.match(ln) or L.CLOSED_ITEM_RE.match(ln)
        if m:
            out.append(hashlib.sha256(L.item_key(f"- [ ] {m.group('text').strip()}").encode("utf-8")).hexdigest()[:8])
    return out


def board_split_case(L, case: Path) -> dict:
    """``split_board()`` of a case's ``board.md`` and its optional ``archive.md`` (v3.0): the files, or the
    refusal; ``split_board_notes()`` of them; whether every item line's persisted key is the end of an id."""
    board = fs_read(str(case / "board.md")) or ""
    archive = fs_read(str(case / "archive.md")) or ""
    got = _refused(lambda: L.split_board(board, archive))
    if "refused" in got:
        return {"refused": got["refused"]}
    files = got["ok"]
    ids = {p.rsplit("/", 1)[-1][:-3][-8:] for p in files if p != "README.md"}
    return {"files": files, "notes": [list(n) for n in L.split_board_notes(files, board, archive)],
            "persisted_keys_found": all(h in ids for h in _persisted(L, board + "\n" + archive))}


def board_dir_case(L, case: Path) -> dict:
    """A board read through ``load_board()`` (v3.0): ``board/`` (or ``case.json``'s ``path``, relative to the case,
    which need not exist), its ``unreadable`` paths read as None; the Board's form, major, path and problems, its
    reads, ``board_dir_problems()`` and ``version_problem()``; with ``since``, the ids a read with it gives."""
    spec = json.loads((case / "case.json").read_text(encoding="utf-8")) if (case / "case.json").exists() else {}
    unreadable = set(spec.get("unreadable", []))

    def ls(p):
        return fs_ls(str(case / p))

    def read(p):
        return None if p in unreadable else fs_read(str(case / p))
    path = spec.get("path", "board")
    board = L.load_board(path, ls, read)
    out = {"form": board.form, "major": board.major, "path": board.path, **board_read(L, board),
           "problems": [list(x) for x in board.problems],
           "board_dir_problems": [list(x) for x in L.board_dir_problems(path, ls, read)],
           "version_problem": L.version_problem(board)}
    if "since" in spec:
        part = L.load_board(path, ls, read, since=date.fromisoformat(spec["since"]))
        out["since"] = {"items": [i.id for i in part.items], "closed": [i.id for i in part.closed]}
    return out


def edit_cases(L, spec: dict, root: Path = HERE) -> dict:
    today = date.fromisoformat(spec["today"])
    out: dict = {"predicates": {}, "versions": []}  # v3.0 retired the v2 line writers' groups
    out["item_keys"] = {ln: L.item_key(ln) for ln in spec.get("item_keys", [])}  # v2.3: Hide until is stripped
    for ln in spec["predicates"]:
        out["predicates"][ln] = {"entry_id": L.entry_id(ln), "row_id": L.row_id(ln), "is_item": L.is_item(ln),
                                 "is_open_item": L.is_open_item(ln), "is_stamp": L.is_stamp(ln),
                                 "is_sweep_stamp": L.is_stamp(ln, ("Swept", "Swept-deep"))}
    for t in spec["versions"]:
        out["versions"].append({"major": L.format_major(t), "problem": L.version_problem(t)})
    out["bold_heads"] = {(f"heading: {t['heading']}" if isinstance(t, dict) else t):
                         (L.bold_head(t["heading"], heading=True) if isinstance(t, dict) else L.bold_head(t))
                         for t in spec["bold_heads"]}  # v3.0: a heading, read whole
    out["not_right_forms"] = {a: L.is_not_right_form(a) for a in spec["not_right_forms"]}
    out["not_right_fills"] = {c["name"]: _refused(lambda c=c: L.fill_not_right(c["said"], c["offered"]))
                              for c in spec["not_right_fills"]}
    if "forms" in spec:  # v2.8: any <head>: answer is a form
        out["forms"] = {a: {"is_form": L.is_form(a), "form_head": L.form_head(a)} for a in spec["forms"]}
        out["form_fills"] = {c["name"]: _refused(lambda c=c: L.fill_form(c["said"], c["offered"],
                                                                         **({"form": c["form"]} if "form" in c else {})))
                             for c in spec["form_fills"]}
    out["queue_subjects"] = [_refused(lambda c=c: L.queue_subject(c["tool"], c["action"], c["ids"]))
                             for c in spec["queue_subjects"]]
    out["implicit_keys"] = [L.implicit_key(c["priority"], c["type"], c["id"], c["repo"]) for c in spec["implicit_keys"]]
    out["key_orders"] = [sorted(ks, key=L.key_order) for ks in spec["key_orders"]]
    out["midpoints"] = [_refused(lambda a=a, b=b: L.midpoint(a, b)) for a, b in spec["midpoints"]]
    out["rank_reads"] = [list(L.rank(t)) for t in spec["rank_reads"]]
    out["rank_writes"] = [_refused(lambda c=c: L.set_rank(c["text"], c["lines"])) for c in spec["rank_writes"]]
    out["respaces"] = [_refused(lambda c=c: list(L.respace(c["text"], c["ledger"], fixed=c.get("fixed", ()),  # v2.3
                                                             repo=c.get("repo", ""))))
                       for c in spec.get("respaces", [])]
    if spec.get("split_notes"):  # v2.4: a module without split_notes() fails this key alone
        out["split_notes"] = ([[list(n) for n in L.split_notes(t)] for t in spec["split_notes"]]
                              if hasattr(L, "split_notes") else "the module has no split_notes — older than v2.4")
    if spec.get("item_notes"):  # v2.4: a module without item_notes() fails this key alone
        out["item_notes"] = ({c["name"]: L.item_notes(L.parse_item(c["file"]) if "file" in c  # v3.0: either major
                                                      else L.parse_board(c["line"], warn=False)[0], today)
                              for c in spec["item_notes"]}
                             if hasattr(L, "item_notes") else "the module has no item_notes — older than v2.4")
    out["rank_paths"] = {p: L.rank_path(p) for p in spec["rank_paths"]}
    out["components"] = {f: L.components(L.entries((root / f).read_text(encoding="utf-8")))
                         for f in spec["components"]}
    return out


def item_fields(item) -> list[list[str]]:
    """A BoardItem's header fields (v3.0), ``BoardItem.fields`` as ``[name, value]`` pairs, in order."""
    return [[n, v] for n, v in item.fields]


def item_attrs(item) -> dict:
    """The attributes of a BoardItem that ``item/``'s ``parse`` case names (v3.0): each date ``YYYY-MM-DD``, each
    tuple a list (``decided`` ``[label, date]``, ``closed`` ``[date, why]``, ``doer`` ``[kind, name, text]``, each
    reply ``[by, date, words]``), None as null."""
    def day(d):
        return d.isoformat() if d is not None else None
    return {"id": item.id, "words": item.words, "kind": item.kind, "added": day(item.added), "due": day(item.due),
            "bad_due": item.bad_due, "fyi_due": item.fyi_due, "hide_until": day(item.hide_until),
            "context": item.context, "answers": item.answers, "default": item.default,
            "decided": [item.decided[0], day(item.decided[1])] if item.decided else None,
            "decided_by": item.decided_by, "doer": list(item.doer) if item.doer else None, "parts": item.parts,
            "replies": [list(r) for r in item.replies],
            "closed": [day(item.closed[0]), item.closed[1]] if item.closed is not None else None}


def _raises(fn):
    """``{"ok": fn()}``, or ``{"raises": "ValueError"}`` when it raises one (v3.0: an id, a path)."""
    try:
        return {"ok": fn()}
    except ValueError:
        return {"raises": "ValueError"}


def item_cases(L, spec: dict) -> dict:
    """The board's item file (v3.0): ``parse_item()`` of each file at its path, as ``item_attrs()`` and
    ``item_fields()``; ``item_file()`` and ``decided_file()`` of each compose case, and ``item_file_problem()`` of each
    file they write; ``edit_item()`` of each edit; ``item_file_problem()`` and ``canonical_item_file()`` of each file;
    the ids (``item_id()``, ``is_item_id()``, ``item_path()``, ``key_id()``); and the commit subjects of a board write,
    v2 and v3 (``subject()``, ``subject_kind()``, ``edit_action()``, ``subject_id()``)."""
    if not hasattr(L, "parse_item"):  # a module older than v3.0
        return {"missing": "the module has no parse_item — older than v3.0"}
    today = date.fromisoformat(spec["today"])

    def parsed(c):
        it = L.parse_item(c["text"], c["path"])
        return None if it is None else {"attrs": item_attrs(it), "fields": item_fields(it)}

    def compose(c):
        if c["fn"] == "item_file":
            kw = {k: c[k] for k in ("kind", "answers", "default", "detail", "hide_until", "lifts", "parts", "doer")
                  if k in c}
            return _refused(lambda: L.item_file(c["text"], c["due"], c.get("today", spec["today"]), c["session"],
                                                c["host"], c["context"], **kw))
        by = {"by": c["by"]} if "by" in c else {}
        return _refused(lambda: L.decided_file(c["title"], c["ref"], c["answers"], c["default"], c["words"],
                                               spec["today"], **by))

    def edit(c):
        to = date.fromisoformat(c["to"]) if c.get("to") else None
        return _refused(lambda: L.edit_item(c["text"], c["action"], to=to, answer=c.get("answer"), why=c.get("why"),
                                            reply=c.get("reply"), by=c.get("by"), today=today,
                                            close=bool(c.get("close"))))
    def board(b):
        return None if b is None else L.load_board(b["path"], dict_ls(b["files"]), b["files"].get)

    def gate(c):  # v3.0 (B2): the gate over Boards; a board read from a file is refused
        return _refused(lambda: [list(p) for p in L.board_problems(board(c["board"]), board(c.get("old")))])

    def strings(c):  # v3.0 (B2): D7's one rule for a string argument; from B5 a v2 string is no item
        ents = c.get("entries", {})
        return {"closes": {lb: _refused(lambda lb=lb: L.closes(c["text"], lb, ents)) for lb in c["labels"]},
                "parts_problems": L.parts_problems(c["text"], ents)}
    composed = {c["name"]: compose(c) for c in spec["compose"]}
    ids, subj = spec["ids"], spec["subjects"]
    return {
        "parse": {c["name"]: parsed(c) for c in spec["parse"]},
        "compose": composed,
        "written": {n: L.item_file_problem(r["ok"]) for n, r in composed.items() if "ok" in r},
        "edits": {c["name"]: edit(c) for c in spec["edits"]},
        "gate": {c["name"]: gate(c) for c in spec.get("gate", [])},
        "strings": {c["name"]: strings(c) for c in spec.get("strings", [])},
        "problems": {c["name"]: L.item_file_problem(c["text"]) for c in spec["problems"]},
        "canonical": {c["name"]: _refused(lambda c=c: L.canonical_item_file(c["text"])) for c in spec["canonical"]},
        "ids": {"item_id": [_raises(lambda a=a, n=n: L.item_id(a, n)) for a, n in ids["item_id"]],
                "is_item_id": {s: L.is_item_id(s) for s in ids["is_item_id"]},
                "item_path": [_raises(lambda i=i, d=d: L.item_path(i, d)) for i, d in ids["item_path"]],
                "key_id": [{"key_id": L.key_id(L.item_key("- [ ] " + c["text"])),
                            "as_persisted": L.key_id(L.item_key("- [ ] " + c["text"])) == c["hex"]}
                           for c in ids["key_id"]]},
        "subjects": {
            "subjects": [_refused(lambda c=c: L.subject(
                c["tool"], c["action"], c["text"], id=c["id"], to=c.get("to"), answer=c.get("answer"),
                session=c.get("session"))) for c in subj["subjects"]],  # v3.0 removed the form with no id
            "subject_kinds": {s: L.subject_kind(s) for s in subj["subject_kinds"]},
            "edit_actions": {s: L.edit_action(s) for s in subj["edit_actions"]},  # v2.3
            "subject_ids": {s: L.subject_id(s) for s in subj["subject_ids"]}},
    }


def ledger_edit_cases(L, spec: dict, root: Path = HERE) -> dict:
    """The entry writers' cases (v2.2): an input is an entry file beside ``cases.json`` or inline
    ``text`` (a CRLF case must be inline: a text read here has its line endings translated)."""
    d = root / "ledger_edit"
    missing = [n for n in ("canonical", "entry_text", "edit_entry") if not hasattr(L, n)]
    if missing:  # a module older than v2.2: this case fails, the others still run
        return {"missing": f"the module has no {', '.join(missing)} — older than v2.2"}

    def text(c):
        return c["text"] if "text" in c else (d / c["file"]).read_text(encoding="utf-8")

    def canon(c):
        got = _refused(lambda: L.canonical(text(c)))
        if "ok" in got:
            got["idempotent"] = L.canonical(got["ok"]) == got["ok"]
        return got
    def log(c):
        if not hasattr(L, "log_lines"):  # a module older than v2.4
            return {"missing": "the module has no log_lines — older than v2.4"}
        t = text(c)
        return {"log_lines": L.log_lines(t), "log_problems": [list(x) for x in L.log_problems(t)],
                "status_notes_to_log": _refused(lambda: L.status_notes_to_log(t)),
                "gate_age": {g: L.gate_age(t, g) for g in c["gates"]},
                **({"gate_added": {g: L.gate_added(t, g) for g in c["gates"]}} if hasattr(L, "gate_added") else {})}

    def plan(c):  # v2.4: what an archive leaves its dependents
        if not hasattr(L, "archive_plan"):
            return {"missing": "the module has no archive_plan — older than v2.4"}
        table = c.get("resolve", {})
        return _refused(lambda: L.archive_plan(
            text({"file": c["ledger"]}), text({"file": c["archive"]}), c["tid"], superseded_by=c.get("superseded_by"),
            dropped=c.get("dropped", False),
            resolve=lambda x: tuple(table[x]) if x in table else ("unresolved", f"{x} is not in the case's resolver")))

    def edits(c):
        def run():
            out = text(c)
            for st in c["steps"]:
                dated = st["action"] in ("note", "archive", "reopen")  # these require a date
                args = ({"today": c.get("today", spec["today"])} if dated
                        else {"today": c["today"]} if st["action"] in ("set", "edit") and "today" in c else {})  # v2.5: their own
                out = L.edit_entry(out, st["action"], **{**args, **st["args"]})
            return out
        return _refused(run)
    return {"canonical": {c["name"]: canon(c) for c in spec["canonical"]},
            "edit_entry": {c["name"]: edits(c) for c in spec["edit_entry"]},
            "check": {c["name"]: [r for r in L.check(text({"file": c["ledger"]}), text({"file": c["archive"]}) if c["archive"] else "",
                                                     old=text({"file": c["old"]}) if c.get("old") else None,
                                                     today=spec["today"])
                                  if r["kind"] in ("archive-open-parts", "part-of-archived", "part-of-unknown",
                                                   "log-not-last", "log-line", "event-undated", "status",  # status: v2.7
                                                   "misplaced-name",  # v2.8
                                                   "decision-missing")  # v3.1
                                  or r["kind"] == "retired"]  # v3.0: every retired kind
                      for c in spec["check"]},
            "entry_text": {c["name"]: _refused(lambda c=c: L.entry_text(
                c["id"], c["title"], c["fields"],
                c["sections"] if isinstance(c["sections"], dict) else [tuple(x) for x in c["sections"]],
                **({"filed": c["filed"]} if "filed" in c else {}),
                **({"declared_fields": c["declared_fields"]} if "declared_fields" in c else {})))  # v2.8
                for c in spec["entry_text"]},
            "log": {c["name"]: log(c) for c in spec.get("log", [])},
            "archive_plan": {c["name"]: plan(c) for c in spec.get("archive_plan", [])}}


def lift_cases(L, spec: dict, root: Path = HERE) -> dict:
    """Lifting a gate (v2.4): ``lift_gate()``, ``decide_lift()`` and their outputs compared, ``reassign_gate()`` and
    ``reassigns()``, ``check()``'s reassign note, ``closes()``, ``edit_item(close=)``, ``waiting_only()``,
    ``parse_closed_items()``, ``answered_by()`` and its problems over a v2 board read as a ``Board``, and the
    waiting-only refusals of ``item_file()`` and ``item_file_problem()``. Each entry is a file of ``lift/entries/``;
    an item is an item file named from ``items`` (v3.0: v2.x named lines)."""
    if not hasattr(L, "decide_lift"):  # a module older than v2.4
        return {"missing": "the module has no decide_lift — older than v2.4"}
    d = root / "lift" / "entries"
    today = date.fromisoformat(spec["today"])

    def entry(tid):
        return (d / f"{tid}.md").read_text(encoding="utf-8")
    items = spec["items"]  # v3.0: item files, by name
    takes_archived = "archived" in inspect.signature(L.decide_lift).parameters  # v2.6

    def decide(c):
        if "archived" in c and not takes_archived:  # a v2.4 module is never handed the keyword
            return {"missing": "the module's decide_lift takes no archived — older than v2.6"}
        return _refused(lambda: L.decide_lift(
            items[c["line"]], {t: entry(t) for t in c["entries"]}, c["label"], c["by"],
            spec["today"],
            c["people"], c["answered_by"], **({"archived": c["archived"]} if "archived" in c else {})))
    decided = {c["name"]: decide(c) for c in spec["decide_lift"]}
    lifted = {c["name"]: _refused(lambda c=c: L.lift_gate(
        entry(c["file"]), c["gate"], c["by"], today=c.get("today", spec["today"]),
        **{k: c[k] for k in ("answer", "evidence", "suffix", "override", "people", "answered_by") if k in c}))
        for c in spec["lift_gate"]}

    def after(c):
        base = {t: entry(t) for t in ("TD-500", "TD-501", "TD-502", "TD-521", "TD-530")}
        return {**base, **decided[c["after"]]["ok"]} if "after" in c else base

    def close(c):
        return _refused(lambda: L.edit_item(items[c["line"]], c.get("action", "decide"), answer=c.get("answer"),
                                            reply=c.get("reply"), by=c["by"], today=today, close=True))

    def board(text):  # v3.0: a v2 board's text read as the Board the readers take, through a one-file map
        return L.load_board("board.md", lambda p: None, {"board.md": text}.get)
    ledger = "# Ledger\n\nLedgerboard: 2\n\n" + "\n".join(entry(t) for t in spec["check"])
    return {
        "decide_lift": decided,
        "lift_gate": lifted,
        "same_text": [decided[c["decide"]]["ok"][c["id"]] == lifted[c["lift"]]["ok"] for c in spec["same_text"]],
        "reassign": {c["name"]: _refused(lambda c=c: L.reassign_gate(
            entry(c["file"]), c["frm"], c["to"], by=c["by"], why=c["why"], today=spec["today"]))
            for c in spec["reassign"]},
        "reassigns": [L.reassigns(entry(t), g) for t, g in spec["reassigns"]],
        "check": [r for r in L.check(ledger, "", today=spec["today"]) if r["kind"] == "gate-reassigned-often"],
        "closes": [decided[c["after"]] if "missing" in decided.get(c.get("after"), {})
                   else L.closes(items[c["line"]], c["label"], after(c)) for c in spec["closes"]],
        "close": {c["name"]: close(c) for c in spec["close"]},
        "waiting_only": {x: L.waiting_only(x) for x in spec["waiting_only"]},
        "closed_items": [[{"line": it.line, "words": it.words, "kind": it.kind, "answers": it.answers, "lifts": it.lifts,
                           "parts": it.parts, "decided": it.decided, "decided_by": it.decided_by, "detail": it.detail}
                          for it in L.parse_closed_items(b)] for b in spec["closed_items"]],
        "answered_by": [{"value": L.answered_by(board(b)), "problems": [list(x) for x in L.answered_by_problems(board(b))]}
                        for b in spec["answered_by"]],
        "item_files": [_refused(lambda c=c: L.item_file(
            c["text"], c["due"], spec["today"], c["session"], c["host"], c["context"],
            **{k: c[k] for k in ("kind", "answers", "default", "detail", "lifts") if k in c}))
            for c in spec["item_files"]],
        "item_file_problems": [L.item_file_problem(t) for t in spec["item_file_problems"]],
    }


def ids_cases(L, spec: dict) -> dict:
    """The next id (v2.4): ``parse_take()`` of counter commits, ``next_id()``, ``ids_held()`` of a v1 pair and a
    v2 directory (a newer major refused), and ``judge_takes()`` of new ids against a fixture counter's takes."""
    if not hasattr(L, "judge_takes"):  # a module older than v2.4
        return {"missing": "the module has no judge_takes — older than v2.4"}
    return {
        "parse_take": [L.parse_take(c["subject"], c["body"]) for c in spec["parse_take"]],
        "next_id": [list(L.next_id(c["last"], c["ids"], c["floor"])) for c in spec["next_id"]],
        "ids_held": {c["name"]: _refused(lambda c=c: sorted(L.ids_held(c["files"]))) for c in spec["ids_held"]},
        "judge_takes": {c["name"]: [[list(x) for x in r] for r in L.judge_takes(
            c["new"], c["takes"], c["entries"], c["branch"], "main")]
            for c in spec["judge_takes"]},
    }


def sweep_cases(L, spec: dict, root: Path = HERE) -> dict:
    """The gate sweep (v2.4): ``sweep()`` over ``sweep/``'s ledger, archive and boards on each run's dates, the same
    sweep again once the first run's items are filed and its closes made (it writes nothing new), ``covers()``
    of entries and gates, and the refusals. Each board is read whole through ``load_board()`` (v3.0), from a map of
    ``sweep/``'s files. The rerun reads each v2 board's split (v3.0, F150): the first run's closes made as moves by
    id and its filings written with ``item_file()``; ``widgets.md``'s first ``TD-239`` closed line, which the
    split refuses beside its twin, is dropped in memory for the rerun alone (F385). The ``split`` case reads
    ``split_board()`` of its v2 board, put in the map under its directory (F383)."""
    if not hasattr(L, "sweep"):
        return {"missing": "the module has no sweep — older than v2.4"}
    d = root / "sweep"
    files = {p.relative_to(d).as_posix(): p.read_text(encoding="utf-8") for p in sorted(d.rglob("*")) if p.is_file()}
    if "split" in spec:  # v3.0: the split case's directory is the v2 board's split, in memory
        sb = next(b for b in spec["boards"] if b["basename"] == spec["split"]["basename"])
        files.update({f"{spec['split']['dir']}/{k}": v for k, v in L.split_board(files[sb["board"]]).items()})
    ents = [files["ledger.md"], files["archive.md"]]
    results = {(r[0], r[1]): (r[2], r[3]) if len(r) > 3 else r[2] for r in spec["results"]}

    def boards_of(bs, fs=files):
        return [(b["url"], b["basename"], L.load_board(b.get("dir") or b["board"], dict_ls(fs), fs.get)) for b in bs]
    boards = boards_of(spec["boards"])

    def run(c, bs=boards, **kw):
        kw.update({"reask_days": c["reask_days"]} if "reask_days" in c else {})  # v2.7: a run's own window
        return L.sweep(ents, bs, results, c["today_utc"], c["today_local"], repo=spec["repo"], **kw)
    runs = {c["name"]: run(c) for c in spec["runs"]}
    first = next(c for c in spec["runs"] if c["name"] == spec["rerun"])
    day = first["today_local"]
    after = dict(files)
    rerun_boards = []
    for b in spec["boards"]:
        name = L.origin_key(b["url"]) or b["basename"]
        ids = set(runs[first["name"]]["to_close"].get(name, []))
        filed = runs[first["name"]]["to_file"].get(name, [])
        if not b.get("dir"):  # a v2 board: the rerun reads its split (v3.0), written beside it in memory
            text = after[b["board"]]
            if b["basename"] == "widgets":  # F385: the first of two closed lines of one id, which the split refuses
                cut = next(ln for ln in text.split("\n") if "TD-239" in ln and "Closed: 2026-10-20" in ln)
                text = text.replace(cut + "\n", "", 1)
            arch = b["board"][:-3] + "_archive.md"
            b = dict(b, dir=b["board"][:-3] + ".split")
            after.update({f"{b['dir']}/{k}": v for k, v in L.split_board(text, after.get(arch, "")).items()})
        rerun_boards.append(b)
        for i in sorted(ids):  # close by id (the file moves), file with item_file()
            src = after.pop(f"{b['dir']}/{i}.md")
            after[f"{b['dir']}/{L.item_path(i, day)}"] = L.edit_item(src, "done", why="swept",
                                                                     today=date.fromisoformat(day))
        for it in filed:
            new = L.item_file(it["text"], None if it["kind"] == "fyi" else day, day, "sweep", None, it["context"],
                              kind=it["kind"], answers=it["answers"], default=it["default"], detail=it["detail"],
                              lifts=it["lifts"])
            after[f"{b['dir']}/{L.item_id(day, hashlib.sha256(new.encode()).hexdigest()[:8])}.md"] = new
    entry = L._entry_texts("\n".join(ents))
    out = {"parts_problems": _parts_cases(L, spec, boards[0])} if spec.get("parts_problems") else {}

    def sets(c):  # v3.0 (B2): a run over a set of boards of its own
        got = run(c, boards_of(c["boards"]))
        return {"to_file": {b: [it["text"] for it in x if c["about"] in it["text"]] for b, x in got["to_file"].items()},
                "to_close": got["to_close"]}

    def compared(got):  # two reads of one board compared (SPEC *Reading a board*): lists sorted by id
        return {"to_file": got["to_file"], "to_close": {b: sorted(x) for b, x in got["to_close"].items()},
                "lifts": sorted(got["lifts"], key=lambda x: (x["id"], x["gate"]))}

    def split(c):  # v3.0 (B2): a v2 board beside its split directory gives the same sweep
        bs = [dict(b, dir=c["dir"]) if b["basename"] == c["basename"] else b for b in spec["boards"]]
        r = next(x for x in spec["runs"] if x["name"] == c["run"])
        return {"same": compared(run(r, boards_of(bs))) == compared(runs[r["name"]]),
                "board_dir_problems": [list(x) for x in L.board_dir_problems(c["dir"], dict_ls(files), files.get)]}
    return {
        **out,
        "runs": runs,
        "rerun": run(first, boards_of(rerun_boards, after)),
        "covers": [[[b, it.id, state] for b, it, state in L.covers(entry[t], g, boards, spec["repo"])]
                   for t, g in spec["covers"]],
        "refused": {c["name"]: _refused(lambda c=c: L.sweep(
            ents, boards, results, "2026-11-03", "2026-11-03", repo=c["repo"],
            **{k: c[k] for k in ("reask_days", "event_age_days") if k in c})) for c in spec["refused"]},
        "sets": {c["name"]: sets(c) for c in spec.get("sets", [])},
        **({"split": split(spec["split"])} if "split" in spec else {}),
    }


def _parts_entry(tid: str, e) -> object:
    """A ``parts_problems`` case's entry: an object is built into an entry's text (its ``status``, ``blocked``
    and ``part_of``); anything else (a text holding no entry, a value that is no string) is given as it is."""
    if not isinstance(e, dict):
        return e
    head = ["**Priority:** Medium", "**Type:** debt", "**Added:** 2026-11-01", f"**Status:** {e.get('status', 'Open')}"]
    head += [f"**Blocked by:** {e['blocked']}"] if e.get("blocked") else []
    head += [f"**Part of:** {e['part_of']}"] if e.get("part_of") else []
    return f"## {tid}: {e.get('title', 'An invented entry')}\n\n" + "\n".join(head) + "\n\n**Why:** Invented.\n"


def _one_item_file(L, line: object) -> object:
    """A case's v2 line as the item file its split gives (v3.0: the readers take an item file), when it is a v2
    board holding one item the split accepts; anything else (a board of two items, a refused one, no string) as
    given, which the readers take as no item."""
    try:
        files = [v for k, v in L.split_board(line).items() if k != L.BOARD_README] if isinstance(line, str) else []
    except L.Refused:
        files = []
    return files[0] if len(files) == 1 else line


def _parts_cases(L, spec: dict, own) -> dict:
    """``parts_problems()`` (v2.6) of each case; a case's line is its ``line``, else a decide built from its
    ``context`` and ``parts``. The readers are given an item file (v3.0): the decide built as one, or a case's line as
    its split's (``_one_item_file()``). ``covers``: each listed part's ``covers()`` on a one-item board holding the line,
    given as this repo's own board. ``lift``: ``decide_lift()`` of ``Go`` by ``pat``, ``People: pat``, with the
    case's ``lift_archived`` (else its ``archived``): the ids it changes and the Log lines it adds, or its
    refusal (each case's entries carry no Log, so every Log line is the lift's)."""
    if not hasattr(L, "parts_problems"):
        return {"missing": "the module has no parts_problems — older than v2.6"}
    out = {}
    for c in spec["parts_problems"]:
        line = c["line"] if "line" in c else (
            f"- [ ] decide 2026-11-06 (session `w-1`) — Go on the builds? Context: {c.get('context', 'TD-4 decision (pat)')}."
            f" Parts: {c.get('parts', 'TD-9, TD-10')}. Due: 2026-11-20. Answers: Go | Not yet.")
        item = _one_item_file(L, line) if "line" in c else (
            f"## Go on the builds?\n\n**Kind:** decide\n**Added:** 2026-11-06\n**Session:** w-1\n"
            f"**Context:** {c.get('context', 'TD-4 decision (pat)')}\n**Parts:** {c.get('parts', 'TD-9, TD-10')}\n"
            "**Due:** 2026-11-20\n**Answers:** Go | Not yet\n")
        ents = {k: _parts_entry(k, v) for k, v in c.get("entries", {}).items()}
        got = {"problems": L.parts_problems(item, ents, c.get("archived", []))}
        if c.get("covers"):
            board = f"# Needs the user\n\nKinds: decide | act | look | watch | fyi\nPeople: pat\n\n{line}\n"
            boards = [(own[0], own[1], L.load_board("board.md", dict_ls({"board.md": board}), {"board.md": board}.get))]
            gate = L.CONTEXT_ANY_GATE_RE.search(L.CONTEXT_RE.search(line).group("ctx")).group(0)
            by_num = {L._num(k): v for k, v in ents.items()}
            got["covers"] = {p: [[b, state] for b, _, state in L.covers(
                by_num[L._num(p)], L._carried(by_num[L._num(p)], gate) or gate, boards, spec["repo"])]
                for p in L.parse_parts(line)}
        if c.get("lift"):
            def lift(c=c, line=line, ents=ents):
                new = L.decide_lift(item, ents, "Go", "pat", "2026-11-06", ["pat"], None,
                                    archived=c.get("lift_archived", c.get("archived", [])))
                return {k: [ln["text"] for ln in L.log_lines(t)] for k, t in sorted(new.items())}  # no case's entry has a Log
            got["lift"] = _refused(lift)
        out[c["name"]] = got
    return out


def host_log_cases(L, spec: dict) -> dict:
    """A host-log check counted over records (v2.5): ``first_instant()`` and ``count_host_log()``, no file read."""
    if not hasattr(L, "count_host_log"):
        return {"missing": "the module has no count_host_log — older than v2.5"}

    def rec(r):
        at = r.get("at")
        if isinstance(at, str) and at.endswith("Z"):
            at = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return {**r, "at": at}

    def count(c):
        return _refused(lambda: L.count_host_log([rec(r) for r in c["records"]], L.parse_check(c["check"]),
                                                 c["since"], public_only=c.get("public_only", False)))
    return {"first_instant": {d: _refused(lambda d=d: L.first_instant(d).isoformat()) for d in spec["first_instant"]},
            "count_host_log": {c["name"]: count(c) for c in spec["count_host_log"]}}


def _fs_board(root: Path, rel: str, L):
    """The board at ``root/rel`` read through ``load_board()`` from the file system (v3.0): a directory's names
    with each subdirectory as ``<name>/``, a file's text read as bytes so its line endings stay."""
    def ls(p: str):
        q = root / p
        return sorted(c.name + "/" if c.is_dir() else c.name for c in q.iterdir()) if q.is_dir() else None

    def read(p: str):
        q = root / p
        return q.read_bytes().decode("utf-8") if q.is_file() else None
    return L.load_board(rel, ls, read)


def verdict_cases(L, spec: dict, root: Path = HERE) -> dict:
    """The merge gate's verdicts (v2.4): ``lift_pr_verdict()``, ``tripwire()`` and ``uncovered_decisions()`` of
    each case's base and head trees. ``verdict/base/`` is every case's base tree; a case's ``cases/<name>/base/``
    and ``cases/<name>/head/`` lay files over it (the head over the base after its own overlay), its ``delete_base``
    names paths the base drops (after its overlay, before the head is laid over it) and its ``delete`` paths the
    head drops, a path ending in ``/`` every path under it (v3.0). Boards another repo holds are under
    ``verdict/boards/``, each a directory or a v2 file (its archive beside it as ``<stem>_archive.md``), read
    through ``load_board()`` (v3.0)."""
    if not hasattr(L, "lift_pr_verdict"):
        return {"missing": "the module has no lift_pr_verdict — older than v2.4"}
    d = root / "verdict"
    shared = tree(d / "base")

    def drop(t: dict, paths: list) -> None:  # v3.0: a path ending in `/` takes every path under it
        for p in paths:
            for k in [k for k in t if k == p or (p.endswith("/") and k.startswith(p))]:
                del t[k]

    def trees(c):
        base = {**shared, **tree(d / "cases" / c["name"] / "base")}
        drop(base, c.get("delete_base", []))
        head = {**base, **tree(d / "cases" / c["name"] / "head")}
        drop(head, c.get("delete", []))
        return base, head

    def verdict(c):
        base, head = trees(c)
        got = L.lift_pr_verdict(base, head, c["files"], c["subject"], c["commits"], c["created_at"],
                                c["merged_at"], spec["repo"])
        return {"carve_out": got["carve_out"], "flags": [list(x) for x in got["flags"]],
                "review": [list(x) for x in got["review"]]}

    def uncovered(c):
        base, head = trees(c)
        boards = [(b["url"], b["basename"], _fs_board(d / "boards", b["board"], L)) for b in c["boards"]]
        refusals, flags = L.uncovered_decisions(base, head, boards, spec["repo"])
        return {"refusals": [list(x) for x in refusals], "flags": [list(x) for x in flags]}
    return {
        "verdict": {c["name"]: verdict(c) for c in spec["verdict"]},
        "tripwire": {c["name"]: [list(x) for x in L.tripwire(*trees(c), c["subject"], spec["repo"])]
                     for c in spec["tripwire"]},
        "uncovered": {c["name"]: uncovered(c) for c in spec["uncovered"]},
    }


def grammar_cases(L, spec: dict) -> dict:
    """The grammar appendix's fixtures (v2.3): each string's verdict, from the module — an item file's ``item_file_problem()`` (v3.0), a rank file's ``rank()`` flags, a ``Blocked by``'s ``parse_gates()``, an Event section's ``parse_event_section()`` (v2.4),
    and (v2.7) a Status value's ``status_problem()``, a Log line's ``log_line()``, a header block's ``canonical()``
    and (v3.0) an ``Added`` value's ``_real_day()``, whole."""
    if not hasattr(L, "parse_gates"):  # a module older than v2.4: this case fails, the others still run
        return {"missing": "the module has no parse_gates — older than v2.4"}
    if not hasattr(L, "status_problem") or not hasattr(L, "_real_day"):  # older than v2.7: the same
        return {"missing": "the module has no status_problem or _real_day — older than v2.7"}

    def status(archived: bool):  # v2.7: a Status value on a minimal entry
        return lambda s: _why(L.status_problem(f"## TD-1: x\n\n**Status:** {s}\n", archived=archived))
    judge = {
        "status-open": status(False),
        "status-resolved": status(True),
        "status-superseded": status(True),
        "status-dropped": status(True),
        "log-line": lambda s: _log_verdict(L.log_line(s)),
        "header-block": lambda s: _why(_refused(lambda: L.canonical(f"## TD-1: x\n\n{s}\n")).get("refused")),
        "added": lambda s: (L._real_day(s), None),  # v3.0: a real date, whole
        "item-file": lambda s: _why(L.item_file_problem(s)),  # v3.0: a whole item file
        "rank-file": lambda s: (not L.rank(s)[1], L.rank(s)[1]),
        "blocked-by": lambda s: _gates_verdict(L.parse_gates(s)),  # v2.4: a person's name is a decision's
        "event-section": lambda s: (L.parse_event_section(s)["problem"] is None, L.parse_event_section(s)["problem"]),
    }
    return {start: {prod: [dict(zip(("accepted", "why"), judge[start](s))) for s in g["accept"] + g["refuse"]]
                    for prod, g in groups.items()}
            for start, groups in spec.items()}


def _why(problem) -> tuple[bool, object]:
    """A judge's verdict from a problem, None when there is none."""
    return problem is None, problem


def _log_verdict(r: dict | None) -> tuple[bool, str | None]:
    """A Log line's verdict (v2.7): read, and not ``malformed`` (a writer's prefix out of its shape)."""
    if r is None:
        return False, "not a Log line"
    return r["kind"] != "malformed", r["kind"] if r["kind"] == "malformed" else None


def _gates_verdict(g: dict) -> tuple[bool, list[str] | None]:
    """A ``Blocked by`` value's verdict (v2.4): read with nothing left unread, else the items left unread."""
    left = [r["item"] for r in g["retired"]] + g["bad"]
    return (not left, left or None)


def origin_cases(L, spec: dict) -> dict:
    """Repos and origins (v2.4): ``origin_key()`` and ``origin_path()`` of each URL, ``item_key()`` of lines
    differing only in a repo's case, ``item_refs()`` of Contexts naming repos, ``parse_blocked()`` of ids, and ``item_file_problem()`` of a `Parts`
    naming one repo in two cases (v3.0; ``item_problem()`` of its v2 line before it)."""
    if not hasattr(L, "origin_key"):
        return {"missing": "the module has no origin_key — older than v2.4"}
    return {"origin_key": {u: {"key": L.origin_key(u), "path": L.origin_path(u)} for u in spec["origin_key"]},
            "item_key": {x: L.item_key(x) for x in spec["item_key"]},
            "item_refs": {x: L.item_refs(x) for x in spec["item_refs"]},
            "blocked": {x: list(L.parse_blocked(x)) for x in spec["blocked"]},
            "item_file_problem": [L.item_file_problem(x) for x in spec.get("item_file_problem", [])]}  # v3.0


def status_cases(L, spec: dict) -> dict:
    """``status_problem()`` of each ``status_problem`` case (v2.7; ``migrate/``'s group until v3.0)."""
    if not hasattr(L, "status_problem"):  # a module older than v2.7
        return {"missing": "the module has no status_problem — older than v2.7"}
    return {"status_problem": {c["name"]: L.status_problem(c["text"], archived=c["archived"])
                               for c in spec["status_problem"]}}


def event_cases(L, spec: dict) -> dict:
    """Events (v2.4): ``parse_check()`` of each check's value (each confinement refusal among them) and
    ``parse_event_section()`` of each section's text."""
    if not hasattr(L, "parse_check"):
        return {"missing": "the module has no parse_check — older than v2.4"}
    return {"parse_check": {x: L.parse_check(x) for x in spec["parse_check"]},
            "parse_event_section": {x: L.parse_event_section(x) for x in spec["parse_event_section"]}}


def tree(d: Path) -> dict[str, str]:
    """Every file under `d`, by its path relative to `d`, read as bytes so line endings are kept."""
    return {str(p.relative_to(d)): p.read_bytes().decode("utf-8")
            for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}


STDOUT = "expected_stdout.txt"  # a writer case holding it has its stdout compared as text (v3.0, board.py show)


def writer_case(L, case: Path, writer: str = "board") -> dict:
    """The writer's (``board.py``'s, ``ledger.py``'s) ``main()`` of the case's argv, in a copy of its ``before/``:
    exit, printed JSON, files after; a usage error's exit is argparse's 2. A case holding ``expected_stdout.txt``
    gives its stdout as text, ``stdout``, and no JSON."""
    board = importlib.import_module(f"{L.__name__}.{writer}")
    argv = json.loads((case / "cmd.json").read_text(encoding="utf-8"))["argv"]
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(case / "before", work)
        out = io.StringIO()
        os.chdir(work)
        try:
            with contextlib.redirect_stdout(out):
                try:
                    code = board.main(argv)
                except SystemExit as e:  # argparse's usage error (exit 2), its message on stderr
                    code = e.code
        finally:
            os.chdir(here)
        if (case / STDOUT).exists():  # v3.0: stdout as text, byte for byte, never stripped or parsed
            return {"exit": code, "out": None, "after": tree(work), "stdout": out.getvalue()}
        printed = out.getvalue().strip()
        return {"exit": code, "out": json.loads(printed) if printed else None, "after": tree(work)}


def v2_case(L, md: Path) -> dict:
    """A v1 case's v2 twin, ``<case>.v2/``: ``split()`` of the v1 texts must write it file for file,
    and ``load()`` of it must give the v1 case's expected JSON, its summary rows aside (none in v2)."""
    d = md.with_name(md.stem + ".v2")
    led, arc, _ = v1_texts(md)
    got = ledger_case(L, md, (*L.load(str(d), fs_ls, fs_read), fs_read(L.rank_path(str(d)))))
    rows, got["rows"] = got["rows"], "(the v1 twin's)"
    got["v2"] = {"split_matches_dir": _refused(lambda: L.split(led, arc)) == {"ok": v2_files(d)},
                 "rows": rows, "problems": L.v2_problems(str(d), fs_ls, fs_read)}
    return got


def v2_expected(want: dict | None) -> dict | None:
    if want is None:
        return None
    return dict(want, rows="(the v1 twin's)", v2={"split_matches_dir": True, "rows": [], "problems": []})


def person_text_cases(L, spec: list) -> dict:
    """Text a person reads (v3.2): each case a call of ``code_tokens()``, ``sentence_problems()``,
    ``person_text_problems()`` or ``title_problems()`` and its result — the tokens, or each problem as
    ``[rule, refuse, line]``, or ``{"error": "ValueError"}`` — or a constant's value (``{"constant": name}``)."""
    out = {}
    for case in spec:
        if "constant" in case:
            out[case["name"]] = getattr(L, case["constant"])
            continue
        try:
            got = getattr(L, case["fn"])(*case.get("args", []), **case.get("kwargs", {}))
        except ValueError:
            out[case["name"]] = {"error": "ValueError"}
            continue
        out[case["name"]] = [list(p) for p in got] if case["fn"] != "code_tokens" else got
    return out


def cases(L, root: Path):
    for md in sorted((root / "ledger").glob("*.md")):
        if not md.name.endswith(".archive.md"):
            yield md.with_suffix(".json"), ledger_case(L, md)
            if md.with_name(md.stem + ".v2").is_dir():
                yield (md.with_suffix(".json"), "v2"), v2_case(L, md)
    for md in sorted((root / "board").glob("*.md")):
        yield md.with_suffix(".json"), board_case(L, md)
    for case in sorted(p for p in (root / "board").glob("*") if p.is_dir() and not p.name.endswith(".v3")):
        yield case / "expected.json", board_case(L, case)  # v3.0: a board and its archive beside it
    for md in sorted([*(root / "board").glob("*.md"),
                      *(p for p in (root / "board").glob("*") if p.is_dir() and not p.name.endswith(".v3"))]):
        if _v3_dir(md).is_dir():  # v3.0: its split
            yield ((md / "expected.json" if md.is_dir() else md.with_suffix(".json")), "v3"), board_v3_case(L, md)
    yield root / "board" / "split_notes.json", board_split_notes(L, root)  # v3.0
    for case in sorted(p for p in (root / "board_split").glob("*") if p.is_dir()):
        yield case / "expected.json", board_split_case(L, case)  # v3.0
    for case in sorted(p for p in (root / "board_dir").glob("*") if p.is_dir()):
        yield case / "expected.json", board_dir_case(L, case)  # v3.0
    spec = json.loads((root / "edit" / "cases.json").read_text(encoding="utf-8"))
    yield root / "edit" / "expected.json", edit_cases(L, spec, root)
    spec = json.loads((root / "item" / "cases.json").read_text(encoding="utf-8"))
    yield root / "item" / "expected.json", item_cases(L, spec)  # v3.0
    if hasattr(L, "__path__"):  # the writers ship in the package; a single module file has none
        for case in sorted(p for p in (root / "board_writer").glob("*") if p.is_dir()):
            yield case, writer_case(L, case)
        for case in sorted(p for p in (root / "ledger_writer").glob("*") if p.is_dir()):
            yield case, writer_case(L, case, "ledger")
    spec = json.loads((root / "ledger_edit" / "cases.json").read_text(encoding="utf-8"))
    yield root / "ledger_edit" / "expected.json", ledger_edit_cases(L, spec, root)
    spec = json.loads((root / "grammar" / "cases.json").read_text(encoding="utf-8"))
    yield root / "grammar" / "expected.json", grammar_cases(L, spec)
    spec = json.loads((root / "origins" / "cases.json").read_text(encoding="utf-8"))
    yield root / "origins" / "expected.json", origin_cases(L, spec)
    spec = json.loads((root / "events" / "cases.json").read_text(encoding="utf-8"))
    yield root / "events" / "expected.json", event_cases(L, spec)
    spec = json.loads((root / "lift" / "cases.json").read_text(encoding="utf-8"))
    yield root / "lift" / "expected.json", lift_cases(L, spec, root)
    spec = json.loads((root / "ids" / "cases.json").read_text(encoding="utf-8"))
    yield root / "ids" / "expected.json", ids_cases(L, spec)
    spec = json.loads((root / "sweep" / "cases.json").read_text(encoding="utf-8"))
    yield root / "sweep" / "expected.json", sweep_cases(L, spec, root)
    spec = json.loads((root / "host-log-pure" / "cases.json").read_text(encoding="utf-8"))
    yield root / "host-log-pure" / "expected.json", host_log_cases(L, spec)
    spec = json.loads((root / "verdict" / "cases.json").read_text(encoding="utf-8"))
    yield root / "verdict" / "expected.json", verdict_cases(L, spec, root)
    spec = json.loads((root / "status" / "cases.json").read_text(encoding="utf-8"))
    yield root / "status" / "expected.json", status_cases(L, spec)
    spec = json.loads((root / "person_text" / "cases.json").read_text(encoding="utf-8"))
    yield root / "person_text" / "expected.json", person_text_cases(L, spec)  # v3.2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--module", type=Path, default=None,
                    help="the package directory to test (or a single module file; default ../ledgerboard)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate the expected JSON (ledgerboard repo only)")
    mode.add_argument("--check-header", action="store_true",
                      help="check the release header of each package file and this set's MANIFEST")
    mode.add_argument("--stamp", metavar="X.Y", help="write this set's MANIFEST for release X.Y")
    mode.add_argument("--check-tracked", action="store_true",
                      help="compare MANIFEST's paths with the NUL-separated paths on stdin (git ls-files -z)")
    a = ap.parse_args(argv)
    for flag, on in (("--stamp", a.stamp is not None), ("--check-tracked", a.check_tracked)):
        if on and a.module is not None:
            print(f"--module is not used with {flag}", file=sys.stderr)
            return 2
    if a.stamp is not None:
        if not RELEASE_ARG_RE.fullmatch(a.stamp):
            print("usage: --stamp <major.minor>", file=sys.stderr)
            return 2
        return _stamp(a.stamp)
    if a.check_tracked:
        return _check_tracked()
    module = a.module if a.module is not None else HERE.parent / "ledgerboard"
    if a.check_header:
        return _check_header(module)
    L = load(module)
    bad = 0
    n = 0
    for path, got in cases(L, HERE):
        n += 1
        twin = isinstance(path, tuple)  # a v2 (v3) case: its v1 (v2) twin's expected JSON is its own
        path, kind = path if twin else (path, None)
        got = json.loads(json.dumps(got, default=str))
        if path.is_dir():  # a writer case: expected.json and the after/ directory
            after = got.pop("after")
            stdout = got.pop("stdout", None)
            if a.write:
                shutil.rmtree(path / "after", ignore_errors=True)
                for rel, text in after.items():
                    (path / "after" / rel).parent.mkdir(parents=True, exist_ok=True)
                    (path / "after" / rel).write_bytes(text.encode("utf-8"))
                if stdout is not None:
                    (path / STDOUT).write_bytes(stdout.encode("utf-8"))
                (path / "expected.json").write_text(
                    json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
                continue
            want = (json.loads((path / "expected.json").read_text(encoding="utf-8"))
                    if (path / "expected.json").exists() else None)
            if stdout is not None and stdout.encode("utf-8") != (path / STDOUT).read_bytes():
                bad += 1
                print(f"FAIL {path.relative_to(HERE)}: the writer's stdout differs from {STDOUT}")
                continue
            if got != want or after != tree(path / "after"):
                bad += 1
                print(f"FAIL {path.relative_to(HERE)}: the writer's output or files differ from the expected")
            continue
        if a.write:
            if not twin:
                path.write_text(json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            continue
        want = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if twin:
            want = v2_expected(want) if kind == "v2" else v3_expected(want)
        if got != want:
            bad += 1
            print(f"FAIL {path.relative_to(HERE)}{f' (its {kind} twin)' if twin else ''}: "
                  "the module's output differs from the expected JSON")
    if a.write:
        print(f"wrote {n} expected file(s)")
        return 0
    print(f"{n - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
