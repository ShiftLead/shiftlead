#!/usr/bin/env python3
"""Run every ledgerboard fixture against a copy of the ledgerboard package; exit 1 on any difference.

    python3 fixtures/run.py [--module PATH] [--write]
    python3 fixtures/run.py --check-header [--module PATH]

``--module`` is the copy to test (default: ../ledgerboard/ beside this directory), so a consumer
that vendors the package and these fixtures checks its own copy. It is the package's directory,
loaded as a package so its files' relative imports resolve (a single module file, a copy from
before the package, is loaded as a module). ``--write`` regenerates every expected ``*.json`` from
the module instead of comparing — for the ledgerboard repo only, after a deliberate format change;
review the diff. ``--check-header`` checks only the first line of every ``*.py`` file in the
package: a release's ``# ledgerboard v<x.y> sha256:<hex>`` whose hash is that of every byte after
the first line, the same release in each (exit 1 when one is not a release header, its hash does
not match, or two name different releases). Stdlib only.

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
  ``rank_path()`` and ``components()`` of a ledger fixture's entries (v1.2), and ``respace()`` (v2.3); an answer's
  consequence — ``item_record()``'s ``consequences`` and ``decided_line()``'s marked label (v1.3); ``item_line()``'s
  ``kind``, ``answers``, ``default`` and ``detail``, passed when a case carries them, with a case's own
  ``today`` in place of the file's (v2.3); ``item_problem()``, ``canonical_item()`` and ``board_problems()``
  (v2.3), ``archive_subject()`` (v2.3), and ``Hide until`` (v2.3): ``edit_action()``, ``item_key()`` of lines
  that carry one, ``item_line(hide_until=)``, and ``snooze``/``due``; and who answered (v2.3): ``decide``'s
  and ``decided_line()``'s ``by``, and ``board_problems()`` of a board's ``People:`` line; and ``Parts:`` and ``Lifts:`` (v2.3): read,
  ordered and keyed, through every edit, ``item_line(lifts=)`` and the item gate.
- ``archive/<case>.board.md`` and ``<case>.archive.md`` → ``<case>.json`` (v2.3): ``archive_closed()`` of the
  two, read as bytes, or its refusal.
- ``ledger/parts.md`` (v2.1): ``Part of`` — a parent with open and with archived parts, the order,
  and each check; ``components()`` of it joins through the field.
- ``ledger_edit/cases.json`` (+ the entry files it names) → ``ledger_edit/expected.json`` (v2.2): one
  entry's writers — ``canonical()`` of each input (and whether a second pass changes it) and
  ``entry_text()`` of each new entry, and ``edit_entry()`` of each case's steps run in order, or why
  each is refused; and ``check()``'s Part of flags of a ledger before and after an archive
  (``check/``), ``archive-open-parts`` among them.
- ``board_writer/<case>/`` (v2.3): the board writer, ``board.py`` — ``before/`` (the files a command
  starts from), ``cmd.json`` (``{"argv": [...]}``, run in a copy of ``before/``), ``after/`` (every file
  as the command leaves it: a refusal or a ``--plan`` leaves ``before/``'s) and ``expected.json`` (its
  exit code and the JSON it printed: the subject and the paths, the plan, or why it refused).
- ``grammar/cases.json`` → ``grammar/expected.json`` (v2.3): SPEC's grammar appendix — per start symbol and
  production, strings that production's EBNF accepts and refuses, and the module's verdict on each:
  ``item_problem()`` of an item line, ``rank()``'s flags of a rank file, ``is_person()`` of a name.
  ``tests/test_grammar.py`` checks the appendix's EBNF against these verdicts.
- ``ledger/escaped.md`` (v2.2): ``Escaped from`` is the format's own field — a ledger with a
  ``Fields:`` line flags an undeclared field beside it, never it.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
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
        return tuple(table[item]) if item in table else ("unresolved", f"{item} is not in the fixture's resolver")
    p = L.pickable(text, archive, resolve, rank_text=rank_text)
    return {"entries": p["entries"], "pickable": [e["id"] for e in p["pickable"]],
            "blocked": [e["id"] for e in p["blocked"]], "flags": p["flag_recs"],
            "declared": p["declared"], "rows": L.rows(text),
            "check": L.check(text, archive, resolve=resolve, rank_text=rank_text),
            "check_since_empty": L.check(text, archive, old="", resolve=resolve)}


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
            kw = {k: c[k] for k in ("kind", "answers", "default", "detail", "hide_until", "lifts") if k in c}  # v2.3's keywords
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
    def edits(c):
        def run():
            out = text(c)
            for st in c["steps"]:
                dated = st["action"] in ("note", "archive", "reopen")  # the others take no date
                args = {"today": c.get("today", spec["today"])} if dated else {}
                out = L.edit_entry(out, st["action"], **{**args, **st["args"]})
            return out
        return _refused(run)
    return {"canonical": {c["name"]: canon(c) for c in spec["canonical"]},
            "edit_entry": {c["name"]: edits(c) for c in spec["edit_entry"]},
            "check": {c["name"]: [r for r in L.check(text({"file": c["ledger"]}), text({"file": c["archive"]}) if c["archive"] else "",
                                                     old=text({"file": c["old"]}) if c.get("old") else None)
                                  if r["kind"] in ("archive-open-parts", "part-of-archived", "part-of-unknown")]
                      for c in spec["check"]},
            "entry_text": {c["name"]: _refused(lambda c=c: L.entry_text(
                c["id"], c["title"], c["fields"],
                c["sections"] if isinstance(c["sections"], dict) else [tuple(x) for x in c["sections"]]))
                for c in spec["entry_text"]}}


def grammar_cases(L, spec: dict) -> dict:
    """The grammar appendix's fixtures (v2.3): each string's verdict, from the module — an item line's
    ``item_problem()``, a rank file's ``rank()`` flags, a person's name's ``is_person()``."""
    if not hasattr(L, "is_person"):  # a module older than v2.3: this case fails, the others still run
        return {"missing": "the module has no is_person — older than v2.3"}
    judge = {
        "item-line": lambda s: (L.item_problem(s) is None, L.item_problem(s)),
        "rank-file": lambda s: (not L.rank(s)[1], L.rank(s)[1]),
        "person": lambda s: (L.is_person(s), None),
    }
    return {start: {prod: [dict(zip(("accepted", "why"), judge[start](s))) for s in g["accept"] + g["refuse"]]
                    for prod, g in groups.items()}
            for start, groups in spec.items()}


