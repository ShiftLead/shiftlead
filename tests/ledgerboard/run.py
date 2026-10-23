#!/usr/bin/env python3
"""Run every ledgerboard fixture against a copy of ledgerboard.py; exit 1 on any difference.

    python3 fixtures/run.py [--module PATH] [--write]
    python3 fixtures/run.py --check-header [--module PATH]

``--module`` is the copy to test (default: ../ledgerboard.py beside this directory), so a consumer
that vendors the module and these fixtures checks its own copy. ``--write`` regenerates every
expected ``*.json`` from the module instead of comparing — for the ledgerboard repo only, after a
deliberate format change; review the diff. ``--check-header`` checks only the module's first line:
a release's ``# ledgerboard v<x.y> sha256:<hex>`` whose hash is that of every byte after the first
line (exit 1 when it is not a release header, or the hash does not match). Stdlib only.

Fixtures, each an invented input and its expected JSON:
- ``ledger/<case>.md`` (+ ``<case>.archive.md``, optional ``<case>.resolve.json`` mapping a
  ``<repo>#TD-NNN`` item to ``[state, why]``, optional ``<case>.rank.yml``, its rank file) →
  ``<case>.json``: ``pickable()`` and ``check()``.
- ``board/<case>.md`` → ``<case>.json``: every open item's ``item_record()`` at ``TODAY``, plus
  ``item_key()`` of every item line and ``closed_items()``.
- ``edit/cases.json`` → ``edit/expected.json``: ``edit_line()``, ``subject()``, ``subject_kind()``,
  ``item_line()``/``decided_line()``, the line predicates, the version reader (v1.0), and
  ``bold_head()``, ``is_not_right_form()`` and ``fill_not_right()`` (v1.1), and the rank —
  ``queue_subject()``, ``implicit_key()``, ``key_order()``, ``midpoint()``, ``rank()``, ``set_rank()``,
  ``rank_path()`` and ``components()`` of a ledger fixture's entries (v1.2); an answer's
  consequence — ``item_record()``'s ``consequences`` and ``decided_line()``'s marked label (v1.3).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
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


def load(path: Path):
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


def ledger_case(L, md: Path) -> dict:
    text = md.read_text(encoding="utf-8")
    arch = md.with_name(md.stem + ".archive.md")
    archive = arch.read_text(encoding="utf-8") if arch.exists() else ""
    res = md.with_name(md.stem + ".resolve.json")
    table = json.loads(res.read_text(encoding="utf-8")) if res.exists() else {}

    rk = md.with_name(md.stem + ".rank.yml")
    rank_text = rk.read_text(encoding="utf-8") if rk.exists() else None

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
            "keys": [L.item_key(ln) for ln in text.splitlines() if L.is_item(ln)],
            "closed": L.closed_items(text)}


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
    for c in spec["compose"]:
        if c["fn"] == "item_line":
            out["compose"].append(_refused(lambda c=c: L.item_line(
                c["text"], c["due"], spec["today"], c["session"], c["host"], c["context"])))
        else:
            out["compose"].append(_refused(lambda c=c: L.decided_line(
                c["title"], c["ref"], c["answers"], c["default"], c["words"], spec["today"])))
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
    out["rank_paths"] = {p: L.rank_path(p) for p in spec["rank_paths"]}
    out["components"] = {f: L.components(L.entries((root / f).read_text(encoding="utf-8")))
                         for f in spec["components"]}
    return out


def cases(L, root: Path):
    for md in sorted((root / "ledger").glob("*.md")):
        if not md.name.endswith(".archive.md"):
            yield md.with_suffix(".json"), ledger_case(L, md)
    for md in sorted((root / "board").glob("*.md")):
        yield md.with_suffix(".json"), board_case(L, md)
    spec = json.loads((root / "edit" / "cases.json").read_text(encoding="utf-8"))
    yield root / "edit" / "expected.json", edit_cases(L, spec, root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--module", type=Path, default=HERE.parent / "ledgerboard.py")
    ap.add_argument("--write", action="store_true", help="regenerate the expected JSON (ledgerboard repo only)")
    ap.add_argument("--check-header", action="store_true", help="check only the module's release header")
    a = ap.parse_args(argv)
    if a.check_header:
        why = header_problem(a.module.read_bytes())
        print(f"header: {why}" if why else f"header: ok ({a.module.read_bytes().split(b' ', 3)[2].decode()})")
        return 1 if why else 0
    L = load(a.module)
    bad = 0
    n = 0
    for path, got in cases(L, HERE):
        n += 1
        got = json.loads(json.dumps(got, default=str))
        if a.write:
            path.write_text(json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            continue
        want = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if got != want:
            bad += 1
            print(f"FAIL {path.relative_to(HERE)}: the module's output differs from the expected JSON")
    if a.write:
        print(f"wrote {n} expected file(s)")
        return 0
    print(f"{n - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
