---
name: summary-table-conflicts-resolve-row-wise
description: Since TD-1195 shiftlead's ledger is one file per entry, with no Summary table to conflict on; a v1 ledger's conflict still resolves row-wise (cadence §2.5); `ao --json` goes before the subcommand
metadata:
  type: feedback
---

Since TD-1195 (2026-10-28) shiftlead's ledger is `docs/ledger/`: one `TD-NNN.md` per entry, archived ones under
`archive/` (`git mv`), and no stored Summary table (`dev-cadence run ledger.py --summary` prints it). Two
filings never conflict. Two edits to the same entry conflict in that one file, and resolve there.

In a repo still on a v1 ledger (cadence §2.5, dev-cadence TD-137), a summary-table conflict is resolved row by
row, one row per id matching its body, and an archive-tail conflict keeps both. After a rebase,
`grep -c '^| TD-NNN '` each id in the hunk.

Also: `ao --json msg person "…"` — the global `--json` sits before the subcommand; after the text it is read
as part of the message and the call errors with *unrecognized arguments*. Related: [[shiftlead-td-grind-mechanics]].
