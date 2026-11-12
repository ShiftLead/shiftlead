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
- ``board/<case>.md`` → ``<case>.json``: every open item's ``item_record()`` at ``TODAY``, plus
  ``item_key()`` of every item line and ``closed_items()``, and ``needs_you()`` at ``TODAY`` and ``board_people()`` (v2.3).
- ``edit/cases.json`` → ``edit/expected.json``: ``edit_line()``, ``subject()``, ``subject_kind()``,
  ``item_line()``/``decided_line()``, the line predicates, the version reader (v1.0), and
  ``bold_head()``, ``is_not_right_form()`` and ``fill_not_right()`` (v1.1), and the rank —
  ``queue_subject()``, ``implicit_key()``, ``key_order()``, ``midpoint()``, ``rank()``, ``set_rank()``,
  ``rank_path()`` and ``components()`` of a ledger fixture's entries (v1.2), and ``respace()`` (v2.3), and
  ``split_notes()`` of a README and ``item_notes()`` of a line at the file's ``today`` (v2.4); an answer's
  consequence — ``item_record()``'s ``consequences`` and ``decided_line()``'s marked label (v1.3); ``item_line()``'s
  ``kind``, ``answers``, ``default`` and ``detail``, passed when a case carries them, with a case's own
  ``today`` in place of the file's (v2.3); ``item_problem()``, ``canonical_item()`` and ``board_problems()``
  (v2.3), ``archive_subject()`` (v2.3), and ``Hide until`` (v2.3): ``edit_action()``, ``item_key()`` of lines
  that carry one, ``item_line(hide_until=)``, and ``snooze``/``due``; and who answered (v2.3): ``decide``'s
  and ``decided_line()``'s ``by``, and ``board_problems()`` of a board's ``People:`` line; and ``Parts:`` and ``Lifts:`` (v2.3): read,
  ordered and keyed, through every edit, ``item_line(lifts=)`` and the item gate; and ``item_line(parts=)`` (v2.6):
  the snapshot written in number order, spelled as given, and each of its refusals.
- ``sweep/cases.json`` → ``sweep/expected.json`` (v2.4): ``sweep()`` and ``covers()`` over ``sweep/``'s ledger and
  boards; and ``parts_problems()`` (v2.6) of each ``parts_problems`` case's line against its own entries and
  ``archived``, with, where the case asks, ``covers()`` of each listed part on a one-item board holding the line,
  and the ``decide_lift()`` cross-check of a ``Go``. From v2.7, a lifting answer closed with no lift (TD-224 to
  TD-269): the ``act`` that says its lift is owed, held entries, its close, and a run's own ``reask_days``.
- ``archive/<case>.board.md`` and ``<case>.archive.md`` → ``<case>.json`` (v2.3): ``archive_closed()`` of the
  two, read as bytes, or its refusal.
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
  among them), the Dropped archive, and ``rename_ref`` keeping one copy. From v2.7, ``check()``'s ``retired`` flag on a
  ``Waits`` line (``check/waits_*``): an error where the edit added or changed the line, ℹ where it left it, or with
  no ``old``.
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
  ``cases/<name>/base/``, then its ``cases/<name>/head/`` over that, less its ``delete`` paths.
- ``board_writer/<case>/`` (v2.3): the board writer, ``board.py`` — ``before/`` (the files a command
  starts from), ``cmd.json`` (``{"argv": [...]}``, run in a copy of ``before/``), ``after/`` (every file
  as the command leaves it: a refusal or a ``--plan`` leaves ``before/``'s) and ``expected.json`` (its
  exit code and the JSON it printed: the subject and the paths, the plan, or why it refused).
- ``ledger_writer/<case>/`` (v2.4): the ledger writer, ``ledger.py`` — laid out as ``board_writer/``'s cases, each
  ``argv`` carrying ``--json`` so what it prints is one object: a report, the paths written, the plan, why it
  refused, or the ids it ``needs``.
- ``migrate/cases.json`` → ``migrate/expected.json`` (v2.7): ``migrate_entry()`` of one entry's invented text,
  open or archived, with its ``closed_date``, ``kinds`` and ``decided``; its output run again, which changes
  nothing; and ``status_problem()`` of each form, in its place and out of it.
