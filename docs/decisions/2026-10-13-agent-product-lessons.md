# ADR 2026-10-13: Lessons from Grok Bot, Muse and Hermes Agent — for discussion

Status: **for discussion** (2026-10-13, at Paul's request). Nothing here is designed, filed or
approved. It gathers what the day's three surveys — [Grok Bot](2026-10-13-grok-bot.md),
[Muse](2026-10-13-muse.md) and [Hermes Agent](2026-10-13-hermes-agent.md) — suggest shiftlead learn,
says for each what shiftlead already has, and asks the question a discussion should settle. A lesson
Paul picks becomes a design round and a TD entry; one he declines is marked so here.

## Where shiftlead stands (Paul, 2026-10-13)

*"It seems like someone would use either Hermes or ShiftLead — both would be a bit cumbersome. I
think being able to get into a terminal session (take control) and being able to use subscriptions
are big differentiators for us."*

Every product surveyed today runs its **own** agent loop; none lets the person take over a live
session, and none runs on the person's coding-tool subscription (Hermes reaches Claude Max only
through purchased extra-usage credits, Grok Bot and Muse not at all). shiftlead already says both:

- **Take control:** goal 2, *"Read and drive a session in place: full conversation in an embedded
  terminal, type prompts, answer menus in the terminal"* (§2).
- **Subscriptions:** *"The person's Claude Max login, their repos, their tools, and the cost of what
  their sessions do stay with them"* (§4.5c); the usage gate plans around the subscription's own
  windows (§6 *Usage gate*).

So the lessons below are judged by one test: **does it make shiftlead better at running the
person's own tools, interactively, on their own subscription?** A lesson that would need shiftlead
to grow its own agent loop fails it.

## The lessons

Size is a guess: *small* is one TD build, *medium* a design round and a build, *large* several.

### 1. A second line of defence on permission prompts

- **From:** Muse's Sentinel gates everything the agent sends out, read and write kept apart; Grok
  Bot's Auto-review rules, which decide which actions stop for approval (*Ask first* winning a conflict); Hermes's
  `smart` approvals, where an auxiliary model judges risk.
- **shiftlead now:** every prompt is relayed to the UI's Allow/Deny (§4.2); a team's manager session
  triages its members' prompts by its brief — allow what the brief plainly covers, deny anything
  touching `~/.shiftlead`, `~/.claude`, systemd or another worktree, escalate questions
  (`src/shiftlead/briefs/manager.md`). Some prompts never reach the hook because the tool's own
  settings pre-allow them (the allowlist tdgrind ships, §4.2). No shiftlead-side rule set; and
  *"Allow for this session"* was decided **no, not now** (2026-09-23, §10).
- **How it might fit:** per-role allow/deny rules the host agent checks before a prompt reaches
  anyone — deterministic, in the role's settings (§4.8) — with the manager's triage and the person
  behind them. Unlike the declined *Allow for this session*, these would be per role and written
  down, not granted from a prompt. A model-judge is the later, optional step.
- **Caution:** Hermes's own security page says its denylist *"does not sandbox a hostile or
  compromised agent"*; rules cut noise, they are not a boundary. Claude Code's own permission
  settings already do some of this per profile.
- **Size:** medium. **Question:** rules in shiftlead, or lean on each tool's own permission settings
  per profile and only show them?

### 2. A locked setting says it is locked

- **From:** Grok Bot shows an org-level rule on the person's settings as *"Required by your admin.
  You can't edit or delete this rule."*
