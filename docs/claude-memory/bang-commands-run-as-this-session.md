---
name: bang-commands-run-as-this-session
description: "A `!` command the person types runs in the session's shell, so ShiftLead reads it as the session: person-only acts (`ao promote`, `ao promote clear`) are refused, and `ao service install` needs XDG_RUNTIME_DIR"
metadata:
  type: feedback
---

A `!` command Paul types into a Claude Code session runs in that session's shell, which carries `SHIFTLEAD_SESSION`, `TMUX` and `TMUX_PANE` but no `XDG_RUNTIME_DIR` or `DBUS_SESSION_BUS_ADDRESS`. On 2026-10-26 (ao-shiftlead-prompts):
- `! ao promote clear shiftlead` was refused: *cannot run clear_promote: a person's own act, refused to every session but the person's own shell*. The same refusal met the session's own `ao promote`.
- `! … ao service install` failed: *Failed to connect to user scope bus … $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined*. pip had already installed, so the venv was new while the units still ran the old code.
- `! loginctl enable-linger` failed with *No such device or address*: the shell has no login session. Linger was already `yes`.

**Why:** the host agent decides who asks from the caller's environment, and a `!` shell inherits the session's.

**How to apply:** for an act only the person may do, give Paul the command for his own terminal (or the page's control), never a `!` line. For the hand promote pair from a `!` line, prefix `export XDG_RUNTIME_DIR=/run/user/$(id -u);`. Check linger with `loginctl show-user "$USER" -p Linger`. See [[shiftlead-is-pinned-run-dev-cadence-scripts]].
