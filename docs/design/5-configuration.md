## 5. Configuration

- Hosts: `~/.shiftlead/hosts.yml` on every host — the UI host's copy lists the hosts; each host
  agent's copy carries its own `local` entry and, on a node, `home:` (§4.4a). The `local` entry's
  fields: `name`, `vscode_host`, `local: true|false` (`vscode://file` links, for a UI on the machine
  you sit at), `volatile: true|false`, `repos_registry` path (unset: the home's own roster, `repos.txt` under the home, into which dev-cadence's `~/.config/dev-cadence/repos.txt` is imported when it exists — *Repos*, below; TD-584), `runs_keep_days`, `identity` (§4.8a)
  and `person` (§4.4a); the top-level keys are `home:`, `nodes:` and `link:` (§4.4a). There are
  no per-host `transport:` or `ssh` target entries: the hub-and-spoke ssh transport they were for
  was replaced by the home and node split (§4.4a, §7 phase 2), where a node dials the home with its
  `link:` and the home lists it under `nodes:` with its flags (`volatile` among them, which sorts
  that host's *unreachable* card with *idle*, §4.5). The UI process may run on a
  laptop; only the session hosts need to stay awake. The parser is `sessionorc.hosts`, shared by the UI and the host agent (there are
  no env-var overrides). A field the *agent* acts on (`runs_keep_days`) is read on the session host
  from its own file's `local` entry, so every session host carries its own copy. `local.name`, `home:` and `local.identity`
  are read by the host agent **once, at its start**, and by the UI on every request, so a hand edit
  of one leaves the two disagreeing until the agent restarts: the Org page then says so in one line
  under the node banner — *hosts.yml changed: name kmaster → box — restart pending* — naming each
  value that moved, the agent's (from its `host` and `identity` answers) against the file's.
  A node's `link:`
  key is the node→home link of §4.4a (built for a container node; a machine node is not yet in use, TD-057). **`home:`** names the host whose agent holds the org's graph
  and mail; an agent whose file names no `home:`, or names itself, is the home. On Paul's machines
  it is `home: kmaster`.
- **The settings a person moves** (the ADR [settings
  audit](../decisions/2026-09-25-settings-audit.md)): **`settings.yml`**, beside `hosts.yml` in the shiftlead home **of the home** — home-
  owned, one file for the org — read by the home's agent on every tick (`sessionorc.settings`),
  written **only by its `set_settings` RPC**, a person's own, refused to a session as `inbox_pause`
  is; `ao gate`, `ao schedule`, `ao team until` (§4.7) and the Settings page (§4.5 screen 8) all
  write through it. Nobody edits it by hand while the agent runs, though a hand edit is read on the
  next tick; it carries no comments, and a write rewrites it whole. **The line it draws**: a
  *definition* — what a team, a repo, a host or a profile *is* — stays in its own file above and
  below this bullet; a *setting* is a value the person turns without redefining anything, and every
  such value lives here, under six keys:

```yaml
usage_gate:                                   # §6 *Usage gate* — per profile, per window label as the adapter names it
  grind: {"5h": 30, week: {per_day: 10}}      # line 70% on the session window; 100 − 10 × days left on the weekly
  grind-api: {day: "$5", week: "$20"}        # a metered profile's reserve is an amount (§4.2a): the window's 100; "2M tok" without prices
settle: {design-first: 5m}                    # §4.4 *A new entry settles before it is pickable* (TD-707): per Kind, how long a new ledger entry waits, holdable, before a lane may take it; a Kind not listed 0; a repo's .shiftlead.yml settle: wins key by key; set_settings and the Settings page's field
spend:                                        # §4.4 *Spend per seat* (TD-818): what a turn with no cost of its own is weighed at; read by the seat pass, set by set_settings and the Settings page
  weights: {as_of: "2026-10-17",              # the date the defaults were taken from the API's list prices; shown beside them
            claude-fable: {input: 10, output: 50, cache_read: 0.25, cache_write: 20},
            claude-opus: {input: 4, output: 20, cache_read: 0.2, cache_write: 8},
            claude-sonnet: {input: 2, output: 10, cache_read: 0.2, cache_write: 4},
            claude-haiku: {input: 0.1, output: 0.5, cache_read: 0.01, cache_write: 0.2},
            claude-opus-5: {input: 5, output: 25, cache_read: 0.5, cache_write: 10},      # the longer keys: older generations still served, so a /model to one weighs true; claude-opus-5-5 is the current one, as the family row
            claude-opus-5-5: {input: 4, output: 20, cache_read: 0.2, cache_write: 8},
            claude-opus-4: {input: 5, output: 25, cache_read: 0.5, cache_write: 10},
            claude-sonnet-4: {input: 3, output: 15, cache_read: 0.3, cache_write: 6},
            claude-haiku-4: {input: 1, output: 5, cache_read: 0.1, cache_write: 2}}   # $ per million tokens per kind, by model prefix (longest wins); a model none matches is drawn unweighed
usage: {max_age: 1h}                          # §6 *A reading the gate can no longer trust* (read by the gate, set by set_settings, ao gate --max-age and the Settings page's field): past it the gate projects; `off` never. A key of its own: every key under usage_gate is a profile's name
teams:                                        # per team, by the name org.yml or a repo's teams: defines
  ao-grind:
    schedule: {start: reset, profile: grind, window: week}   # §6 *Schedule* (TD-133)
    until: "2026-09-26T06:00:00-06:00"        # §6 *Team stop time*: every member and seat stops here
    reserve: 10                               # §6 *Usage gate*: added to grind's reserve for this team's sessions
    on_work: start                            # §6 rule 8: start | ask | off, when a wound-down team's lanes, or a finished member's lane, gain work; start when absent
    flow: build-review                        # §4.9c: which of the team's flows it runs now; absent, the first
    balance: {prs: 10, oldest: 2d, review: true}   # §6 *Balance*: over any of these the team's members take no new claim; absent, no rule
permissions:                                  # TD-636, §4.9b *The director seat*: per role, the adapter's rule syntax; a deny wins
  grinder: {allow: ["Bash(pdm run test:*)", "Bash(gh pr view:*)"], deny: ["Bash(rm -rf:*)"]}
director: {level: conservative, groom: 7d}    # TD-657, §4.9b *The director answers what is passed up to it*: conservative | extrapolate | liberal; groom every <duration> | off
repos:                                        # per registered checkout, by its directory name
  shiftlead: {promote: {auto: false}, pull: true, sync: {auto: true}, director: {level: extrapolate}}   # §6 *Promote*: the one switch a person flips (run and check stay in .shiftlead.yml); §6 *Pull*: the checkout follows origin, on when absent; §6 *Sync*: a mechanical sync PR merged at the home, on when absent
person:                                       # the person's own — nothing here reaches a policy
  open_in: vscode                             # the editor button, below
  file_link: {folder_first: true, wait: 1}    # what a file link sends (§4.6): the folder first, and how long before the file, 0–4 s; below
  terminal: {size: 13, face: "JetBrains Mono",   # goal 12: ligatures off regardless, monospace always the fallback
             copy_on_select: true}             # a selection in the Focus pane copies itself (§4.5a; default on)
  inbox: {board_show: "next:10"}              # which board items the Inbox lists before they are due: next:<n> per repo | due | <n>d | all (drawn by the Inbox and the Repo page, picked on the Settings page's You)
  composer: folded                            # §4.5a *Focus composer* **the bar**: folded (the default) | open — whether Focus draws the composer as one bar under the terminal or open under it (TD-491)
  attach: {max: "256M"}                       # §4.4 *Attachment drop*: the most a Focus attachment may be, 1M to 4G (TD-473; built by TD-478); read by the attach RPC on each call
notify:                                       # §4.10 *Told on Telegram when nobody is looking*: read by the home's tick, and by the watch (§4.10 *When the home itself is down*)
  telegram: {on: false,                       # the one switch; absent or false, nothing is sent
             secrets: "samscrape/prd",        # the Doppler project/config holding TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID — a name, never a value
             link: "http://kmaster:8765"}     # how the person's phone reaches the UI (§4.5b); the row's address is appended; absent, reach.url
reach:                                        # §4.5b *The setting*: the person's route to the UI's route port; written by `ao connect` (`set_reach`; `set_settings` refuses the key) or by hand in this file, absent until then
  route: tailscale                            # tailscale | cloudflare (TD-656, built when asked)
  url: "https://kmaster.tail1234.ts.net"      # what a phone opens
  allow: ["paul@example.com"]                 # the logins the route port lets in: Tailscale-User-Login, or the Access token's email; compared without case; empty lets nobody in
  # team: myteam                              # cloudflare only: <team>.cloudflareaccess.com, whose certs sign the token
  # aud: "4f1c…"                              # cloudflare only: the Access application's audience tag
```

  `spend.weights` holds the API's list prices of 2026-10-17 as its default, a key per model family Claude Code reports, its current generation, and a longer key per older generation still served — the values above, the design's own, `as_of` the date they were taken (a newer price is the person's settings change, never a build-time correction), `cache_write` at twice `input` (the one-hour write a Claude Code session makes, §4.2a) and Haiku's `cache_read` at a tenth of its input; Haiku's dearer rate past a 100k prompt is not modelled, so its figure there reads low; the person's own values replace them whole per key, and a key with a kind missing weighs that kind at its `input`, the safe side, as `prices:` does (§4.2a). The figure is *API-equivalent* (§4.4 *Spend per seat*), and a weight changed applies from then on: a written row is not re-weighed.
  A metered profile's reserve under `usage_gate:` is an amount per window (§6 *Usage gate*) — `grind-api: {day: "$5", week: "$20"}` or `{day: "2M tok"}` — read against the account's spend (§4.2a), where a subscription profile's is a percent; the unit says which, and one that does not fit the profile's billing is refused, naming it. A profile absent under `usage_gate:` has no line on any window; a team absent under `teams:` has
  no schedule, no stop time and no priority, and starts the team, or the member, when work appears (`on_work: start`); a repo absent under `repos:` promotes by hand, is pulled (§6 *Pull*: `pull: false` is the opt-out), and has its mechanical sync PRs merged at the home (§6 *Sync*: `sync: {auto: false}` is the opt-out).
  **Nodes** (§4.4a *Settings, replicated*): the home sends the whole file to every node whose link
  is up after each write, and to a node on its `hello`; the node writes its replica and its gate
  reads that, offline included — *policies that stop run on the node, from its replica* — so the
  last settings a node was sent stay in force until its next dial; `set_settings` at a node is
  forwarded while the link is up and refused offline in the words the home-owned edits use.
  **`ui.yml` is retired**: its one key, `open_in:`, lives under `person:`; a `ui.yml` still on disk
  is not read: the agent's `settings` read names it (`migrate`), and the Org's teams line — the
  Settings page too, once built — says *migrate: ui.yml is no longer read*. The UI reads
  `person:` through that read, at most every five seconds, before it serves a request, and keeps the
  last answer when a read fails. What `person.open_in` takes is what `ui.yml` took, the editor button of the card and of the
  Focus Session card, *edit yml*, the Settings page's **Open file**, the Focus pane's file link and the Session
  card's recent files (§4.6 *A path in the pane is a link*: the same template with the file's path, served to the page as `editor.file`):
  - **`vscode`** — the default, and what a missing file means:
    `vscode://vscode-remote/ssh-remote+{remote}{path}?windowId=_blank` and, where the UI runs on
    the machine the person sits at, `vscode://file{path}?windowId=_blank`. The file form is each
    without `?windowId=_blank` and with `:line` after the path (§4.6; TD-524), and a file link sends the
    folder form before it, as `person.file_link` says (§4.6; TD-532, TD-536).
  - **`cursor`** — **no preset**. A preset's form must be confirmed against the editor's own
    documentation before it ships; Cursor's (`cursor.com/docs/reference/deeplinks`) documents
    only its `cursor://anysphere.cursor-deeplink/…` prompt, command and rule links, not a form
    that opens a folder, and community write-ups are not the editor's documentation. `open_in:
    cursor` is refused and named like any bad value; a Cursor user writes the form as a template,
    `{label: Cursor, url: "cursor://vscode-remote/ssh-remote+{remote}{path}?windowId=_blank"}`,
    which is theirs to trust.
  - **`{label: "…", url: "…", file: "…"}`** — a template of the person's own, which is how any other editor
    is reached (Zed, a JetBrains Gateway link: their remote forms are not the same shape, so they
    are not presets). `file` is optional (TD-536): the file link's own form, for an editor whose file
    link is not its folder link with `:{line}` after it; absent, the file form is `url` filled, as below.
    It takes the same three words, must be `scheme://…` under the same refusals, and `{path}` in it is
    the file; a `file` without `{path}` names no file, so it links none, as a `url` without one does.
  - **`none`** — removes the button everywhere.

  A template takes `{path}` (percent-encoded), `{line}` and `{remote}`, the host's `vscode_host`
  — `{line}` is the file form's (the printed line, else `1`; TD-524), and **a folder form drops it with the one
  `:` before it**, so `zed://ssh/{remote}{path}:{line}` opens the directory as `zed://ssh/host/dir` from the
  editor button, *edit yml* and Settings' **Open file** (TD-528: filling `1` would hand the handler a
  *file*, and refusing the template would take the button from the one person who wrote a file link);
  the Settings page's note under *url* names the three —
  from `hosts.yml` — an ssh alias in the person's own `~/.ssh/config`, whatever editor reads it;
  with no `{remote}` in it, a template is used as it stands on every host. **`person.file_link`** is what
  a file link sends, whatever the editor (§4.6 *A path in the pane is a link*; TD-536): **`folder_first`**,
  on when absent — the session's folder link goes first, so the file lands in the worktree's window;
  off, the file form alone, into the window holding its folder or else the last-used one — and
  **`wait`**, the seconds between the two, `1` when absent, `0` to `4` (the browser's activation window
  is five; a value outside is refused by `set_settings` as a terminal size outside its bounds is, and
  the file read keeps the default). The Settings page's **You** card draws both under the editor pick
  (§4.5a *Settings page: You, file link*). A command is not a setting: the page sends URLs and runs
  nothing (§4.6). **A template must be
  `scheme://…`, and `javascript`, `data`, `vbscript` and `file` are refused as schemes** — the
  scheme being the part before `://`, parsed, never a substring (`vscode://file…` is scheme
  `vscode`). One that does not parse, or is refused, is named on the page when it is served and
  the default button is drawn: a pasted bad line must not become a link that runs. The label is
  text the person wrote, escaped. Nothing under `person:` reaches a policy: the gate and the tick
  read the file by key and never this one.
