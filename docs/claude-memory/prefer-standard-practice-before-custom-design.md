---
name: prefer-standard-practice-before-custom-design
description: before designing a custom mechanism, look for the standard tool or accepted practice (git's own checks first) and design on top of it
metadata:
  type: feedback
---

Before a design invents a mechanism, find the standard way the tool or the field already does it, and build on that. Only add what the standard way leaves out.

**Why:** TD-978 (a close reaps its worktree, 2026-10-23) spent review rounds 8–11 on a home-grown "is this branch safe to delete" test. That test was patch-id twin matching, a reinvented `git cherry`, and each round's fix opened the next round's hole. Paul asked whether git already does this. It does:
- `git worktree remove` without `--force` refuses a dirty or locked worktree;
- `git branch -d` and `git merge-base --is-ancestor` say whether every commit is on origin;
- the remote-tracking ref's reflog (`--fork-point`'s mechanism) says whether a rewritten branch was once pushed.

The design was rewritten on those.

**How to apply:** when a design needs a safety or state test (git, tmux, systemd, HTTP, etc.), first write down which built-in command or convention answers it, and what gap is left. Name both in the design. A mechanism that keeps failing review rounds is a signal you are reinventing one ([[design-review-loop-with-sonnet]]).