def tree(d: Path) -> dict[str, str]:
    """Every file under `d`, by its path relative to `d`, read as bytes so line endings are kept."""
    return {str(p.relative_to(d)): p.read_bytes().decode("utf-8")
            for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}


def writer_case(L, case: Path) -> dict:
    """``board.py``'s ``main()`` of the case's argv, in a copy of its ``before/``: exit, printed JSON, files after."""
    board = importlib.import_module(L.__name__ + ".board")
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
    spec = json.loads((root / "ledger_edit" / "cases.json").read_text(encoding="utf-8"))
    yield root / "ledger_edit" / "expected.json", ledger_edit_cases(L, spec, root)
    spec = json.loads((root / "grammar" / "cases.json").read_text(encoding="utf-8"))
    yield root / "grammar" / "expected.json", grammar_cases(L, spec)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--module", type=Path, default=HERE.parent / "ledgerboard",
                    help="the package directory to test (or a single module file)")
    ap.add_argument("--write", action="store_true", help="regenerate the expected JSON (ledgerboard repo only)")
    ap.add_argument("--check-header", action="store_true", help="check only the release header of each package file")
    a = ap.parse_args(argv)
    if a.check_header:
        why = headers_problem(a.module)
        print(f"header: {why}" if why else
              f"header: ok ({package_files(a.module)[0].read_bytes().split(b' ', 3)[2].decode()})")
        return 1 if why else 0
    L = load(a.module)
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
