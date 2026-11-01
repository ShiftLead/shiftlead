---
name: ao-team
description: How to stand up an shiftlead team — the project, the definition, the roles, and `ao team start` — for a person at a terminal and for an agent told to do it.
---

# Stand up a team

One recipe, for a person at a terminal and for an agent session told *stand up a grind team for
repo X*. It is the same text either way: `ao team --skill` prints this file, so a session serves
itself from the tool rather than from a memory of the design.

Every command below is one you can run. Nothing here explains why — design §4.9 (teams), §4.8
(roles), §4.4a (nodes) and §5 (a repo's own file) do that, and this points at them where it helps.

**What a team is.** A named definition of sessions to start together: a **manager** and its
**members**, each under a **role**, all of them on **one repo** (a repo has any number of teams; a
**project** is a heading over repos, design §4.9 *Projects*). `ao team start` reads the definition, checks
everything first, then creates the manager and each member with the manager as its controller. Nothing
about a team is stored on a session's record but two strings, `team` and `project`, and nothing
keys on them (§9 invariant 9) — the definition is the whole of it. **One exception, for mail
alone:** the mail gate keys on both badges — its *sideways* edge on `team`, so on a team with no
manager session (the `manager: {role: person}` case below) the badge is the only edge between
members there is, and its *across teams* edge on `project`, so two teams on one project may settle
things by mail (§4.10). Everywhere else the badges are labels.

---

## 0. Before anything: is there a host agent?

```
ao status
```

`no sessions` (or a list) means the agent is up. **Exit 3 means the command could not reach one**,
and the line says which of two things happened: *the host agent restarted under this command — run
it again* (it is up; run it again and nothing else), or *host agent not reachable*, which is the
one a person answers with `shiftlead-agent serve`, or `ao service install` for the units. A session
that gets exit 3 stops there and says so: **it never starts one** (`ao --skill`).

## 0b. Is the repo ready?

```
ao doctor repos
```

One line per registered repo: whether it is served — agent-cadence's tree, its gate and its ledger,
each lack named with its cure — and the warnings (a missing board, no worktree setup, agent-cadence's
per-clone setup not run). An unserved repo gets no team (`ao team start` refuses it); its ledger and
gate come from agent-cadence's adoption, which is the person's to run, not yours (design §5 *The seams*).
A repo the doctor does not list is not registered on this host; that is the person's to fix, not yours.

**What the repo needs before a team can pick anything.** A worker picks by an entry's header lines,
never its prose (design §6 rule 6), so the ledger's entries carry them first:

- **`**Blocked by:**`** — *pickable* is derived from it and never written: an entry with none, or
  whose every blocker is archived, is pickable. `decision (paul)` there keeps the entry from every
  lane until the person decides.
- **`**Kind:**`** — `build`, or none, is a `free-pick` lane's (and a `live-check` once its build is
  live); `design-first` is a designer's.
- **`**Owner:**`** — the word a lane's `owner:` matches (*What a lane takes*, step 3). `paul` is the
  person's owner word (`PERSON_OWNER` in `sessionorc/ledger.py`, as agent-cadence's seeded ledger's
  `Fields:` line declares it), and keeps an entry from every lane that carries an `owner:` word. **To keep an
  entry from every worker, whatever its lanes**, block it: `**Blocked by:** decision (paul)`.
- **The rules a PR lands by**, written down — agent-cadence's review and merge rules (its §4) where the repo
  uses them (branch → PR → independent review → the gate → merge), else in the briefs (step 4). A team
  merges its own PRs by what is written, never by a person's habit.

## 1. Decide where the team runs

A team runs on the machine you start it from, unless its definition carries `host:` — then every
session lands on that **node** (§4.4a). Skip to step 2 if it runs here.

For a container node, in `~/.shiftlead/hosts.yml`:

```yaml
nodes:
  contractmatch: {container: {devcontainer: ~/contractmatch}}
```

then bring it up and check it:

```
ao host up contractmatch
ao host status contractmatch
```

`ao host` takes `up`, `rebuild`, `forget` and `status`, and the name must be a `nodes:` entry with
a `container:` block. A node whose link is down is not a team you can start — `ao team start`
refuses before it creates anything.

**The one-time human steps are not `ao`'s**, and both come before the first start:

