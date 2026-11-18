# ADR 2026-11-18: Tools, Flows and Team pages — the frame

Status: **for discussion**. Class: in-repo. This is the frame for three design rounds: TD-1953 (the Tools
page), TD-1954 (the Flows page) and TD-1153 (the team page), worked out with Paul on 2026-11-18 in
session td-1153. It holds only what cuts across the three pages: where each thing lives, how a seat's
model and login are chosen, which seats a flow has, and which current rules that reverses. Each page's
own questions and holes are in its ledger entry, as that round's starting list. Nothing here changes
the design until a round writes it there.

Review rounds: the design held on 2026-11-18 (Paul). Round 1 (Sonnet) read the plan before this split,
and its twelve findings are applied; the record is `docs/reviews/TD-1953.md`. Three earlier reads (Fable,
Sonnet, Fable, on PR #4110) came while the design was still changing and are not counted.

## Why three pages

Paul, 2026-11-18: a person should choose the model and subscription each seat runs on, see a flow and the
seats it uses, and run a team from one page. Today all three are hand edits or scattered:

- **Who runs on what** is a **profile** (CLI, account, model and options, §4.2a) in `~/.shiftlead/profiles.yml`,
  written by hand and picked by name in five rungs (§4.9) and a dozen other places.
- **The path work takes** is a flow, a directory of `flow.yml` and stage briefs in the package, the org
  or a repo, naming roles only (§4.9c).
- **A team's running settings** are `settings.yml` keys on the Settings page's team card; its
  **definition** is a block of `org.yml` or the repo's `.shiftlead.yml` (§5, ADR 2026-09-25).

The order is fixed: **Tools, then Flows, then Team**, each designed in its own round with the others in
mind. A flow names models the Tools page knows, and a team picks a flow and lists its logins.

## Where each thing lives

**What is the install's is saved at once; what is shared through git goes by PR** (the settings ADR's
rule).

| Thing | Lives in | Written | Page |
|---|---|---|---|
| Tools and services found, their versions, logins and identity, the models each login offers, each login's reserve and reading | each tool's own config directory (read); `settings.yml` | detected; reserves at once | Tools |
| A login: its tool, account, config directory, `billing` (a metered one's `prices`), `extra_args` — each host its own | `profiles.yml` (each host's) | at once, by the person's pages only | Tools |
| A flow: its id, stages, seats (each by a key), triggers, briefs, each seat's model and `permission_prompts`, its review-round settings | the flow's directory (package: read-only; org: committed by the home; repo: by PR) | as the flow is | Flows |
| The team's one ordered login list, across tools | `settings.yml` | at once | Team |
| Flow pick, seat counts (`size`, `max`, by seat key), hours, reserve priority, balance, on_work | `settings.yml` | at once | Team |
| The team's definition: the flows it lists, and each seat's name and brief by the seat's key | `org.yml` (at once) or `.shiftlead.yml` (by PR, under the full cadence) | rarely | Team |
| Which team's question seat tags a repo's untagged entries | the repo's settings | at once | Team |

