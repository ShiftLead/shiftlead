# ADR 2026-10-13: Hermes Agent — Nous Research's open agent, its Kanban board, and who each is for

Status: survey (2026-10-13, at Paul's request). **Nothing here changes the design by itself.** It
says what Hermes Agent is, whether it takes shiftlead's ground, whether the two can run together, and
what is worth borrowing. The third of the day's surveys, after [Grok Bot](2026-10-13-grok-bot.md)
and [Muse](2026-10-13-muse.md).

## Context

Paul asked for the same analysis of [Hermes Agent](https://hermes-agent.nousresearch.com/). A Sonnet
agent surveyed the site, docs, repository and coverage; the session re-read the vendor's own pages
the comparison rests on (see *What was checked*). Unlike Grok Bot and Muse, **every source that
matters is primary**: the docs and the MIT-licensed code are public. The repository dates from
2025-07-22, has about 253k stars, and released v0.21.7 on 2026-10-12; it moves weekly, so read this as
of 2026-10-13. Hermes was already in shiftlead's record once: it is one of Paperclip's twelve
adapters ([Paperclip ADR](2026-09-24-paperclip.md)).

## What it is

| | |
|---|---|
| Vendor | Nous Research. Open source: *"MIT — see LICENSE"* ([README](https://github.com/NousResearch/hermes-agent)). Installed by `curl … install.sh \| bash` on Linux, macOS and WSL2; a desktop app and an optional hosted Nous Portal besides. It imports an OpenClaw setup (`hermes claw migrate`) |
| Shape | **one personal agent the person runs themselves**: *"Full TUI with multiline editing, slash-command autocomplete, conversation history, interrupt-and-redirect"*, and a gateway daemon for *"Telegram, Discord, Slack, WhatsApp, Signal, and CLI — all from a single gateway process"* (README). It keeps working with the person away: a *"Built-in cron scheduler with delivery to any platform … running unattended"* (README) |
| Where it runs | *"Seven terminal backends — local, Docker, SSH, Singularity, Modal, Daytona, and Vercel Sandbox"*; *"Run it on a $5 VPS or a GPU cluster"* (README) |
| Models | the person's choice: *"Nous Portal, OpenRouter, OpenAI, your own endpoint, and many others … Switch with `hermes model`"* (README); Anthropic by API key, setup-token or OAuth, and local endpoints such as Ollama and vLLM ([providers](https://hermes-agent.nousresearch.com/docs/integrations/providers)). Bots can each pin *"its own model"* ([Bot Mode](https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode)) |
| Claude subscription | Max only, and **only the overage**: OAuth *"Requires Max and purchased extra usage credits"*; *"All Hermes usage bills as 'extra usage' even while your included Max allowance sits untouched"*; *"Pro subscribers cannot use the OAuth path"* (providers). A Claude Code CLI provider to reach the plan's allowance was proposed and closed unmerged (PR #40528, closed 2026-07-14) |
| Memory and skills | *"Agent-curated memory with periodic nudges. Autonomous skill creation after complex tasks. Skills self-improve during use. FTS5 session search"* (README) — the *"closed learning loop"* is its headline |
| Many agents | in-process subagents (*"Spawn isolated subagents for parallel workstreams"*, README) and, the part that matters here, **Kanban** (below) |
| Coding | git worktrees built in: `hermes -w` or `/worktree new` gives a tree on a `hermes/<name>` branch, kept on exit only with unpushed commits ([worktrees](https://hermes-agent.nousresearch.com/docs/user-guide/git-worktrees)); `/rollback` checkpoints; an opt-in mode hands OpenAI turns to the Codex CLI app-server, *"Hermes becomes the shell around it"* ([Codex runtime](https://hermes-agent.nousresearch.com/docs/user-guide/features/codex-app-server-runtime)) |
| Consent | `approvals.mode: smart \| manual \| off`, a 300-second timeout, and separate settings for cron, single-query and webhook/API sessions, each `deny` in the documented config; a hardline blocklist; and container backends as the real boundary. Its own words on the denylist: *"it does not sandbox a hostile or compromised agent"* ([security](https://hermes-agent.nousresearch.com/docs/user-guide/security)) |
| Price | free software; the person pays their model provider, or a Nous Portal subscription that bundles models and tools |

### Kanban: an org of agents, on one host

*"Hermes Kanban is a durable task board, shared across all your Hermes profiles, that lets multiple
named agents collaborate on work … Every task is a row in `~/.hermes/kanban.db`; every handoff is a
row anyone can read and write; every worker is a full OS process with its own identity"*
([Kanban](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban)). A dispatcher
spawns workers (Hermes profiles) with a `kanban_*` toolset — `kanban_request_review`,
`kanban_request_changes`, `kanban_block`, `kanban_heartbeat` and more — and the person drives the same
board from `hermes kanban`, a slash command or a dashboard. Among its named patterns: *"Engineering
pipelines — decompose → implement in parallel worktrees → review → iterate → PR"*. A task can carry a
**PR completion contract** (`--completion-contract OWNER/REPO`), which reads the repo's branch
protection and required checks before the task may complete; *"A commit or diff alone never
automatically completes a task"*. Workers run to a finite iteration budget with a warning near 90%.
*"Kanban is single-host by design"* under a *"trusted-local-user threat model"* (same).

## Who each is for

Paul's framing — *the big companies target everyday users; shiftlead targets developers and tech
leads who understand the process, LLMs and harnesses, and want full control* — fits Grok Bot and
Muse. **Hermes breaks the pattern: it is open source, self-hosted, model-neutral, and built for the
same technical person.** Its README even pitches training data (*"Batch trajectory generation"*). So
the line between Hermes and shiftlead is not who or how much control, but **which harness**:

- **Hermes is the harness.** Its agent loop, its tools, its memory and its skills are the product;
  the person picks only the model. Coding is one use among research, ops and *"digital twins"*.
- **shiftlead runs other people's harnesses.** Claude Code, Codex and Gemini CLI as their vendors
  ship them (§4.3), interactive in tmux, with a terminal the person can take over. A developer who
  already chose Claude Code for coding gains nothing from swapping it for Hermes's loop, and on a
  Claude subscription loses the plan's allowance (the row above). shiftlead keeps that choice: the
  usage gate reads the subscription's own windows (§6 *Usage gate*).

## Does it usurp shiftlead?

**Partly; it is the nearest of the three.** Kanban covers ground shiftlead covers — named agents, a
shared board, review handoffs, worktrees, a PR that completes only on green checks — and it is free and
self-hosted. Where they part:

| | Hermes Agent | shiftlead |
|---|---|---|
| Who | technical individuals; open source | developers and tech leads running coding agents |
| Which agent | Hermes's own loop (Codex app-server as an opt-in runtime) | the person's tools as shipped: Claude Code, Codex, Gemini CLI, shells (§4.3) |
| Which model and bill | any provider by key; Claude Max only through extra-usage credits | the tool's own login and subscription (§6 *Usage gate*) |
| Workers | headless processes on a finite iteration budget | interactive sessions in tmux, each one attachable and typed into (§4.1, §4.5) |
| Hosts | Kanban on one host; the agent's commands on seven backends | the person's machines and container nodes under one home (§4.4a) |
| The person intervenes by | chat (TUI or a messaging app), the board, approval prompts | attaching to the terminal, Allow/Deny relayed to the UI (§4.2), mail (§4.10) |
| Consent | smart/manual/off approvals; an auxiliary model judges risk | the tool's own permission prompts, relayed; grants on every act of control (§4.8) |
| Repo rules | a PR completion contract per task | branch → PR → review → squash merge as the repo's cadence, with its ledger and board (cadence §2–§4) |
| Learning | self-written skills and agent-curated memory | the repo's memory files, briefs and ledger, read by any tool |

## Can it run with shiftlead?

- **shiftlead running Hermes: yes, and it is the useful pairing.** `hermes` is a terminal program,
  so it runs today under the `shell` adapter, scraped (§4.3). A hook-fed adapter looks feasible:
  Hermes has *"four hook systems"*, one of them shell hooks set in a profile's `config.yaml`, running in
  the CLI, gateway and TUI, where *"a shell `pre_tool_call` hook can block or fail closed"*; the event catalogue
  includes `on_session_start`, `on_session_end`, `pre_tool_call`, `pre_approval_request` and
  `subagent_stop` ([hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks)).
  `pre_approval_request` is an observer (*"return ignored"*), so the hook could show a question in
  the UI but not answer it; the answer would go back as keys, or through the TUI gateway's JSON-RPC,
  which is for hosts *"that want fine-grained control of sessions, slash commands, approvals, and
  streaming events"* ([programmatic integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration)).
  Which events reach a shell hook, as opposed to a plugin hook, was not checked. Running Hermes this
  way gives a team a non-Anthropic worker with its own memory, under shiftlead's rules.
- **Hermes running shiftlead's tools: no.** It cannot run Claude Code as a worker or a provider (the
  closed PR above), and its Kanban workers are Hermes profiles. Its Codex runtime is the one
  exception, and it embeds Codex rather than handing over a session.
- **Hermes driving shiftlead: possible, not wanted.** A Hermes agent on the same machine could run
  `ao`, and an `ao` call with no `SHIFTLEAD_SESSION` is the person (§4.8a): the same hole as a Grok
  Bot driving it. Its messaging gateway overlaps shiftlead's own Telegram notice (§4.10 *Told on
  Telegram*); the two need not meet.
- **Both on one repo: not without a rule.** Hermes Kanban workers in worktrees and shiftlead sessions
  in worktrees would each believe they own the queue; pick one org per repo.

## What to learn

1. **A completion contract that reads the forge's own required checks.** Hermes refuses to call a PR
   task done until branch protection's required checks pass on the exact head. shiftlead's
   `check_cadence.py` reads CI too, as a detector (cadence §7); Hermes makes it the definition of done.
   *A note for whoever next designs Ready to close; not filed.*
2. **A budget warning before the cap.** A worker is told near 90% of its iteration budget to report or
   checkpoint. shiftlead's analogue is context and usage; a nudge to write the ledger before a session
   runs out is the same idea. *A note, not filed.*
3. **Hermes as a worker tool.** An adapter row in §4.3's table, hook-fed if the shell hooks carry
   the events above, would make shiftlead the place a team mixes Claude Code with an open,
   model-neutral agent. *A note, not filed.*

**Not wanted:** an agent loop that replaces the vendor's harness for the person's main coding tool,
headless workers with no terminal to take over, an auxiliary model as the default judge of what is
dangerous, and a board that is single-host by design.

## What was checked

Re-read from the vendor's pages: the README (licence, TUI, gateway platforms, learning loop, cron,
subagents, seven backends, providers, `claw migrate`, trajectories); the providers page (Anthropic
OAuth, extra usage, Pro excluded, Ollama and vLLM); Kanban (the board, toolset, engineering pipelines,
PR completion contracts, *never automatically completes*, single-host); hooks (four systems, shell
hooks, `pre_tool_call` blocking, the event names, `pre_approval_request` as an observer); security
(approval modes, timeout, per-mode defaults, *does not sandbox*); worktrees; the Codex runtime; Bot
Mode; programmatic integration (ACP, TUI gateway, API server, no `--mode rpc`). From GitHub: the
repository's creation date, stars and latest release, and issue #48320 closed as a duplicate of #33462,
whose implementing PR #40528 was closed unmerged. Not used: coverage of funding and launch dates (search summaries only).

## What this ADR does not do

It approves nothing and files nothing. The §3 table gains one row pointing here; the three lessons
are notes.
