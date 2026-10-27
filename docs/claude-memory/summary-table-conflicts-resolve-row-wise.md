---
name: summary-table-conflicts-resolve-row-wise
description: A ledger conflict resolves by row and by entry (cadence §2.5); `ao --json` goes before the subcommand
metadata:
  type: feedback
---

Cadence §2.5 (dev-cadence TD-137): a summary-table conflict is resolved row by row, one row per id matching
its body; an archive-tail conflict keeps both. After a rebase, `grep -c '^| TD-NNN '` each id in the hunk.

Also: `ao --json msg person "…"` — the global `--json` sits before the subcommand; after the text it is read
as part of the message and the call errors with *unrecognized arguments*. Related: [[shiftlead-td-grind-mechanics]].
