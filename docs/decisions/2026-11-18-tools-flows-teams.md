# ADR 2026-11-18: Tools, Flows and Team pages — the plan, for discussion

Status: **for discussion**. Review rounds: none counted yet — the three reads so far (Fable, Sonnet,
Fable, on PR #4110) came while the design was still changing, and Paul counts the limited rounds only
from when it stops (2026-11-18). This is the high-level plan behind TD-1953 (the Tools page), TD-1954 (the
Flows page) and TD-1153 (the team page), written with Paul on 2026-11-18 in session td-1153 before any
of them is designed. It says where each thing lives, which current rules each page keeps or reverses,
and the open questions, each with a recommendation. A Fable review reads it before the first design
round. Nothing here changes the design until a round writes it there.

## Why three pages

Paul, 2026-11-18: a person should choose the CLI, model and subscription each seat runs on, see a flow
and the seats it uses, and run a team from one page. Today all three are hand edits or scattered:

- **Who runs on what** is a **profile** (CLI, account, model and options, §4.2a) in `~/.shiftlead/profiles.yml`,
  written by hand, and picked at five places in order: the package's role, `org.yml`'s `roles:` overlay,
  the repo's `roles:`, a member's or seat's own `profile:`, then `ao new --profile` (§4.9). Seats may
  take an ordered `pool:` of profiles as a fallback (§4.9b *A seat as an ordered pool*).
- **The path work takes** is a flow, a directory of `flow.yml` and stage briefs in the package, the org
  (`~/.shiftlead/flows/`) or a repo (`.shiftlead/flows/`), naming roles only (§4.9c).
- **A team's running settings** (flow pick, `size`, `max`, schedule, until, reserve priority, balance,
  on_work) are `settings.yml` keys on the Settings page's team card; its **definition** (members,
  seats, briefs, listed flows) is a block of `org.yml` or the repo's `.shiftlead.yml` (§5, ADR
  2026-09-25).

The order is fixed: **Tools, then Flows, then Team**, each designed in its own round with the others in
mind. A flow picks from what the Tools page knows, and a team picks a flow.

## Where each thing lives

The pages follow one rule the settings ADR already draws: **what is the install's is saved at once;
what is shared through git goes by PR**.

| Thing | Lives in | Written by | Page |
|---|---|---|---|
| CLIs and services found, versions, logins and their identity, the models each login offers, each login's reserve and reading | each tool's own config directory, read; `settings.yml` | detection, read-only; reserves at once | Tools |
| Account names, reserves per subscription (`usage_gate:`) | `profiles.yml`, `settings.yml` (the install's) | a writer RPC, at once | Tools |
| A login: its account, config directory, `billing` (and a metered one's `prices`), `extra_args` — per host | `profiles.yml` (each host's own) | a writer RPC, at once | Tools |
| A flow's stages, seats, triggers, briefs | the flow's directory (package: read-only; org: at once, committed by the home; repo: by PR) | the Flows page | Flows |
| Each seat's model, its `permission_prompts`, and its review-round settings | the flow's directory, with its seats | as the flow is | Flows |
| The team's ordered logins, across tools (the first that offers a seat's model, then backups) | `settings.yml` (the install's; see *A flow names its models*, below) | at once | Team |
| Flow pick, seat count ranges (`size`, `max`), hours, reserve priority, balance, on_work | `settings.yml` | at once (as the Settings team card does today) | Team |
| A team's definition (which flows it lists; each of a flow's seats' name and brief, by the seat's key) | `org.yml` (at once) or `.shiftlead.yml` (by PR) | rare; the page opens the PR | Team |

So most of the team page needs no PR at all; design PR #4076's "a repo team's edit lands as a PR" covers
only the rare definition change.

