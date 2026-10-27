---
name: no-vscode-windows-for-agent-worktrees
description: A worktree only a session uses opens no window — cadence §1.1; `open_worktree.sh` is for the person
metadata:
  type: feedback
---

Cadence §1.1 (dev-cadence TD-139): `open_worktree.sh` leaves a VS Code window on Paul's desktop, so a
session's own worktree is made with `git worktree add` (and `dev-cadence run hydrate_worktree.sh` in it).
