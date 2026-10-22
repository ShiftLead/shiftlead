# Gemini CLI's conformance fixtures

Captured from the real tool (Gemini CLI 0.64.0 on kmaster, 2026-10-21, TD-785), never written by hand
(design §4.3 *The conformance suite*). The tool ran on a private tmux server (120×40) in a scratch
directory, on the `gemini-conformance` home, with the machine's layer and `CLI_TITLE=probe`, so no
person's session is in them. `manifest.json` names each fixture with what the adapter read from it.

- `panes/`: `capture-pane -p -J -e -S -12` as `capture_tail(…, 12, raw=True)` keeps it (trailing blank
  rows dropped, the last twelve kept), the colours kept so the composer's reader is tested as it runs:
  `idle-empty` (the placeholder), `idle-typed` (*hello there* typed, not submitted), `idle-pasted` (three
  lines pasted, not submitted), `working-empty` (mid-turn), `working-typed` (a prompt typed mid-turn) and
  `working-queued` (that prompt submitted mid-turn: the tool queues it in faint *Queued* lines above an
  empty composer). Their `state` is `null`: the adapter's state is its title's, never the tail's.
- `captured/`: what the live walk's `--capture` recorded (`pdm run conformance gemini --profile
  gemini-conformance --capture`, 0.64.0, 2026-10-21, TD-785 slice 5), unshortened: `hooks.jsonl`, each hook
  payload the tool handed `shiftlead-hook --adapter gemini` (the state mapping and `pending`);
  `titles.json`, the pane titles on the walk's tmux server at its end (`title`); and `panes/<n>-<step>.txt`,
  each step's pane (`capture-pane -e`, the title on its first line). The walk held four of its seven steps:
  at the doorbell the free tier's daily quota ran out (*Usage limit reached for gemini-3.8-flash*, the
  tool's own dialog in `6-a-doorbell.txt`), so its resume and transcript steps were not reached.

- `transcripts/`: two chats the live walks wrote on the `gemini-conformance` home (0.64.0, TD-786 slice 1),
  copied unchanged from its `.gemini/tmp/<slug>/chats/` (`read_transcript`, `context`, `links`, `spend`):
  `walk-limit` (2026-10-21, the walk that met the quota at the doorbell: a prompt, a shell call, the
  doorbell) and `walk-resume` (2026-10-22, the same steps, then resumed: the tool's `$patch` at the
  resume, and each call's response written again as `<id>_response`). The harness puts each where the
  adapter looks, its session id replaced by the test's. Neither printed a link.

- `procs/two-tasks.json`: `/proc` as `identity.LinuxProc` read it under the pane's process (0.64.0, 2026-10-22,
  TD-786 slice 3), the tool on a private tmux server in a scratch directory on the `gemini-conformance` home
  with two shell-mode commands (`!timeout 300 sleep 290`, `!python3 -c …`) each moved to the background with
  Ctrl+B: the pane's `node`, the `node` it relaunches itself as, and each command's `bash -c` wrapper under
  that; each `cmdline` value cut to 160 characters (`background`).
