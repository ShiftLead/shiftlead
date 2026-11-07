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

The board conflicts too (two PRs' `board_edit.py add`s insert at the same place): at the stopped rebase run
`agent-cadence run board_edit.py replay --board docs/user_attention.md` — it reads the three sides from git, makes your
side's writes again on main's board (and archive), stages them — then `git rebase --continue`; never by hand, and
yours to run as the PR's author before the re-precheck (a cloud session's PR: its reader's; TD-1514,
design §4.4 *Two PRs' records merge in either order*). A `done` that archives (nine closed items already) runs without
`--no-commit`, the board committed first, so its archive is the helper's own commit.

Also: `ao --json msg person "…"` — the global `--json` sits before the subcommand; after the text it is read
as part of the message and the call errors with *unrecognized arguments*. Related: [[shiftlead-td-grind-mechanics]].
