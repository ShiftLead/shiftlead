# Claude Code's conformance fixtures

Captured from the real tool (Claude Code 2.1.301 on kmaster, 2026-10-16), never written by hand (design
§4.3 *The conformance suite*, TD-784). Long string values are shortened (`… <the URLs it held>`, a
thinking block's `signature` as `sig`); every key, type and structure is as captured. No pane or
transcript of a person's own session is used. `manifest.json` names each fixture with what the adapter
read from it at capture.

- `panes`: the screen-rule fixtures under `tests/fixtures/screens/` (TD-015, TD-032, TD-064, TD-296),
  each recorded from a live pane, and `panes/grinder-working.txt`, `ao tail ao-shiftlead-grinder-ao-2
  -n 30` of grinder-ao-2's own pane mid-turn, with `ao`'s own trailer lines (`[shiftlead] …`) removed and an email address in a command line shown as `<redacted>`.
  `ao tail` prints the screen without its colours, so no fixture here tells a painted composer from a
  faint suggestion; the unit tests in `tests/test_claude_adapter.py` hold that.
- `transcripts/grinder-doorbell.jsonl`: one doorbell turn of grinder-ao-2's own transcript
  (`~/.claude/projects/-home-kmaster-shiftlead--claude-worktrees-grinder-ao-2/c052bdd3-….jsonl`, lines
  364–470): the `api-request-blob` and `api-request-shape` lines dropped, and of each bookkeeping type
  (`attachment` by its kind, `api-request`, `custom-title`, `mode` and the rest) the first kept.
- `procs/grinder-two-tasks.json`: `/proc` as `identity.LinuxProc` read it under grinder-ao-2's pane
  process, with two background shell tasks running; each `cmdline` value cut to 160 characters.

- `captured/`: what the live walk's `--capture` recorded (`pdm run conformance claude-code --profile
  conformance --capture`, Claude Code 2.1.302, 2026-10-16, TD-784 slice 3), unshortened: `hooks.jsonl`,
  each hook payload the tool handed `shiftlead-hook` across the walk's seven steps, its bytes, one per line
  (the state mapping and `pending`); `statusline.jsonl`, the status line's payloads (`usage_report`); and
  `titles.json`, the pane titles on the walk's tmux server at its end (`title`). The walk ran in a scratch
  directory under `/tmp` on a profile set aside for it, so no person's session is in them.

- `transcripts/prompts.jsonl` and `panes/prompts.txt` (TD-976, the `prompts` read): one conversation of
  seven prompts captured by hand on the `conformance` profile (Claude Code 2.1.309, Haiku, 2026-10-22) in
  a scratch directory under `/tmp`, on a tmux server of its own: a short prompt, *yes*, the first prompt
  typed again, one longer than forty characters, `/rename conformance prompts` (a local command with
  arguments and its output, which this build writes as two `system` entries), the meta line the rename
  leaves, a count interrupted with Escape (`[Request interrupted by user]`), and one more. The transcript
  keeps its `user`, `assistant`, `system` and `custom-title` lines, unshortened; the `attachment` and
  `api-request*` lines are dropped, since they carry the system prompt. The pane is `capture-pane -p -S -
  -E -` of the same conversation at its end, trailing empty rows dropped.