- ``grammar/cases.json`` → ``grammar/expected.json`` (v2.3): SPEC's grammar appendix — per start symbol and
  production, strings that production's EBNF accepts and refuses, and the module's verdict on each:
  ``item_problem()`` of an item line, ``rank()``'s flags of a rank file, ``parse_gates()`` of a ``Blocked by`` (v2.4,
  whose ``person`` productions hold a person's name), ``parse_event_section()`` of an Event section (v2.4).
  ``tests/test_grammar.py`` checks the appendix's EBNF against these verdicts.
- ``origins/cases.json`` → ``origins/expected.json`` (v2.4): repos and origins — ``origin_key()`` and
  ``origin_path()`` of ssh, https and unreadable URLs; ``item_key()`` of two lines differing only in a repo's
  case (it stays byte-exact); ``item_refs()`` folding a repo's case and reading no ref from a bad repo; and
  ``parse_blocked()`` of ids whose repo is or is not the grammar.
- ``ledger/gates.md`` (v2.4): ``Blocked by``'s gates at ``TODAY`` — an ``until`` past, reached and ahead, an
  ``event``, a decision with and without its Ask, each gate repeated, the retired words (``hold``, ``decision
  (designer)``, the old form, ``Waits``, ``Taken by``, a stage word in Status), a Priority outside the three,
  items the grammar does not read, the words in any case, and a parent's ``parts_gates``.
- ``ledger/events.md`` (v2.4): ``check()``'s events — a section whose text holds quotes, a gate with no section,
  sections whose gates are gone (one explained by its ``gate lifted`` Log line), a name twice, and each section
  the reader refuses.
- ``events/cases.json`` → ``events/expected.json`` (v2.4): ``parse_check()`` of each check type's value, every
  argument confinement refusal among them, and ``parse_event_section()`` of sections well and badly formed.
- ``lift/cases.json`` (+ ``lift/entries/``) → ``lift/expected.json`` (v2.4): lifting a gate — ``lift_gate()`` of
  each shape and each refusal, ``decide_lift()`` of a parent's go (a lift, a kept-waiting and a work-order answer,
  a skipped part, a parent without the gate, a person in another case, an emptied ``Blocked by``, two lifting
  labels, an event's three answers, each refusal), the two compared byte for byte, ``reassign_gate()`` and
  ``reassigns()`` with ``check()``'s note, ``closes()``, ``edit_line(…, close=True)``, ``waiting_only()``,
  ``parse_closed_items()``, ``answered_by()`` and its problems, and the waiting-only label refused by
  ``item_line(lifts=)`` and ``item_problem()``.
- ``ids/cases.json`` → ``ids/expected.json`` (v2.4): the next id — ``parse_take()`` of takes, a range and commits
  that are not takes, ``next_id()`` over ``LAST``, ids and a floor, ``ids_held()`` of each layout, and
  ``judge_takes()`` of each id's ``Id take`` (and, in the transition, its ``Taken by``) against a counter's takes.
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
    """``ls`` for ``load()`` over the file system (SPEC *The ledger as a directory*)."""
    p = Path(path)
    return sorted(c.name for c in p.iterdir() if c.is_file()) if p.is_dir() else None


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
    text = md.read_text(encoding="utf-8")
    items = L.parse_board(text, warn=False)
    return {"items": [L.item_record(i, TODAY) for i in items],
            "people": L.board_people(text),  # v2.3
            "needs_you": [[i.line, cls, days] for i, cls, days in L.needs_you(text, TODAY)],  # v2.3
            "keys": [L.item_key(ln) for ln in text.splitlines() if L.is_item(ln)],
            "closed": L.closed_items(text)}


def archive_case(L, md: Path) -> dict:
    """``archive_closed()`` of a board and its archive, read as bytes so a CRLF case keeps its line endings."""
    board = md.read_bytes().decode("utf-8")
    archive = md.with_name(md.name.replace(".board.md", ".archive.md")).read_bytes().decode("utf-8")
    got = _refused(lambda: L.archive_closed(board, archive))
    return {"refused": got["refused"]} if "refused" in got else {"board": got["ok"][0], "archive": got["ok"][1]}


