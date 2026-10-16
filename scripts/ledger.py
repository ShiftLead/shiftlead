#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/ledger.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""What in the TD ledger may be picked now, and what is blocked on what (TD-064).

    ledger.py --pickable [--ledger PATH] [--archive PATH] [--json]

An entry may carry one optional field, between **Status:** and **Location:** (cadence.md §2):

    **Blocked by:** TD-047, TD-042
    **Blocked by:** decision (Paul) — docs/user_attention.md, 2026-09-25 item

Comma-separated entry IDs, then optionally ``decision (<who>)`` — last, because the pointer
after it runs to the end of the line and may hold anything. An ID may name another repo's entry
(TD-071), ``<repo>#TD-NNN`` — ``<repo>`` a roster path's basename, or ``owner/name`` (its origin)
when basenames collide:

    **Blocked by:** dev-cadence#TD-036, TD-120

It resolves through this machine's roster (cadence.md §9, ``$DEV_CADENCE_REG_DIR`` honoured) to
that clone's ledger and archive, read from its ``origin/<default>`` when the ref exists, else its
working tree; it lifts when the entry is in that archive. Anything it cannot resolve keeps the block. **Pickable is derived, never written:** an entry is pickable when
it has no Blocked by field, or every entry it names is archived and it names no decision.
So archiving a blocker makes its dependents pickable with no further edit. A written
``**Pickable:**`` line is only a field: it never overrides the derived one, and a disagreement is flagged.

An entry may also carry ``**Type:** debt | feature`` (cadence.md §2.11); no field reads as debt.
Within one Priority, debt is picked before features.

``--pickable`` prints the pick order — the rank (ledgerboard SPEC *The rank*, TD-119): entries fall into
cards (joined by Blocked by), cards go by key, and within a card an entry follows what it is blocked by. An
entry's key is its line in the rank file beside the ledger (``<ledger stem>_rank.yml``,
``docs/technical_debt_rank.yml``) when it has one, else Priority (High, Medium, Low, then anything else),
then Type (debt before feature), then id; a card's key is its best lined key, else its best one — then
the blocked entries with their blockers, then flags: a rank file line it cannot read, a blocker that names no
entry in the ledger or the archive, an item the field cannot read, a Type it does not know
(read as debt), and a block whose
blockers are all archived (pickable now; the field can go). Which entries a given picker
also excludes (a sibling's lease, a brief's own rules) is the picker's business, not this.
``--list`` prints every entry the filters keep, in the same order; ``--where`` terms are ANDed,
match the first word case-insensitively, and ``FIELD=`` keeps an entry without the field.
``type`` and ``priority`` match the derived value (no Type is debt). ``--counts`` counts per value.
What to *do* with a field (lanes, routing) is the orchestrator's, never this script's.

``--check`` prints only the flags and exits 1 when an error stands (TD-073) — every ⚠: an unknown
Type, a value outside a declared vocabulary, a Blocked by item it cannot read or resolve, a
``Fields:`` line it cannot read. ℹ lines stay information. ``--check --since REF`` judges an edit,
not the ledger: an entry counts only when its header block differs from the one at REF (or is new),
and a ``Fields:`` flag only when the declaration changed, so a ledger that was never clean passes
and the edit that adds one more bad field does not. On a counted entry two more things are errors:
a written Pickable that disagrees with the derived one, and — when the ledger declares vocabularies
at all — a header field that is neither the cadence's nor declared. Standing flags are counted, not
printed. ``--json``: ``{"flags": [{"level": error|info, "id", "field", "kind", "text", "standing"}],
"errors": N}`` — key on ``kind`` and ``field``, never on the sentence. Kinds: fields-decl, below-header,
type, vocabulary, blocked-item, cross-repo, blocked-unknown, blockers-archived, pickable-disagrees,
undeclared-field, rank (a rank file line). ``check_cadence.py``'s ``ledger`` row runs the same check on a PR's ledger edit.

