---
name: designer-run-lessons-2026-10-12
description: a steer answered by the techlead owes no --outcome; ao inbox --json prints a trailer line after its JSON; a ledger conflict on rebase is resolved by re-running the edit script's ledger slice on main's copy
metadata:
  type: feedback
---

Three things from the TD-577 round (PR #1554, 2026-10-12):

- An `--outcome` names a question **to the person**: `ao msg --outcome done --for <id> person` is refused when `<id>` was a steer to the techlead (*the person inbox holds no question*). A steer the techlead answered is closed by its reply; nothing else is owed (`ao progress none` was accepted after one, 2026-10-12).
- `ao inbox --unread --json` prints `[shiftlead] nothing unread — …` to **stderr** after the JSON (only inside a session), so a `2>&1` capture makes `json.load` fail with *Extra data*: keep stderr apart, or parse with `json.JSONDecoder().raw_decode(s)[0]`. `ao msg --json` puts its warning **before** the JSON ([[ao-msg-warning-precedes-json]]) — the two trailers differ.
- When main moves under a design PR and the ledger conflicts on rebase, do not resolve the hunks by hand: squash to one commit, `git checkout origin/main -- docs/technical_debt.md`, re-run the edit script's ledger slice (its asserts still hold on main's copy), continue. Two rounds of hand-resolution cost two pushes here; the third, by script, was one. See [[summary-table-conflicts-resolve-row-wise]], [[edit-script-asserts-before-writing]].

Later the same day (TD-584, TD-578, TD-580, TD-581; PRs #1567, #1568, #1575, #1577):

- **A new ledger entry goes in id order: before the first entry with a higher id, else at the file's true end, after its last `---`.** `tests/test_ledger.py` (`test_ids_are_assigned_in_order_within_each_file`) fails a body out of order; the Summary table's row order is not tested, so keep it in order by hand. On 2026-10-14 TD-676 was appended after a TD-677 that merged while its PR was open, and CI went red on that push (#1739, fixed before the merge). On 2026-10-12 the ledger ended with an unclosed `<!-- Entry template:` line (an entry after it rendered hidden); by 2026-10-13 that tail was gone. Read the last lines before inserting, and never locate the end by a marker (below).
- **`ao msg --shot` rides only on a steer or an ask to `person`**; to the techlead it is refused (*a look is the person's*). A design with a mockup sends its steer to the person with the shot.
- **Re-read the highest TD on `origin/main` *and* in open PRs' diffs right before committing** ([[td-ids-live-in-pr-diffs]]), not at the start of the round: TD-593 was used twice on main (#1569 and #1568; #1574 renumbered TD-578's build to TD-597), and TD-594 was taken on main by #1570 while #1575 held it, so that build became TD-596. A renumber after a rebase is the edit script re-run on main's ledger with the new number, then the id-order test.

On 2026-10-13 (TD-604, TD-627):

- **A rebase's conflict script that fails must stop the rebase.** Twice a carry script asserted and exited, and the same shell line went on to `git rebase --continue`, committing main's ledger in place of the branch's edits. Run the carry, check its exit, and only then `git add` and continue — never in one `if …; fi; … --continue` chain. See [[edit-script-asserts-before-writing]].
- **Find the ledger's tail by the file's end, never by `rindex` of a marker.** Main's trailing `<!-- Entry template:` came and went that day; when it was gone, `rindex` found the real template block at the top and the "append" cut 982 lines. Append after the last line, and assert the line count grew before writing.

**Why:** each cost a failed command or an extra CI round before the merge.
**How to apply:** options before recipients ([[ao-msg-options-before-recipients]]); `raw_decode` on every `ao … --json` read; re-run the script on main's ledger after a rebase conflict.
