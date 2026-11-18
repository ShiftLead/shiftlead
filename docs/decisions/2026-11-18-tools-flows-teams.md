# ADR 2026-11-18: Tools, Flows and Team pages — the plan, for discussion

Status: **for discussion**. This is the high-level plan behind TD-1953 (the Tools page), TD-1954 (the
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
| CLIs found, versions, logins and their identity | each tool's own config directory, read | detection, read-only | Tools |
| Account names, reserves per subscription (`usage_gate:`) | `profiles.yml`, `settings.yml` (the install's) | a writer RPC, at once | Tools |
| Profiles (login + model + options) | `profiles.yml` | a writer RPC, at once | Tools |
| A flow's stages, seats, triggers, briefs | the flow's directory (package: read-only; org: at once, committed by the home; repo: by PR) | the Flows page | Flows |
| Each seat's CLI and model | the flow's directory, with its seats | as the flow is | Flows |
| Which login runs each seat, where a CLI has several | `settings.yml` (the install's; see *A flow names its models*, below) | at once | Flows, Team |
| Flow pick, seat count ranges (`size`, `max`), hours, reserve priority, balance, on_work | `settings.yml` | at once (as the Settings team card does today) | Team |
| A team's definition (which flows it lists, members' own briefs, the seats it adds) | `org.yml` (at once) or `.shiftlead.yml` (by PR) | rare; the page opens the PR | Team |

So most of the team page needs no PR at all; the earlier draft's "a repo team's edit lands as a PR" covers
only the rare definition change.

## Seats come in three tiers

Today the techlead, auditors, fact-checkers and the sweeper are the team's `seats:`, run under every flow,
and "a seat never sits out" (§4.9c). Paul wants the flow to say which seats exist and when each is used,
and some seats on every team. The plan splits them:

1. **Every team's seats** — the **manager** (on call, or `person`) and the **question seat** (the
   techlead's first job: the go-between that answers a member's steer or work question or passes it
   up, §4.9b, and that another repo's ask finds by `--team`/`--repo`). Automatic; the flow only names
   their model, or says the person holds it. A team never lacks one, so `{techlead}` in briefs, Add
   entry's default (`entries.feature`) and cross-repo asks keep working.
2. **The flow's seats** — its stages (design, build, review, hunt, ...) and its **on-call seats**: a
   review stage's reader on held paths (the techlead's second job), the auditors (`prs: 10`), the
   fact-checkers (`asks`), a sweeper (`swept:`). A flow may leave any of these out. This reverses
   "a seat never sits out" for these seats only.
3. **The org's seats** — the **director** and the repo's **tagging seat**, outside any team. They stay on
   the Settings page; the Tools page lists them among what runs on each profile.

## Every flow covers the minimum tasks

The process runs on git and PRs, so a flow is followable only if it says who does each of these, or
takes the default. The Flows page checks every flow against the list, as §4.9c checks followability
today.

| Task | Default when the flow names nobody |
|---|---|
| Merge a PR | the PR's author, on the cadence's gate (cadence §4.2 step 5); under a review stage, its last reader |
| Run the precheck on a PR's head | the author or the merger (cadence §4.12); main's own is the home's |
| Review evidence (`cadence-review:`; a fact-check for docs) | the author's independent reviewer (cadence §4.8) |
| Read a held path (`held:`) | the review stage's reader; with none, the person |
| Answer a member's question | the team's question seat (tier 1); with none, the person |
| File entries and write the board | each session, through the helpers; the question seat lands filed asks |
| Notice stalls, permissions, idle-with-work | the manager (tier 1) and the home's tick |

Escalation to the person and promoting the live copy are fixed: no flow changes them.

## A flow names its models; the install binds only the subscription

Paul, 2026-11-18: *part of defining a good flow will also be defining which models do which parts — if
those models are not available on a machine, then that machine cannot run that flow (the user can copy
and modify it to fit). That way in theory people could share flows with each other, and in theory we
could benchmark different flow results.*

So each seat of a flow names the **CLI and model** it runs on (`claude-code` · `opus`, `grok` · its
model), never an account or a profile name, which are one machine's (and a node's are its own,
§4.4a). The install binds only **which login** runs each such seat: the one login of that CLI where
there is one, a per-seat pick where there are several (two SuperGrok subscriptions spread by hand over
two seats). That binding is the install's, saved at once on the Flows page or the team page, and it
compiles into the `profile` a record already carries, so invariant 9 (*a flow is not on the record*)
holds: the tick never reads a flow.

**A machine that cannot run a seat's model cannot follow the flow**, read as followability is today
(§4.9c), naming the reason: *td-grok cannot be followed here: no Grok login*; *build on Fable has no
passing grinder smoke on claude-code 2.4*. The person copies the flow and changes the model. The seat
smoke and the judge (§4.3, §4.9b), today lines quoted in PRs, become records this check reads, kept per
CLI version, model and role. Paul, 2026-11-18: ShiftLead ships the **known passes** — a list in the package
of the CLI, model and role combinations its own smoke passed, on which CLI versions — so a person does not
re-run a smoke someone has already run; a person's own passes, recorded by the Tools page, add to it.

