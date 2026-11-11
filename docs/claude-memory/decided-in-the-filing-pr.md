---
name: decided-in-the-filing-pr
description: When the person answers a held entry's decide before its filing PR merges, lift with board_edit.py decide and drop the board item from the PR; ledger.py refuses bold paragraph openers
metadata:
  type: feedback
---

When the person answers a held entry's question while its filing PR is still open (TD-1581, 2026-11-10):
- `board_edit.py decide --line N --expect "<the line's start>" --answer … --by paul --no-commit` lifts the gate in the entry and writes a lifted line to its Log. `--expect` is the line's literal start, `- [ ] decide …`, not the question.
- Then restore `docs/user_attention.md` to main's copy. The merge gate's `board` row fails a closed line that closes nothing open on main, and the `gates` row passes without the item, since main never held the gate.

`ledger.py new` and `ledger.py edit` refuse a paragraph that opens in bold, because it reads as a section of its own (`**X:**` / `**X.**`). Open with plain words, and keep bold for inside a sentence or a list item.

**Why:** each one cost a refused precheck-and-merge cycle (about 12 minutes) or a retry.
**How to apply:** check the drafted Why/Fix files for lines starting with `**` before calling `ledger.py new`. Decide in the filing PR only when the answer came before the merge. See [[summary-table-conflicts-resolve-row-wise]] and [[precheck-and-merge-in-one-command]].
