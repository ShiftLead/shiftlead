---
name: designer-run-lessons-2026-10-04
description: A design PR that waits on a steer — its history line in its own entry's docs/history/ file, expect its build number to be taken, and hold the worktree still while a reviewer reads
metadata:
  type: feedback
---

Three things that cost CI cycles on 2026-10-04 (PRs #981, #1006, #1009, #1022), each a design PR that sat open for a steer while grinders merged:

- **A history line goes to its own entry's file, `docs/history/TD-<n>.md`.** Until TD-1513's cut every PR appended to the same `docs/design-history.md` section, so a line added there conflicted with each merge (#1022 took three rebases, five minutes of CI each); the file is frozen now, and two PRs for two entries write two files (design §4.4 *Two PRs' records merge in either order*).
- **The build entry's number**: ids and renumbers come from `ao td reserve` (cadence §2.10).
- **While a reviewer reads, the author leaves its tree alone**: cadence §4.8 (dev-cadence TD-136). A second design that touches the same passages is stacked on the first's branch (see [[retarget-a-stacked-pr-with-the-api]]).

**Why:** each is a merge that failed after a green gate, or a number that pointed at someone else's entry.
**How to apply:** when writing the dated history line, the build entry, and when starting the fact-check. Related: [[shiftlead-td-grind-mechanics]], [[summary-table-conflicts-resolve-row-wise]].