Defaults: ``docs/technical_debt.md`` and ``docs/technical_debt_archive.md`` at the top of
the git work tree the command runs in. Offline, read-only. Exit 0 (``--check``: 1 on an error);
2 when the ledger, or ``--since``'s ref, cannot be read or the arguments are unusable. A detector,
never a gate (cadence.md §7): ``--check`` is what lets a caller choose to gate on it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledgerboard as LB  # noqa: E402  # sibling SYNC file: the ledger format, defined once (ShiftLead/ledgerboard)
import nudge_user_attention as N  # noqa: E402  # sibling SYNC script: the roster, origin and default-branch readers (§9) — the resolver only
from ledgerboard import (  # noqa: E402,F401  # re-exported: readers and tests reach them as ledger.<name>
    BLOCKED_RE,
    CADENCE_FIELDS,
    COMMENT_RE,
    DECISION_RE,
    EDIT_ERRORS,
    FIELD_RE,
    FIELDS_DECL_RE,
    HEADING_RE,
    ID_ITEM_RE,
    PRIORITIES,
    PRIORITY_RE,
    ROW_RE,
    SECTION_RE,
    TYPE_RE,
    TYPES,
    WORD_RE,
    XREPO_ITEM_RE,
    _num,
    declared,
    entries,
    field_key,
    first_word,
    header_block,
    parse_blocked,
)
from ledgerboard import heading_nums as _heading_nums  # noqa: E402

LEDGER_REL, ARCHIVE_REL = "docs/technical_debt.md", "docs/technical_debt_archive.md"
ALIASES = ("type", "owner", "kind")  # --type X is --where type=X, and so on


GIT_TIMEOUT = float(os.environ.get("LEDGER_GIT_TIMEOUT", "10"))  # s per git call into another clone; tests shorten it


def _git(root: Path, *args: str) -> str | None:
    """stdout of one git call in another clone, or None on any failure — a timeout included, so one
    hung roster repo leaves its items unresolved (blocked, flagged) instead of failing the run."""
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None


class Roster:
    """Resolves ``<repo>#TD-NNN`` through this machine's roster; each repo is read once, and only when asked."""

    def __init__(self) -> None:
        self._roots: list[Path] | None = None
        self._read: dict[Path, dict] = {}

    def _find(self, repo: str) -> tuple[Path | None, str]:
        if self._roots is None:
            reg = N.read_registry()
            self._roots = reg or []
            if reg is None:
                return None, "no roster on this machine"
        if "/" in repo:
            hits = [r for r in self._roots
                    if (N._local_origin(r) or "").rstrip("/").lower().endswith("/" + repo.lower())]
        else:
            hits = [r for r in self._roots if r.name.lower() == repo.lower()]
        if not hits:
            return None, "not on this machine's roster"
        if len(hits) > 1:
            return None, (f"{len(hits)} roster repos are named {repo} — write owner/name")
        return hits[0], ""

    def _repo(self, root: Path) -> dict:
        if root not in self._read:
            branch = N.default_branch(root)
            ref = f"origin/{branch}"
            has_ref = _git(root, "rev-parse", "--verify", "-q", ref) is not None

            def read(rel: str) -> str | None:
                if has_ref:
                    return _git(root, "show", f"{ref}:{rel}")  # a hung or failed show: unreadable, the block stays
                try:
                    return (root / rel).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return None
            led, arch = read(LEDGER_REL), read(ARCHIVE_REL)
            self._read[root] = {"source": ref if has_ref else "working tree", "readable": led is not None,
                                "live": _heading_nums(led), "archived": _heading_nums(arch)}
        return self._read[root]

    def resolve(self, item: str) -> dict:
        """{item, repo, root, source, state: archived | open | unresolved, why} for one ``<repo>#TD-NNN``."""
        repo, tid = XREPO_ITEM_RE.match(item).groups()
        out = {"item": item, "repo": repo, "root": None, "source": None, "state": "unresolved", "why": ""}
        root, why = self._find(repo)
        if root is None:
            out["why"] = why
            return out
        info = self._repo(root)
        out.update(root=str(root), source=info["source"])
        n = _num(tid)
        if not info["readable"]:
            out["why"] = f"no readable {LEDGER_REL} in {root} ({info['source']})"
        elif n in info["archived"]:
            out["state"] = "archived"
        elif n in info["live"]:
            out["state"] = "open"
        else:
            out["why"] = f"{repo} has no {tid} in its ledger or archive ({info['source']})"
        return out


def pickable(ledger: str, archive: str, roster: Roster | None = None, undeclared: bool = False,
             rank_text: str | None = None) -> dict:
    """ledgerboard's pickable, in rank order, with this machine's roster resolving ``<repo>#TD-NNN`` items."""
    return LB.pickable(ledger, archive, (roster or Roster()).resolve, undeclared, rank_text=rank_text)


