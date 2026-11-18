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
| Which profile each of a flow's seats runs on | an **install-local casting** beside the flow (see *Models are cast*, below) | at once | Flows |
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
   up, §4.9b, and that another repo's ask finds by `--team`/`--repo`). Automatic; the flow only casts
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

## Models are cast per install, not written in a shared flow

A repo's flow is shared through git; a login is one machine's (and a node's are its own, §4.4a). So a
flow file never names a profile or an account. Instead each install keeps a **casting** per flow: which
profile each seat of that flow runs on, written on the Flows page and saved at once. It slots into the
existing precedence as one rung: above the role overlays, below a member's own `profile:` and `ao new
--profile`. It compiles into the `profile` a record already carries, so invariant 9 (*a flow is not on
the record*) holds: the tick never reads a flow.

Paul's "a different model is a copied flow" stays the road: two teams on one flow share its casting;
a team that wants Sonnet on build copies the flow (its briefs by `package:` reference) and casts the
copy. Two subscriptions spread by hand are two seats cast on two profiles; formal load balancing is
the deferred pool-with-`max` design (§4.9b), out of scope.

A cast is offered only where it is safe: a seat may be cast on a profile whose **seat smoke** passed
for that role (and a fact-checker's **judge** row), on the CLI version installed. Today those passes are
lines quoted in PRs (§4.3, §4.9b); the Tools page keeps them as records so the picker can check them.

## Review rounds stay the cadence's

`review-model`, `fact-check-model` and `design-rounds` are agent-cadence's settings in
`docs/cadence.toml` and the person's layer, read by agent-cadence's scripts, not by ShiftLead; authors
run those reviews as their own subagents. A flow does not own them. The flow's review stage (a
reader on held paths) is a different thing and stays the flow's. Revisit only if a flow needs
different rounds from its repo, which would be an agent-cadence change first.

## Which current rules this reverses or bends

- **§4.9c orthogonality** — a flow still names roles only; the model moves to the casting, not into
  `flow.yml`. Smaller reversal than "a flow names its models".
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
- **Flows**: the casting's file and its node story (org flows already cannot run on a node, §4.9c);
  pools on a cast seat (refused today on a review stage, the techlead and the manager); a flow switch
  never changes an interactive member's model (invariant 5); followability shown with its reason.
- **Team**: which rows move from the Settings team card (and the flow chip's link); `size`/`max` and
  run-only members (TD-1149) and auto size (TD-1154); the change tray applies on Save, but a live team
  still moves only on Apply.

## Open questions, each with a recommendation

1. **Is the question seat a tier-1 seat on every team?** Recommended: yes, as the manager is; a team that
   wants none says `person`.
2. **Where does a casting live?** Recommended: `~/.shiftlead/castings/<flow>.yml` on the home, copied to a
   node with the profiles it names, as profiles are today.
3. **Do on-call seats move from the team's `seats:` into `flow.yml`?** Recommended: yes for tier 2, with a
   migration that keeps each repo's current seats in a repo copy of its flow.
4. **Is "Install" a button?** Recommended: a button that opens a Shell tab with the command typed, the
   person pressing Enter.
5. **Does the team page show the casting?** Recommended: read-only, beside each seat, with a link to the
   flow's page; changing it there would make two places that cast.