**Profiles leave the person's view** (Paul, 2026-11-18). A profile today bundles a CLI, an account, a model
and options (§4.2a), named by hand in `profiles.yml` and picked by name in a dozen places. The plan splits
it: the **model** is the flow's, and so is how a seat runs (`permission_prompts`); the **login** — the
account, its config directory, `billing` and `extra_args` — is the Tools page's. A profile survives only inside, as
what a model and a login compile to on a session's record. Sessions no flow runs (`ao new`, the director,
the sweep, the schedule, a person's own session) pick a login and a model the same way, never a profile
by name, so `profiles.yml` becomes the Tools page's store of logins. A seat that runs differently (the grind-ask
trial: one grinder with permission prompts on, `.shiftlead.yml`) says so on its seat in the flow, so a
trial is a flow copy with that seat changed, and needs no second login (Paul, 2026-11-18: agreed).

## Seats come in three tiers

Today the techlead, auditors, fact-checkers and the sweeper are the team's `seats:`, run under every flow,
and "a seat never sits out" (§4.9c). Paul wants the flow to say which seats exist and when each is used,
and some seats on every team. The plan splits them:

1. **Every team's seats** — the **manager** (on call, or `person`) and the **question seat**: the
   techlead's first job, the go-between that answers a member's steer or work question or passes it up
   (§4.9b), that another repo's ask finds by `--team`/`--repo`, and that tags entries where its line
   says `tags: true` (§4.9b, §4.4). Automatic: a team never lacks one. Today the techlead is optional and
   never `person` (§4.9b), and `{techlead}` reads `none` without one; the plan adds **`person`** as a value,
   under which `{techlead}` names the person, `--team`/`--repo` asks reach the person's Inbox, and
   `entries.feature`'s default role `techlead` falls to the person. Whether a tier-1 seat is a session
   or the person is the team's choice; its model, where it is a session, is the flow's. Whether the question seat and a
   review stage's reader stay one record, as they are today (§4.9c), is the Flows round's.
2. **The flow's seats** — its stages (design, build, review, hunt, ...) and its **on-call seats**: a
   review stage's reader on held paths (the techlead's second job), the auditors (`prs: 10`), the
   fact-checkers (`asks`), a sweeper (`swept:`). A flow may leave any of these out, reversing "a seat
   never sits out" for these seats only; the rule's own reason (§4.9c *A switch mid-chain*) stays: a
   seat a switch leaves out still answers what it was already asked, then closes.
   **What a seat line holds splits** (§4.9b: today `{name, role, trigger, brief, profile}`; its old
   `home:` is refused since TD-722, a team landing on one host, §4.9): the flow holds what is shareable —
   a **key** naming the seat within the flow (two fact-checker `asks` seats, one on Gemini and one on
   Grok, are told apart only by it), the role, the trigger with its argument (`asks`, `prs: 10`,
   `every:`, `swept:`), the model, `permission_prompts`, a context bound; the team keeps what is its own,
   by that key — the seat's name (org-unique), its own brief, and the techlead's `tags`. The manager's and
   techlead's other keys (`lane`, `grants`, `unattended`, `on_call`, `context`) are placed by the Flows
   round. `pool:` goes (below).
3. **The org's seat** — the **director**, outside any team. It stays on the Settings page, and picks a
   login and a model as every session no flow runs does.

## Every flow covers the minimum tasks

The process runs on git and PRs, so a flow is followable only if it says who does each of these, or
takes the default. The Flows page checks every flow against the list, as §4.9c checks followability
today.

| Task | Default when the flow names nobody |
|---|---|
| Merge a PR | the PR's author, on the cadence's gate (cadence §4.2 step 5); under a review stage, its last reader |
| Run the precheck on a PR's head | the author or the merger (cadence §4.12); main's own is the home's |
| Review evidence (`cadence-review:`; a fact-check for docs) | the author's independent reviewer (cadence §4.8) |
| Read a held path (`held:`) | the review stage's reader; a flow with no review stage gives no reader, and the author merges on the cadence's gate (§4.9c) |
| Answer a member's question | the team's question seat (tier 1), which may be the person |
| File entries and write the board | each session, through the helpers; the question seat lands filed asks |
| Notice stalls, permissions, idle-with-work | the manager (tier 1) and the tick of the host the team runs on |

