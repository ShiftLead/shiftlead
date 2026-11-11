---
name: board-changes-close-and-add
description: Never restore or hand-reshape docs/user_attention.md; a changed decide item is `done` then `add`, and an archiving `done` is the helper's own commit
metadata:
  type: feedback
---

A decide item's `Parts:` is part of its item key (ledgerboard SPEC; TD-050's D3, Paul-approved): to narrow or widen it, close the old item with `board_edit.py done` and `add` a new one. Never `git checkout <old> -- docs/user_attention.md` to undo an add, and never fold a `done` that archives into a larger commit with `--no-commit`: the archive must be the helper's own commit, or the cadence `board` row fails.

**Why:** On TD-1551 (PR #3447, 2026-11-11) restoring the board file to re-add an item made `board_edit.py replay` refuse on rebase ("removed an item without archiving it"), and an archive folded into the big commit failed the gate; together with board contention they cost four of seven precheck runs.

**How to apply:** Board edits go through `board_edit.py` only, in this order when one item replaces another: `done` (without `--no-commit` when it archives, the board committed first), then `add --no-commit`. Lifting one part of a shared decide with its answer marks the whole item decided (ledgerboard TD-067); split the item first. See [[decided-in-the-filing-pr]], [[summary-table-conflicts-resolve-row-wise]].