def edit_cases(L, spec: dict, root: Path = HERE) -> dict:
    today = date.fromisoformat(spec["today"])
    out: dict = {"edits": {}, "subjects": [], "subject_kinds": {}, "compose": [], "predicates": {}, "versions": []}
    for c in spec["edits"]:
        to = date.fromisoformat(c["to"]) if c.get("to") else None
        out["edits"][c["name"]] = _refused(lambda c=c, to=to: L.edit_line(
            c["line"], c["action"], to=to, answer=c.get("answer"), why=c.get("why"),
            reply=c.get("reply"), by=c.get("by"), today=today))
    for c in spec["subjects"]:
        out["subjects"].append(_refused(lambda c=c: L.subject(
            c["tool"], c["action"], c["text"], to=c.get("to"), answer=c.get("answer"), session=c.get("session"))))
    for s in spec["subject_kinds"]:
        out["subject_kinds"][s] = L.subject_kind(s)
    out["edit_actions"] = {s: L.edit_action(s) for s in spec.get("edit_actions", [])}  # v2.3
    out["item_keys"] = {ln: L.item_key(ln) for ln in spec.get("item_keys", [])}  # v2.3: Hide until is stripped
    for c in spec["compose"]:
        if c["fn"] == "item_line":
            kw = {k: c[k] for k in ("kind", "answers", "default", "detail", "hide_until", "lifts", "parts")
                  if k in c}  # v2.3's keywords; parts v2.6
            out["compose"].append(_refused(lambda c=c, kw=kw: L.item_line(
                c["text"], c["due"], c.get("today", spec["today"]), c["session"], c["host"], c["context"], **kw)))
        else:
            by = {"by": c["by"]} if "by" in c else {}  # v2.3: who answered
            out["compose"].append(_refused(lambda c=c, by=by: L.decided_line(
                c["title"], c["ref"], c["answers"], c["default"], c["words"], spec["today"], **by)))
    out["item_problems"] = {ln: L.item_problem(ln) for ln in spec["item_problems"]}  # v2.3: the item gate
    out["canonical_items"] = [_refused(lambda ln=ln: L.canonical_item(ln)) for ln in spec["canonical_items"]]
    out["board_problems"] = [L.board_problems(c["new"], c["old"]) for c in spec["board_problems"]]
    out["archive_subjects"] = [_refused(lambda c=c: L.archive_subject(c["tool"], c["count"], c.get("session")))
                               for c in spec["archive_subjects"]]
    for ln in spec["predicates"]:
        out["predicates"][ln] = {"entry_id": L.entry_id(ln), "row_id": L.row_id(ln), "is_item": L.is_item(ln),
                                 "is_open_item": L.is_open_item(ln), "is_stamp": L.is_stamp(ln),
                                 "is_sweep_stamp": L.is_stamp(ln, ("Swept", "Swept-deep"))}
    for t in spec["versions"]:
        out["versions"].append({"major": L.format_major(t), "problem": L.version_problem(t)})
    out["bold_heads"] = {t: L.bold_head(t) for t in spec["bold_heads"]}
    out["not_right_forms"] = {a: L.is_not_right_form(a) for a in spec["not_right_forms"]}
    out["not_right_fills"] = {c["name"]: _refused(lambda c=c: L.fill_not_right(c["said"], c["offered"]))
                              for c in spec["not_right_fills"]}
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
        out["item_notes"] = ({c["name"]: L.item_notes(L.parse_board(c["line"], warn=False)[0], today)
                              for c in spec["item_notes"]}
                             if hasattr(L, "item_notes") else "the module has no item_notes — older than v2.4")
    out["rank_paths"] = {p: L.rank_path(p) for p in spec["rank_paths"]}
    out["components"] = {f: L.components(L.entries((root / f).read_text(encoding="utf-8")))
                         for f in spec["components"]}
    return out


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
                                                   "log-not-last", "log-line", "event-undated", "status")  # status: v2.7
                                  or (r["kind"], r["field"]) in (("retired", "waits"), ("retired", "location"))]  # v2.7
                      for c in spec["check"]},
            "entry_text": {c["name"]: _refused(lambda c=c: L.entry_text(
                c["id"], c["title"], c["fields"],
                c["sections"] if isinstance(c["sections"], dict) else [tuple(x) for x in c["sections"]],
                **({"filed": c["filed"]} if "filed" in c else {})))
                for c in spec["entry_text"]},
            "log": {c["name"]: log(c) for c in spec.get("log", [])},
            "archive_plan": {c["name"]: plan(c) for c in spec.get("archive_plan", [])}}