Escalation to the person and promoting the live copy are fixed: no flow changes them.

## A flow names its models; the team lists its logins

Paul, 2026-11-18: *part of defining a good flow will also be defining which models do which parts — if
those models are not available on a machine, then that machine cannot run that flow (the user can copy
and modify it to fit). That way in theory people could share flows with each other, and in theory we
could benchmark different flow results.*

So each seat of a flow names the **model** it runs on (`opus`, `sonnet`, a Grok model), never an account,
a login or a profile name, which are one machine's (and a node's are its own, §4.4a). It does not name
the CLI either: Paul, 2026-11-18, *if I were to use an aggregate service like poe.com, then I could
conceivably use ops from there in addition to claude code*, so one model may be reached through more than
one tool, and the tool is the login's. The team binds **which logins** run the seats, as one ordered list
(below); a launch
records the seat's `model` and `login` (below), neither a flow field, so invariant 9 (*a flow is not on
the record*) holds: the tick never reads a flow.

**A machine that cannot run a seat's model cannot follow the flow**, read as followability is today
(§4.9c), naming the reason: *td-grok cannot be followed here: no Grok login*; *build on Fable has no
passing grinder smoke on claude-code 2.4*. The person copies the flow and changes the model. The seat
smoke and the judge (§4.3, §4.9b), today lines quoted in PRs, become records this check reads, kept per
CLI version, model and role. Paul, 2026-11-18: ShiftLead ships the **known passes** — a list in the package
of the CLI, model and role combinations its own smoke passed, on which CLI versions — so a person does not
re-run a smoke someone has already run; a person's own passes, recorded by the Tools page, add to it.

This reverses §4.9c's *a flow names roles only* and *roles and flows are orthogonal*: a role's
profile overlays (`roles:` in `org.yml` and `.shiftlead.yml`) no longer choose a model for any seat;
the rest of a role overlay (a brief, a context bound) stays.
Under a flow, a seat's model comes from the flow and its login from the team's list, and nothing
overrides them: a member's own `profile:` and the role overlays' profiles go (Paul, 2026-11-18: overrides
are complexity not needed).

**The team lists its subscriptions; the flow names only the model** (Paul, 2026-11-18: *the model name in
the flow, and the sub list in the teams page — my flow could say opus, then my teams page says
(claude-paul, claude-heather, claude-api) and if opus is not available, the flow is broken*). The team
page keeps **one ordered list of logins**, across tools (`poe-paul, claude-paul`), saved at once with the
team (`settings.yml`), since login names are one machine's, each login drawn with its tool, its account
and the models it offers (read on the Tools page, which names each in the families flows use). A seat
takes the first usable login that offers its model. **A team whose list holds no login that can run a
seat's model cannot follow the flow**, and the page says why. A login is usable for a seat only where its
tool, the model and the seat's role have a smoke pass (known or the person's own), so an aggregator's
login is offered for a seat once its tool passes there.

- **Every launch picks its login.** A seat's launch record (`launch/<id>.json`, which restarts and seat
  fills replay) holds the seat's model, not a login; every launch, a restart and a fill included, takes
  the first **usable** login in the team's list: signed in, not gated or `limited`, and not on an account
  an earlier, unusable login already shares (the reserve and the reading are the account's, §6, so a
  second login of one account is no backup). The record gains `model` and `login` as fields a start
  writes, which the definition's compare reads in place of the compiled `profile` (§4.9c's TD-619
  compare, `teamrun`), so a seat on a backup login reads no difference and no mark is needed. A reorder
  or a removed login is no difference either: it takes effect at each seat's next launch.
