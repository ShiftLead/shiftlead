# A subagent's permission, captured (TD-947, 2026-10-21)

Claude Code 2.1.307 on the walk's `conformance` profile, a scratch home, `permission_prompts: all`,
`permission_wait: 90`, by `probe.py` (run as `python probe.py <worktree> --profile conformance --mode
<mode> --out <dir> [--wait N]`; past the fall-through it presses Enter on the dialog and reads a minute more). Each directory holds the hook payloads (`hooks.jsonl`), the record read once a second
(`timeline.jsonl`, `t` in seconds from the prompt's send) and the panes named by their moment:

- `background/`: the main thread ends its turn, then the subagent's `PermissionRequest` arrives. The pane
  draws no dialog for 90 s (`pane-03-needs-20s.txt`) and draws it once the hook times out
  (`pane-05-after-fallthrough.txt`, *Bash command · from the general-purpose agent*).
- `foreground/`: asked for a foreground subagent, the tool still backgrounds it. The request lands mid-turn,
  the main thread's `Stop` follows a second later and ends the waiter (the record reads `idle`), and the
  dialog is drawn once the hook returns (`pane-02-needs-5s.txt`).
- `answered/` (`permission_wait: 30`): the dialog drawn at the fall-through is answered in the pane (*1. Yes*,
  by an Enter). The subagent's own `PostToolUse` follows, with the same `agent_id` and the asked call's
  `tool_use_id`, then its `SubagentStop` (which carries `agent_id`), then the main thread's woken turn.
- In every subagent capture (not `main/`), a `PreToolUse` from an `agent_id` with no `SubagentStart` lands
  about thirty seconds after the `PermissionRequest`, inside or outside the hook's wait. It is the tool's own, and no subagent's.
- `main/`: the main thread's own permission is drawn as the hook starts waiting (`pane-01-needs-0s.txt`).

The `PermissionRequest` carries `agent_id` and `agent_type` inside a subagent, and no `tool_use_id` on either
road. No manifest names these files; they are evidence for design §4.2 *Permissions are answered through the
hook* and fixtures for TD-950's tests.