This reverses §4.9c's *a flow names roles only* and *roles and flows are orthogonal*: a role's
profile overlays (`roles:` in `org.yml` and `.shiftlead.yml`) no longer choose a model for a flow's
seat. They stay for sessions no flow runs (`ao new`, the director, the sweep, a person's own session).
The precedence gains the flow's seat as a rung, below a member's own `profile:` and `ao new --profile`.

**A backup for a critical seat** (Paul, 2026-11-18: *paul-grok is limited, but grok-heather is the
backup*) is one ordered list per seat on the flow: CLI and model entries, *Grok, then Claude Code · Opus*.
The install expands each entry into every signed-in login of that CLI, tried in order before the next
entry, so another login is a backup with nothing set; the page draws one line, *Grok · backup Claude Code ·
Opus*, with each login's state under it. The person may set only which login a seat starts on (to spread
two subscriptions by hand) and exclude a login from a seat. It reuses the seat pool (§4.9b *A seat as an
ordered pool*): later members are held and filled only when the one before cannot answer, each its own
record. Pools are refused today on a review stage, the techlead and the manager, since a backup is another
session and so another reader; the Flows round decides whether that holds, for a backup of either kind.
Formal load balancing across subscriptions is the deferred pool-with-`max` design, out of scope.

**A model is named by its family, not its version** (Paul, 2026-11-18): a seat says `opus` or `sonnet`, and
the CLI runs its default version of it, so ShiftLead never tracks which old versions a CLI still offers.
The version a session actually ran is read from its transcript (the spend reader already reads model ids
there) and kept on its record, so metrics compare like with like without the flow naming it. Opus 5 and
Opus 5.5 are one flow.

## A flow has an id, and a lineage

Paul, 2026-11-18: flows get an internal id, so a person may rename one freely. Each `flow.yml` carries an
**`id`** written when the flow is created (a built-in's fixed in the package); everything that names a
flow — a team's `flows:` list, the `flow` setting, the login bindings, the stage chip's lookup, a
benchmark's record — names the id, and the name is a label. A copy takes a new id. There is no `from:`:
a copy may be changed past any resemblance, so lineage says little; what a benchmark needs is the
**content hash** of the flow a session ran under, kept on its record beside the model version. Open for the Flows round: how a flow is found once its directory name stops being its name
(today *a flow is found by its directory*), and what the org-over-repo-over-package shadowing means when
two places hold one id.

## A flow may set its review rounds

Paul, 2026-11-18: the review rounds are *a lever that will want to be played with — particularly the
max rounds and counts for convergence and sticking points*. agent-cadence already reads every one of its
settings from the environment first (`CADENCE_<KEY>`, before the repo's `docs/cadence.toml`, the machine
file and the default; cadence §9.18), and ShiftLead launches every session, so a flow can set
`review-model`, `fact-check-model`, `design-rounds` and `design-rounds-wide` on a seat at launch. Only
agent-cadence's config reader and its review statistics read them, not the merge gate, so a seat run on
other rounds trips no one else's check.

Two limits. The stop rule for convergence and a sticking point is prose in cadence §4.8, not a setting:
making it a lever means new keys in agent-cadence, a change there and a pin bump here. And the person's
own cadence layer may say how rounds alternate (this install's says Sonnet, fix, Fable, fix), so a flow
that changes `review-model` must agree with it or say it overrides it.

## Which current rules this reverses or bends

- **§4.9c orthogonality** — reversed: a flow's seat names its CLI and model; role overlays keep only
  sessions no flow runs.
- **§4.9c "a seat never sits out"** — reversed for tier-2 seats.
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

- **Tools**: per host (a node's CLIs and logins are its own); renaming an account moves its reserve
  and its usage and spend history (the key changes); metered and API-key logins (no quota, amount
  reserves); a profile's options beyond CLI, account and model (`permission_prompts`, `config_dir`,
  `extra_args`, `billing`); a writer for `profiles.yml`, which has none today; the context bound, a
  role setting that a new model should re-ask.
- **Flows**: where the login bindings live and their node story (org flows already cannot run on a node, §4.9c);
  pools on a flow's seat (refused today on a review stage, the techlead and the manager); a flow switch
  never changes an interactive member's model (invariant 5); followability shown with its reason.
- **Team**: which rows move from the Settings team card (and the flow chip's link); `size`/`max` and
  run-only members (TD-1149) and auto size (TD-1154); the change tray applies on Save, but a live team
  still moves only on Apply.

## Open questions, each with a recommendation

1. **Is the question seat a tier-1 seat on every team?** Recommended: yes, as the manager is; a team that
   wants none says `person`.
2. **Where do login bindings live?** Recommended: `settings.yml` under the team (`teams.<team>.logins`),
   since which subscription runs a team's seat is the team's running choice; a node's are its own.
3. **Do on-call seats move from the team's `seats:` into `flow.yml`?** Recommended: yes for tier 2, with a
   migration that writes each repo's current seats into a repo copy of its flow.
4. **Is "Install" a button?** Recommended: a button that opens a Shell tab with the command typed, the
   person pressing Enter.
5. **Which review-round keys does a flow get first?** Recommended: the four agent-cadence has today, by
   environment; convergence and sticking-point keys filed against agent-cadence as their own entry.
6. **May a review stage, the techlead or the manager have a backup?** Recommended: not until the Flows
   round shows how a review chain hands a PR to a backup reader, a new session either way; until then
   such a seat waits out its limit, as it does today.