- **A seat that is stopped moves.** An unattended seat that is gated (its account at its reserve, §6,
  which pauses it before the tool's own limit) or `limited` (Paul, 2026-11-18: *hitting either the
  reserve or a hard limit should trigger the backup*) is relaunched on the next usable login, its
  conversation resumed: **Switch profile…** (§4.3 *The limit dialog*, §4.5a), designed for a person's
  press and not built, done by the tick of the host the team runs on (a node's own, §4.4a). One
  mechanism serves every seat (Paul, 2026-11-18: a question seat stopped mid-answer is where a build
  seat stopped mid-issue is, only less often); new questions to a stopped question seat are routed around
  it meanwhile (§4.9b), and a lane's other members keep picking. With no usable login left the seat waits,
  as it does today. An interactive session is never moved (invariant 5). A relaunch is a new process on
  the same record (§4.5a), so the seat keeps its name, and a review stage's reader stays one reader.
- **Resuming across logins and tools.** A tool resumes a conversation from its own config directory, and
  another login is another directory, or another tool. ShiftLead already keeps the transcripts, so where
  a tool cannot resume, the relaunch starts a fresh session seeded from the transcript (Paul,
  2026-11-18), and an open ask the seat held stays on its mail for it. The Tools round tests a native
  resume first, with a second Claude login, since every Claude profile here shares one.
- **A metered login** (`claude-api`) is marked as one, since a seat that moves to it spends money; it is
  used like any other in its place in the list, its reserve an amount rather than a share of a window
  (§6) — see open question 8.
- **Backups are logins, never models.** Falling back to another model is out of scope; if it is wanted it
  is the flow's to name, perhaps as a **failover flow** with its own model set (Paul, 2026-11-18: *if
  that ever becomes a need*). The ordered pool (§4.9b *A seat as an ordered pool*) is retired: a list of
  profiles, which leave the person's view, for a fallback to another model, and used by no definition on
  this install. Spreading two subscriptions over seats by hand would need a per-seat *start on* pick,
  left out until asked for. Formal load balancing is out of scope.
- **Sessions no team runs** — the director, the sweep, a scheduled start — take an ordered login list of
  their own on the page where they are set, and move as a seat does. A person's own session starts on the
  login and model picked in the New session form, and is never moved.