- **The node's `env` file**, `~/.shiftlead/nodes/<name>/env`, mode `0600`, one `KEY=value` a line
  and **unquoted** (`docker --env-file` keeps quotes as part of the value): `GH_TOKEN`, a
  fine-grained GitHub token (`gh auth setup-git` at provisioning makes `git push` use it);
  `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL`; and whatever the repo's own briefs say a worker needs
  (contractmatch's is a Doppler service token). Never the person's own token.
- **The token is the fence.** It names the repos the team pushes to and nothing else: a repo the
  node can see but the team must not change (a sibling clone, a symlink's target) is left out of
  it, so a push there fails whatever a brief says.
- **One `claude` login per profile** the team's roles name, inside the node:
  `docker exec -u <the image's user> -it <container> env CLAUDE_CONFIG_DIR=/shiftlead/profiles/<profile> claude`,
  the container's id from `ao host status <name>`.

**What a node does to the repo's devcontainer** (design §4.4a): the image, its `features`,
`remoteUser` and the lifecycle commands are kept; `mounts`, `customizations` and `containerEnv` are
dropped, each dropped mount an empty tmpfs at its target; and the checkout is mounted at **its host
path**, never `/workspaces/<x>`. A lifecycle script written for `/workspaces/<x>` does nothing
there, or fails `ao host up`, which names the cause: point it at the checkout's path, and pin the image user's uid to the
person's (`useradd --uid 1000`), before `ao host up`.

## 2. Say where the repo is

A repo is its checkout's directory name, and a checkout registered on this host (a line in
`repos.txt` under the home, design §5 *Repos*) is all a team on this host needs. A **project** is optional: a heading over
repos in `~/.shiftlead/org.yml`, with an optional `title`, which also says where a repo is checked
out on a host the registry does not cover:

```yaml
projects:
  contractmatch:
    title: ContractMatch
    repos:
      contractmatch: {kmaster: ~/contractmatch, contractmatch: /home/kmaster/contractmatch}
      samscrape:     {kmaster: ~/samscrape}
```

The key under a repo is a **host name**, and the value that host's checkout. This machine's
name is `local: {name: …}` in `~/.shiftlead/hosts.yml`, else its short hostname (`hostname -s`). **A repo
sits in at most one project**; a repo in none is a heading of its own. A team's sessions are started
in its repo's checkout, so a repo with no checkout on the host the team runs on is what `ao team
start` refuses on.

## 3. Say what the team is

**A repo's own team goes in its `.shiftlead.yml`** (*Which file*, below), the same keys with no
`repo:` and no `host:`:

```yaml
teams:
  cm-grind:
    manager: {role: manager, name: manager-cm}
    members:
      - {role: grinder, count: 2, name: grinder-cm, lane: [free-pick, owner:grinder]}
```

and `org.yml` places it on a node with `place: {cm-grind: contractmatch}`. The `org.yml` form,
beside `projects:`, takes `repo:` and `host:` as well:

```yaml
teams:
  cm-grind:
    repo: contractmatch          # the one repo the team works: required in org.yml
    host: contractmatch          # omit to run on the machine you start it from
    manager: {role: manager, name: manager-cm}
    members:
      - {role: grinder, count: 2, name: grinder-cm, lane: free-pick}
```

- **`manager:`** — always a mapping. `role` (default `manager`), `name` (default `<team>-lead`), and
  optionally `profile`, `lane`, `brief`, `grants`, `unattended`, `on_call`. **A `manager`-role
  manager is on call by default** (design §6 *A manager on call*): no manager session stands while
  the team runs; the home starts one when a member needs a reading no policy makes (a question to
  it, a permission, a `stalled?` member, one idle with open work) and it is closed once it has acted. `ao team list` marks it
  *manager: <name> (on call)*. `on_call: false` keeps a standing manager instead. **`manager: {role: person}`**
  means *the person manages*: no manager session is started. (`manager: person`, the bare string, is
  refused — *teams.<name>.manager must be a mapping, not str*.) `lead:`, its name until
  2026-09-20 (TD-076), is refused as an unknown key.
- **`techlead:`** — optional, one per team: the go-between that answers teammates' questions
  before they reach you (design §4.9b). `name` (default `<team>-techlead`), and optionally
  `profile`, `brief`, `context`; no `role` and no `grants`. It is started after the manager, under
  it, and every brief in the team names it as `{techlead}`. Without one, questions come to you as
  now. **`context:`** is the seat's **primer** — a path in the team's checkout that its brief reads
  first (`{context}`); `ao team start` says so, and starts anyway, when it is missing. See
  *A techlead's primer* below before the first start with a seat.
- **`members:`** — each is a role and a `count`; `name` is the **prefix**, and above one member the
  sessions are `<name>-1`, `<name>-2`, … Each also takes, as the manager does, `profile`,
  `lane`, `brief`, `grants` and `unattended` — so a member's `profile:` goes on its line, not in a
  `roles:` overlay; any other key is refused.
  **`{team: other-team}` is refused when the file is read**, naming the key: no team holds another
  (design §4.9 *Teams*) — teams that work together are teams on one repo, or on repos under one
  heading, and settle things by mail. Write each team on its own and start each on its own.
- Both take `lane:` and `unattended:` (default true). **`lane:` is one word or a list.**
  `free-pick` means *choose from the ledger by priority*; anything else is a named lane, the
  references that member works — `lane: [TD-041, TD-054]`, or `lane: TD-041,TD-054` — which its
  brief reads as `TD-041, TD-054` (`{lane}`) and works **in that order, stopping at its end**
  rather than free-picking past it. A member with a named lane is out of work when every item
  on it is `done` or `dropped`.
- **A repo with little or no work** (`ao doctor repos` reads its ledger's count): a start whose every
  member's lane holds nothing to pick is refused (step 5), so a `free-pick` team on an empty ledger
  does not start. Run an on-call manager alone (leave `members:` out) or one member, and start it with
  `ao team start <name> --anyway` where a lane it starts is empty.

A team can live in **its repo's** `.shiftlead.yml` under `teams:` instead, and travels with the
checkout. The org file wins a name collision. **Which file:** the repo's, when the team works that
repo from its checkout on the machine you start it from — its `repo:` is unsaid there (the repo
itself; one naming another repo is refused), and its project is the `org.yml` heading that lists
the repo, else none; `org.yml`, when the team nests another, because only `org.yml` says how teams
relate. **`projects:` on a team and `home:` on its sessions**, written before TD-722, are read for
one release with a warning that names the fix (`write repo: <repo>`) where they name one repo, and
the team is refused by name where they name two (design §4.9 *A definition written before TD-722*). A repo's team that should run on a node stays in the repo: `org.yml` places
it with `place: {<team>: <host>}`, and its checkout there is that host's registry entry of the
repo's name (a repo's file never names a host). **A public repo's team goes in `org.yml`**, whatever its
shape and wherever it runs: the repo's file is published with the repo, and with it the definition's
profile and session names.

`.shiftlead.yml` takes these keys and refuses any other: `ledger`, `roles`, `controllers`,
`teams` and `promote` (read by the home's promote, design §6), `gate` (the merge gate's command,
`{pr}` filled; unset, agent-cadence's `check_cadence.py` where the checkout holds it, design §5 *The seams*),
`worktree_setup` (a command run in each new worktree; unset, agent-cadence's `hydrate_worktree.sh` where
the checkout holds it, or the pinned tree's in a pinned repo, design §5 *The seams*), `board` (the person's board, from the repo's root; unset,
agent-cadence's `user_attention.md` where the checkout holds it, design §5 *The seams*), `settle` (how long a new
ledger entry of each Kind waits before a lane may take it, `{design-first: 10m}`, design §4.4), `held` (the paths a flow's review stage waits for, design §4.9c),
`commands` (a mapping, `test: …` and `lint: …` filling the briefs' `{test}` and `{lint}`, design §5 *The seams*), and
`unattended` and `ready_when`, which nothing reads yet — **never `projects`**, which is the org's (design §5).

**Ignore `.claude/worktrees/`** in the repo's `.gitignore` before the first start: every team
session works in `<repo>/.claude/worktrees/<name>`, and a repo that does not ignore it leaves
nested checkouts that a `git add -A` in the main checkout stages as gitlinks.

**Commit and push both before the start.** The definition is read from the checkout as it is on
disk, but each session's worktree is cut from `origin/HEAD` after a fetch, so a `.shiftlead.yml`,
a `.gitignore` line or a brief that is only in the main checkout's working tree is missing from
every member's worktree.

**Check a definition on its branch.** `ao team list` and `ao org check` read each registered
checkout as it stands, so a `.shiftlead.yml` written on a branch — where a repo's review rules want
it — is invisible to both until it merges. Run `ao org check --root <worktree>` in the worktree
before the PR: it reads the repo file, and the briefs, primer and role directories it names, at
`<worktree>` in place of the registered checkout, and every other repo as it stands. Fix what it
names on the branch.

### What a lane takes

One function reads the lane words against each entry's header lines (`lane_matches` in
`sessionorc/ledger.py`, design §6 rule 6). What it does, and what it leaves to a brief:

- **`free-pick`** takes a pickable entry whose `Kind:` is `build` or unwritten; **`design-first`**
  a pickable `Kind: design-first` entry (a decision owed to the designer is that `Kind:`).
- **`owner:<word>` narrows the other words** and matches nothing alone: under
  `[free-pick, owner:grinder]` an entry's `Owner:` must be `grinder` **or absent** — an entry with
  no `Owner:` passes. To keep one out, give it an Owner the lane does not name: `paul` (step 0b),
  or any word of the repo's own. **A bare `free-pick` reads no Owner at all**, `paul`'s included:
  only a `Blocked by:` keeps an entry from it.
- **A named lane** (`lane: [TD-041, TD-054]`) matches nothing in code: the member's brief reads it
  as `{lane}` and works it in order, and nothing else holds the member to it.
- **Work orders are in every `free-pick` lane, whatever its `owner:` words**: every open
  **decided** line on the board that is not `fyi` (`board:<key>`) and every red or sync PR nobody
  holds (`pr:<n>`). `fyi` is the board's one mark that keeps a line from a team, and it is not a
  decision; nothing marks a decided line *not for a team*, so where a repo has work a team must never
  touch (a private repo, a person's own area), **the briefs are the only fence** for those lines:
  say so under *The lane* in the worker's brief.
- **An entry can sit in a lane and still not be taken**: one **settling** (new, inside its Kind's
  `settle:` window — by default only `design-first`, 5m; a Kind no layer lists settles not at all;
  design §4.4 *A new entry settles before it is pickable*), one **waiting** (a `**Waits:**` line naming a date or an event, §4.4 *An entry says
  what it waits for*), and one that **needs a team** (`needs_team`: its `Team:` names no team the
  ledger's `Fields:` line declares, or it names none where that line declares two or more, §4.4
  *An entry names its team*) match no lane. `ao repo` says each, so a first start whose lane reads
  empty is read there first.
- **The team's sums leave the person's entries out; a lane does not.** The team card's lane
  lists, the Repo page and `ao repo` count an `Owner: paul` entry, or one blocked by
  `decision (paul)`, as the person's and in none of the team's kinds — but a bare `free-pick`
  member's own pick, and its own count on the card, still take an `Owner: paul` build that is
  pickable. What the pages show is not the fence: block the entry (step 0b).

### A repo over sibling repos

A team is on **one repo**, and every reading of a PR is that repo's: `ao progress done --pr <n>` is
read with `gh` in the team's checkout, `held:` globs match that repo's paths, and the red-PR and
sync-PR work orders and the PR and Doing facets read that repo alone. An umbrella whose work lands
in sibling repos with their own remotes (agent-cadence's `docs/nested-repos.txt`) gives each member
its own worktree or link of each sibling, as `hydrate_worktree.sh` sets them up — and **none of
the siblings' PRs is seen**: a sibling's PR number given to `--pr` is read as the umbrella's PR of
that number. Until ShiftLead reads them (TD-943), such a team lands a sibling change as **paired
PRs**, written into its briefs: the sibling PR carries the change and its review, then an umbrella
PR moves the ledger entry and links the sibling PR by its URL, and the umbrella PR is the one
`--pr` names and the flow reads. The siblings have no gate there but the review the brief asks for.

## 4. Say what the roles are

A role is a preset: a brief, a lane, grants, a profile, an icon. Seven are built in —

| role | brief | grants |
|---|---|---|
| `manager` | the package's `manager.md` | `control` |
| `grinder` | the package's `grinder.md` | none |
| `hunter` | the package's `hunter.md` | none |
| `techlead` | the package's `techlead.md` | none |
| `auditor` | the package's `auditor.md` | none |
| `designer` | the package's `designer.md` | none |
| `plain` | none | none |

(`lead` and `orchestrator`, the manager's old names, are unknown roles.)

— and a repo overrides any key in its `.shiftlead.yml`:

```yaml
roles:
  grinder: {brief: docs/briefs/grinder.md, lane: free-pick, profile: grind, icon: wrench}
  manager: {brief: docs/briefs/manager.md, grants: [control]}
controllers: [manager-cm]
ledger: notes/ledger.md          # unset: agent-cadence's ledger path
commands: {test: make test, lint: make lint}
```

Resolution is lowest first: the package's built-ins, then an org-wide `roles:` overlay in
`org.yml`, then the repo's own — each overriding **per key**, so a repo that sets only `brief`
keeps the built-in's grants. A `brief:` path is relative to the repo root. **A repo's brief is a
supplement, never a replacement** (design §4.8): the package's template is always the brief, and
the repo's file is filled into its *This repo's rules* section — see *A repo's brief*, below. At
the start a brief's placeholders are filled: `{lane}` with the member's lane,
`{techlead}` and `{manager}` with the ids those sessions take, `{context}` with the seat's primer —
each `none` where there is nothing to name (an empty lane reads `(none given)`).

**A `profile:` must already exist**, in `~/.shiftlead/profiles.yml` — it is an account of a tool,
not a word you may invent, and `ao team start` refuses a name that is not declared:

```yaml
default: paul
profiles:
  paul:  {adapter: claude-code, account: paul,  model: opus,   config_dir: ~/.claude}
  grind: {adapter: claude-code, account: grind, model: sonnet, config_dir: ~/.claude-grind}
```

With no file at all there is one implicit profile, `default`, on the tool's own config directory —
so a team that names none works, and a team that names `grind` needs the block above **and** a
`claude` login inside that `config_dir`, which is a person's one-time step and nobody else's.
**`ao team start` does not check that login**: a profile with none starts every session on the
tool's first-run screen, each `needs-you`. Check it before the first start — `claude` run with
`CLAUDE_CONFIG_DIR` set to that `config_dir` opens signed in, or on the login screen.

Check what resolves, from inside the repo:

```
ao roles
```

### A repo's brief

The built-in templates hold every shiftlead mechanic — the lane loop, claims and leases, the
cadence review and merge, asking and outcomes, the declarations a run ends with, the usage gate's
pause, the never-list of `ao` verbs — and move with the package on every promote. They name no
repo's layout: where a brief needs one it holds a slot — `{gate}`, `{board}`, `{ledger}`,
`{ledger_check}`, `{test}`, `{lint}`, `{design_dir}`, `{cadence_rules}` — filled at the start: the cadence's
(`{gate}`, `{board}`, `{ledger}`, `{ledger_check}`, `{cadence_rules}`) with agent-cadence's paths and the
repo's `.shiftlead.yml` `board` and `ledger`, the repo's own (`{test}`, `{lint}`, `{design_dir}`) from its
`commands` or its checkout, else the seam's own sentence (*no test command: run what the repo's README
says*), never empty (design §5 *The seams*). **A repo whose standing rules, scratch tools or reviewers differ says so in its own
brief**, and only that. Wherever it is given — a member's or manager's
`brief:` in the team definition (which takes the slot in place of the role's), a repo's
`roles.<name>.brief`, or `ao new --role <r> --brief <path>` — it is filled under *This repo's
rules*, and **where it and the template disagree, the repo's wins**, except that it may add to the
never-list and never take from it. What the host agent enforces (the usage gate, the restart
ceiling, the permission gate) no brief moves. A role the package ships no template for takes its
brief whole.

A skeleton — one short section each, and nothing the template already says:

- **First reads** — the files to read before anything, beyond `CLAUDE.md` and the cadence rules.
- **Where it works** — the branch naming, the default branch, anything about worktrees the repo
  does differently.
- **The gate** — what a PR needs beyond `commands:` and agent-cadence's gate: who reviews and who merges which
  PRs (e.g. *anything under `src/core/` waits for the techlead*).
- **Standing rules** — what is never done here: deploys, destructive data operations, files with
  their own line endings, what waits on the person, whole areas the team leaves alone.
- **The lane** — what a `free-pick` excludes in this repo, or the context a named list needs.
- **Asking** — only if it differs from the template's (a techlead, else the person).

`ao team start` and `ao new` say, and start anyway, when a repo's brief repeats one of the
template's headings — the sign of a whole brief not yet cut down to the repo's own rules — and
`ao team start` says the same of a clock time or a run number in it: a brief describes the job,
not the run (design §4.8), because the start is also the restart.

### A techlead's primer

A techlead starts cold, for one batch of questions, and sees only the asker's framing; a design
of any size cannot be read per fill. So the seat reads a primer first — this repo's is
`docs/briefs/techlead-context.md`, a model for another's (design §4.9b *Its standing context*).

- **It is an index, never a source.** An answer cites the document the primer pointed to, read
  there; the primer itself is never cited, so a stale one can misdirect a search and cannot
  become an authority.
- **What goes in:** what the project is, in a page; its parts and which depends on which; who may
  do what; how a change lands (review, merge rights, what is never touched); the questions already
  decided, each with **where it is written**; and what always goes up. Two to three thousand
  words — it is read on every fill.
- **What stays out:** anything that would be quoted as the answer itself; anything that changes
  weekly (the ledger's contents, who is working on what); secrets.
- **When:** before the first `ao team start` with a techlead seat; and again in the PR that
  changes the architecture, a standing decision or the merge rules — that PR updates the primer,
  and its fact-check reads the primer against the change.
- **Who:** a session of **that** repo with its design in front of it, or the person — never a
  session reaching across from another repo, which knows neither its decisions nor its never-list.
- **Held to its pointers by a test** where the repo can — shiftlead's is `tests/test_primer.py`,
  four checks, each a few lines in any language: every design section the primer names is a
  heading in the design; every invariant it names is in the design's invariant list; every path
  it names exists in the repo; every ledger id it names is an entry in the ledger or its archive.

## 5. Start it, and read it

```
ao team list                 # every definition, its source file, and whether it is live
ao team start cm-grind       # every check first, then the manager, then each member
ao team status cm-grind      # each member with its state, lane and report line
```

`ao team start` is **all or nothing**: every check runs before any session is created, so a bad
definition costs you nothing. A name a **live** session already holds refuses the whole start; a
name an exited or closed session holds is **superseded**, which is what makes `start` the restart
too. `-p/--profile` overrides the profile for every session in the team. A start whose every
member's lane holds nothing to pick is refused, saying so; `--anyway` starts it all the same.

Then, per session:

```
ao status -v                 # grants, team, project, under (its controllers), members, stop time,
                             # the tool's title, the model, its report line, findings, out of work,
                             # its `doing` line and unread mail — whichever of those it has
```

For what a **role** resolved to, read `ao roles` in the repo; `ao status -v` shows what a session
*is*, not the preset it came from.

## 6. Stop it

```
ao team stop cm-grind                 # wrap up the members, then the manager — each finishes and exits
ao team stop cm-grind --now           # kill instead of asking
ao team stop cm-grind --close         # also close each member that settled clean and pushed
```

`--close` is what lets `ao team start` run again under the same names without superseding anything.
`--timeout` bounds the wait for the members (default 300 s).

**One member back** (design §4.9a *One member back, today*). Mail to an exited member waits in its
inbox and starts nothing: only a seat is filled by a question. To bring one member back into a
running team: **Restart** — on its Inbox restart row, in its card's *more ▾*, or `ao restart <id>` —
which puts it back in the team's run as its launch record started it, unattended and on a fresh
prompt, with its mail kept (a person's alone: a session is refused); for a record with no launch
record, **Resume with changes…** on its card with *Unattended* ticked — **Resume** alone
starts it attended — which supersedes the record in place and keeps its mail; or the team's
**Start**, which brings the whole definition; or **Members…** on the team card → **Add member** of
the same role, which edits `org.yml` and creates it fresh under the manager.

---

## For an agent session told to do this

You are reading this because someone ran `ao team --skill`. The rules of `ao --skill` still apply —
they are about behaving inside a session; these are about setting one up.

1. **Read before you write.** `ao team list` and `ao roles` say what already exists. A team that is
   already defined is edited, not re-added under a second name.
2. **Write the definition, then check it, then start it.** `ao org check --root <worktree>` before
   the PR, `ao team list` after the merge (*Check a definition on its branch*, step 3): each fails
   loudly on a malformed file and names the key; fix it there rather than at `start`.
3. **Never invent a host, a repo path or a profile.** A repo with no checkout on the host the team runs
   on — in its registry or under its `projects:` heading — is a refusal, not a guess — ask the person for the path.
4. **Check the profile before you name it.** A `profile:` in a role or a member must be a key in
   `~/.shiftlead/profiles.yml`; `ao team start` refuses one that is not, and the file is the only
   place that says which exist.
5. **The one-time human steps are not yours**: a profile's `claude` login, a node's `env` file,
   anything that needs a credential. Say which are outstanding and stop.
6. **Report what you did with the tool's own words**: paste `ao team status <name>`. Do not
   summarise a state you did not read.
7. **`ao --json` on every call** when you are parsing, never prose (`ao --skill`).

## Where this leaves the older documents

`docs/briefs/README.md` covers the one case this does not: a **single** worker launched by hand
with `ao new`, and the membership pitfall that comes with it. Design §4.9 is the spec this recipe
is a path through; read it when a key here is not enough.
