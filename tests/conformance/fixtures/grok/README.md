# Grok Build's conformance fixtures

Captured from the real tool, never written by hand (design §4.3 *The conformance suite*). The adapter is not
registered yet (TD-1637), so no test reads these yet; the state-feed slice reads them.

- `captured/hooks-scratch.jsonl` (Grok Build 1.0.77 `50ca579fa996` on kmaster, 2026-11-14, TD-1637 slice 9):
  every hook payload, unchanged, one per line, that a capture-only hook file (`hooks/cap.json`, the thirteen
  events `HOOK_EVENTS` names, `cat >>`) recorded in a scratch copy of the signed-in `grok-conformance` home,
  the tool on a private tmux server (160×45) in a scratch git directory, launched with the adapter's
  `LAUNCH_ENV`, `--session-id 11111111-2222-4333-8444-555555555555` and `--permission-mode default`, on the
  tool's default model. In order: `SessionStart` (`source` `new`); a prompt that ran `touch made.txt && ls`
  with no prompt (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` `end_turn`); the mode cycled
  with Shift+Tab back to the footer's unlabelled mode; a prompt whose `rm … && mkdir …` raised a
  `Notification` `permission_prompt` (`message` *Tool permission requested*) before its `PostToolUse` and
  `Stop`; `/clear`, which fired a `SessionStart` (`source` `new`) with a new `sessionId` and no
  `SessionEnd`; and `/exit`, which fired the new conversation's `SessionEnd` and `Stop` (both `reason`
  `shutdown`), then the first conversation's `SessionEnd` and `Stop` (`shutdown`) after them; no
  `shutdown` `Stop` carries a `promptId`. No subagent, question
  tool or `StopCancelled` is in it.