- Repos: **ShiftLead's own roster**, `repos.txt` under the home (one main-checkout path per line, `#`
  comments), read first; **dev-cadence's `~/.config/dev-cadence/repos.txt` is imported** into the
  reading when it exists, so a host that runs the cadence lists both and one without it lists what
  ShiftLead was given; `hosts.yml`'s `repos_registry` names one file in place of the home's
  ([ADR 2026-10-12](../decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md), *Its own roster*; TD-584, built by TD-590). A repo without
  dev-cadence is a repo like any other: what ShiftLead requires of it is *The seams*, below. Directories that are not
  repos are not registered anywhere: New session takes a path, and the host agent remembers recent
  ones per host in `~/.shiftlead/recent_dirs`.
- Per repo: `.shiftlead.yml` (checked in). A repo that has not renamed its file since the project was
  `agentorc` is read from `.agentorc.yml` while no `.shiftlead.yml` is beside it (`sessionorc.paths.repo_file`, TD-060):

```yaml
unattended:                           # read by nothing yet (below)
  workers: 3
  brief: ~/.tdgrind/{name}-prompt.md
  window: {weekday: "20:00-06:00", weekend: all}
  # no usage gate here: its reserves are the person's, per profile, in settings.yml (TD-100)
  wrapup_minutes: 15
  creds_min_hours: 0.25
roles:                                # §4.8 presets; every key optional, built-ins apply otherwise
  grinder: {brief: docs/briefs/grinder.md, lane: free-pick, profile: grind,   # profile: §4.9
            review: {reader: techlead}}   # §4.9b *The reader*: its PRs wait for the techlead; `held:` defaults to every PR
  hunter: {brief: docs/briefs/hunter.md, icon: search}   # icon: §4.8, one name from the fixed set
  manager: {brief: docs/briefs/manager.md, grants: [control]}
  plain: {prompts: [{label: review PR, text: "Review the PR I name next as the cadence says, then report."},
                    {label: sweep, text: /stranded-work},
                    {label: waiting on me, text: "What is waiting on me across this repo's board and my inbox?"}]}   # prompts: §4.8, the chips beside Send (TD-161)
controllers: [manager-ao-1]           # §4.8: who may act on a session started here (a preset may
                                      # override it with its own `controllers:`); omitted = nobody
ledger: docs/technical_debt.md        # what a TD-NNN reference resolves to: a ledger in ledgerboard format (*The seams*)
board: docs/user_attention.md         # the person's board, optional (*The seams*); unset: the Inbox is the person's channel
gate: python3 scripts/check_cadence.py --pr {pr} --json   # the merge gate, a command judged by its exit code (*The seams*)
worktree_setup: scripts/hydrate_worktree.sh   # run in every new worktree (*The seams*)
held: ["src/sessionorc/**"]           # §4.9c: the paths a review stage holds (the `build` flow holds nothing)

settle: {design-first: 10m}           # §4.4 *A new entry settles*: wins over settings.yml's settle:, key by key
                                      # this repo's own flows and roles are directories in .shiftlead/, not keys (§4.9c)
teams:                                # §4.9: the repo's own teams, aggregated into the org; org.yml wins a name
  grind: {flows: [build], manager: {role: manager, name: manager}, members: [{role: grinder, count: 2, name: grinder}]}
ready_when: [tree_clean, branch_pushed, pr_merged, no_subagents, ledger_touched]   # read by nothing yet
commands:                             # `test` and `lint` fill the briefs' {test} and {lint} (*The seams*); the rest the Commands page's (read by nothing yet)
  test: pdm run test
  lint: pdm run lint
  cluster: ./scripts/cluster-status.sh
promote:                              # §6 *Promote*: how a merge to `main` becomes the live copy
  run: scripts/promote.sh             # makes the tree it is started in live; run at the home
  check: scripts/live_sha.sh          # prints the commit that is live now, or fails saying why
  smoke: scripts/smoke.sh             # optional: exits 0 when what is live works; run after check reads the commit
```

  **Read by nothing yet** (TD-149): `unattended:` (once the New session switch's precondition; the Role pick that replaced it does not check it, §4.5
  screen 3; the window and wrap-up are `settings.yml`'s and the tick's today), `ready_when:` (§4.2's
  checks, which are fixed today and not chosen per repo) and the names of `commands:` other than
  `test` and `lint` (the Commands page, §4.5 screen 5, phase 4) are accepted and checked, so a file
  written ahead of its feature does not break `ao new`, and nothing acts on them until that feature
  is built. **Not keys**: `adapter:` and
  `worktrees:` are refused, the error naming where each is decided — the adapter per session and per
  profile, and a session's worktree always `<repo>/.claude/worktrees/<name>` (the host agent never
  reads this file, so it could not move it). **`anchor:`** is retired (§4.9b *No anchor seat*): `anchor: false` is read and passed over, any other value refused as retired, since no seat runs in a main checkout (§9 invariant 2).

  **`promote:`** (`run` and `check`, both required; `smoke` optional; `auto` refused as `settings.yml`'s) is the repo's own
  answer to *how does `main` become what is running*, and nothing in shiftlead names pip, a venv,
  systemd, skaffold or wrangler: this repo's `run` is the pip pair of CLAUDE.md and its `check`
  prints the installed build's commit (`sessionorc.build.info()`); samscrape's would be its
  skaffold run and the deployed image's tag; contractmatch's a wrangler deploy and the deployment's
  commit; dev-cadence's its sync. Both are commands run **at the home** (§6
  *Promote* says when), `check` in the checkout and `run` in the tree it is to make live: the
  checkout, on main's head, for a promote, and a detached worktree at the commit for a rollback
  (§6 *A rollback*). So **`run` makes live the tree it is started in**, names no path to
  the checkout, and finds the checkout in `SHIFTLEAD_PROMOTE_ROOT` when it needs what no commit
  holds. It is judged by what `check` says
  afterwards, never by its exit code; `check` prints one full commit on stdout and exits 0, or
  exits non-zero with the reason on stderr (*not deployed*, *no cluster*), which the row shows as
  *live: unknown — <reason>*. **`smoke`** (TD-804) is run once `check` reads the new commit, in the
  tree `run` was started in, and judged by its exit code. 0 means what is live works. A failure puts
  back what was live before, never after a rollback (§6 *The smoke*): this repo's loads the pages
  and reads `ao`, and samscrape's would hit the deployed service. A block without one concludes on
  `check` alone. `auto` lives in `settings.yml` (`repos.<repo>.promote.auto`, the Settings page's switch) and is `false` when absent: the row offers a press. A repo with no
  block has no promote, no row and no `ao promote`. It is read **by the host agent**
  (`sessionorc.promote`, the key alone, from each checkout in the home's registry, `smoke:` from the
  run's tree when a run starts, §6 *The smoke* — the agent
  resolves no role and no brief), because a policy that acts needs its declaration where the policy
  runs; the seams below are read there for the same reason, and the rest of the file is the clients'.
  `ledger:` travels on the record as well, because it is a session's.

  **The seams** ([ADR 2026-10-12](../decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md), *What ShiftLead requires of a repo, and what it only uses*; TD-584).
  ShiftLead **requires** one thing of a repo: a ledger in ledgerboard format at `ledger:` (default
  `docs/technical_debt.md`), the format `ShiftLead/ledgerboard`'s `SPEC.md` defines and its
  `ledgerboard.py` reads — the one parser, vendored as `src/sessionorc/ledgerboard.py` and held
  byte-equal to the synced `scripts/ledgerboard.py` where both exist (§8 *Which side a thing lives
  on*). `ao repo init` writes an empty one (§4.7). An external tracker is mapped *into* the ledger by
  an importer, never read in its place. Everything else is **used when present, and named when not**
  — a seam is a key of this file, each with a default that is dev-cadence's file when the checkout
  holds it, and a fixed sentence the Repo page, `ao doctor` and the briefs say when neither is there,
  never empty text or a silent fallback (§4.5a *Repo page: missing seams*, §4.7 `ao doctor` **repos**):
  - **`board:`** — the person's board, default `docs/user_attention.md` when that file exists; unset
    and absent, the person's channel is the Inbox alone (*no board: the Inbox is the person's channel*;
    every reader, `workorders.board_path`, built by TD-587).
    With one, the Inbox reads it in-process through `ledgerboard.py` — the checkout's file and
    `origin/<default>`'s after the host's own fetch, the origin note derived from the two (§4.5 screen 6
    *Boards are read against origin*) — and runs no dev-cadence script; a repo with a board needs no
    dev-cadence. A session's own edit of a line is `ao board edit` on its branch (§4.7); the person's
    presses are the write-back (§4.4).
  - **`gate:`** — the merge gate, a command with `{pr}` filled that exits 0 for a mergeable PR, judged
    by its exit code alone; default, when `scripts/check_cadence.py` exists, that script run `--pr {pr}
    --json`, the one shape whose rows the record's checks entry keeps (§6 rule 10). Unset and absent:
    **the review stage never merges on its own**, the record's entry reads `verdict: none` and
    `ao status -v` prints *no gate: a person merges* (§6 rule 10); the Repo page (TD-591) and the
    briefs (§4.9c, TD-588) say the same.
  - **`commands:`** — a mapping; `test` and `lint` fill `{test}` and `{lint}` in the built-in briefs and
    flows (§4.8 *A repo's brief*), each unset one filling with its seam's sentence (*no test command:
    run what the repo's README says*). This repo's own `pdm run …` lives here and in its own brief,
    not in the built-ins, which name no repo's layout ([ADR 2026-10-12](../decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md),
    *Briefs and flows name no repo's layout*; TD-588).
  - **`worktree_setup:`** — a command run by the shell in each new worktree, its path `$1`, after it is created
    (`sessionorc.gitinfo.ensure_worktree`; a worktree reused is not set up again), default
    `scripts/hydrate_worktree.sh` when present and executable, given the worktree's path; unset and
    absent, nothing runs and the Repo page says *no worktree setup* (TD-589). A setup that fails
    leaves the worktree and fails the create with its own words.
  - **`ledger:`** carries, beside the ledger, the `{ledger_check}` the briefs name: `python3
    scripts/ledger.py --check` when that script exists, else the seam's sentence.
  **The layout slots** a built-in brief names (`repoconfig.layout`, TD-588) are `{gate}` (*no gate: a person
  merges*; dev-cadence's default `python3 scripts/check_cadence.py --pr {pr}`, the `{pr}` filled as
  `<n>` after the rest), `{board}` (*no board: the Inbox is the person's channel*), `{ledger}`,
  `{ledger_check}` (*no ledger check: keep each entry in the shape the ledger's other entries have*),
  `{test}` (*no test command: run what the repo's README says*), `{lint}` (*no lint command: keep to the
  style of the code around the change*), and two that are no key, dev-cadence's file or the sentence:
  `{design_dir}` (`docs/design/` where the checkout holds it, else *no design directory: the README and
  the code say what is true*) and `{cadence_rules}` (*read docs/cadence.md §1–§4* where it exists, else
  *no cadence rules: the repo's README says how a change lands*). They are read only when the brief
  being composed names one — a node's files are asked across the link, where a directory or a file
  past the cap is refused by name and is there, and any other failure stops the start rather than tell
  the brief a seam is absent — after every other slot, and fill a supplement's text as they fill the
  template's. `commands:` is also read in its older list form, `[{name, run}]`.
  Convention notices (§6 rule 12) and the SessionStart line (§4.3) run only in a dev-cadence repo:
  features of one, never requirements. **Who reads them**: the host agent, at the home, reads
  `ledger:`, `board:`, `gate:`, `worktree_setup:` and `settle:` as it reads `promote:` — for the repo facts
  (§4.4: the seam state the Repo page and `ao doctor` draw), the gate run (§6 rule 10 runs at the
  home), the write-back (§4.4: the board's path) and a worktree's creation — and the clients
  (`repoconfig.py`) read every key for the briefs, `ao board edit` and `ao repo init`; `commands:`
  and the rest of the file are the clients' alone.

- Org (§4.9): the teams each registered repo defines in its own `.shiftlead.yml`, aggregated with
  the org file, which holds what no one repo can: the project headings over repos, a team kept out of its repo's file, `place:`
  and the install's `roles:` overlay; `org.yml`, `profiles.yml` and `settings.yml` (and the
  person's `preferences.md`, §4.9b, TD-657) are tracked by a git work tree in `~/.shiftlead/` at the home (§4.9 *The org is an aggregate*, *What is
  left at the home has a history*).
  The org file: `~/.shiftlead/org.yml` on the UI host — projects, teams, and an org-wide `roles:`
  roster that sits between the package's built-ins and a repo's own, each preset checked key by key
  exactly as a repo's `roles:` is. Read by the clients on every use, never by the host agent:

```yaml
projects:                                    # §4.9: headings on repos (TD-722); a repo in at most one, a repo in none its own heading
  contractmatch: {title: ContractMatch, repos: {samscrape: {kmaster: ~/samscrape}, contractmatch: {kmaster: ~/contractmatch}}}
  guardians: {repos: {guardians: {devenv: /workspaces/guardians}, guardians-api: {devenv: /workspaces/guardians/api}}}
teams:
  ao-grind:
    repo: shiftlead                            # one repo per team (TD-722); unsaid in a repo's own .shiftlead.yml
    manager: {role: manager, name: manager-ao-1}
    members:
      - {role: grinder, count: 2, name: grinder-ao, lane: free-pick}
roles:
  grinder: {profile: grind}
director: {profile: grind, brief: docs/briefs/director.md}   # TD-636, §4.9b *The director seat*: the org's one seat of no team, trigger `prompt` (with `asks` and `groom`, TD-657); absent, none
```

A repo without the file gets defaults: `adapter: claude-code`, worktrees under
`.claude/worktrees`, `ready_when: [tree_clean, branch_pushed, no_subagents]`, no commands, no
unattended mode, the three built-in presets with the package's brief templates, and
`docs/technical_debt.md` as the ledger. The `unattended:` block is where every time-shaped
setting lives (window, stop times); the usage gate's reserves are the
person's and live in `settings.yml`. A `roles:` preset never carries a schedule, and a
grant never carries one either. A directory session (no repo) reduces to `ready_when:
[no_subagents]`.

- **Test knobs, not settings**: `SHIFTLEAD_TICK` — the host agent's tick in seconds (default 2),
  read once at its start — exists for the test suite, which runs agents on a faster clock; nothing a
  person sets, and no page shows it.

