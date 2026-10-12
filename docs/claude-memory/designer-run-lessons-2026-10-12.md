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

- **A new ledger entry goes above the file's tail**, never appended: `docs/technical_debt.md` ends with `---` and an unclosed `<!-- Entry template:` line, so an entry written after it renders hidden. Insert before that `---`, with a `---` of its own before the `## TD-NNN` heading.
- **`ao msg --shot` rides only on a steer or an ask to `person`**; to the techlead it is refused (*a look is the person's*). A design with a mockup sends its steer to the person with the shot.
- **Re-read the highest TD on `origin/main` *and* in open PRs right before committing**, not at the start of the round: TD-593 and TD-594 were each taken by another session within minutes. A renumber after a rebase is the edit script re-run on main's ledger with the new number, then the id-order test.

**Why:** each cost a failed command or an extra CI round before the merge.
**How to apply:** options before recipients ([[ao-msg-options-before-recipients]]); `raw_decode` on every `ao … --json` read; re-run the script on main's ledger after a rebase conflict.
