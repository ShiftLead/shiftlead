---
name: gate-everything-after-a-merge-on-its-state
description: "Confirm MERGED before deleting the branch or reporting (cadence §1.4); a PR closed by a deleted branch comes back by pushing the same sha and reopening"
metadata:
  type: feedback
---

Cadence §1.4: confirm the merge (`gh pr view N --json state`) before concluding anything — the branch's
deletion, `ao progress done`, a note — each in its own call, a delete naming one branch, never a loop
(#727 → #730 on 2026-09-28). The cadence does not say the cure: when a deleted branch has closed the PR,
`git push origin <branch>` at the same sha and `gh pr reopen` bring it back with its comments (#895,
2026-10-02). See [[gate-a-merge-on-the-checks-exit-code]].
