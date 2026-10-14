# Technical Debt

Known issues, compromises, and deferred work. Add an entry any time a problem is identified but not immediately fixed — no exceptions, however small (see [`cadence.md`](cadence.md) §2).

**This file holds open work only.** The summary table below lists exactly the entries that have a body in this file — one row each, no history. When an entry is fully resolved, move the whole body to [`technical_debt_archive.md`](technical_debt_archive.md), delete its summary row, and replace **Fix** with the resolution date plus a pointer to whichever doc/code now carries the lasting content. An entry that is only *partly* resolved stays here, with what shipped and what remains spelled out in its **Status**.

IDs are `TD-` plus a zero-padded three-digit number, assigned in order and never reused. Priority is a field, never part of the ID.

Two header lines follow **Added:** so a worker can filter the file instead of re-reading it (TD-118): **Owner** — who moves the entry next (`anchor`, `designer`, `grinder`, `paul`, `dev-cadence`); **Kind** — what the next step is (`build`, `design-first`, `live-check`, `evaluation`, `decision`). Every open entry carries them; keep them true when the Status changes. **Pickable is derived, never written** (cadence §2.4, TD-228): an entry is pickable while its `**Blocked by:**` names nothing still open and no decision, so what waits on another entry or on a person's word says so there, with its pointer; what nothing blocks and a grinder still cannot build — a live look, an evaluation, the anchor's edit — is said by its **Kind** or its **Owner**, and the Status says what is next. A `live-check` is followed on its line by its build's last merged PR — `**Kind:** live-check #<n>`, written by the PR that makes the entry a live check — and once that PR is live (`ao promote status`) the check is in a `free-pick` lane whose owner it has (design §4.9b, TD-320); cadence's script reads the word alone. A grinder's pick list is therefore `ao repo` (its pickable entries, a live check whose build is live among them), and `python3 scripts/ledger.py --list --pickable yes --owner grinder --kind build` lists the builds alone; the designer's is `--owner designer --kind design-first`. The line below is the one list of the **Owner** and **Kind** words (cadence §2.12): `scripts/ledger.py` flags a value outside it, and `tests/test_ledger.py` reads its sets from it and checks the two lines' shape, so a new word is added there and nowhere else.

Fields: Owner = anchor | designer | grinder | paul | dev-cadence; Kind = build | design-first | live-check | evaluation | decision

---

