---
name: designer-run-lessons-2026-10-12
description: a steer answered by the techlead owes no --outcome; ao inbox --json prints a trailer line after its JSON; a ledger conflict on rebase is resolved by re-running the helper's command on main's copy
metadata:
  type: feedback
---

Three things from the TD-577 round (PR #1554, 2026-10-12):

- An `--outcome` names a question **to the person**: `ao msg --outcome done --for <id> person` is refused when `<id>` was a steer to the techlead (*the person inbox holds no question*). A steer the techlead answered is closed by its reply; nothing else is owed (`ao progress none` was accepted after one, 2026-10-12).
- `ao inbox --unread --json` prints `[shiftlead] nothing unread — …` to **stderr** after the JSON (only inside a session), so a `2>&1` capture makes `json.load` fail with *Extra data*: keep stderr apart, or parse with `json.JSONDecoder().raw_decode(s)[0]`. `ao msg --json` puts its warning **before** the JSON ([[ao-msg-warning-precedes-json]]) — the two trailers differ.
- When main moves under a design PR and an entry conflicts on rebase, do not resolve the hunks by hand: squash to one commit, `git checkout origin/main -- docs/ledger/TD-NNN.md`, run the `agent-cadence run ledger.py set|note|edit` command again on main's copy, continue (design §4.4 *A session writes the ledger and the board only through the helpers*, TD-1286). Two rounds of hand-resolution cost two pushes here; the third, by re-running, was one. See [[summary-table-conflicts-resolve-row-wise]], [[edit-script-asserts-before-writing]].

Later the same day (TD-584, TD-578, TD-580, TD-581; PRs #1567, #1568, #1575, #1577):

- (retired: a v1 single-file ledger's id order) Since TD-1195 a new entry is its own `docs/ledger/TD-NNN.md`, filed under the id `ao td reserve` gives with `agent-cadence run ledger.py new --id TD-n` (TD-1360).
- **`ao msg --shot` rides only on a steer or an ask to `person`**; to the techlead it is refused (*a look is the person's*). A design with a mockup sends its steer to the person with the shot.
- **Take the id from `ao td reserve` right before committing** (cadence §2.10, [[td-ids-live-in-pr-diffs]]), never from the highest TD read by hand: TD-593 was used twice on main (#1569 and #1568; #1574 renumbered TD-578's build to TD-597), and TD-594 was taken on main by #1570 while #1575 held it, so that build became TD-596. A renumber after a rebase is `agent-cadence run ledger.py renumber` to a new number from `ao td reserve`.

On 2026-10-13 (TD-604, TD-627):

- **A rebase's conflict script that fails must stop the rebase.** Twice a carry script asserted and exited, and the same shell line went on to `git rebase --continue`, committing main's ledger in place of the branch's edits. Run the carry, check its exit, and only then `git add` and continue — never in one `if …; fi; … --continue` chain. See [[edit-script-asserts-before-writing]].
- (retired with the v1 ledger: appending to one ledger file by script; an entry is its own file and only the helpers write it.)

**Why:** each cost a failed command or an extra CI round before the merge.
**How to apply:** options before recipients ([[ao-msg-options-before-recipients]]); `raw_decode` on every `ao … --json` read; re-run the helper's command on main's copy after a rebase conflict.