- **shiftlead now:** settings come in layers — the package default, a repo's `.shiftlead.yml`, the home's
  settings file (§5; the context bound's two layers, §4.8) — with no "set by the repo" mark on the
  Settings page.
- **How it might fit:** a setting fixed by a higher layer is drawn read-only, naming that layer.
- **Size:** small. **Question:** worth it now, or only once more than one person shares a home?

### 3. Show what a session plans, not only what it did

- **From:** Muse's *"audit trail showing everything Muse has done and plans to do"*.
- **shiftlead now:** `ao progress` claims and outcomes (done, dropped, blocked, restart, none, §4.7),
  shown on the team card (§4.5a); and the session's own `doing` line (§4.8), drawn on the card and as
  Focus's *Working* panel (§4.5a) — what it is doing **now**. Nothing says what comes next.
- **How it might fit:** extend `doing` with a short *next* list, or let a claim carry a plan
  (`ao progress claim TD-123 --plan "…"`), shown beside *Working* and replaced as the session moves on.
- **Size:** small. **Question:** useful to you when you glance at the org view, or noise?

### 4. Done means the forge's required checks pass on the exact head

- **From:** Hermes's PR completion contract reads branch protection's required checks on the PR's
  head before a task may complete; *"A commit or diff alone never automatically completes a task"*.
- **shiftlead now:** Ready to close needs the PR merged (§2 goal 11); `check_cadence.py`'s `ci` row
  reads the head's check runs, as a detector (cadence §7), not the protected branch's required set;
  `ao progress done <ref> --pr <n>` is accepted, then checked at the home on the reports' cadence
  (§6 rule 10): the member is told its failing rows, and a second fail or a fail on a merged PR
  becomes an Inbox row.
- **How it might fit:** check at declaration time — refuse `done … --pr <n>` while the PR's required
  checks are red or missing — and have `check_cadence.py` read the protected branch's required set
  rather than every run.
- **Size:** small to medium. **Question:** refuse, or accept and mark the claim *done · checks
  pending*?

### 5. Warn before the wall, not at it

- **From:** Hermes tells a worker near 90% of its iteration budget to checkpoint or report.
- **shiftlead now:** the context bound speaks only once a session is **over** it (§6 rule 5): a
  fixed line when it is idle, repeated after twenty minutes, and a clause on every `ao` reply while
  it works; the usage
  gate pauses at a window's line (§6 *Usage gate*); TD-460 is reading back a 200k bound.
- **How it might fit:** one earlier line at, say, 80% of either — *finish this entry, push, ledger;
  take nothing new* — so a session parks cleanly instead of being stopped mid-entry.
- **Size:** small. **Question:** fold into TD-460's read-back?

### 6. Briefs and routines from a session the person drove

- **From:** Grok Bot saves a routine from a demonstration (*show it once, it saves the steps*);
  Hermes writes skills after a complex task.
- **shiftlead now:** briefs are hand-written files (`docs/briefs/`, the shipped `anchor.md` and
  `manager.md`), sent as the first prompt (§4.1).
- **How it might fit:** *Save as brief* on a session: a session drafts a brief from that transcript,
  landed by PR like any other brief, so it stays readable and reviewed.
- **Size:** medium. **Question:** do you find yourself repeating the same driven session often
  enough to want this?

### 7. Memory that grows, but stays readable

- **From:** Hermes's *"closed learning loop"* — agent-curated memory, self-improving skills.
- **shiftlead now:** `docs/claude-memory/`, one fact per file, landed by PR (cadence §7.1–§7.3);
  skills are static. Grok Bot's ADR names memory the person cannot read as *not wanted*.
- **How it might fit:** at wrap-up, a session proposes memory entries from what it hit, as a PR the
  person or techlead reads — the learning loop, kept in the repo.
- **Size:** medium. **Question:** is Claude Code's own memory plus today's convention enough?

### 8. Name the model that served each turn

- **From:** Grok Bot's analytics name the model that served each request, routing hidden or not.
- **shiftlead now:** the card shows the model in use when the adapter can tell (TD-031, §4.2a); a
  metered profile records a model per turn for spend (§4.3); nothing for subscription profiles.
- **How it might fit:** the record keeps the model changes of a run (model and time), shown in Focus.
- **Size:** small. **Question:** has a fallback or a mid-run model switch ever mattered to you?

### 9. Reach from a chat app

- **From:** Hermes's gateway (Telegram, Discord, Slack, WhatsApp, Signal), Muse on WhatsApp, Grok
  Bot on X and mobile.
- **shiftlead now:** one-way Telegram: one message, with a link, for a row that stops a session or a
  team while nobody is looking (§4.10 *Told on Telegram*).
- **How it might fit:** answer from the message — Allow/Deny, a steer's pick — through the same
  grants as the UI (§4.8). Taking control still means the terminal. **It runs into a rule:** a
  message sends no pending text, question words or `doing` line, because it leaves the machine
  for a third party's servers (§4.10 *What a message says*); answering needs that text, or blind
  buttons.
- **Size:** medium. **Question:** is a link to the page enough, or do you want to answer from your
  phone?

### 10. New harnesses as tools

- **From:** Hermes has shell hooks (session start and end, a blocking `pre_tool_call`, an observer
  `pre_approval_request`); Muse Code keeps a local event log.
- **shiftlead now:** §4.3's table; TD-112 (*a scraped second-adapter spike*) is open, with neither
  Codex nor Gemini CLI installed on kmaster.
- **How it might fit:** TD-112's spike first, on a tool people already run beside Claude Code (Codex
  or Gemini CLI). By Paul's either/or, Hermes is a weak candidate: its users want its loop, not
  shiftlead's.
- **Size:** medium per adapter. **Question:** confirm Codex or Gemini CLI first, Hermes and Muse
  Code later if asked?

## Not wanted, from the three between them

An agent loop that replaces the person's coding tool, and headless workers with no terminal to take
over (Hermes); a model chosen by the vendor (Grok Bot, Muse); memory the person cannot read, and one
shared computer for every agent (Grok Bot); a record that lives only in the vendor's product, and
training on the person's work by default (Muse).

## What this ADR does not do

It designs nothing and files nothing. Each lesson Paul picks gets a TD entry and, where marked
medium or larger, a design round; the answers are recorded here beside each question.
