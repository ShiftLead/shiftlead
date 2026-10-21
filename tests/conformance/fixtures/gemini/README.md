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
- `captured/titles.json`: the pane titles read across the same run (`title`).

The hook payloads, transcripts and the live walk's `--capture` come with the entry point (TD-785).