- **The compiled profile** (a model and a login) is written by the host that launches, from its own
  `profiles.yml` (a node's is its own, §4.4a), never by a session; the home learns a node's login names
  from the node to check a node team's list.

**A model is named by its family, not its version** (Paul, 2026-11-18): a seat says `opus`, `sonnet` or `flash-lite` (the
family is the CLI's own word; `gemini-3.5-flash-lite` is pinned on this install because the CLI's default
model exhausts the free tier at once, `profiles.yml`), and the CLI runs its default version of it, so ShiftLead never tracks which old versions a CLI still offers.
The version a session actually ran is read from its transcript (the spend reader already reads model ids
there) and kept with its run's benchmark row (*A flow has an id*), so metrics compare like with like
without the flow naming it. Opus 5 and
Opus 5.5 are one flow.

## A flow has an id

Paul, 2026-11-18: flows get an internal id, so a person may rename one freely. Each `flow.yml` carries an
**`id`** written when the flow is created (a built-in's fixed in the package); everything that names a
flow — a team's `flows:` list, the `flow` setting, the stage chip's lookup, a benchmark's record — names the id, and the name is a label. A copy takes a new id. There is no `from:`:
a copy may be changed past any resemblance, so lineage says little; what a benchmark needs is the
**content hash** of the flow a session ran under. Invariant 9 keeps the record free of any flow or stage
field (§9, §4.9c), so neither the hash nor the flow's id goes on the record: the client writes them, with
the model version the transcript names and the tool that ran it, to a store of its own beside the spend reader's, read by no
rule. Open for
the Flows round: how a flow is found once its directory name stops being its name (today *a flow is found by its directory*), and what the org-over-repo-over-package shadowing means when
two places hold one id.

## A flow may set its review rounds

Paul, 2026-11-18: the review rounds are *a lever that will want to be played with — particularly the
max rounds and counts for convergence and sticking points*. agent-cadence already reads every one of its
settings from the environment first (`CADENCE_<KEY>`, before the repo's `docs/cadence.toml`, the machine
file and the default; cadence §9.18), and ShiftLead launches every session, so a flow can set
`review-model`, `fact-check-model`, `design-rounds` and `design-rounds-wide` on a seat at launch. Only
agent-cadence's config reader and its review statistics read them, not the merge gate, so a seat run on
other rounds trips no one else's check.

Three limits. agent-cadence's review statistics judge a design's cap from the repo's file
(`review_stats.py`), so a flow's cap set by environment is read against the repo's; the Flows round
either has the flow's value written where the statistics read it or accepts the mismatch. A
fact-checker seat's model in the flow and `CADENCE_FACT_CHECK_MODEL` are two sources for one fact: the
flow writes both from one field. The stop rule for convergence and a sticking point is prose in cadence §4.8, not a setting:
making it a lever means new keys in agent-cadence, a change there and a pin bump here — partly a bump
only, since a newer agent-cadence than this repo's pin already has `design-hold-rounds`. And the person's
own cadence layer may say how rounds alternate (this install's says Sonnet, fix, Fable, fix), so a flow
that changes `review-model` must agree with it or say it overrides it.

## Which current rules this reverses or bends

- **§4.9c orthogonality** — reversed: a flow's seat names its model; the tool is the login's.
- **§4.2a profiles** — a profile is no longer named by the person anywhere: the model is the flow's (or
  picked beside a login for a session no flow runs), the login and its options the Tools page's. Every
  place that takes a profile by name today (§4.9's five rungs, seat pools, `schedule.profile`,
  `sweep.profile`, `director.profile`, `ao new --profile`, *Switch profile…*) changes, and today's
  `profiles.yml` files and team definitions migrate.
- **§4.9c "a seat never sits out"** — reversed for tier-2 seats.
- **§4.9b *A seat as an ordered pool*** — retired (see *the team lists its subscriptions*).
- **The record and the compare** — the record gains `model` and `login`, a launch record holds a model
  and no login, and §4.9c's TD-619 compare reads the model; §6's gate, which pauses a seat at its
  account's reserve, now hands it to the next usable login first.
- **§4.3 *Nobody answers the box for the session … waits for a person*** and **§4.5a** *Switch profile…*
  (a person's control, not built) — an unattended `limited` seat is relaunched by the tick; the build
  rewrites those passages and §4.5a's two *not built* notes.
- **§4.3 "the install is never run by ShiftLead or a session"** (Grok; Gemini's layer needs `sudo`) — the
  Tools page shows the documented install and opens a Shell tab where the person runs it; it does not
  run it. Keeps the rule.
- **Definition edits from a page** — a repo team's or repo flow's edit is a PR under the full cadence:
  an independent review and the precheck (cadence §4.8, §4.12), and its held-path reader where it
  touches one (here `docs/briefs/**`, which a flow's or member's brief may be). No self-merging road:
  it would need an agent-cadence carve-out, and an edit of `.shiftlead.yml` can rewrite `held:` itself,
  removing the gate it would pass.
- **§4.5a "a control not in its table does not exist"** — every control on the three pages gets a row
  and an `ao` verb (or a stated exception) in its round.

## Holes each round must close

- **Tools**: per host (a node's CLIs, logins and `profiles.yml` are its own, and its tick runs its relaunches);
  a login's schema first (account, config directory, options, per host); renaming an account moves its reserve
  and its usage and spend history (the key changes); metered and API-key logins (no quota, amount
  reserves); a login's options (`permission_prompts`, `config_dir`, `extra_args`, `billing`, and a
  metered login's `prices`); a writer for `profiles.yml`, which has none today, written only from the
  person's own pages and RPC, as `set_settings` is; the context bound, a
  role setting that a new model should re-ask; migrating today's profiles into logins, and every
  `profile:` in definitions and settings into a flow's model and a team's login list.
- **Flows**: org flows cannot run on a node (§4.9c), so a node team's flows are its repo's;
  a flow switch
  never changes an interactive member's model (invariant 5), which starts on what the person picked; a
  stage held only by an interactive member counts toward followability as today; followability shown with its reason.
- **Settings that name a profile today** — `teams.<t>.schedule.profile`, `sweep.profile`,
  `director.profile`, `ao team start --profile`, `ao new --profile` — each becomes a login and a model.
- **Team**: the per-CLI login list and how a limited login's seat moves to the next; which rows move from the Settings team card (and the flow chip's link); `size`/`max` and
  run-only members (TD-1149) and auto size (TD-1154); the change tray applies on Save, but a live team
  still moves only on Apply.

## Open questions, each with a recommendation

1. **Is the question seat a tier-1 seat on every team?** Recommended: yes, as the manager is; a team that
   wants none says `person`.
2. **Is the login list per CLI or per team?** Decided (Paul, 2026-11-18): one list per team, across
   tools, since an aggregator reaches models of several makers; a per-seat *start on* pick only if
   spreading by hand is wanted.
3. **How do today's teams move onto flows that name models?** Recommended: the built-in flows are
   written exactly as a person's are (Paul, 2026-11-18: dogfooding), each seat's model the package's
   choice from the smoke and judge results, not Opus throughout — the manager, whose work is stalls,
   permissions and questions, on Sonnet once a manager smoke exists and passes. Until the known-passes
   list exists the built-ins name what their roles run on today (`org.yml`: hunter, auditor and manager
   on Sonnet, the rest on Opus), so no team changes model by moving onto them;
   so a team on `td` keeps running wherever Claude Code is signed in; a team whose seats run another model
   today (a fact-checker on Gemini, a grinder trial on another model) is migrated by a one-time step that
   writes a flow of its own under a new name and id (a directory may not take a built-in's name, §4.9c),
   re-points the team's `flows:` list (a repo team's by PR) and its `flow` setting, and moves each
   tier-2 seat's role, trigger and model into it while the team keeps the seat's name and brief.
   An org team's new flow is an org flow, which a node cannot run (§4.9c), so a node team's goes in its
   repo. Role overlays' models and members' `profile:` values are dropped by the same step, each
   written into the flow or the login list first.
4. **Is "Install" a button?** Recommended: a button that opens a Shell tab with the command typed, the
   person pressing Enter.
5. **Which review-round keys does a flow get first?** Recommended: the four agent-cadence has today, by
   environment; convergence and sticking-point keys filed against agent-cadence as their own entry.
6. **Does a review stage, the techlead or the manager get a backup?** Answered by the relaunch: yes, the
   same seat on the next login, so a review chain keeps one reader. What stays refused is a second
   reader beside the first.
7. **Every team runs a flow** (Paul, 2026-11-18). A flow is opt-in today (§4.9c). A *none* flow that
   behaves as a flowless team does cannot be written as a flow: a flowless team reads each role's own
   `review:` and keeps its seats on the team (§4.9c), which no flow file expresses. Decided (Paul,
   2026-11-18): no *none* flow; a team picks a real flow, the plainest being the built-in `build` (build
   only, no review stage). Per-role review rules, the one thing a flowless team has that a flow drops, are
   a flow's to express if they are ever wanted. Every team on this install already runs one, so nothing migrates here. Tier-1 seats' models are
   named in the flow, and a flow switch reaches a running team only through Apply (Paul, 2026-11-18),
   which waits until the question seat holds no open ask.
8. **May a seat move onto a metered login on its own?** Decided (Paul, 2026-11-18): yes, in its place in
   the list, bounded by its amount reserve; a person who wants it only by hand leaves it out of the list.
9. **Does a flow ever pin the tool?** The same model through Claude Code and through an aggregator's tool
   is two harnesses, which may do the work differently, and a benchmark should know. Recommended: no pin
   for now; every run's tool is kept beside its model version and flow hash, so results can be split by
   it, and a pin is added if a flow is found to need one.