## Summary

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| TD-003 | Phone layout: narrow Focus with a soft-key row | Medium | Open |
| TD-005 | `pretrust()` can lose a concurrent Claude Code rewrite of `.claude.json` | Low | Open |
| TD-026 | Scheduling: start/stop times and window overrides for unattended sessions, editable from the UI | Medium | Partly done — the reset start (TD-133) and the start time (TD-152) designed; archives with them |
| TD-035 | Adapters without a session-start hook still run dev-cadence's SessionStart set | Low | Open — designed; builds with the second adapter (TD-112) |
| TD-052 | Messages between sessions: the mailbox, the graph that gates it, the bounds, and the surfaces — build design §4.10 | High | Partly done — steps 1–8 done (5 was a measurement); the second-adapter step and the live check remain |
| TD-060 | The rename to ShiftLead's loose ends: TD-552's text sweep and TD-553's fallback; archives when both are done | Medium | Step 2 live 2026-10-11 (#1505, cutover done); repo renamed and moved to the ShiftLead org; the live briefs swept; the dev venvs rebuilt; what is left is split out (TD-552, TD-553, and each repo's own entry) |
| TD-071 | Org page review 2026-09-18: the ideas not built — Forget all on a stopped team, unread mail on a folded team, a state roll-up on a live team's header, slimmer dead cards, a quieter mode badge | Low | Items 1 and 2 built 2026-09-23 (PR #499); 8 is Paul's canvas |
| TD-112 | The adapter contract has grown Claude-shaped and neutrality is untested: a scraped second-adapter spike now, not in phase 5 | Medium | Open |
| TD-131 | Mail, the board and the records are JSON and Markdown files read whole: fine at today's size, and no answer to search over history, counts per filter, or a retention longer than twelve hours | Low | Decision (Paul) — not yet; the trigger is written down |
| TD-133 | Build the team start at the reset — `schedules:` in `settings.yml`, the tick's replay, `ao schedule`, the card's *starts* note | Low | Open — designed; not scheduled until Paul says |
| TD-156 | UI review of the end of a session, and of the whole Focus screen: the two-line header, Close session as the next act, the side panel's folds, a concluded team never folds | Medium | Designed and built 2026-09-25 (cloud session with Paul) — live look pending; (g) not reproduced |
| TD-290 | A UI change goes to the person unchecked: the grinder that made it verifies it itself (Playwright, a scratch UI before the PR, the live copy read-only after the promote), a reviewer only for what it cannot settle, and what is left for the person is a look sent as mail — a steer or an ask, in Steering or Needs you — no longer a `watch` | Medium | Designed 2026-10-03 — build TD-292 (TD-291 built) |
| TD-292 | Build the mail half of a look: the briefs' three cases as a steer or an ask, `--shot` and the envelope's `shots`, screenshots and the pair on the row, Send to reviewer | Medium | Built (#975, #980, #982, #983, #987, #990, #1007); live check waiting on the first look a builder sends |
| TD-297 | The parts of the live looks of 2026-10-03 nobody could see: each waits on a press, a live event or a fixture, for a scratch home or the next time it happens | Low | Open |
| TD-299 | Run the guardians and contractmatch teams inside their devcontainers: provision the nodes for workers, define guardians' team, land both by `place:` | Medium | Paul's — contractmatch done; guardians' team, node and `place:` left |
| TD-300 | A look's screenshots from a sender on another host draw their names alone: the shot route reads this host's registry only | Low | Live check #993 — waits on a look from a node (TD-299) |
| TD-410 | Every team Start fills the on-call manager, which reads ~60k tokens of design to find nothing due: 14 fills since 2026-10-03, all *nothing to do* | Medium | Designed — TD-413 builds it |
| TD-413 | Build TD-410: a Start writes the on-call manager held — no pane until a reading is due — the fill's cause line, and the on-call briefs' first reads | Medium | Built (#1287, #1684); live check: a week's journal once #1684 is live |
| TD-460 | Read back the one-week trial of a 200k context bound on ao-grind's grinders | Medium | Open |
| TD-463 | Four CI flakes since 2026-10-03, one of them seen four times | Medium | Open |
| TD-512 | A PR that truncates `docs/technical_debt_archive.md` passes every gate: the ledger tests and the cadence check's ledger row read neither its length nor what it lost | Low | Open |
| TD-553 | Drop the `.agentorc.yml` fallback once samscrape, contractmatch and dev-cadence have renamed theirs | Low | Blocked by the three repos' renames |
| TD-584 | Design the ledgerboard split into ShiftLead: §4.5a, §4.7, §4.9a, §5, §6 and §8 (the ADR's build 3) | High | Designed — TD-585–TD-591 build it |
| TD-585 | Vendor ledgerboard and drop ShiftLead's own ledger and board parsers (the ADR's build 4) | High | Open |
| TD-587 | `board:` path key and `ao board edit` (done, snooze) for a session's own branch | Medium | Open |
| TD-588 | Briefs, flows and `team_skill.md` name no repo's layout: `commands:`, variables, and a test that bars the literals | Medium | Open |
| TD-591 | `ao doctor` and the Repo page name what a repo lacks; `ao repo init` makes an empty ledger | Low | Open |
| TD-611 | The UI's single event loop stalls the Focus terminal: two bulk polls render megabytes synchronously several times a minute, and both grow with the inbox, the fleet and the PR count | High | Live check — blocked by TD-670 |
| TD-614 | The UI and `ao` re-derive what the host agent could hold once: inbox counts, the board reading, per-session views — poll-and-render instead of one reading pushed | High | Designed — TD-615, TD-616, TD-617 build it |
| TD-622 | #1563's `AO.shellHere`: the *tab* blocked-pop-up word, the create-answered-without-an-id close and the directory-less placeholder are held by no test (test audit) | Low | Open |
| TD-623 | No document says how a repo gets its first ShiftLead team: what to write, in which repo, what is the person's | Medium | Open — blocked: Paul says when guardians-devenv TD-028's gap list is enough |
| TD-627 | The Focus Git card's changed files are plain text: make each a link that opens it in the person's editor, as the Session card's recent files do | Low | Designed — TD-628 builds it |
| TD-628 | Build TD-627: each path on the Focus Git card a link by the recent files' form; a deletion and a new directory stay text | Low | Open |
| TD-630 | Pictures and files cannot go into the Add entry form: a screenshot of what is wrong needs a session opened first | Medium | Designed — TD-633 builds it |
| TD-636 | A director seat answers permission prompts for the person: routine ones allowed or denied by written rules, the rest escalated | Medium | Designed — TD-641, TD-642 build it |
| TD-637 | `ao progress done … --pr <n>` is accepted while the PR's required checks are red or missing | Medium | Designed — TD-639, TD-640 build it |
| TD-638 | A commit names the session that made it, not the model: as tools and models multiply, which model did what is lost | Low | Designed — TD-644, TD-645 build it |
| TD-640 | `check_cadence.py`'s `ci` row reads the base branch's required checks, not every run on the head (TD-637) | Low | Open |
| TD-641 | Build TD-636 (1): the person's `permissions:` rules per role, matched by the host at the hook, the always-the-person list, every answer an *Answered for you* FYI | Medium | Slice 1 in #1697; slice 2 (the pages) left |
| TD-642 | Build TD-636 (2): the org's director seat — `director:` in `org.yml`, its trigger and `director.md`, the `permit` grant, the manager's triage standing aside | Medium | Open |
| TD-645 | `prepare-commit-msg` writes `Agent-Model: <adapter>/<model>` from `AGENT_MODEL_FILE`, else `AGENT_MODEL` (TD-638) | Low | Open |
| TD-646 | Reachability: the person's own route to the UI — Tailscale first, `ssh -L` always, Cloudflare designed and built when asked; a relay forwards ciphertext only | Medium | Designed — TD-647, TD-648 build it |
| TD-647 | Build TD-646 (1): the UI's route port — a second loopback listener that requires the route's identity on every request and websocket | Medium | Open |
| TD-648 | Build TD-646 (2): `ao connect` (tailscale, off), `reach:` in `settings.yml`, `ao doctor`'s route line, the README guide | Medium | Open |
| TD-651 | The team card's **definition changed** Apply tooltip names seats alone: a profile relaunch (TD-619) is applied there too | Low | Open |
| TD-652 | The pages re-derive who holds a red PR (`teamrun.pr_holders`, a copy of `workorders.holds_pr`): the home's reading should carry the holders | Low | Open |
| TD-656 | Build TD-646 (3): the Cloudflare route — the Access token check on the route port, `ao connect cloudflare`, its doctor line and guide | Low | Open — built when asked |
| TD-657 | The director seat knows the person only through its brief: it should also answer what techleads pass up, from the person's written preferences in layers, at a level the person sets | Medium | Designed — TD-661, TD-662, TD-663 build it |
| TD-661 | Build TD-657 (1): a pass goes to the director where the org has one — `passes` once per passer, the director's `asks` cause, its pass to the person, both recommendations on the row | Medium | Open |
| TD-662 | Build TD-657 (2): the preference layers and the level — the package's `preferences.md`, `{preferences}` in `director.md`, `director.level` per org and repo, `answered.level`, the Settings page's Director card, `ao prefs` | Medium | Open |
| TD-663 | Build TD-657 (3): the groom pass, the seed, Remember this, the interview — `ao prefs propose`, the *preferences proposed* row's Accept and Discard, the home's commit | Medium | Open |
| TD-665 | A shell's Focus and card draw an agent's controls: Wrap up types the wrap-up prompt into bash, and Message, Reports, Ready to close and the Session card's grants and controllers are agent-shaped | Medium | Designed — TD-666 builds it |
| TD-666 | Build TD-665: a record with no agent — the adapter's `agent` on the view; no prose typed, no mail, no derived claim; Focus and the card draw a shell's controls | Medium | Open |
| TD-667 | A key typed into the Focus terminal while it is scrolled back is swallowed by tmux's copy mode: typing should return the pane to the live screen and reach the prompt | Medium | Designed — TD-669 builds it |
| TD-668 | The Add entry form's **What** box is one line high and its hidden error note draws as an empty orange box: `.input`'s 34 px and `.warn`'s `display: flex` beat `rows` and `[hidden]` | Low | Open |
| TD-669 | Build TD-667: a typed key leaves copy mode first — the bridge's *scrolled* mark, `copy-mode -q` before a printable key, Enter, Tab, Backspace or paste, its tmux commands in order; every host-agent send leaves copy mode first | Medium | Open |
| TD-670 | A Focus stream is sent every repo's whole facts on each `repos` push to read its PR marks, and the loop still holds 45–300 ms with a stream open: TD-611's remainder | High | Live check — once #1704 is live |

---

<!-- Entry template:
## TD-001: Short title of the problem

**Priority:** High | Medium | Low
**Added:** YYYY-MM-DD
**Owner:** anchor | grinder | paul | dev-cadence
**Kind:** build | design-first | live-check | evaluation | decision
**Status:** Open
**Location:** `path/to/file.py` (function/section)

**Why:** what's wrong, how it was found, and the reasoning — future sessions need the why, not just the symptom.

**Fix:** concrete direction(s), and what would count as done.

**Related:** other TDs, PRs, decision docs.
-->

## TD-003: Phone layout: narrow Focus with a soft-key row

**Priority:** Medium
**Type:** feature
**Added:** 2026-09-06
**Owner:** paul
**Kind:** build
**Status:** **Paul, 2026-10-07:** reserved until the real connection path (how the phone reaches the home) is built. **Paul, 2026-10-13 (the lessons ADR, lesson 9):** the Inbox, improved, is to be the phone's text interface; a chat integration only if it cannot be. Open **Next:** Paul's (the grinder brief reserves it).
**Location:** `src/shiftlead/ui/static/app.css` (`@media (max-width: 720px)`), `focus.html`

**Why:** Design §4.5 (phone, phase 2): Team collapses to cards with Allow / Deny, Focus gets a narrow mode with the terminal full-width and a soft-key row (↑ ↓ ← → Enter Esc Tab 1–9) so questions are still answered through the terminal. The CSS has a bare media query; there is no soft-key row and nothing has been tried on a phone.

**Fix:** soft-key row that sends keys through the terminal websocket (not `send-keys`, invariant 6), collapsed side panel, 44 px tap targets on Allow / Deny; test on a phone over the route `ao connect` sets up (design §4.5b; TD-647, TD-648). On the phone the failure is silent — with the Tailscale app off or asleep, Safari shows its own error and none of the UI's pages — and iOS drops the `/events` and `/term` websockets whenever it suspends Safari: so reconnect on `visibilitychange` and `online`, the UI's disconnected banner opening with *is Tailscale on?*, the Telegram note saying *(Tailscale on)*, and the page fit for *Add to Home Screen* now that the route gives it a stable `https` origin (Fable review of TD-646, 2026-10-13).

**Related:** design §10 "Phone answers for questions" (open).

## TD-005: `pretrust()` can lose a concurrent Claude Code rewrite of `.claude.json`

**Priority:** Low
**Added:** 2026-09-06
**Owner:** anchor
**Kind:** evaluation
**Status:** Open. **Read 2026-10-10 (ao-paul, with Paul): the file edit is the documented route, and its key is too narrow.** Claude Code has no flag, setting or environment variable that only skips the trust dialog (CLI reference, settings reference, env-vars, read 2026-10-10 on 2.1.296). `claude -p` skips it, but that is the headless mode, and bypass mode is not documented to skip it. The permissions page (*What runs before you trust a folder*) documents the manual route as `projects["<path>"].hasTrustDialogAccepted = true` in `~/.claude.json`, *where `<path>` is the repository root*. Its *Project allow rules and workspace trust* section adds that a worktree uses *the main checkout's root*. `pretrust()` keys the entry on `cwd`, each session's own worktree, so it rewrites the tool's file on nearly every new worktree where once per repo would do. That is where the race's exposure comes from. The worktrees page tells a person to run `claude` once in a new directory, which reads against the permissions page, so a test settles it. **Next:** an attended run, as the Fix says.
**Location:** `src/shiftlead/adapters/claude_code/__init__.py` (`pretrust`)

**Why:** The first-run trust quirk does a read-modify-write of Claude Code's own `.claude.json` under an flock that only agentorc takes. A running Claude Code session that rewrites the file inside that window loses its write (or we lose our flag, which merely re-shows the dialog). Raised in the PR #3 review; the window is one read plus one write at launch time.

**Fix:** (1) Test, in an attended run, whether a fresh worktree of a repo whose main checkout is trusted opens with no dialog (the permissions page says it does; the worktrees page suggests not). (2) If it does, key `pretrust()` on the main checkout's root (the first entry of `git worktree list --porcelain`, as the cadence line computes it) and on `cwd` outside a repo. The write then happens once per repo, and the race's window shrinks to that one launch. (3) As the fallback, answer the dialog through the terminal channel. The adapter's screen rules already recognise it (`explain`, which names the trust dialog), so what is missing is the key press, sent once, on a pane agentorc itself launched into a directory it chose. (4) Drop the file edit altogether only if (3) proves reliable on its own. Since there is no supported flag or settings key, the documented file edit stays the primary road. **Done when** the test's answer is written here, `pretrust()` writes at most once per repo, and a dialog that still appears is answered with no person's press.

**Related:** TD-006.

## TD-026: Scheduling: start/stop times and window overrides for unattended sessions, editable from the UI

**Priority:** Medium
**Type:** feature
**Added:** 2026-09-10
**Owner:** grinder
**Kind:** build
**Status:** Partly done — **round 2, 2026-09-25 (the designer, PR #548), on Paul's answer to the scope ask (*keep start_at and a scheduled state for one session as well*):** §6 *Start time* (`start_at`; the record created now with its launch record and the directory's slot, the `scheduled` state, the session created at the instant by the tick, `ao at`, Cancel), §4.2's state, §4.5a's *starts* note, **At** field and ◷ glyph, §4.7's verbs, the glossary's *start time*; the build is **TD-152**. Dropped on the same answer: window overrides with an expiry (TD-101), calendar-shaped windows, one-off runs. Was: **design round 2026-09-24 (the designer, PR #526):** the start at the reset is designed as §6 *Schedule* — a replay of the team's last person-pressed start from its launch records at the `resets` of a named profile's window, kept in `settings.yml` `schedules:` (§5), set by `ao schedule` (§4.7), shown as the team card's *starts* note (§4.5a); the build is **TD-133**, unscheduled until Paul says (2026-09-22: *not vital, not scheduled*). **A team-wide stop time** was designed 2026-09-25 as a setting (§6 *Team stop time*, `teams.<team>.until`, the Settings page and `ao team until`; TD-146 builds it), which answers the *editing a stop time from the page* shape for a team. The other shapes below — `start_at` and a `scheduled` state for one session, window overrides with an expiry (TD-101 already says *not wanted yet*), calendar-shaped windows, one-off runs — are a scope question put to Paul the same day (ask m-32d769985798; the recommendation: build the reset start, drop the rest, and let the phase-3 run window be its own design when it comes). Was: the per-session **stop time** landed 2026-09-13 (PR #129): `run_until` on the record, `ao new --unattended --until 06:00|+8h|<ISO>`, `ao until <session> <when>|--clear`, the wrap-up-then-kill on the tick, and *stops 06:00* on `ao status -v`. That closes gap (1) below — a hand-started worker now has a stopper. Open: `start_at` and the `scheduled` state, window overrides with an expiry, calendar-shaped schedules, one-off runs, and the UI *beyond* the stop time — the card and Focus header say *stops 06:00* and the New session form has an **Until** field (PR #131), **and the Focus header's badge became the control that edits it on 2026-09-14 (PR #147)** — click for a time, empty to clear, drawn only for an unattended session since the agent refuses one on an interactive session either way; a session with no stop time shows a dim *no stop time* rather than nothing, because "nothing will stop this" is the fact a person opening Focus most needs. The review of that PR found a live bug the control would have made easy to hit: `set_stop` cleared `wrapup_sent_at` on every call, so re-confirming an unchanged, already-elapsed stop time asked a session inside its wrap-up grace to wrap up a second time — and, since the ask happens before the grace check, repeatedly touching the control deferred the forced kill indefinitely, which is this entry's own gap (1) reintroduced through the edit path. Only a *different* time now counts as a new run. Latent and not reached today: every caller passes the one shared `WRAPUP_PROMPT`, so the control cannot yet clobber a custom wrap-up text, but it would if custom texts were ever exposed. The card shows no next transition for a repo window because there is no repo window. The repo window is still phase 3; when it lands it should *set* a stop time rather than be a second mechanism. **2026-09-22:** one more schedule shape, decided by Paul the same day: **a team start at the usage window's reset**, using the reset time the adapter already reports (§4.3, TD-073) — configurable, **off by default**, set from the settings page TD-100 describes; not vital, not scheduled. **Next:** designed; the builds are TD-133 (the reset start, unscheduled until Paul says) and TD-152 (the start time); this entry archives with them.
**Blocked by:** TD-133, TD-152
**Location:** design §6 (policies), §4.5a (New session, card / Focus header), §5 `.agentorc.yml` `unattended:` block

**Why:** Design §6 gives unattended sessions one schedule: the repo's weekly `window` (phase 3, the tdgrind port). That covers the nightly grind and nothing else. Two gaps showed on 2026-09-10, the first day the three samscrape tdgrind workers ran under agentorc instead of the cron supervisor: (1) a worker started by hand with `ao new --unattended` outside the window has **no stopper at all** — nothing wraps it up at 06:00, at a usage cap, or when the token lapses, so "start it now so I can watch it" means "remember to close it yourself"; (2) every deviation from the weekly window is a hand edit to a config file — tdgrind's `~/.tdgrind/config` carries dated shell one-liners (`[ "$(date -u +%s)" -lt <epoch> ] && WINDOW_START=0 …`) for "Paul is out today, run all day", which is a schedule expressed as code, invisible to the Team and forgotten once it lapses. A scheduler is the general form of both: a session or repo carries *when it may run*, the policy tick enforces it, and the UI shows and edits it.

**Fix:** treat the weekly window as one kind of schedule and add the others on the same policy tick, all visible on the card:

- **Per-session `run_until` / `start_at`** on the New session form and the `ao new` flags (`--until 06:00`, `--until +8h`, `--at 20:00`): a stop time gets wrap-up-then-kill exactly like leaving the window; a start time queues the session (a new `scheduled` state on the Org page, with the time) and the tick launches it. A session started by hand with `--unattended` and no `--until` inherits the repo window's next close, so gap (1) cannot recur.
  **`--until` landed 2026-09-13 (PR #129)**: the CLI parses `06:00` (the next one, in the caller's local clock), `+8h` and ISO and hands the agent an absolute instant — "the next 06:00" is a question about the caller's clock, so the record never has to answer it. At the instant the agent sends the wrap-up prompt once and kills the session when it settles or ten minutes later; the wording travels on the record (like `ledger`) because `sessionorc` must not know what a brief is, and it is the same text `ao team stop` sends. `ao until <session> <when>|--clear` sets or clears it afterwards, through a `set_stop` RPC gated as an acting call — a stop time is a `kill` with a delay on it. `--until` without `--unattended` is refused rather than stored: a stop time nothing will act on is this entry's own failure inverted. The UI followed in PR #131: the **stops** note on the card and the Focus header (§4.5a), from the same formatter `ao status -v` uses, and the New session **Until** field, which refuses a stop time on a session that is not unattended exactly as `ao new` does. Left here: `start_at`, the `scheduled` state, editing a stop time from the page (the CLI's `ao until` has no page equivalent yet), and the inheritance from the repo window, which needs the window (phase 3) first.
- **Window overrides with an expiry**, per repo, kept in agent state rather than the checked-in `.agentorc.yml`: "run all day until 2026-09-02 20:00", "pause until Monday" (the PAUSE flag with a date), caps to 99% until the weekly reset. Shown on the repo's row with the expiry; expired overrides fall away by themselves. This replaces the dated one-liners in tdgrind's config.
- **Calendar-shaped schedules** in the `unattended:` block beyond weekday/weekend: a list of `{days, hours}` rules, and a `tz` (the window is in the host's local time today, which is right on one host and ambiguous on two — phase 2 adds the second host).
- **One-off runs**: schedule a *command* session (§4.5 Commands) or a brief at a time — "run the deploy at 02:00", "start a review worker Friday evening" — which is the Commands tab plus a time. This is the dev-cadence `/schedule`-style routine, local and tmux-backed.
- Edits from the UI go through agent RPCs (`set_schedule`, `set_override`), never by writing the repo file; the checked-in block is the default, overrides layer on top. `ao status` shows the next transition ("stops 06:00", "starts Fri 20:00") per session and per repo.

Done when: a hand-started unattended session shows when it will stop and stops then; "run all day today" is one click or one `ao` line with an expiry, not a config edit; the Team shows a scheduled-but-not-started session; and tdgrind's `config` overrides file has nothing left to express.

**Related:** design §6 run window / usage gate / PAUSE, §7 phase 3 (tdgrind migration — this is the step after it, or the shape the port should take), TD-010 (adopting hand-started sessions faces the same "who stops it" question), samscrape TD-274 (the tdgrind supervisor), samscrape `~/.tdgrind/config` dated overrides of 2026-09-01.

## TD-035: Adapters without a session-start hook still run dev-cadence's SessionStart set

**Priority:** Low
**Added:** 2026-09-12
**Owner:** grinder
**Kind:** build
**Status:** Open — **designed 2026-09-24 (the designer, PR #530):** the 2026-09-12 decision is written into design §4.3 *A repo's start hooks are every adapter's to run* (the tool's start hook, else the runner at launch with its stdout prepended to the first prompt; a hand-started session untouched; the anchor check's source for another tool decided with that adapter). The build is the second adapter's, whichever TD-112's spike picks; this entry is its checklist and archives with it. Was: design question; no second adapter exists yet **Next:** nothing to build until a second adapter exists (TD-112's spike); the rule is written.
**Blocked by:** TD-112
**Location:** `src/shiftlead/adapters/<tool>/` (a future Gemini CLI / Codex CLI adapter), `src/shiftlead/adapters/claude_code/__init__.py` (`CADENCE_HOOK_LINE`, the pattern to generalise), design §4.2, §4.3

**Why:** dev-cadence's per-repo conventions are tool-neutral in their rules and scripts (cadence.md, the ledger and board, `check_cadence.py`, `cadence_hooks.sh`, the pre-push hook, the review-evidence PR comment) but their *wiring* is Claude Code's: the runner line lives in `.claude/settings.json` and in this adapter's launch layer, the runner resolves the repo from `CLAUDE_PROJECT_DIR`, and `check_anchor.py` reads the live-session registry under `~/.claude/sessions`. A repo worked by another tool gets the rules and none of the delivery: no attention board at session start, no cadence-changes entry, no anchor warning. Decided 2026-09-12 (with Paul): tool-specific wiring belongs in the harness adapter, not in the repo and not with a per-repo agent — the repo does not know which tool will work it; the harness does.

**Fix:** (1) every adapter's launch runs `scripts/cadence_hooks.sh --session-start` for the session directory when the script is executable there: through the tool's own start hook where it has one (Gemini CLI hooks, design §4.3 table), otherwise by running the runner at launch with the hook payload it would have received and prepending its stdout to the first prompt — non-intrusive, nothing needed from the repo; (2) the runner takes the repo root from an argument or `PWD` as well as `CLAUDE_PROJECT_DIR` (dev-cadence change; it already falls back to `git rev-parse --show-toplevel`) — settled by design §4.3 and ADR 2026-10-08 (TD-159): the runner falls back to `pwd`, and nothing is owed to dev-cadence; (3) the anchor check needs an equivalent of the live-session registry for the other tool, or agentorc's own session records as the source when the session was launched by it — decide when the second adapter lands. Done when a session launched through a second adapter in a dev-cadence consumer prints the due-items line and the unseen cadence-changes entries at its start, and a hand-started session of that tool is untouched.

**Related:** design §4.2 (the launch layer carries the line, 2026-09-11), §4.3 (adapter contract, the hooks table), §4.8 (relay); dev-cadence cadence §3 (one SessionStart line; who makes the change, 2026-09-12); TD-028 (orchestrator brief).

## TD-052: Messages between sessions — build design §4.10

**Priority:** High
**Added:** 2026-09-14 (raised by Paul)
**Owner:** anchor
**Kind:** live-check #343
**Status:** Open — **the design landed first, as §4.10 (2026-09-14)**, with three rows in §4.5a, a sentence in §4.7, invariants 5 and 11 amended and invariant 13 added, and the §10 question answered; **extended 2026-09-16** with how a Claude Code session is told it has mail (the doorbell, the `Stop` hook, the line on every `ao` reply) and the lifecycle of an entry; **revised twice 2026-09-16** after a Fable review of all of §4.10 (thirteen changes, §10's entry of that date — among them the wake budget's refill rule, the person inbox, copies to other controllers, the `Stop`-hook block cut, and the build order below — then sixteen more from a second Fable review: the host agent decides mail wakes when a recipient is reachable, `wait` moves into the host agent, exact thread counting, pending asks on exit; **a fourth Fable review the same day** adopted ten more — open asks never pruned, the pair tally windowed, a non-wake leaves the watermark, repeats refused not dropped, `sends` recorded on the target for `conflict`, the controller's `send` charge dropped, the skill file displaces, a person's Message control, wall-clock ask bounds, person-inbox refusals name the board — and Sonnet review rounds followed, §10). **Step 1 landed 2026-09-17 (PR #163, Fable)**: `sessionorc.mail` holds both gates as functions over a record map (`act_gate` is the old `_gate` moved; `message_gate` reads the four edges) and the bound constants, every one a placeholder until step 6 (`None` = unlimited; each refusal path is built and tested by monkeypatching it); `MailEntry`, `Tally` and `SendEntry` on the record (`inbox`, `outbox`, `threads`, `sends`, `superseded_by`, `host`), with `view()` — what `list`, `get` and the push carry — dropping bodies for `unread` and `mail` marks; the `msg` and `inbox` RPCs; `sends` written by `send`/`keys` at the gate with the submit's verdict, and `ao status -v` printing the last three plus the unread count and marks; the tick's `_sweep_mail` (expiry, pending on exit, expired on close, retention); `_supersede` moving mail and rewriting ids; a same-nonce retry returning the first verdict. Two things the step text did not say, decided in the code and written into §4.10: the sender keeps its own copy of every entry (`outbox`) so the sender-side marks are on its record, and `ACTING_RPCS` moved to `mail.py` beside the gates (re-exported from `agent.py`). Two things left to later steps deliberately: `ao msg` / `ao inbox` as CLI commands and the person inbox (step 2 — a `to` of `person` is refused naming the board until then); the identical-repeat and per-sender damping (step 6, with the numbers). `tests/test_mail.py` carries the tests, one per rule. **Step 8 landed 2026-09-16 (PR #165, Opus)** for the four session-side rows of §4.5a — the Focus Inbox panel, the card's unread chip, Reply, and Message — plus an `inbox_delete` RPC (a person's only, one record's copy); the Org top bar's person inbox followed once step 2 had merged: **step 8 completed 2026-09-16 (PR #168, Opus)** — the top bar's count (rendered on the Org page, then polled from the `inbox` RPC: nothing pushed carries it), its panel with Reply and delete, and `inbox_delete` naming no session deleting from the person inbox; no Reply on an entry the person sent, by design — a person does not answer themselves, and the session's answer lands in the person inbox. **Step 2 landed 2026-09-16 (PR #166, Opus)**: `ao msg`, `ao inbox` (the fixed header, each entry marked controller / person / other) and the person inbox in `person_inbox.json` beside `sessions/`, with the mail rules in `ao --skill`; the top bar reads it with the `inbox` RPC given no caller and no `id`, and replies with `msg` given `reply_to` and no `to`. Decisions the step text did not make: the person inbox keeps no exchange tally — only the sending session's record counts, and `PERSON_INBOX_DEPTH` / `PERSON_SENDER_DEPTH` bound the rest (a sentence in §4.10); a session's `reply` to a person's message with no addressee lands in the person inbox, and a person may not write to it; its depths count unread entries, which — a person's read setting nothing — is every entry until a person-inbox delete exists (`inbox_delete` covered session inboxes only until PR #168 added the person inbox); every session sender shows as `[other]` there, since no session is the person's controller; `ao msg --reply-to <id> "…"` may omit the addressee and defaults `--kind` to `reply`; `ao inbox` at a terminal reads only the person inbox; and to hold 120 lines the skill's membership and verify-every-send paragraphs were tightened as well as the `ao wait` one. **Step 4 landed 2026-09-16 (PR #170, Opus)**, text only: the mail rules in `src/shiftlead/briefs/orchestrator.md`, `grinder.md`, `hunter.md`, `docs/briefs/orchestrator-ao-1.md` and `docs/briefs/tdgrind-ao-1.md` — a lead's round reads `ao inbox --unread` first and answers every `ask`; a grinder reads its inbox before claiming, notes its same-team siblings at claim and mails its lead at `done`; `ao msg person` for what is not yet a board item; the controllers-and-people rule once per brief; and an *unknown method* fallback to `ao progress` / `ao finding` for a host agent older than the build. The live leads' ticks still run on `loop` rather than ending in `ao wait` (TD-049 steps 5–6), and `ao wait` returns on mail only once step 3 lands; the briefs take effect on the next `ao team start`. **Step 3 landed 2026-09-16 (PR #171, Opus)**: `wait` is the host agent's RPC (`ao wait` a thin call, which says in one line and exits 1 against an agent that predates it), held on its own connection and cancelled when that connection closes; the wake decision is `_decide_wake`, the one function step 7's doorbell calls; `mail_decided`, `wakes` and `wake_refilled_at` are home-owned fields on the record; `WAKE_BUDGET` (None), `WAKE_WINDOW` and `WAKES_KEEP` sit in `mail.py`; every response to a session with unread mail carries `mail` in its envelope, and the CLI prints the line after every command that reached the agent. Decisions the step text did not make: mail's half of the per-caller cursor *is* the `mail_decided` watermark, so no mail is kept in the `waits/` file; a first wait wakes on no member's change but does decide unread mail already waiting; a wait returns mail as headers only (id, from, role, kind, about, at), so `read_at` stays `ao inbox`'s; `ao --json wait` prints `{changed, mail, wake}` rather than a bare list; a person's session blocked in `wait` is never returned by mail (invariant 5); a person's `keys` refills like a `send`, and a person's message refills its named addressees, not its copies; the watermark, `wakes` and the refill move with a resume; the unread line goes to stderr under `--json`, and a command that never reached the agent (`ao --skill`) prints none; a watermark whose entry has left the inbox falls back to its `at`, compared `>=` (a redundant wake, never a missed one). Step 5 reads each record's `wakes`: `cause: mail, charged: true` are mail-caused wakes, `cause: member, charged: false` the free ones, `covered` the entries each took in. The briefs' *once step 3 lands* caveat stays true until the live agent is restarted onto this code. Steps 5, 6 and 7 below stay open. **The workers building them run from briefs in `docs/briefs/archive/td052-step*.md`** (steps 2 and 8: PR #164; steps 3, 4 and the top-bar row 8b: PR #167 — both merged on a failing `ledger` row, which this sentence repairs: a brief names the step it builds, and the ledger is where that is recorded), one worker per step under orchestrator-ao-1, each step its own PR. Code steps below, each its own PR, in order **Found watching two live teams, 2026-09-17:** delivery, three of the four gate edges in use (upward, downward, team; no *shared target* yet), the pair tallies and the person's notes all behave as §4.10 says, but **no record has a single `wakes` entry**: both leads pace their rounds with the `loop` timer and never call `ao wait`, because the lead brief says only that `ao wait` *returns on new mail* and never tells the lead to block in it between rounds. So mail to a lead waits for its next 10-minute round, and step 5 has no wake data to measure. Before step 5 can produce numbers the lead brief needs the sentence (block in `ao wait --timeout <round>` between rounds), which takes effect at the next team start. **Done 2026-09-17 (PR #194):** the lead template and `docs/briefs/orchestrator-ao-1.md` end every round in `ao wait --timeout 540`, with the `loop` timer kept only as the fallback when `ao wait` itself fails, and a quiet round no longer costs a commit. Not seen live yet. **Step 6 landed 2026-09-18 (PR #214):** every placeholder set from step 5's measurement (eight hours of samscrape-grind, 2026-09-17), with the evidence and the rule *twice the measured traffic stays clear* written into §4.10 *The numbers*: thread 40, pair 300 per 24 h (`PAIR_BOUND`, split from the thread bound — one number could not serve both), mailbox 100 unread, person inbox 200 / 20 per sender, retention 12 h, wake budget 30 an hour. A thread's tally is pruned with its last entry, and the bookkeeping fields ride only a `get`. Step 5 is what it was — the records of any night's team. **Step 7 landed 2026-09-20 (PR #343, Opus, grinder-ao-1):** the doorbell — each tick, a hook-confirmed `idle` session with unread mail no wake has covered and an empty composer is rung with `sessionorc.mail.unread_line`, the one text the per-command line prints, as its own task; the ring is `_decide_wake` (`via: doorbell` on the wake), so the budget and *rung only for new mail* are the watermark's; one ring per idle stretch; a person's session, a pane with no `composer()`, a session blocked in `wait` and a wrap-up under way are skipped. *A wrap-up under way* gained `wrapup_at`, stamped by a `send` marked `wrapup` (Wrap up and `ao team stop`, the manager's wind-down) and cleared by the next plain send, because the host agent cannot tell the wrap-up prompt from another send by its text. A failed ring is retried once without a second charge and only into an empty composer, then written as `doorbell_failed`, which `ao status -v` prints. As built in design §4.10 after the doorbell's rules. **What is left of this entry:** the second-adapter step below (with TD-035) and the *Done when*'s live half — seen on the running system after a promote (docs/user_attention.md). **Next:** the second-adapter step waits on TD-112, the live half on a promote.
**Blocked by:** TD-112

**Location:** `src/sessionorc/models.py` (the `inbox` on the record), `src/sessionorc/agent.py` (`rpc_msg`, `rpc_inbox`, a new `rpc_wait` — `ao wait` today runs wholly in `src/shiftlead/cli.py` (`cmd_wait`, `wait_scope`, `wake_changes`) and moves here — the message gate beside `_gate`, `_supersede`), `src/sessionorc/store.py` (persistence with the record), `src/shiftlead/cli.py` (`ao msg`, `ao inbox`, `ao wait`), `src/shiftlead/ui/` (the Inbox panel, the unread chip, Reply), `src/shiftlead/skill.md`, design §4.10 / §4.5a / §4.7 / §9 invariants 5, 11, 13

**Why:** four kinds of session-to-session traffic exist — lead → worker, worker → lead, lead ↔ lead, worker ↔ worker — and one mechanism served all of them: `ao send`, the host agent typing keystrokes into a pane. Only the first works. A worker reaches upward through `progress` and `findings`, which are the wrong shape for it: declarations about references, addressed to nobody and delivered to nobody. They are ungated — any session may write any record's — but that is not a channel: writing onto another session's record states a fact about it rather than telling it anything, and nothing carries it to the session that must read it; two leads are peers, so TD-036's gate refuses them each other; two workers coordinate by side effects — a ledger row, a branch name, a PR that already claims the reference. Paul, 2026-09-14: *"we need to make sure agent to agent comms are first class in our design."* The cause is a conflation, not four missing features: the `control` grant (`orchestrate` until TD-055) + `controllers` answers *may A act on B?*, and messaging was folded into it because keystrokes were the only delivery there was — typing into a pane genuinely is an act of control. §4.10 splits the two. This entry builds it.

**Fix, in order — each step is usable on its own.** Reordered 2026-09-16 after the Fable review of §4.10: everything that types nothing comes first, a team runs on it, and the wake budget is set from what that team spent *before* the doorbell — the only part that types into a pane — is built.

1. **The record and the RPCs.** Built with TD-057 step 1's address choices from the start — `host` on the record, ids qualified on the way in, message ids, `at` and nonces minted by the host agent, the gates as functions over a record map — so a second host needs no migration. `inbox` on the session record (persisted and reloaded with it, dies when it is forgotten); the `msg` and `inbox` RPCs; the message gate as its own function beside `_gate`, refusing by naming §4.10's graph rather than invariant 11, with a test per edge — upward, downward, same `team` badge (invariant 9's named exception), shared controlled target — and per refusal. The interactive split is its own test: an acting RPC onto a person's session still refused, a message to it landing and never waking (invariant 5). Also in this step, because each is a field or a rule on the entry: `read_at` set only when `inbox` returns the entry to its caller (never by `wait`, never by a person's UI read); `text` capped; **threads** — a `reply` belongs to its root's thread whatever its `about`, messages replying to nothing count per pair, and the tally is a field on **both** participants' records, never recounted from surviving entries; the **automatic copy** of a controller's mail `about` a session to that session's other controllers, expanded into `to` at send time and **exempt** from the recipient cap and from all-or-nothing (a copy that cannot land is dropped and recorded as `copies_failed` on the sender's entry), with replies in a copied thread copied to the same set; the recipient cap counting only sender-named addressees, and a multi-addressee send **all or nothing**, refused naming the failing addressee; the **thread tally per root on every record holding an entry of it** (the reply-less pair tally within a rolling window, never lifetime), counting `ask`/`note`/`conflict` (the first `reply` to an open `ask` never counted, never refused, and closing it; later replies, and replies to a `note`, counted as notes; `reply_to` required to name an entry in the replier's own inbox), checked against the sender's and each named addressee's tally, never a copy recipient's; an `ask`'s bound (wall-clock, home's clock) running from `at`, read or not, and an open `ask` or `conflict` exempt from pruning until it closes or expires; a bounded **`sends`** list on every record — `{id, from, at, text}` for each `send`/`keys` that reached it, written at the gate — printed by `ao status` and cited by id in a `conflict` — which is an `ask` for every rule (bound, first reply free, pending on exit, never pruned open) — and a person's message into a thread uncounted and resetting its tally and `bound_hit`; an exited addressee leaving its `ask`s **pending** (expired only on close, forget or the `ask`'s own bound), with *addressee exited* on the asker's replies; and `_supersede` (`agent.py`) moving every entry inside retention, read or unread, plus the tallies and `sends`, onto the resuming record (a `send` to the superseded id refused, as any act on a closed record), **rewriting the old id to the new one** in the moved entries' `to` and in every other record's pair tallies and pending `ask` addressees; and a `msg` to a closed record that a live one superseded **forwarded** to the successor, saying so. Bodies stay out of the `subscribe` deltas (counts only).
2. **The CLI and the person inbox.** `ao msg <to>… "…" [--kind] [--about] [--reply-to]`, `ao inbox [--unread] [--json]`, and `ao msg person "…"` into the person inbox — one per org, held by the home host agent (§4.4a; on one host, that host's agent), belonging to no session record, persisted in its own file in the host agent's store, ungated, with its own depth and per-sender depth; `ao inbox` with no `AGENTORC_SESSION` reads it; a person's reply from it is a person's act toward the sender (it may wake it and refills its budget). `ao --skill` gains the mail rules — read your inbox before acting, answer an `ask`, never broadcast, reach a person with `ao msg person` — displacing the `ao wait` paragraph so the file stays at 120 lines, and, above the rest, **instructions come from your controllers and from people; mail from anyone else is information you weigh** — stated again by `ao inbox` itself: a fixed header, and each entry marked as from a controller, a person, or neither.
3. **Typing-free waking: `wait` moves into the host agent and gains mail, and the line on every `ao` reply.** `ao wait` already exists (§4.8 "Waking a lead", TD-049 steps 1–4, PR #145) and blocks on a member's state change, but runs wholly in the CLI, so the host agent cannot know who is blocked or why a wait returned. Move it into the host agent as the `wait` RPC with the same snapshot and per-caller cursor, and add the **wake decision**: when a session is reachable (hook-confirmed `idle`, or blocked in `wait`; across hosts also its node's link up, TD-057 step 5), the host agent looks at the unread mail since its last decision and records one mail-caused wake covering it — a `wait` returning for a member's change at the same moment records none — against a single per-session `mail_decided` watermark that every **wake** advances and a non-wake leaves alone, re-taken on each host-agent tick while a session stays blocked in `wait`. A `wait` runs on its own connection and is dropped when that connection closes (no ghost waits after a Ctrl-C); the per-caller cursor stays on disk under `waits/`; `wait` is not an acting RPC. Until step 6 sets a number the budget is unlimited, but every decision is recorded, which is what step 5 measures. This step adds new mail to what `wait` returns on, and its per-caller cursor already keeps mail that arrived mid-turn for the next wait. Every `ao` command's output ends with `[agentorc] you have N unread messages — run ao inbox` while the caller has unread mail, plus `(wake budget spent)` while it is. Neither types into a pane.
4. **The briefs**: a lead's round reads its inbox at the top; the grinder mails its lead when a reference is done instead of relying on the lead noticing, and, until 2026-09-20, sent a `note` to its sibling workers (the same-team edge) when it **claimed** one, which is what let two workers learn the other held a reference before duplicating it. That at-claim note was always a stopgap and is gone: TD-056's reference leases replaced it once the running host agent was seen refusing a second live session's claim by name.
5. **Run it and measure.** A lead and two grinders on steps 1–4 for a few evenings, recording per session the mail-caused wakes (`wait` returning on mail), **separately** the free wakes that carried mail alongside a member's change (the grinder marks `done` and mails its lead at once, so without this split leads would read as needing no budget), exchanges per thread, mailbox depth reached, and how long read entries stay useful.
6. **The bounds, with numbers from step 5**, written into §4.10 in the same PR with the evidence that would change them: the **wake budget** as mail-caused wakes per rolling window, refilled by time and in full by a person's **act** toward the session (a send, a reply, an answer — never opening Focus or reading), never by a controller's send or a non-mail turn; a controller's `send` never charged (the round-two charge was dropped in the fourth review as redundant with the wake charge); exhaustion visible on the record and to the sender; the mailbox depth, refusing with a reason the sender sees; the per-thread exchange bound and the pair window, past which the host agent **refuses the send** naming the bound and the thread and writes a `bound_hit` mark every participant's card and `ao` replies show (the sender writes any board line itself — the host agent never commits to a board here); an `ask`'s default bound and the *expired* mark on both cards and the asker's `ao` replies, including the gone-addressee case; the `text` cap; the delivery damping (identical-repeat window and per-sender rate, both refusing with a reason); the retention window and pruning, open asks exempt; the person inbox's depth, whose refusal names the board.
7. **The doorbell** (§4.10, 2026-09-16): (a) the fixed line — an unread count and nothing a sender wrote, with a test that a crafted `about` never reaches the pane; (b) submitted through `_submit` only on a hook-confirmed `idle` **with an empty composer**, coalesced per idle stretch, spending wake budget, and skipped for a person's session, a session with no `composer()`, a spent budget, a wrap-up under way or `out_of_work`; rung only when the unread count has risen since the last ring; retried once, then recorded. A session that has only declared `out_of_work` may be rung — only a wrap-up or wind-down under way beats mail. No `Stop`-hook block — cut in review; `Stop` stays fire-and-forget.
8. **The UI**: the Inbox panel on Focus beside Reports, the unread chip on the card, Reply, a person's **Message** control, and the person inbox in the Org top bar (§4.5a's five rows).

**Deliberately not in scope:** any broadcast, channel or room; mail as a durable record (the ledger and the board keep that job — invariant 13); and messaging across hosts, which design §4.4a routes through the home host agent and TD-057 builds.

**A further step, only when a second adapter exists:** `mail` on the adapter contract (§4.3) — how a session of a given tool is handed entries and woken by them. Claude Code's answer is `ao inbox` and `ao wait`, which is why steps 1–8 can be built without it; the contract entry earns its keep the moment a tool with no shell, or one whose turns a harness composes, gets an adapter. Until then the honest statement is the one §4.10 makes: an adapter with no native path falls back to a pane write, which is a `send`, and the message/control line is that adapter's convention rather than the host agent's gate. Sequenced with TD-035, which is not itself the work of building a second adapter but the design question that second adapter forces — dev-cadence's SessionStart wiring is Claude Code's — and this step is the same question asked of mail: both are answered by the adapter, and neither can be answered before one exists.

**Done when** a worker tells its lead it finished without the lead polling, and an idle worker is rung for a message with nothing its sender wrote typed into its pane; a worker reaches its person through the person inbox; two leads over one worker settle a contradiction between themselves and land a board line when they cannot; a message to a person's session is delivered where a send is refused; every refusal names §4.10's graph; a session out of wake budget receives mail that lands without waking it, visibly to itself and to the sender; and a person's session is never woken by mail at all.

**Related:** design §4.10 (the whole section), §4.5a, §4.7, §9 invariants 5, 11 and 13, §10 (the 2026-09-14 entry, and the 2026-09-13 one it answers); TD-039 (the conflict half — a `conflict` message and its exchange, which step 6 bounds), TD-049 (the wake, absorbed by step 3), TD-036 (the graph the gate reads), TD-028 (the report channels the Inbox sits beside and deliberately is not).

## TD-060: The name `agentorc` is taken — rename the project

**Priority:** Medium
**Added:** 2026-09-16 (Paul; discussed in samscrape session 746e1973 on kmaster)
**Owner:** anchor
**Kind:** build
**Status:** **Read 2026-10-12 (the anchor):** TD-552 is archived (#1520); what is left is TD-553, now this entry's `Blocked by`, so it leaves the anchor's pickable list until TD-553 is done. **Split 2026-10-11 (the anchor, Paul's word):** what is left is no longer Paul's and no longer here — the rest of (b), the text sweep, is **TD-552** (a grinder's); (c)'s last step, the fallback dropped, is **TD-553**, blocked by each repo's rename: samscrape's `.agentorc.yml` → `.shiftlead.yml` by the anchor the same day (samscrape #1077), contractmatch's in its own ledger (TD-055, with its briefs, `CLAUDE.md` and memory), dev-cadence's in its own (TD-091, with (d), the synced files, and a sync; its TD-089 holds the `eyecantell/dev-cadence` headers). **The dev venvs were rebuilt the same day** (Paul's word): `~/shiftlead` and the 22 worktrees whose `.pdm-python` named `/home/kmaster/agentorc`, `rm -rf .venv .pdm-python && pdm sync -G ui -G dev` in each; `pdm run pytest` passes in the checkout and `grinder-ao-1`. This entry archives when TD-552 and TD-553 are done. **(b) the live briefs swept 2026-10-11 (the anchor, Paul's word, before ao-grind's restart):** nine of the ten under `docs/briefs/` outside `archive/` (`techlead-context.md` had none) name `~/shiftlead`, `src/shiftlead/`, `shiftlead-venv`, `~/.shiftlead`, `SHIFTLEAD_HOME`, the `shiftlead-*` units, `.shiftlead.yml` and `repos/ShiftLead/shiftlead` — the Playwright interpreter and grinder-ao-2's lane named paths that no longer exist; `docs/briefs/archive/` stays as written. **Found then, left for Paul's press:** the dev venvs did not move with the checkout — `~/shiftlead/.pdm-python`, the main `.venv`'s `.pth` and script shebangs, and each worktree's `.venv`/`.pdm-python` name `/home/kmaster/agentorc/…`, so `pdm run test` fails in the checkout and every worktree until each is rebuilt (`rm -rf .venv .pdm-python && pdm sync -G ui -G dev`). **(e) the repo renamed 2026-10-11 (the anchor, Paul's word; no session running):** GitHub `eyecantell/agentorc` → `eyecantell/shiftlead`, then transferred to the `ShiftLead` org the same day (Paul's word) — `ShiftLead/shiftlead`, both old URLs redirect; the checkout moved `~/agentorc` → `~/shiftlead`, with a symlink left at the old path for the session that moved it (`rm ~/agentorc` once that session is closed), `git worktree repair` over the 30 worktrees and `origin` set to `https://github.com/ShiftLead/shiftlead.git`; `org.yml`'s project and `settings.yml`'s `repos:` key renamed `shiftlead` (backups `*.bak-2026-10-11-repo-rename`), `promotes/agentorc` moved to `promotes/shiftlead`, dev-cadence's `repos.txt` and `consumers.txt`, each checkout's `autoMemoryDirectory`, and `~/.claude/projects/-home-kmaster-agentorc*` moved to `-home-kmaster-shiftlead*` with links back, so a past session resumes from the new path. Read after: `ao team list` — ao-grind on project `shiftlead`, its seats `ao-shiftlead-…`; `ao promote` names the repo `shiftlead`; `ao doctor hooks --probe default` — SessionStart in 1.9 s. A closed session's `ao-agentorc-…` records stay as they are. **(a) the cutover done 2026-10-11 (the anchor, Paul's word and root press; no session running):** `ao host forget contractmatch` (there is no `host down`; it drops the `nodes:` entry, put back by hand), the new venv, `ao migrate`, `sudo … --system`, `ao service install`, node up. Read after: `ao doctor` — tmux under `shiftlead-tmux`, the watch timer, every profile, node contractmatch linked at the home's build; `ao team list` reads all four teams (three through the `.agentorc.yml` fallback); `ao doctor hooks --probe default` — SessionStart in 1.7 s; the old venv removed. **What the runbook missed, for the next machine:** `~/.local/bin`'s `ao`/`agentorc*` links still pointed into the old venv (repointed by hand to `shiftlead-venv`); the home agent started before the `nodes:` entry was back, so it opened no link socket for the node until `ao service install` again; and its supervisor raced the hand `ao host up` into a second container (removed). **Step 2 merged 2026-10-11 (#1505; #1511 renamed two build-chip tests that merged beside it). Built 2026-10-10 (the anchor, branch `td060-rename`; Paul, that evening, with every session closed after the tmux move):** the decisions — `agentorc` → `shiftlead` for the distribution, the product package, the console scripts (`shiftlead`, `shiftlead-agent`, `-hook`, `-ui`, `-watch`; `ao` stays), the entry-point group, `~/.shiftlead`, the `SHIFTLEAD_*` variables, the four units and `~/.local/share/shiftlead-venv`; `sessionorc` **kept**; a **clean cut** with a one-time `ao migrate`; a repo's `.agentorc.yml` **read as a fallback** (`sessionorc.paths.repo_file`) until each repo renames its own by PR. The `ao-` prefix stays. **Left, in order:** (a) the cutover, with no session running and both units stopped — `ao host down contractmatch`; a new venv (`virtualenv -p python3.13 ~/.local/share/shiftlead-venv`, `pip install '/home/kmaster/agentorc[ui]'` at the merged main); the checkout on a clean, current `main`; `shiftlead-venv/bin/ao migrate`; `sudo …/shiftlead-venv/bin/ao service install --system` (Paul's root press, before the user units: it removes `agentorc-tmux`/`agentorc-watch` and starts the new tmux server); `shiftlead-venv/bin/ao service install`; `ao host up contractmatch`; the old venv removed; (b) the text sweep the PR left: `docs/briefs/**` (held paths), `docs/mockups/`, `docs/cadence*` notes, the memories' live pointers — dated records stay as written; (c) each repo's `.agentorc.yml` → `.shiftlead.yml` (agentorc, samscrape, contractmatch, dev-cadence), then the fallback dropped; (d) dev-cadence's synced files that name `agentorc` (`scripts/cadence_hooks.sh`, `docs/cadence.md`), and a sync; (e) **the repo renamed `shiftlead` too (Paul, 2026-10-10)** — GitHub redirects the old name; the checkout's directory, and with it every `ao-agentorc-…` session id, the `agentorc` project in `org.yml` and the Claude transcript paths, is its own quiet window. Before: **Paul, 2026-10-07:** snoozed to 2026-10-21. **Owner paul since 2026-10-06 (the anchor):** nothing in it is a member's to pick. Step 2 waits for the release boundary Paul picks. Open — **Paul, 2026-10-04: the anchor picks the quiet window for step 2 and runs it** (no team running, both units stopped). **decided by Paul 2026-09-22: go with the rename to `shiftlead`** (his words: *go with the rename to shiftlead, we will have to figure out when to rename the repo*). **Step 1 is done:** its remaining half, the visible name — the UI wordmark in `base.html` (*Shift**Lead***), every page's `<title>` (*Org · ShiftLead*) and the mockups' wordmark — landed 2026-09-22 (grinder-ao-2). **Step 2, the machine names** (`~/.agentorc`, the seven env vars, the units, the venv, `.agentorc.yml`, the `agentorc-hook` entry point, with the migration and its test), waits for a release boundary with no team running and both units stopped, as *Fix* says, and the anchor runs it. **When the GitHub repo is renamed is Paul's, and open** (board line, 2026-09-22): it can follow step 2 or go first, since GitHub redirects the old name. Was: awaiting Paul's decision on the name. `shiftlead` is the leading candidate (free on PyPI, npm, crates.io and as a GitHub org when checked 2026-09-16; `.dev`/`.org`/`.tech` open per Paul); Paul asked for time to think. Nothing is renamed. **Both names were claimed 2026-09-17 ahead of the decision:** PyPI `shiftlead 0.0.0` (empty placeholder) and the GitHub org `ShiftLead`; the domains are not registered. The candidates, the test they were held to, the measured surface and the six decisions are in [ADR 2026-09-16](decisions/2026-09-16-rename.md). Worktree `agentorc_rename` exists with no commits. **Next:** step 2 waits for the release boundary Paul picks.
**Blocked by:** TD-553

**Location:** the whole repo — 1,110 case-insensitive occurrences of `agentorc` in 93 tracked files and 260 of `sessionorc` in 56 (`origin/main` at `8bd21b9`) — plus what lives outside it: `~/.agentorc/`, seven `AGENTORC_*` environment variables (the six below plus `AGENTORC_BUILD`, added since this was measured), `agentorc-agent.service` / `agentorc-ui.service`, `~/.local/share/agentorc-venv`, `.agentorc.yml` in other repos, the `ao-` session-id prefix, and three synced files in dev-cadence (and so in samscrape and contractmatch).

**Why:** another project holds the name (TD-059 is to identify it). This is the second rename (`sessionherd` → `agentorc`, 2026-09-04, chosen to sit beside `cmdorc`), and it is cheaper now than it will ever be again: one user, nothing published to PyPI, no external adapter known. Every week adds briefs, ADRs and session records that carry the old name.

**Fix:** decide the six questions in the ADR (the name; what happens to `sessionorc`; whether the `ao-` id prefix stays as an opaque historical prefix — recommended; whether `ao` survives as an alias; a compatibility window or a clean cut with a `migrate` command; whether to claim the names before deciding). Then, in order: claim PyPI + the GitHub org; land TD-055 first, since it edits many of the same lines; one PR for packages, entry points, env vars, state dir, units and config file name, with the migration and a test for it; the text sweep, **leaving dated records — ADRs, the ledger archive, memories — as written**; dev-cadence's three synced files and a sync; the repo rename and a README tagline drawn from TD-059. **Land the machine-facing step with no team running and both units stopped:** running sessions hold `AGENTORC_SESSION` in their environment and resolve `agentorc-hook` from the unit's PATH, so a rename under a live team breaks every started session's hooks.

**See TD-076 before deciding (2026-09-20):** on 2026-09-19 Paul decided the coordinating role becomes `manager`, the go-between `techlead`, and bare `lead` is retired — which weakens the *shift lead is the job* argument for `shiftlead` and should be weighed in the same sitting.

**2026-09-21, Paul: the spelling is `ShiftLead`, `shiftlead.dev` is bought (Cloudflare), and the command stays `ao`** — short, in every brief and every worker's habit, and `sl` is a joke command on many Linux boxes; `shiftlead` may be a long-form alias. **The order confirmed by Paul 2026-09-21** (*that order works*) — **step 1 begun the same evening: the README's and the design's titles and the glossary say ShiftLead (this PR); the wordmark in `base.html` and the page `<title>` are a worker's, one line each; step 2 waits for a release boundary.** As suggested: **the visible name first** (the UI wordmark, the README, the design's title and this ledger's head — one PR, cheap, the page half a worker's) and **the machine names at a release boundary** (`~/.agentorc`, the seven env vars, the units, the venv, `.agentorc.yml`, with the migration and its test) with no team running, as *Fix* says. **Decided by Paul, 2026-09-20: the project keeps `shiftlead`** — with the roles `manager` and `techlead` (TD-076) — so the name stands for what the product is for, not for a role in it; the ADR's *the metaphor is the job* paragraph is to be reworded when the rename is carried out. What remains of this entry is the carrying out.

**Done when** the installed distribution, both units, the state directory and the README carry the new name; a session started before the rename is either migrated or documented as needing a restart; `git grep -i agentorc` returns only dated records and the "was `agentorc`" lines; and the three dev-cadence files are synced.

**Related:** TD-059 (the neighbours the name search found; its survey supplies the tagline), TD-055 (the glossary rename — `lead` is already the decided word, which is much of why `shiftlead` fits), design §4.1 (session ids), §4.3 (the two packages). **README positioning (TD-059, 2026-09-20):** the first-screen sentence drawn from the neighbours survey is in [ADR 2026-09-20](decisions/2026-09-20-session-desk-neighbours.md) (c); it goes in with the rename.

## TD-071: Org page review, 2026-09-18 — what was built, and the ideas that were not

**Priority:** Low
**Added:** 2026-09-18 (the anchor session; Paul's review of the Org page)
**Owner:** paul
**Kind:** build
**Status:** **Paul, 2026-10-07:** snoozed to 2026-10-14. Open — **items 1 and 2 built 2026-09-23 (PR #499, grinder-ao-1); item 8 is Paul's canvas.** Was: **items 1 and 2 designed 2026-09-23 (the anchor): §4.5a rows *team card: Forget all* and *team header ✉ n*; build them as the rows say, one page PR each or together (`src/shiftlead/ui/`: `group_head.html`, `org.html`, `app.js`); item 8 is Paul's canvas.** Forget all is n Forgets behind one confirm, skipping and naming every card with the dirty / unpushed flag (not refusing the team on one flag — the per-card Forget refuses nothing but a suspended record, `rpc_remove`); the unread sum on a folded header is display only, the mail staying under §4.10. Item 2's open question is answered by the code: a start under the same name moves the old record's mail to the new session (`_supersede`, TD-081), so an unread note outlives the run and lands in the next one's inbox — by design, and now visible on the fold. Was: **items 1 and 2 approved by Paul 2026-09-23: the anchor writes their two §4.5a rows in one design PR, then a grinder builds; item 8 stays Paul's canvas.** Was: a list to pick from, none approved; **items 3, 4 and 5 are settled by TD-095's card (2026-09-21)**, **6 and 7 by the mockups catching up (2026-09-22, grinder-ao-2)**, below. Left: 1 and 2 (each a §4.5a row first — the anchor's design), 8 (Paul's canvas). Built in the same PR as this entry: a team with nothing live keeps its card (Start on it, its dead cards folded, below the live teams and *No team*), the **Teams** strip retired, state glyphs on every pill, *Person inbox* → **Inbox**. **Next:** what is left is item 8, Paul's canvas.
**Location:** `src/shiftlead/ui/` (templates, `app.js`, `app.css`)

**Why:** on 2026-09-18 the page was seven cards, six of them dead, under a strip of three stopped teams: nothing on it said which dead card was whose, and what was running was one card among them. The review fixed the grouping; these are what it turned up beside it, kept here so they are not lost with the conversation.

**Ideas, cheapest first:**
1. ~~**Forget all** on a stopped team's card~~ — **built 2026-09-23 (PR #499)**, as design §4.5a *team card: Forget all* says: — seven exited cards is seven Forget clicks today. A team-level control: §4.5a row first. It should refuse while any of the team's sessions is not ready to close (unpushed work, as `orchestrator-ao-1`'s *305 unpushed* flag showed on 2026-09-18).
2. ~~**Unread mail on a folded team**~~ — **built 2026-09-23 (PR #499)**, as design §4.5a *team header ✉ n* says: — the header of a folded team says nothing about its sessions' unread counts (`tdgrind-1` held 19 on 2026-09-18). A `✉ n` beside the fold count. Unread mail on an exited session is by design as far as it goes: an unread entry never ages out (§4.10), and a *resumed* conversation takes the old record's mail with it (`agent.py`, `_supersede` → `_move_mail`). **Not verified:** what a fresh `ao team start` under the same name does with the dead record's inbox. Most of those 19 were claim notes, stale within the hour — worth deciding whether an unread `note` should outlive the run it was sent to (§4.10).
3. ~~**A roll-up on a live team's header**~~ — **built by TD-095 (2026-09-21, PR #389)**: the header reads `host / repo · 2 working · 1 unseen · 1 idle`, counts in the grid's order, *needs you* its ringed mark. In words, not glyphs — the counts sit beside pills that already carry the glyphs.
4. ~~**Exited cards carry less**~~ — **decided otherwise by TD-095** (design §4.5 *The card's anatomy*, Paul 2026-09-21): every card is the same six rows at one height, a dead one included, so a page of cards reads as a grid; what a dead card does carry less of is controls — its foot leads with Forget (PR #384), and a stopped team folds its dead cards away (2026-09-18).
5. ~~**The mode badge**~~ — **built by TD-095 (2026-09-21, PRs #384 and #391)**: *unattended* is a plain quiet word, *interactive* carries the `person` mark at full strength (reserved for it), the toggle moved into *more*, and the Org filter gained *mine*.
6. ~~**The legend**~~ — **built 2026-09-22 (mockups)**: the Org artboard's note gives the sort order as the state pills themselves, glyph and word, and every mockup pill that is a state carries the page's glyph (a due date or a report's status, marked `plain`, does not).

7. ~~**The mockups are behind the page**~~ — **done 2026-09-22**: the Teams strip is gone from `gen.py`; a stopped team is its own card below *No team* — `ao-grind` *wound down 6h ago* with its sessions folded, `cadence-sweep` a definition no session carries — each with **Start**; the pinned control was already gone (TD-095). As first written: `docs/mockups/gen.py` and the generated `Main.dc.html` / `MainDark.dc.html` still draw the Urgent first / Pinned control and the Teams strip, both retired 2026-09-18 (review of PR #229). Regenerate them with the look-and-feel pass rather than twice.

8. **The look-and-feel pass (Paul, 2026-09-18), in progress on a design canvas** — https://claude.ai/artifact/K1y8Nzy3PJnTCecBVANj8y (private to Paul): the Org page, the Inbox page (TD-069) and the state-icon vocabulary, round 1 dark. Constraints Paul has set so far, which bind whatever is built from it: **a state icon must not look like something to press** — the pause bars and the stop square read as buttons, and the glyphs shipped in PR #226 have the same fault (`‖` idle, `■` exited, and `▶` working is a play button by the same reading, all in `app.css`), so they change with this pass (canvas round 2: a prompt caret for idle, a dashed outline for exited, a pulse line for working); **nothing on a page is a control that parses what an agent printed** — Allow / Deny stay the `PermissionRequest` hook's answer channel (§4.2) and nothing else gets buttons from screen text; **the usage chip says what its numbers are** (`grind 19%·49%` is the profile's 5-hour and weekly windows, and reads as nothing); **a light theme is required, later** — so colours land as tokens (`app.css` already defines them on `:root`, with `html[data-theme="dark"]` overriding), never as literals in templates.

**Done when** each idea is either built (its own PR, §4.5a first) or struck here.

**Related:** design §4.5a (**team groups**, **state icon**), TD-069, TD-070, TD-065 (the undefined `chip` class — same page, same kind of finding).

## TD-112: The adapter contract has grown Claude-shaped and neutrality is untested

**Priority:** Medium
**Added:** 2026-09-22 (the anchor session; the design review)
**Owner:** anchor
**Kind:** evaluation
**Status:** **Paul, 2026-10-10 (with ao-paul): agreed, a spike, and integration tests with it.** Run as an interactive session, not a member's lane: a second tool must be installed and signed in (neither `codex` nor `gemini` is on kmaster on 2026-10-10; the sign-in is Paul's account or key), the work is judgement (which of the contract's methods are neutral), and its result is an ADR, not a merge. **Paul, 2026-10-13 (the lessons ADR, `docs/decisions/2026-10-13-agent-product-lessons.md` lesson 10):** Gemini CLI is *"a definite fit"*, so it is the spike's tool; Hermes Agent, Muse Code and Grok Bot are not wanted as tools for now. The lasting product is an **adapter conformance suite**: one set of tests every adapter passes against its real tool (launch, the state it reports, `send`, `composer()`, the doorbell and mail, `title()`), so neutrality is checked on every change and not once by the spike. The spike says which of those a scraped adapter can pass and which belong to Claude Code alone. Open — for evaluation. The design's stated moat is one neutral view across tools, and only one agent adapter exists. Since phase 1 the contract (§4.3) gained `composer()`, `title()`, `mail()`, a session id chosen at launch, the doorbell, the trust pre-seed and screen rules, each shaped by Claude Code. Phase 5 puts the second adapter last. Recommendation: a scraped spike now — Codex CLI or Gemini CLI, `state_source: scraped`, no hooks — to see which of the contract's methods are really neutral, what `send` and the doorbell do without a readable composer, and whether the record's fields assume a tool session id. The spike is a branch and an ADR, not a shipped adapter. **Next:** for evaluation, not scheduled.
**Location:** design §4.3, §7 phase 5, `src/shiftlead/adapters/`

**Why:** every Claude-shaped feature built before a second adapter exists is a feature that may have to be unbuilt, and the claim the product is sold on has not been tested.

**Related:** TD-015 (the classifier), TD-052 (mail's adapter step), design §4.3.

## TD-131: Mail, the board and the records are JSON and Markdown files read whole: fine at today's size, and no answer to search over history, counts per filter, or a retention longer than twelve hours

**Priority:** Low
**Added:** 2026-09-24 (Paul: *all this begs the question — do we need a db (with indexing) at some point?*; the anchor session)
**Owner:** paul
**Kind:** decision
**Status:** **Paul, 2026-10-07:** stays parked until its trigger. Open — **the anchor's answer 2026-09-24: not yet, and the trigger is written down.** What holds the data today: the person inbox is one JSON file (`~/.agentorc/person_inbox.json`, 39 entries and 46 KB on 2026-09-24), and a session's inbox is a field of its record, which is one JSON file per session under `sessions/` (`sessionorc/store.py`), both home-owned and read whole on every poll; closed entries are pruned after `MAIL_RETENTION` (12 h); the board is `docs/user_attention.md`, read by dev-cadence's script. At these sizes a read-and-filter in Python is under a millisecond and the page's filter runs in the browser over the rows it has; an index would buy nothing. **What would change the answer** — any one of: (1) mail kept past retention so a person can search history (*what did the techlead say about #517 last week*); (2) counts per filter across every team and host (TD-129's rail) on an inbox of thousands rather than dozens; (3) threads and outcomes joined across many sessions at once (mail stays home-owned across hosts — §4.4a: a node's replicas hold no mail — so this is a size question, not a placement one); (4) a second reader of the same data outside the host agent's process. **The step when one arrives is SQLite**, in the standard library, one file under `~/.agentorc/`, with FTS5 for the text search, written and read only by the host agent as the JSON is today — not a server, not a second process, and nothing a container node needs installed. The stores already sit behind one module each (`sessionorc/mail.py`, the record store in `sessionorc/agent.py`), so the change is local to them and the RPCs and the page do not move. What is not on the table: a database as the source of truth for the design's home-owned facts — those stay files a person can read and back up (`BACKUP_MEMBERS`). **Next:** a decision, and not yet: the trigger is below.

**Location:** `src/sessionorc/mail.py` (the store, `MAIL_RETENTION`), `src/sessionorc/store.py` (one record file per session, its `inbox` a field), `src/sessionorc/agent.py` (`BACKUP_MEMBERS`), `src/shiftlead/ui/app.py` (the filter's `data-find`), design §4.4 (the home), §4.4a (nodes), §4.10 (mail)

**Why:** the question is right and early; answering it now, with the trigger named, means the next person to feel the need knows what was decided and why.

**Related:** TD-129 (the rail's counts, the text search), TD-127 (what a row shows), TD-125 (retention and the FYI), TD-057 (nodes and where mail lives).

## TD-133: Build the team start at the reset — `schedules:` in `settings.yml`, the tick's replay, `ao schedule`, the card's *starts* note

**Priority:** Low
**Type:** feature
**Added:** 2026-09-24 (the designer; TD-026's design round, PR #526)
**Owner:** grinder
**Kind:** build
**Status:** **Paul, 2026-10-07:** snoozed to 2026-10-21. Open — designed, nothing built. Design: §6 *Schedule*, §5 `settings.yml` (`teams.<team>.schedule` since 2026-09-25 — the key moved under the team with the Settings page's design, TD-100 (4); the page's Teams card sets it once built), §4.7 `ao schedule`, §4.5a *team card: starts note*, glossary *schedule*. **Next:** Paul's word first: *not vital, not scheduled* (2026-09-22); ask m-32d769985798 offers to schedule it.
**Blocked by:** decision (Paul) — snoozed to 2026-10-21 (Paul, 2026-10-07); ask m-32d769985798

**Location:** `src/sessionorc/settings.py` (the second key and its validation), `src/sessionorc/agent.py` (the tick's pass beside `_keep_running`: the reset instant from the account's usage reading, the replay with `why: schedule`, `set_settings` taking the key), `src/shiftlead/cli.py` (`ao schedule`), `src/shiftlead/ui/app.py` and the team card template (the *starts* note), `tests/`.

**Why:** the ao-grind team winds down when its lane empties and is started again by a person's hand the next day, and the designer now refills the lane overnight; a start at the weekly reset closes that loop without the host agent reading `org.yml` or inventing a team. Paul decided the shape on 2026-09-22 and called it not vital; this entry is the build, waiting for his word.

**Fix:** three slices, the first two in `src/sessionorc/**` (the techlead reads them, §4.9b).
1. **The key and the pass**: `schedules: {<team>: {start: reset, profile, window}}` parsed with the reserves (a bad entry logged and skipped, never fatal); each tick, for each rule, the instant is the named window's `resets` in that profile's account reading (§4.2a; no reading, no fire); when the instant passes — once per reset, remembered on the home as `schedules_fired: {<team>: <resets>}` so a restart of the agent does not fire twice — every record badged with the team that is `exited`/`closed` by the team's own ending (`out_of_work` set, or a manager's own close after a wind-down), not suspended, not at a ceiling, is replayed from its launch record as rule 2 replays, `why: schedule`, under `RESTART_CEILING`, a seat written held as rule 8's start writes it (§6 rule 3, TD-654; TD-660 builds the held replay in `_replay`); a team with anything live is skipped; no launch records → nothing, logged once. `set_settings` accepts the key; a session's call is refused as today.
2. **`ao schedule`**: the listing with the next instant, `<team> reset --profile --window`, `<team> off`; the client refuses an undefined team (org.yml and the repos' `teams:`) and a label no adapter of the profile reports.
3. **The card**: the *starts* note on a team card with nothing live, from the rule and the reading, by the *stops* formatter.

**Done when** ao-grind, wound down on a Wednesday night with `ao schedule ao-grind reset --profile grind --window week` set, is running again within one tick of Thursday's reset with the manager, both grinders, the designer and the seats as they were last started, each card's `restarts` carrying `why: schedule`; the same team live at the reset is untouched; the team card read *wound down 6 h · starts at the reset · Thu 07:00* before and shows the sessions after; a session's `ao schedule … reset` is refused; TD-026 is closed or re-scoped by Paul's answer.

**Related:** TD-026 (the design and the open scope question), TD-103 (the launch record and the replay this reuses), TD-100 (`settings.yml`, the settings page that would also set this), TD-122 (the account's `resets`), TD-101 (the override shape that stays not wanted).

## TD-156: UI review of the end of a session: after a person's Wrap up, Focus offers Kill in the header and Close only in the side panel, and a concluded team folds the card that is ready to close

**Priority:** Medium
**Added:** 2026-09-25 (raised by Paul: he wrapped up the resumed designer and could not find a Close)
**Owner:** paul
**Kind:** design-first

**Why:** the end of a session is the one moment the person must act (only the person closes it, §2), and the screen they are on when the moment comes does not show them the act: Focus leads with Kill, Close is below the fold, and a concluded team hides the card. A session left open costs nothing in tokens but stays live, holds its worktree and its name, and is one more thing the team's next Start has to close first.

**Status:** **Paul, 2026-10-07:** snoozed to 2026-10-14. **Designed and built 2026-09-25**, in a cloud session with Paul, from his screenshot of the designer's Focus (the header over three lines, buttons on two of them, *unattended* where *Take over* should read) and his ask: *simplify the screen, hide the rarely used info under something expandable, and fix the button layout*. The design is §4.5 *The Focus screen's anatomy* and *What Wrap up promises*, and the §4.5a rows **Close session**, **more ▾**, Wrap up, Kill, Copy / Paste, the side panel, grants, controllers and **team groups**; the mockups are `Focus`, `FocusOrc` and the new `FocusReady` artboards, and the Org artboard's fold. What each question got: **Next:** Paul's interactive UI review, likely a cloud session (board line, due 2026-09-30); the design changes it yields go to the designer or a grinder afterwards.

- (a) **Focus after a wrap-up**: yes — the header is two lines, and the acts line's first button is the next act by the card's rule: **Close session**, outlined, the moment Ready to close passes on an `idle` or `exited` session, with ***ready to close ✓*** on the identity line in the card's words; Take over is the next act on an unattended session otherwise; Kill went into **more ▾**, last and red, with Pop out, Copy, Paste, Hand back and Copy tmux command. Message, Wrap up, Open shell here and the editor button stay plain on the acts line. The grants and controllers chips left the header for the Session card.
- (b) **a concluded team's fold**: a concluded team **never folds** — only a team with nothing live does (`live`, not `stopped`, is what the fold keys on) — and every team header counts *n ready to close* beside its states.
- (c) **what Wrap up promises**: the button's hover and the press's toast read *asks it to finish, push and report — the same prompt the policy sends; you close it when Ready to close passes*. The rule that a person's Wrap up is only the prompt stands.
- (d) **Kill's place**: behind more ▾ whatever the state, as on the card; Close is the act when the checklist passes, Kill one menu away for a worktree that must be kept.
- (e) the mockups: regenerated; `FocusReady.dc.html` is the after-wrap-up case.
- (f) the fold control: beside Start, *▸ n sessions* / *▾ n sessions*.
- (g) **two cards named designer-ao-1**: **not reproduced** — no live Org in a cloud session. The client's swap is by id (`old.replaceWith(fresh)`), so two elements need two inserts of one id; the events handler now drops any second element with a card's id after a delta as a guard. **Paul, 2026-09-25: the doubled card is handled under its own TD**, so it leaves this entry's live look.
- Fixed beside it: the header's mode button read *unattended* instead of *Take over* — a card-era line rewrote every mode button's text to the bare mode word after `mode_act` had been set.
- Every side card is a fold remembered per browser; Session starts folded, its summary the profile; the stops control sits on the identity line only while a stop time is set, and in the Session card as *none — set* otherwise.
- **Paul's second round, the same afternoon** (§4.5 *Whose session it is*): the identity line is the **name alone** (no host / repo, the tool's title only when it differs — the designer's read *designer-ao-1* twice); what the session says it is doing left the header for a **Working** card at the top of the side panel, beside Reports (*we already have a Reports card for finished work*); **Close session** and *ready to close ✓* are drawn only on the person's **own** session — interactive, or no team badge — since *I would expect the team members to run themselves and I would be responsible for interactive sessions I started*; a team member's Ready to close is **folded** by default and its note says its team closes it, its Close being the more ▾ entry; and **no team-level close** for the finished ones — the anchor's *Close finished* proposal was declined.

**Reviewed by Sonnet, four rounds in the cloud session (2026-09-25), READY at round 3 and confirmed at round 4.** Taken: the card's Close session gated on *own* like Focus's (round 1); the Forget all row's stale fold label, a member's checklist losing its small Close so more ▾ is the one place (round 2); the stops row as the Session card's control set or not, Forget all into the team header's right-hand cluster with Start and the fold, the first-paint outline following *own* (round 3); the stops row's old sentence on Focus's empty state (round 4). Overruled: "the branch deletes shipped sections" (a two-dot diff against a moved main; main was merged in instead) and "the header's *n ready to close* should count exited sessions" (an exited session's act is Forget, not Close — the row now says *idle*).

**Left for Paul's live look (board line):** the two lines at 1440 and 1280; Close session appearing on a wrapped-up own session without a reload; the fold beside Start; a concluded team's cards in view with *1 ready to close* in its header.

**What happened, as the seed for the review**, 2026-09-25 15:15Z on the designer resumed by Paul (TD-155's record):

1. Paul pressed **Wrap up** on Focus. The session declared *out of work* (`ao progress none`, the wrap-up's words), the record reads `idle` with every Ready-to-close check passing (*tree clean*, *branch pushed*, *no subagents running*, *outcomes reported*). Nothing closes it: a person's Wrap up is only the prompt (§4.5a *Focus: Wrap up*); the policy's `run_until` path is what kills after a wrap-up, and it applies to a stop time, never a press (`_enforce_stop_times`). *Closing is your act; the checklist only says when it is ready* (the side panel's own note). That is the design (§2, goal *only the person closes it*) and this entry does not question it.
2. On **Focus** the header reads *Pop out · Open shell here · VS Code · Copy · Paste · Message · Wrap up · ✕ Kill* — Kill in red as the only stop in sight. **Close** is a small button in the side panel's *Ready to close* card (`focus.html`, `#closebtn`, enabled by `app.js` when every check passes and the state is `idle` or `exited`), below the Reports and Inbox panels, where Paul did not find it. §4.5a says exactly this — *Focus side panel: diff / log / PRs, run-log link, Close* — so the build is faithful and the design is what the review has to change: the card's rule (§4.5 *The card's anatomy*: the next act is the one outlined button in the foot, **Close session** on *ready to close ✓*) has no counterpart on Focus, whose header shows the same controls whatever the session's state.
3. On **Org** the card was there but hidden: the `ao-grind` team had concluded (its manager exited), and a team with nothing live folds its cards behind *n sessions — show* (§4.5a *team groups*). The designer, `idle` and ready to close, counts as nothing live for the fold (`live: 0 if g["stopped"]`, `app.py`), so the header read *concluded 6m ago · out of work · 1 idle · 1 on call · 3 exited · 5 sessions* with a **Start** button, and Paul read it as *already closed*. The folded card carries the caption *ready to close ✓* and the **Close session** button, but the fold hides both, and the header's counts do not say that one of the five is a live session waiting for a press.

**What the review has to settle:** (a) **Focus after a wrap-up** — when Ready to close passes, does the header carry **Close session** as the outlined next act (the card's rule applied to Focus), with Kill behind *more* or kept as the danger it is; and does the *out of work* badge in the header say *ready to close ✓ · Close* the way the card's slot and caption do; (b) **a concluded team's fold** — a session still there (`idle`, `exited` with a pane) is *live* for the fold, or the fold header carries *1 ready to close* with the Close a press away, or the folded group unfolds itself while it holds anything a person must still close; (c) **what Wrap up promises** — the button's label or its confirm says what happens next (*asks it to finish and push; you close it when the checklist passes*), so a person is not left waiting for a close that is theirs to press; (d) **Kill's place** — whether a `ready to close ✓` session should offer Kill at all, since Close does the same kill after the checks; (e) the mockups (`docs/mockups/gen.py`) for Focus at *ready to close* and for a concluded team holding one; (f) **the fold control's place** (Paul, 2026-09-25): *n sessions — show* sits apart from the team card's other controls, and it took a minute to find — move it beside **Start** so a team card's buttons are together, and give it a show / hide icon (a chevron or an eye) with the count, since the words alone did not read as the way in; (g) **two cards named designer-ao-1** were on the page before Paul closed the resumed designer. The store holds one record and the host agent log reads *designer-ao-1 superseded the exited session of the same name* at the resume (08:06:16 MDT) — TD-145's rule, promoted 2026-09-24 20:16, before the resume — so the doubling was the page's: a card the browser kept after the supersede, or the same id drawn twice by the group and a fold. Reproduce it in the review (resume an exited team member from Focus, watch Org) and say which; the record side is §4.1's rule, one name per team, and held.

**Done when** Paul, having pressed Wrap up on a session, sees on the same screen the one press that closes it once it is ready, and a team card with a session waiting to be closed says so without unfolding — built; his live look closes it; (g) is another TD's.

**Related:** §4.5 *The card's anatomy* (the outlined next act), §4.5a *Focus: Wrap up*, *Focus: Kill*, *Focus side panel: Close*, *card: Close session*, *Org: team groups* (the fold), §4.9a (a declaration is not a state), TD-081 / TD-145 / TD-155 (the resumed session this was seen on), TD-154 (reading a transcript, the other reason the session was resumed at all), TD-095 (the card's foot and slot).

## TD-290: A UI change goes to the person unchecked — the grinder verifies it, a reviewer only if needed, and what is left is a `look`

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-02 (the anchor, from Paul's walk of the pages: *we should probably have these types of verification items sent to a reviewer (and then to me if needed)*; 2026-10-03: *I would expect a grinder who makes ui changes to verify them itself before sending to a reviewer, and only send to a reviewer if needed*; *a distinction between "watch" items (issues that have arisen once and need to be seen again before acting) and "look" items (items that are for me to take a look at) — have the look items go to either steering or "needs you" instead of creating a new category*)
**Owner:** designer
**Kind:** design-first
**Status:** **Designed 2026-10-03**, twice (the designer). In the morning, on Paul's three points (PR #947; the two choices steered as `m-71d3c709e116`, Paul: *Go with both defaults: the techlead seat is the reviewer … and a look the techlead leaned Works on closes as Works at its Due date*): what was left for the person was a board `look` line, drawn under Steering with a default and closed by its team at its `Due:` — **superseded the same evening**. In the evening, on Paul's note `m-d435ff0d831a` (PR #977): a look that reaches the person is mail. Design as it stands: §4.9b *A UI change is verified by its builder* (the builder's scratch home and the **UI check** in its PR; the live copy read by a `watch`, never pressed; the reviewer is the techlead seat, its three replies; what is left is nothing, a `steer` with the default *Works* where the techlead leaned, or an `ask` with *Works* / *Not right* where nobody could settle it; a board `look` only without agentorc's mail), §4.10 *A look* (`shots`), §4.7 `--shot`, §4.5 screen 6, §4.5a **Inbox row: a look** and its **Send to reviewer** (`inbox_hand`), the glossary's *look* and *scratch home*, mockup `Inbox.dc.html` (`docs/mockups/reviews/2026-10-03-td290-look-rows.png`). Nothing is asked of dev-cadence. Builds: TD-291 (the builder's half; built and archived), TD-292 (the mail's and the Inbox's half).
**Blocked by:** TD-292
**Location:** design §4.5a (a board row's answers, **Works** / **Not right…**; the Inbox's sections), §4.9 (roles), `docs/briefs/grinder-ao-*.md` (*never run `ao ui`*; *a fix that needs a live look is … a `watch` line*), cadence §3.5 (the live look, written as a `watch`); the anchor's Playwright set-up (`~/ao-shots/pwlib`, `~/ao-shots/scripts/`, headless Chromium)

**Why:** today no one checks a UI change before the person does. A grinder may not run `ao ui` (its brief), and the live copy changes only at the anchor's promote, so every merged UI change ends in a `watch` line asking the person to look, and most of what those lines ask is mechanical: a label reads so, a button is greyed, a toast says *x*, a size takes. The board held ten at once on 2026-10-02 and Paul walked them page by page over an evening. A headless browser can make most of those checks: Playwright with Chromium loads a page, waits for its scripts and the terminal, reads values and takes screenshots; it settled TD-288's fresh-load half. And the word is wrong: `watch` means a thing seen once that must be seen again before acting (a session's §6 check), while these lines ask the person to look.

**Fix:** design first. *(Point (3) below is the entry as it was raised; Paul's note of 2026-10-03 evening replaced it — what is left for the person is mail, a `steer` or an `ask`, and never a board line where agentorc's mail reaches: see Status.)* (1) **The grinder verifies its own UI change.** Before the PR, against a scratch UI: a temporary `AGENTORC_HOME` and a private port, the same kind of thing as `pdm run test`, never the live units, so the brief's rule changes from *never run `ao ui`* to *never run it against the live home*. It drives the change with Playwright and puts the screenshots and the values it read in the PR. After the promote, it makes a read-only look at the live copy. (2) **A reviewer only if needed:** for what the grinder cannot settle by itself, such as a judgement of layout or wording, or a state it cannot stage. Say who that reviewer is (the techlead seat, or a reviewer role with a browser) and what it sends on. (3) **What is left for the person is a `look` item, not a `watch`** (dev-cadence TD-082 adds the kind). It carries the screenshots, says what was checked and what is the person's to judge, and draws in **Needs you**, or in **Steering** when it carries a default and a bound. It does not get an Inbox section of its own. `watch` keeps its meaning. (4) A **Send to reviewer** answer on a `look` row, for when the person would rather have it checked first, and what that writes on the board. Keep it one rule: a look that a machine can settle never waits on the person.

**Done when:** the design says who verifies a UI change and how the rest reaches the person, the grinder briefs say it, the build entries are on the ledger with a `Blocked by:` line, and the next merged UI change goes through it.

**Related:** TD-255 (a live look's answers), TD-244 (the page walks), TD-288 (settled half by a headless look), cadence §3.5.

## TD-292: Build the mail half of a look

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-03 (the designer, TD-290's build; re-scoped the same evening on Paul's note: a look is mail)
**Owner:** anchor
**Kind:** live-check #1007
**Status:** **Read 2026-10-13 (the anchor): a steer carrying shots lapsed with no press, but it is no builder's look.** The live Inbox (headless GET of `/inbox`, read only) draws one `/shot/` screenshot: designer-ao-1's TD-630 design `steer` (`m-10d827d892f8`, `shots: [2026-10-13-td630-add-entry-attach.png]`, the route answering it) closed with *you let it go with its default* and an `outcome · done`, now under *FYI*. That is the steer-with-shots half of the mechanism (the thumbnail drawn on a `steer` row, the lapse to its default with no press) seen live; the *Done when*'s three readings still wait on a builder's look after a page PR (a leaned-*Works* `steer`) and on Paul pressing **Send to reviewer** — no entry is `handed` as a look. **Read 2026-10-12 (the anchor):** no look since — the live Inbox (headless GET of `/inbox`) draws no `/shot/` screenshot, its one *Steering* row is no look, and no entry is `handed`. **Read 2026-10-09 (the anchor): the first look arrived, and its *ask* half holds.** grinder-ao-1's `m-500957934330` (05:13Z, `--kind ask`, re TD-478, two `shots`) is on the live Inbox (headless GET of `/inbox`, read only) under *Needs you* (`data-section="needs"`) with its two screenshots drawn from `/repo/agentorc/shot/…` (the route answers 200, `image/png`) and the pair drawn as **Works** / **Not right…**, beside **Send to reviewer**. Still to read: a leaned-Works look as a `steer` under *Steering* that lapses to *Works* with no press (none has been sent), and **Send to reviewer** pressed by Paul (no entry is `handed`). **Read 2026-10-08 (the anchor, TD-426):** still no look: none of the person inbox's 124 entries carries a shot. **Built; a live check waiting on an event (grinder-ao-2, 2026-10-05).** #1007, the last slice, is live (`ao promote status`: live f8090c2). Read that day with a headless GET of the live Inbox: no look mail is on it — no row draws a `/shot/` screenshot and none carries a seat's reading — so none of the *Done when*'s three readings can be made yet. They wait on the first look a builder sends after a page PR (design §4.9b), and Send to reviewer's on Paul pressing it on one. Nobody can cause that on purpose, so the entry is the anchor's until a look has arrived; whoever reads one then writes what it showed here. Before: the board row's pair on cadence's kind `look` is built: PR #975 (`LOOK_KINDS`), slice 1 of the entry as it was first scoped. Re-scoped 2026-10-03 evening (PR #977) to the mail rows. Slice 1 built — PR #980 (the grinder brief's three cases as mail; the techlead preset's two sentences). Slice 2 built — PR #983 (`ao msg --shot`; `shots` on the envelope, checked whole against `docs/mockups/reviews/<name>.png`). Slice 3, the row, built — PR #982 (`look_shots`, `look_pair`, `GET /repo/<repo>/shot/<name>.png`; this host's registry only, another host's is TD-300). Slice 4a, the host agent's half of Send to reviewer, built — PR #990 (`inbox_hand`, `snoozed_for`, `look`, `looked_by`; the techlead preset's *A look handed to you*). Slice 4b built — PR #1007 (the page's **Send to reviewer**, the seat read from `org.yml`; the snoozed row's *with <seat> since <time>*; the handed `ask` read as a look; the `looked_by` line above the answers). Merged, live look pending: the *Done when*'s Send to reviewer, with a real techlead seat.
**Location:** `docs/briefs/grinder-ao-1.md` (the paragraph *A change to a page is verified by you*, the one brief that carries it), `src/shiftlead/briefs/techlead.md` (*A screenshot ask*: *The builder then puts a board line before the person*; *what reaches the person is the builder's board line, one road*), `src/shiftlead/cli.py` (`ao msg --shot`), `src/sessionorc/mail.py` and `src/sessionorc/models.py` (`shots`, `snoozed_for`, `read_by` on an envelope), `src/sessionorc/agent_inbox.py` (`inbox_hand`), `src/shiftlead/ui/inbox.py` and `src/shiftlead/ui/app.py` (the row, the screenshot route); design §4.9b *A UI change is verified by its builder*, §4.10 *A look*, §4.7, §4.5a **Inbox row: a look** and **Send to reviewer**; mockup `docs/mockups/Inbox.dc.html`, `docs/mockups/reviews/2026-10-03-td290-look-rows.png`

**Why:** Paul, 2026-10-03 (his note `m-d435ff0d831a`): *rework TD-290 so a look that reaches the person is mail, not a board line*; his reason there: *a steer already means go with the default at the bound unless I say otherwise, which is what the leaned-Works look wants*. The briefs TD-291 landed (#972, #973) still tell a builder to write a board line.

**Fix:** as §4.9b's table and §4.5a's two rows say, in slices, each its own PR. (1) **The briefs** (touches `docs/briefs/**`: the reader's read; needs nothing built): this repo's grinder brief says the three cases as mail, and the techlead preset's two sentences name the builder's message in place of its board line — nothing when every check held; `ao msg person --kind steer --default "Works" --bound <no shorter than a night> --about TD-NNN "…"` naming the techlead's reply and the screenshots' paths where it leaned; `--kind ask --answer "Works" --answer "Not right: <what>"` where nobody could settle it — sent after the merge, the first paragraph the one thing that is Paul's to judge; a *Not right* reply is ledgered as an entry of its own and its outcome reported; no board line, but the `watch` for a read of the live copy stays. (2) **`--shot`** (touches `src/sessionorc/**`: the reader's read): up to four, a `.png` under `docs/mockups/reviews/` of the sender's repo, only on a `steer` or an `ask` to the person, refused otherwise in words; `shots` on the envelope; the briefs of slice 1 then name the screenshots with it. (3) **The row**: `GET /repo/<repo>/shot/<name>.png` serving that one directory at `origin/<default>` and nothing else; thumbnails under a look's text, on the `steer` and the `ask` row alike; on the `ask`, the pair *Works* / *Not right: <what>* drawn as **Works** and **Not right…**. (4) **Send to reviewer** (touches `src/sessionorc/**`): `inbox_hand {id}`, the person's alone — the `handed` `ask` to the sender's team's techlead seat with the look's text, `shots` and id; the look snoozed with `snoozed_for` until that debt closes and listed *with <seat> since*; the outcome's line back on the look as `looked_by`, drawn above its answers; the refusals in the host agent's words; the techlead preset says how a handed look ends: one outcome whose text is its reading, or `blocked`.

**Done when:** a builder's leaned-Works look reaches Paul as a `steer` under *Steering* with its screenshots drawn and lapses to *Works* with no press, one nobody settled is an `ask` under *Needs you* with **Works** / **Not right…**, and **Send to reviewer** fills the techlead seat and brings the look back with the seat's reading.

**Related:** TD-290 (the design), TD-291 (the builder's half), TD-255 (a live look's pair), TD-218 (a handed entry), TD-127 (a message's shape).

## TD-297: The parts of the live looks of 2026-10-03 nobody could see

**Priority:** Low
**Type:** debt
**Added:** 2026-10-03 (the anchor, with TD-296)
**Owner:** anchor
**Kind:** live-check
**Status:** Open — **Owner anchor from 2026-10-05 (grinder-ao-1): what is left is out of a scratch home's reach** — a check that waits on a logged-in session or on GitHub is made by whoever has them, and a live event when it happens. **A team stop time on members' cards does not hold** (pressed the same day with a shell member: the record and Focus take it, the Org draws it nowhere): TD-335. Every press still listed needs a logged-in claude-code session (a scratch home's `CLAUDE_CONFIG_DIR` is its own, so none logs in: a role chip's `prompts:`, Resume, a permission card's Deny and keys, a team Start or `ao new me --team`, `stalled?`, a second agent session, Add entry's session, a live team's reserve line) or GitHub (`auto`'s green checks, the Org's *over its line*), and the rest are live events, read when they happen. **seven presses seen working 2026-10-04 (grinder-ao-1)** on a scratch home (`scripts/look_home.py`, its repo given a local origin so Ready to close passes), in headless Chromium: Close session is in the Focus header once Ready to close passes, drawn with no reload, and Close takes the record to `closed` (TD-156); Close and Kill each leave one *pane is gone* line after one *retrying in 1s*, and no websocket opens in the six seconds after (TD-029); on a killed session `#compose` is disabled with *this session's process has ended*, and **→ Send** sends nothing and says so (TD-047); Message… from a card's *more ⋯*, ✉ Message in Focus and Reply on an Inbox `ask` row each open the mail dialog (TD-052); `j` rings an FYI note and `x` presses its Dismiss, which confirms and removes it (TD-124); Put on the board opens a four-row box where Enter adds a line and Ctrl+Enter puts it on, the lines joined into one line at the top of *Needs the user*, one commit (TD-281); `ao new --unattended --at +2h` draws a *scheduled · starts <time>* card whose *more ⋯* holds Start now and Cancel, Cancel confirms and forgets the record, and `ao at <id> now` starts it on the next tick (TD-152). Those are struck from the Fix's list. **Three more the same day, on the same home:** a board row's answers are drawn in the order written with the default marked *DEFAULT*, the body without the tail, and **Go with it** in the foot after Reply; a click on an answer, **Go with it** (its confirm names the default), `1` and `4` on a ringed row and `g` each write the decision as one commit (`agentorc: decide <head>: <answer> (session look)`) and toast *decided: <answer> — committed on the board, not pushed*; **Not right…** on a look line opens the Reply composer with *Not right:* begun and writes the words as the decision, toasting *no entry was handed on: no team services repo: there is no techlead seat …* on a home with no techlead (TD-255); *due this week* on Settings → You saves `board_show: 7d` and the Inbox's line reads *showing board items due this week · 1 not shown, the next due Jan 1 — show* (TD-220); **Drop** on a claim with no PR is under the Reports card's *more ▾* in Focus, its confirm names the lease and the one session that may claim it again, and the session's inbox gains *your claim on TD-001 was dropped by the person — the lease is gone* (TD-150, TD-028). Struck too. **Snooze on an `unpushed` row** (an exited session whose repo is ahead of origin) offers *in 1 hour*, *tomorrow 08:00* and *a date and time…*, and the row moves under *1 snoozed — show* (TD-079); struck. The trail row the same home drew for an `unpushed` row that ended by a push read *resolved: resolved ×2*, where §4.10 says *pushed*: TD-308. **Three more 2026-10-05 (grinder-ao-1)**, on a scratch home whose repo had a local bare origin and a `promote:` block (`check` reading a file the `run` writes), in headless Chromium: a `run` that exits 1, pressed with `ao promote repo`, draws a counted *Needs you* row reading *failed: promoting cdc6c41 — the run ended and live is 04cd6aa, not cdc6c41 (exit 1). Nothing is promoted for repo until this is dismissed or a press succeeds.* with the log's tail; a second merge on origin is read (*main 4359875, 2 ahead*) and promotes nothing while the failure stands; **Dismiss** toasts *the failure is cleared: promoting goes on* and the row is a plain promote row again (TD-132 (3)); **Promote** on the row, with a `run` that works, toasts *promoting repo to f556e05 — checks read unknown, pressed through* and live reaches main; with `auto` on, `ao promote repo --back` makes the earlier commit live, and `ao promote status` and the Inbox row (under *Needs you*) read *live 04cd6aa, rolled back from f556e05 … · auto on · held*, with FYI notes *rolled back repo to … — main is n commits ahead*; the row's **Dismiss** toasts *the hold is ended: live stays where it is, and promoting goes on* and the hold is gone from `ao promote status` (TD-226); **Start** on a stopped team whose only member's lane matches nothing opens the dialog *Start lk-grind? · Nothing to pick: every member's lane is empty, so the team will wind down as soon as it starts. · grinder: 0 · Cancel · Start anyway*, and Cancel closes it with the team still stopped (TD-265, TD-262; *Start anyway* not pressed, since it launches claude-code sessions a scratch home cannot log in). Struck. Not pressable there: `auto` promoting by itself (TD-132 (2)) needs green checks, which a repo with no GitHub remote never reads (*checks unknown*); **Snooze on a `stalled?` row** needs a hook-fed session, since only those stall (`agent_tick`: a shell is `working` or `idle`). **Two more the same day, on a second scratch home:** on an unattended shell session with a team, Focus draws **Take over**; once pressed, *more ▾* holds **Hand back** (a session with no team and no controllers reads *Switch to unattended* there, as `cards.py` words it), and Hand back turns the record unattended again, the composer closed (TD-096); on a team the home's `org.yml` defines, with the home made a work tree, **Members…** opens *Members of lk-org*, *stopped: an edit is the definition only — the next Start brings it*, the name prefilled *grinder-lk-2*, and **Add member** lists it, toasts *org.yml: added grinder-lk-2 (grinder) — the team is stopped: its next Start brings the member*, writes one line into `org.yml`, and the home commits it as *org: lk-org added grinder-lk-2 (grinder)* (TD-268). Struck.
**Location:** the closed look lines of 2026-10-03 in `docs/user_attention_archive.md` (each names its TD); design §4.5, §4.5a

**Why:** the looks were made read-only against the live copy, and presses only on isolated scratch homes, two of which stopped early (TD-298). What follows was not seen. None waits on Paul.

**Fix:** make each on a scratch home (TD-291's `scripts/look_home.py`) where a press settles it, or read-only the next time the live event happens; a failure is its own entry. **Presses:** a role chip sending `prompts:` (TD-170, needs a claude-code session); Resume on an exited card (TD-155); Deny's *why?* box (TD-117); `a`/`d` keys on a permission card; New session's Start and Wind down for a team (TD-173, TD-276) and `ao new me --team`; Snooze on a `stalled?` row (TD-079, needs a hook-fed session); Promote's `auto` (TD-132 (2), needs a repo whose checks read green); a profile reserve's chip line after Save, the Org's amber *over its line* (TD-244 Settings); Add entry → Hand to the techlead and → Open a session on the live repo page (TD-219, TD-283, with a logged-in session); a second agent session in a directory refused (TD-152; a shell is exempt, so it needs an agent session). **Live events:** an early or repeat restart mark reaching the person, with the row naming it (TD-249's last case); a member steering you with nothing else to pick (TD-274's wind-down part); *merged without its read* and either row's Dismiss (TD-258); the Inbox restart row, `ao restart`, an exited Focus banner (TD-250); a manager fill by cause (TD-259); a *reported* reading under a minute after a new session (TD-233 s2) and *· projected n%* (TD-233 s4); *closed by you / by manager-ao-1 / itself* and a wind-down within ten minutes (TD-265); an orphaned question (TD-216); the team-start row on the Inbox (TD-244 Settings); the origin row turning live with no reload after a pull, and agentorc's checkout catching up once the anchor is idle (TD-281, TD-263); *earlier turns* on a transcript of more than 20 turns (TD-166); four restarts in two hours and *early: nothing reported done* (TD-249); *brief: changed* in `ao status -v` (TD-217); a SendMessage to a worker refused (TD-064); a metered profile (TD-151, once one is declared).

**Carried from TD-255 at its archive (2026-10-03), a design gap, not a look:** a team whose manager is on call has no round, so a live look decided *Works* reaches no holder to close it, and the pair has no help entry. Whoever designs TD-290's rework (looks as mail) settles who closes a decided look; until then the anchor closes them.

**Done when:** each is seen working or ledgered as its own entry.

**Related:** TD-296, TD-291, TD-244.

## TD-299: Run the guardians and contractmatch teams inside their devcontainers

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-03 (the anchor; Paul lifted the guardians hold the same day: *i think guardians and contractmatch are good candidates for using teams within a container*)
**Owner:** paul
**Kind:** build
**Status:** **Read 2026-10-09 (the anchor): the owner is paul.** contractmatch's half is done: since 2026-10-06 its grinder gates a frontend PR in its container (`/home/kmaster/contractmatch/.agentorc.yml`). What is left is guardians, (5), and every step of it is the person's: `/home/kmaster/guardians-devenv/.agentorc.yml` does not exist, `hosts.yml` has no guardians node, and `org.yml` has no guardians `place:`. A board line asks for it. **Read 2026-10-08 (the anchor, TD-426's run):** nothing in it is a member's now — the node's env and logins, `org.yml`'s `place:`, `ao host up guardians` and contractmatch's brief are the person's, or the person's own session's. In progress — (1) and (2) done 2026-10-03: the image installed Claude Code as root, so `developer` had none; contractmatch #108 moved it under `USER developer`, and `ao host rebuild contractmatch` brought up container `9e66a47155fa` with `claude` 2.1.289 at `/home/developer/.local/bin`, the agent on the live wheel (`8b1da05d4214`) and the link up. The image's postCreate *copying credentials from stuff_for_containers_home* copies nothing on the node: that mount is a tmpfs there. **(3) and (4) done 2026-10-03:** the node's `env` (values unquoted: `docker --env-file` keeps quotes) and three profile logins; `place: {cm-grind: contractmatch}` and the project's node path in `org.yml`; the team started on the node, and grinder-cm-1 merged #110–#113 from inside (none touches `frontend/`: a frontend PR checked inside is still to come). Found on the way: TD-301 (hooks, built and live), TD-302 (a node session's own word is refused) and TD-316 (a node rebuild replaces its container and ends the sessions inside without a word: grinder-cm-1 and manager-cm-1 at 23:38). **Left:** contractmatch's brief still sends frontend work to the devcontainer (Paul's cm session is changing it); then guardians, (5). guardians works from the umbrella repo (Paul, 2026-10-03): its team is defined in `guardians-devenv` against that repo's ledger and board alone
**Location:** `~/.shiftlead/hosts.yml` (`nodes:`), `~/.shiftlead/nodes/<name>/` (`env`, `profiles/`), `~/.shiftlead/org.yml` (`place:`), `/home/kmaster/guardians-devenv/.shiftlead.yml` (new), guardians-devenv's `docs/briefs/team-setup.md` and TD-028, `/home/kmaster/contractmatch/.agentorc.yml`; design §4.4a *A container node*, §4.9 *Where a repo's team lands*, §10

**Why:** the hold of 2026-09-23 is lifted: guardians' five repos are checked out at `~/guardians-devenv`, §10 decided that a devcontainer running an `agentorc-agent` is a node, and the contractmatch node reads *running · link: up — linked* (`ao host status contractmatch`). A team in its container gets the project's own toolchain (contractmatch's `frontend/**` PRs are left open today because kmaster cannot run `flutter analyze`), and an unattended worker's reach is the container's mounts, with a repo-scoped token, never the person's credentials. Nothing has run a team on a node yet: TD-057's *Done when* is that run.

**Fix:** (1) **contractmatch first, on the node already up:** check that the image has what a worker runs (`claude`, the toolchain, Python 3.12+ on the agent's PATH); (2) `ao host rebuild contractmatch` at the live version if the node's build is behind; (3) **Paul's, once per node:** `~/.agentorc/nodes/<name>/env` (`0600`) with a fine-grained GitHub token scoped to the repo, the author name and email, and the repo's own needs (contractmatch: a Doppler service token), and one `claude` login inside per profile the node's roles name (`/agentorc/profiles/<profile>/`); (4) `place: {cm-grind: contractmatch}` in `org.yml` with the team wound down, then Start, and watch one entry go from pick to merged PR from inside, a frontend one included; (5) **guardians:** a `nodes: guardians: container: {devcontainer: ~/guardians-devenv}` entry and `ao host up guardians`, step (3) for it, then `guardians-devenv/.agentorc.yml` with a team in the manager / techlead / members shape the other repos use (by a PR in that repo), `place:` to its node, and the team's briefs written in guardians-devenv (2026-10-09: the old `docs/briefs/guardians-orchestrator.md` is retired to `archive/`; guardians-devenv's `docs/briefs/team-setup.md` and its TD-028 carry the steps, run by a session there). The five-repo constellation (cadence §9): the team works from the umbrella's ledger and board alone (Paul, 2026-10-03).

**Done when:** cm-grind and a guardians team each run on their node, each with a PR merged from inside, and TD-057's *Done when* reads met.

**Related:** TD-057 (the home and node split), TD-229 (repo-defined teams and `place:`), TD-296/TD-298 (2026-10-03's looks).

## TD-300: A look's screenshots from a sender on another host draw their names alone

**Priority:** Low
**Type:** debt
**Added:** 2026-10-03 (grinder-ao-2, TD-292 slice 3)
**Owner:** anchor
**Kind:** live-check #993
**Status:** **Read 2026-10-08 (the anchor, TD-426):** now `Blocked by: TD-299`, the entry that places the first member on a node, so it leaves the lane until then. **A live check waiting on an event (grinder-ao-1, 2026-10-05):** #993 is live, and its *Done when* needs a look sent by a member running on a node, which no grinder can cause — TD-299 places the first such member; whoever reads the home's Inbox after that look reads its thumbnails there. Built — PR #993 (`sessionorc.shots`, `host_shot` and the link's `shot`; the row's `?host=` and the route reading there). The *Done when* waits on the first look from a member on a node (TD-299 places one).
**Blocked by:** TD-299
**Location:** `src/sessionorc/shots.py` (the one reading), `src/sessionorc/agent_remote.py` (`host_shot`), `src/sessionorc/agent_link.py` (the link's `shot`), `src/shiftlead/ui/inbox.py` (`shot_root`, `shot_bytes`, `look_shots` with the sender's host), `src/shiftlead/ui/app.py` (`repo_shot`, `?host=`); design §4.4a *A look's screenshots on another host*, §4.5a **Inbox row: a look** (*through the host whose registry holds the repo*)

**Why:** the row (#982) serves a screenshot only from a checkout in this host's registry. A look sent by a member running on a node (TD-299, `place:`) names a repo that the node's registry holds and the home's does not, so the row draws the file names and no images.

**Fix:** a host-agent read of one `.png` under `docs/mockups/reviews/` at `origin/<default>` of a registered repo, refusing any other path; the route asks the host whose registry holds the sender's record's repo (`repos_of`), as the place check does. Tests: a node-placed sender's look draws its thumbnails.

**Done when:** a look from a member on a node draws its screenshots on the home's Inbox.

**Related:** TD-292 (the row), TD-299 (teams on nodes), TD-057 (the home and node split).

## TD-410: Every team Start fills the on-call manager, which reads ~60k tokens of design to find nothing due: 14 fills since 2026-10-03, all *nothing to do*

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-08 (the person's session, from Paul's *what does the manager still do — do you recommend moving it to Haiku?*; TD-118's step (4) dropped in its favour)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-08 (the designer, PR #1285): design §6 rule 3 *A Start writes the seat and never fills it* — `ao team start`, and an Apply's create of a manager the run lacks (§4.9c), writes a manager on call's record as a held anchor's is written (TD-386's `create` with `held`): `closed`, no pane, the launch record, `seat: {trigger: team}`, no `seat_held`; its id is the name's, so the members' `controllers` name it before it has run, as they name the techlead's, and the fill keeps the id; the Start's line reads *on call — comes when a member needs a reading*. **A Start with something already due fills at once** by the rule alone: the first tick reads the kept mail's question (the held create moves the mail as a fill does — it did not before, so the build adds it) or a member's `needs-you` as any seat's cause; the Start is never a cause. **A fill says why it came**: the fill's prompt is the brief with one closing line, *[agentorc] you are filled for: <by> — <member or ask id>*, so the first act is the reading. **First reads** (§6 *What is left is judgement*): checked against the code — the on-call template `manager_on_call.md` (1,400 words) already names no section of the design, reading `ao --skill` and its log first, then `seat_due` from `ao status --json` under its causes; the 60k reading in the Why is the standing `manager.md`'s (4,200 words; §4.8, §6 and the cadence), which is `on_call: false`'s alone; what remains is the repo's supplement `docs/briefs/manager-ao-1.md`, whose *first reads* (§4.2, §9's invariants, the cadence skill) move under the readings that need them — a held path, the build's briefs slice. The waste the journal shows is the fourteen fills with nothing due, and the held create ends them. §4.9 `on_call` and §4.9c's Apply say the same. TD-413 builds it. Before: Open.
**Blocked by:** TD-413
**Location:** `src/shiftlead/teamrun.py` (`start`: `plan.lead` is created live whatever `team.manager.on_call` says); `src/shiftlead/briefs/manager.md` (*First:* reads `ao --skill`, design §4.8 and §6, cadence §1–§4); design §4.9 `on_call`, §6 rule 3 (the `team` trigger), §6 *What is left is judgement, and a seat holds it*, §4.8

**Why:**
- Since TD-259 the manager is a seat on call, meant to be filled by §6 rule 3's `team` trigger only when a reading needs judgement: an `ask` to it, a permission on an unattended member, a `stalled?` member, *idle · open work* after the nudge, an escalation.
- `ao team start` still creates the manager as a live session, before the techlead and the members. So every Start fills it.
- Each fill reads the brief (about 4,200 words), then its first reads: design §4.8 (about 9,500 words), §6 (about 21,000) and cadence.md (about 8,500). That is some 60–70k tokens.
- The host agent's journal, 2026-10-01 to 2026-10-08, has 14 closes of a filled manager across the four teams, from 2026-10-03 on, each logged as *a seat with nothing due, idle and pushed*. They line up with Starts: on 2026-10-08, ao-grind's manager started at 15:12 and closed at 15:15 MDT, and samscrape's started at 15:54 and closed at 15:56. manager-ao-1's round log for each reads *filled with no seat_due … nothing to do*.

**Fix (to design):**
1. A Start writes an on-call manager's record without a pane, as a held seat is written (TD-386's `create` with `held`). Rule 3's `team` trigger fills it on its first due reading. Say what the controllers point at until then: the members' `controllers` name the manager's id whether or not it has a pane.
2. A filled manager's first reads shrink to its brief, plus the one §6 rule its filling reading names, read on demand. The brief's *First:* paragraph names no whole section.
3. A fill says why it came (the reading that made it due, on the line the tick types), so the round starts from it.
- Decide whether a Start with something already due (an open `ask` to the manager carried over) fills at once.

**Done when** a Start on a team with an on-call manager creates no manager pane, the manager is filled the first time one of its readings is due, a fill's first reads are its brief and the rule it was filled for, and a week's journal shows no *nothing due* close for a manager.

**Related:** TD-118 (archived; its step (4), the manager on Haiku, dropped for this), TD-247 (the manager's jobs moved to the tick), TD-259 (the seat on call), TD-386 (the held create), TD-381 (the anchor seat's record without a pane).

## TD-413: Build TD-410: a Start writes the on-call manager held — no pane until a reading is due — the fill's cause line, and the on-call briefs' first reads

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-08 (the designer, from TD-410's design)
**Owner:** anchor
**Kind:** live-check #1684
**Status:** **Built 2026-10-13 (grinder-ao-1, PR #1684, TD-660):** rule 8's start writes every unattended seat held; once #1684 is live, read the journal half again — a week of it with no seat closed with nothing due straight after a rule 8 start. **Read 2026-10-13 (the anchor): the journal half does not hold — blocked by TD-654.** `journalctl --user -u shiftlead-agent` (read only) since the promote: every *a seat with nothing due* close of a manager follows a fill for a cause (*the seat is due (stalled) — filling it*) or a held create, except two, and both follow a rule 8 start: *rule 8: starting dc-grind again for ['TD-092', 'TD-096'] (4 records)* at 2026-10-12 10:57:36 MDT, `ao-dev-cadence-manager-dc-1` *superseded the closed session* (no *written closed with no pane*) and closed at 10:59:51; and *starting cm-grind again for ['TD-056'] (4 records)* at 2026-10-13 10:06:20, `ao-contractmatch-manager-cm-1` replayed over the link and closed at 10:08:32. Each start's techlead seat went the same way, as did ao-grind's techlead at rule 8's start of 2026-10-11 04:35. `agent_tick._work_start` replays every ended crew record, seats included, through `_replay`, which creates a pane; §6 rule 3's *A Start writes the seat and never fills it* names `ao team start` and Apply alone. The 10-12 read below missed the first of these. The held create of a person's Start still holds. TD-654 says what is wrong; this check is read again once it is built and live. **Read 2026-10-12 (the anchor): the journal half holds so far.** `journalctl --user -u agentorc-agent -u shiftlead-agent` (read only) from 2026-10-08: the last *a seat with nothing due* close of a manager is `ao-samscrape-manager-sam-1` at 15:56 MDT on 2026-10-08, before the promote (19:33); since then such closes are techleads, audits and anchors only. The week ends 2026-10-15. **Read 2026-10-09 (the anchor): the held create holds.** ao-grind's start at 13:22Z left `ao-agentorc-manager-ao-1` `closed` with `closer: {by: start, why: held}`, and samscrape-grind's at 14:30Z did the same for `ao-samscrape-manager-sam-1` (`ao status --json`). The journal half waits on the calendar: the week from the promote runs to 2026-10-15. **Read 2026-10-08 (the anchor, TD-426):** #1287 went live 2026-10-08 19:33 MDT (aebeea3); no team has started since (ao-grind's manager-ao-1 was created at 15:12 that day, filled and closed by the tick as a seat), so the check waits on the next `ao team start`. Built 2026-10-08 (grinder-ao-1, PR #1287), all three slices: `teamrun.start` and `apply` write a manager on call `held` (`on_call_gate`), the line *on call — comes when a member needs a reading*; the held create moves kept mail; a fill's prompt ends with *[agentorc] you are filled for: <by> — <member or question>* (`agent_tick.filled_for`, `restarts` `for: seat_due`); `docs/briefs/manager-ao-1.md`'s first reads under the readings. Tests in `test_anchor_seat.py`, `test_manager_on_call.py`. **The live check:** once #1287 is live (`ao promote status`), read with no press of yours: the next `ao team start` of an on-call team (its output, or `ao status -v`) shows the manager `closed` with `closer: {by: start, why: held}` and no pane; and from the promote on, a week of `journalctl --user -u agentorc-agent` (read only) holds no *a seat with nothing due* close of a manager that was never filled for a cause. TD-410 is archived with this entry. **Read 2026-10-08 19:39 local (grinder-ao-2):** #1287 went live with `aebeea3` at 19:33 (the host agent's journal: *promoted `agentorc` `aebeea3` — 9 commits*); no `ao team start` has run since, so the held create is not yet seen — `ao status --json` shows `ao-agentorc-manager-ao-1` `closed` by `{by: tick, why: seat}` at 21:15Z, a close from before the promote. The journal since the promote holds no *a seat with nothing due* line. **Waits for** the next `ao team start` of an on-call team, and a week of journal from 2026-10-08 19:33 (to 2026-10-15): read both then, and archive or file what is wrong.
**Location:** `src/shiftlead/teamrun.py` (`start`: `plan.lead`'s create; `apply`: the manager the run lacks; the Start's row words), `src/sessionorc/agent.py` (`rpc_create`'s `held` for a `team` seat, `_schedule(state="closed")`), `src/sessionorc/agent_tick.py` (`_fill` → `_replay`: the closing line on the prompt), `src/shiftlead/briefs/manager_on_call.md` (the first paragraph reads the line), `docs/briefs/manager-ao-1.md` (first reads moved under the readings — a held path), `tests/test_teamrun*.py`, `tests/test_seats*.py` / `tests/test_manager_on_call*.py`

**Why:** TD-410: `start` creates the manager live before every other record, so every Start fills a manager on call into nothing — fourteen fills since 2026-10-03, each closed as *a seat with nothing due*. Design §6 rule 3 *A Start writes the seat and never fills it*, §6 *What is left is judgement* (first reads), §4.9 `on_call`, §4.9c (Apply).

**Fix:** as designed, three slices —
1. **The held create** (`teamrun.start`, `teamrun.apply`): when `team.manager.on_call`, `plan.lead` is created with `held=True` and no `held_reason` (the create takes `seat` and `unattended`, which the on-call launch carries; `rpc_create` accepts `held` without `held_reason`, and a `team` seat's held record takes no `seat_held`); **the held path honours `keep_mail`**: today `rpc_create` returns from `_schedule(state="closed")` before `_move_mail`, and `_schedule` writes `supersedes: [{mail: false}]`, so a held record begins with an empty inbox — make the held create move the superseded record's mail when `keep_mail` is given, as a fill does, so a question to the last run's manager fills the seat; `lead_id` is the reply's id as today, so every member's `controllers` and every brief's `{manager}` are unchanged; the Start's row for it reads *manager-ao-1: on call — comes when a member needs a reading* (`org.MANAGER_WHEN`); `apply` creates a manager on call the run lacks the same way. Pin: a Start on an on-call team makes no manager pane (`state == "closed"`, `closer: {by: start, why: held}`, a launch record written), the members' `controllers` name its id, the techlead's `controllers` too; the tick's first `_seat_pass` with a kept `ask` in its inbox (a Start with `keep_mail` over a concluded team's manager record holding an open `ask`, the mail moved) or a member hook-confirmed `needs-you` on a permission fills it on that tick; with nothing due, no fill and no close (it is closed already, and `_seat_pass` closes an `idle` seat only); the launch record replays into a pane (the fill), not into another held record. `on_call: false` starts the manager live as today.
2. **The cause line**: `_fill` passes the cause to `_replay`, which appends to the prompt it hands `create` — after `_refill_prompt`, on the stored prompt too — one line, `\n\n[agentorc] you are filled for: <by> — <member>` (`<ask id>` for `asks`), fixed words from `seat_due`; no other `why` adds a line; the `restarts` entry carries `for: seat_due` beside `why: fill`. `manager_on_call.md`'s *First* paragraph says the brief's last line names the reading it was filled for, and the line under the causes that reads `seat_due` from `ao status --json` says it is the same reading. Pin: the created prompt ends with the line for each of the four causes; a crash restart's prompt carries none.
3. **The briefs** (held path, `docs/briefs/**` — the techlead reads it): `docs/briefs/manager-ao-1.md` loses its *First reads, beyond the template's* sentence; what it named goes where a reading needs it — §9 invariants 5 and 9–11 beside the permission reading, §4.2 beside `stalled?`, the cadence skill beside *idle · open work* — in one short line each. `src/shiftlead/briefs/manager_on_call.md` names no section of the design whole (check it still does not after slice 2's edit).

**Done when** a Start on a team with an on-call manager creates no manager pane and its members' `controllers` name the manager's id; the manager is filled the first time one of its readings is due, a Start with a question kept in its mail filling on the first tick; a fill's prompt ends with the cause line; `docs/briefs/manager-ao-1.md` names no first reads of its own; the tests above pin each; `pdm run test` and `pdm run lint` pass. The live check, once this is live: a week's host-agent journal shows no *a seat with nothing due* close of a manager that was never filled for a cause, and `ao team start ao-grind`'s output names the manager *on call*. TD-410 is archived with this entry.

**Related:** TD-410 (the design), TD-259 (the seat on call), TD-386 (the held create), TD-395 (`held_reason`), TD-400 (Apply creates a seat the run lacks), TD-217 (the replay fills the brief again).

## TD-460: Read back the one-week trial of a 200k context bound on ao-grind's grinders

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-08 (the anchor, from Paul's decision on TD-378: *Pin 1h, restart lapsed, trial 200k*)
**Owner:** anchor
**Kind:** live-check #1317
**Status:** Open — the bound is set in `.agentorc.yml` (`roles.grinder.context: {bound: 200k}`) by the PR that filed this entry. Each grinder takes it at its next start, and the trial week runs from the first such start to about 2026-10-15. Until then the check waits on the calendar, which nobody can hurry.
**Location:** `.shiftlead.yml` (`roles: grinder: context:`); design §4.8 *The bound has two layers*; the usage ledger and the run logs under `~/.shiftlead/` (read only)

**Why:**
- Requests over 200k tokens of context carried 35% of agentorc's weighted cost from 2026-10-01 to 10-08 ([ADR 2026-10-08](decisions/2026-10-08-prompt-cache.md)).
- A 200k bound cuts the mean context per request by about 29%. Against that, each grinder run is about two-fifths shorter, and every restart pays its first write and a re-orientation (the ledger, the files and the design read again).
- Nobody can net the two on paper. Paul decided to measure it on the weekly window for a week.

**Fix:** after a week on 200k (from about 2026-10-15), compare ao-grind's grinders' usage-window percentage per merged PR against the week before (2026-10-01–08). Count their restarts per merged PR alongside. Write the reading into the ADR's Consequences. Then keep the line in `.agentorc.yml` (and design §4.8 says this repo's grinder number is measured), or take it out (the 300k default returns), in a PR. A result that is unclear goes to Paul as a `steer` with the reading. **Done when** the line stays or goes with a written reading behind it.

**Related:** TD-378 (archived), [ADR 2026-10-08](decisions/2026-10-08-prompt-cache.md) option 4, TD-249 (the bound's last change), TD-459.

## TD-463: Four CI flakes since 2026-10-03, one of them seen four times

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-08 (the anchor, from the CI read that closed TD-063 and TD-078)
**Owner:** anchor
**Kind:** live-check #1332
**Status:** Built by #1332 (2026-10-09); a week of CI is still to read. #1332 fixed three of the four. The board test now waits on its fetching read's start, not a 2 s poll. The mail test now settles its members before the wait's cursor. The forget test had a real cause: `_refresh_git` wrote `_git_checked` for a record forgotten while its git read ran. That is fixed, with a regression test. The fourth, `test_a_screen_rules_state_goes_back_when_its_screen_is_gone`, did not reproduce in 50 runs beside a full suite and is **watched**. **To read on or after 2026-10-16:** CI runs from #1332's merge for any of the four. None failed: archive this entry. One did: a new entry for it, and this one `**Blocked by:**` it. The week is the only thing to wait for, so the owner is the anchor.
**Location:** `tests/test_ui_board.py`, `tests/test_mail.py`, `tests/test_agent_paths.py` (the tests below)

**Why:**
- A red run on main stops the promote policy (*not now: checks on main are failed*), and a red PR costs a re-run.
- The anchor's read of 2026-10-08 covered every run from 09-27 to 10-09, including the first attempts of re-runs. It found these four failing after every earlier flake had its fix:
  - `tests/test_ui_board.py::test_one_fetching_read_at_a_time_and_a_press_never_waits_on_it` — **four times**, on both Pythons: run 37111273858 (10-03, `td294-host-reads`), 37175483747 (10-04, `td292-look-shots`), 37253443447 (10-05, **main**), 37320649134 (10-05, `td099-live-check`). Each time `assert ['plain'] == ['plain', 'fetch']`: the fetching read had not started when the test looked.
  - `tests/test_mail.py::test_asks_waiting_counts_open_questions_addressed_to_a_record_and_wakes_its_manager` — once, run 37252493668 (10-05, main, 3.12): *ao-test-asks-waiting-counts-open-0-mgr never blocked in wait*. The same job also failed `test_link.py`'s supersession test, which was TD-326's, fixed by #1058 at 07:29Z that day.
  - `tests/test_agent_paths.py::test_a_screen_rules_state_goes_back_when_its_screen_is_gone` — once, run 37574592141 (10-07, main, 3.13): `assert False`.
  - `tests/test_agent_paths.py::test_forget_leaves_no_side_table_entry` — once, run 37748462010 (10-08, `td397-checkout-held-tests`, 3.12): the forgotten id was still in a side table.

**Fix:** take the four-time one first. Reproduce each under load (the file in a loop beside a full suite, as TD-078 did), then bound each wait on the signal it waits for rather than on a duration (TD-033, TD-261). A test that does not reproduce in 50 loaded runs is named as such here and watched. **Done when** each is fixed or watched, and none has failed in CI for a week.

**Related:** TD-063 and TD-078 (archived; the same family), TD-285, TD-289, TD-326 (archived flakes, each fixed by waiting on its signal).

## TD-512: A PR that truncates `docs/technical_debt_archive.md` passes every gate: nothing reads what the archive lost

**Priority:** Low
**Type:** debt
**Added:** 2026-10-09 (grinder-ao-2, found on #1421)
**Owner:** dev-cadence
**Kind:** build
**Status:** Open
**Location:** `scripts/check_cadence.py` (the `ledger` row; a SYNCED FILE, dev-cadence's), `tests/test_ledger.py`

**Why:** On #1421 (TD-461) an archive edit written as `open(a, "w").write(open(a).read() + entry)` truncated the file before reading it: the archive went from 8,363 lines to 22, its header and every entry from TD-011 to TD-455 gone. `pdm run pytest tests/test_ledger.py` passed (11 passed), and the cadence check's `ledger` row reads only that the PR names its TD and touches a ledger file. Only the Sonnet fact-check caught it, by reading the diff's `@@ -1,8363 +1,22 @@`. The archive is append-only by its own header ("appended in resolution order", "Each keeps its original TD number forever"), so a PR that deletes archived entries is never right.

**Fix:** in the cadence check's `ledger` row, fail a PR whose diff removes a `## TD-NNN:` heading from `docs/technical_debt_archive.md`, naming the ids (a rebase's conflict resolution that drops one shows the same way). Being a SYNCED FILE, it is made in dev-cadence and synced here. **Done when** a PR deleting an archived entry's heading fails the `ledger` row.

**Related:** TD-461 (#1421).

## TD-553: Drop the `.agentorc.yml` fallback once samscrape, contractmatch and dev-cadence have renamed theirs

**Priority:** Low
**Type:** debt
**Added:** 2026-10-11 (the anchor, split from TD-060 (c) on Paul's word)
**Owner:** grinder
**Kind:** build
**Status:** Open — until each of the three repos' `main` carries `.shiftlead.yml` and no `.agentorc.yml` (samscrape's by the anchor's PR, samscrape #1077, 2026-10-11; the other two are the entries below); read each with `git -C ~/<repo> ls-tree origin/main --name-only` before the pick.
**Blocked by:** contractmatch#TD-055, dev-cadence#TD-091
**Location:** `src/sessionorc/paths.py` (`LEGACY_REPO_FILE`, `repo_file`), `src/shiftlead/org.py:1044`, `src/shiftlead/repoconfig.py` (536, 576), `src/shiftlead/migrate.py`'s docstring (21, 36), `tests/test_migrate.py:92`, and the design's sentences on the fallback (`docs/design/4.7-cli.md:373`, `5-configuration.md:124`).

**Why:** the rename read a repo's `.agentorc.yml` as a fallback (TD-060 step 2) so the other repos could rename theirs by their own PRs. Once they have, the fallback is code that reads a file nobody writes.

**Fix:** delete `LEGACY_REPO_FILE` and every use of it; `repo_file` returns `<root>/.shiftlead.yml`; a repo that still has only `.agentorc.yml` then has no repo file — `ao doctor` names the file to rename (one line, `org`'s check). The design's fallback sentences go in the same PR, the dated fact to `docs/design-history.md`. It is grinder-ao-1's (its lane is `src/sessionorc/**`), and its claim names the `repoconfig.py` and `org.py` lines it touches in grinder-ao-2's lane.

**Done when** `git grep -n LEGACY_REPO_FILE` returns nothing, `.agentorc.yml` is left only in `migrate.py` and `tests/test_migrate.py` (the migration's own data) and in §10's answered questions (dated), `ao team list` reads all four teams from `.shiftlead.yml`, and a repo with only `.agentorc.yml` is named by `ao doctor`.

**Related:** TD-060, TD-552.

## TD-584: Design the ledgerboard split into ShiftLead: §4.5a, §4.7, §4.9a, §5, §6 and §8 (the ADR's build 3)

**Priority:** High
**Type:** feature
**Added:** 2026-10-12 (ao-dc-decouple, with Paul)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-12 (the designer) — every section the ADR names says what it decided: §5 *The seams* (`board:`, `gate:`, `commands:` `test`/`lint`, `worktree_setup:`, what `ledger:` requires, each seam's fixed sentence; *Repos* ShiftLead's own roster importing dev-cadence's); §4.7 `ao repo init`, `ao board edit done|snooze` (on the session's branch, `--line`/`--expect`, no `decide`/`reply`, refused on the default branch and a dirty index), `ao doctor` **repos** (a missing ledger a lack, an unset seam a warning); §4.5a *Repo page: missing seams* and the origin note from two in-process reads; §4.5 screen 6 and §4.4 read boards through `ledgerboard.py`, the copy-picking rule gone; §4.9a closes a decided line with `ao board edit done`; §6 rule 10 runs `gate:` by exit code, *no gate: a person merges*; §8 three layers and *no second parser*; the 2026-10-08 ADR's Status line. No mockup: the one drawn change is the Repo page's seam lines, plain text under the title. Help-list wording stays with the builds. TD-585–TD-591 build it; this PR drops TD-584 from their `Blocked by:`. Was: Open.
**Blocked by:** TD-585, TD-586, TD-587, TD-588, TD-589, TD-590, TD-591
**Location:** design §5 *The seams* and *Repos*, §4.7 `ao repo init` / `ao board edit` / `ao doctor` **repos**, §4.5a *Repo page: missing seams* and *origin note*, §4.5 screen 6, §4.4 *Repo facts* and *Board write-back*, §4.9a, §6 rule 10, §8; `docs/design-history.md`; the 2026-10-08 ADR's Status line

**Why:** Paul, 2026-10-12: dev-cadence must work for any session with no ShiftLead on the machine, and ShiftLead should recommend dev-cadence but not require it, without the two drifting. The [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md) (decided by Paul the same day) puts the ledger and board formats in a third repo, `ShiftLead/ledgerboard`, read by both with no second parser. Its builds need the design first (CLAUDE.md: a change in behaviour is a change to the design first).

**Fix:** as the ADR's *Builds* row 3 says: §5 gains `gate:`, `worktree_setup:`, `board:`, `commands:` read by the briefs, and ShiftLead's own roster; §4.7 `ao doctor`'s repo rows, `ao repo init` and `ao board edit <done|snooze>`; §4.5a the Repo page's missing-seam lines and the Inbox reading boards in-process (checkout and origin, the origin note derived); §4.9a `ao board edit` for a session's own branch and *What a session does with a decided line* closing it with `ao board edit done`; §6 the review stage with no gate ("no gate: a person merges"); §8 the ADR's rule in place of the 2026-10-08 paragraph. The 2026-10-08 ADR's Status gains "superseded in part by ADR 2026-10-12 (the formats' placement); the rest stands". Help-list wording goes in the build entries, not here.

**Done when** every section the ADR names says what the ADR decided, design-history has the dated line, and TD-585–TD-591 can each be built from the design without a choice.

**Related:** [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md); TD-585–TD-591 (its builds).

---

## TD-585: Vendor ledgerboard and drop ShiftLead's own ledger and board parsers (the ADR's build 4)

**Priority:** High
**Type:** feature
**Added:** 2026-10-12 (ao-dc-decouple, with Paul)
**Owner:** grinder
**Kind:** build
**Status:** Filed 2026-10-13 (ShiftLead/ledgerboard#8): ledgerboard TD-002 — `bold_head` and the `Not right: <what>` form's reading, a v1.1 minor release; this entry is blocked by it instead of the anchor's decision, and closes by vendoring v1.1 and swapping `board.HEAD_RE`, `workorders.head`'s own bold pattern and `board.NOT_RIGHT_FORM` for its calls (a bold run inside a reply's words is no longer a head). Slice 6 (grinder-ao-1, 2026-10-13, #1674): ShiftLead's `pickable` is ledgerboard's — `ledger.entries` takes each entry's `blocked_by` from `lb.pickable` on the same text and archive (no walk of its own), and `Registry` answers `(state, why)`, the why naming what left an item unresolved. Left: a board line's bold head (`board.HEAD_RE`, `workorders.head`'s bold run, the Inbox's `board_head`, `agent_inbox`) and the live look's `Not right: <what>` form (`board.NOT_RIGHT_FORM`) — ledgerboard v1.0 reads neither, and its ledger has no entry for them; the decision (anchor) below is filing that entry in ShiftLead/ledgerboard, after which this entry is blocked by it instead (its old blocker, dev-cadence#TD-106, is archived). Slice 5 (grinder-ao-1, 2026-10-13, #1666, merged): the Inbox's board regexes — `CONTEXT_RE`, `REPLY_MARK_RE` and `board.py`'s `DUE_RE`/`DECIDED_RE`/`ANSWERS_RE` aliases go, the Inbox cutting a row's fields with ledgerboard's own (`lb.CONTEXT_RE`, `REPLY_TAIL_RE`, `DUE_RE`, …; a mid-sentence *Context:* is the field, as ledgerboard reads it); the origin note is chosen by the reading's `fetch_case` and names `fetch_why` (`ORIGIN_PHRASES` goes); `BOARD_FIELDS`/`reader_lacks` go; `SUBHEAD_RE` is markdown and moves to `render.part_heads` (§4.5 screen 6). Left after it, each needing ledgerboard first (the ADR: no second parser): a line's bold head (`board.HEAD_RE`, `workorders.head`'s bold run, the Inbox's `board_head`) and the live look's `Not right: <what>` form (`board.NOT_RIGHT_FORM`; ledgerboard has `LIVE_LOOK_ANSWERS` but no reading of the form), and ShiftLead's own `pickable` derivation (`ledger.entries`) through `lb.pickable`, with `Registry` returning `(state, why)`. Slice 4 (grinder-ao-1, 2026-10-13, #1662, merged): the board writes through ledgerboard — `board.py`'s `edit_line`, `item_line`, `decided_line` and `message()` are ledgerboard's calls with `subject("shiftlead", …)`, the three adds one `append` (`add` loses `entry`, `add_decided` its `ref`); Done appends `Closed:`; a decide on a decided line and an answer carrying a field's name stay refused in front of the call; the answer in a subject clipped at 80 and the subject at 250 (§4.4 *Board write-back*). `board.py` still names `DUE_RE`, `DECIDED_RE`, `ANSWERS_RE` (ledgerboard's, aliased), `HEAD_RE` and `NOT_RIGHT_FORM` for the Inbox and `agent_inbox`. Slice 3 (#1659, merged): the board read in-process — `workorders.read_boards` parses through ledgerboard (`parse_board`, `item_record`, `item_key`) and makes its own bounded fetch and three-way compare against origin, with `fetch_case` and `fetch_why` beside `fetch_note`; the line key and `ao board show` are ledgerboard's; no `nudge_user_attention.py` is run, and `READER`, `can_name`, the Inbox's *carries no reader* note and `ao board show`'s *no board reader* refusal go (§4.5 screen 6 *Boards are read against origin*). Slice 2 (#1652, merged): the ledger read through ledgerboard — `sessionorc/ledger.py` and `reports.py` keep no ledger line-shape regex (headings, fields, `Blocked by` items, `Answers:` and the diff walkers are ledgerboard's; `Kind: live-check #<n>` past its word stays ShiftLead's). Slice 1 (#1647, merged): the vendoring — `scripts/vendor_ledgerboard.sh <tag>` (the wheel copy and the fixtures only, with `tests/ledgerboard/MANIFEST`), `src/sessionorc/ledgerboard.py` at v1.0, the ruff exclusion, and `tests/test_ledgerboard_fixtures.py` (byte-equal to `scripts/ledgerboard.py`, the header's hash and the MANIFEST's tag, every vendored file as vendored, the release's fixtures). Left: slice 5, the Inbox's regexes (`src/shiftlead/ui/inbox.py`, grinder-ao-2's file, named at the claim — `board_body`, `board_text`, `CONTEXT_RE`, `SUBHEAD_RE`, `REPLY_MARK_RE`, `ORIGIN_PHRASES` derived from `fetch_case`, `BOARD_FIELDS`/`reader_lacks` — whose note still says *sync dev-cadence's files*, the techlead's note on #1659), with `board.py`'s and `agent_inbox`'s remaining `HEAD_RE`/`NOT_RIGHT_FORM` and `Registry` as `(state, why)`. Was: Open — ledgerboard v1.0 is released (ShiftLead/ledgerboard, tag `v1.0`; its `fixtures/run.py` and `SPEC.md`), and dev-cadence vendors it (its TD-106). Moving to it changes four things ShiftLead does today — each is v1.0 keeping dev-cadence's behaviour, the definition until now: (1) `done` appends `Closed: <today>.`, where `board.py` only ticks; (2) `decide` on a decided line rewrites it — keep `board.py`'s refusal as a check in front of the call; (3) `decided_line`/a reply refuse `Context:` and `Closed:` in the words as well as `Answers:`/`Decided:`; (4) the subjects are `subject()`'s — `reply <head>` not `reply on <head>`, the head by `edit_head()` (prefix and fields dropped, 60 chars) not the bold run, and `append` for every add (the three old insert subjects still read as appends). `item_line` takes `(text, due, today, session, host, context)`, as `board.py`'s does; the ADR's shorter signature omits `today`. A resolver may return `(state, why)` or a mapping. Was: Open.
**Blocked by:** ledgerboard#TD-002
**Location:** `src/sessionorc/{ledger,board,reports,workorders}.py`, `src/shiftlead/ui/inbox.py`, new `src/sessionorc/ledgerboard.py` and `scripts/vendor_ledgerboard.sh` (both created by this entry), `pyproject.toml` (ruff exclude), `tests/`

**Why:** Paul, 2026-10-12: dev-cadence must work for any session with no ShiftLead on the machine, and ShiftLead should recommend dev-cadence but not require it, without the two drifting. The [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md) (decided by Paul the same day) puts the ledger and board formats in a third repo, `ShiftLead/ledgerboard`, read by both with no second parser. ShiftLead parses both formats itself today (`sessionorc/ledger.py`, `board.py`, the Inbox's regexes) and runs dev-cadence's `nudge_user_attention.py` for the board.

**Fix:** as the ADR's *Builds* row 4 and *How ledgerboard is consumed* say: the dev-cadence sync PR that brings `scripts/ledgerboard.py` also runs `vendor_ledgerboard.sh 1.0` (fixtures and the wheel copy only); every line-shape regex in the modules listed goes to ledgerboard calls; `board.py`'s `message()`, `item_line()`, `decided_line()` become ledgerboard calls with `tool="shiftlead"`, its three insert subjects collapsing into `append`; `Registry` returns `(state, why)`; the Inbox reads the checkout's board and origin's itself and derives the origin note (`ORIGIN_PHRASES`, `BOARD_FIELDS`, `BOARD_SOURCE` go); the ruff exclusion; the byte-equality, header-hash and fixture tests. Tests rewritten, each assertion listed here as it is changed: `tests/test_board.py` (subjects, `DECIDED_RE`), `test_ui_inbox*.py`, `test_reports.py`, `test_workorders.py`, `test_ledger*.py`.

**Done when** `git grep` finds no ledger or board line-shape regex outside `ledgerboard.py` in `src/`, the Inbox runs no dev-cadence script, and the suite passes.

**Related:** [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md); ledgerboard#TD-001 (release v1.0); ledgerboard#TD-002 (v1.1: the bold head and the `Not right:` form); dev-cadence#TD-106 (dev-cadence vendors it).

---

## TD-587: `board:` path key and `ao board edit` (done, snooze) for a session's own branch

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-12 (ao-dc-decouple, with Paul)
**Owner:** grinder
**Kind:** build
**Status:** Open.
**Blocked by:** TD-585
**Location:** `src/shiftlead/repoconfig.py`, `src/shiftlead/cli.py`, `src/sessionorc/board.py`, §4.7's help list (`src/shiftlead/ui/help.py`)

**Why:** Paul, 2026-10-12: dev-cadence must work for any session with no ShiftLead on the machine, and ShiftLead should recommend dev-cadence but not require it, without the two drifting. The [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md) (decided by Paul the same day) puts the ledger and board formats in a third repo, `ShiftLead/ledgerboard`, read by both with no second parser. A session closes a decided board line with `scripts/board_edit.py`, a dev-cadence script, so a repo without dev-cadence cannot.

**Fix:** per the ADR: `board:` (default `docs/user_attention.md`) read by every board reader; `ao board edit <done|snooze> --line <n> --expect "<start>" …` (`--board` defaulting to `board:`) calls ledgerboard's `edit_line()` and commits with `subject("shiftlead", …)` on the current branch, touching nothing else; no `decide` or `reply` (cadence §3.5: the person's words, write-back only). And `--key board:<key>` in place of `--line` and `--expect` (§4.7): the line found by its id as `ao board show` finds it (`workorders.show`, `workorders.ref`; TD-607 built the id, this verb's flag waits for the verb).

**Done when** a session closes and snoozes a line on its branch in a repo with no `scripts/`, the commit carries the ledgerboard subject, and `decide`/`reply` are refused, with tests.

**Related:** [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md); ledgerboard#TD-001 (release v1.0); dev-cadence#TD-106 (dev-cadence vendors it).

---

## TD-588: Briefs, flows and `team_skill.md` name no repo's layout: `commands:`, variables, and a test that bars the literals

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-12 (ao-dc-decouple, with Paul)
**Owner:** grinder
**Kind:** build
**Status:** Open.
**Blocked by:** TD-586, TD-587
**Location:** `src/shiftlead/briefs/*.md`, `src/shiftlead/flows/**/*.md` (five), `src/shiftlead/team_skill.md`, `repoconfig.py`/`teams.py` (the filling), this repo's `.shiftlead.yml` and own brief

**Why:** Paul, 2026-10-12: dev-cadence must work for any session with no ShiftLead on the machine, and ShiftLead should recommend dev-cadence but not require it, without the two drifting. The [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md) (decided by Paul the same day) puts the ledger and board formats in a third repo, `ShiftLead/ledgerboard`, read by both with no second parser. The built-in briefs hard-code this repo's layout (`pdm run test`, `docs/cadence.md`, `scripts/check_cadence.py`, `scripts/board_edit.py`, `docs/design/`), so a repo without dev-cadence, or with another layout, gets wrong instructions.

**Fix:** per the ADR's *Briefs and flows name no repo's layout* and its `commands:` seam: `.shiftlead.yml`'s `commands:` (`test`, `lint`; today accepted and read by nothing) is read by `repoconfig.py` and fills `{test}` and `{lint}`; `{ledger_check}` defaults to `python3 scripts/ledger.py --check` and `{cadence_rules}` to "read docs/cadence.md §1–§4" only when those files exist, each otherwise the seam's sentence; the variables: `{gate}`, `{board}`, `{ledger}`, `{ledger_check}`, `{test}`, `{lint}`, `{design_dir}`, `{cadence_rules}`; an unset one fills with a sentence naming the seam, never empty; `{pr}` inside `{gate}` filled after; this repo's specifics move to its own `.shiftlead.yml` and brief; a session's board edit is `ao board edit` (TD-587); a test fails on `docs/cadence.md`, `/cadence`, `scripts/`, `docs/technical_debt.md`, `docs/user_attention.md`, `docs/design/` or `pdm run` outside a variable. A repo with no gate (§5 *The seams* `gate:` unset and no `scripts/check_cadence.py`) fills the briefs' gate step with *no gate: a person merges* (§6 rule 10, §4.9c) — what TD-586 records and nothing draws yet.

**Done when** `commands:` is read, the test passes, and a brief filled for this repo reads as it does today.

**Related:** [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md); TD-586, TD-587.

---

## TD-591: `ao doctor` and the Repo page name what a repo lacks; `ao repo init` makes an empty ledger

**Priority:** Low
**Type:** feature
**Added:** 2026-10-12 (ao-dc-decouple, with Paul)
**Owner:** grinder
**Kind:** build
**Status:** Open.
**Blocked by:** TD-586, TD-587, TD-589
**Location:** `src/shiftlead/doctor.py`, `src/shiftlead/ui/repo.py`, `src/shiftlead/cli.py`, §4.5a/§4.7 help (`src/shiftlead/ui/help.py`)

**Why:** Paul, 2026-10-12: dev-cadence must work for any session with no ShiftLead on the machine, and ShiftLead should recommend dev-cadence but not require it, without the two drifting. The [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md) (decided by Paul the same day) puts the ledger and board formats in a third repo, `ShiftLead/ledgerboard`, read by both with no second parser. Every dev-cadence feature ShiftLead uses switches itself off silently when the file is absent.

**Fix:** per the ADR's *Says what is missing*: `ao doctor` gains repo rows and the Repo page a line per unset seam (no gate, no board, no worktree setup, no ledger); `ao repo init` writes an empty ledger in ledgerboard format at `ledger:`.

**Done when** a repo with only a ledger shows each missing seam on the Repo page and in `ao doctor`, and `ao repo init` on a bare repo makes a ledger ShiftLead reads, with tests.

**Related:** [ADR 2026-10-12](decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md); TD-584 (the design: what it draws and from where), TD-585 (the vendored `ledgerboard.py` that `ao repo init`'s ledger and the ledger check read), TD-586 (the missing-gate line).

---

## TD-611: The UI's single event loop stalls the Focus terminal: two bulk polls render megabytes synchronously several times a minute, and both grow with the inbox, the fleet and the PR count

**Priority:** High
**Type:** debt
**Added:** 2026-10-12 (ao-paul; measured by two read-only agents on the live UI)
**Owner:** grinder
**Kind:** live-check #1660
**Status:** Open — slice 1's page half in PR #1610 (2026-10-12, grinder-ao-2): `/api/person/inbox?counts=1` answers the top bar's numbers from `inbox_sections` with nothing rendered, and every page but the Inbox page and a message page polls it. Left of slice 1: `ao inbox --counts` — the counts are the UI's (state rows, the board horizon), not the host agent's, so a shell read needs either the UI's endpoint or a home read of the board; its own slice (TD-616's §4.7 `ao inbox` once TD-614's design lands). Slice 5 in PR #1615 (2026-10-12, grinder-ao-2): the bridge's queue bounded in bytes (`QUEUE_HIGH` / `QUEUE_LOW`, the pty unread between) and each send everything queued. Slices 3–4 are TD-617's. Slice 2 in PR #1619 (2026-10-12, grinder-ao-2): `/api/person/inbox` builds its sections, markup and JSON on a worker thread (`asyncio.to_thread`), gzipped there when the browser takes it, so nothing the size of the inbox runs on the loop; per-endpoint rather than `GZipMiddleware`, which compresses on the loop. Not built: the cap on *answered for you* with a *show more* — a control §4.5a does not have, so a design round's if the re-measurement still wants it (Dismiss all, TD-602, shrinks the group today). What is left is TD-616's and TD-617's; once both merge this entry is the live check its *Done when* names. Live read 2026-10-14 (grinder-ao-2, `9bb725c` live, journal and headless reads only): the bulk polls are gone — no `GET /api/sessions` at all, and the full `/api/person/inbox` only from the Inbox page (`watching=1`, 15 in the busiest hour of four, against ~540 an hour before); `counts=1` only at a page's load or while its stream is down (~10–20 an hour). **The loop is not yet quiet**: a static-file probe every 50 ms for 75 s holds p99 5 ms, max 20 ms with no stream open, but with one Focus stream (`light=1&focus=`) 8 probes over 50 ms (max 139 ms), and with the Org stream 33 (max ~300 ms in a 150 s run). Each Focus stream receives every repo's whole facts on every `repos` push, ~1.2 MB a minute (shiftlead's 755 KB), to read `pr_marks` alone, and further 45–85 ms holds come between its events. What is wrong is TD-670; the re-measurement waits on it.
**Blocked by:** TD-670
**Location:** `src/shiftlead/ui/static/app.js` (`refreshInboxCount` ~L1198 and the 20 s interval ~L1259 that runs it, or the Inbox's `refreshInboxPage`; Focus's `refreshMembership` ~L4370, called on a peer's event ~L4436); `src/shiftlead/ui/app.py` (`api_person_inbox` ~L3025–3105, `api_sessions` ~L2359, `events` ~L3381–3570); `src/shiftlead/ui/cards.py` (the `pr_marks` map ~L327); `src/shiftlead/ui/pty_bridge.py` (the queue ~L27, the pump ~L185)

**Why:** Paul, 2026-10-12: the Focus terminal lags again, better after TD-572 (#1544) and slower by the day since. The pty bridge shares `shiftlead-ui`'s one asyncio loop with every handler, so any synchronous render holds every keystroke and output frame. Measured on the live UI (about an hour after a promote):
- `shiftlead-ui` averages ~17% of a core. The journal shows ~540 `GET /api/person/inbox` and ~200 `GET /api/sessions` an hour, and almost nothing else.
- `/api/person/inbox` is **2.74 MB** and costs ~0.5 s of loop CPU per call. Six concurrent calls all finish at ~2.7 s, so they serialise, and a static file went from 3 ms to 102 ms behind one. Every page polls it every 20 s (`refreshInboxCount`) only to read the top bar's counts. The handler renders every section's markup each time: *answered for you* 1.23 MB for 168 rows, *needs* 418 KB, horizon 175 KB, ledger 120 KB, and `entries` 673 KB besides. It grows with the retained person inbox (193 entries, 25–45 a day).
- On Focus, every other-session event calls `refreshMembership`, which fetches the whole `/api/sessions`: **456 KB**, ~0.29 s, a `view()` of all 24 sessions plus `repo_facts`. That is ~200 an hour, in bursts of 6–14 a minute. 214 KB of it is `pr_marks`, a per-session map of every PR, which grows without bound.
- The Org page's full `/events` stream runs `view()`, `compact_in` and `render_card` per delta, per connected client, inline, plus `fresh_heads` on every reshaping delta. Seven connections were open.
- The pty bridge queues frames in an unbounded `asyncio.Queue` and sends one chunk per frame. Whenever the loop stalls, output arrives late and in a burst.

Together that is roughly 6–10 minutes of loop stall an hour, and it grows.

**Fix:** in slices, each its own PR, the first alone taking the stall off Focus:
1. **A counts-only read.** One function computes the top bar's numbers (`needs`, `fyi_n`, overdue, `answered_marks`, the build chip) without rendering anything. `/api/person/inbox?counts=1` serves it, and `refreshInboxCount` uses it on every page but the Inbox. `ao inbox --counts` prints the same numbers: no shell command counts the person inbox's sections today, and a session's `ao inbox --unread` marks what it reads.
2. **The Inbox's own render off the loop.** Run it in `asyncio.to_thread`, or cache it keyed on the inbox's revision and the boards' reading. Add `GZipMiddleware`. Cap *answered for you* at the newest N, with a *show more*.
3. **Focus membership without `/api/sessions`.** Read it from the `focus=` stream's fleet, or from a one-session endpoint. Trim the list view's `pr_marks` to the PRs drawn and drop `tail`.
4. **The Org stream.** Compute heads and card renders once per delta and fan them out to the clients, or coalesce deltas to about one a second. *Built as TD-617 (TD-614's design), with slice 3's Focus membership and `pr_marks`; slice 1's counts read is TD-616's fallback.*
5. **The bridge.** Bound the queue, and join every drained chunk into one send.
- Tests: the counts read renders no template and equals the full read's counts; Focus issues no `/api/sessions` on a peer's delta; the bridge coalesces queued chunks.

**Done when** a Focus tab sees no request above ~50 ms of loop time in steady state, `/api/person/inbox` is fetched only by the Inbox page, the UI's CPU falls well under today's ~17%, and the tests above pass. A re-measurement after the promote, journal counts and a static-file latency probe during a poll, is the live check.

**Related:** TD-572 (archived: the light events stream for Focus), TD-599 / TD-602 (archived: *answered for you*'s Dismiss all; pressing it shrinks the largest section today), TD-131 (whole-file reads, a later scale).

---

## TD-614: The UI and `ao` re-derive what the host agent could hold once: inbox counts, the board reading, per-session views — poll-and-render instead of one reading pushed

**Priority:** High
**Type:** debt
**Added:** 2026-10-12 (ao-paul, at Paul's ask)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-12 (the designer) — **one owner per reading, pushed** (§4.4 *Each reading has one owner, and a client never re-derives it*): (1) **the boards are the host agent's** — `boards` on the repo reading, read every `BOARD_EVERY` (60 s) and at once after a write-back, origin fetched on `REPOS_EVERY`, the work orders derived from it, pushed with `repos`; the UI's `read_boards`/`BOARD_TTL` and `ao`'s own read go; (2) **the Inbox's counts are the UI process's, not the host agent's** — the honest answer to Paul's question: they are the Inbox's sections, classified by `shiftlead` code (state rows, the board horizon, the ledger's *for you*, review marks), and `sessionorc` never imports `shiftlead`; so the host agent pushes `inbox` with a revision on every person-inbox change, the UI recomputes the counts once per input change and pushes `counts` on every stream, the top bar polls nothing, TD-611 slice 1's counts read is the fallback (`since=<rev>` → `unchanged`), and `ao inbox --counts` runs the same template-free function; (3) per-session views once per delta for every stream, PR marks once per repo on the `repos` push, Focus's members from its stream — TD-611's slices 3–4 built in this form as TD-617; (4) said no to a revision on every record, a cache layer, and moving the Inbox's classification into `sessionorc`. No mockup: nothing drawn changes. Built by TD-615, TD-616, TD-617. Was: Open.
**Blocked by:** TD-615, TD-616, TD-617
**Location:** design §4.4 (*Repo facts*, *Board write-back*), §4.5 (the `/events` stream; the top bar, the Inbox), §4.7 (`ao inbox`, `ao board show`); `src/shiftlead/ui/app.py` (`read_boards` ~L372, `api_person_inbox`, `api_sessions`, `events`); `src/shiftlead/ui/inbox.py` (`board_argv`, `BOARD_TTL`); `src/shiftlead/cli.py` (its own board read ~L1502); `src/sessionorc/agent_tick.py` (the repo reading's `workorders.read` ~L2904, every `REPOS_EVERY`)

**Why:** Paul, 2026-10-12, on TD-611's `ao inbox --counts`: *should we have the host agent run it and maintain counts somewhere to reduce burden even further? are there other centralizations we should make as well?* Today three processes compute the same things on their own clocks:
- **The board.** The host agent runs every repo's board reader every `REPOS_EVERY` (300 s) for the work orders. The UI runs it again every `BOARD_TTL` (60 s) for the Inbox's rows, and `ao` runs it a third time. That is three subprocess runs of one file, each with its own failure note.
- **The person inbox's counts.** The host agent holds the person inbox, but the UI computes *needs*, FYI, overdue and *answered* by fetching and rendering all of it (TD-611), on every page every 20 s.
- **Per-session views.** `/api/sessions` and the Org stream rebuild `view()` for every session on every request or delta, per client. `pr_marks` repeats one repo's PRs once per session.

**Fix:** design first. One principle: **the host agent keeps each reading once and pushes changes; clients read the reading, never re-derive it.**
1. **One board reading** in the host agent: every board's items, read by the reader on the repo reading's clock and at once after a write-back, with the work orders derived from it. The UI's Inbox rows and `ao board show` read it over RPC, so the UI stops running the reader.
2. **Inbox counts kept by the host agent:** recomputed whenever the person inbox, a board reading or the fleet changes, and pushed on the events stream as an `inbox` delta. The top bar updates from the stream with no poll. `ao inbox --counts` (TD-611 slice 1) reads the same numbers. TD-611's counts endpoint becomes the fallback for a client with no stream.
3. **Per-session views computed once per delta** and fanned out to every client (TD-611 slice 4 in this form), with `pr_marks` sent once per repo, not once per session.
4. Weigh, and say no where it does not pay: a revision number on each reading so a client can ask *changed since n?*; the PR and ledger readings are already central (*Repo facts*).
- Mockups: none, since nothing drawn changes. §4.4 says which readings exist and who reads them.

**Done when** the design names each reading's one owner and its push, and build entries exist for each slice. TD-611's slices 1 and 4 are re-pointed at them or marked as their first step.

**Related:** TD-611 (the lag that found it), TD-131 (whole-file stores, a later scale), TD-384 (work orders from the board).

---

## TD-622: #1563's `AO.shellHere` — the *tab* wording of the blocked-pop-up toast, the close on a create that answers without an id, and the placeholder's directory fallback — are held by no test

**Priority:** Low
**Type:** debt
**Added:** 2026-10-12 (test-audit-ao-1, auditing #1563)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Location:** `src/shiftlead/ui/static/app.js` (`AO.shellHere`), `tests/test_ui_popout.py` (`SHELL_PROBE`, `test_open_shell_here_opens_beside_the_page_it_was_pressed_on`)

**Why:** #1563 (TD-579) has a node probe and a source-shape test, and its docstring says *a blocked open creates nothing and says so* and that the placeholder *reads "opening a shell in <dir>…"*. Probe: each change below, one at a time, then `PYTHONPATH=$PWD/src pytest -q tests/test_ui_popout.py`: every one still passes (7 passed).
- `const what = asWindow ? "window" : "tab";` → `const what = "window";`: the probe blocks only the window form (`AO.shellHere("a", "/repo/x", true)`), so a blocked *tab* — the plain press, the common one — saying *the browser blocked the window* is read by no test.
- `if (!res || !res.id) { …w.close()…; return res; }` removed: a create that answers without an `id` leaves the placeholder tab open at *opening a shell in …* for good; the probe's `AO.act` returns an id or throws, never `{}`.
- `dir || "this session's directory"` → `dir || "x"`: the probe always passes `/repo/x`, so the fallback sentence (a card whose `data-dir` is empty) is never drawn.
The window's `w.name` assignment, by contrast, is caught.

**Fix:** extend `SHELL_PROBE`: a blocked open with `asWindow` false (the toast names the tab, nothing created), an `AO.act` that answers `{}` (the placeholder closed, no `href` set), and a press with an empty `dir` (the placeholder names the session's directory). **Done when** each probe above fails a test.

**Related:** TD-577, TD-579 (#1563).

---

## TD-623: No document says how a repo gets its first ShiftLead team

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-09 (Paul, while starting guardians' team)
**Owner:** designer
**Kind:** design-first
**Status:** Open. Standing up guardians' team (2026-10-09) needed facts spread across design §4.4a,
§4.9, §4.9b, §4.9c, `docs/briefs/README.md`, the package role templates, two working examples
(contractmatch's and dev-cadence's repo config and briefs) and TD-299's step list. A session
in the new repo had to be handed a brief written from all of them.
**Blocked by:** decision (paul) — when guardians-devenv TD-028's *doc gaps* list (a first run to learn from) is enough to write from
**Location:** a new how-to (where it lives is part of the fix: the README's *Run it*, a
`docs/` page, or `ao`'s skill text), `docs/briefs/README.md`, design §4.9.

**Why:** every repo that joins repeats the same search, and a brief written from memory goes stale
(the retired `guardians-orchestrator.md` did: it said the repos were not on kmaster and the
devcontainer question was open, both untrue by the time it would have run).

**Fix:** one page, in order: what the repo must have first (the cadence, §4, a ledger whose entries
carry `Blocked by:` so a worker can pick), `.shiftlead.yml` (teams, flows, `held:`), the briefs as
supplements and the techlead primer, `ao org check`, `ao team start` on the host, then the
container node (`hosts.yml`, the node's `env` and logins, `ao host up`, `place:`) — and which of
those are the person's. Fold in each gap guardians-devenv TD-028 records, and say what a
constellation (an umbrella ledger, PRs in sibling repos) does differently.

**Done when:** a session in a repo with no team stands one up from that page alone, without a
brief written for it.

**Related:** TD-299, guardians-devenv TD-028 and `docs/briefs/team-setup.md`, TD-055 (archived
with the retired brief).

---

## TD-627: The Focus Git card's changed files are plain text: make each a link that opens it in the person's editor, as the Session card's recent files do

**Priority:** Low
**Type:** feature
**Added:** 2026-10-13 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — each path on the Git card is a link by the Session card's **recent files** form: the editor button's file template with the path joined to the worktree, no `:line`, the two launches unless *opens the folder first* is off, drawn only where the editor button is (text under `open_in: none` and on another host's record); the status code stays text. **Not a file stays text**: a deletion (`D`, nothing to open) and an untracked directory (`?? dir/`, a folder form would open its own window), each with a hover saying why; a rename carries its new path only (the porcelain line's) and links it; a conflict (`UU`) links as any change. §4.5a *Focus side panel, Git card: changed files*. No mockup: the card's text is unchanged but for the links. Built by TD-628. Was: Open.
**Blocked by:** TD-628
**Location:** design §4.5 item 4 (the side panel's **Git** card), §4.5a (*Focus side panel* rows: **recent
files**, **diff / log / PRs**), §4.6 *A path in the pane is a link*, §5 `person.open_in` / `person.file_link`;
`src/shiftlead/ui/templates/focus.html` (`#gitfiles`), `src/shiftlead/ui/static/app.js` (the `#gitfiles`
redraw, `AO.recentFiles`, `AO.openFile`, `AO.fileUrl`), `src/sessionorc/gitinfo.py` (`GitInfo.files`:
porcelain lines, repo-relative).

**Why:** Paul (2026-10-13): *our git card in the focus session screen shows modified files — add links
to those files so they can be opened in vscode/other (leverage our other open file flows).* The Git
card draws `GitInfo.files` (up to twenty `M path` / `?? path` lines) as text, while the Session card's
**recent files**, a terminal path and Settings' **Open file** already open a file in the person's
editor; the Git card is open by default and the Session card folded, so the file a person sees first
is the one they cannot open.

**Fix:** design first, since a control is a §4.5a row: each path on the Git card a link by the
recent files' form — the editor button's file template, the two launches unless *opens the folder
first* is off, drawn only where the editor button is, text under `open_in: none` — with what a path
that is not a regular file does (a deleted one, an untracked directory under `--untracked-files=normal`,
a rename's old side). The build reuses `AO.openFile`; nothing is parsed from the screen. **Done when**
a click on a changed file on the Git card opens it in the person's editor.

**Related:** TD-525, TD-532, TD-536, TD-538 (recent files and the file link).

---

## TD-628: Build TD-627: each path on the Focus Git card a link by the recent files' form; a deletion and a new directory stay text

**Priority:** Low
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-627's round)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Location:** design §4.5a *Focus side panel, Git card: changed files* (beside *recent files*); `src/shiftlead/ui/templates/focus.html` (`#gitfiles` ~L234: each line split into its status code and its path, the path an `<a>` as the recent files draw theirs), `src/shiftlead/ui/static/app.js` (the `#gitfiles` redraw ~L4248: the same split and link; the press through `AO.openFile`, as the recent files' is), `src/sessionorc/gitinfo.py` (`GitInfo.files` ~L26: read only — `"<code> <path>"`, a rename's new path, `?? dir/` for a new directory); `tests/test_ui_focus*.py` or `tests/test_ui.py` (the Focus page's pieces)

**Why:** TD-627: Paul, 2026-10-13 — *our git card in the focus session screen shows modified files — add links to those files so they can be opened in vscode/other (leverage our other open file flows)*; the Git card is open by default and its files are plain text, while the folded Session card's recent files open.

**Fix:**
1. Split each `GitInfo.files` line at its first space into the code and the path; draw the code as text and the path as the recent files' link (`data-file` the path joined to the worktree's root — a porcelain path is relative to it, which is the record's directory or above it, as `app.js` ~L3631 resolves one for `isChanged` — the same class and handler), on first render and on the delta's redraw.
2. Text, with a hover, for a line whose code ends in `D` — `D`, `MD`, `AD`, `RD` (*deleted in the worktree*; TD-632) — and a path ending in `/` (*a new directory: open it from the worktree's window*); a file deleted and made again lists as `D` (text) and `??` (a link).
3. No link where the editor button is not drawn (`open_in: none`, another host's record): the lines as today.
4. Tests: a modified, an untracked and a conflicted path are links with the joined path; `D`, `MD`, `AD` and `RD` lines are text with the deletion's hover, a `D c` with a `?? c` beside it draws the first as text and the second as a link, and a `dir/` text with its hover; under `open_in: none` every line is text; the delta's redraw draws the same as the first render.

**Done when** a click on a changed file on the Focus Git card opens it in the person's editor by the same file link as the recent files, a deletion and a new directory stay text saying why, and the tests above pass; the builder's look (design §4.9b) is named in the PR.

**Related:** TD-627 (the design), TD-525, TD-532, TD-536, TD-538 (recent files and the file link).

---

## TD-630: Pictures and files cannot go into the Add entry form: a screenshot of what is wrong needs a session opened first

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (Paul, through Add entry; drafted by ao-shiftlead-entry-4)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer; mockup `AddEntry.dc.html`, shot `docs/mockups/reviews/2026-10-13-td630-add-entry-attach.png`) — the composer's road on the form's **What** (Attach, drop, paste; pieces, bound, names, progress); **where a file lands before a session exists**: a **draft folder** at the home, `~/.shiftlead/attachments/<draft>/`, its token minted by the host agent on the form's first file (`attach` takes `draft` in place of a session id), **the path inserted final** — neither way out moves a file, since the person's words name it; **at the press** the draft is claimed: *Open a session* hands it to the create and the folder lives as that session's files do; *Hand to the techlead* carries it on the `ask` and the folder is kept `runs_keep_days` from the hand; **an abandoned form** leaves an unclaimed draft the hourly sweep removes an hour after its last write, as a stale `.part`. A node-hosted team's form refuses it in place. §4.5a *Add entry form: Attach / drop / paste*, §4.4 *The Add entry form's draft* (the claim a `claimed.json` in the folder), §4.10 *An entry handed to a seat* (`draft` on `entry_add`), §4.6 *Run-log retention*, §4.9. Built by TD-633. Was: Open.
**Blocked by:** TD-633
**Location:** design §4.5a (*Add entry form* rows; the *Focus composer* and *Message and Reply dialog*
**Attach / drop / paste** rows), §4.9 *Add an entry to the ledger*, §4.4 *Attachment drop* and *An
attachment's life*; `src/shiftlead/ui/templates/base.html` (the form), `src/shiftlead/ui/static/app.js`,
`src/shiftlead/ui/app.py` (`/api/entry/hand`, `/api/entry/session`).

**Why:** Paul (2026-10-13): *add a TD so that files/pics can be pasted into the "add entry" form. I had
to open this session to give you those pics* — TD-629's two screenshots went in through this session's
Focus composer, after the session was open, since the form's **What** takes text alone. The composer
and the Message dialog already attach, drop and paste (TD-530); the form, the one door for a thought
had while looking at the Org, is the place a screenshot of what is wrong is most often at hand.

**Fix:** design first, since it is a §4.5a row: the composer's road on the form's **What** — **Attach**,
a dropped file, a pasted image named `paste-<date>-<time>.<ext>`, each path inserted at the caret —
with where a file lands before any session exists (both ways out start or fill one only at the press:
a holding folder moved under the session's `attachments/` at **Open a session**, or under the techlead
seat's at **Hand to the techlead**, and what an abandoned form leaves). **Done when** a screenshot
pasted into the form reaches the drafting session as a path it can read, by either way out.

**Related:** TD-180, TD-219 (the form), TD-530 (the Message dialog's attach).

---

## TD-636: A director seat answers permission prompts for the person: routine ones allowed or denied by written rules, the rest escalated

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (ao-paul, with Paul — the lessons ADR, lesson 1)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — (1) **one director seat per org**, `org.yml`'s `director:` (absent, none: off by default), on call by the trigger *a prompt no rule answered pending on an unattended record*, distinct from the techlead (which answers asks) and replacing a manager's permission triage where defined; (2) **the person's `permissions:` rules per role** in `settings.yml`, the adapter's syntax, matched by the host first at no token cost, then the director's judgement, then the person; **always the person's**: questions and menus, every interactive session's prompt (§9 invariant 5), and any prompt naming `~/.shiftlead`, `~/.claude`, a systemd unit or a path outside the member's worktree and checkout unless denied — the host refuses a rule's or the director's *allow* there, a deny standing as a manager's does today; the director is **the first seat of no team**, written by any team start when the org defines it, trigger `prompt`; a profile's **`permission_prompts: ask`** is what lets an unattended launch keep its prompts (an empty `unattended_args` falls back to the skip today); a rule's or director's answer is an *Answered for you* FYI in the sourced reply's shape, with no Overrule; (4) **every answer told** as an FYI in *Answered for you*, the rule or reason with it; (5) **not *Allow for this session***: no session's settings change, one prompt at a time, rules written by the person; (6) the **`permit`** grant: `decide` on unattended records only. The value: an unattended profile can launch without `--dangerously-skip-permissions`. §4.9b *The director seat*, §4.8 `permit`, §4.2, §5, §10, glossary. Built by TD-641 and TD-642. Was: Open.
**Blocked by:** TD-641, TD-642
**Location:** design §4.2 (the permission relay, Allow/Deny), §4.8 (roles, grants), §4.9 / §4.9b (seats; the techlead seat answers asks for the person), §10 *"Allow for this session"* (decided no, 2026-09-23); `src/shiftlead/briefs/manager.md` (a manager's permission triage)

**Why:** Paul, 2026-10-13: *"I like the idea of filtering permission prompts — essentially allowing a director seat to handle them for the user (we talked about a director seat at one point but have not implemented)."* Every prompt a tool does not pre-allow reaches the person, or a team's manager, which triages its members' prompts by its brief. Muse's Sentinel, Grok Bot's Auto-review rules and Hermes's `smart` approvals all put a second line in front of the person (`docs/decisions/2026-10-13-agent-product-lessons.md`). The glossary's *director* is a position in the control graph (the session whose members are managers), not a seat; no seat answers prompts for the person.

**Fix:** design first. The round settles: (1) the seat — one per home or per team, its preset and brief, and how it differs from the techlead seat (which answers asks) and a manager's triage; (2) what it may answer — written allow/deny rules per role (deterministic, checked first), its own judgement for the rest, and what always reaches the person (a question or menu, anything touching `~/.shiftlead`, `~/.claude`, systemd, another worktree); (3) never an interactive session's prompt (§9 invariant 5); (4) every answer told to the person, as the techlead's are (§4.9b *Everything answered for the person is told to the person*), with the rule or reason; (5) how it squares with *Allow for this session* having been declined; (6) the grant it holds (§4.8). The design names the build entries.

**Done when** the design says who answers which prompts for the person and the build entries are filed with `Blocked by` lines.

**Related:** TD-637, TD-638 (the same ADR's other picks), the manager brief's triage, §4.9b.

---

## TD-637: `ao progress done … --pr <n>` is accepted while the PR's required checks are red or missing

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-13 (ao-paul, with Paul — the lessons ADR, lesson 4)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — (1) **refused while a required check failed** on the exact head, in words naming them; **accepted as *checks pending*** while one runs, rule 10 reading it again and a later failure its *fail*, the declaration standing (invariant 10); (2) **green reads the base branch's required checks** — protection and rulesets, read with the repo reading as `required` — and every run on the head where nothing is required; a non-required failure refuses nothing and is named; (3) a **merged** PR is accepted unread, a repo with **no CI** accepted, a **read the home could not make** accepted with *checks unknown*, a PR closed unmerged accepted and said; (4) **`check_cadence.py`'s `ci` row** reading the required set is dev-cadence's change, filed as TD-640. §4.8 *A `done` with a PR is told what its checks read*, §4.7, §6 rule 10. Built by TD-639 and TD-640. Was: Open.
**Blocked by:** TD-639, TD-640
**Location:** design §4.7 (`ao progress done <ref> --pr <n>`), §6 rule 10 (*The cadence check*, run at the home after the declaration); `scripts/check_cadence.py` `row_ci` (reads every check run on the head, not the protected branch's required set; the script is dev-cadence's)

**Why:** Paul, 2026-10-13: *"I agree an agent should not say its done if its PR is not green."* Today the declaration is accepted and checked afterwards on the reports' cadence: the member is told its failing rows, and a second fail becomes an Inbox row. Hermes Agent's PR completion contract refuses a task's completion until the required checks pass on the exact head (`docs/decisions/2026-10-13-hermes-agent.md`).

**Fix:** design first. The round settles: (1) `done … --pr <n>` refused, in words naming the failing or missing checks, while the PR's head is not green — or accepted as *done · checks pending* and turned into a refusal only when they fail; (2) what "green" reads — the protected branch's required checks (and rulesets) on the exact head, falling back to every run when the repo protects nothing; (3) a merged PR (already through the forge's gate) and a repo with no CI; (4) whether `check_cadence.py`'s `ci` row reads the required set too (a dev-cadence change). The design names the build entries.

**Done when** the design says what `done … --pr` does on a red or pending head and the build entries are filed.

**Related:** TD-636, TD-638, TD-618 (the PR `checks` mark), §6 rule 10.

---

## TD-638: A commit names the session that made it, not the model: as tools and models multiply, which model did what is lost

**Priority:** Low
**Type:** feature
**Added:** 2026-10-13 (ao-paul, with Paul — the lessons ADR, lesson 8)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — (1) **one trailer, `Agent-Model: <adapter>/<model>`**, not a second `Co-Authored-By` (a model is no git identity, and the forge draws a co-author as a person); (2) **the hook reads a file**, `AGENT_MODEL_FILE` (`<absolute git-dir>/shiftlead-agent-model`, one per worktree), which the host agent writes with the full id whenever the record's model in use is set or changes (both set-sites: the hook's SessionStart and `PostModelSwitch`, the tick's transcript read), with `AGENT_MODEL` (the profile's alias with its adapter, `claude-code/opus`, the full id being unknown at launch) as the fallback, the trailer replaced, not added, on an amend and nothing where neither is set — the synced hook never asks `ao` (§8); (3) a review's model stays the `cadence-review:` line's; a subagent's is not named, the commit being the session's; (4) the hook is dev-cadence's (TD-645), the launch's variables and the file ShiftLead's (TD-644). §4.2, §4.2a, §8. Built by TD-644 and TD-645. Was: Open.
**Blocked by:** TD-644, TD-645
**Location:** `scripts/git-hooks/prepare-commit-msg` (dev-cadence's, cadence §9.9: `Co-Authored-By: $AGENT_NAME <…>` from the `AGENT_NAME` the orchestrator exports); design §4.2a (the model in use, TD-031), §4.3 (a metered profile's `Turn` carries `model`)

**Why:** Paul, 2026-10-13: *"As we start using more models, recording which did what is a good idea. We get some of this by including the session name as a git contributor, but could expand it to list the actual model."* Today a squash commit carries the session's trailer (`ao-paul <ao-paul@shiftlead.placeholder>`) and, from Claude Code's own attribution, `Claude Opus 5.5`; a tool that adds no attribution of its own (Codex, Gemini CLI) leaves only the session, and a mid-run model switch or a subagent on another model is in neither.

**Fix:** design first. The round settles: (1) the trailer's shape (a second `Co-Authored-By` naming the model, or a key such as `Agent-Model:`); (2) where the hook reads the model — an `AGENT_MODEL` exported at launch is stale after a switch, so perhaps the session's record (the model in use, §4.2a) through `ao`; (3) a review's model, which the `cadence-review:` line already names; (4) the hook change goes to dev-cadence (its synced file), shiftlead's part is what it exports. The design names the build entries, one of them dev-cadence's.

**Done when** the design says how a commit names the model that made it and the build entries are filed.

**Related:** TD-636, TD-637, TD-031, cadence §9.9.

---

## TD-640: `check_cadence.py`'s `ci` row reads the base branch's required checks, not every run on the head (TD-637)

**Priority:** Low
**Type:** debt
**Added:** 2026-10-13 (the designer, TD-637's round)
**Owner:** dev-cadence
**Kind:** build
**Status:** Open
**Location:** `scripts/check_cadence.py` `row_ci` (a SYNCED FILE, dev-cadence's: the change is made there and synced)

**Why:** TD-637: ShiftLead's `done … --pr` now reads the base branch's required checks (§4.8), while the cadence check's `ci` row reads every check run on the head; a non-required check that fails fails the row and a required one the forge would block on reads the same as any. Two readers of *green* that disagree tell a member two things.

**Fix:** in dev-cadence, `row_ci` reads the base branch's required set (branch protection's required contexts and the rulesets' `required_status_checks`), passes when those passed on the head, names a failed non-required check as a note, and keeps *every run* where nothing is required; then the sync brings it here.

**Done when** the `ci` row passes a PR whose required checks passed and a non-required one failed, fails one whose required check failed, and dev-cadence's sync lands it.

**Related:** TD-637 (the design), TD-639 (ShiftLead's side).

---

## TD-641: Build TD-636 (1): the person's `permissions:` rules per role, matched by the host at the hook, the always-the-person list, every answer an *Answered for you* FYI

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-636's round)
**Owner:** grinder
**Kind:** build
**Status:** Slice 1 built (grinder-ao-1, PR #1697): the rules at the hook, deny before allow, the always-the-person check (`sessionorc/permits.py`), the FYI with answerer `rules` (a reply to it refused), `permissions` on the settings read with `malformed`, `permission_prompts`. **Left: slice 2, the pages** (`src/shiftlead/ui`, grinder-ao-2's half): the *Answered for you* row whose `answered.answerer` is `rules` draws Dismiss alone and names `settings.yml`'s `permissions:` (§4.5a), and the Settings page draws `permissions.malformed` where it names a refused value. Slice 3 built (grinder-ao-1): a node answers by rule only while its link is up and once the home has filed the FYI over it (`answered_by_rule`, a request; the home's `_take_answered_by_rule`, the asker by its address); a link down or a filing refused leaves the prompt for the person.
**Location:** design §4.9b *The director seat answers permission prompts for the person* (line 1 and *What always reaches the person*), §4.2 (the relay), §5 `settings.yml` `permissions:`; `src/sessionorc/settings.py` (the key, checked: a role name, `allow`/`deny` lists of strings), the adapter (`src/shiftlead/adapters/claude_code/`: a `rule_matches(rule, tool, input)` in Claude Code's `Tool(pattern)` syntax, the core naming no tool), the host agent's `PermissionRequest` path (`src/sessionorc/agent_hook.py`: match before the waiter; a deny over an allow; answered through the hook with the rule as reason), the always-the-person check (a path under `~/.shiftlead` or `~/.claude`, a systemd unit, outside the record's worktree and checkout — one function, used here and by TD-642's `permit`), the *Answered for you* FYI (`src/sessionorc/agent_mail.py` ~L671 writes one only for a reply with `source` today: a host-written one in the same `answered: {question, asker, answerer, source}` shape, `models.py` ~L390, the prompt as question, the member as asker, `rules` as answerer, the rule as source; the row draws no Overrule for it), the profile key (`src/shiftlead/profiles.py` ~L48 and the adapter ~L533: `permission_prompts: ask | skip`, the skip flag added only under `skip`, the default); `tests/test_hook*.py`, `tests/test_agent*.py`, `tests/test_mail.py`, `tests/test_profiles*.py`

**Why:** TD-636: Paul, 2026-10-13 — *filtering permission prompts*; the first line in front of the person is the person's own rules, at no token cost.

**Fix:**
1. `settings.yml` `permissions: {<role>: {allow: [...], deny: [...]}}`, read by the host agent; a malformed rule is named where the Settings page shows settings, and ignored. `profiles.yml`'s `permission_prompts: ask | skip` (default `skip`): the adapter adds `--dangerously-skip-permissions` to an unattended launch only under `skip`.
2. At the hook, for an **unattended** record only: the role's `deny`, then its `allow`; an *allow* of a prompt on the always-the-person list (a path under `~/.shiftlead` or `~/.claude`, a systemd unit, outside the record's worktree and checkout) is not made — the prompt goes on — while a deny of one stands; a match answers through the hook with *rule: <the rule>* as the reason.
3. Every answer by a rule: one FYI in the person inbox's *Answered for you*, the `answered` shape filled as the design says; no Overrule on its row, the row naming `settings.yml`'s `permissions:` instead.
4. An interactive record's prompt and a question or menu are never matched.
5. Tests: an allow rule answers and writes the FYI; a deny wins over an allow; an allow of a prompt naming `~/.shiftlead` is not made and a deny of one is; `permission_prompts: ask` launches without the skip flag and the default with it; an interactive record is never matched; a question is never matched; no rules leaves everything as today.

**Done when** a prompt on an unattended member that the person's rules cover is answered at once by the host with the rule as reason and told in *Answered for you*, the always-the-person prompts and every interactive session's are not, and the tests above pass.

**Related:** TD-636 (the design), TD-642 (the seat), TD-075 (*Answered for you*).

---

## TD-642: Build TD-636 (2): the org's director seat — `director:` in `org.yml`, its trigger and `director.md`, the `permit` grant, the manager's triage standing aside

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-636's round)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Blocked by:** TD-641
**Location:** design §4.9b *The director seat* (line 2), §4.8 `permit`, §5 `org.yml` `director:`, §6 rule 3 (seats and their triggers); `src/shiftlead/teams.py` / `teamrun.py` (the org's `director:` read by the client; any `ao team start` or Apply writes the director seat when the org defines it and no record holds it — the first seat of no team, trigger `prompt`, added to the trigger set), `src/sessionorc/agent_tick.py` (rule 3: the trigger *a prompt no rule answered pending on an unattended record*, filling the seat, closing it with nothing due), `src/sessionorc/agent_common.py` / `agent.py` (the `permit` grant: `decide` on any unattended supervised record of the org, without controllers, refused on interactive, on itself and where TD-641's always-the-person check holds), `src/shiftlead/briefs/director.md` (new: what to allow, deny and pass up), `src/shiftlead/briefs/manager.md` (*with a director, permissions are its*), the *Answered for you* FYI with the director's reason; `tests/test_agent*.py`, `tests/test_seat*.py`, `tests/test_tick*.py`

**Why:** TD-636: Paul, 2026-10-13 — *allowing a director seat to handle them for the user*; the prompts no written rule covers need a judge before the person.

**Fix:**
1. `org.yml` `director: {profile, brief}` (absent: none); the home keeps the seat as a team's techlead seat is kept, with no team badge.
2. The trigger: an unattended record's prompt still pending after TD-641's rules, with the director defined; the seat filled, handed the prompt's record, tool, input, and the member's role, brief and claim.
3. `permit`: `ao allow|deny <id> <reason>` (the `decide` RPC) from the seat on any unattended record of the org; refused on interactive, on itself, and on an *allow* of an always-the-person prompt (a deny stands).
4. A pass: `ao msg person` naming the prompt and why, the prompt left as `needs-you`.
5. Every answer: an FYI in *Answered for you* with the reason.
6. The manager's brief: with a director defined, it leaves permissions to it.
7. Tests: the seat fills on an unmatched prompt and not on a matched one; `permit` allows and denies an unattended record's prompt, is refused on an interactive one, on itself and on a `~/.shiftlead` prompt; no `director:` leaves the prompt to the person; the FYI is written.

**Done when** an unattended member's prompt no rule covers is answered by the director seat with a reason told to the person, or passed up in words, never touching an interactive session or the always-the-person prompts, and the tests above pass.

**Related:** TD-636 (the design), TD-641 (the rules), TD-151 (the techlead seat), §6 rule 3.

---

## TD-645: `prepare-commit-msg` writes `Agent-Model: <adapter>/<model>` from `AGENT_MODEL_FILE`, else `AGENT_MODEL` (TD-638)

**Priority:** Low
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-638's round)
**Owner:** dev-cadence
**Kind:** build
**Status:** Open
**Location:** `scripts/git-hooks/prepare-commit-msg` (a SYNCED FILE, dev-cadence's: the change is made there and synced; cadence §9.9)

**Why:** TD-638: ShiftLead now names the model in use in `AGENT_MODEL_FILE` and the declared one in `AGENT_MODEL` (design §4.2); the hook that writes `AGENT_NAME` as a co-author writes no model.

**Fix:** in dev-cadence, beside the `Co-Authored-By` trailer: read the first line of `$AGENT_MODEL_FILE` when it is set and readable, else `$AGENT_MODEL`, and add `Agent-Model: <value>` with `git interpret-trailers --if-exists replace` for that key (an amend after a model switch names the new model, never two); nothing when neither is set; tool-neutral, never calling `ao`. Then the sync brings it here.

**Done when** a commit made in a session with either variable carries one `Agent-Model:` trailer naming the model then in use, one made without carries none, and dev-cadence's sync lands it.

**Related:** TD-638 (the design), TD-644 (ShiftLead's side).

---

## TD-646: Reachability: the person's own route to the UI — Tailscale first, `ssh -L` always, Cloudflare designed and built when asked; a relay forwards ciphertext only

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (ao-connect, with Paul)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (ao-connect); **Fable review the same day, adopted by Paul**: Tailscale ships alone first (TD-647 in two slices, Cloudflare moved to TD-656, built when asked), a dated interim serve of 8765 taken knowingly, Tailscale's identity trust stated, `listeners.json` cut for asking the port, a lost device's cut-off per route, the passkey as the coming second way in, the phone's silent failure in TD-003. Original round — §4.5b rewritten: the person brings the route and shiftlead runs nothing in its path; Tailscale offered first (`tailscale serve`, a `*.ts.net` certificate, no domain, nobody in the middle who can read it), Cloudflare Tunnel + Access second (since moved to built when asked, TD-656), `ssh -L` always; every route dials out, so each works behind CGNAT. The UI gains a **route port** (8766, loopback) on which the route's identity is required — `Tailscale-User-Login`, or a verified Access token — and the plain port 8765 keeps no login but checks `Host` and `Origin` and refuses proxy headers. `ao connect` sets a route up and checks it, writing `reach:` (§5). A relay, if one is built, forwards ciphertext only: TLS ends on the home, the home serves the UI and holds the login (a passkey). §4.5, §4.5c, §4.4a, §4.7, §4.8a, §5, §7 and §10 amended.
**Blocked by:** TD-647, TD-648
**Location:** design §4.5b (rewritten), §4.5 *Security* and screen 8 *Not on the page*, §4.7 `ao connect` and `ao doctor`'s **route** check, §5 `reach:`, §4.8a *The threat model*, §4.5c, §4.4a *The link*, §7 phase 2, §10

**Why:** Paul, 2026-10-13: the UI is reached today by keeping an `ssh -L` running, and Paul is moving to an ISP behind CGNAT, which breaks a WireGuard endpoint at home and an `ssh -L` from outside it. Paul also judged that a technical user would not give root-equivalent access to their machine through shiftlead's own infrastructure unless Cloudflare or another well-known provider were in the path, and asked how this scales. Paul's decisions: bring your own route, with one route primary (Tailscale, since it is the easier setup) and Cloudflare for those who want it; guide the person through a free account.

**Fix:** design first (this entry); built by TD-647 (the route port) and TD-648 (`ao connect`, the setting, the doctor line, the guide); the Cloudflare route by TD-656, when asked.

**Done when** the design says how the person reaches the UI from anywhere, behind CGNAT included, and the build entries are filed with `Blocked by` lines.

**Related:** TD-003 (the phone layout, reserved until a route exists), TD-057 (the link), the monetisation discussion of 2026-10-13 (not yet written down; an ADR is offered).

---

## TD-647: Build TD-646 (1): the UI's route port — a second loopback listener that requires the route's identity on every request and websocket

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (ao-connect, TD-646's round)
**Owner:** grinder
**Kind:** build
**Status:** Open — two slices; slice 1 is what Paul's phone waits on (Fable review, 2026-10-13). The Cloudflare token check moved to TD-656.
**Location:** design §4.5b *The route port*; `src/shiftlead/ui/app.py` (`main`, the middleware), `src/shiftlead/ui/pty_bridge.py` (the websocket upgrade), `src/shiftlead/service.py` (`DEFAULT_BIND`, `unit_text`), `src/shiftlead/cli.py` (`ao ui`, `ao service install`), `src/shiftlead/ui/templates/refused.html` (new), `src/sessionorc/settings.py` (the `reach:` reader), `README.md` (one line)

**Why:** TD-646: `tailscale serve` reaches the UI from loopback, as a local browser does, so the identity check needs a port of its own on which an absent identity is a refusal.

**Fix:**

*Slice 1 — the route port with the Tailscale check, and the checks on both ports:*
1. The UI listens on the route port (8766, `--route-port`, always `127.0.0.1`; `0` runs no route listener) beside the plain port, in one process: `main()`'s one `uvicorn.run` becomes two `uvicorn.Server`s on one loop (`ws_ping_interval=20`, `lifespan="off"`, `log_level="info"` kept; `proxy_headers=False` on both), each serving the app wrapped by an ASGI layer of its own that knows its listener (never inferred from `Host`). Every check below lives in that layer, outside `create_app()`, and runs before the app's websocket-attempt logger, so the app's existing `TestClient` tests are untouched and the new ones drive the layer; every answer carries `X-Shiftlead-Listener: plain|route`, and the layer puts `scope["shiftlead"] = {listener, origin}` for the absolute links the server renders (`page_origin`; the websocket URLs are built in the browser from `location`). The route listener binds its own socket and hands it to `serve(sockets=[…])`, so a failed bind is caught and retried each minute rather than `Server.startup`'s exit, the plain port serving meanwhile; signal handlers are installed once by the process and set `should_exit` on both servers (uvicorn's `serve()` installs and restores its own through `capture_signals()`, so the layer drives each server's `_serve` itself — the mechanism is the build's: if it drives `_serve`, it takes an upper bound on uvicorn (`<0.NN`) decided in that PR, the test of one SIGTERM stopping both holding it). `--allow-host <name>` (repeatable) on `ao ui`, `shiftlead-ui` and `ao service install`. `ao ui`, `shiftlead-ui` and the unit share the defaults; the unit carries `--route-port` only when its install was given one, so the promote's `ao service install` picks up the default.
2. `reach:` read by the settings reader (`src/sessionorc/settings.py`, a reader and validator of its own: `route`, `url`, `allow`, `team`, `aud`), so a hand-written `reach:` works before `ao connect` exists. On the route port, a check before every request and websocket upgrade, reading `reach:` from `settings.yml` itself through that reader, never through the host agent's `settings` RPC (at most every five seconds), so the route outlives the agent: no `reach:` → `403` naming `ao connect` once TD-648 is live, and until then the hand-written `reach:` (`route`, `url`, `allow`); `tailscale` → `Tailscale-User-Login`, decoded (Tailscale MIME-encodes a non-ASCII value), in `reach.allow` compared without case; an empty `allow` lets nobody in; a `cloudflare` route refused naming TD-656 until it is built. The refusal is `refused.html`, saying which check failed and the command that cures it.
3. On the plain port, the proxy-header refusal first (below), so a proxy aimed there always gets the route-port page, never a `421`. Then on both ports, §4.5b *Origin and Host*: `Host` (case-folded, port split off, `[::1]` understood) one the port serves — on the route port `reach.url`'s host, its port not compared; on the plain port the loopback names at any port and each `--allow-host` on any bind, plus the bind address and the machine's names when `--bind` is not loopback — else `421` naming `--allow-host`; a websocket upgrade must carry an `Origin`, and a request other than `GET`/`HEAD` an `Origin` or `Sec-Fetch-Site: same-origin`; a present `Origin` must match whatever else the request carries (scheme, host and port, a default port elided) — `reach.url`'s on the route port, `http://<Host>` on the plain port — else `403`. The plain port refuses `403` a request carrying `Tailscale-User-Login`, `Tailscale-User-Name`, `Cf-Access-Jwt-Assertion`, `Cf-Connecting-Ip`, `X-Forwarded-For` or `X-Forwarded-Host`, its page naming the route port — which also ends §4.5b's dated interim serve of 8765, the page naming `tailscale serve --https=443 off`, then `ao connect tailscale` once TD-648 is live and until then the manual pair — `tailscale serve --bg --https=443 http://127.0.0.1:<route port>` and a hand-written `reach:` (`route: tailscale`, `url`, `allow`). The README's *Reaching the UI from elsewhere* line, which points a Cloudflare tunnel at `127.0.0.1:8765`, says *point a proxy at the route port, 8766* in the same PR (the *Use it* step names a tunnel with no port, and TD-648 rewrites it). `page_origin` from `reach.url` on the route port, from the checked `Host` on the plain one. Every refusal on either port logged at `warning`: listener, check, `Host`, `Origin`, the decoded login — never a token — except a route-port refusal with a loopback `Host` (a local process: the CLI's own probes), logged at `info` and not counted; a count since start kept and carried on every answer as `X-Shiftlead-Refused: <n> <start>` for `ao doctor`. A UI not on the home (a node, §4.4a) runs no route listener and logs *no route listener: not the home*.
4. Tests: a hand-written `reach:` read and a malformed one refused by the validator; `reach:` read with the host agent stopped; the interim's request (`Tailscale-User-Login` and a `*.ts.net` `Host`) on the plain port getting the route-port page, not `421`; an `--allow-host` name served on a loopback bind; a refusal logged with no token in it and counted in `X-Shiftlead-Refused`; a UI on a node (`hosts.is_node()`) binding no route port; a doctor-style probe (loopback `Host`, no identity) refused, logged at `info`, uncounted; each Tailscale refusal and pass, for HTTP and for a websocket upgrade, an encoded login decoded; a foreign-`Origin` POST and websocket refused on both ports; a present but foreign `Origin` refused beside `Sec-Fetch-Site: same-origin`; an `http` `Origin` refused on the route port of an `https` `reach.url`; a rebound `Host` refused on the plain port, `localhost` at another port served, an `--allow-host` name served when bound to a private address; each proxy header refused on the plain port; `scope["shiftlead"]` reaching the app on each listener; one SIGTERM stopping both servers; the route port's bind failure leaving the plain port up; `--route-port 0`.

*Slice 2 — open websockets follow the setting:*
5. The route listener's own task reads `reach:` every five seconds; each open websocket keeps the identity it was let in with and is closed when the new `reach:` no longer lets it in. Fail closed: refuse until a first read answers; while `settings.yml` cannot be read or parsed keep the last good reading for a minute, then close the route port's sockets and refuse until a read answers.
6. Tests: a websocket closed when `reach:` is removed and when `allow` narrows; closed after a minute of failed reads.

**Done when** (slice 1, promoted at a keyboard or with an ssh over the tailnet in hand, since it ends §4.5b's interim serve) a request on the route port without the person's Tailscale identity is refused and one with it is served, and both ports refuse foreign origins and rebound names; (slice 2) removing or narrowing `reach:` closes the websockets it no longer lets in.

**Related:** TD-646 (the design), TD-648 (`ao connect`, which writes `reach:`), TD-656 (the Cloudflare route).

---

## TD-648: Build TD-646 (2): `ao connect` (tailscale, off), `reach:` in `settings.yml`, `ao doctor`'s route line, the README guide

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (ao-connect, TD-646's round)
**Owner:** grinder
**Kind:** build
**Status:** Open — waits for all of TD-647 (its `Blocked by`). The phone does not: once TD-647's slice 1 is live, `reach:` written by hand in `settings.yml` (§4.5b *The setting*), with `tailscale serve --bg --https=443 http://127.0.0.1:8766` run by hand, gives a working route without this command.
**Blocked by:** TD-647
**Location:** design §4.7 `ao connect` and `ao doctor` **route**, §5 `reach:`, §4.5b *The setting* and *Cutting off a lost device*; `src/shiftlead/cli.py`, the settings schema, the `doctor` checks, `README.md` (*Reach it from your phone*), `notify.telegram.link`'s reader

**Why:** TD-646: the route is the person's to set up; shiftlead checks each step, names the one it cannot take, and writes the setting only when the route works.

**Fix:**
1. `notify.telegram.link` defaults to `reach.url` (the `reach:` reader is TD-647's); the Settings page's Telegram-link placeholder is `reach.url` when set, else `http://localhost:8765` (today `http://{{ host }}:8765`, which a loopback plain port refuses).
2. The `set_reach` RPC, the one RPC that writes the key: checks the shape (a known route, an `https` URL, a non-empty `allow`, `team` and `aud` for `cloudflare`) and is refused to a session as `set_settings` is; `set_settings` refuses the `reach` key, naming `ao connect`.
3. `ao connect` with no argument, `tailscale`, `off`, `--allow`, `--route-port`, as §4.7 orders the checks: never `sudo`, a *lacking:* line and a stop at the first step it cannot take; a tagged home without `--allow`, a 443 already served by something else (one aimed at the plain port named as §4.5b's interim, with its `off` command), and Funnel on each refused; each port's state learnt by asking it (refused: the UI is not running, and a stop; `X-Shiftlead-Listener`: the UI's; neither: another process, named from `ss -lptn`); refused on a node; the tailscale order of §4.7 (write, serve, probe on `X-Shiftlead-Listener: route`, restore on failure, turning off only a handler this run added, by its target `127.0.0.1:<route port>`); `off` removing only its own handler; `cloudflare` refused naming TD-656 until it is built.
4. `ao doctor`'s **route** line, the same reading, plus *lacking* when the route port did not bind, naming the holder, and when the UI is not running; and the refusals counted since the UI started (TD-647's log).
5. README *Reach it from your phone* (and a line that a script calling the UI over HTTP sends an `Origin`): a Tailscale account with a second factor, the client, `tailscale up`, the operator line, HTTPS and MagicDNS on, Tailnet Lock, the tailnet access rule granting the person's login the home's 443 and 22 (22 for the ssh that cures the interim from the phone), `ao connect tailscale`, the phone's app, and an ssh app on the phone while the interim serve is in use; cutting off a lost phone (remove the device from the tailnet); `ssh -L` kept as the fallback. It replaces the README's *Reaching the UI from elsewhere* paragraph and the *Use it* step's route line (which names WireGuard and a Cloudflare tunnel).
6. Tests: each check's lacking line with the provider commands faked (tagged home, 443 taken, 443 aimed at the plain port, Funnel on); each port state read by asking; `set_settings` refusing `reach`; `off` removing the setting and only its own serve.

**Done when** `ao connect tailscale` on a home logged in to Tailscale leaves a phone on the same tailnet opening the UI at the printed URL.

**Related:** TD-646 (the design), TD-647 (the route port), TD-656 (the Cloudflare route), TD-003 (the phone layout).

---

## TD-651: The team card's **definition changed** Apply tooltip names seats alone: a profile relaunch (TD-619) is applied there too

**Priority:** Low
**Type:** debt
**Added:** 2026-10-13 (grinder-ao-2, building TD-620 slice 2)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Location:** `src/shiftlead/ui/templates/group_head.html` (the `definition_changed` Apply button's `title`; the *flow changed* one's says *lane, reader or stage brief*), design §4.5a *flow changed — Apply*

**Why:** since #1673 (TD-620) a member whose role's profile changed reads **definition changed — Apply** where nothing else differs, and Apply relaunches it; the button's title still says only *each seat it names that the run lacks is started*, and the *flow changed* one names the lane, reader and stage brief but not the profile. The mark's own title and the confirm carry the lines, so nothing is hidden; the hover words are short of what the press does.

**Fix:** both titles name the profile relaunch (*a member whose profile differs is relaunched with the definition's, taken at its next restart*); a page test reads them; the UI check on a scratch home (TD-291).

**Done when** both Apply titles say what Apply does to a profile difference and the test holds them.

**Related:** TD-619, TD-620, TD-399.

---

## TD-652: The pages re-derive who holds a red PR (`teamrun.pr_holders`, a copy of `workorders.holds_pr`): the home's reading should carry the holders

**Priority:** Low
**Type:** debt
**Added:** 2026-10-13 (grinder-ao-2; the techlead's note on #1668, TD-618 slice 4)
**Owner:** grinder
**Kind:** build
**Status:** Open — needs #1668 merged (it adds `pr_holders`).
**Blocked by:** TD-618
**Location:** `src/shiftlead/teamrun.py` (`pr_holders`, added by #1668), `src/sessionorc/workorders.py` (`holds_pr`, the `pr_orders` reading), the Repo page's *held by <name>* tag (`src/shiftlead/ui/repo.py`), design §4.4 *Each reading has one owner* (TD-614), *A red PR nobody holds is a work order*

**Why:** the home's `pr_orders` reading lists only the red PRs nobody holds, so the Repo page, to tag one *held by <name>*, runs `teamrun.pr_holders` — the same test as `workorders.holds_pr`, written again over the records the page holds. Two copies of one rule drift; §4.4 *Each reading has one owner* puts a derivation on the reading, once.

**Fix:** the home's reading carries, per red PR past `ORPHAN_AFTER`, its holders (`holds_pr` over the records, as the orders are derived); the page reads them and `pr_holders` goes; a test that the page and the reading name the same holder.

**Done when** `git grep pr_holders src/` is empty, the Repo page's *held by* tag reads the reading, and the suite passes.

**Related:** TD-613, TD-614, TD-618.

---

## TD-656: Build TD-646 (3): the Cloudflare route — the Access token check on the route port, `ao connect cloudflare`, its doctor line and guide

**Priority:** Low
**Type:** feature
**Added:** 2026-10-13 (ao-connect, TD-646's Fable round)
**Owner:** grinder
**Kind:** build
**Status:** Open — designed, built when asked: nobody runs the route today, and the home's passkey (designed with the relay, §4.5b) may replace the token check, so the two are decided together before this is built.
**Blocked by:** decision (Paul) — built when asked (Fable review, adopted by Paul 2026-10-13)
**Location:** design §4.5b (the `cloudflare` route and check), §4.7 `ao connect cloudflare` and `ao doctor` **route**; `src/shiftlead/ui/` (the route port's layer), `src/shiftlead/cli.py`, `pyproject.toml` (`pyjwt[crypto]`), `README.md`

**Why:** TD-646: Cloudflare Tunnel + Access serves a device that cannot run Tailscale and a person who wants a hostname of their own; the Fable review moved it out of the path of Paul's phone.

**Fix:**
1. On the route port, `cloudflare` → `Cf-Access-Jwt-Assertion` verified with PyJWT (`pyjwt[crypto]`, a new dependency): algorithm pinned to RS256, the key its `kid` names from `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` (cached an hour; fetched again on an unknown `kid`, at most once a minute; none ever fetched refuses), `iss` that URL's origin, `aud` holding `reach.aud`, `nbf`/`exp` with 60 s leeway, `email` present and in `reach.allow`.
2. `ao connect cloudflare --hostname --team --aud`, as §4.7 orders it: the local tunnel config's rule targets the route port and carries `access: {required, teamName, audTag}` (a dashboard-managed tunnel said to be unreadable); the cookieless fetch refused on any answer marked by a listener; the certs fetched once; the email asked, or refused with no terminal and no `--allow`; `off` removing only `reach:`.
3. `ao doctor`'s **route** line for `cloudflare`: the cookieless fetch and the certs fetch again.
4. The README's Cloudflare part: the domain, the named tunnel pointed at `127.0.0.1:8766` with `access:`, the Access application, revoking a lost device's sessions.
5. Tests: wrong `alg`, `iss`, `aud`, expired, no `email`, with a test key pair standing in for Cloudflare's certs; `ao connect cloudflare`'s refusals with the fetches faked.

**Done when** a phone through a Cloudflare tunnel with Access reaches the UI, and `ao connect cloudflare` refuses a tunnel with no Access in front.

**Related:** TD-646 (the design), TD-647, TD-648, the relay's passkey (§4.5b).

---

## TD-657: The director seat knows the person only through its brief: it should also answer what techleads pass up, from the person's written preferences in layers, at a level the person sets

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (ao-paul, with Paul — after TD-636's round)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — design §4.9b *The director answers what is passed up to it, from the person's preferences*, with §4.5a (the *preferences proposed* row, the Settings page's **Director** card, **Remember this**, the level on *answered for you*), §4.7 `ao prefs`, §4.9 (the home's work tree tracks `preferences.md`), §5 (`director: {level, groom}`, `repos.<repo>.director.level`), §6 rule 3 (the director's `asks` and `groom`), the glossary's *preferences*. The six points: (1) `--pass-up` goes to the director where the org defines one, once per passer (`passes`), the director's pass to the person; (2) the layers — `src/shiftlead/briefs/preferences.md` → **`~/.shiftlead/preferences.md`** (the person's, private, tracked by the home's work tree) → a repo's `.shiftlead/preferences.md` → the person's `## <repo>` section; the floor (*Always ask me*, the Never list, *What always reaches the person*) no layer lowers; the package and person layers filled into the brief as `{preferences}`, the repo's read in the asker's repo, a preference cited where it is written; (3) `director.level` (`conservative` default, `extrapolate`, `liberal`), overridden per repo, on `answered.level` and the row; (4) prompts judged against the preferences too, at the level; (5) the groom pass (`director.groom`, `7d`; **Groom now**), seeded on its first run from the boards' `Decided:` lines and the person's dated quotes, **Remember this** on a reply to a director's pass, the interview (an interactive session of the person's), every change a proposal (`ao prefs propose`) the person **Accept**s; (6) **Open file** on the Director card's layers and on an *answered for you* row citing a preferences file. TD-661, TD-662 and TD-663 build it. The defaults the person may care about — the person's layer in the home's work tree, every change by Accept, Remember this off until ticked, a weekly groom — were a steer to the techlead, m-b94fe34f403f, answered *go with your default* the same day (m-91cf2eed11f6, from the ledger's Why and §4.9).
**Blocked by:** TD-661, TD-662, TD-663
**Location:** design §4.9b *The director seat answers permission prompts for the person* (TD-636), *Passing up keeps the thread and the asker* (`pass_up` is *only to the person*), *Its standing context: a primer*, *What it may answer*; §5 (`settings.yml`, `org.yml`); §2 goal 6 (*Jump out*); briefs' layering (`src/shiftlead/briefs/`, `docs/briefs/`)

**Why:** TD-636's design (#1661) makes the director one per org, judging permission prompts by its brief (`director.md`). Paul, the same day, set its larger shape:
- *"The director would be one per ao instance — so across all teams. The original thought was that techleads would pass questions that they could not answer to it. Challenge is setting context — is this another techlead and it uses the context for the appropriate team … or does it have a higher level view based on user (my) prefs? Would we need an interview to set those up?"*
- Answered with ao-paul: a second techlead adds little (it reads the docs the first could not answer from); what a director adds is **what the person would say**. So it answers from the person's **written preferences** plus the asking team's primer, cites the line (`--source`), and passes the rest to the person. The techlead stays (Paul: *"agreed have both"*): worker → techlead → director → person.
- **A level** (Paul: *"Some users may want the director to be conservative (only what is clearly documented), what is reasonably extrapolated, or answer liberally (only ask if there is no related docs/indicators)"*): `conservative` (default) / `extrapolate` / `liberal`, per repo as well. At every level §4.9b's **Never** list and *What always reaches the person* still go to the person, and each answer names the level that produced it.
- **Preferences in layers** (Paul: *"Should we have preferences per repo (and it lives in each repo) with some set of defaults like we do for briefs?"*): package defaults → **the person's own, across repos** (private, in git; ao-paul's addition, so risk, spending and *always ask me* are not copied into every repo nor shown in a shared one) → a repo's own file, checked in. The most specific wins; nothing overrides the Never list.
- **Grown and groomed** (Paul: *"we would want the preferences routinely groomed so that it becomes general sentiments instead of specifics"*): seeded from what is already decided (boards' `Decided:` lines, *Paul, <date>:* quotes in the ledger and history), a short interview for the gaps, an answer to a passed-up question offered as an addition (*remember this?*), and a routine grooming pass landed as a change the person reviews.
- **An Open preferences button** (Paul: *"a button for the user to be able to open the pref file in an editor"*): on the Settings page and on each *Answered for you* row, opening the file the answer cited.

**Fix:** design first, extending TD-636's seat (its rules → director → person order and *What always reaches the person* stand). The round settles: (1) `pass_up` to the director where the org has one, and from it to the person (the thread, `passed_up` once per passer, the recommendation); (2) the preferences files — names, where the person's own lives, the layer order, and the director's first read (the primer's rule: an index, cited at the source); (3) the level — key, where it is set, how an answer shows it; (4) the director's prompt judgement read against the preferences as well as `director.md`; (5) seeding, the interview, *remember this?*, and grooming — who runs each and how each lands; (6) the button. The design names the build entries.

**Done when** the design says what the director answers beyond permission prompts, from which preferences, at which level, and how the preferences grow and are groomed, and the build entries are filed with `Blocked by` lines.

**Related:** TD-636 (the seat), TD-641 / TD-642 (its builds; TD-642's brief and trigger are where this lands), `docs/decisions/2026-10-13-agent-product-lessons.md` (lessons 1 and 7).

---

## TD-661: Build TD-657 (1): a pass goes to the director where the org has one — `passes` once per passer, the director's `asks` cause, its pass to the person, both recommendations on the row

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-657's round)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Blocked by:** TD-642
**Location:** design §4.9b *Passing up keeps the thread and the asker*, *The director answers what is passed up to it*, §6 rule 3 (`asks` on the director seat), §4.5a *Inbox row: passed up*; `src/sessionorc/agent_mail.py` (`rpc_pass_up` ~L981, the `passed_up` refusal ~L1009 and ~L161), `src/sessionorc/agent_tick.py` (rule 3's `seat_due` for the director), `src/shiftlead/ui/` (the passed-up row), `src/shiftlead/briefs/techlead.md`, `director.md` (TD-642's)

**Why:** TD-657: Paul, 2026-10-13 — *techleads would pass questions that they could not answer to it*; today `pass_up` goes only to the person.

**Fix:**
1. `pass_up`: open to the addressee once **per passer** — `passes: [{by, at, recommend}]` appended, `passed_up` the latest time; a second pass by the same passer refused. Where the org's director seat record exists, is not suspended and is not at its fill ceiling, and the passer is not it, the asker's entry goes to the director's inbox, never refused as full; else, and from the director, to the person as today (the full-inbox refusal only there).
2. Rule 3: the director seat is due by `asks` while a question passed up to it is open in its inbox (as a techlead's `asks`); its *filled for* line names the question.
3. The person's copy draws each pass's recommendation, the latest first (`ao inbox` and the row).
4. `director.md` gains the question half: answer with `--source` or pass up with a recommendation; a `steer`'s bound is not extended. `techlead.md` says a pass reaches the director where there is one.
5. Tests: a techlead's pass with a director lands in the director's inbox and makes it due; the director's pass reaches the person with both recommendations; a second pass by the same passer is refused, the director's after the techlead's accepted; with no director, or the director suspended or at its fill ceiling, the pass goes to the person as before; the person's reply goes to the asker and closes every copy.

**Done when** a question a techlead passes up reaches the director where the org has one and the person otherwise, the director's pass reaches the person showing both recommendations, and the tests above pass.

**Related:** TD-657 (the design), TD-642 (the seat), TD-662, TD-663.

---

## TD-662: Build TD-657 (2): the preference layers and the level — the package's `preferences.md`, `{preferences}` in `director.md`, `director.level` per org and repo, `answered.level`, the Settings page's Director card, `ao prefs`

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-657's round)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Blocked by:** TD-642
**Location:** design §4.9b *The director answers what is passed up to it* (*Preferences, in layers*, *Its first read*, *A level the person sets*), §4.5a (Settings page **Director** card, *Inbox row: answered for you*), §4.7 `ao prefs`, §5 `settings.yml` `director:`; `src/shiftlead/briefs/` (new `preferences.md`; `director.md`), `src/sessionorc/brief.py` (`fill`: `{preferences}`), `src/sessionorc/settings.py` (the keys), `src/sessionorc/agent_mail.py` (`answered.level`), `src/shiftlead/cli.py`, `src/shiftlead/ui/` (Settings, Inbox)

**Why:** TD-657: Paul, 2026-10-13 — *preferences per repo … with some set of defaults like we do for briefs*; *conservative … reasonably extrapolated, or answer liberally*; *a button for the user to be able to open the pref file in an editor*.

**Fix:**
1. `src/shiftlead/briefs/preferences.md`: the package's defaults, under the topic headings (*Spending*, *Scope*, *Risk*, *Style*, *Always ask me*, *Permissions*), short.
2. Two file slots in `director.md`, `{preferences}` (the package's) and `{my_preferences}` (`~/.shiftlead/preferences.md`, read by the home), filled by rule 7's fill so both are in `sources`; `brief.fill` (`src/sessionorc/brief.py` ~L84) lets this one slot be missing and fill *none written*, where a missing file raises `Unreadable` today. The director's *filled for* line names the absolute paths of the asking repo's `.shiftlead/preferences.md` and primer in the home's checkout of it. `director.md` states the order, the floor, the three levels, the citation form, and that it never reads `~/.shiftlead`.
2a. `director.md`'s prompt half reads a prompt against the preferences' *Permissions* as well as its own rules, at the level in force, under the floor; the level is handed on a prompt fill as on a question's. A start refuses a `director:` whose profile is `permission_prompts: ask`.
3. `settings.yml` `director: {level, groom}` and `repos.<repo>.director.level`, validated (`conservative|extrapolate|liberal`; a duration or `off`), written by `set_settings`; the level in force handed on the fill and recorded on a sourced reply as `answered.level`.
4. The *answered for you* row names the level and draws **Open file** on a source that is a preferences file.
5. The Settings page's **Director** card (level, per-repo picks, groom every, the layers with Open file and *create it*), drawn when `org.yml` defines `director:`; `ao prefs` (the listing).
6. Tests: the fill carries both layers in order, and fills with the person's file absent (*none written*); a change to the person's file is seen as a source change; a prompt fill carries the level; a director on an `ask` profile is refused at the start; a bad level is refused by `set_settings`; a repo's override wins for its questions; `answered.level` is written and drawn; the card's Save writes both keys.

**Done when** the director's fill carries the package's and the person's preferences and names the repo's, the level is set per org and per repo and shown on every answer, the Director card and `ao prefs` show the layers, and the tests above pass.

**Related:** TD-657 (the design), TD-642 (the seat and `director.md`), TD-661, TD-663.

---

## TD-663: Build TD-657 (3): the groom pass, the seed, Remember this, the interview — `ao prefs propose`, the *preferences proposed* row's Accept and Discard, the home's commit

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-657's round)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Blocked by:** TD-661, TD-662
**Location:** design §4.9b *The director answers what is passed up to it* (*Grown and groomed*, *Remember this*, *The interview*), §4.5a (*Inbox row: preferences proposed*, *Inbox row: passed up*'s Remember this, the Director card's Groom now and Interview), §4.7 `ao prefs`, §4.9 *What is left at the home has a history*, §6 rule 3 (`groom`); `src/sessionorc/agent_settings.py` (`_commit_defs` ~L326 / `rpc_commit_defs` ~L312: `preferences.md` tracked; new `prefs_propose`, `prefs_accept`, `prefs_discard`), `src/sessionorc/agent_tick.py` (the `groom` cause), `src/sessionorc/agent_mail.py` (`remember` on a reply, kept until a pass concludes), `src/shiftlead/briefs/` (new `interview.md`; `director.md`'s groom half), `src/shiftlead/cli.py`, `src/shiftlead/ui/`

**Why:** TD-657: Paul, 2026-10-13 — *we would want the preferences routinely groomed so that it becomes general sentiments instead of specifics*; *would we need an interview to set those up?*

**Fix:**
1. The home's work tree tracks `preferences.md`; a hand edit is committed *edited by hand* as the other definitions are.
2. `prefs_propose {text, why}` from the director seat or an interactive session (refused from any other): writes `~/.shiftlead/preferences.proposed.md` (a newer replaces it) and the *preferences proposed* row; `prefs_accept` / `prefs_discard`, a person's own — accept moves it over and commits *preferences: <why>* — and either concludes the groom pass.
3. Rule 3's `groom` on the director: due `director.groom` after the last conclusion (none yet: at the first tick the seat exists), or on `ao prefs groom` / **Groom now**; never while a proposal stands, so a pass that proposed is not refilled until Accept or Discard.
4. `director.md`'s groom half: read the file, the remembered answers and, the first pass or with the file empty, the seed (every registered repo's board `Decided:` lines, the person's dated quotes in its ledger and design history); write general sentiments, a remembered line about one repo under its `## <repo>` heading; name the gaps in `--why`.
5. **Remember this** on the compose of the person's reply to a question whose `passes` name the director, and of an **Overrule** of a director's sourced answer: `remember: true` on the reply entry; its copy in the director's inbox kept until a groom pass concludes; the Director card counts them (*3 remembered*).
6. `ao prefs interview` / **Interview**: the person's interactive session with `interview.md` (the layers, the last gaps), ending in `ao prefs propose`.
7. Tests: a proposal from the director writes the row and a member's is refused; Accept commits and Discard deletes, each concluding the pass; `groom` is due at the seat's first tick, on the interval and on the press, and not while a proposal stands (no refill loop); a remembered reply survives the inbox's aging until the pass concludes; a hand edit is committed.

**Done when** the director grooms the person's file on its interval and on a press, seeding it the first time, a remembered answer reaches the next pass, the interview proposes, every change reaches the file only by the person's Accept or hand edit, and the tests above pass.

**Related:** TD-657 (the design), TD-661, TD-662, TD-210 (the home's work tree).

---

## TD-665: A shell's Focus and card draw an agent's controls: Wrap up types the wrap-up prompt into bash, and Message, Reports, Ready to close and the Session card's grants and controllers are agent-shaped

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-13 (Paul, through Add entry; drafted by ao-shiftlead-entry-5)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — §4.3 *A record with no agent*: one adapter capability, **`agent`** (`False` for `shell` and `command`, `True` where unset), carried on the record's view and read by every reader instead of an adapter's name. On such a record: (1) Wrap up is not drawn and the `send` RPC's `wrapup` is refused; a stop time and `ao team stop` kill at once; the host types nothing of its own (no pause, nudge, doorbell, fill); (2) Message is not drawn and `msg` to it is refused (§4.10); (3) Reports is not drawn and no claim is derived for it; (4) Close is offered without the Ready to close checks, confirming *the shell is killed; the directory is left as it is*, reaping nothing; (5) the composer reads *Type a command…*, Send never *Steer*, Attach kept, no prompt chips; (6) the Session card drops grants, controllers, adapter id, context and rounds, and Inbox, Working and Told at start go. §4.5a *Focus, card: A record with no agent*, §4.1, §6 *Stop time*. TD-666 builds it.
**Blocked by:** TD-666
**Location:** `src/shiftlead/ui/templates/focus.html` (the acts line: Message, Wrap up; the composer's *Compose a prompt…*; the side panel: Reports, Ready to close, Session's grants and controllers), `src/shiftlead/ui/templates/card.html` (the card's **more ▾**: Wrap up ~L148), `src/shiftlead/ui/app.py` (`wrapup` sends `WRAPUP_PROMPT` with no adapter check ~L2228), `src/sessionorc/models.py` (`WRAPUP_PROMPT`), `src/shiftlead/ui/cards.py` (`ready_to_close` ~L1032: tree clean, branch pushed, subagents, outcomes, mail), `src/sessionorc/reports.py` (derived claims from the directory's branch); design §4.5a rows *Focus: Wrap up*, *card: more ▾*, *Message*, *Focus: Open shell here*, §4.5 *The Focus screen's anatomy*, §4.1 *A plain shell is an adapter*, §4.8 *The person's own shell is the person* (TD-580)

**Why:** Paul, 2026-10-13, on `dc-paul-shell` (opened by **Open shell here** from `dc-paul`): *"it has items that do not belong — like the "wrap up" button … make sure everything there is specifically for a shell/command instead of an agent."* Screenshot: `docs/mockups/reviews/td-665/shell-focus-2026-10-13.png`. The Focus template and the card draw the same controls for every adapter; only Transcript and its editor link know a shell has no tool session id. What that does on a shell:
- **Wrap up** types `WRAPUP_PROMPT`, English prose, into bash, which **runs it as a command line** (the screenshot: `-bash: syntax error near unexpected token '('`). Prose with a backtick, `$(` or `;` in it would run something. A shell runs no hooks (§4.3), so nothing can wrap it up: the control can only do harm.
- **Message** mails an inbox that nothing reads: a shell has no `ao inbox` hook and no agent to run one.
- **Reports** shows the claims derived from the directory's branch (the screenshot: *TD-104 claimed*), so a shell opened in a worker's worktree shows the worker's claim as its own.
- **Ready to close** checks an agent's hand-off (tree clean, branch pushed, subagents, outcomes reported, mail read). A shell that shares another session's worktree is never *ready* while that agent's files are dirty, and the confirm says *its worktree reaped* for a shell that holds no worktree.
- The composer says *Compose a prompt…*; on a shell Send types commands. The Session card draws **grants** and **controllers**, which mean nothing for the person's own shell (§4.8, TD-580: no role, no controller).

**Fix:** design first. A §4.5a reading per adapter capability (no hooks, no tool session id, no mailbox reader), not `adapter == "shell"` checks in templates (§4.3: core names no adapter). The round settles, for a `shell` (and a `kind: command` run): (1) Wrap up left out of Focus and the card, and the `send` RPC with `wrapup` refused for an adapter with no agent (so `ao team stop` and the policy cannot type it either); (2) Message left out, or kept only where something reads the inbox; (3) Reports left out, or derived claims shown only on an agent's record; (4) Ready to close for a shell: Close with a plain confirm (*the shell is killed; the directory is left as it is*), or which checks apply; (5) the composer's words (*Type a command…*) and whether its attach and prompt chips apply; (6) the Session card's rows (grants, controllers, adapter id, context) for a shell. The design names the build entry.

**Done when** §4.5a says which Focus and card controls a shell draws, and why, and the build entry is filed.

**Related:** TD-580 (the person's own shell), TD-577 (Open shell here), TD-112 (adapter neutrality), TD-156 (the Focus review).

---

## TD-666: Build TD-665: a record with no agent — the adapter's `agent` on the view; no prose typed, no mail, no derived claim; Focus and the card draw a shell's controls

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-13 (the designer, TD-665's round)
**Owner:** grinder
**Kind:** build
**Status:** Slice 1 of 2 (the host, `src/sessionorc/**`) in PR #1701 (2026-10-14, grinder-ao-1): `adapters.has_agent` reads the adapter's `agent` (False on `shell` and `command`), `_view` carries it; the anchor rule, the usage reads, the settings merge and the container occupancy check key on it; `send` with `wrapup` and `set_mode` to unattended refused on one; its stop time and `ao team stop` (`teamrun._stop_one`, the one line of `src/shiftlead/**` it touches) kill it at once; no doorbell, policy line or gate mark; `msg` to it refused, the person included; `reports.holds_directory` and the derive pass skip it. Tests in `tests/test_no_agent.py`; the suite's agent stand-in is the stub `agentshell` (tests/_stubs.py), a shell that counts as an agent. Left: slice 2, the pages (`src/shiftlead/ui/**`), grinder-ao-2's package.
**Location:** design §4.3 *A record with no agent*, §4.5a *Focus, card: A record with no agent* (and *more ▾*, *Wrap up*, *Message*), §4.10, §6 *Stop time*; `src/sessionorc/adapters.py` (`Adapter`'s optional attributes ~L47; `ShellAdapter` ~L254, `CommandAdapter` ~L273: `agent = False`), `src/sessionorc/agent_serve.py` (`_view` ~L49, which already reads `adapters.get(s.adapter)`; `agent` set before the early return for a node's own records ~L76), `src/sessionorc/agent.py` (`rpc_send` ~L2008: `wrapup` refused), the stop-time and team-stop kill, `src/sessionorc/agent_wake.py` (the doorbell), `agent_tick.py` (nudges, pause and resume prompts, fills), `agent_mail.py` (`rpc_msg`: an addressee with no agent refused), `src/sessionorc/reports.py` (`derive` ~L67: skip it); `src/shiftlead/ui/templates/focus.html` (~L100 Wrap up, Message, the composer, Reports, Inbox, Working, the Session card), `card.html` (~L148), `src/shiftlead/ui/cards.py` (`ready_to_close` ~L1032), `src/shiftlead/ui/app.py` (~L2228 `wrapup`)

**Why:** TD-665: Paul, 2026-10-13, on `dc-paul-shell` — *make sure everything there is specifically for a shell/command instead of an agent*; Wrap up typed English prose into bash, which ran it (`docs/mockups/reviews/td-665/shell-focus-2026-10-13.png`).

**Fix:** two slices.
1. **The host** (`src/sessionorc/**`, held): `agent` on the adapter (`getattr(adapter, "agent", True)`), `False` on `shell` and `command`, put on the view in `agent_serve._view`, a node's included; every existing `adapter == "shell"` check converted to `agent` (so a `command` run is covered too) — `agent.py` ~L1063, ~L1593, `agent_tick.py` ~L2483, ~L3407, ~L3419, `agent_spend.py` ~L345, ~L369, `agent_settings.py` ~L60, `agent_remote.py` ~L413 — or left in words where it means the adapter itself (the tick's adoption of a hand-started session as `shell`, `agent_tick.py` ~L3712); `set_mode` to `unattended` refused for a record with no agent; `send` with `wrapup` refused in §4.3's words; the stop time and `ao team stop` kill a record with no agent at once; no doorbell, nudge, pause/resume prompt or fill typed into one; `msg` refuses it as an addressee (*nothing reads `<name>`'s inbox — it runs no agent*), the person included; `reports.derive` skips it.
2. **The pages** (`src/shiftlead/ui/**`): every control in §4.5a's row read from the view's `agent` — Wrap up, Message, Reports, Inbox, Working, Told at start, the grants and controllers chips, the adapter id, context and rounds lines, the ready-to-close caption and checklist, and prompt chips and the mode toggle (Take over, Hand back, *Switch to unattended*) not drawn; the composer's *Type a command…*, Send never *Steer*; Close offered without the checks, its confirm *the shell is killed; the directory is left as it is*, reaping nothing. No template names an adapter. A look by the builder (§4.9b *A UI change is verified by its builder*): Focus and the card of a shell beside an agent's, shots committed under `docs/mockups/reviews/`.
3. Tests: the view carries `agent` false for `shell` and `command` and true for `claude-code`; `send` with `wrapup` refused on a shell; a shell's stop time kills it with nothing typed; `msg` to a shell refused, from a session and from the person; `derive` gives a shell in a worker's worktree no claim; the Focus and card renders of a shell lack each control the row names and draw *Type a command…*; Close on a shell reaps no worktree; `set_mode` unattended refused on a shell; a `command` run is spared the pause, nudge and fill as a shell is.

**Done when** nothing types prose into a shell or a command run, mail to one is refused, no claim is derived for one, Focus and the card draw only a shell's controls (looked at, shots in the PR), and the tests above pass.

**Related:** TD-665 (the design), TD-580 (the person's own shell), TD-577 (Open shell here), TD-112 (adapter neutrality).

---

## TD-667: A key typed into the Focus terminal while it is scrolled back is swallowed by tmux's copy mode: typing should return the pane to the live screen and reach the prompt

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-13 (the designer) — §4.6 *Typing returns the pane to the live screen*, §4.5a *Focus pane: typing in a scrolled-back terminal*, §4.3 *Prompt injection*. (1) **Typing** is a key frame holding a printable character, Enter, Tab or Backspace alone, or a bracketed paste; arrows and other escape sequences, Escape, Ctrl+C (copy mode's cancel, never an interrupt) and other control bytes stay copy mode's. (2) **The bridge knows**: any scroll message sets its *scrolled* mark; a counted key while it stands runs `copy-mode -q` (nothing when no mode) and clears it, then writes the key; another client's copy mode unseen (no `#{pane_in_mode}` read per key). **Order**: the bridge's tmux commands run one at a time, each awaited to its end, in frame order; a leave failing or past two seconds is logged and the key written anyway. (3) **The composer**: typing in it leaves the pane alone, but **Send** leaves copy mode, since a scratch tmux 3.5a showed a paste reaches a pane in copy mode while its Enter is the mode's, so a send into a scrolled-back pane would stick. Every host-agent paste-and-Enter now leaves copy mode first. (4) A program's own mode is untouched, and a read-only attach drops keys first. TD-669 builds it.
**Blocked by:** TD-669
**Location:** `src/shiftlead/ui/static/app.js` (the Focus terminal: `term.onData` sends keys as they are; the `wheel` handler and Shift+PageUp send `{scroll}` messages), `src/shiftlead/ui/pty_bridge.py` (`scroll_argv`: `copy-mode -e`, `send-keys -X -N n scroll-up`; `pump`'s `up()` writes key frames to the pty and awaits `scroll` only until the tmux command is spawned); design §4.6 *Scrollback is tmux's, reached through tmux*, §4.5a (no row yet for a key in a scrolled-back terminal; *Focus composer* rows for what stays out)

**Why:** Paul, 2026-10-13: *"Is there a way to have the Focus terminal unscroll to the prompt input when a user starts typing in it? Typing into the composer should not do this, just in the terminal portion."* The wheel and Shift+PageUp scroll tmux's history by putting the pane in copy mode (§4.6), and in copy mode tmux reads keys as copy-mode commands, not input: checked on a scratch tmux 3.5a (emacs `mode-keys`, the default), `x y z` typed after a five-line scroll-up left the pane in copy mode and reached nothing. So a person who scrolled back to read and starts typing loses the keys, silently, and must scroll down to the bottom (or know copy mode's `q`) first. A local terminal and VS Code jump to the prompt on input; xterm.js's `scrollOnUserInput` would do that here, but it does nothing with `scrollback: 0`, since the history is tmux's.

**Fix:** design first, a §4.6 sentence and a §4.5a row: a key the person types into the terminal while the pane is in copy mode first leaves copy mode (`copy-mode -q` against the session; checked: it returns the pane to the live screen) and then reaches the pane, so the first key is not lost. The round settles: (1) **which input counts** — a printable key, Enter, Backspace and a paste (Paul's *starts typing*), and not a lone modifier, Shift+PageUp/PageDown, the wheel, Ctrl+C or Ctrl+Shift+C taken by Copy, or a key on a read-only attach (dropped anyway, §4.6); (2) **who knows the pane is scrolled** — the page (a flag set by its own scroll messages, cleared at the bottom; another client's copy mode unseen) or the bridge (`#{pane_in_mode}` read before a key frame), and **the order**: the leave must finish before the key is written, which `pump`'s `scroll` does not wait for today; (3) **the composer stays out**, as Paul asks: typing in it leaves the terminal where it is (whether its **Send** should leave copy mode is the round's call); (4) a program's own mode (`less`, a pane's `vi`) is not copy mode and is untouched. The design names the build entry.

**Done when** §4.6 and §4.5a say what a key typed into a scrolled-back terminal does, and the build entry is filed.

**Related:** TD-022 (scrollback is tmux's), TD-174 (the wheel as a scroll message), TD-491 (the composer's bar).

---

## TD-668: The Add entry form's **What** box is one line high and its hidden error note draws as an empty orange box

**Priority:** Low
**Type:** debt
**Added:** 2026-10-13 (grinder-ao-2, TD-633's look on a scratch home)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Location:** `src/shiftlead/ui/templates/base.html` (`#entrywhat`, `#entryerr`), `src/shiftlead/ui/static/app.css` (`.input` L114: `height: 34px`, which a `textarea.input` keeps unless it is `.tall`; `.warn` L130: `display: flex`, which beats the UA's `[hidden]`)

**Why:** read on TD-633's screenshots (`docs/mockups/reviews/2026-10-13-td633-form.png`): **What** carries `rows="6"` but draws one line and a half, so a page of words — or the attachment paths the form now inserts — scrolls in a box the mockup (`docs/mockups/gen.py` `add_entry`, 132 px) draws four times as tall; and `<p class="note warn" id="entryerr" hidden>` shows as an empty orange box under **Open a session** whenever there is no error. Not TD-633's change: neither rule is touched by it.

**Fix:** `#entrywhat` gets `tall` (or a height of its own near the mockup's); a `.warn[hidden] { display: none; }` rule beside `.btn[hidden]`'s, and a grep for other `warn` nodes that rely on `hidden`. A test that the form's textarea is `tall` and the stylesheet hides a hidden `.warn`.

**Done when** the form's **What** draws several lines, no empty warning box shows on a form with no error, and the test holds.

**Related:** TD-633 (found on its look), TD-219 (the form), TD-296 (the same `[hidden]` fault on `.btn`, `.radio`).

---

## TD-669: Build TD-667: a typed key leaves copy mode first — the bridge's *scrolled* mark, `copy-mode -q` before a printable key, Enter, Tab, Backspace or paste, its tmux commands in order; every host-agent send leaves copy mode first

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-13 (the designer, TD-667's round)
**Owner:** grinder
**Kind:** build
**Status:** Slice 2 built (grinder-ao-1): `Tmux.leave_copy_mode` (`copy-mode -q`, `check=False`) at the top of `HostAgent._type`, of `Tmux.send_prompt` and of the brief's Enter-only retry (`_enter_again`), so every host-agent send leaves copy mode before it types; tests: `send` into a pane in copy mode submits (`test_agent.py`), and the blind `send_prompt` (`test_tmux.py`). **Left: slice 1, the bridge** (`src/shiftlead/ui/**`, grinder-ao-2's half).
**Location:** design §4.6 *Typing returns the pane to the live screen*, §4.5a *Focus pane: typing in a scrolled-back terminal*, §4.3 *Prompt injection*; `src/shiftlead/ui/pty_bridge.py` (`scroll_argv` ~L119: a leave argv beside it; `pump` ~L209 and its `up()` ~L233: the mark, the counted frame, the leave before the write), `src/shiftlead/ui/app.py` (`scroll` ~L3680: awaited to its end instead of reaped in the background, a `leave` beside it through the same `inside` prefix and socket), `src/sessionorc/tmux.py` (`paste` ~L257, `send_prompt` ~L276: `copy-mode -q` first), `src/sessionorc/agent.py` (`_submit` ~L2106, the confirmed send)

**Why:** TD-667: Paul, 2026-10-13 — *have the Focus terminal unscroll to the prompt input when a user starts typing in it*. In copy mode tmux reads keys as its own commands, so a key typed into a scrolled-back pane is lost, and a send's Enter into one is too.

**Fix:** two slices; the second is in `src/sessionorc/**` (held).
1. **The bridge** (`src/shiftlead/ui/**`): `pump` takes a `leave` callable beside `scroll`. Any scroll message sets *scrolled*. A key frame that counts — one not starting with `\x1b` that holds a printable character, or exactly `\r`, `\t`, `\x7f` or `\b`, or one starting with the bracketed-paste opener `\x1b[200~`; every other `\x1b`-led frame never counts (arrows `\x1b[A`, `\x1bOP`, Alt-keys `\x1bx`, and xterm.js's replies on the same `onData` channel — `\x1b[?1;2c`, `\x1b[24;80R`, `\x1b[I`, app.js ~L3895) — while *scrolled* stands, awaits `leave()` (`copy-mode -q -t =<sid>:`, bounded at two seconds, a failure logged) and clears the mark before `pty.write`. Scroll and leave commands run one at a time, each awaited to its end, in frame order. A read-only attach drops the frame first, as today.
2. **The send** (`src/sessionorc/**`): `copy-mode -q` against the session at the top of `_type` (~L2116, before its `lead` line ~L2133 and the paste) and of `send_prompt`, so nothing typed lands in copy mode (`check=False`: no mode is no error).
3. Tests: `pump` with a fake pty and a recording `leave`: a printable key after a scroll calls `leave` once and then writes; a second key does not call it again; an arrow, Escape, an Alt-key, Ctrl+C and xterm's replies (`\x1b[?1;2c`, `\x1b[24;80R`, `\x1b[I`) after a scroll do not call it; a burst of printable characters does; a paste does; a read-only pump calls nothing; the leave is awaited before the write, and a scroll's command finishes before a following leave. On a private tmux socket: a pane scrolled up, then `x` through the bridge, ends out of copy mode with `x` at the program. `send` into a pane in copy mode submits (the composer empties).

**Done when** a key typed into a scrolled-back Focus terminal reaches the program, the pane back on the live screen, a send into such a pane submits, the composer's typing leaves the pane alone, and the tests above pass.

**Related:** TD-667 (the design), TD-022 (scrollback is tmux's), TD-174 (the wheel), TD-027 (the confirmed send).

---

## TD-670: A Focus stream is sent every repo's whole facts on each `repos` push to read its PR marks, and the loop still holds 45–300 ms with a stream open: TD-611's remainder

**Priority:** High
**Type:** debt
**Added:** 2026-10-14 (grinder-ao-2, TD-611's live read)
**Owner:** grinder
**Kind:** live-check #1704
**Status:** Built — slice 1 (fix 1) in PR #1702 (2026-10-14, grinder-ao-2): a light stream takes `{event: "repos", root, pr_marks}` (`null` for a dropped repo), the full stream the push whole — on every push, not only when the marks moved as fix 1 said: the host pushes a repo only when its reading changed, and the Inbox re-reads its boards and ledger on that push (review of #1702). Slice 2 (fix 2, and fix 3's off-the-loop half) in PR #1704 (2026-10-14, grinder-ao-2): profiled offline with the live home's readings, a counts recount spent ~45 ms in `person_states`' views and ~40 ms in `board_reading`, and `heads` the same views and every header render per regroup — each now in `asyncio.to_thread` (the longest loop gap of a recount 37 → 18 ms in the harness); the groups were already sent only when changed (`heads_key`). Left: the live check, once #1704 is live (`ao promote status`): the probe of *Done when* beside one Focus stream and beside the Org stream; then TD-611's.
**Location:** `src/shiftlead/ui/app.py` (`fan_step`'s `repos`/`doing` branch: `run.to_all(run.live, ev)`; `heads` ~L971, run per regroup on the loop; `counts_now` ~L855), `src/shiftlead/ui/fanout.py` (`to_all`, the `groups` flush ~L157), `src/shiftlead/ui/counts.py` (`_recounter`, `_ticker`), `src/shiftlead/ui/static/app.js` (Focus's `repos` handler ~L4518, the Inbox's re-read ~L3156)

**Why:** TD-611's live read, 2026-10-14 (`9bb725c` live; read-only: a static-file probe of `/static/app.css` every 50 ms beside one `/events` websocket the probe opened, nothing pressed). The bulk polls TD-616 and TD-617 removed are gone, but the loop is not yet what TD-611's *Done when* asks (no request above ~50 ms of loop time with a Focus tab open):
- With no stream open: 1397 probes, p99 5 ms, max 20 ms.
- With one Focus stream (`light=1&focus=…`): 8 of 1383 over 50 ms, max 139 ms. The stream received 1.6 MB in 75 s, almost all `repos`: the host pushes every repo's facts about once a minute (7 repos, ~1.2 MB a burst; shiftlead 755 KB, samscrape 246 KB, dev-cadence 128 KB — their `prs`, `ledger`, `completed` and `boards`), and `fan_step` forwards each event whole to every live stream, light ones included, though Focus reads only `root` and `pr_marks` from it and the Inbox page only re-reads on it. A ~70 ms hold follows each burst.
- Holds of 45–85 ms also come every few seconds with no event on the Focus stream: work the one subscriber does for the fleet (another record's delta, the counts keeper's recount, which awaits the person inbox, the board and the build chip on the loop before its `to_thread`) — not attributed yet.
- With the Org stream open: 33 of 1340 over 50 ms in 75 s, and up to ~300 ms in a 150 s run. Each regroup ships `groups` of ~200 KB, built by `heads`, which runs `view()` over the whole fleet and renders every header and the rollup on the loop.

**Fix:**
1. A light stream's `repos` is `{event, root, pr_marks}` and a mark that the repo is held or dropped — never the repo's facts — and is sent only when that repo's marks changed (the Inbox page re-reads on it, so an unchanged minute is a re-read for nothing). The full stream keeps the whole event.
2. Find the 45–85 ms holds: run `scripts/look_home.py` with repo facts and a person inbox the live size (or profile the subscriber's steps with timings) and name each step over ~20 ms; move what is pure computation (`heads`'s views and renders, the decode of a large host reply, the counts' pre-thread reads) to a worker thread, or coalesce it.
3. The Org stream's `groups`: computed off the loop, and sent only when they changed.
- Tests: a light stream's `repos` carries no `repo` facts and is not sent when the marks did not change; Focus's handler still replaces its marks and drops a repo's on `repo: null`.

**Done when** the probe above — a static file every 50 ms for 75 s beside one Focus stream, and again beside the Org stream — finds no probe over ~50 ms in steady state, and the tests pass; then TD-611's live check is read again.

**Related:** TD-611 (the live check this blocks), TD-617 (the one subscriber), TD-616 (the counts keeper), TD-572 (light streams), TD-614.

---
