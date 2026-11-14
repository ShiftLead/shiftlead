---
name: reviewer-can-detach-your-head
description: A reviewer given your worktree can `git checkout <sha>` there; later commits land on a detached HEAD and `git push` pushes nothing
metadata:
  type: feedback
---

On 2026-11-13 (TD-1815, #3793) a Sonnet fact-checker told to read "at commit X" in the designer's own worktree ran
`git checkout X`. Seven later commits went onto the detached HEAD; each `git push -q` printed nothing and pushed
nothing, so the PR's head stood at X through two rounds, until another reviewer's `git checkout <branch>` exposed it.

**Why:** a fresh agent reads "at commit X" as "check X out" unless told not to, and a quiet push hides the detach.

**How to apply:** every reviewer prompt that names your worktree says *never `git checkout`, `git switch` or
`git reset`; read with `git show <sha>:<path>`*. After each push, compare `git rev-parse HEAD` with
`refs/remotes/origin/<branch>`. A fact-check by ref alone (cadence §4.8) avoids it. Related:
[[reviewer-prompts-keep-out-of-the-anchor]].
