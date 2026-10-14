"""`ao repo init` (design §4.7, §5 *The seams*; TD-584, built by TD-591): an empty ledger in ledgerboard
format at the repo's `ledger:` path — the preamble with its `Fields:` declaration and the summary
table's header, no entry — and the archive beside it. It commits nothing and refuses when either file
exists. The one step a repo without dev-cadence needs before ShiftLead reads it."""

from __future__ import annotations

from pathlib import Path

from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard, workorders

from . import repoconfig

# the owner and kind words the lanes filter on (§4.8 *Choosing in a free-pick lane*), the person's
# owner word the one the repo facts count as *for you* (§4.4 *Repo facts*)
FIELDS = (
    f"Fields: Owner = anchor | designer | grinder | {ledger_mod.PERSON_OWNER}; "
    "Kind = build | design-first | live-check | evaluation | decision"
)

LEDGER = f"""# Technical Debt

Known issues, compromises, and deferred work: one entry per problem, open work only. When an entry is
resolved, move its whole body to [`{{archive}}`]({{archive}}), delete its summary row, and replace
**Fix** with `**Resolved:** YYYY-MM-DD (PR #n)`.

The format is defined in ShiftLead/ledgerboard's [`SPEC.md`](https://github.com/ShiftLead/ledgerboard/blob/main/SPEC.md).
IDs are `TD-` plus a zero-padded three-digit number, assigned in order and never reused. An entry's
fields are the `**Name:** value` lines right under its heading, up to the first blank line; pickable
is derived from `**Blocked by:**`, never written.

Ledgerboard: {ledgerboard.FORMAT_MAJOR}

{FIELDS}

---

## Summary

| ID | Title | Priority | Status |
|----|-------|----------|--------|

---

<!-- Entry template:

## TD-001: Short title of the problem

**Priority:** High | Medium | Low
**Added:** YYYY-MM-DD
**Owner:** grinder
**Kind:** build
**Status:** Open
**Location:** `path/to/file.py`

**Why:** what's wrong, how it was found, and the reasoning.

**Fix:** concrete direction(s), and what would count as done.
-->
"""

ARCHIVE = """# Technical Debt Archive

Resolved entries moved from [{ledger}]({ledger}), appended in resolution order. Each keeps its TD number
forever, keeps its **Why**, and replaces **Fix** with `**Resolved:** YYYY-MM-DD (PR #n)`.
"""


def init(root: Path | str) -> list[str]:
    """Write the empty ledger and its archive under `root`, at `.shiftlead.yml`'s `ledger:` (the default
    when it names none); the two paths written, relative to `root`. ValueError when either file is
    there (*a ledger is there: docs/technical_debt.md*) or `ledger:` leaves the repo."""
    root = Path(root)
    rel = repoconfig.load(root).ledger
    arch = ledger_mod.archive_path(rel)
    if not workorders.inside(Path(rel)):
        raise ValueError(f"ledger: {rel} is not a path inside the repo")
    for what, path in (("a ledger", rel), ("an archive", arch)):
        if (root / path).exists():
            raise ValueError(f"{what} is there: {path}")
    led, arc = root / rel, root / arch
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text(LEDGER.format(archive=Path(arch).name), encoding="utf-8")
    arc.write_text(ARCHIVE.format(ledger=Path(rel).name), encoding="utf-8")
    return [rel, arch]
