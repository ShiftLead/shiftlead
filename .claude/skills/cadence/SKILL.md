---
name: cadence
description: Run the cadence check on this branch's PR (review evidence, squash, CI, base, ledger, worktree, pushed, deploy) — do the independent review and post its evidence comment if missing, then merge only when every row passes. Pass a PR number to check another PR, or "week" for every PR merged in the last 7 days.
---

# Cadence — check a PR against cadence.md §1–§5 before merging

Read [`docs/procedures/cadence.md`](../../../docs/procedures/cadence.md) — in a repo that pins agent-cadence, the file `agent-cadence path procedures/cadence.md` prints — and follow it; the whole procedure lives there,
where an agent in any tool can run it (TD-093); this file holds no rule of its own. An argument that is a PR number means that PR; `week` means every PR merged in the last 7 days (`--since 7d`); none means the current branch's PR.
