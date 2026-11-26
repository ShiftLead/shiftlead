---
name: board-changes-close-and-add
description: Never restore or hand-write a board item's file; a changed decide item is `done` then `add`, each through the writer
metadata:
  type: feedback
---

A decide item's `Parts:` is part of its item key (ledgerboard SPEC; TD-050's D3, Paul-approved): to narrow or widen it, close the old item with `board_edit.py done --id <id>` and `add` a new one. Never `git checkout <old>` an item's file under `docs/user_attention/` to undo an add: an edit goes through the writer.

**Why:** On TD-1551 (PR #3447, 2026-11-11, on the one-file board before ledgerboard v3.0) restoring the board file to re-add an item made the rebase's replay refuse, and an archive folded into the big commit failed the gate; together with board contention they cost four of seven precheck runs. Since v3.0 (TD-1881) each item is its own file and a `done` moves it into `archive/<YYYY-MM>/`, so the archive threshold and the replay are gone (TD-2316).

**An item added and replaced on the same unmerged PR** is the exception (TD-1569, #3465, 2026-11-11): its `done` leaves a closed item with no open one on the base, which the gate's board row refuses (*a closed line with no open line it closes*). Drop the first item's file from the branch (it never reached main) and keep only the new `add`, rather than closing it.

Better still, write the end-of-rounds item only after the closing fact-check raises nothing.

**How to apply:** Board edits go through `board_edit.py` only (`--id <id>`, from `board_edit.py list`), in this order when one item replaces another: `done`, then `add --no-commit`. Lifting one part of a shared decide with its answer marks the whole item decided (ledgerboard TD-067); split the item first. See [[decided-in-the-filing-pr]], [[summary-table-conflicts-resolve-row-wise]].