def lift_cases(L, spec: dict, root: Path = HERE) -> dict:
    """Lifting a gate (v2.4): ``lift_gate()``, ``decide_lift()`` and their outputs compared, ``reassign_gate()`` and
    ``reassigns()``, ``check()``'s reassign note, ``closes()``, ``edit_line(close=)``, ``waiting_only()``,
    ``parse_closed_items()``, ``answered_by()`` and its problems, and the waiting-only refusals of ``item_line()``
    and ``item_problem()``. Each entry is a file of ``lift/entries/``; a line is named from ``lines``."""
    if not hasattr(L, "decide_lift"):  # a module older than v2.4
        return {"missing": "the module has no decide_lift — older than v2.4"}
    d = root / "lift" / "entries"
    today = date.fromisoformat(spec["today"])

    def entry(tid):
        return (d / f"{tid}.md").read_text(encoding="utf-8")
    lines = spec["lines"]
    takes_archived = "archived" in inspect.signature(L.decide_lift).parameters  # v2.6

    def decide(c):
        if "archived" in c and not takes_archived:  # a v2.4 module is never handed the keyword
            return {"missing": "the module's decide_lift takes no archived — older than v2.6"}
        return _refused(lambda: L.decide_lift(
            lines[c["line"]], {t: entry(t) for t in c["entries"]}, c["label"], c["by"], spec["today"],
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
        return _refused(lambda: L.edit_line(lines[c["line"]][2:].join(["- ", ""]), c.get("action", "decide"),
                                            answer=c.get("answer"), reply=c.get("reply"), by=c["by"],
                                            today=today, close=True))
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
                   else L.closes(lines[c["line"]], c["label"], after(c)) for c in spec["closes"]],
        "close": {c["name"]: close(c) for c in spec["close"]},
        "waiting_only": {x: L.waiting_only(x) for x in spec["waiting_only"]},
        "closed_items": [[{"line": it.line, "text": it.text, "kind": it.kind, "answers": it.answers, "lifts": it.lifts,
                           "parts": it.parts, "decided": it.decided, "decided_by": it.decided_by, "detail": it.detail}
                          for it in L.parse_closed_items(b)] for b in spec["closed_items"]],
        "answered_by": [{"value": L.answered_by(b), "problems": [list(x) for x in L.answered_by_problems(b)]}
                        for b in spec["answered_by"]],
        "item_lines": [_refused(lambda c=c: L.item_line(
            c["text"], c["due"], spec["today"], c["session"], c["host"], c["context"],
            **{k: c[k] for k in ("kind", "answers", "default", "detail", "lifts") if k in c}))
            for c in spec["item_lines"]],
        "item_problems": {ln: L.item_problem(ln) for ln in spec["item_problems"]},
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
            c["new"], c["takes"], c["entries"], c["branch"], "main", accept_taken_by=c["accept_taken_by"])]
            for c in spec["judge_takes"]},
    }


