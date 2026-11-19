# ADR 2026-11-18: Tools, Flows and Team pages — the frame

Status: **for discussion**. Class: **wide** (reclassed by Paul after round 3, 2026-11-18: the migration
rewrites every team repo's `.shiftlead.yml`, and `flow.yml` becomes a format meant to be shared), capped
at `design-rounds-wide`. This is the frame for three design rounds: TD-1953 (the Tools
page), TD-1954 (the Flows page) and TD-1153 (the team page), worked out with Paul on 2026-11-18 in
session td-1153. It holds only what cuts across the three pages: where each thing lives, how a seat's
model and login are chosen, which seats a flow has, and which current rules that reverses. Each page's
own questions and holes are in its ledger entry, as that round's starting list. Nothing here changes
the design until a round writes it there.

Review rounds: the design held on 2026-11-18 (Paul). Round 1 (Sonnet) read the plan before this split,
rounds 2 to 6 (Fable, Sonnet, Fable, Sonnet, Fable) the frame; their findings are applied (rounds 5 and
6 returned FIXED; round 5 found nothing build-changing), those on the director's part
moved with it to TD-1956 (Paul, 2026-11-18); the record is `docs/reviews/TD-1953.md`. Three earlier reads (Fable,
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
| Tools and services found, their versions, logins and identity, the models each login offers, each account's reserve and reading (a reserve is the account's, §6) | each tool's own config directory (read); `settings.yml` | detected; reserves at once | Tools |
| A login: its tool, account, config directory, `billing` (a metered one's `prices`), `extra_args` — each host its own | `logins.yml` (each host's, §4.2b; `profiles.yml` is hand-written and goes at the cut-over) | at once, by the person's pages only | Tools |
| A flow: its id, stages, seats (each by a key), triggers, briefs, each seat's model and `permission_prompts`, its review-round settings | the flow's directory (package: read-only; org: committed by the home; repo: by PR) | as the flow is | Flows |
| The team's one ordered login list, across tools | `settings.yml` | at once | Team |
| Flow pick, seat counts (`size`, `max`, by seat key), hours, reserve priority, balance, on_work | `settings.yml` | at once | Team |
| The team's definition: the flows it lists, and each seat's name and brief by the seat's key | `org.yml` (at once) or `.shiftlead.yml` (by PR, under the full cadence) | rarely | Team |
| Which team's question seat tags a repo's untagged entries | the repo's settings | at once | Team |

**Profiles leave the person's view** (Paul, 2026-11-18). The **model** is the flow's, and so is how a seat
runs (`permission_prompts`); the **login** is the Tools page's. A profile survives only inside, as what a
model and a login compile to at a launch, written by the launching host from its own `profiles.yml`.
Sessions no flow runs (`ao new`, the director, the sweep, a scheduled start, the person's own session)
pick a model where they are set, and their login where they start: the person's own session in + New or
`ao new --login`, and the director, the sweep and a scheduled start from an ordered `logins:` beside the
`profile:` each replaces (§4.2b, TD-1953's round dropped the install-wide default list). Nothing overrides a seat's model or login: a member's own
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
   (`swept:`). **A flow that names no question seat leaves its members' questions to the person**, as a
   team without a techlead does today: a member's brief reads `{techlead}` as `none` and says *ask the
   person* (§4.9b). Whether the director takes that load is TD-1956's, outside this frame (Paul,
   2026-11-18: *drop the director from this discussion for now and pick it up in another TD*). As today,
   another team's `--team`/`--repo` ask is refused with *has no question seat — ask the person* (§4.10), and a session's request to file
   an entry in the repo is refused (§4.9b); `entries.feature` defaults, as today, to the role of
   the stage that takes `design-first`, else to the question seat's role (§4.9c), and where the flow has
   neither, to a new value, `person`: an entry the person picks up. No member's question reaches the person that
   did not today. **The record marks the question seat**: a start writes it
   on the seat's `seat` mark (today `tags: true` does this, §4.10, TD-1565), so `--team` never finds a
   fact-checker, which is also an `asks` seat. A flow may leave any of its seats out. **A switch drops a
   seat by one rule**: the seat still answers what it was already asked, then closes (§4.9c *A switch
   mid-chain*, whose reason stays); the switch itself waits for nothing. The question seat joins the
   compare (§4.9c, TD-619), so a member whose brief named the dropped seat as `{techlead}` reads
   *definition changed* and is relaunched with the new one at Apply; an interactive member is never
   relaunched (invariant 5), and is told the new seat instead.
3. **The director** stays the org's, outside any team, on the Settings page.

**Tagging is the repo's, not a flow's** (Paul, 2026-11-18). Where a repo has more than one team, an entry
filed without a `Team:` line is handed to a tagging seat that writes it (§4.4 *An entry names its team*);
today that is the first live team's techlead, marked `tags: true`. It chooses between teams, so no one
team's flow owns it: the repo names which team's question seat tags (`settings.yml` `repos.<repo>`, §5),
defaulting, as today, to the first live team in the repo's declared team order (§4.4) whose flow has a
question seat. Where none has, the home puts a Queue item before the person naming the untagged entries;
today only the Repo page and `ao repo` say why nobody tags (`teamrun.tagging_seat`). A one-team repo, as every repo here
is, needs none.

**A seat line splits by a key** (§4.9b's `{name, role, trigger, brief, profile}`; `home:` is refused since
TD-722). The flow holds what can be shared — the key, the role, the trigger with its argument, the model,
`permission_prompts`, a context bound (the flow's alone, re-asked when its model changes); the team holds what is its own, by that key — the seat's
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
| Answer a member's question | the flow's question seat; with none, the person (the director's part: TD-1956) |
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
  (transcript) method*): the new session is seeded from the old one's transcript, never a tool's own
  resume, and an open ask stays on the seat's mail. ShiftLead keeps only a transcript's path; the file is
  the tool's, under the login's config directory, and on a node the node's (§4.3). So the handoff is a
  new adapter-contract method — read a transcript into a bounded handoff text — on the host that ran
  it; it is cross-cutting, and the cut-over build's design takes it (moved there by TD-1953's round: a
  handoff is a launch's, not a login's).
- **A metered login** is used in its place in the list (decided), bounded by its amount reserve; the page
  marks it, since moving onto it spends money.
- **Backups are logins, never models.** Falling back to another model is out of scope; if it is ever
  wanted it is the flow's, perhaps a **failover flow** with its own model set (Paul).
- **The cut-over from profiles** — every launch moving from a named profile to a model and a login —
  needs the Flows round's model and the Team round's list, so it is built after both, and it happens **in
  one window** (*Moving every repo over*, below; Paul, 2026-11-18: the two shapes never run side by side).
  Until the window every launch is today's: the profile rungs (`org.yml`'s `roles:` profiles among them) and
  a team's own `techlead:` and `seats:`. The pages, logins and the new launch path are built and promoted
  before it, read by nothing. At the window `profiles.yml` and the `roles:` profiles go, and each host's
  logins are in its `logins.yml` (§4.2b).
- **Known smoke passes ship with ShiftLead** (Paul), per tool, model and role, so a person does not re-run
  a smoke someone already has; their own passes add to it. The gate is on from the first build, the list
  seeded with every tool, model and role running here today. **The gate keys on tool, model and role, not
  on the tool's version**: each pass records the version it ran on, and a new version is only told, once a
  day, as §4.3 does today, so a tool that updates itself never strands every seat on it; a pass is lost only
  when a smoke on the new version fails.

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

## Moving every repo over, and sharing a flow

The plan is wide: it changes every repo with a team, and makes `flow.yml` a format meant to travel.

- **One window, no dual read** (Paul, 2026-11-18). Every part of the new shape is built and promoted
  first, read by nothing; the old shape keeps running until the window. Six repos — samscrape,
  contractmatch, ledgerboard, agent-cadence, guardians-devenv and shiftlead itself — write `techlead:
  {name, context}` and name built-in flows by directory, so each has its move ready beforehand as a green,
  reviewed PR, held unmerged. `ao migrate --check` runs on every host before the window and names whatever
  the migration would refuse (below and §4.2b), for the person to fix in the old shape first. **The window**:
  every team is stopped (the person's own sessions stay, in tmux); `ao migrate` runs on the home and on each
  node — the home's files in one commit of its tracked definitions (§4.9), a container node re-provisioned
  with the new wheel, a machine node (guardians-devenv) updated by the person; the six repo PRs merge,
  shiftlead's last; the reader switches to the new shape alone; the teams restart. `ao org check` says
  when every repo and node is on it. **Going back** reverts the migration's commit, runs `ao promote --back`,
  and reverts the repo PRs, an older reader refusing a moved repo's file; nothing else holds a rollback.
  A built-in flow's id is its name (`td`, `build-review`, `build`), so `flows: [td]` and `flow: td` keep
  reading; an org or repo flow with no `id` reads as its directory's name until it is saved with one.
  `techlead.context` (today the techlead's primer) goes with the question seat's brief, on the team's side of
  the split.
- **A format version.** `flow.yml` carries `format: <n>`, read before the stray-key check (§4.9c), and a
  flow with none reads as format 1. A flow from a newer ShiftLead reads *made by a newer ShiftLead*, never
  a stray-key refusal; a repo flow that writes a new key waits on the promote that accepts it, as `color`
  did (TD-1765); a shared flow carries or names the roles it uses, since a
  role lives outside the flow's directory; the Flows page says which of model, role or smoke pass is
  missing where a flow cannot be followed. The content hash covers the flow's resolved `package:` briefs,
  or the package version with them, so two versions never hash alike.
- **A model swap on a node team is a repo PR** (decided, Paul, 2026-11-18: flows live in the repo when
  customised): org flows cannot run on a node
  (§4.9c), so a node team's flows are its repo's, and changing a model there is a PR, where an org team's
  is saved at once.

## Which current rules this reverses or bends

- **§4.9c orthogonality** — reversed: a flow's seat names its model; the tool is the login's.
- **§4.2a profiles** — no longer named by the person anywhere; every place that takes one by name (§4.9's
  five rungs, `schedule.profile`, `sweep.profile`, `director.profile`, `ao new --profile`, `ao team start
  --profile`, *Switch profile…*) changes, and today's profiles, definitions and settings migrate.
- **§4.9c "a seat never sits out"** — reversed for a flow's seats; and §4.9c's *a seat is `org.yml`'s,
  which no flow compiles* — a flow now compiles its seats.
- **§4.9c *a flow's name is its directory's*, *a flow is found by its directory*** — a flow is named and
  found by its `id`; its name is a label; and §4.9c's stray-key refusal in `flow.yml` reads `format` first.
- **§4.9c *A flow is opt-in*** — reversed (every team runs one); §4.9c's rejected alternative *`td` as
  every team's default* stays rejected: a team picks its flow.
- **§4.9b's techlead, optional and never `person`** — becomes the flow's question seat, the person by
  default; §4.9b's *ask the person when there is no techlead* is the same rule restated.
- **§4.9b *A seat as an ordered pool*** — retired; **§4.9b *A seat that cannot answer is routed around***
  — a stopped seat's questions go to its extras, then the person.
- **§4.4's tagging seat** — chosen by the repo's setting, not by `tags: true` on a techlead. `seat.tags`
  splits in two: the question mark (every question seat) and the tagging mark (the one seat the repo's
  setting names, written at its team's start, the tick's `tag` cause reading it). Every reader of `tags`
  moves to one or the other: §4.10's `--team`/`--repo` choice (TD-1565, `agent_mail._one_seat`), an
  entry's reroute and filer (`agent_mail`), the tick's `tag` cause (`agent_tick`), and
  `teamrun.tagging_seat`.
- **The record and invariant 9** — the record gains `model`, `login`, the seat's key and its question mark,
  and `permission_prompts` compiles into a field a start writes beside `lane`, `review` and
  `prompt_from`; a launch record holds the model; the compare reads *model a → b* and the question seat.
  Under invariant 15 the home holds a record's intent: the home writes `model`, and a node's tick, which
  picks the login at a node launch, reports the `login` it took. The `relaunch` mark, today a person's act carrying `profile`, carries a
  `model`, and the tick's relaunch of a stopped seat is a path of its own. Invariant 9 is amended to say so.
- **§6's usage gate** — a gated seat moves to the next usable login before it pauses.
- **§4.3 *Nobody answers the box … waits for a person*** and **§4.3, §4.5a *Switch profile…*** (a person's
  control, not built, resuming with `--resume`) — the tick relaunches an unattended gated or `limited`
  seat, handed over from the transcript.
- **§4.3's adapter contract** — gains the transcript handoff method (above). §4.3's tool-version rule (a
  new version is told, nothing stops) is kept: the smoke gate does not key on the version.
- **§4.3's install rule** (never run by ShiftLead or a session) — kept: the Tools page opens a Shell tab
  with the install typed, and the person runs it.
- **Definition edits from a page** — a repo team's or repo flow's edit is a PR under the full cadence; no
  self-merging road, since an edit of `.shiftlead.yml` can rewrite `held:` itself.
- **§4.5a** — every control on the three pages gets a row and an `ao` verb, or a stated exception.