**Profiles leave the person's view** (Paul, 2026-11-18). The **model** is the flow's, and so is how a seat
runs (`permission_prompts`); the **login** is the Tools page's. A profile survives only inside, as what a
model and a login compile to at a launch, written by the launching host from its own `profiles.yml`.
Sessions no flow runs (`ao new`, the director, the sweep, a scheduled start, the person's own session)
pick a login and a model the same way. Nothing overrides a seat's model or login: a member's own
`profile:` and the role overlays' profiles go (Paul: overrides are complexity not needed). A seat that runs
differently, such as the grind-ask trial's permission prompts, is a flow copy with that seat changed.

## Which seats a flow has

Today the techlead, auditors, fact-checkers and sweeper are the team's `seats:`, run under every flow, and
"a seat never sits out" (§4.9c). Paul: the flow says which seats exist and when each is used.

1. **Every team has a manager** (on call, or `person`), automatic; the flow names its model, under the
   fixed key `manager`.
2. **Everything else is the flow's**: its stages (design, build, review, hunt, ...) and its on-call seats
   — the **question seat** (key `question`: the go-between that answers a member's steer or work
   question or passes it up, and that another repo's `--team`/`--repo` ask finds, §4.9b), a review
   stage's reader on held paths, the auditors (`prs: 10`), the fact-checkers (`asks`), a sweeper
   (`swept:`). **A flow that names no question seat sends questions to the person** (Paul, 2026-11-18),
   as a team without a techlead does today (§4.9b): `{techlead}` names the person, `--team`/`--repo`
   asks reach the person's Inbox, and `entries.feature` stores a literal `person`. A flow may leave any
   of these out; a seat a switch leaves out still answers what it was already asked, then closes (§4.9c
   *A switch mid-chain*, whose reason stays). A flow switch reaches a running team only through Apply
   (Paul), which waits until the question seat holds no open ask.
3. **The director** stays the org's, outside any team, on the Settings page.

**Tagging is the repo's, not a flow's** (Paul, 2026-11-18). Where a repo has more than one team, an entry
filed without a `Team:` line is handed to a tagging seat that writes it (§4.4 *An entry names its team*);
today that is the first live team's techlead, marked `tags: true`. It chooses between teams, so no one
team's flow owns it: the repo names which team's question seat tags, defaulting to the first live team's
where that is a session, else the person. A one-team repo, as every repo here is, needs none.

**A seat line splits by a key** (§4.9b's `{name, role, trigger, brief, profile}`; `home:` is refused since
TD-722). The flow holds what can be shared — the key, the role, the trigger with its argument, the model,
`permission_prompts`, a context bound; the team holds what is its own, by that key — the seat's
org-unique name and its brief. Two fact-checker seats on Gemini and Grok are told apart only by the key.
Seat counts (`size`, `max`) are keyed by it too. The ordered pool (§4.9b) is retired: it is a list of
profiles, and no definition here uses one.

**Every team runs a flow** (Paul, 2026-11-18): a flow is opt-in today (§4.9c), and there is no *none*
flow, since a flowless team's per-role `review:` and team-held seats cannot be written as one. The
plainest is the built-in `build`. Every team here already runs a flow.

## Every flow covers the minimum tasks

The process runs on git and PRs, so a flow is followable only if each task has someone, its own or the
default. The Flows page checks every flow against the list, as §4.9c checks followability today.

| Task | Default when the flow names nobody |
|---|---|
| Merge a PR | the author, on the cadence's gate (cadence §4.2); under a review stage, its last reader |
| Run the precheck on a PR's head | the author or the merger (cadence §4.12); main's own is the home's |
| Review evidence (`cadence-review:`; a fact-check for docs) | the author's independent reviewer (cadence §4.8) |
| Read a held path (`held:`) | the review stage's reader; with no review stage, nobody, and the author merges on the gate (§4.9c) |
| Answer a member's question | the flow's question seat; with none, the person |
| File entries and write the board | each session, through the helpers |
| Notice stalls, permissions, idle-with-work | the manager and the tick of the host the team runs on |

Escalation to the person and promoting the live copy are fixed: no flow changes them.

## A flow names its models; the team lists its logins

Paul, 2026-11-18: *part of defining a good flow will also be defining which models do which parts — if
those models are not available on a machine, then that machine cannot run that flow (the user can copy
and modify it to fit). That way in theory people could share flows with each other, and in theory we
could benchmark different flow results.*

- **A seat names a model by family** — `opus`, `sonnet`, `flash-lite`, the tool's own word — never a
  version, a tool, an account or a login. The tool runs its default version; the version a session ran is
  read from its transcript for metrics. One model may be reached through more than one tool (Paul: an
  aggregator such as poe.com), so **the tool is the login's**, and a flow pins none (decided; each run's
  tool is kept for metrics).
- **The team keeps one ordered login list across tools** (Paul: *my flow could say opus, then my teams
  page says (claude-paul, claude-heather, claude-api)*; `poe-paul, claude-paul`). A team whose list
  holds no login that can run a seat's model cannot follow the flow, and the page says why.
- **Every launch takes the first usable login offering the seat's model** — a start, a restart, a seat
  fill and a td-max extra alike. **Usable**: signed in; not gated (its account at its reserve, §6) or
  `limited`; not on an account an earlier unusable login shares (a reserve is the account's, §6); and with
  a smoke pass for its tool, the model and the seat's role. A launch record holds the model, never a
  login; the session's record gains `model` and `login`, and the definition's compare (§4.9c, TD-619)
  reads the model, so a seat on a backup login reads no difference and a reordered list takes effect at
  each next launch.
- **A stopped seat moves** (Paul: *hitting either the reserve or a hard limit should trigger the backup*).
  An unattended seat that is gated or `limited` is relaunched by the tick of the host it runs on on the
  next usable login — the same seat and record, so a review stage keeps one reader. With none usable it
  waits, as today. An interactive session is never moved (invariant 5). Meanwhile its questions go to its
  extras, then the person (§4.9b).
- **Every handoff starts from the transcript** (Paul: *all handoffs should probably use the same
  (transcript) method*): the new session is seeded from the transcript ShiftLead keeps, never a tool's own
  resume, and an open ask stays on the seat's mail.
- **A metered login** is used in its place in the list (decided), bounded by its amount reserve; the page
  marks it, since moving onto it spends money.
- **Backups are logins, never models.** Falling back to another model is out of scope; if it is ever
  wanted it is the flow's, perhaps a **failover flow** with its own model set (Paul).
- **Known smoke passes ship with ShiftLead** (Paul), per tool version, model and role, so a person does not
  re-run a smoke someone already has; their own passes add to it. The gate is on from the first build,
  the list seeded with every tool, model and role running here today.

## A flow has an id, and may set its review rounds

- **An id** (Paul): `flow.yml` carries an `id` written at creation, a built-in's fixed in the package.
  Everything that names a flow names the id; the name is a label, free to change. A copy takes a new id;
  there is no `from:` (Paul: a copy may change past resemblance). A benchmark needs the **content hash**
  of the flow a run used, which, with the flow's id, the model version and the tool, goes to a store of the
  client's own read by no rule — never the session's record (invariant 9).
- **Review rounds** (Paul: *a lever that will want to be played with*): agent-cadence reads every setting
  from `CADENCE_<KEY>` before the repo's file (cadence §9.18), and ShiftLead launches every session, so a
  flow may set `review-model`, `fact-check-model`, `design-rounds` and `design-rounds-wide` on a seat. Only
  agent-cadence's config reader and review statistics read them, not the merge gate. Convergence and
  sticking-point settings are prose in cadence §4.8 today, so they are agent-cadence's to add.

## Which current rules this reverses or bends

- **§4.9c orthogonality** — reversed: a flow's seat names its model; the tool is the login's.
- **§4.2a profiles** — no longer named by the person anywhere; every place that takes one by name (§4.9's
  five rungs, `schedule.profile`, `sweep.profile`, `director.profile`, `ao new --profile`, `ao team start
  --profile`, *Switch profile…*) changes, and today's profiles, definitions and settings migrate.
- **§4.9c "a seat never sits out"** — reversed for a flow's seats.
- **§4.9b's techlead, optional and never `person`** — becomes the flow's question seat, the person by
  default; §4.9b's *ask the person when there is no techlead* is the same rule restated.
- **§4.9b *A seat as an ordered pool*** — retired; **§4.9b *A seat that cannot answer is routed around***
  — a stopped seat's questions go to its extras, then the person.
- **§4.4's tagging seat** — chosen by the repo's setting, not by `tags: true` on a techlead.
- **The record and invariant 9** — the record gains `model` and `login`; a launch record holds the model;
  the compare reads *model a → b*. The `relaunch` mark, today a person's act carrying `profile`, carries a
  `model`, and the tick's relaunch of a stopped seat is a path of its own. Invariant 9 is amended to say so.
- **§6's usage gate** — a gated seat moves to the next usable login before it pauses.
- **§4.3 *Nobody answers the box … waits for a person*** and **§4.3, §4.5a *Switch profile…*** (a person's
  control, not built, resuming with `--resume`) — the tick relaunches an unattended gated or `limited`
  seat, handed over from the transcript.
- **§4.3's install rule** (never run by ShiftLead or a session) — kept: the Tools page opens a Shell tab
  with the install typed, and the person runs it.
- **Definition edits from a page** — a repo team's or repo flow's edit is a PR under the full cadence; no
  self-merging road, since an edit of `.shiftlead.yml` can rewrite `held:` itself.
- **§4.5a** — every control on the three pages gets a row and an `ao` verb, or a stated exception.