def sweep_cases(L, spec: dict, root: Path = HERE) -> dict:
    """The gate sweep (v2.4): ``sweep()`` over ``sweep/``'s ledger, archive and boards on each run's dates, the same
    sweep again once the first run's items are filed and its closes made (it writes nothing new), ``covers()``
    of entries and gates, and the refusals."""
    if not hasattr(L, "sweep"):
        return {"missing": "the module has no sweep — older than v2.4"}
    d = root / "sweep"

    def read(name):
        return (d / name).read_text(encoding="utf-8") if name else ""
    ents = [read("ledger.md"), read("archive.md")]
    boards = [(b["url"], b["basename"], read(b["board"]), read(b["archive"])) for b in spec["boards"]]
    results = {(r[0], r[1]): (r[2], r[3]) if len(r) > 3 else r[2] for r in spec["results"]}

    def run(c, bs=boards, **kw):
        kw.update({"reask_days": c["reask_days"]} if "reask_days" in c else {})  # v2.7: a run's own window
        return L.sweep(ents, bs, results, c["today_utc"], c["today_local"], repo=spec["repo"], **kw)
    runs = {c["name"]: run(c) for c in spec["runs"]}
    first = next(c for c in spec["runs"] if c["name"] == spec["rerun"])
    after = []
    for url, base, text, archive in boards:
        name = L.origin_key(url) or base
        keys = set(runs[first["name"]]["to_close"].get(name, []))
        lines = [ln.replace("- [ ]", "- [x]", 1) + f" Closed: {first['today_local']} — swept."
                 if L.is_open_item(ln) and L.item_key(ln) in keys else ln for ln in text.split("\n")]
        for it in runs[first["name"]]["to_file"].get(name, []):
            lines.append(L.item_line(it["text"], first["today_local"], first["today_local"], "sweep", None,
                                     it["context"], kind=it["kind"], answers=it["answers"], default=it["default"],
                                     detail=it["detail"], lifts=it["lifts"]).rstrip("\n"))
        after.append((url, base, "\n".join(lines) + "\n", archive))
    entry = L._entry_texts("\n".join(ents))
    out = {"parts_problems": _parts_cases(L, spec, boards[0])} if spec.get("parts_problems") else {}
    return {
        **out,
        "runs": runs,
        "rerun": run(first, after),
        "covers": [[[b, it.text, state] for b, it, state in L.covers(entry[t], g, boards, spec["repo"])]
                   for t, g in spec["covers"]],
        "refused": {c["name"]: _refused(lambda c=c: L.sweep(
            ents, boards, results, "2026-11-03", "2026-11-03", repo=c["repo"],
            **{k: c[k] for k in ("reask_days", "event_age_days") if k in c})) for c in spec["refused"]},
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


def _parts_cases(L, spec: dict, own) -> dict:
    """``parts_problems()`` (v2.6) of each case; a case's line is its ``line``, else a decide built from its
    ``context`` and ``parts``. ``covers``: each listed part's ``covers()`` on a one-item board holding the line,
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
        ents = {k: _parts_entry(k, v) for k, v in c.get("entries", {}).items()}
        got = {"problems": L.parts_problems(line, ents, c.get("archived", []))}
        if c.get("covers"):
            board = f"# Needs the user\n\nKinds: decide | act | look | watch | fyi\nPeople: pat\n\n{line}\n"
            boards = [(own[0], own[1], board, "")]
            gate = L.CONTEXT_ANY_GATE_RE.search(L.CONTEXT_RE.search(line).group("ctx")).group(0)
            by_num = {L._num(k): v for k, v in ents.items()}
            got["covers"] = {p: [[b, state] for b, _, state in L.covers(
                by_num[L._num(p)], L._carried(by_num[L._num(p)], gate) or gate, boards, spec["repo"])]
                for p in L.parse_parts(line)}
        if c.get("lift"):
            def lift(c=c, line=line, ents=ents):
                new = L.decide_lift(line, ents, "Go", "pat", "2026-11-06", ["pat"], None,
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


def verdict_cases(L, spec: dict, root: Path = HERE) -> dict:
    """The merge gate's verdicts (v2.4): ``lift_pr_verdict()``, ``tripwire()`` and ``uncovered_decisions()`` of
    each case's base and head trees. ``verdict/base/`` is every case's base tree; a case's ``cases/<name>/base/``
    and ``cases/<name>/head/`` lay files over it (the head over the base after its own overlay), and its
    ``delete`` names paths the head drops. Boards another repo holds are files of ``verdict/boards/``."""
    if not hasattr(L, "lift_pr_verdict"):
        return {"missing": "the module has no lift_pr_verdict — older than v2.4"}
    d = root / "verdict"
    shared = tree(d / "base")

    def trees(c):
        base = {**shared, **tree(d / "cases" / c["name"] / "base")}
        head = {**base, **tree(d / "cases" / c["name"] / "head")}
        for p in c.get("delete", []):
            head.pop(p, None)
        return base, head

    def verdict(c):
        base, head = trees(c)
        got = L.lift_pr_verdict(base, head, c["files"], c["subject"], c["commits"], c["created_at"],
                                c["merged_at"], spec["repo"])
        return {"carve_out": got["carve_out"], "flags": [list(x) for x in got["flags"]],
                "review": [list(x) for x in got["review"]]}

    def uncovered(c):
        base, head = trees(c)
        boards = [(b["url"], b["basename"], (d / "boards" / b["board"]).read_text(encoding="utf-8"),
                   (d / "boards" / b["archive"]).read_text(encoding="utf-8") if b["archive"] else "")
                  for b in c["boards"]]
        refusals, flags = L.uncovered_decisions(base, head, boards, spec["repo"])
        return {"refusals": [list(x) for x in refusals], "flags": [list(x) for x in flags]}
    return {
        "verdict": {c["name"]: verdict(c) for c in spec["verdict"]},
        "tripwire": {c["name"]: [list(x) for x in L.tripwire(*trees(c), c["subject"], spec["repo"])]
                     for c in spec["tripwire"]},
        "uncovered": {c["name"]: uncovered(c) for c in spec["uncovered"]},
    }


def grammar_cases(L, spec: dict) -> dict:
    """The grammar appendix's fixtures (v2.3): each string's verdict, from the module — an item line's
    ``item_problem()``, a rank file's ``rank()`` flags, a ``Blocked by``'s ``parse_gates()``, an Event section's ``parse_event_section()`` (v2.4),
    and (v2.7) a Status value's ``status_problem()``, a Log line's ``log_line()``, a header block's ``canonical()``
    and an ``Added`` value's ``migrate_entry()``."""
    if not hasattr(L, "parse_gates"):  # a module older than v2.4: this case fails, the others still run
        return {"missing": "the module has no parse_gates — older than v2.4"}
    if not hasattr(L, "status_problem") or not hasattr(L, "migrate_entry"):  # older than v2.7: the same
        return {"missing": "the module has no status_problem or migrate_entry — older than v2.7"}

    def status(archived: bool):  # v2.7: a Status value on a minimal entry
        return lambda s: _why(L.status_problem(f"## TD-1: x\n\n**Status:** {s}\n", archived=archived))
    judge = {
        "status-open": status(False),
        "status-resolved": status(True),
        "status-superseded": status(True),
        "status-dropped": status(True),
        "log-line": lambda s: _log_verdict(L.log_line(s)),
        "header-block": lambda s: _why(_refused(lambda: L.canonical(f"## TD-1: x\n\n{s}\n")).get("refused")),
        "added": lambda s: _added_verdict(L.migrate_entry(f"## TD-1: x\n\n**Added:** {s}\n**Status:** Open\n",
                                                          archived=False, today=TODAY)),
        "item-line": lambda s: (L.item_problem(s) is None, L.item_problem(s)),
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


def _added_verdict(got: dict) -> tuple[bool, list[str] | None]:
    """An ``Added`` value's verdict (v2.7): ``migrate_entry()`` changes nothing, lists nothing and stops on nothing
    (an entry it stops on is not one it leaves alone)."""
    left = got["changes"] + got["listed"] + got["stops"]
    return not left, left or None


def _gates_verdict(g: dict) -> tuple[bool, list[str] | None]:
    """A ``Blocked by`` value's verdict (v2.4): read with nothing left unread, else the items left unread."""
    left = [r["item"] for r in g["retired"]] + g["bad"]
    return (not left, left or None)


def origin_cases(L, spec: dict) -> dict:
    """Repos and origins (v2.4): ``origin_key()`` and ``origin_path()`` of each URL, ``item_key()`` of lines
    differing only in a repo's case, ``item_refs()`` of Contexts naming repos, ``parse_blocked()`` of ids."""
    if not hasattr(L, "origin_key"):
        return {"missing": "the module has no origin_key — older than v2.4"}
    return {"origin_key": {u: {"key": L.origin_key(u), "path": L.origin_path(u)} for u in spec["origin_key"]},
            "item_key": {x: L.item_key(x) for x in spec["item_key"]},
            "item_refs": {x: L.item_refs(x) for x in spec["item_refs"]},
            "blocked": {x: list(L.parse_blocked(x)) for x in spec["blocked"]},
            "item_problem": {x: L.item_problem(x) for x in spec.get("item_problem", [])}}


def migrate_cases(L, spec: dict) -> dict:
    """``migrate_entry()`` of one entry (v2.7), each case's text with ``archived`` and its own ``closed_date``,
    ``kinds`` and ``decided`` at the file's ``today``; ``again`` is its output run once more without ``decided``
    (null after a stop), which must change nothing; ``gate_age`` (a case naming a ``gate``) that gate's age before
    and after; and ``status_problem()`` of each ``status_problem`` case."""
    if not hasattr(L, "migrate_entry"):  # a module older than v2.7
        return {"missing": "the module has no migrate_entry — older than v2.7"}

    def run(c: dict) -> dict:
        kw = {k: c[k] for k in ("closed_date", "kinds", "decided") if k in c}
        got = L.migrate_entry(c["text"], archived=c["archived"], today=c.get("today", spec["today"]), **kw)
        if "gate" in c:  # a gate's age before and after: a line migrate writes first in the Log moves it
            got = dict(got, gate_age=[str(L.gate_age(t, c["gate"])) for t in (c["text"], got["text"])])
        if got["stops"]:
            return dict(got, again=None)
        kw.pop("decided", None)
        again = L.migrate_entry(got["text"], archived=c["archived"], today=c.get("today", spec["today"]), **kw)
        return dict(got, again={"same_text": again["text"] == got["text"], "changes": again["changes"],
                                "stops": again["stops"]})

    return {"migrate_entry": {c["name"]: run(c) for c in spec["migrate_entry"]},
            "status_problem": {c["name"]: L.status_problem(c["text"], archived=c["archived"])
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


def writer_case(L, case: Path, writer: str = "board") -> dict:
    """The writer's (``board.py``'s, ``ledger.py``'s) ``main()`` of the case's argv, in a copy of its ``before/``:
    exit, printed JSON, files after."""
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
                code = board.main(argv)
        finally:
            os.chdir(here)
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


def cases(L, root: Path):
    for md in sorted((root / "ledger").glob("*.md")):
        if not md.name.endswith(".archive.md"):
            yield md.with_suffix(".json"), ledger_case(L, md)
            if md.with_name(md.stem + ".v2").is_dir():
                yield (md.with_suffix(".json"), "v2"), v2_case(L, md)
    for md in sorted((root / "board").glob("*.md")):
        yield md.with_suffix(".json"), board_case(L, md)
    for md in sorted((root / "archive").glob("*.board.md")):
        yield md.with_name(md.name.removesuffix(".board.md") + ".json"), archive_case(L, md)
    spec = json.loads((root / "edit" / "cases.json").read_text(encoding="utf-8"))
    yield root / "edit" / "expected.json", edit_cases(L, spec, root)
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
    spec = json.loads((root / "migrate" / "cases.json").read_text(encoding="utf-8"))
    yield root / "migrate" / "expected.json", migrate_cases(L, spec)


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
        twin = isinstance(path, tuple)  # a v2 case: its v1 twin's expected JSON is its own
        path = path[0] if twin else path
        got = json.loads(json.dumps(got, default=str))
        if path.is_dir():  # a writer case: expected.json and the after/ directory
            after = got.pop("after")
            if a.write:
                shutil.rmtree(path / "after", ignore_errors=True)
                for rel, text in after.items():
                    (path / "after" / rel).parent.mkdir(parents=True, exist_ok=True)
                    (path / "after" / rel).write_bytes(text.encode("utf-8"))
                (path / "expected.json").write_text(
                    json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
                continue
            want = (json.loads((path / "expected.json").read_text(encoding="utf-8"))
                    if (path / "expected.json").exists() else None)
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
            want = v2_expected(want)
        if got != want:
            bad += 1
            print(f"FAIL {path.relative_to(HERE)}{' (its v2 twin)' if twin else ''}: "
                  "the module's output differs from the expected JSON")
    if a.write:
        print(f"wrote {n} expected file(s)")
        return 0
    print(f"{n - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