def check(ledger: str, archive: str, old: str | None = None, roster: Roster | None = None,
          rank_text: str | None = None) -> list[dict]:
    """ledgerboard's check (--check's flags, the rank file's too), with this machine's roster resolving cross-repo items."""
    return LB.check(ledger, archive, old, (roster or Roster()).resolve, rank_text=rank_text)


def _at_ref(ledger: Path, ref: str) -> tuple[str | None, str]:
    """(the ledger's text at ``ref``, why not). A ledger that did not exist at ref is "" — every entry is new."""
    top = _git(ledger.parent, "rev-parse", "--show-toplevel")
    if top is None:
        return None, f"{ledger} is not in a git work tree"
    root = Path(top.strip())
    if _git(root, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}") is None:
        return None, f"no commit {ref!r} in {root}"
    try:
        rel = ledger.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None, f"{ledger} is outside {root}"
    # newlines as read_text() gives them for the working file, or a CRLF ledger makes every entry "changed"
    return (_git(root, "show", f"{ref}:{rel}") or "").replace("\r\n", "\n").replace("\r", "\n"), ""


def value_of(rec: dict, key: str) -> str:
    """What a filter or a count reads: the derived Type and Priority, else the field's first word."""
    if key == "type":
        return rec["type"]
    if key == "priority":
        return rec["priority"].lower()
    return first_word(rec["fields"].get(key))


def select(recs: list[dict], where: list[tuple[str, str]], want_pickable: bool | None) -> list[dict]:
    out = []
    for r in recs:
        if want_pickable is not None and r["pickable"] != want_pickable:
            continue
        if all(value_of(r, k) == v for k, v in where):
            out.append(r)
    return out


def counts(recs: list[dict], by: list[str]) -> list[dict]:
    """One row per combination of values of the ``by`` fields, most entries first; an absent field is ``(none)``."""
    c = Counter(tuple(value_of(r, k) or "(none)" for k in by) for r in recs)
    return [dict(zip(by, vals), count=n) for vals, n in sorted(c.items(), key=lambda kv: (-kv[1], [(v == "(none)", v) for v in kv[0]]))]


def field_summary(res: dict) -> list[dict]:
    """Every field any entry carries, with how many carry it, the values seen, and its vocabulary."""
    seen: dict[str, Counter] = {}
    for r in res["entries"]:
        for k, v in r["fields"].items():
            seen.setdefault(k, Counter())[first_word(v) or "(empty)"] += 1
    keys = [k for k in CADENCE_FIELDS if k in seen] + sorted(k for k in seen if k not in CADENCE_FIELDS)
    keys += [k for k in res["declared"] if k not in seen]
    out = []
    for k in keys:
        vals = seen.get(k, Counter())
        out.append({"field": k, "defined_by": "cadence" if k in CADENCE_FIELDS else
                    ("preamble" if k in res["declared"] else "undeclared"),
                    "entries": sum(vals.values()), "declared": res["declared"].get(k),
                    "values": dict(sorted(vals.items(), key=lambda kv: (-kv[1], kv[0])))})
    return out


def _toplevel() -> Path:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                       timeout=10, check=False)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else Path.cwd()


