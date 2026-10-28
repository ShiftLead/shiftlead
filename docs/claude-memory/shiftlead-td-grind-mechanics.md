---
name: shiftlead-td-grind-mechanics
description: "Gotchas for scripted ledger edits, PR comments and merging in ShiftLead (post comments from a file, a review comment after the merge never counts, kill by pid); the ledger habits point at cadence §2.5, §2.8, §2.12, §4.8"
metadata: 
  node_type: memory
  type: project
  originSessionId: 31a6d882-e7d4-40aa-a6a0-3e7bb44d4af9
  modified: 2026-09-14T18:40:00Z
---

Learned running the 2026-09-09/10 unattended TD grind in agentorc (session tdgrind-ao-1):

- A scripted ledger edit parses through `ledger.py` or ledgerboard, never a hand regex on
  `## TD-NNN:` — the template comment is itself headed `## TD-001` (cadence §2.12, TD-137).
- `gh pr merge --squash` is silently refused while CI is still pending (`mergeStateStatus`
  UNSTABLE); `gh pr view N --json state` then still says OPEN. Poll
  `gh pr view N --json statusCheckRollup` for `SUCCESS` first. `gh pr checks` output has a
  space in the check name, so `awk '{print $2}'` is wrong.
- Ledger and archive-tail conflicts, and the rebase right before the merge: cadence §2.5 (TD-137).
- The archive's label is cadence §2.8's and the review comment's shape is §4.9's; run
  `tests/test_ledger.py` before pushing even a doc-only ledger PR.
- `pkill -f <pattern>` kills the wrapping shell when the pattern appears in the command line
  itself; kill by pid. (Run 2 hit it again: exit 144 on the whole Bash tool call.)
- A probe script that starts a child agent must put `SHIFTLEAD_HOME` under a *short* path: the
  session scratchpad path is too long for `agent.sock` (`OSError: AF_UNIX path too long`) and
  the child waits forever for a socket that never appears.
- Where a reviewer reads: cadence §4.8 (TD-136), refs or its own worktree, never the working copy.
- CI runners lag tmux's exit status: a pane can read `dead=1` with no `pane_dead_status` for
  more than 6 s (seen on 3.13 only, PR #52). Do not assert `exit_code` right after `exited`.

Added 2026-09-14 (same session, a later run, ten PRs merged):

- A PR number is the forge's: cadence §2.8 (TD-137).
- **A review comment posted or edited after the merge never counts**: editing the comment
  afterwards fails on `updated_at > merged_at`, so the row can never go green. Post the evidence
  before the merge. (The check once read the verdict on the first line only, TD-050; it reads
  any line now, cadence §4.9.)
- **Post PR comments from a file, and read them back.** `gh pr comment --body "$(...)"` with a
  command substitution that fails silently posts the *error output* as the comment. I destroyed
  two real review-evidence comments that way (an `gh api .../issues/$pr/comments/$cid` call that
  404'd became the comment body). Write the body to a file, POST with `--input`, then
  `gh api .../issues/comments/$ID -q .body | head -1` to confirm.
- **`gh pr list --author @me` is not "my PRs".** Every session on this machine pushes as the same
  GitHub account, so that lists *every* session's open PRs. At wrap-up I took one for my own
  in-flight work, commissioned a review of it, and only found the owner when `git checkout` said
  the branch was already used by another worktree. Identify ownership first: `git worktree list`
  (a branch checked out elsewhere is someone else's), and the branch name against your own
  `ao progress` claims.
- **Never `git checkout <file>` to undo a test fixture edit** while you have uncommitted work in
  that file — it silently discards the real change too. Copy the file aside and copy it back.

Added 2026-09-22 (grinder-ao-1):

- The verdict words are cadence §4.9's: ask the reviewer for its findings, then write the
  verdict line yourself.
- A TD number is taken on main between your write and your merge (2026-09-24: TD-126 filed by the
  anchor while a PR carrying its own TD-126 was open). Take every id, and a renumber's, from
  `ao td reserve` (cadence §2.10), never from the highest `## TD-` read by hand; keep main's rows and
  yours row-wise.

- Appending to the archive in Python: read into a variable first. `open(a,'w').write(open(a).read()+x)` truncates before it reads and leaves the archive holding one entry (2026-09-27, PR #677, caught by review).

**Why:** these cost real time and one wrong PR state on the first run.
**How to apply:** when scripting ledger moves or chaining merges in this repo, reuse these rules;
a helper that skips the template block lives only in a session scratchpad, so rewrite it.
Related: [[unattended-workers-run-inside-shiftlead]].
