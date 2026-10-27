---
name: reviewer-prompts-keep-out-of-the-anchor
description: A reviewer reads refs or its own worktree, never the anchor's checkout — cadence §4.8
metadata:
  type: feedback
---

Cadence §4.8 (dev-cadence TD-136): a reviewer reads refs or its own detached worktree, never the author's
tree or the anchor. Here the anchor is `/home/kmaster/shiftlead`: name it in a reviewer prompt only for
`git fetch` (a Sonnet reviewer once ran `git checkout origin/<branch> -- .` there, 2026-09-22).
Related: [[shiftlead-td-grind-mechanics]].