def _row(r: dict) -> str:
    return f"  {r['id']:<7} {r['priority']:<7} {r['type']:<8} {r['title']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--pickable", nargs="?", const=True, default=None, metavar="yes|no",
                    help="alone: print the pick order, the blocked entries and the flags; "
                         "with --list/--counts: keep only entries whose derived pickable is yes (or no)")
    ap.add_argument("--list", action="store_true", help="print every entry the filters keep, in pick order")
    ap.add_argument("--counts", metavar="FIELD[,FIELD]", help="count the kept entries per value of one or two fields")
    ap.add_argument("--fields", action="store_true", help="every field the entries carry, and each one's vocabulary")
    ap.add_argument("--check", action="store_true", help="print only the flags; exit 1 when an error (⚠) stands")
    ap.add_argument("--since", metavar="REF", help="with --check: count only entries whose header block differs "
                                                   "from the ledger at REF (e.g. origin/<default>), or is new")
    ap.add_argument("--where", action="append", default=[], metavar="FIELD=VALUE",
                    help="keep entries whose FIELD's first word is VALUE (FIELD= : absent or empty); repeatable")
    for name in ALIASES:
        ap.add_argument(f"--{name}", metavar=name.upper(), help=f"same as --where {name}=VALUE")
    ap.add_argument("--ledger", help="default: docs/technical_debt.md at the work tree's top")
    ap.add_argument("--archive", help="default: technical_debt_archive.md beside the ledger")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    modes = [m for m in ("list", "counts", "fields", "check") if getattr(a, m)]
    if a.pickable is not None and not modes:
        if a.pickable is not True:
            ap.error("--pickable yes|no filters --list or --counts; alone, --pickable takes no value")
        modes = ["pickable"]
    if len(modes) != 1:
        ap.error("give exactly one of --pickable, --list, --counts, --fields, --check")
    mode = modes[0]
    if a.since is not None and mode != "check":
        ap.error("--since applies to --check only")
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

    ledger = Path(a.ledger) if a.ledger else _toplevel() / "docs" / "technical_debt.md"
    archive = Path(a.archive) if a.archive else ledger.with_name("technical_debt_archive.md")
    try:
        text = ledger.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"ledger: cannot read {ledger}: {e}", file=sys.stderr)
        return 2
    try:
        arch = archive.read_text(encoding="utf-8", errors="replace")
    except OSError:
        arch = ""  # no archive yet: nothing is archived
    try:
        rank_text = Path(LB.rank_path(str(ledger))).read_text(encoding="utf-8", errors="replace")
    except OSError:
        rank_text = None  # no rank file: every entry's key is its implicit one
    if mode == "check":
        old = None
        if a.since is not None:
            old, why = _at_ref(ledger, a.since)
            if old is None:
                print(f"ledger: --since: {why}", file=sys.stderr)
                return 2
        recs = check(text, arch, old, rank_text=rank_text)
        errors = [r for r in recs if r["level"] == "error"]
        if a.json:
            print(json.dumps({"flags": recs, "errors": len(errors)}, indent=2, ensure_ascii=False))
            return 1 if errors else 0
        for r in recs:
            if not r["standing"]:
                print(r["text"])
        standing = sum(r["standing"] for r in recs)
        print(f"ledger check: {len(errors)} error(s)"
              + (f"; {standing} standing flag(s) on entries unchanged since {a.since}, not shown" if standing else ""))
        return 1 if errors else 0
    res = pickable(text, arch, rank_text=rank_text)

    if mode == "pickable":
        if a.json:
            print(json.dumps({k: res[k] for k in ("pickable", "blocked", "flags")}, indent=2, ensure_ascii=False))
            return 0
        print(f"Pickable ({len(res['pickable'])}), in pick order:")
        for r in res["pickable"]:
            print(_row(r))
        if not res["pickable"]:
            print("  (none)")
        if res["blocked"]:
            print(f"Blocked ({len(res['blocked'])}):")
            for r in res["blocked"]:
                print(f"{_row(r)} — by {', '.join(r['blocked_by'])}")
    elif mode == "list":
        kept = select(res["entries"], where, want)
        if a.json:
            print(json.dumps({"entries": kept, "flags": res["flags"]}, indent=2, ensure_ascii=False))
            return 0
        print(f"Entries ({len(kept)}), in pick order:")
        for r in kept:
            print(_row(r) + ("" if r["pickable"] else f" — blocked by {', '.join(r['blocked_by'])}"))
        if not kept:
            print("  (none)")
    elif mode == "counts":
        rows = counts(select(res["entries"], where, want), by)
        if a.json:
            print(json.dumps({"by": by, "counts": rows, "flags": res["flags"]}, indent=2, ensure_ascii=False))
            return 0
        for row in rows:
            print(f"  {row['count']:>4}  " + "  ".join(f"{k}={row[k]}" for k in by))
        if not rows:
            print("     0")
    else:
        fs = field_summary(res)
        if a.json:
            print(json.dumps({"fields": fs, "flags": res["flags"]}, indent=2, ensure_ascii=False))
            return 0
        for f in fs:
            vocab = f" — declared: {' | '.join(f['declared'])}" if f["declared"] else ""
            vals = ", ".join(f"{v} {n}" for v, n in f["values"].items())
            print(f"  {f['field']:<12} {f['defined_by']:<10} {f['entries']:>3} entries  {vals}{vocab}")
    for f in res["flags"]:
        print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
