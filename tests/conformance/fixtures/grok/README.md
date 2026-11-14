# Grok Build's conformance fixtures

Captured from the real tool, never written by hand (design §4.3 *The conformance suite*). `manifest.json`
says what the adapter reads off each (TD-1637 slice 13), and `tests/test_grok_hook.py` reads the hook captures
through the state feed's `translate` as well.

- `captured/hooks.jsonl` (Grok Build 1.0.77 `50ca579fa996` on kmaster, 2026-11-14, TD-1637 slice 9):
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
- `captured/hooks-subagents.jsonl` (Grok Build 1.0.77 on kmaster, 2026-11-13 local, TD-1637 slice 12): the same
  capture-only hook file in a fresh scratch copy of `grok-conformance`, launched as above with `--session-id
  22222222-3333-4444-8555-666666666666`, on the tool's default model (the data-sharing opt-in left unanswered,
  off by default). In order: a prompt whose subagent ran `mkdir sub2 …` with no prompt (`spawn_subagent`,
  `SubagentStart`, the child's `UserPromptSubmit`, tool events, `SubagentStop` and its own `SessionEnd`
  `shutdown`, all with `subagentType`); a prompt whose subagent ran `rm a.txt && mkdir sub3`, raising a
  `permission_prompt` on `spawn_subagent` and one on the child's command — both on the **parent's** `sessionId`,
  with no `subagentType` — each answered *Yes* with Enter; an `ask_user_question` (`PreToolUse`, then a
  `Notification` `elicitation_dialog`, answered *Blue*); a background subagent running `sleep 120`, killed by
  `kill_command_or_subagent` (its `task_id` the `subagentId`), which fired no `SubagentStop`, only the child's
  `SessionEnd`; and `/exit`.
- `captured/panes/*.txt` and `captured/titles.json` (Grok Build 1.0.77 on kmaster, 2026-11-13 local, TD-1637 slice
  13): `tmux capture-pane -p -e` of a fresh scratch copy of `grok-conformance` on a private tmux server (160×45),
  launched as above with `--session-id 33333333-4444-4555-8666-777777777777`, and the pane's `#{pane_title}` at
  each step: the empty composer at launch, a typed line, a two-line bracketed paste, a turn running with an
  empty composer, with a typed line and with a queued prompt, a permission prompt (`rm a.txt && mkdir made`)
  and an `ask_user_question`. The titles' first entry is the launch's, before the tool named the session.
- `captured/transcripts/tools.jsonl` and `captured/transcripts/panes.jsonl`, each with its `*.summary.json` (Grok
  Build 1.0.77 on kmaster, TD-1637 slice 15): the `updates.jsonl` and `summary.json`, unchanged, that the tool wrote
  for the sessions of `captured/hooks.jsonl` (`11111111-…`, two shell commands, the mode cycled) and of the panes
  (`33333333-…`, an essay, a shell command, an `ask_user_question` answered *Blue*, a poem and a queued prompt),
  copied from their scratch homes' `sessions/<the cwd, encoded>/<id>/`.
- `captured/listings/*.txt` (Grok Build 1.0.77 on kmaster, 2026-11-14, TD-1637 slice 16): `tmux capture-pane -p -J`
  (trailing blanks trimmed) of a fresh scratch copy of `grok-conformance` on a private tmux server (200×60), launched
  with the adapter's `LAUNCH_ENV` and its hook file, plus a second user hook file `hooks/other.json` (one `Stop`
  handler, `/bin/echo other`): `hooks-list.txt` after `/hooks-list` (*Loaded hooks (14)*, `global/other` among
  them); `mcps.txt` with `/mcps` open on the account's hosted connector *Automations* `[ready]`; `mcps-disabled.txt`
  after Space on that row, which wrote `[disabled_mcp_tools] __managed_gateway_connectors = ["tasks"]` into the
  scratch home's `config.toml`. The walk's Grok listing reads these (`scripts/conformance.py`'s `FOREIGN`).
- `captured/hooks-batch-plan-wake.jsonl`, `captured/hooks-plan-always-approve.jsonl` and
  `captured/hooks-stop-failure.jsonl` (Grok Build 1.0.77 on kmaster, 2026-11-14, TD-1840): the same capture-only hook
  file in a fresh scratch copy of `grok-conformance`, with `HOME` an empty scratch directory and the adapter's
  `LAUNCH_ENV`. The first, on a private tmux server (160×45) with `--session-id 44444444-5555-4666-8777-888888888888`
  and `--permission-mode default`: a two-call batch (`rm a.txt` and `mkdir made`), where the second call's
  `PreToolUse` came only after the first's `permission_prompt` was answered *Yes*; `enter_plan_mode`, whose
  `PostToolUse` followed its `PreToolUse` at once with nothing asked, and `exit_plan_mode`, which fired a
  `permission_prompt` (*Plan approval requested*) until `a` approved the plan; a background `sleep 25; echo bg-done`
  after whose `Stop` the command's end fired a `Notification` `task_complete` and a `UserPromptSubmit` of the tool's
  own (a `<system-reminder>` naming the task), starting a turn; and `/exit`. The second, headless (`-p`) with
  `--always-approve`: the same plan-mode pair, where `exit_plan_mode`'s `permission_prompt` still fired and passed
  unanswered. The third, headless with `--always-approve` and `GROK_CLI_CHAT_PROXY_BASE_URL` a local stub answering
  every request 400 (`--session-id 66666666-7777-4888-8999-aaaaaaaaaaaa`): a `Notification` `agent_error`, then
  `StopFailure` with `error` `invalid_request`, `errorDetails` the API message and a `promptId` (the same stub answering
  500 drew retries for over three minutes and no `StopFailure`).
