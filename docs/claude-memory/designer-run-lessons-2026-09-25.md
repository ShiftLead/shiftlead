---
name: designer-run-lessons-2026-09-25
description: "A steer to the person is refused when the person inbox holds 20 unanswered entries (the board is the channel); a fact-check agent in the shared worktree must read explicit refs; a stacked design PR chain and the bound-merges are the next run's first job"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 111132eb-b111-40f2-842c-9895175c01c3
  modified: 2026-09-25T19:15:25.180Z
---

Three things the designer run (and one from a techlead seat) of 2026-09-25 learned (see [[shiftlead-td-grind-mechanics]], [[reviewer-prompts-keep-out-of-the-anchor]]):

1. **`ao msg --kind steer person` is refused as full** once the person inbox holds 20 entries unread or unanswered from the caller: *the person is away — write the line on user_attention.md with a Due: date*. The board line is then the channel (one line listing every open steer, its default and the alternative, `Due:` the bound's day), merged as its own small PR so it is on `main` at once; the design PR's Status names that board line instead of a steer id.
2. **Where a fact-check agent reads** is cadence §4.8 (dev-cadence TD-136): refs, never the shared worktree. Here: tell it to skip `gen.py` unless `rev-parse --abbrev-ref HEAD` is the PR's branch.
4. **A techlead's `ao msg --reply-to <id> --source …` is refused the same way** (2026-10-01, at the per-sender cap of 100, `PERSON_SENDER_DEPTH`): the `--source` form copies the person as *answered for you*, so a full person inbox refuses the reply to the asker too. Send the reply without `--source`, opening with `Source: <where>`, and say in the summary that no answered-for-you copy reached the person.
3. **A build entry's TD number can be taken on `main` by a grinder while the design PR is open** (TD-169 was, PR #556's review): take its id, and any renumber's, from `ao td next` (cadence §2.10), and at merge time rebase and resolve the table row-wise, renumbering the build entry across design.md, the history and the ledger.

**Why:** each cost a fix commit and a second review round; the first also left a steer unsent until the refusal was read.

**How to apply:** at every `ao msg person`, read the reply for `"error"`; prompt every reviewer with refs (§4.8); `ao td next` before numbering, never the highest id read by hand ([[td-ids-live-in-pr-diffs]]).
