---
name: summary-table-conflicts-resolve-row-wise
description: Since TD-1195 shiftlead's ledger is one file per entry, with no Summary table to conflict on; an entry's conflict resolves by main's copy and the helper's command again; `ao --json` goes before the subcommand
metadata:
  type: feedback
---

Since TD-1195 (2026-10-28) shiftlead's ledger is `docs/ledger/`: one `TD-NNN.md` per entry, archived ones under
`archive/` (`git mv`), and no stored Summary table (`agent-cadence run ledger.py --summary` prints it). Two
filings never conflict. Two edits to the same entry conflict in that one file: take main's copy
(`git checkout origin/main -- docs/ledger/TD-NNN.md`) and run your `agent-cadence run ledger.py set|note|edit`
command again on it, never resolve the hunk by hand (design §4.4 *A session writes the ledger and the board only through the helpers*, TD-1286).

Also: `ao --json msg person "…"` — the global `--json` sits before the subcommand; after the text it is read
as part of the message and the call errors with *unrecognized arguments*. Related: [[shiftlead-td-grind-mechanics]].
