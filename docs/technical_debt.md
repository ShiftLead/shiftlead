# Technical Debt

Known issues, compromises, and deferred work. Add an entry any time a problem is identified but not immediately fixed — no exceptions, however small (see [`cadence.md`](cadence.md) §2).

**This file holds open work only.** The summary table below lists exactly the entries that have a body in this file — one row each, no history. When an entry is fully resolved, move the whole body to [`technical_debt_archive.md`](technical_debt_archive.md), delete its summary row, and replace **Fix** with the resolution date plus a pointer to whichever doc/code now carries the lasting content. An entry that is only *partly* resolved stays here, with what shipped and what remains spelled out in its **Status**.

IDs are `TD-` plus a number zero-padded to three digits (four from TD-1000 on), assigned in order and never reused. Priority is a field, never part of the ID.

Two header lines follow **Added:** so a worker can filter the file instead of re-reading it (TD-118): **Owner** — who moves the entry next (`designer`, `grinder`, `paul`, `dev-cadence`; the anchor seat is retired, design §4.9b *No anchor seat*); **Kind** — what the next step is (`build`, `design-first`, `live-check`, `evaluation`, `decision`). Every open entry carries them; keep them true when the Status changes. A third, **Waits**, is written only on an entry that is pickable and still waits on something no `Blocked by:` item names (TD-715, design §4.4 *An entry says what it waits for*): `until <date>` (*`**Waits:** until 2026-10-16 — CI runs on or after 10-16`*) or `event` (*`**Waits:** event — the next cadence-sync PR`*). What waits on the person is `Blocked by: decision (paul) — <what they must do>`, or `Owner: paul`, never a `Waits:` line. **Pickable is derived, never written** (cadence §2.4, TD-228): an entry is pickable while its `**Blocked by:**` names nothing still open and no decision, so what waits on another entry or on a person's word says so there, with its pointer; what nothing blocks and a grinder still cannot build — a live look, an evaluation, the person's edit — is said by its **Kind** or its **Owner**, and the Status says what is next. A `live-check` is followed on its line by its build's last merged PR — `**Kind:** live-check #<n>`, written by the PR that makes the entry a live check — and once that PR is live (`ao promote status`) the check is in a `free-pick` lane whose owner it has (design §4.9b, TD-320); cadence's script reads the word alone. A grinder's pick list is therefore `ao repo` (its pickable entries, a live check whose build is live among them), and `python3 scripts/ledger.py --list --pickable yes --owner grinder --kind build` lists the builds alone; the designer's is `--owner designer --kind design-first`. The line below is the one list of the **Owner** and **Kind** words (cadence §2.12): `scripts/ledger.py` flags a value outside it, and `tests/test_ledger.py` reads its sets from it and checks the two lines' shape, so a new word is added there and nowhere else.

Fields: Owner = designer | grinder | paul | dev-cadence; Kind = build | design-first | live-check | evaluation | decision; Waits = until | event

---

## Summary

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| TD-003 | Phone layout: narrow Focus with a soft-key row | Medium | Open |
| TD-005 | `pretrust()` can lose a concurrent Claude Code rewrite of `.claude.json` | Low | Open |
| TD-026 | Scheduling: start/stop times and window overrides for unattended sessions, editable from the UI | Medium | Partly done — the reset start (TD-133) and the start time (TD-152) designed; archives with them |
| TD-035 | Adapters without a session-start hook still run dev-cadence's SessionStart set | Low | Open — designed; builds with the second adapter (TD-112) |
| TD-052 | Messages between sessions: the mailbox, the graph that gates it, the bounds, and the surfaces — build design §4.10 | High | Partly done — steps 1–8 done (5 was a measurement); the second-adapter step and the live check remain |
| TD-071 | Org page review 2026-09-18: the ideas not built — Forget all on a stopped team, unread mail on a folded team, a state roll-up on a live team's header, slimmer dead cards, a quieter mode badge | Low | Items 1 and 2 built 2026-09-23 (PR #499); 8 is Paul's canvas |
| TD-112 | The adapter contract has grown Claude-shaped and neutrality is untested: a second adapter (Gemini CLI) and a conformance suite every adapter passes | Medium | Designed — built by TD-784, TD-785, TD-786 |
| TD-131 | Mail, the board and the records are JSON and Markdown files read whole: fine at today's size, and no answer to search over history, counts per filter, or a retention longer than twelve hours | Low | Decision (Paul) — not yet; the trigger is written down |
| TD-133 | Build the team start at the reset — `schedules:` in `settings.yml`, the tick's replay, `ao schedule`, the card's *starts* note | Low | Open — designed; not scheduled until Paul says |
| TD-290 | A UI change goes to the person unchecked: the grinder that made it verifies it itself (Playwright, a scratch UI before the PR, the live copy read-only after the promote), a reviewer only for what it cannot settle, and what is left for the person is a look sent as mail — a steer or an ask, in Steering or Needs you — no longer a `watch` | Medium | Designed 2026-10-03 — build TD-292 (TD-291 built) |
| TD-292 | Build the mail half of a look: the briefs' three cases as a steer or an ask, `--shot` and the envelope's `shots`, screenshots and the pair on the row, Send to reviewer | Medium | Built (#975, #980, #982, #983, #987, #990, #1007); live check waiting on the first look a builder sends |
| TD-297 | The parts of the live looks of 2026-10-03 nobody could see: each waits on a press, a live event or a fixture, for a scratch home or the next time it happens | Low | Open |
| TD-299 | Run the guardians and contractmatch teams inside their devcontainers: provision the nodes for workers, define guardians' team, land both by `place:` | Medium | Paul's — contractmatch done; guardians' team, node and `place:` left |
| TD-300 | A look's screenshots from a sender on another host draw their names alone: the shot route reads this host's registry only | Low | Live check #993 — waits on a look from a node (TD-299) |
| TD-512 | A PR that truncates `docs/technical_debt_archive.md` passes every gate: the ledger tests and the cadence check's ledger row read neither its length nor what it lost | Low | Open |
| TD-636 | A director seat answers permission prompts for the person: routine ones allowed or denied by written rules, the rest escalated | Medium | Designed — TD-641, TD-642 build it |
| TD-637 | `ao progress done … --pr <n>` is accepted while the PR's required checks are red or missing | Medium | Designed — TD-639, TD-640 build it |
| TD-638 | A commit names the session that made it, not the model: as tools and models multiply, which model did what is lost | Low | Designed — TD-644, TD-645 build it |
| TD-640 | `check_cadence.py`'s `ci` row reads the base branch's required checks, not every run on the head (TD-637) | Low | Open |
| TD-641 | Build TD-636 (1): the person's `permissions:` rules per role, matched by the host at the hook, the always-the-person list, every answer an *Answered for you* FYI | Medium | Built (#1697, #1708, #1714); live check waits for the person's first `permissions:` rule and a profile set to `permission_prompts: ask` |
| TD-642 | Build TD-636 (2): the org's director seat — `director:` in `org.yml`, its trigger and `director.md`, the `permit` grant, the manager's triage standing aside | Medium | Open |
| TD-645 | `prepare-commit-msg` writes `Agent-Model: <adapter>/<model>` from `AGENT_MODEL_FILE`, else `AGENT_MODEL` (TD-638) | Low | Open |
| TD-656 | Build TD-646 (3): the Cloudflare route — the Access token check on the route port, `ao connect cloudflare`, its doctor line and guide | Low | Open — built when asked |
| TD-657 | The director seat knows the person only through its brief: it should also answer what techleads pass up, from the person's written preferences in layers, at a level the person sets | Medium | Designed — TD-661, TD-662, TD-663 build it |
| TD-661 | Build TD-657 (1): a pass goes to the director where the org has one — `passes` once per passer, the director's `asks` cause, its pass to the person, both recommendations on the row | Medium | Open |
| TD-662 | Build TD-657 (2): the preference layers and the level — the package's `preferences.md`, `{preferences}` in `director.md`, `director.level` per org and repo, `answered.level`, the Settings page's Director card, `ao prefs` | Medium | Open |
| TD-663 | Build TD-657 (3): the groom pass, the seed, Remember this, the interview — `ao prefs propose`, the *preferences proposed* row's Accept and Discard, the home's commit | Medium | Open |
| TD-673 | ShiftLead's Telegram notes go through samscrape's bot (`secrets: samscrape/prd`): give ShiftLead a bot and a Doppler config of its own | Low | Open |
| TD-703 | A member renamed in `.shiftlead.yml` keeps its old name on rule 8's restart, and a person's Start can leave the old record beside the new one | Medium | Designed — TD-706 builds it |
| TD-704 | The phase chips (*add*, *design*, *grind*, *review*) are fixed in the UI: define them, and what each matches, beside the roles in `org.yml`, overridable in `.shiftlead.yml` | Medium | Open |
| TD-706 | Build TD-703: a member renamed or removed in the definition is paired, applied and started without leaving two records | Medium | Built (#1802, #1807, #1818); live check |
| TD-717 | A seat whose first hook is lost sits with its brief unsent for hours: the scraped send never fires for Claude Code, and nothing acts on the *brief not sent* mark | High | Designed — TD-720 builds it |
| TD-720 | Build TD-717: a launch whose first hook is lost gets its brief from the composer, keeps *no hook* across a restart, and is replayed once | High | Built by #1834, #1837, #1838; live check read 2026-10-15, the replay waits for a lost first hook (anchor) |
| TD-723 | Backfill TD-722: samscrape and contractmatch under one ContractMatch project | Low | Open |
| TD-748 | The Queue: one card per effort — a TD and everything its `Blocked by:` joins, with its asks — ranked by the person, the rank the pick order; the Inbox keeps what names no TD | Medium | Designed — built by TD-769, TD-770, TD-771 (on dev-cadence#TD-119); trial TD-772 |
| TD-772 | Read back the Queue's two-week trial to Paul — passed-over flags a week, idle-while-work lines, the oldest unanswered TD ask | Medium | Open |
| TD-786 | Build TD-112 (3): the Gemini CLI adapter's reads — transcript, context, links, model, start context, mail, background, usage and spend; the full conformance suite live | Medium | Open |
| TD-794 | The Focus terminal shows a reply's lines cut off mid-word, and a block of it twice: a resize makes Claude Code repaint over lines tmux has already kept | Low | In progress (slice 1 #2129) |
| TD-820 | The designer runs far past its context bound inside one design: 955 requests over 300k in a week | Medium | Designed — built by TD-836, TD-837 (done) |
| TD-836 | Build TD-820 (1): rule 5 reads a waiting claim as not in progress, and the restart carries the waiting claims | Medium | Built (#2048) — live check |
| TD-846 | Compliance before shiftlead is sold: SOC 2 and ISO 27001 wait for a hosted or team edition; the EU Cyber Resilience Act and the supply-chain basics a buyer asks for come first | Low | Open — deferred until the monetisation decision picks a paid option |
| TD-850 | A member waiting on CI or a lane polls in its own turn — a foreground `timeout 180 tail -f /dev/null` between `ao status` reads — because no brief says what wakes it besides mail | Medium | Built (#2051, #2328) — live check, waits until 2026-10-31 |
| TD-857 | Gemini's first job: the fact-check of a doc-only PR, read by a Gemini CLI session on the free tier instead of a Claude subagent, and its verdicts compared with Claude's | Medium | Open |
| TD-900 | The Repo page is a board by stage, the Org page is Sessions, Up next numbered per repo, a live divider on Merged | Medium | Designed — built by TD-902, TD-901, TD-903, TD-904, TD-905, TD-907 |
| TD-905 | Build TD-900 (5): the ledger row's controls, once — Done… with words, Back to design…, Hold… with words | Medium | Built (#2160, #2162) — live check |
| TD-907 | Build TD-900 (6): the session side of *done — words* and *back to design — words* (a held path) | Medium | Open — blocked by TD-905 |
| TD-909 | The Queue card: Decide / Do / Read, Answer / Start session / ⋯, a Waiting group, one-sentence items (ADR 2026-10-19) | High | Designed — built by TD-911–TD-918 (on dev-cadence#TD-121, #TD-122) |
| TD-916 | Build TD-909 (7): `ao msg`'s one-sentence warning, and the briefs' rule and `--about` | Medium | Open — blocked by TD-772 |
| TD-917 | Build TD-909 (8): the backfill of `Ask:` lines and consequences | Medium | Open — blocked by TD-772, dev-cadence#TD-121 |
| TD-934 | A single-owner flow: one session designs and builds, review stays fresh — built as an opt-in beside `td` | Medium | Open — blocked by decision (paul): Paul runs the design session |
| TD-938 | The top bar's readings and tools past one developer: the build chip's audience, the host reading across nodes, + New's place under a director | Medium | Open — blocked by decision (paul): Paul runs the design round |
| TD-943 | A team over an umbrella repo cannot see its sibling repos' PRs: `--pr`, `held:` and the PR readings are the one repo's | Medium | Open — waits on Paul's paired-PR answer (guardians-devenv TD-028) |
| TD-946 | The cadence procedure says the pair `ao pr wait N && scripts/check_cadence.py --pr N`, and the *no checks means conflicting* memory is retired (TD-940's third part) | Low | Open — dev-cadence's SYNCED file |
| TD-959 | A Gemini profile signed in with Google shows no usage chip: its quota is read only by the tool, with a token in its encrypted file | Medium | Open |
| TD-964 | The end of a session on Focus, second round: the ending banner and the ending card (what the session cost), Hand back in Take over's place, the side panel folded with a value on each summary, a Sent card | Medium | Designed and reviewed 2026-10-21; hold lifted 2026-10-22 — build |
| TD-971 | The home's own id reads are removed once every repo it serves has synced the counter's script; a checkout without it is refused, naming the sync | Medium | Open — waits on every registered repo's sync |
| TD-986 | On a phone the Focus terminal cannot be scrolled reliably, and there is no Tab to accept a suggestion | Medium | Designed — builds TD-989, TD-990 |
| TD-990 | The Focus soft-key row: `Tab Esc ↑ ↓ ← → Enter 1–9` under the terminal on a phone or a coarse pointer | Medium | Built (#2320) — the phone look with Paul |
| TD-995 | A session cannot address another repo or team: names resolve only to sessions, so a request for another repo's ledger ends as a command printed for the person | Medium | Designed — builds TD-1000, TD-1001 |
| TD-997 | The Transcript draws a session's start context as its first entry — Paul's to keep or drop | Low | Open — waits on Paul |
| TD-998 | `ao` is not on PATH inside a container node: sessions and shells there reach it only as `/shiftlead/venv/bin/ao` | Low | Designed — builds TD-1004, TD-1005 |
| TD-999 | The wait guard in Gemini CLI: its `BeforeTool` hook refuses an unattended session's foreground CI watch, as Claude Code's `PreToolUse` does | Low | Designed — build TD-1007 |
| TD-1000 | A session asks another team's or repo's question seat — `ao msg --team` / `--repo`, the org-wide `ask` edge, and `ao td add --repo` for another repo | Medium | Open — build |
| TD-1004 | The generated node Dockerfile links `/usr/local/bin/ao` to the venv's `ao`, so `ao` is on `PATH` in a container node | Low | Built (#2333) — live check |
| TD-1007 | Gemini CLI's layer wakes a session at a background command's end, and its hook refuses an unattended foreground CI watch | Low | Built (#2343) — live check |
| TD-1009 | ShiftLead requires dev-cadence, and the person's briefs, start prompts and preferences live in their dev-cadence layer repo | Medium | Proposed — ADR 2026-10-25, for Paul's decision |

---

<!-- Entry template:
## TD-001: Short title of the problem

**Priority:** High | Medium | Low
**Added:** YYYY-MM-DD
**Owner:** designer | grinder | paul | dev-cadence
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

**Fix:** soft-key row that sends keys through the terminal websocket (not `send-keys`, invariant 6) — built ahead by TD-990 (TD-986, 2026-10-23), so not this entry's — collapsed side panel, 44 px tap targets on Allow / Deny; test on a phone over the route `ao connect` sets up (design §4.5b; TD-647, TD-648). On the phone the failure is silent — with the Tailscale app off or asleep, Safari shows its own error and none of the UI's pages — and iOS drops the `/events` and `/term` websockets whenever it suspends Safari: so reconnect on `visibilitychange` and `online`, the UI's disconnected banner opening with *is Tailscale on?*, the Telegram note saying *(Tailscale on)*, and the page fit for *Add to Home Screen* now that the route gives it a stable `https` origin (Fable review of TD-646, 2026-10-13).

**Related:** design §10 "Phone answers for questions" (open).

## TD-005: `pretrust()` can lose a concurrent Claude Code rewrite of `.claude.json`

**Priority:** Low
**Added:** 2026-09-06
**Owner:** paul
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
**Owner:** grinder
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
**Owner:** designer
**Kind:** design-first
**Status:** Designed (2026-10-16, the designer) — §4.3 *The second adapter: Gemini CLI* and *The conformance suite*, read from Gemini CLI 0.64.0's installed package (no run): **hook-fed, not scraped** — `GEMINI_CLI_HOME` per profile, `--session-id` chosen at launch, the per-launch layer through `GEMINI_CLI_SYSTEM_SETTINGS_PATH` (its hooks concatenate), per-process trust (`GEMINI_CLI_TRUST_WORKSPACE=true`) since no hook runs in an untrusted folder; `BeforeAgent`/`AfterAgent`/`Notification` for the state, the terminal title (`CLI_TITLE`) covering a cancelled or failed turn; the contract's new `permission_channel` False — no hook answers a Gemini confirmation, so no Allow / Deny, the terminal is the answer (§4.5a); start context and mail through `SessionStart`/`BeforeAgent` `additionalContext`. The suite: offline fixtures in CI, a live walk by hand on a profile set aside for it. §4.2a, §4.5a, §7 phase 5. Built by TD-784 (the suite, first), TD-785, TD-786. Was: **Paul, 2026-10-16 (the board, line `board:fbc6ebd9`): file it design-first for the designer.** Of the three answers put to him — he runs the spike now with ao-paul, file it design-first for the designer, or leave it for evaluation — Paul chose the designer: the design decides the scraped Gemini adapter's shape (which §4.3 contract methods it implements and which are Claude Code's alone, `state_source: scraped`, what `send` and the doorbell do without a readable composer, whether the record assumes a tool session id) and the adapter conformance suite, and lands them as build entries naming this one in `**Blocked by:**`; the 2026-10-10 note that the spike is an interactive session's is superseded by this decision. Was: **Paul, 2026-10-10 (with ao-paul): agreed, a spike, and integration tests with it.** Run as an interactive session, not a member's lane: a second tool must be installed and signed in (neither `codex` nor `gemini` is on kmaster on 2026-10-10; the sign-in is Paul's account or key), the work is judgement (which of the contract's methods are neutral), and its result is an ADR, not a merge. **Paul, 2026-10-13 (the lessons ADR, `docs/decisions/2026-10-13-agent-product-lessons.md` lesson 10):** Gemini CLI is *"a definite fit"*, so it is the spike's tool; Hermes Agent, Muse Code and Grok Bot are not wanted as tools for now. The lasting product is an **adapter conformance suite**: one set of tests every adapter passes against its real tool (launch, the state it reports, `send`, `composer()`, the doorbell and mail, `title()`), so neutrality is checked on every change and not once by the spike. The spike says which of those a scraped adapter can pass and which belong to Claude Code alone. **2026-10-15 (grinder-ao-2, answering Paul's board question *does the recently added Gemini CLI fit the bill?*):** in part. What was added is dev-cadence's TD-109 (dev-cadence #259, 2026-10-14): Gemini CLI installed on kmaster (`~/.npm-global/bin/gemini`, 0.64.0) and signed in with Paul's Google account, and a Gemini backend for dev-cadence's session *introspection* (`agent_sessions.py`: lists Gemini sessions, their cwd and `gemini --resume <uuid>`). That removes the spike's blocker (a second tool installed and signed in) and gives facts read off a real install (`docs/plans/2026-10-12-session-introspection-adapter.md` in dev-cadence: chats under `~/.gemini/tmp/<slug>/chats/`, a `sessionId` in the first record, no live registry). It is not a ShiftLead adapter: `src/shiftlead/adapters/` still holds only `claude_code/`, and the spike, its ADR and the conformance suite are all unbuilt. Who runs the spike, and when, is put back to Paul on the board. Open — for evaluation. The design's stated moat is one neutral view across tools, and only one agent adapter exists. Since phase 1 the contract (§4.3) gained `composer()`, `title()`, `mail()`, a session id chosen at launch, the doorbell, the trust pre-seed and screen rules, each shaped by Claude Code. Phase 5 puts the second adapter last. Recommendation: a scraped spike now — Codex CLI or Gemini CLI, `state_source: scraped`, no hooks — to see which of the contract's methods are really neutral, what `send` and the doorbell do without a readable composer, and whether the record's fields assume a tool session id. The spike is a branch and an ADR, not a shipped adapter.
**Blocked by:** TD-784, TD-786
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
**Owner:** grinder
**Kind:** live-check #1007
**Waits:** event — a builder's look after a page PR (a leaned-*Works* steer) and the person's **Send to reviewer** on one
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
**Owner:** grinder
**Kind:** live-check
**Status:** Open — **Owner anchor from 2026-10-05 (grinder-ao-1): what is left is out of a scratch home's reach** — a check that waits on a logged-in session or on GitHub is made by whoever has them, and a live event when it happens. **A team stop time on members' cards does not hold** (pressed the same day with a shell member: the record and Focus take it, the Org draws it nowhere): TD-335. Every press still listed needs a logged-in claude-code session (a scratch home's `CLAUDE_CONFIG_DIR` is its own, so none logs in: a role chip's `prompts:`, Resume, a permission card's Deny and keys, a team Start or `ao new me --team`, `stalled?`, a second agent session, Add entry's session, a live team's reserve line) or GitHub (`auto`'s green checks, the Org's *over its line*), and the rest are live events, read when they happen. **seven presses seen working 2026-10-04 (grinder-ao-1)** on a scratch home (`scripts/look_home.py`, its repo given a local origin so Ready to close passes), in headless Chromium: Close session is in the Focus header once Ready to close passes, drawn with no reload, and Close takes the record to `closed` (TD-156); Close and Kill each leave one *pane is gone* line after one *retrying in 1s*, and no websocket opens in the six seconds after (TD-029); on a killed session `#compose` is disabled with *this session's process has ended*, and **→ Send** sends nothing and says so (TD-047); Message… from a card's *more ⋯*, ✉ Message in Focus and Reply on an Inbox `ask` row each open the mail dialog (TD-052); `j` rings an FYI note and `x` presses its Dismiss, which confirms and removes it (TD-124); Put on the board opens a four-row box where Enter adds a line and Ctrl+Enter puts it on, the lines joined into one line at the top of *Needs the user*, one commit (TD-281); `ao new --unattended --at +2h` draws a *scheduled · starts <time>* card whose *more ⋯* holds Start now and Cancel, Cancel confirms and forgets the record, and `ao at <id> now` starts it on the next tick (TD-152). Those are struck from the Fix's list. **Three more the same day, on the same home:** a board row's answers are drawn in the order written with the default marked *DEFAULT*, the body without the tail, and **Go with it** in the foot after Reply; a click on an answer, **Go with it** (its confirm names the default), `1` and `4` on a ringed row and `g` each write the decision as one commit (`agentorc: decide <head>: <answer> (session look)`) and toast *decided: <answer> — committed on the board, not pushed*; **Not right…** on a look line opens the Reply composer with *Not right:* begun and writes the words as the decision, toasting *no entry was handed on: no team services repo: there is no techlead seat …* on a home with no techlead (TD-255); *due this week* on Settings → You saves `board_show: 7d` and the Inbox's line reads *showing board items due this week · 1 not shown, the next due Jan 1 — show* (TD-220); **Drop** on a claim with no PR is under the Reports card's *more ▾* in Focus, its confirm names the lease and the one session that may claim it again, and the session's inbox gains *your claim on TD-001 was dropped by the person — the lease is gone* (TD-150, TD-028). Struck too. **Snooze on an `unpushed` row** (an exited session whose repo is ahead of origin) offers *in 1 hour*, *tomorrow 08:00* and *a date and time…*, and the row moves under *1 snoozed — show* (TD-079); struck. The trail row the same home drew for an `unpushed` row that ended by a push read *resolved: resolved ×2*, where §4.10 says *pushed*: TD-308. **Three more 2026-10-05 (grinder-ao-1)**, on a scratch home whose repo had a local bare origin and a `promote:` block (`check` reading a file the `run` writes), in headless Chromium: a `run` that exits 1, pressed with `ao promote repo`, draws a counted *Needs you* row reading *failed: promoting cdc6c41 — the run ended and live is 04cd6aa, not cdc6c41 (exit 1). Nothing is promoted for repo until this is dismissed or a press succeeds.* with the log's tail; a second merge on origin is read (*main 4359875, 2 ahead*) and promotes nothing while the failure stands; **Dismiss** toasts *the failure is cleared: promoting goes on* and the row is a plain promote row again (TD-132 (3)); **Promote** on the row, with a `run` that works, toasts *promoting repo to f556e05 — checks read unknown, pressed through* and live reaches main; with `auto` on, `ao promote repo --back` makes the earlier commit live, and `ao promote status` and the Inbox row (under *Needs you*) read *live 04cd6aa, rolled back from f556e05 … · auto on · held*, with FYI notes *rolled back repo to … — main is n commits ahead*; the row's **Dismiss** toasts *the hold is ended: live stays where it is, and promoting goes on* and the hold is gone from `ao promote status` (TD-226); **Start** on a stopped team whose only member's lane matches nothing opens the dialog *Start lk-grind? · Nothing to pick: every member's lane is empty, so the team will wind down as soon as it starts. · grinder: 0 · Cancel · Start anyway*, and Cancel closes it with the team still stopped (TD-265, TD-262; *Start anyway* not pressed, since it launches claude-code sessions a scratch home cannot log in). Struck. Not pressable there: `auto` promoting by itself (TD-132 (2)) needs green checks, which a repo with no GitHub remote never reads (*checks unknown*); **Snooze on a `stalled?` row** needs a hook-fed session, since only those stall (`agent_tick`: a shell is `working` or `idle`). **Two more the same day, on a second scratch home:** on an unattended shell session with a team, Focus draws **Take over**; once pressed, *more ▾* holds **Hand back** (a session with no team and no controllers reads *Switch to unattended* there, as `cards.py` words it), and Hand back turns the record unattended again, the composer closed (TD-096); on a team the home's `org.yml` defines, with the home made a work tree, **Members…** opens *Members of lk-org*, *stopped: an edit is the definition only — the next Start brings it*, the name prefilled *grinder-lk-2*, and **Add member** lists it, toasts *org.yml: added grinder-lk-2 (grinder) — the team is stopped: its next Start brings the member*, writes one line into `org.yml`, and the home commits it as *org: lk-org added grinder-lk-2 (grinder)* (TD-268). Struck.
**Waits:** event — each press left needs a logged-in session or GitHub, and each live event is read when it happens
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
**Owner:** grinder
**Kind:** live-check #993
**Status:** **Read 2026-10-08 (the anchor, TD-426):** now `Blocked by: TD-299`, the entry that places the first member on a node, so it leaves the lane until then. **A live check waiting on an event (grinder-ao-1, 2026-10-05):** #993 is live, and its *Done when* needs a look sent by a member running on a node, which no grinder can cause — TD-299 places the first such member; whoever reads the home's Inbox after that look reads its thumbnails there. Built — PR #993 (`sessionorc.shots`, `host_shot` and the link's `shot`; the row's `?host=` and the route reading there). The *Done when* waits on the first look from a member on a node (TD-299 places one).
**Blocked by:** TD-299
**Location:** `src/sessionorc/shots.py` (the one reading), `src/sessionorc/agent_remote.py` (`host_shot`), `src/sessionorc/agent_link.py` (the link's `shot`), `src/shiftlead/ui/inbox.py` (`shot_root`, `shot_bytes`, `look_shots` with the sender's host), `src/shiftlead/ui/app.py` (`repo_shot`, `?host=`); design §4.4a *A look's screenshots on another host*, §4.5a **Inbox row: a look** (*through the host whose registry holds the repo*)

**Why:** the row (#982) serves a screenshot only from a checkout in this host's registry. A look sent by a member running on a node (TD-299, `place:`) names a repo that the node's registry holds and the home's does not, so the row draws the file names and no images.

**Fix:** a host-agent read of one `.png` under `docs/mockups/reviews/` at `origin/<default>` of a registered repo, refusing any other path; the route asks the host whose registry holds the sender's record's repo (`repos_of`), as the place check does. Tests: a node-placed sender's look draws its thumbnails.

**Done when:** a look from a member on a node draws its screenshots on the home's Inbox.

**Related:** TD-292 (the row), TD-299 (teams on nodes), TD-057 (the home and node split).

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
**Kind:** live-check #1714
**Status:** **Read 2026-10-14 (grinder-ao-2, `b5096ad` live, which holds #1714): it waits for the person's first rule.** A headless GET of the live `/inbox` (read only) draws no row naming *your permissions: rules* — no prompt has been answered by a rule — and a session cannot read `settings.yml` (`ao settings` is the person's own act), so whether a rule is written is not readable from here. The row itself was looked at on a scratch home with #1714. What is left is the person's, and it is two settings, not one: a `permissions:` rule for a grinder role in `settings.yml`, **and** that role's profile set to `permission_prompts: ask` in `profiles.yml` — an unattended profile defaults to `skip`, so no member's prompt reaches the hook until then. The anchor reads the rest once a rules row shows on the Inbox. On a scratch home (grinder-ao-1, mail `m-0a16fbb045f9`, `b5096ad`): with grinder `allow ['Bash(pdm run test:*)', 'Read']` and `deny ['Bash(rm:*)']`, an unattended record's `pdm run test -q` was allowed and its `rm -rf build` denied, each with *rule: …* as the reason; a Read of `~/.claude/settings.json` (always the person), a prompt no rule covers, and an interactive record's covered prompt were each left waiting; the Inbox drew exactly two *your permissions: rules* rows, each offering Dismiss and the team chip only, with no Overrule. Slice 1 built (grinder-ao-1, PR #1697): the rules at the hook, deny before allow, the always-the-person check (`sessionorc/permits.py`), the FYI with answerer `rules` (a reply to it refused), `permissions` on the settings read with `malformed`, `permission_prompts`. Slice 2 built (grinder-ao-2, 2026-10-14, #1714): the *Answered for you* row whose `answered.answerer` is `rules` names *your permissions: rules*, draws the rule in place of a source and **Dismiss** alone; the Settings page's settings.yml card names each `permissions.malformed` value as ignored; a node's asker was already named — the home's fleet carries its record under the same `<id>@<host>` (a test holds it). Slice 3 built (grinder-ao-1, PR #1708): a node answers by rule only while its link is up and once the home has filed the FYI over it (`answered_by_rule`, a request; the home's `_take_answered_by_rule`, the asker by its address); a link down or a filing refused leaves the prompt for the person. **Built; a live check**: once #1714 is live (`ao promote status`), read the *Done when* on the live home — a `permissions:` rule in `settings.yml` for a grinder role, and the next prompt it covers on an unattended member answered at once with *rule: …* as its reason and filed under *Answered for you* (the Inbox read headless, its row drawing Dismiss alone); no prompt of an interactive session answered by it.
**Blocked by:** decision (paul) — a `permissions:` rule for a grinder role in `settings.yml`, and that role's profile set to `permission_prompts: ask` in `profiles.yml`
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
6a. The seat is the org's, above every project heading (TD-722, amended 2026-10-15): no `team` or `project` badge; the **Org block** in place of a Project block — every registered checkout on its host, read from the repo registry at each fill (not from `projects:`), each named with its project heading where it has one; its record's `dir` its own plain directory outside every repo, `~/.local/share/shiftlead/director/` (§4.9b *The director seat*); and its card drawn in a row of its own at the top of the Org page beside the person's row, only where `director:` is defined, with no Start or Wind down (TD-725's grouping draws it there).
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

## TD-673: ShiftLead's Telegram notes go through samscrape's bot (`secrets: samscrape/prd`): give ShiftLead a bot and a Doppler config of its own

**Priority:** Low
**Type:** debt
**Added:** 2026-10-14 (ao-connect, Paul)
**Owner:** paul
**Kind:** build
**Status:** Open
**Location:** design §4.10 *Told on Telegram* (*Where the secrets live*); `~/.shiftlead/settings.yml` `notify.telegram.secrets`; Doppler

**Why:** the home's `notify.telegram` reads `secrets: samscrape/prd`, so ShiftLead's notes go out through samscrape's bot, with its token and chat (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). That ties the two products together: rotating samscrape's token, retiring its bot or moving its Doppler project silently stops ShiftLead's notes, and the notes arrive under samscrape's name. Paul, 2026-10-14: *set up our own ShiftLead bot instead of piggy-backing on samscrape's*.

**Fix:** done at a sitting with Paul, since each step is his:
1. In Telegram, ask @BotFather `/newbot` (a name such as *ShiftLead*), and keep the token.
2. Send the new bot any message from the chat that should receive the notes, then read that chat's id from `https://api.telegram.org/bot<token>/getUpdates` (`message.chat.id`).
3. Create a Doppler project and config for ShiftLead (say `shiftlead/prd`) holding `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. On the Settings page, set the Telegram card's secrets to `shiftlead/prd`; it is the person's own setting, refused to a session.
5. Check that a note arrives from the new bot, then decide whether samscrape's bot keeps its ShiftLead chat.

**Done when** a ShiftLead note arrives from ShiftLead's own bot, and `settings.yml` names no samscrape secrets.

**Related:** TD-092 (Told on Telegram), TD-648 (`reach.url`, the notes' default link).

---

## TD-703: A member renamed in `.shiftlead.yml` keeps its old name on rule 8's restart, and a person's Start can leave the old record beside the new one

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-14 (ao-paul, with Paul)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-14 (the designer; no mockup: the card's mark draws its lines as it does) — §4.9 *A member renamed or removed in the definition*: the client pairs the records the definition no longer names with the names no record carries, within a role, in order; a pair is a rename, applied by a relaunch under the new name whose create succeeds the old record (mail, open claims, `lane_seen` and every `controllers` carried), a leftover record a removal, marked sat out (`dropped` lets it mark a seat). Read on a stopped team too, and reached only by a person's Apply or Start; Members…'s Remove marks the record the same way. Built by TD-706. Was: Open.
**Blocked by:** TD-706
**Location:** design §4.9 *Where definitions live*, §4.9c *Apply*, §6 rule 8; `src/sessionorc/agent_tick.py` (`_work_start` ~L1670, `_work_replays` ~L1730), `src/sessionorc/work.py` (`crew`), `src/shiftlead/teamrun.py` (`start`, `apply`)

**Why:** Paul renamed dev-cadence's members on 2026-10-14 (dev-cadence `1145d97`: `manager-dc-1` → `dc-manager`, `techlead-dc-1` → `dc-techlead`, `grinder-dc-1` → `dc-grinder`) and saw nothing change. The definition is read — `ao team list` shows *manager: dc-manager (on call) techlead: dc-techlead* — but dc-grind is stopped, and its cards are the closed records of the last run under the old names. Rule 8's start replays a team's ended crew records (`_work_replays`) with their own names and launch records and never reads the definition (§6 *Keeping a team running*), so the team would come back as `grinder-dc-1`. Only a person's Start creates records under the new names, and `crew` is every unattended record of the team: the old ones stay closed, not superseded, and a later rule 8 start could replay them beside the new ones (read in the code, not seen live). Paul: *we should also make sure members are not duplicated on changes as well (e.g. dc-grinder alongside grinder-dc-1)*. The design says nothing of a rename.

**Fix:** decide what a renamed member is: the client finds the difference as it finds a lane's or a profile's (§4.9c, TD-619), shown as **definition changed — Apply**, and Apply (or the next Start) retires the old record — superseded by the new name's, its mail and claims carried — so neither rule 8 nor the card ever holds both. A member removed from the definition is the same case without a successor.

**Done when** the design says how a rename and a removal reach a running and a stopped team, and no path leaves two records for one member; a build entry carries it.

**Related:** TD-619 (a profile change reaches the team), TD-654 (rule 8 replays seats), TD-457.

---

## TD-704: The phase chips (*add*, *design*, *grind*, *review*) are fixed in the UI: define them, and what each matches, beside the roles in `org.yml`, overridable in `.shiftlead.yml`

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-14 (ao-paul, with Paul)
**Owner:** designer
**Kind:** design-first
**Status:** Open
**Blocked by:** decision (paul) — designed in an interactive session with Paul
**Location:** design §4.5a *team card: TDs in motion*, *Org: rollup*, §4.9 *Where definitions live*, §4.9c *Flows*; `src/shiftlead/ui/org.py` (`PHASES` L27, `motion_rows` ~L310)

**Why:** Paul, 2026-10-14: *where are the chip names defined (e.g. GRIND, DESIGN, REVIEW)? it seems like those should be defined beside the roles (in org.yml with repo-level overrides available in .shiftlead.yml)*, and: *having the chip names and entries it matches configurable is the right move for being able to create new flows on the fly. It may need to be designed in an interactive session to make sure we come up with a simple, effective design.* Today `PHASES = ("add", "design", "grind", "review")` is a constant, and `motion_rows` derives a claim's phase in one line: a `design-first` entry is *design*, a claim with a PR *review*, anything else *grind*. A flow with another stage (a fact-check, a live check, a hunt) has no chip of its own.

**Fix:** to be designed with Paul: where a phase is defined (the role, the flow's stage, or a list of its own), what it matches (an entry's `Kind`, a PR, the claimant's role), its order and colour, and how a repo overrides the org's.

**Done when** the design names the definition and its matching rule, and a build entry carries it.

**Related:** §4.9c flows, TD-418.

---

## TD-706: Build TD-703: a member renamed or removed in the definition is paired, applied and started without leaving two records

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-14 (the designer, building TD-703's design)
**Owner:** grinder
**Kind:** live-check #1818
**Waits:** event — Paul's next Apply or Start of dc-grind; read again 2026-10-15 (the anchor): dc-grind stopped, its card still lists the three old names as removed, every dc record closed
**Status:** Live check read 2026-10-15 (grinder-ao-2, #1818 live at a235a54): dc-grind was started under its new names at 04:10Z, before #1807 or #1818 was live, so `dc-grinder`, `dc-manager` and `dc-techlead` were created beside `grinder-dc-1`, `manager-dc-1` and `techlead-dc-1` with no `succeeds`, and the Done when's three renames can no longer be read: the new names carry records, so no newcomer is left to pair. What reads now holds for that state: `ao team list` and the page (headless GET) show dc-grind stopped, *definition changed*, *grinder-dc-1: removed from the definition*, *manager-dc-1: …*, *techlead-dc-1: …*, and Start's confirm says *It first applies the definition:* with the same three lines. Left for the event nobody here can cause (Paul's next Apply or Start of dc-grind), to read then: the three old records (now `sit_out: null`) carry `sit_out: {dropped: true}`, none is replayed, and `ao status -v` shows one record per new name; a rename read as a rename on a live card waits for a team renamed after #1818 went live. Owner anchor until then. Was: Slice 3 built 2026-10-15 (grinder-ao-2, #1818): Apply hands a rename as `relaunch` with the newcomer's `name` and a removal as `relaunch {sit_out, dropped}`, a stopped team's too; Start reads the same pairing after its checks and a concluded team's closes, marks each removal, creates each paired or held newcomer with `succeeds`, lists them in `moved` and its confirm, and refuses a session's start of a renamed team or one beside a live orphan; Members…'s Remove takes the sit-out form with `dropped`. **Live check:** once #1818 is live (`ao promote status`), read dc-grind's stopped card for the three renames of the Done when (a headless GET), and after Paul's Apply or Start, `ao status -v` shows one current record per new name and the old ones `superseded_by`. Not built: a rename pairing an orphan on one host with a newcomer on another is refused by the home's `succeeds` (the pairing is by role alone). Before: Slice 1 built 2026-10-14 (grinder-ao-2): `teamrun.renames` pairs the orphans with the newcomers; `differences` reads `rename` and `removed` (a stopped team's too, alone), first, and a paired or held newcomer is no `start`; the card's mark (beside Start on a stopped team), the member's `flow_mark`, `ao team list` and `ao team flow` print the lines. Slice 2 built 2026-10-14 (grinder-ao-1): `RELAUNCH_KEYS` gains `name` (kept when absent, as `profile`), a rename marked `relaunch.name`; `_replay` creates a renamed record under the launch record's new name with `succeeds: <old id>` (rule 7's restart, rule 8's start, rule 3's fill — a held seat's `_schedule` too); `create`'s `succeeds` is admitted as `keep_mail` is (`_check_succeeds`) and `_succeed` moves the mail, writes `superseded_by` and, at the home, `_carry` copies claims in progress and `lane_seen`, rewrites this host's records' and every launch record's `controllers`, and drops the old launch record (a node's own record waits for its next create, design §4.9, TD-712); `_sit_out` takes `dropped`, which lifts its seat refusal and is kept on the mark; `_seat_pass` never fills a sat-out seat. Until slice 3 Apply skips a rename or a removal and says so (*— not applied yet*), creating nothing. Slice 3 (Apply and Start, `src/shiftlead/`) open. Was: slice 1 built.
**Location:** design §4.9 *A member renamed or removed in the definition* and *Add or remove a member from the team card*, §4.9c *Switching*, §6 *Keeping a team running*, §4.5a *team card: flow changed — Apply*, *team groups* (Apply beside Start on a stopped team) and *Members dialog: Remove*; `src/shiftlead/teamrun.py` (`differences`, `flow_changed`, `flow_view`, `apply`, `start`, `remove_member`, `Difference`), `src/shiftlead/ui/cards.py` (`flow_mark`), `src/shiftlead/ui/org.py` and `src/shiftlead/ui/templates/group_head.html` (the mark and Apply, whose title and confirm name renames and removals, beside Start on a stopped team), `src/shiftlead/cli.py` (`ao team list` ~L1146, `ao team flow` ~L1972), `src/sessionorc/agent_common.py` (`RELAUNCH_KEYS`), `src/sessionorc/agent.py` (`rpc_relaunch`, `_sit_out`, `rpc_create`, `_move_mail`), `src/sessionorc/agent_tick.py` (`_replay`, `_seat_pass`)

**Why:** TD-703's design. Paul renamed dev-cadence's members on 2026-10-14 and nothing changed: rule 8 replays ended records under their own names, a person's Start would create the new names beside the old records, and Members…'s Remove sends a wrap-up that leaves a declared record rule 8 replays at the next wind-down.

**Fix:** this touches `src/sessionorc/**`, so the techlead reads it (§4.9b). Slices, each its own PR:
1. **The pairing** — `teamrun.renames(plan, sessions) -> (renames, removals)` as §4.9 says: orphans (crew, current, not sat out, name not in the definition) against newcomers (definition names no current record carries), paired within a role — a seat with the same seat — orphans by `created`, newcomers in definition order. `differences` gains `Difference` kinds `rename` (record, launch) and `removed` (record), read on a stopped or wound-down team too (renames and removals only there); an orphan whose `relaunch` mark already carries a newcomer's `name` is no difference, and the newcomer reads as held by it. Apply's and Start's confirm list each pair. `flow_mark`, `ao team list` and `ao team flow` print *grinder-dc-1 → dc-grinder: renamed* and *grinder-dc-2: removed from the definition*; the stopped team's card draws **definition changed — Apply** beside Start with the title §4.5a gives.
2. **The home's half** — `RELAUNCH_KEYS` gains `name`; a relaunch whose `name` differs is replayed (rule 7's restart, rule 8's start, rule 3's fill) as a `create` under the new name with **`succeeds: <old id>`**: the old record's mail moved (`_move_mail`), `superseded_by` written on it, its `claimed` progress entries and `lane_seen` copied to the new record, every record's `controllers` and every launch record's naming the old address rewritten to the new, the launch record moved to the new id. `succeeds` is admitted as `keep_mail` is (`_check_keep_mail`: the person, the home's replay, or a controller of the old record) and refused otherwise. `_sit_out` takes `dropped: true`, which lifts its seat refusal; `_seat_pass` never fills a sat-out seat. A node member's own record is rewritten by TD-712.
3. **Apply and Start** — `apply` hands each rename's launch with `name` and each removal as `relaunch {id, sit_out: true, dropped: true}`; `start` reads the same pairing after its checks and a concluded team's closes, creates each paired newcomer with `succeeds`, marks each removal, and lists both in its result and confirm. `remove_member` uses the sit-out form (with `dropped`) for a live or an ended member instead of `_stop_one`.
- **Tests:** a renamed member on a live team relaunches under the new name with its mail, claims and `lane_seen`, and the old record superseded; a renamed manager's members name the new id in their `controllers` and launch records; a stopped team's rename by Apply is replayed by rule 8 under the new name and the old never; a person's Start after a rename leaves one current record per name; a removed member (Apply or Members…'s Remove) is marked sat out and `_work_replays` skips it; a dropped seat is marked and never filled; two orphans and two newcomers of one role pair in order, and the confirm lists the pairs; after Apply on a stopped team the card offers the rename no more; a person's session is never an orphan; the doc-bound §4.5a tests pass.

**Done when** dev-cadence's rename (`grinder-dc-1` → `dc-grinder`, `manager-dc-1` → `dc-manager`, `techlead-dc-1` → `dc-techlead`) reads as three renames on dc-grind's stopped card, Apply or Start brings the team back under the new names with no old record replayed beside them, and every listed test passes.

**Related:** TD-703 (the design), TD-619 (a profile change reaches the team by Apply), TD-163 (Members…), TD-654.

---

## TD-717: A seat whose first hook is lost sits with its brief unsent for hours: the scraped send never fires for Claude Code, and nothing acts on the *brief not sent* mark

**Priority:** High
**Type:** debt
**Added:** 2026-10-15 (ao-paul, with Paul)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-15 (the designer; no mockup: one mark's words and one Inbox reason) — §4.1 *A launch whose hook never comes is recovered*. The scraped send keys on the composer reading empty, whatever the record's state. A record keeps `hook_seen_at`, and only that seeds the agent's fresh-hook table at load: the cause of the 47-minute mark was that a new Claude Code record is `confidence: hook` from its create, so a restart counted its missing hook as fresh. A supervised record marked *no hook since launch*, a seat included, is replayed once (`why: lost-brief`), and the senders of its open asks are told; a second loss is the person's. Neither a promote nor a fill waits for the other. `shiftlead-hook` keeps its traceback in `hook-errors.log`. Built by TD-720. Was: Open.
**Blocked by:** TD-720
**Location:** design §4.1 *A brief whose first hook is lost*, §4.5a *brief not sent* mark, §6 (seat fill and promote); `src/sessionorc/agent_wake.py` (`_first_prompt_road`, `_send_first_prompts`), `src/sessionorc/agent_tick.py` (`_observe`), `src/shiftlead/adapters/claude_code/screen_rules.toml`

**Why:** on 2026-10-15 at 00:42:07 MDT the home filled `ao-shiftlead-techlead-ao-1` for the held-PR ask on #1807; the ask on #1811 (opened 00:42:30) reached the same seat moments later. At 00:42:12 an auto promote restarted the host agent. The new pane's `SessionStart` hook failed with a traceback (run log `ao-shiftlead-techlead-ao-1-20261015T064207Z.log`), and no hook reached the agent. The seat sat at an empty composer, read `stalled?`, until Paul killed it at 08:37. Both asks passed their bound (`ao pr held` reads *bound 2h*) and lapsed to the person. Both PRs, each with a SHIP review, waited unread until Paul killed the seat at 08:37 and grinder-ao-1 asked again at 11:33, and grinder-ao-2's stacked #1818 waited with them. TD-348's fallback did not help, for three reasons:
- **The scraped send needs a scraped `idle` that Claude Code never produces.** `_first_prompt_road` sends once on a scraped `idle` after `FIRST_PROMPT_HOOK_WAIT`. No rule in `screen_rules.toml` matches Claude Code's empty composer, so a hook-fed record with no hook stays `working`, and `_observe` moves it to `stalled?`, never to `idle`. `ao explain --file` on the stuck screen, with and without the hook-error lines, reads *no screen rule matched*. So does a live idle session (`ao-shiftlead-entry-7`, *idle (hook)*).
- **The mark came late, and nothing acts on it.** The agent that started at 00:42:13 did not write *no hook since launch* in its 47 minutes. The agent that started at 01:29:46 wrote it at once (`the brief of ao-shiftlead-techlead-ao-1 was not sent: no hook since its launch`), 47 minutes after the launch, not the 5 minutes of `FIRST_PROMPT_BOUND`. Why the first agent never marked it is not yet known. Once written, the mark is only a card reason: the seat is neither relaunched nor closed, its asks are neither re-rung nor told, and the seat is not refilled because it is still held.
- **A launch just before a promote loses its first hook.** The fill and the restart were 5 s apart. The hook's traceback is not saved (the run log holds only its first line). That it ran against a half-replaced install is a guess, not confirmed.

**Fix** (for the designer to decide):
- A recovery for a Claude Code launch with no hook: a screen rule that reads the empty composer at launch as `idle` so the scraped send can fire, or a send that keys on the composer reading empty (the check `_first_prompt_typing` already makes) in place of a scraped `idle`.
- What the *brief not sent* mark does for an unattended seat: relaunch it once from its launch record (the seat stays due, as its asks are), then close it so the next fill starts clean, and tell the askers whose bound it holds.
- Why a restarted agent did not mark the record within `FIRST_PROMPT_BOUND`, and whether the bound counts from `created` across restarts.
- Whether a fill waits out a promote in progress, or a promote waits for a launch's first hook. And whether the `SessionStart` hook keeps its traceback somewhere readable.

**Done when** a seat launched with its first hook lost gets its brief within minutes, or is relaunched or closed with its askers told, and no seat sits with its brief unsent past `FIRST_PROMPT_BOUND`.

**Related:** TD-348 (the scraped send and the mark, built), TD-342 (its design), TD-341, TD-062 (the promote), TD-706 and TD-710 (the PRs that waited).

---

## TD-720: Build TD-717: a launch whose first hook is lost gets its brief from the composer, keeps *no hook* across a restart, and is replayed once

**Priority:** High
**Type:** debt
**Added:** 2026-10-15 (the designer, building TD-717's design)
**Owner:** grinder
**Kind:** live-check #1838
**Waits:** event — the next launch whose first hook is lost (a *brief not sent* mark); read again 2026-10-15 (the anchor): no record carries `first_prompt_error`, no `lost-brief` in any `restarts`
**Status:** Built — slice 1 (recovery of the send: `hook_seen_at`, the seeding at load, the scraped road on the composer, the mark) by #1834; slice 2 (the replay: `_lost_brief`, a seat's fill context, the senders told, *brief lost twice*) by #1837; slice 3 (the hook's traceback: `shiftlead.hook_entry`, `hook-errors.log`, `paths.hook_errors_file`) by #1838, with #1837's review leftovers: a test holds the fill ceiling's `tripped` to a `why: fill` ceiling, and a seat's ceiling with no `why` reads *restarts exhausted*, not *fills exhausted*. **Live check** once #1838 is live (`ao promote status`), read-only: `~/.local/share/shiftlead-venv/bin/shiftlead-hook` imports `shiftlead.hook_entry`, and no live record carries `first_prompt_error` *no hook since launch* without a `lost-brief` entry in its `restarts` or a `restart_ceiling` (`ao status -v --json`). The replay itself waits for the next lost first hook, an event nobody can cause: if none has come, write what was read here and make the **Owner** `anchor`. **Read 2026-10-15 (grinder-ao-1, live `96c68ac`):** the live `shiftlead-hook` imports `shiftlead.hook_entry` (`from shiftlead.hook_entry import main`, the module present in the venv); `ao status -v --json` lists 20 records, every one carrying the `hook_seen_at` field (set on the seven that have had a hook), none with `first_prompt_error`, no `lost-brief` in any `restarts`, and the only `restart_ceiling` is docs-audit-ao-1's `why: fill`. No lost first hook has come since #1838 went live, so the replay is unread: the anchor reads it at the next *brief not sent* mark — the record replayed once with `lost-brief`, its askers told — and archives the entry.
**Location:** design §4.1 *A launch whose hook never comes is recovered*, §6 rule 1 (*A lost brief*), §4.5a *brief not sent* mark and *Inbox row: restart*; `src/sessionorc/agent_wake.py` (`_first_prompt_road`, `_send_first_prompts`, `_first_prompt_typing`), `src/sessionorc/agent.py` (`_last_hook`'s seeding at load ~L629), `src/sessionorc/agent_hook.py` and `agent_tick.py` ~L3943 (where a hook is applied), `src/sessionorc/models.py` (`Session`), `src/sessionorc/agent_tick.py` (`_keep_running`, `_replay`), `src/shiftlead/adapters/claude_code/hook.py` (`main`), a new `src/shiftlead/hook_entry.py` and `pyproject.toml`'s `shiftlead-hook`, `src/sessionorc/paths.py` (`hook_errors_file`), `src/shiftlead/ui/inbox.py` (`restart_mark`), `src/shiftlead/ui/cards.py` (~L913, ~L951: a seat's `restart_ceiling` words)

**Why:** TD-717's design. On 2026-10-15 a techlead seat filled five seconds before an auto promote lost its first hook and sat at an empty composer for eight hours, while two held-PR asks lapsed to the person.

**Fix:** this touches `src/sessionorc/**`, so the techlead reads it (§4.9b). Slices, each its own PR:
1. **Recovery of the send** (`sessionorc`).
   - **`hook_seen_at`.** `Session` gains `hook_seen_at`, written by the pane's host at the first hook event applied to the record, live or drained from the queue. It is kept across saves and carried by nothing a replay copies.
   - **Seeding at load.** `_last_hook` is seeded for a `confidence == "hook"` record only when it carries `hook_seen_at` or its brief is not `_first_prompt_due`. Today every `confidence == "hook"` record is seeded. The second test keeps every record from before the field seeded as today.
   - **The scraped road.** `_first_prompt_road`'s `scraped` road no longer needs `state == "idle"`. It needs:
     - no `hook_seen_at`;
     - no entry in `_last_hook`;
     - no try made;
     - age at least `FIRST_PROMPT_HOOK_WAIT`;
     - a state that is not `needs-you`, `exited` or `closed`, and not `superseded_by`.

     `_first_prompt_typing` already insists on the composer reading empty for this road. An adapter with no `composer` reader keeps needing a scraped `idle`.
   - **The mark.** `_send_first_prompts`' *no hook since launch* mark reads `hook_seen_at`, not `_last_hook`, so it is written at `FIRST_PROMPT_BOUND` across restarts.
2. **The replay** (`sessionorc`).
   - **Who is replayed.** The tick replays a supervised record (a team member or a seat) whose `first_prompt_error` is *no hook since launch*, on the next tick. It first closes the live record, through `rpc_close` with closer `{by: tick, why: lost-brief}` and `_mark_closed`, as rules 2 and 7 do before `_replay` (agent_tick.py ~L785–L925); the run never started, so no `restart_blocked` applies. It then replays it as rule 1's replay does: `create` with `keep_mail`, `restarts` gaining `{at, why: "lost-brief"}`, counted in `RESTART_CEILING`.
   - **A second loss.** A record whose newest `restarts` entry is `lost-brief` and that is marked again is not replayed. It is written `restart_ceiling: {at, count, why: "lost-brief"}`, with `count` the record's `lost-brief` replays (so 1), and `ui/inbox.py`'s `restart_mark` and `cards.py`'s seat words (~L913, ~L951, which today read any seat ceiling as *fills exhausted*) read that `why` as *brief lost twice*, with no count. The fill ceiling's `tripped` test (~L2610) counts only a `why: "fill"` ceiling. The *brief not sent* mark stays.
   - **A seat's replay** passes the fill's `closing` (`filled_for(seat_due)`) again and sets `seat_filled`, as rule 3's fill does (agent_tick.py ~L2605–L2630). `lost-brief` is not counted by the fill ceiling (`why == "fill"`). A failed close is the replay entry's `error`.
   - **The senders.** After the replay, each sender of an `ask` or `steer` still open in the moved inbox gets a system note in the design's words. Bounds are unchanged.
   - **Who is left alone.** A person's own session, unsupervised, is never replayed.
3. **The hook's traceback** (`shiftlead`). `pyproject.toml`'s `shiftlead-hook` points at a new `shiftlead.hook_entry:main`, a module of the standard library alone (`src/shiftlead/__init__.py` is empty; `shiftlead.adapters.claude_code`'s `__init__` imports `sessionorc`, so the hook module cannot be the entry). It imports `shiftlead.adapters.claude_code.hook` inside a `try` and calls its `main`. An exception in the import is appended to `<home>/hook-errors.log`, the home read from `SHIFTLEAD_HOME` else `~/.shiftlead` without `sessionorc.paths` (cut to its last 256 KB when it passes it; `paths.hook_errors_file()` names the same file for readers), with the time, `SHIFTLEAD_SESSION` and the event name. The hook then exits 1, Claude Code's non-blocking error, so it still shows its one-line *hook error* as §4.1 says (the build found this line saying 0, which would hide it).
- **Tests:**
  - A Claude Code record created with no hook, reading `working` with an empty composer, gets its brief by the scraped send after `FIRST_PROMPT_HOOK_WAIT`.
  - The same record with a dialog on screen does not.
  - A live hook-fed record from before the field (no `hook_seen_at`, brief sent) is seeded at load.
  - An agent restarted after the launch does not seed it, sends it, and marks it at `FIRST_PROMPT_BOUND` when the composer never reads empty.
  - A record with `hook_seen_at` is seeded as before.
  - A marked seat is replayed once with `lost-brief`, its open ask moved and its sender told.
  - A second loss is not replayed and reads *brief lost twice*.
  - An unsupervised marked record is left alone.
  - The hook's import failure writes `hook-errors.log` and exits 1.

**Done when** a seat launched with its first hook lost gets its brief within `FIRST_PROMPT_HOOK_WAIT` of its composer reading empty, or is replayed once with its askers told, no record waits past `FIRST_PROMPT_BOUND` unmarked across an agent restart, and every listed test passes.

**Related:** TD-717 (the design), TD-348 (the scraped send and the mark), TD-342, TD-062 (the promote).

---

## TD-723: Backfill TD-722: samscrape and contractmatch under one ContractMatch project

**Priority:** Low
**Type:** feature
**Added:** 2026-10-15 (Paul, in an interactive session)
**Owner:** paul
**Kind:** build
**Status:** Open
**Blocked by:** TD-722
**Location:** `~/.shiftlead/org.yml` (`projects:` — today `samscrape` and `contractmatch`, one repo each); `~/samscrape/.shiftlead.yml`, `~/contractmatch/.shiftlead.yml` (their teams, defined there since 2026-10-03)

**Why:** Paul, 2026-10-15: *file a backfill to have samscrape and contractmatch both be on the ContractMatch project.* The two repos are one product; once a project is a heading on repos (TD-722), they share one, which draws them together on the Org page, lets their teams settle things by mail (§4.10 *across teams, by project*) and gives each session the other repo in its Project block.

**Fix:** once TD-722's build is live, one project, `contractmatch` (drawn *ContractMatch* if the design gives a heading a display name), listing both repos with their checkouts per host, in place of the two one-repo projects; the teams in each repo's `.shiftlead.yml` changed only as TD-722's migration says. A session live at the change keeps its old `project` badge (`samscrape`) until its next start, since the badge is written at create, so the two repos' teams mail each other only once each has restarted: make the change between runs, or accept the lag. Paul decided the change on 2026-10-15; Paul makes it once TD-722's build is live, with a backup of the org file first (`org.yml.bak-<date>-<what>`), as earlier org-file edits had.

**Done when** the Org page draws samscrape and contractmatch under one ContractMatch heading, and a samscrape session's brief names contractmatch's checkout in its Project block.

**Related:** TD-722.

---

## TD-748: The Queue: one card per effort — a TD and everything its `Blocked by:` joins, with its asks — ranked by the person, the rank the pick order; the Inbox keeps what names no TD

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-15 (Paul, in an interactive session)
**Owner:** designer
**Kind:** design-first
**Status:** Designed (2026-10-16, the designer): §4.4 *The Queue: cards, and the rank that orders them* (components with no exception, the top entry, rows and their state words, *stalled* at `QUEUE_STALL_AFTER`, the card's status, completed cards, lined and implicit keys, the rank file `<ledger stem>_rank.yml`, intents flushed as `queue: rank` PRs by the board's road, the rank the pick order); §4.5 screen 12 *Queue*, screen 6 *Where a row is drawn* (`home: inbox|queue`, the numbers unchanged) with its ledger and held rows on their cards, screen 11 item 2 the repo's cards; §4.5a nine Queue rows; §4.7 `ao rank`; §4.8 *Choosing in a free-pick lane* by rank; §4.10 `about` from the sender's claim and *The Inbox is a queue* renamed *Nothing leaves the Inbox without an answer*; glossary *Queue*, *card*, *rank*, *stalled*. Built by TD-769, TD-770, TD-771, which wait on dev-cadence#TD-119 (ledgerboard's components, keys and rank file; cadence's `queue-edit` class); the trial read back by TD-772. Was: Agreed 2026-10-15 — [ADR 2026-10-15](decisions/2026-10-15-queue.md), reviewed by Fable (four rounds converged, final AGREE) and Sonnet (three rounds, READY). A mockup drawn from the real ledger and inbox was reviewed with Paul over seven rounds the same evening, and the ADR amended from it (§9: one card rule with no exception, the header the top entry, no red, *waiting* beside *blocked*, `decision (paul)` drawn as a hold, no Snooze on the Queue, move buttons; round 6: the Queue's look from a frontend-design pass, titles wrapped in full, completed cards opening to each entry's `Resolved:`); Fable and Sonnet rounds on the amendment converged (round 2 READY) and round 6 was fact-checked by Sonnet; merged as #1887. **Paul lifted the hold 2026-10-15 23:44 MDT** (in an interactive session): the design round is next, the designer's. The builds will wait on a dev-cadence entry (the rank file's format and order in ledgerboard, the `queue-edit` audit class), filed when the design names it.
**Blocked by:** TD-769, TD-770, TD-771, TD-772
**Location:** `docs/decisions/2026-10-15-queue.md`; the design text it rewrites: §4.4 *Repo facts*, §4.5 screens 6 and 11 (4.5-ui.md:511–512, 1058), §4.5a a row per new control, §4.7 `ao rank` and `ao repo`, §4.8 *Choosing in a free-pick lane* (4.8-capabilities-roles.md:531–540), §4.10 (4.10-messages.md:719), the grinder and designer briefs

**Why:** Paul, 2026-10-15: *what I really care about is — where is TD/feature X that I added recently (already done, being worked, waiting to be worked, needs me for something)*, and *I want to know that my teams are working, and working the things I think are important first (dependencies considered)*. The Inbox is per message and orders by `Due:` dates he finds arbitrary; picks go by High/Medium/Low (36 of 56 open entries are Medium at filing) and nothing lets him say what comes next.

**Fix:** the ADR, whole: a `/queue` page of cards (connected `Blocked by:` components across repos, no exception), each headed by its top entry with its rows' states and its asks; groups Recently completed / In progress / Up next; the person drags or moves cards, the rank written to `docs/technical_debt_rank.yml` one line per member by debounced tool PRs, every undragged entry ranked implicitly by Priority, Type and id; the rank is the pick order by convention; the Inbox draws only what names no TD. Slices: (1) ledgerboard rank file + order + `ao rank` + briefs; (2) the Repo page's cards; (3) the Queue page. A two-week trial from slice 3, read by passed-over flags, idle-while-work lines and the oldest unanswered TD ask.

**Done when** the design says all of the ADR, its build entries are filed with the dev-cadence entry in their `Blocked by:`, and this entry's `Blocked by:` names them.

**Related:** TD-604, TD-693, TD-715, TD-716, TD-734, TD-749.

---

## TD-772: Read back the Queue's two-week trial to Paul — passed-over flags a week, idle-while-work lines, the oldest unanswered TD ask

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-16 (TD-748's design, the designer)
**Owner:** grinder
**Kind:** build
**Status:** Open — waits for the trial's two weeks since TD-771's last slice merged (#1967, 2026-10-16)
**Waits:** until 2026-10-30 — the Queue's two-week trial, from TD-771's last merge on 2026-10-16
**Location:** design §4.5 screen 12 (*A trial*); [ADR 2026-10-15](decisions/2026-10-15-queue.md) §7; the doing log (`doing.jsonl`), the `queue` reading's passed-over flags, the person inbox's open asks (read only)

**Why:** TD-748: Paul decides from the trial whether the Queue keeps its place beside the Inbox, and what changes in the lanes; no lane change is made before it reads back (ADR §7).

**Fix:** once its `Waits:` date has passed, read over the fourteen days: the passed-over flags per week (from the claims' first `ao doing` lines against the rank at the time, since the flags are not kept), the doing log's lines of a member idle or out of work while its lane held unclaimed pickable work, and the age of the oldest unanswered `ask` about a TD on each day; put them to Paul as one `ask` with the ADR's choices, his answer written into TD-748's ADR and, where it changes the design, a design-first entry.

**Done when** the three readings are written in this entry's Status and Paul's decision is recorded.

**Related:** TD-748, TD-771, TD-460 (the same shape of trial read).

---

## TD-786: Build TD-112 (3): the Gemini CLI adapter's reads — transcript, context, links, model, start context, mail, background, usage and spend; the full conformance suite live

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-16 (TD-112's design, the designer)
**Owner:** grinder
**Kind:** build
**Status:** Open — slice 1, the reads (`transcript_path`, `read_transcript`, `context`, `model_in_use`, `links`, `spend`), in #2266; slice 2, start context, mail and the repo's start hooks (the layer's `SessionStart` timeout raised, so the installed layer reads *stale* until reinstalled), in #2269; slice 3, `background` (the relaunched `node`'s shell wrappers, a fixture captured from 0.64.0), in #2271; `usage` moved to TD-959 (it reads the person's Google token); the live walk is left, on 0.65.0 (Paul: *Keep 0.65.0*, m-5a05c82759c8, to the ask m-cd1f21682bb1). Read 2026-10-22 23:31Z (grinder-ao-1, `pdm run conformance gemini --profile gemini-conformance`, Gemini CLI 0.65.0): launch, first hook and a short prompt held; the permission step did not — after the `touch` prompt the record read `working` (`hook`) for the walk's 300 s and no `needs-you` was seen, with no pane captured. A second walk with `--capture`, right after it, stopped at the short prompt on the tool's *Usage limit reached for gemini-3.8-flash* dialog (read as `limited`, `scraped`): the profile's daily quota was spent, likely by the first walk's retried turn, so whether the first walk's permission was the limit too or a 0.65 dialog the screen rule misses is open. Read again, with `--capture`, once the quota resets; the 0.65 captures are not committed (the limit dialog in place of the turn's panes). Read again 2026-10-23 14:21Z and 14:26Z (grinder-ao-1, two walks with `--capture`, 15 h after the quota was seen spent): launch and first hook held both times, and the short prompt (*Reply with the one word: ready*) did not. Each walk's capture of the pane at the timeout (`panes/3-a-short-prompt.txt`, read and not committed) showed the tool's *…taking a bit longer, we're still on it* with *esc to cancel, 5m*, and each chat file holds the prompt with no reply and no error. That is the tool retrying a request it cannot get answered, most likely the account's quota or capacity, not the adapter. Both chat files end with a SessionEnd hook failure at the teardown. The next walk should run with the tool's debug output (`--debug`, or its F12 drawer) to name the error the tool keeps retrying. Read 2026-10-24 06:00Z (grinder-ao-2, `gemini --debug -p` on the profile's home): the hang is the tool's default model, gemini-3.8-flash — `fetch failed sending request`, then `503 … This model is currently experiencing high demand` on every retry — while gemini-2.5-flash answered at once. Walked on gemini-2.5-flash (a scratch `SHIFTLEAD_HOME` whose `profiles.yml` copies `gemini-conformance` with `model: gemini-2.5-flash`; the live file read only): launch, first hook and the short prompt held; the permission was seen `needs-you` and allowed by the walk's Enter, the command ran and `AfterTool` and `AfterAgent` landed, and the record still read `needs-you` for 300 s — the stack kept a permission for a waiter a Gemini one never has. Slice 4 fixes it (the main thread's next event ends a no-channel permission, §4.2, §4.3), in #2323; the walk again with it: four steps held, the permission included. The doorbell rang (`BeforeAgent` carried *you have 1 unread messages — run ao inbox*) and gemini-2.5-flash answered *Would you like me to run ao inbox?* instead of running it, so the mail, resume and transcript steps wait for the default model; captures not committed.
**Waits:** until 2026-10-26 — gemini-3.8-flash answers `gemini-conformance` (`gemini --skip-trust -p` from its home, no `503`); then the live walk with `--capture` on the tool's default model
**Location:** design §4.3 *The second adapter: Gemini CLI*; `src/shiftlead/adapters/gemini/` (a `transcript.py`); `tests/conformance/fixtures/gemini/`

**Why:** TD-112, slice 3: what the pages and the policies read from a session, so a Gemini session's card, transcript page and rule 5 (the context bound) works as a Claude Code one's does.

**Fix:**
- **`transcript_path(session_id, cwd, profile)`** (the home from the profile): the hook's reported path kept on the record, else `chats/session-*-<id[:8]>.jsonl` (top level only: `chats/<parent>/` holds subagents) whose first record's `sessionId` is the id.
- **`read_transcript`**: last line per record id, `$set`/`$patch`/`$rewindTo` applied, `user`/`gemini` mapped to neutral entries (a prompt, text, thoughts, tool calls with results); the tool's `<session_context>` preamble shown as context, not a prompt.
- **`context`**: the last `gemini` record's `tokens.input`, `window` 1,048,576 (256,000 for a Gemma model). **`links`**, **`model_in_use`** (the record's `model`), **`spend`** for a metered profile, the subagents' chats under `chats/<parent>/` included: `cache_read` = `cached`, `input` = `input` − `cached`, `output` = `output` + `thoughts`, `cache_write` absent, a record counted once at its last line (its `id` as the turn's `id` and `response`).
- **`start_context = True`**: the layer's SessionStart hook prints `additionalContext` from the record's `start_context`, on startup and resume; the host agent types the first prompt only after the SessionStart report.
- **`mail`**: BeforeAgent's `additionalContext` carries the inbox's top-of-turn delivery; the doorbell stays a pane write. **`links`** deduped by record id.
- **The repo's start hooks**: `shiftlead-hook --adapter gemini` on SessionStart runs `scripts/cadence_hooks.sh --session-start` itself where executable (the main checkout's runner, as §4.2's line does), its stdout in the same `additionalContext` (plain stdout would be an on-screen message), that hook's `timeout` at least 150000 ms (the runner's 150 s bound).
- **`background`**: the pane's `node`, its relaunched `node` child, that child's shell children.
- **`usage`**: a Google-login home's quota endpoint (`retrieveUserQuota`) into windows labelled by model; an API-key home None.
- **Tests**: fixtures of each record kind and patch; the offline suite in full for `gemini`. Live: the full walk, including the mail and the doorbell, output in the PR.

**Done when** a Gemini session's transcript page, context bound (rule 5), start context, mail and the cadence start hook work as a Claude Code session's do, and the full conformance suite passes for `gemini` offline and live.

**Related:** TD-112, TD-784, TD-785.

---

## TD-794: The Focus terminal shows a reply's lines cut off mid-word, and a block of it twice: a resize makes Claude Code repaint over lines tmux has already kept, and no refresh can mend them

**Priority:** Low
**Type:** debt
**Added:** 2026-10-16 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** paul
**Kind:** build
**Status:** In progress (grinder-ao-2). Slice 1 #2129 (2026-10-18), step 2's cure: the Focus sends one `{resize}` per gesture — the last grid once the box has been still 150 ms, none when tmux already has it (`AO.resizeSender`, design §4.6). Counted on a scratch home in headless Chromium: a 30-frame narrowing of the window sent 29 `{resize}` frames to the bridge before, one after (the final grid, 84×34, the same). Left: steps 1, 3 and 4 with a Claude Code session printing a long reply — compare `tmux capture-pane -p -S -` before and after a drag, a put away and a Settings size, now at one resize per gesture, and write the damaged-line count here; a scratch home's sessions are `shell`, so this needs a Claude Code session in a throwaway profile — an attended run, so the entry is Paul's (grinder-ao-2, 2026-10-18).
**Location:** design §4.6 *Attach behaviour with another client present* (`window-size latest`, and `window-size manual` plus a fixed `default-size` named as the fallback if the reflow upsets Claude Code's TUI), *Scrollback is tmux's, reached through tmux* (TD-022); §4.5 *The panel put away* (the terminal refits as a window resize does); `src/shiftlead/ui/static/app.js` (`new ResizeObserver(() => fit.fit())` and `term.onResize` → `{resize: [cols, rows]}`, ~L4536–L4537: one resize per observed frame, no debounce; `AO.setTermLook`, ~L70, refits on a face or size change); `src/shiftlead/ui/pty_bridge.py` (`resize`, ~L95, `setwinsize` on the attach's pty); `src/sessionorc/tmux.py` (the session options, `history-limit` ~L113)

**Why:** Paul, 2026-10-16, on `ao-queue-vs-inbox`'s Focus scrolled back in tmux's copy mode: the line *That was the last part of TD-769's live check. A builder will now find the check in its lane, read #1950 and cl* stops at *cl*, and the next line starts a different paragraph (*- The rank file: …*); a page refresh mended a different line but not this one. He asked whether resizing does it. The record says yes, and that the damage is in the pane itself, not the browser: `ao tail ao-shiftlead-ao-queue-vs-inbox -n 3000` (tmux's own capture, at the pane's current width) holds the same reply mangled differently — *a new* ends a line mid-sentence and the next line starts *- The rank file:*, and the bullets and the *The system recorded the move…* paragraph appear **twice**. Claude Code redraws its last frame when the pane's width changes. tmux had already put part of that frame into its history and reflowed it to the new width, so the redraw writes over lines that have moved and leaves the old copy's fragments behind. A browser refresh re-attaches and tmux repaints the visible screen, but history already written stays as it is: hence *helps, but not fully*. Any Focus resize can do it: a window drag, **» put away** and back, a terminal face or size from Settings, a second client under `window-size latest`. Today a drag sends one resize per observed frame. The harm: a reply the person reads back can silently lose words or repeat a block, and nothing on the page says the text is damaged.

**Fix:** an evaluation, then a build.
1. **Reproduce it on a scratch home** (`scripts/look_home.py`) with a Claude Code session printing a long reply. Resize the Focus by a drag, by **» put away**, and by a Settings size, then compare `tmux capture-pane -p -S -` before and after. Count the resizes the bridge receives per gesture.
2. **Measure the cheap cure first:** debounce the fit, so one gesture sends one `{resize}` with the final grid (~150 ms, after the last observed change), and send nothing when `cols`×`rows` is unchanged. Count the damaged lines with and without it.
3. If damage remains at one resize per gesture, weigh §4.6's named fallback, `window-size manual` with a fixed `default-size`. It ends reflow, but a narrower Focus then crops instead of wrapping. That changes behaviour the design describes, so it is a design PR first, with the person's look.
4. Whatever is left, which is Claude Code's own repaint, goes in the adapter's notes with the version it was seen on, so the next sighting is recognised and not re-filed.

**Done when** the evaluation's measurements are written here, the debounce has landed or been shown not to help, and any design change has a filed entry of its own.

**Related:** TD-022 (scrollback through tmux), TD-474 / TD-480 (*resized by another client*, the terminal mark), TD-288 (Settings' face and size refit the grid), TD-491 (the folded composer: *a resize would make the tool repaint*).

---

## TD-820: The designer runs far past its context bound inside one design: nearly a quarter of its requests read over 300k tokens and its median is 209k, against the grinders' 151k

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-16 (Paul's session, from a read of the transcripts asked for by Paul)
**Owner:** designer
**Kind:** design-first
**Status:** Designed 2026-10-17 (design §6 rule 5 *A waiting claim is not in progress*, *A replay carries the waiting claims*; §4.8 *A designer's context*). The reading: the context grows **across** designs, not within one. `_context_line` held the bound's line back while any declared claim stood, and a designer holds its designs claimed while their steers and readers run, so it was never told. A claim with an open PR whose next move is someone else's is now waiting, not in progress; the member is told once it holds only waiting claims; the restart carries the waiting claims, so the leases hold. Every tick replay carries the waiting claims with a renewed lease, the idle nudge passes over them, and a run holding only waiting claims declares `none` beside them. The designer's brief keeps reads small (review rounds as subagents returning a verdict, large replies by the slice). Rejected, with the reasons in design-history §6: a restart point inside a design, a designer-only bound, nothing. TD-818's past-300k share per seat is the measure after.
**Blocked by:** TD-836, TD-837
**Location:** design §6 rule 5 (*Context bound*: restarts between entries, never mid-turn), §4.8 *The bound has two layers* (300k for every role that sets none); `src/shiftlead/briefs/designer.md`; `.shiftlead.yml` (`roles: designer:` sets no `context:`)

**Why:**
- designer-ao-1 is an unattended member, so it takes the 300k default bound. Rule 5 only asks a member to restart between entries, and a design is one long entry: the Fable proposal, its rounds with Sonnet and Fable reviewers, the fact-check and the PR.
- Read from its transcripts, 2026-10-09 to 10-16 (main conversation, each response once): 4,105 requests, median context 209k, p90 395k, **955 over 300k**, the largest 813k. Over the same days grinder-ao-1 read a median 151k, p90 223k, and 48 requests over 300k. The techlead read a median 88k, with none over 300k.
- Requests over 200k carried 35% of the weighted cost in TD-378's week. Fable's input is priced at 2.5× Opus 5.5's ($10 against $4 per million tokens on Anthropic's API list), and about 30% of the designer's requests that week were Fable.
- TD-460 measured the grinders' bound and found it flat: the saving in context went on extra restarts. That says nothing about the designer, whose context grows within one entry, where the bound never acts.

**Fix:** design first; measure before choosing.
- From the transcripts, find where a design's context grows: reading the design sections, the review rounds coming back, fact-checks.
- The candidates:
  - a restart point inside a design (after the proposal is written to its branch, before the rounds), carried by the branch and the entry;
  - review rounds run as fresh subagents that return a verdict, not whole transcripts;
  - a designer-specific bound with a mid-entry checkpoint;
  - nothing, if the cost per finished design is already lowest as it is.
- TD-818's spend per finished entry is the measure once it exists. Until then, the hand read is the same as TD-460's.

**Done when** the reading says where the designer's context goes, and the design either gives the designer a restart point or a bound with its build entries filed and named in `Blocked by:`, or says, with the numbers, why it stays as it is.

**Related:** TD-460 (the grinders' bound trial), TD-378 (the prompt cache, archived), TD-818 (spend per seat), rule 5.

---

## TD-836: Build TD-820 (1): rule 5 reads a waiting claim as not in progress, and the restart carries the waiting claims

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-17 (TD-820's design, the designer)
**Owner:** grinder
**Kind:** live-check #2048
**Waits:** event — the next member idle over its context bound whose only claims wait on a steer or a reader; read 2026-10-17 21:10Z (grinder-ao-1, #2048 live in 165d7c5): no record carries `context_sent_at`, and no `restarts` entry since the promote carries a waiting claim
**Status:** Built (2026-10-17, #2048): `agent_tick._waiting_claims` reads the waiting claims; `_context_line` and `_nudge_line` pass over them, the line ends *; #n carry over*, and `_replay` carries them. Live check, once #2048 is live (`ao promote status`): read an unattended designer (or any member) idle over its bound whose only claims wait on a steer or a reader — `ao status -v` shows `context_sent_at` set and its pane's last send is the line ending *carry over*; after its restart, its new record's `progress` holds those claims `claimed` with `at` the `restarts` entry's `at`, and the entry's `left` lacks them; and no idle nudge names them while their replies are out.
**Location:** design §6 rule 5 (*A waiting claim is not in progress*, *A replay carries the waiting claims*), rule 4 (the idle nudge), rule 1 (`left`), §4.9a *The third declaration*, §4.2 *Waiting*, §4.8 *A claim is a lease*; `src/sessionorc/agent_tick.py` (`_context_line`: the `any(e.status == "claimed" and e.source == "declared" …)` test; `_idle_nudge`), `src/sessionorc/work.py` (`waiting_of`, read only), the seats' `prs_waiting`, `src/sessionorc/agent_tick.py` (`_replay`), `src/sessionorc/agent.py` (`_carry`'s copy of claims, the model), `src/sessionorc/models.py` (`review_pr`, `_note_review`)

**Why:** TD-820: the designer is never told it is past its bound. `_context_line` returns while any declared claim stands, and a designer always holds designs waiting on a steer or a reader.

**Fix:**
- **Waiting.** A helper `waiting_claim(record, entry, now)` is true when two things hold:
  - The claim's PR is open: its `pr` or `review_pr`.
  - The record waits on it: `waiting_of` names the reference, or the record's ask for that PR is in a seat's `prs_waiting.asks`.
  - Rules 9, 3, the flow's restart and §4.10 keep reading the claim as in progress.
- **Rule 5.** `_context_line` returns only for a declared claim that is not a waiting claim. When the member holds waiting claims, the line ends *; #n, #m carry over*.
- **Rule 4.** `_idle_nudge` does not count a waiting claim as open work.
- **The carry.** Every tick replay that keeps mail (rules 1, 2, 7 and 8, `_replay`) copies the old record's waiting claims onto the new record, as `_carry` does, each with `at` set to the replay's time (a lease renewal). `left` names only the claims that were not waiting. A person's **Restart** still starts fresh.
- **Tests:**
  - A member idle over its bound whose only claim has an open PR and its own open steer about it is told. With an open PR and nothing waiting (CI running, its own merge), it is not.
  - With a held-PR ask in `prs_waiting.asks`, it is told.
  - The line names the PRs.
  - The idle nudge passes over a waiting claim and still names one that is not.
  - Each tick replay copies the waiting claims with a new `at`, and `left` lists the rest. A person's Restart copies none.
  - Another member's claim on a carried reference is refused as a held lease.
  - A seat is still never told.
  - A member that declared `none` beside a waiting claim reads unfinished: rule 9 still counts the claim, so its team does not wind down under it.

**Done when** an unattended designer holding only designs that wait on steers is told at its bound, and its next run starts holding those claims, unnudged until their replies land.

**Related:** TD-820 (the design), TD-190 (rule 5), TD-706 (`_carry`), TD-245 (`_replay`), TD-814 (the review phase), TD-837.

## TD-846: Compliance before shiftlead is sold: SOC 2 and ISO 27001 wait for a hosted or team edition; the EU Cyber Resilience Act and the supply-chain basics a buyer asks for come first

**Priority:** Low
**Added:** 2026-10-17
**Owner:** paul
**Kind:** decision
**Blocked by:** decision (paul) — which paid option, if any, [the monetisation decision](decisions/2026-10-13-monetisation.md) takes; nothing here is started before then (Paul, 2026-10-17: *low priority, pushed off until we get closer to monetization*)
**Status:** Open — deferred.
**Location:** `docs/decisions/2026-10-13-monetisation.md`; the repo root (`SECURITY.md`, absent); `.github/workflows/` (release and scanning); the wheel `ao service install` writes to `~/.shiftlead/wheels/`

**Why:**
- Paul asked (2026-10-17, the `security` session) whether SOC 2, ISO or other compliance applies to shiftlead.
- SOC 2 and ISO 27001 certify an organisation that operates a service and holds customer data. shiftlead today is MIT, self-hosted, one person per home (design §1, §2), with nothing hosted, so there is nothing for an auditor to examine. They begin to matter on options 2, 3 and 5 of the monetisation doc:
  - **A hosted or relay part** (option 3's managed host, option 5's ciphertext relay; anything that carries sessions, transcripts or keys): SOC 2 Type II (US buyers) or ISO 27001 (EU buyers), and GDPR processor duties with a DPA.
  - **A paid team edition sold to companies:** their procurement sends security questionnaires even for self-hosted software. A SOC 2 report helps and is not required. The product features they need are the ones option 2 lists: identity-provider sign-in, roles, an audit log of who typed into which session.
- What applies to self-hosted software regardless, and is cheap before it is dear:
  - **The EU Cyber Resilience Act.** It covers software with digital elements placed on the EU market. Non-commercial open source is largely exempt; a paid edition is in scope. Vulnerability reporting duties apply from September 2026, the rest from December 2027: a vulnerability disclosure policy, an SBOM, security updates for the support period, secure-by-default settings.
  - **Supply-chain basics a questionnaire asks for:** a `SECURITY.md`, an SBOM of the wheel, signed release artifacts, dependency and secret scanning in CI.
  - **Sensitive data shiftlead keeps:** run logs, mail and pane scrollback under `~/.shiftlead` can hold secrets and personal data. Their retention, redaction and file modes matter more to a real user than a certificate (TD-131 holds retention for mail and records).
  - **Anthropic's terms for unattended use:** whether `ao new --unattended` on a subscription, rather than an API key under the Commercial Terms, fits Anthropic's usage terms. Not read yet; read it before shiftlead is offered to others.
  - **The EU AI Act:** orchestrating general-purpose models for coding is very unlikely to be high-risk; at most transparency duties, only if sold in the EU.
- The dates and scopes above are as known on 2026-10-17 and were not re-read against the regulations' text; check them when the entry is picked up.

**Fix:** when the monetisation decision names a paid option:
1. Read the CRA's obligations for that option (manufacturer of a commercial product, or open-source steward) and Anthropic's current terms for unattended use, and write the answer here.
2. Land the basics as build entries: `SECURITY.md` with a disclosure address, an SBOM and a signature on the release wheel, dependency and secret scanning in CI, and a retention and file-mode rule for `~/.shiftlead`'s logs.
3. Only for a hosted part or a team edition: choose SOC 2 Type II or ISO 27001 by the first buyers' region, and file the controls work (access control, audit log, change management; the cadence's branch, review and merge loop is already most of the last).

**Done when** the paid option's obligations are written here, and the basics are built or each is archived with its reason.

**Related:** [`docs/decisions/2026-10-13-monetisation.md`](decisions/2026-10-13-monetisation.md) (options 2, 3 and 5), TD-131 (retention), design §2 (multi-user access is a non-goal for now).

---

## TD-850: A member waiting on CI or a lane polls in its own turn — a foreground `timeout 180 tail -f /dev/null` between `ao status` reads — because no brief says what wakes it besides mail

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-17 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** grinder
**Kind:** live-check #2328
**Waits:** until 2026-10-31 — a week of members' runs with the wait guard live (#2328, TD-992); if it is promoted later than 2026-10-24, read a week from its promote
**Status:** Built (2026-10-17, #2051): §4.10, `ao --skill` and every role preset say a member never waits in its own turn and what wakes it. Live check, once #2051 is live (`ao promote status`) and a week of runs has started on the new briefs (2026-10-24): read the members' transcripts (`ao transcript <id>`, read-only) for a foreground wait loop — `sleep`, `tail -f /dev/null`, `timeout N` between `ao status` reads; none holds it, one found is a new entry. **Read 2026-10-24 06:05Z (grinder-ao-1)**: every unattended member's Claude Code transcript since #2051 went live (2026-10-17 20:43Z), read-only, the commands each ran in the foreground: no `tail -f /dev/null` and no loop of `ao status` reads anywhere — the polled loop this entry was filed for is gone. What is left is TD-991: on briefs carrying the new sentence, the techlead and the test auditor still waited on CI inside their turn (a foreground `timeout 110`–`1800 gh pr checks <n> --watch`, 2026-10-22 and 10-23), and members tried a foreground `sleep 100; cat <their background task's output>` that the tool refused (grinder-ao-2 10-24, dc-grinder and test-audit 10-23). This check waits on TD-991. **TD-991 built 2026-10-24** (TD-992, #2328): the wait guard refuses an unattended Claude Code session's foreground CI watch; the check is now a week of transcripts with it live — no foreground CI watch run, and one refused shows as the tool's refusal, then the same command in the background.
**Location:** design §4.10 *Waiting on mail is ending the turn*, §4.2 *Working on its own*; `src/shiftlead/skill.md` (*Mail*: *Waiting on mail is ending the turn*); every role preset's first paragraph in `src/shiftlead/briefs/` (`grinder.md`, `designer.md`, `hunter.md`, `auditor.md`, `manager.md`, `manager_on_call.md`, `techlead.md`, and the `.stage.md` variants where they carry the line)

**Why:**
- Paul's screenshot (2026-10-17, ~19:15Z, grinder-ao-1's Focus): the grinder had declared *out of work* 10 minutes earlier and sat `working` in a foreground loop on `pr:2019` — `timeout 180 tail -f /dev/null; date -u; ao status --json | jq … .checks[] | select(.pr==2019)` — a turn spent on every pass, the card reading *working* while nothing of its own was running, and a host note (*your lane gained 1 entry since you declared out of work: TD-828*) unread behind it. Paul: *make sure our team members know that we will wake them up if they are waiting for work, so that they do not end up running loops (and wasting tokens).*
- What is written covers mail, and the manager's round, only. Every preset says *mail it, then end the turn* and that a loop on `ao wait` or `ao inbox` is never how it waits (§4.10); the grinder and designer presets alone add that a turn ended on a *background* shell wait is said with `ao doing`. Only the manager's `ao wait` round says *never a sleep* (`manager.md`, `skill.md`'s *instead of sleeping*); none says the other half: **a member never waits inside its own turn** — no foreground sleep, `tail -f /dev/null`, `timeout N …` or re-read of `ao status` in a loop — and none lists what wakes an idle member: mail and a steer's lapse (the doorbell, §4.10), the host's note that its lane gained work (§6 *Keeping a team running*, §4.9a), and its own background shell or subagent ending (the tool re-invokes it; §4.2 *Working on its own* draws it working meanwhile). A member that does not know the lane note will come keeps looking for work itself.
- So it is guidance, not a new mechanism: every wake the member needs already exists.

**Fix:** one PR, design first in the same diff:
1. §4.10 *Waiting on mail is ending the turn* gains a sentence: a session waiting on anything — mail, CI, a reader, work for its lane — ends its turn; what it waits on outside mail runs as one background command (`gh pr checks <n> --watch` with a `timeout`, run in the background), said first with `ao doing`; what wakes it is listed (the doorbell, the lane note, its background command's end); a foreground sleep or poll is named as the loop it is.
2. `src/shiftlead/skill.md`'s bullet and each preset's first paragraph say the same in one or two sentences — the grinder's and designer's existing *background shell wait* sentence is where it goes; the presets without it gain it, and `manager.md`'s *never a sleep*, written for its round, is widened to every wait. An out-of-work member is told it is rung when its lane gains an entry, so *out of work* is declared and the turn ended, never followed by watching.
3. Run the doc-bound tests (`grep -rln "skill.md\|briefs/" tests`) and update any that quote the changed text.

**Done when** the design, `ao --skill` and every role preset say a member never waits in its own turn and what wakes it; a live check is a week of member transcripts (`ao transcript`) with no foreground wait loop.

**Related:** TD-153 (the *nothing unread* line), TD-734, TD-761 (*Working on its own*).

---

## TD-857: Gemini's first job: the fact-check of a doc-only PR, read by a Gemini CLI session on the free tier instead of a Claude subagent, and its verdicts compared with Claude's

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-17 (Paul, in session `gemini-support`)
**Owner:** designer
**Kind:** design-first
**Status:** Open
**Blocked by:** TD-786
**Location:** `docs/cadence.md` §4.8 (the self-review: *doc-only PRs get a fact-check against the repo*, by the repo's `review-model`), `scripts/cadence_config.py` (`review-model`), `scripts/check_cadence.py` (the review-evidence row); design §4.3 *The second adapter: Gemini CLI*, §4.8 (roles and their profiles), §4.9b; `src/shiftlead/briefs/entry.md`, `src/shiftlead/team_skill.md` (where the fact-check is asked for); `~/.shiftlead/profiles.yml`

**Why:**
- Paul (2026-10-17): *We need to start using gemini cli in shiftlead so that we can make sure we are not being claude focused (see related TDs e.g. TD-112) … find a job that gemini can do for us, recognizing that since it is a free account it will be lesser models.* TD-112's adapter proves a Gemini session can be *run*; nothing yet gives one real work, so neutrality is tested only by the conformance walk.
- The doc-only fact-check fits a free-tier model: it only reads (a wrong verdict costs a re-read, never the tree), its input is small (one diff and the files it cites), its verdict is checkable claim by claim, so its quality can be measured against Claude's on the same PRs, and every doc PR needs one, so it takes steady load off the Claude weekly window. A TD grind is the wrong first job: long context, judgement and the whole cadence loop are where a lesser model and a free tier's rate limits hurt most.

**Fix:** design it first. What the round settles:
1. **How the reader runs**: a ShiftLead Gemini session (an `ao new` on a Gemini profile, mailed the PR, its verdict by `ao msg`), or headless `gemini -p` from the author's session with the diff on stdin. The first exercises the adapter and the org (the point of TD-112); the second needs only TD-785's launch and is cheaper per PR. The drafter's lean is the session, once TD-786 lands.
2. **The profile**: a Gemini profile of its own for the job (not `gemini-conformance`, which the walk owns), its account, and what the free tier's per-minute and per-day limits mean for a day of doc PRs; what happens when the quota refuses (the fact-check falls back to the `review-model`, and the evidence comment says so).
3. **The evidence**: the review-evidence comment names the reader's tool and model, and `check_cadence.py` accepts it. `docs/cadence.md` and `check_cadence.py` are dev-cadence's synced files, so a change there is dev-cadence's (an entry there, named here), or the comment's existing shape is kept and only its reader changes.
4. **The comparison**: for a trial window (the first N doc PRs, or a week), both readers check each PR; the verdicts are compared — a finding one caught and the other missed, a false finding — and the result decides whether Gemini takes the job alone, keeps it beside Claude, or hands it back. Where the tally is kept.
5. **Who it applies to**: every session's doc-only PRs, or first one team's (the grinders', whose doc PRs are most numerous).
6. The design's words, then the build entry, named in `Blocked by:`.

**Done when** the design says how a Gemini reader is run, on which profile, how its verdict is recorded and accepted, and how the trial is judged, and the build entry is filed.

**Related:** TD-112 (the adapter contract and its neutrality), TD-784, TD-785, TD-786 (the adapter's build), TD-035 (start hooks for an adapter without them).

---

## TD-900: The Repo page is a board by stage, the Org page is Sessions, the Queue numbers Up next per repo and marks what is live

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-18 (Paul, in an interactive session with the anchor)
**Owner:** designer
**Kind:** design-first
**Status:** Designed (2026-10-18, Paul with the anchor session, in chat; a Sonnet and an Opus design review adopted the same day, design-history §4.5; the render Paul reviewed is `docs/mockups/reviews/2026-10-18-repo-stage-board.png`, drawn before the review's rules): §4.5 screen 1 (*Sessions*), screen 11 (*the board*: its columns, For you, rows, numbers and moves, Review, Merged with the live divider, its bounds), screen 12 (*Up next* per repo, the live mark, *any open row*); §4.4 *The Queue* (`places`), *A move lands* (the Repo page's neighbours and scope), *Hold* (`why`); §4.5a *Repo page: Technical debt cards* (now the board), *Repo page, Merged: live divider*, *Queue page, Recently completed: live mark*, *Queue page, Up next: the number*, the grip row, the Hold row, *Queue card: what needs the person*; §4.7 `ao repo` and `ao td hold --why`; the glossary; design-history §4.4, §4.5, §4.5a. The builds, in order: TD-902 (the rename, first, since it sweeps the files the rest edit), TD-901 (numbers per repo), TD-903 (the board, after TD-901), TD-904 (the live reading, divider and mark, after TD-902), TD-905 (the row's controls on the Queue and Inbox rows, after TD-902), TD-907 (the session side of *done — words* and *back to design*, a held path, after TD-905).
**Blocked by:** TD-901, TD-902, TD-903, TD-904, TD-905, TD-907
**Location:** design §4.5 screens 1, 11, 12; §4.4 *The Queue*, *Hold*; §4.5a; §4.7; `docs/mockups/reviews/2026-10-18-repo-stage-board.png` and `-live.png`

**Why:** Paul, 2026-10-18: the Org page's name felt off — it is where the person sees what is running and starts interactions, so *Sessions*; and with the Queue built, the Repo page's Technical debt section was the Queue's cards drawn again in Queue order, its Open PRs and Recently completed lists beside them. *Redundant information isn't necessarily bad if it gives another perspective*: the Queue's axis is rank across repos, the Sessions page's is people by place, and nothing drew one repo **by stage** — the balance the page was designed to show (TD-176, §10). Two more asks fit the same page: the Queue's Up next numbers per repo (*ao-grind would have 1, 2, 3 and samscrape its own 1, 2, 3 … that is actually more truthful*), and *something to show the PR most recently promoted*, which on the board is a line across the Merged column, since one promote makes every PR merged before it live at once, and on the Queue a mark on each completed line. Then, asked what a person does on the board, and checked against §4.5a so nothing is said two ways: Stop was Hold on a claimed entry, Close was Done, Needs me was Hold with a reason; only Back to design was new, and every control is the ledger row's, defined once (*add a Back to design option on the Queue page*). Checked before designing: no open PR touches the Queue or the Repo page; TD-888's three builds merged 2026-10-18; TD-772 (the Queue's two-week trial, until 2026-10-30) reads lane behaviour and is not touched — the number's definition changes, the rank and the lanes' pick order do not.

**Fix:** the design as written; the six builds in `Blocked by:`, TD-902 first.

**Done when** the six builds are merged and the live Repo page is the board.

**Related:** TD-748, TD-722, TD-740, TD-770, TD-604, TD-176, TD-772, TD-888.

---

## TD-905: Build TD-900 (5): the ledger row's controls, once — Done… with words on every open row, Back to design…, Hold… with words — one macro in the Queue's row partial, imported by the Inbox's ledger row; `td_hold {why}` and `ao td hold --why`

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-18 (TD-900's design, Paul with the anchor)
**Owner:** grinder
**Kind:** live-check #2162
**Waits:** event — the person's next **Done…**, **Back to design…** or **Hold…** with words on the live copy (its decided line on `docs/user_attention.md`, or `held.why` on a `queue` reading), and the next Inbox ledger row
**Status:** Built in #2160 (slice 1: a hold's words, `ao td hold --why`, the drop notice `td_hold {tell}`) and #2162 (slice 2: the road `ledger_decide {road, words}`, the page's refusals, the one macro on Queue card heads and rows and the Inbox's ledger row, *held (person) — <why>*, the help), 2026-10-19, grinder-ao-1. The scratch-home check (PR #2162's **UI check**) read the buttons, a hold with and without words, and the refusals; a Done… press could not land its line there (the board write opens a GitHub PR). Read once #2162 is live (`ao promote status`): a headless GET of `/queue` draws **Done…**, **Back to design…** and **Hold…** on the card heads by the rules, and a held entry's words where one has them; the next decided line whose words begin *done —* or *back to design —* on `docs/user_attention.md` is the press landing (no press of the live copy: wait for the person's). **Read 2026-10-19 01:20 MDT (grinder-ao-2, live `c6bd5ee`, #2162 live):** a headless GET of `/queue` (200) draws **Done…** 222 times, **Back to design…** 170 and **Hold…** 202, by row state as §4.5 screen 12 and §4.5a *Repo page: Hold / Release* say — a *yours to do* row Hold… alone, a *your decision* row Done… and Hold…, the id-blocked *after TD-n* rows Done… and Back to design… with no Hold, *done* rows none, *ready*, *waits*, *stalled* and *held by grinder-ao-1* rows all three. No live row carries a hold's words (no *held (person) — <why>* outside the buttons' titles), and `/inbox` draws no ledger row today (board 22, notes 231, states 8, trail 1), so its macro is unread; nothing was pressed. What is left is the person's: a press landing its line, and a hold's words on the record and the row. Follow-up #2167 (2026-10-19, grinder-ao-1, branch `td905-open-blocker`): the techlead's nit on #2162 — the home's Back to design on a *blocked* row asks that a blocker is still open; a held path (src/sessionorc). The techlead's second nit — whether Done… / Back to design… may send an empty box (today plain *done* / *back to design*) — is left to TD-907's session side.
**Blocked by:** TD-902
**Location:** `src/shiftlead/ui/templates/queue_row.html` (the one macro) and the Inbox's ledger-row renderer that imports it (`ledger_for_you.html`), `src/shiftlead/ui/static/app.js` (the words box; the Reply road's fixed words beside *done* and *go ahead*; the press's order: tell, clear the hold, write the line), `src/sessionorc/agent_inbox.py` (`rpc_board_reply`), `src/sessionorc/agent_ids.py` (`rpc_td_hold`: `why`, and `tell` — the drop notice of §4.4 *Hold*, no CLI form), the `queue` and `repos` readings (`held.why`), `src/shiftlead/cli.py` (`cmd_td_hold`, `--why`), `src/shiftlead/ui/help.py` (the paragraphs for *Queue card: what needs the person* and *Repo page: Hold / Release on an entry*); `tests/test_ui_queue.py`, `tests/test_ui_board.py`, `tests/test_settle.py`, `tests/test_cli.py`, `tests/test_help.py`

**Why:** TD-900: design §4.5 screen 12 *any open row* (the rules), §4.5a *Queue card: what needs the person* and *Repo page: Hold / Release on an entry*, §4.4 *Hold* (`why`), §4.7 `ao td hold --why`. Paul, 2026-10-18: *add a Back to design option on the Queue page*; and the controls must not say the same thing two ways — Stop was Hold on a claimed entry, Close was Done, Needs me was Hold with a reason, so only Back to design is new, and every one is defined once.

**Fix:** (1) **Done…** on every open ledger row that is not *yours to do*, the words box, the road's words *done — <words>*; not drawn on a design entry with open builds; (2) **Back to design…** on a *pickable*, *live check* or id-blocked row, the same box, the words *back to design — <words>*; (3) both: the home tells the entry's unattended holders and its PR's reader (the `td_hold` note path, no hold written), a person's hold is cleared, then the line is written; refused with the reason where the repo has no servicing team, Back to design where no stage's lane takes `design-first`; the row reads *waiting on them*; (4) **Hold…** with an optional line, `td_hold {why}`, `held: {at, by, why}` on the record, carried by the readings, drawn *held (person) — <why>* wherever the mark is, the state word unchanged, a `decision (paul)` row keeping *held until <words>*, new words replacing old, `ao td hold --why`; (5) nothing page-specific: the Queue card and the Inbox row draw the macro here, the board draws it in TD-903 (its test that the rows are one partial). The session side — reading *done — <words>* and *back to design — <words>* from a decided line — is TD-907's. Write the help paragraphs.

**Done when** the live Queue's card rows and the Inbox's ledger rows show Done…, Back to design… and Hold…, a press tells the holder and lands the decided line, a hold's words are on the record and the row, and a test per rule above.

**Related:** TD-900, TD-903, TD-907, TD-770, TD-731, TD-707.

---

## TD-907: Build TD-900 (6): the session side of *done — <words>* and *back to design — <words>* — the lane that takes the decided line archives, or moves the entry back to design and its design's `Blocked by:` (a held path)

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-18 (TD-900's design round 2, Paul with the anchor)
**Owner:** grinder
**Kind:** build
**Status:** Open
**Blocked by:** TD-905
**Location:** the brief of the lane that takes a `board:<key>` work order (§4.4 *Board write-back*; `src/shiftlead/briefs/**`, the stage briefs under `src/shiftlead/flows/*/`, `src/shiftlead/skill.md` — a held path, so the PR goes to the techlead by `ao msg --kind ask --pr`); the field edit is the session's, by hand in the ledger as today's *go ahead* is (`scripts/ledger.py` is dev-cadence's synced file: if a script is wanted, that is a `dev-cadence#TD-n` named in `Blocked by:`); `tests/test_board.py`, the brief tests

**Why:** TD-900: design §4.5 screen 12 *any open row* — the road's two new fixed words, which a session must read as it reads *go ahead* and *done*.

**Fix:** *done — <words>*: archive the entry with *Resolved: closed by the person — <words>*, its PR named if one is open (left open, the holder already told). *back to design — <words>*: `Kind: design-first`, `Owner: designer`, a Status line with the words and the date, the id taken out of its design's `Blocked by:` with a line on that design saying why; the build's open PR stays open and is named in the Status line. Both land by the board's road as one PR.

**Done when** a Done… and a Back to design… press on the live Queue each land their ledger edit by PR within the lane's next pick, with a test per word.

**Related:** TD-900, TD-905, TD-693 (a design entry's builds).

---

## TD-909: The Queue card — three wants (Decide, Do, Read), three verbs (Answer, Start session on the card's team, ⋯), a Waiting group, items that lead with one sentence

**Priority:** High
**Type:** feature
**Added:** 2026-10-19 (Paul, in an interactive session, over an afternoon of rounds on two review pages)
**Owner:** designer
**Kind:** design-first
**Status:** Designed (2026-10-19, the designer): §4.4 *Waiting* (a card-level `waits`, `wait` from a leaf, `would_be`, unnumbered and unmoved), *The card's status* (*held (person)* no need, a word of its own), *A move lands*, *One owner* (`group`, `start`), *Hold* (a derived claim is not refused); §4.5 screen 12 *Waiting*, *A card* (its own box, its edge, the tree), *Three wants* (Decide, Do, Read), *An item's shape* (a `card` mode per renderer), *Three verbs* (Answer, Start session widened to `{repo, id, card}`, ⋯), no dates of the person's on a card, the kind pick; screen 11's rows; §4.5a six rows amended and five new; §4.10 *An item leads with one sentence* (`render.one_sentence`, the answers' ` — ` split, the warning); glossary *Waiting*, *Decide / Do / Read*. Built by TD-911–TD-918; dev-cadence#TD-121 (the `Ask:` line, the split in cadence §3.5 and ledgerboard) and dev-cadence#TD-122 (the rule in cadence §3.3 and its stage briefs, the cadence check's warning, after TD-772). Was: Agreed (2026-10-19) — [ADR 2026-10-19](decisions/2026-10-19-queue-card.md), drawn from the live ledger ([the page](mockups/reviews/2026-10-19-queue-redesign.html), [its shot](mockups/reviews/2026-10-19-queue-redesign.png)); the review rounds converged the same day (six rounds, Sonnet and Fable alternating, round 6 READY); the designer's round writes it into §4.4 *The Queue: cards, and the rank that orders them*, §4.5 screen 12, §4.5a and §4.10 and names the builds (ADR §8). Amends TD-748's ADR, which stands for what this does not touch. **Paul lifted the hold 2026-10-19 19:10 MDT** (in an interactive session): the design round is next, the designer's.
**Blocked by:** TD-918, TD-911, TD-912, TD-913, TD-914, TD-915, TD-916, TD-917
**Location:** `docs/decisions/2026-10-19-queue-card.md`; the design text it rewrites: §4.4 *The card's status* and *Groups* (4.4-host-agent.md), §4.5 screen 12 *Groups*, *A card*, *What is attached to a card*, *What needs the person* (4.5-ui.md), §4.5a the Queue rows; `src/shiftlead/ui/templates/queue_part.html`, `queue_card.html`, `queue_row.html`, `src/shiftlead/ui/queue.py`; dev-cadence for the writing rule (ADR §6)

**Why:** Measured on 2026-10-19 with the live ledger: 197 cards Up next, 82 amber, 11 saying only *waiting*, the tallest 3,212 px. Paul: *we have many ways that the user's attention is needed and multiple possible replies — we need to figure out how to simplify*; *lots of words all over the place, so I am relegated to reading everything in order*; *the description is written like someone took poor notes then handed them to me*.

**Fix:** The ADR's §1–§6: a Waiting group between In progress and Up next (unnumbered, keeps its place, the date or *event* in the number column); Decide and Do in the header and amber, Read folded with its count; Answer, Start session once per card on its repo's team with the card as context, and ⋯ for the team's controls; no Snooze, Put on the board or Due on a card; each card its own box, the tree's rules drawn, mentions deduplicated; the writing rule (one sentence, consequences, context) in dev-cadence with a backfill, enforced by the home. The design round names the build entries from ADR §8; the dev-cadence entry for the writing rule is filed when the design names it.

**Done when** the design says what the ADR decided, with a build entry per slice of ADR §8, and `Blocked by:` names them.

**Related:** TD-748 (the Queue, designed), TD-772 (the trial's read-back, which counts the Waiting group as a change to what the person sees), TD-900 (the Repo page's board, whose card is the Queue's).

---

## TD-916: Build TD-909 (7): `ao msg` warns on a question to the person that does not lead with one sentence, and the briefs say the rule and `--about`

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-19 (TD-909's design, the designer)
**Owner:** grinder
**Kind:** build
**Status:** Open — waits for TD-772's read-back, since the warning and the briefs change what the trial's readings measure (ADR 2026-10-19 §8)
**Blocked by:** TD-772, TD-913
**Location:** `src/shiftlead/cli.py` (the warning beside the `FIRST_PARA_WORDS` one), `docs/briefs/` (a held path), `src/shiftlead/briefs/*.md` (the presets' message-shape line)

**Why:** TD-909: design §4.10 *An item leads with one sentence* (*The home warns, never refuses*; *A question to the person about an entry names it*).

**Fix:** (1) `ao msg` to the person, `ask` or `steer`, whose first paragraph fails `render.one_sentence` prints one line, *the person reads one sentence first: this paragraph is not one*, and sends; home-authored rows and `--source` replies exempt. (2) The presets and `docs/briefs/`: an `ask` or `steer` to the person leads with one sentence, then what each answer leads to, then the context; answers written `<label> (default) — <consequence>`; `--about` set when the claim is not the subject. Tests: the warning and its exemptions; the briefs' line held by the brief tests.

**Done when** `ao msg` warns as §4.10 says and the briefs carry the rule.

---

## TD-917: Build TD-909 (8): the backfill — an `Ask:` line and each answer's consequence on every open entry that waits on the person

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-19 (TD-909's design, the designer)
**Owner:** grinder
**Kind:** build
**Status:** Open — waits for TD-772's read-back, since it rewrites the entries the trial's page shows (ADR 2026-10-19 §8), and for dev-cadence#TD-121 (the `Ask:` line and the answers' split in cadence §2, §3.5 and ledgerboard)
**Blocked by:** TD-772, dev-cadence#TD-121
**Location:** `docs/technical_debt.md` (on 2026-10-19 about 17 open entries carry `Owner: paul` or `decision (paul)`, none an `Answers:`)

**Why:** TD-909: design §4.10 *An item leads with one sentence* (*with a backfill*).

**Fix:** For every open entry with `Owner: paul`, `decision (paul)` or `Answers:`: an `**Ask:**` line in its body beside Why and Fix — one sentence a cold reader can decide or start a session from — and its answers in `<label> (default) — <consequence>` form where it has some. One PR per few entries, read by the lead; never a header field.

**Done when** no open entry that waits on the person lacks an `Ask:` line.

---

## TD-934: A single-owner flow — one session designs and builds in serial, the review stays a fresh session — built as an opt-in beside `td`

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-21 (Paul, in a dev-cadence session)
**Owner:** paul
**Kind:** design-first
**Status:** Open — nothing designed yet. Paul, 2026-10-21: build the flow rather than gate it on a measurement first. The person picks which flow a team runs, and a built flow gives more reliable numbers than hand-run trials. It is dropped only if it proves broken. Paul runs the design session, so no unattended designer picks it up.
**Blocked by:** decision (paul) — Paul runs the design session for the flow
**Location:** design §4.9c *Flows* (`docs/design/4.9c-flows.md`); `src/shiftlead/flows/` (a new flow beside `td/`, `build/`, `build-review/`); the measurement method is the 2026-10-08 prompt-cache ADR's (`docs/decisions/2026-10-08-prompt-cache.md`) and TD-460's weighted cost per merged PR

**Why:** Paul, 2026-10-21: the `td` flow's separate designer, grinder and techlead are probably the best for the result (fresh eyes at each stage catch issues), but the same model doing design → build → review in serial might get close to that quality for fewer tokens, mostly by keeping the cache warm. Asked for a "single-owner" (or similar) flow. What that session's discussion settled:
- **The saving is mostly not re-loading context, more than cache hits.** Each seat starts cold: brief, CLAUDE.md, the entry, the code it touches, plus the designer's reasoning reconstructed from a written handoff. A single owner has all of it loaded already. Stage handoffs in `td` also often outlast the cache lifetime (one hour on a subscription), so the cache is cold anyway; serial stages run back to back keep it warm.
- **`/compact` between stages works against the cache.** The prompt-cache ADR lists `/compact` as breaking the prefix (it rebuilds the conversation layer, and compaction itself gets the five-minute lifetime). Do not compact between stages. Compact only as a context-size escape, e.g. after a long build. Other CLIs have the same escape (Codex `/compact`, Gemini CLI `/compress`), so the flow needs nothing CLI-specific.
- **Design → build in one head loses little.** It removes a lossy handoff. What it loses is a second look at the approach before code exists, the cheapest place to catch a wrong one.
- **Build → review in one head loses most.** Reviewing your own work is weak even after a compact: the summary carries the author's reasoning, so the review inherits its assumptions. Fresh review is cheap because it reads a diff, not the codebase, and cadence §4.8's independent cheaper-model review is a rule a flow must not drop.

**Fix:** Design and build the flow (working name `solo`) as an opt-in beside `td`. A team's `flows:` chooses it, and so does the person.
- **Stage 1** is one seat that designs, then builds, with no compact between. It is a grinder that can design.
- **An optional design check** applies to entries over a size or risk line: a fresh cheap model reads only the written design note before the build starts.
- **The review** is a fresh session reading the diff, unchanged from `td`.
- `td` stays the choice for large, risky or cross-cutting entries. The design says how an entry or a team picks its flow: a ledger field, a size heuristic, or the team's `flows:`.
- **Once it runs,** compare it with `td` using the prompt-cache ADR's method (main-conversation transcripts, API weights). Measure weighted tokens per merged TD, review findings per PR, rework rounds, and reopened or follow-up TDs. Record the readings in design §4.9c or an ADR. Drop the flow only if it proves broken.

**Done when** the flow exists in `src/shiftlead/flows/`, design §4.9c describes it and when to use it, and a first reading against `td` is recorded.

---

## TD-938: The top bar's readings and tools past one developer — the build chip's audience, the host reading across nodes, + New's place under a director

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-21 (Paul, with the ao-paul session)
**Owner:** paul
**Kind:** design-first
**Status:** Open — nothing designed yet. Paul runs the design round (Sonnet and Fable alternating, as TD-931's), so no unattended designer picks it up.
**Blocked by:** decision (paul) — Paul runs the design round; when it has converged this line names the build entries
**Location:** design §4.5a *Sessions top bar: the bar's three groups*, *build chip*, *usage chip*, *+ New ▾*; §4.5 screen 1 (the cards' `host / repo` header and the *tool · account · model* row), screen 8 (Settings); §4.2 *unreachable* (the host chip goes hollow, the Sessions banner); §4.4a *Home and nodes*; §4.9 and §4.9b (the director); `src/shiftlead/ui/templates/base.html` (the `topbar` block: `#buildchip`, `#hostchip`, `#newmenu`)

**Why:** Paul, 2026-10-21, reading the bar TD-932 built, three questions the design answers for one developer on one host and no further:
- **The build chip is shiftlead's own.** It reads the live host agent's commit and the shiftlead repo's promote state (*main +n*, the hover from `git log live..main`), on every page for everyone. Only the person developing shiftlead on the home can act on it; a self-hoster who installs a release needs at most a version and an *update available* hint. *Does anyone but me (shiftlead dev) need that?*
- **The host reading across nodes.** The bar draws one `<host> ●`, the home's; §4.2 says an unreachable host hollows the dot and the Sessions page banners it. With nodes (§4.4a) there are several hosts to be unreachable, and a session's host is already on its card header (`host / repo`, `host / directory`). *Does kmaster become a scroll, or does that belong on the session cards?* The same question for the tool: §4.5 screen 1 row 4 already draws *tool · account · model* on every card, so a second adapter (Gemini CLI, phase 5) asks nothing of the bar — the design should say so.
- **+ New under a director.** Today New is the bar's one filled button: the person's way to start a loose session or a shell, a team's sessions starting from its card's **+**. Once a director is the person's top-level interaction (§4.9b), the person's first act is to talk to it and the director starts the teams. *Is the New button out of place now?* The director level is not yet designed, so the answer is a note and a direction, not a redesign of the bar twice.

The ao-paul session's assessment, for the round to test: the build chip moves to the Settings page beside the promote's **auto** switch (its *main +n* links to the Inbox's promote row today), drawn in the bar only when the home's shiftlead checkout carries a `promote:` block (the sign that this person is the developer); the host reading stays one name, the home's, its dot the sum of the nodes — hollow when any is unreachable, the hover listing them — and a session's host and tool stay on the card; New is demoted, not dropped: it stops being the filled button when the director's composer is, and moves to the Sessions page's header beside the team cards' **+**, with the change written into §10 until the director is designed.

**Fix:** A design round on §4.5a's bar rows and §4.5 screens 1 and 8, with a comparison page (one shape per answer, `docs/mockups/reviews/`) for Paul to pick from, then build entries: one for the build chip's audience, one for the host dot across nodes (with a line in §4.3 that the tool is the card's, never the bar's), and a §10 question for New's place that the director's design answers. The design round's history lines name the superseded ADR sentences (ADR 2026-09-25 on Settings and the promote's auto switch; §4.2's host chip sentence).

**Done when** the design says who sees the build chip and where, what the bar's host reading means with nodes and what stays on the card, and where New lives under a director, and the build entries are named here.

---

## TD-943: A team over an umbrella repo cannot see its sibling repos' PRs: `--pr`, `held:` and the PR readings are the one repo's

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-21 (the designer, from TD-623; guardians-devenv TD-028 step 4)
**Owner:** designer
**Kind:** design-first
**Waits:** event — Paul's answer on guardians-devenv's board line *Should the new guardians team land docs and demo changes as paired PRs*, which names this change as its third answer. On that answer the entry is designed; on *Paired PRs* (the default) or *Umbrella-only* it drops to Low and its wait becomes `event — a second umbrella team`, since paired PRs work and only a second constellation would show the cost
**Status:** Open. A team is on one repo (design §4.9 *Teams*): `ao progress done --pr <n>` is an integer read
with `gh` in the record's checkout, `held:` globs match that repo's paths, and the red-PR and sync-PR work
orders and the PR and Doing facets read that repo alone, so in an umbrella over sibling repos
(dev-cadence's `docs/nested-repos.txt`) a sibling's PR number is read as the umbrella's PR of that
number, a sibling path can never be held, and an open sibling PR is strandable with no page showing it.
`ao team --skill` (TD-623) tells such a team to land paired PRs meanwhile.
**Location:** design §4.9 *Teams*, §4.9c (`held:`), §4.8 (`ao progress`); `src/sessionorc/agent.py`
(`_pr_checks`), `src/sessionorc/held.py`, `src/sessionorc/workorders.py`

**Why:** an umbrella is dev-cadence's own shape, so ShiftLead meets it on every constellation; paired PRs
work, but the sibling half has no gate and no page.

**Fix:** design first: a repo-qualified PR reference (`owner/repo#n` or a URL) on `--pr` and the record;
whether `held:` and the PR readings follow the umbrella's hydrated siblings; and whether a sibling PR is
gated, and by whose `gate:`.

**Done when** the design says how a team over an umbrella names, reads and gates a sibling PR, and the
builds are in the ledger.

**Related:** TD-623, guardians-devenv TD-028.

---

## TD-946: The cadence procedure says the pair `ao pr wait N && scripts/check_cadence.py --pr N`, and the *no checks means conflicting* memory is retired (TD-940's third part)

**Priority:** Low
**Type:** debt
**Added:** 2026-10-21 (grinder-ao-1, split from TD-940 once its build merged in #2244)
**Owner:** dev-cadence
**Kind:** build
**Status:** Open
**Location:** `docs/procedures/cadence.md` (a SYNCED FILE, dev-cadence's: the change is made there and synced); `docs/claude-memory/no-checks-means-conflicting.md` and its `MEMORY.md` line

**Why:** TD-940 built `ao pr wait <n>` (#2241, #2244), which folds a PR's checks into one word and says *conflicting* where `gh pr checks` printed nothing. Its Fix had the cadence say the pair, so no session hand-rolls a CI poll, but the procedure is a dev-cadence SYNCED file a grinder here cannot edit.

**Fix:**
- `docs/procedures/cadence.md`: `ao pr wait N && scripts/check_cadence.py --pr N` is how a kmaster session waits for a PR's checks; a cloud session has no `ao` to call (ADR 2026-09-24), so its CI wait stays the GitHub MCP tools' and the cadence check runs from kmaster on its PR's number. Written in dev-cadence (where `ao` is shiftlead's and a repo without it keeps `gh pr checks --watch`) and synced here.
- Once synced: `docs/claude-memory/no-checks-means-conflicting.md` retired, its `MEMORY.md` line pointing at `ao pr wait` instead (the wait says *conflicting*); the *wait for CI with gh pr checks --watch* memory likewise.

**Done when** the synced procedure names the pair and neither memory tells a session to read `gh pr checks` itself.

## TD-959: A Gemini profile signed in with Google shows no usage chip: its quota is read only by the tool, with a token in its encrypted file

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-22 (grinder-ao-1, from TD-786)
**Owner:** grinder
**Kind:** build
**Status:** Open — split from TD-786 at its slice 3 (#2271).
**Blocked by:** decision (paul) — whether shiftlead may decrypt the tool's credential file and call Google with the person's token (ask m-0bc2ef3a6645; Paul asked whether the tool offers its own read, and the answer — the footer's *NN% used* for the model in use, `/stats model` — is asked again on its thread, m-14e859ac6fcd, with *Read the footer* as a third way)
**Location:** design §4.3 *The second adapter: Gemini CLI* (`usage`); `src/shiftlead/adapters/gemini/__init__.py`

**Why:** design §4.3 says a Google-login home's `usage` is the quota endpoint, so the card's chip and `limited` work as Claude Code's do. Gemini CLI keeps that home's OAuth token in `.gemini/gemini-credentials.json`, which is encrypted by the tool's file store (`GEMINI_FORCE_FILE_STORAGE`), not JSON; the quota (`retrieveUserQuota`, per-model `buckets` of `remainingFraction` and `resetTime`) is held only in the tool's memory (`lastRetrievedQuota`), never on disk. So the read decrypts the person's token, refreshes it with the tool's OAuth client, asks `loadCodeAssist` for the project, and calls Google — the person's credentials and the network, which an unattended grinder does not take on unasked.

**Fix:** on *Build it*: `usage_for(profile)` / `usage(profile)` as Claude Code's (reasons `metered`, `no_credentials`, `rate_limited`, `error`): an API-key home (`selectedType: gemini-api-key`) has no quota endpoint and reports None, as the design says (no chip); a Google-login home with no credential reports `no_credentials`; one with a credential decrypts the file as the tool does, refreshes, calls `loadCodeAssist` then `retrieveUserQuota`, and maps each bucket with a `modelId` to a window labelled by the model, `pct` = 100 − 100·`remainingFraction`, `resets` = the bucket's `resetTime` where it carries one (to confirm on the captured response). A response captured on a signed-in home is the parse test's fixture. On *Leave Gemini without a chip*: the design's `usage` line says None for every home, and this entry archives.

**Done when** a Google-login Gemini profile's card shows its chip, or the design says it has none.

**Related:** TD-786, TD-112.

---

## TD-964: The end of a session on Focus, second round: the ending banner and the ending card (what the session cost), Hand back in Take over's place, the side panel folded with a value on each summary, a Sent card

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-21 (Paul, in the td-156 session, from his screenshot of his own `dc-paul` closed from Focus — the shot is at `~/.shiftlead/attachments/ao-shiftlead-td-156/paste-20261021-184736.png`, after his live look closed TD-156)
**Owner:** paul
**Kind:** design-first
**Status:** **Hold lifted by Paul 2026-10-22: the build slices may be picked.** Designed 2026-10-21 with Paul (design §4.5 *The Focus screen's anatomy* items 2–4; §4.4 *Spend per seat*'s *One record's reading* (the seat pass's last read of an ended session's profile is TD-965's); §4.5a *Focus: Take over*, *Hand back*, *more ▾*, the ending banner's row, *Focus: ending card*, *Focus side panel: Sent*, the side panel's row, *Reports*; mockups `FocusEnded` and `FocusHeld`, shots `docs/mockups/reviews/2026-10-21-td964-*.png`). **Reviewed 2026-10-21**: seven rounds, Sonnet and Fable alternating, after Paul agreed the layout; READY at round 6 (Fable) and confirmed at round 7 (Sonnet); the ending card cut to the session's own story between rounds 4 and 5 at Paul's word, the seat pass's last read split out as TD-965. The build is sliced by the Fix's five parts.
**Location:** `src/shiftlead/ui/static/app.js` (the `#fexited` banner, the terminal's gone-pane lines, the composer bar's ended text, `AO.dropCard`), `src/shiftlead/ui/templates/focus.html` (the acts line's mode slot, the side cards), `src/shiftlead/ui/cards.py` (`mode_act`), the host agent's record view (`agent_serve`, the `list` view: `sent` and `sent_open` beside `unread` and `mail`), the `seats` RPC (`sessionorc/agent_spend.py` `rpc_seats`: a `record` pick), `/api/spend`, `docs/mockups/gen.py`

**Why:** at the end of an own session Focus still talks past the person. The banner guesses at a cause the record names (*This session's process has closed. Its pane is gone (killed, or the tmux server restarted)* under *closed by you · 18:42*), its grey text and a member's paragraph about where Restart lives crowd the buttons, and the pane below is a dead terminal with a retry line, when the moment is the one where the person decides what next and could read what the session cost. Elsewhere on the same screen: a closed record still draws Ready to close with its Close; the Session card's heading drops below its chevron because the summary's value squeezes it; Reports, Ready to close and Session start open with nothing on their summaries; after Take over, Hand back hides in more ▾ while the slot that held Take over goes empty; and what a session sent is nowhere on its page, though its Inbox is.

**Fix:** design first — done on this entry's branch; the build, in five slices: (1) the ending banner: the ending's words first, the cause's guess only where `ended` names none or the closer is not recorded, *read its transcript* dropped, the grey text and the member's note behind the **i** (the help text's wording goes in with `help.py`, never in a design PR), **Restart** on a supervised member as the card has it; no composer drawn on an ended record; no retry line written for a pane the page knows is gone. (2) the ending card: the `seats` reading's `record` pick (every kept day for one record, by model and by reference) and `/api/spend?record=`, `AO.dropCard`'s frame drawn with the record's own total and by entry, nothing else; in the pane's place on a gone pane, between banner and pane on a kept one; read when the page draws the ending and on a reload. (3) the folds: Reports, Inbox, Sent, Ready to close, Session and Told at start folded by default under a new remembered-fold key; each summary's value (Reports' counts, Inbox *n unread of m* in blue, Sent *n sent, m waiting* in amber, Ready to close ✓ / ✗ first failing check +n in amber, Session the model with tool · account · model on hover); the Session summary's heading `flex: none` and its value cut with an ellipsis; no Ready to close card on a `closed` record (an `exited` one keeps it). (4) Take over / Hand back in one slot, Hand back plain; *Switch to unattended* alone in more ▾. (5) the Sent card: the record view's `sent` and `sent_open`, bodies through `inbox` with `sent` as a person's read on unfold, an ask's answer or *waiting*.

**Done when** Paul, closing an own session from Focus, reads one line saying how it ended, the buttons, and what it cost, with no guessed cause; a member taken over shows Hand back where Take over was; the side panel opens folded with a value on each summary and the Session heading level with its chevron; a session that has sent mail shows it under Sent.

**Related:** TD-156 (the first round, archived), TD-923 (the disconnect card, whose frame the ending card reuses), TD-818 / TD-830–833 (Spend per seat, the figures), TD-490 (the ending's words), TD-096 (Take over / Hand back), TD-075 (`ao inbox --sent`), TD-029 (the reconnect contract), TD-266 (*forgotten by itself a day after the close*).

---

## TD-971: The home's own id reads are removed once every repo it serves has synced the counter's script; a checkout without it is refused, naming the sync

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-22 (the designer, from TD-966; Fable round 3: the home's own road serves no repo once each has synced)
**Owner:** grinder
**Kind:** build
**Waits:** event — every repo registered with the home has `scripts/ledger_next_id.py` on its default branch (its `docs/cadence-sync.lock` at dev-cadence 232f2ad or later), or is dev-cadence itself (`files/scripts/`). The check: for each root `ao repo --json` lists, `git -C <root> cat-file -e origin/<default>:scripts/ledger_next_id.py` (or `files/scripts/ledger_next_id.py` in dev-cadence) succeeds; presence suffices, since the script has taken `--floor` since its first commit (71a501c). Each repo's sync is its own sessions' work, as TD-969 is this repo's; this entry chases none of them, and TD-966 archives with TD-970, not with this
**Status:** Open
**Blocked by:** TD-970
**Location:** `src/sessionorc/agent_ids.py` (`_ids_prs`, `added_ids`, `files_jq`, `PR_READERS`, `FILES_CAP`, `_record`, the own-reads branch of `_ids_give`); `tests/test_td_next.py`; design §4.4 *A ledger entry's id is handed out by the home* (*A checkout without the script*), §4.7 `ao td next` (`reserved` on the home's own road)

**Why:** after the switch (TD-970), the home's own reads serve only a checkout from before the sync, where they can collide with an unpushed id the script gave (Sonnet round 2). They also keep two answer shapes alive. The ADR's end state is one counter, with `ids.json` handing out nothing of its own.

**Fix:** delete the home's own reads and `_record`. A checkout without the script is refused with *no scripts/ledger_next_id.py in <repo>: sync dev-cadence to 232f2ad or later*. `ids.json` stays as the floor and the record (`_record_given`). In the same PR, §4.4 drops *A checkout without the script* and its three reads, and from *Both roads* every own-road sentence: the PRs read a few at a time until 30 seconds in, the fetch that refuses when it does not finish, the *open PRs not read: <why>* line with the 200-PR list and the unread and `patch` rules, and *A fetch that fails refuses the call … main's ids are the floor*. It keeps the lock, the budget, the keying and the record as the one road's, keeps the script's `unread` line under *What it reads*, and rewords *as on the other road* in *The run* and *The record* to stand alone; §4.7 drops `reserved`'s own-road clause; the history line under §4.4 says the road is gone.

**Done when** `rpc_td_next` on a scratch checkout without the script refuses, naming the sync; the own-reads tests are gone; and every remaining `tests/test_td_next.py` test passes.

**Related:** TD-966, TD-970.

---

## TD-986: On a phone the Focus terminal cannot be scrolled reliably, and there is no Tab to accept a suggestion

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-23 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** designer
**Kind:** design-first
**Status:** Designed (2026-10-23, the designer) — §4.6 *Scrollback is tmux's*'s **A finger's drag scrolls it too** (a one-finger drag becomes the wheel's `{scroll, lines}` message, content following the finger; under 10 px a tap; no fling; `touch-action: pinch-zoom`; a touch does not select, and a long press's `contextmenu` is not the right-click paste), and §4.5a rows **Focus pane: soft-key row** (§4.5 *Phone layout*'s row built ahead of TD-003: below 720 px or on a coarse pointer, each key's bytes through `term.input`) and **Focus pane: a finger's drag**. The rest of TD-003's narrow mode stays TD-003's. Archives with its last build.
**Blocked by:** TD-989, TD-990
**Location:** `src/shiftlead/ui/static/app.js` (the terminal's `wheel` handler and `AO.wheelStep`, TD-174, which a touch never reaches; the bridge's `{scroll: up|down, lines: n}` message), `src/shiftlead/ui/templates/focus.html` (the terminal and the composer), `src/shiftlead/ui/static/app.css` (`@media (max-width: 720px)`); design §4.6 *Scrollback is tmux's, reached through tmux* (the wheel), §4.5 *Phone layout* (the soft-key row `Tab Esc ↑ ↓ ← → Enter 1–9`)

**Why:** Paul, 2026-10-23, on his phone over the tailnet (`paste-20261023-210421.png` in the Add entry draft), on the Focus page of an idle Claude Code session whose composer shows a ghost suggestion: *on the focus terminal there is no way to scroll the terminal reliably and no way to hit tab to accept an answer.*

The terminal keeps no local buffer: history is tmux's, reached by the scroll message the page sends on a `wheel` event (§4.6). A finger's drag sends no `wheel` event, so on a phone the history can be reached only by chance, if at all. Claude Code accepts its suggestion with Tab, and a phone's keyboard has no Tab key, so the suggestion cannot be accepted from the terminal. The harm is that a session cannot be read back or steered from the phone through its own terminal. Now that the phone reaches the home over Tailscale, §4.5's phone layout is no longer waiting for a route.

**Fix:** design, then build.
1. **Touch scroll** — designed in §4.6 *A finger's drag scrolls it too*, built by TD-989: a one-finger vertical drag is the wheel's `{scroll, lines}` message, batched per animation frame. A touch does not select (xterm.js 5.5 has none; the techlead took that default, m-35c331c546ff), and `touch-action: pinch-zoom` keeps the page from scrolling under the terminal.
2. **Tab** — §4.5a **Focus pane: soft-key row** (`Tab Esc ↑ ↓ ← → Enter 1–9`), built by TD-990 below 720 px and on a coarse pointer, each key's bytes through the terminal (invariant 6). The rest of TD-003's narrow mode stays TD-003's.

Verify it as a UI change (TD-290): Playwright with touch emulation at 390 px on a scratch home, then a look on the phone.

**Related:** TD-003 (the phone layout; the soft-key row is designed there), TD-174 (the wheel), TD-667 (typing returns the pane to the live screen), TD-985 (the Queue on a phone), TD-290.

## TD-990: The Focus soft-key row: `Tab Esc ↑ ↓ ← → Enter 1–9` under the terminal on a phone or a coarse pointer

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-23 (the designer, from TD-986)
**Owner:** grinder
**Kind:** live-check #2320
**Blocked by:** decision (paul) — his answer to the phone look, mail m-b8ca1cf74bde (*Works* / *Not right: <what>*)
**Status:** Built 2026-10-23 (#2320, grinder-ao-1): the row, `AO.softKey` and `AO.softShown`, the help bullet; every check of *Done when* a browser can make held on a scratch home (the PR's UI check) except Take over / Hand back, which a shell record cannot reach — read in the PR. What is left is the look on the phone (TD-290): once #2320 is live, on Paul's phone a Claude Code session's suggestion accepted by the row's Tab with the keyboard kept up, and a menu answered by an arrow or a digit — a look (design §4.10 *A look*), mailed by whoever holds this check. Read 2026-10-23 (grinder-ao-2): `ao promote status` reads #2320 live in b9cba44, and a GET of a live Focus page carries `#softkeys` with its sixteen `data-key` buttons; the look went to Paul as m-b8ca1cf74bde, with the PR's 390 px screenshot. *Works* archives this entry, and with it TD-986, whose builds are then all archived; *Not right* files what is wrong.
**Location:** `src/shiftlead/ui/templates/focus.html` (between `#term` and `#composer` in `.termwrap`), `src/shiftlead/ui/static/app.js` (beside `term.onData`; `readOnly`, set from the attach's first frame and flipped by Take over / Hand back; `fill()`, which sizes the terminal to the bar; the ending banner's arrival), `src/shiftlead/ui/static/app.css` (`@media (max-width: 720px), (pointer: coarse)`; `--softh`, read by `.composer.overlay`'s `bottom` and `max-height` and by `body.popped .termbox`'s `calc(100vh - 150px)`), `src/shiftlead/ui/help.py` and §4.5a *The help text*; design §4.5a **Focus pane: soft-key row**, §4.5 *Phone layout*

**Why:** TD-986: Claude Code accepts its suggestion with Tab and a phone's keyboard has none, so a menu or a suggestion cannot be answered from the phone through the terminal.

**Fix:** as the §4.5a row says: the row between the terminal and the composer, drawn by the media query, absent on an `exited` / `closed` record, and a state of the row's own, never derived from `readOnly` (which `openTerm()` resets until a frame sets it), shown and hidden by `.hidden` (its `!important` wins over the media query's `display`) on the signals the composer and `#termro` follow, at the flip itself — the template's seed (`s.unattended`), a `{read_only: true}` frame (`app.py` sends none for a writable attach), and the feed's mode flip (Take over shows it, Hand back hides it, without a reload) — and never by `openTerm()`, so a reconnect does not resize the terminal; each key's bytes through `term.input(bytes, true)`, the arrows by `term.modes.applicationCursorKeysMode`; `pointerdown` and `mousedown` defaults prevented (never `touchstart`'s, which would stop the row's sideways pan; the keys are `touch-action: pan-x`), `setPointerCapture` on `pointerdown`, so every pointer's `pointerup` reaches the key, which is sent only when `document.elementFromPoint` there is still that key, nothing on a `pointercancel`; a `.down` class from `pointerdown` to `pointerup`, `pointercancel` or `lostpointercapture` shows the press; a press sends only when `live() && !readOnly`, read at the press; the dim (`!live() || readOnly`) is cosmetic, toggled in `drawMark()` before its `markEl` guard, which `onopen`, `onclose`, the `read_only` frame and the mode flip now call. The template's seed hides the row on an `unattended` record and on one whose `s.state` is `exited` or `closed` (the ending banner's own test); the page hides it in the `fexited` branch when the record ends while open, and that branch's other side shows it again, unless the record is `unattended`, only while `!paneGone` (Resume reloads the page, so the seed shows it there): shown exactly when the record is neither ended nor unattended and the page has a terminal. Below 720 px the open composer (TD-500) comes under the row; above 720 px on a coarse pointer the row's height is `--softh` on `.termwrap`, set by a `ResizeObserver` on the row (so a show or hide re-runs `fill()`), added by `fill()` to the bar's, read by the overlaid composer as its `bottom` (`var(--softh, 0px)`) and in its `max-height` (`calc(100% - var(--softh, 0px))`) under `(pointer: coarse) and (min-width: 721px)` only (below 720 px the composer stays static with `max-height: none`; the fine-pointer rule is unchanged), so it stands above the row and the bar's strip under the row is empty while it is open, and taken off a popped-out window's terminal height; unset reads as 0 (`parseFloat(…) || 0` in `fill()`). The template seeds the row hidden on an `unattended` record; it hides when the record turns `exited` / `closed` with the page open. The bytes come from one pure function, `AO.softKey(name, appCursor)`, over the names `Tab`, `Esc`, `Up`, `Down`, `Left`, `Right`, `Enter`, `1`–`9`; each key is a `<button type="button" tabindex="-1" data-key="<name>">`, which the template test and the Playwright check address. The `ResizeObserver` that sets `--softh` is registered whether or not the composer is folded. The help text gains one bullet after **disconnect card**, in §4.5a's list and `help.py` together in this build (`tests/test_help.py` holds them equal): a `Help` entry keyed `soft-key-row`, named *soft-key row*, where *Focus pane*, listed in the Focus screen's `SCREENS` tuple after `disconnect-card` (the test holds `SCREENS` equal to the entries); the row's container carries `title="{{ help_title('soft-key-row') }}"`, the bullet's first sentence. The bullet: *- **soft-key row** (Focus pane) — Keys under the terminal — Tab, Esc, the arrows, Enter and 1–9 — that type into the session as a keyboard would. Press one on a phone or a tablet, which has no such keys: Tab accepts Claude Code's suggestion, an arrow or a digit picks from a menu. It moves no focus, so the phone's keyboard stays as it is, and it is not there while the terminal is read-only.*

**Done when** a unit test pins the key-to-bytes table (both cursor modes); a template test shows the row present on a live record and absent on an ended one; and a Playwright check at 390 px with touch emulation on a scratch home (`scripts/look_home.py`), on a shell session, taps the terminal (so xterm's textarea is focused), types `ls /us`, presses the row's Tab and reads `/usr/` completed in the pane, with xterm's textarea still `document.activeElement` after the press and the screenshot named in the PR; the same check presses Esc, an arrow and a digit in a scrolled-back pane and reads `#{pane_in_mode}`: the arrow keeps copy mode, the digit leaves it (the bridge, TD-667), and Esc leaves it (tmux's own cancel in the default emacs table; the check runs with it); a `pointerup` off the key or on another key sends nothing, and a sideways pan of the row (ending in `pointercancel`) sends nothing; a reconnect neither shows nor hides the row (an unattended one's stays hidden, an attended one's stays shown and dimmed while down), and Hand back then a reconnect keeps it hidden; on a live shell with the page open, `exit` in the pane hides the row with no reload (the `fexited` side), and Resume (a reload) shows it again; the node probe drives `render()` with a live, attended view and shows the row while `paneGone` is false and leaves it hidden while true; a press between Take over's flip and its re-attach sends nothing and the row is dimmed then; at 390 px the open composer is static with `max-height: none`; with the socket closed the row is dimmed and a press sends nothing; on an unattended session the row is hidden from the first paint, and Take over shows it without a reload. At 1024 px with a coarse pointer (`has_touch`, `(pointer: coarse)` emulated) the row is drawn, and Take over / Hand back leave no gap and no overlap under the terminal, folded and with the composer open, and the open composer's bounding rect ends at or above the row's top (`#composerbar` is outside `.termwrap`, so the wrap's foot is the row's); at 1440 px with a fine pointer the row is not drawn. A unit test shows the arrows' bytes follow `term.modes.applicationCursorKeysMode`. The rest of TD-003's narrow mode stays TD-003's. Then a look on the phone (TD-290).

**Related:** TD-986, TD-989, TD-003, TD-667 (Tab and Enter leave copy mode), TD-290.

---

## TD-995: A session cannot address another repo or team: names resolve only to sessions, so a request for another repo's ledger ends as a command printed for the person

**Priority:** Medium
**Type:** debt
**Added:** 2026-10-24 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** designer
**Kind:** design-first
**Blocked by:** TD-1000, TD-1001
**Status:** Designed 2026-10-24 (the designer, PR #2330): an org-wide `ask` edge to a question seat and its reply, `ao msg --team` / `--repo` resolved at the home from the records, and a session's `ao td add --repo X` for another repo as an `ask` carrying `entry`, not `handed` (design §4.10 *to a question seat*, *A team or a repo as the address*; §4.7). Steered to the techlead as m-33d1a7d42bdf. Built by TD-1000 and TD-1001 (the parser). Reviewed in nine rounds (Fable and Sonnet alternating; Sonnet READY at round 8, Fable's round 9 two follow-ons, adopted; design history §4.10). The steer lapsed to its default 2026-10-25.
**Location:** design §4.10 *The message gate* (its edges: upward, downward, sideways, *across teams, by project*), §4.1 (a bare name resolves to a session *here*, else *no session named <name> here*), §4.7 *Entries* (`ao td add` is a person's only), §4.9b (the techlead seat, filled on a question), §4.4a (a node forwards mail to the home: `MAILBOX` in `src/sessionorc/modes.py`); `src/sessionorc/mail.py` (the gate), `src/shiftlead/cli.py` (`msg`'s parser: one `words` run of positionals, `nargs="*"`)

**Why:** seen 2026-10-24 by contractmatch's interactive session `ao-contractmatch-cm-queue`, on the contractmatch container node, asked to send samscrape a ledger request. Every way it tried was closed:
1. `ao msg samscrape …` answered *no session named samscrape here*. An addressee is a session's id or name. Nothing addresses a repo, a team or its techlead seat. The node cannot read the org either (*the org lives on kmaster (home)…*), so it could not look up a session id to use.
2. `ao td add --repo samscrape …` was refused: it is the person's act alone (§4.7), and a session writes its entry on its own branch or files `ao finding`.
3. `ao finding` took only a ref in the session's own repo (the reporter's reading; the design states no such limit, §4.7, §4.8, so the design round checks it).
4. Claude Code's peer list (`ListAgents`) showed no other sessions, and it is not the channel anyway (§4.10).

So the session printed a command for the person to run on the home, which is the hop the mail layer exists to save. Even with a session id in hand, the gate would refuse the send today. Samscrape and contractmatch are separate projects until TD-723, and §4.10's cross-team edge admits only a session with the same `project` badge. So the request reaches samscrape only through the person. And the same gap stays inside one project: a session can reach another team's sessions only by knowing their ids, and a seat that is empty has no session to address.

A smaller problem came up in the same session. `ao msg samscrape --kind note … "text"`, with the options after the addressee, failed with argparse's *unrecognized arguments*. The error scrolled off above the echoed text, so the send read as sent. The parser takes the addressees and the text as one run of positionals, and an option in the middle splits that run (memory *ao msg: options before recipients*; the same failure on 2026-10-01).

**Fix:** designed (§4.10, §4.7; TD-1000 and TD-1001 build it). The reporter's directions, as the design took them:
1. **Address a repo or a team:** for example `ao msg --repo samscrape` (or `--team <team>`), delivered to that repo's or team's techlead seat through the home, filling the seat on the question as an `ask` fills it today. The design says whether this is a new edge of the gate and how it squares with *across teams, by project*: does it pass only within a project, or does a seat take questions from anywhere, since a seat acts on nothing and only answers or passes up? It also says what a repo with no techlead seat answers.
2. **An entry for another repo, asked by a session:** instead of the refusal, `ao td add --repo X` from a session lands as an `ask` to X's techlead seat marked *session-originated*, or as one press for the person to approve. Either way §4.7's *a person's only* changes, and the design says which.
3. **The parser:** `ao msg` accepts its options anywhere among the positionals (`parse_intermixed_args`, or a check that refuses with the corrected command on the last line). Either way an option after an addressee is no longer a silent-looking failure. This is a build on its own and can be split off when the design settles 1 and 2.

**Done when** the design says how a session reaches another repo's or team's techlead (or says it does not, and why), and its build is merged. A session on a node can then put a ledger request to another repo without the person running a command, and `ao msg <to> --kind note "…"` either sends or ends with a refusal naming the fix.

**Related:** TD-723 (samscrape and contractmatch under one project, which opens the project edge between them), TD-582 (the cross-team edge), TD-299 (the container nodes).

## TD-997: The Transcript draws a session's start context as its first entry, marked *told at start* — Paul's to keep or drop

**Priority:** Low
**Type:** feature
**Added:** 2026-10-24 (the designer, from TD-993 part 2)
**Owner:** designer
**Kind:** design-first
**Blocked by:** decision (paul) — his answer to the ask m-7f566ce663c2
**Status:** Open — waits on Paul's word whether the Transcript should show it.
**Location:** `src/shiftlead/ui/transcript.py`, the Claude Code adapter's transcript read (`src/shiftlead/adapters/claude_code/transcript.py`, which skips every line type it does not list, the `SessionStart` hook's attachment among them), the Gemini adapter's (TD-786); design §4.5 the Transcript, §4.3 `start_context`

**Why:** TD-993 part 2, the drafting session's suggestion: the start context is already in the conversation file, as the `SessionStart` hook's attachment, and the Transcript drops it; drawn as the conversation's first entry it would make the Transcript the whole record of what the session was given, for a closed session too. TD-993 designed the Session card's row (TD-996) and left this to Paul, since it is his to keep or drop.

**Fix:** design first, once Paul says yes: the entry's mark and style, set apart from the prompts; what an adapter whose start context reaches the conversation another way shows (§4.1 `mail.start_context_file_text`); whether the Session card's row then also links to it.

**Related:** TD-993, TD-996, TD-154 (the Transcript).

## TD-998: `ao` is not on PATH inside a container node: sessions and shells there reach it only as `/shiftlead/venv/bin/ao`

**Priority:** Low
**Type:** debt
**Added:** 2026-10-24 (Paul, through Add entry; drafted by ao-shiftlead-techlead-ao-1)
**Owner:** designer
**Kind:** design-first
**Blocked by:** TD-1004, TD-1005
**Status:** Designed 2026-10-24 (the designer): the generated Dockerfile links `/usr/local/bin/ao` to `/shiftlead/venv/bin/ao`, which every shell's `PATH` holds, a login shell's included; the venv's `bin` is not put on `PATH` (a Debian `/etc/profile` resets it for login shells, and its `python3` would shadow the repo's). `ao doctor`'s **nodes** line on a node says when `ao` is not this install's (design §4.4a, §4.7 *`ao doctor`*). Built by TD-1004 (the link) and TD-1005 (the doctor line). Reviewed in six rounds, Fable and Sonnet alternating, both READY at rounds 5 and 6 (design history §4.4a).
**Location:** `src/sessionorc/containers.py` (the agent's start script, `exec {INSIDE_VENV}/bin/shiftlead-agent serve`, run by `exec_cmd` with `SHIFTLEAD_HOME` and the node's env file and no `PATH`; the generated Dockerfile); design §4.4a (the node's `/shiftlead/venv`, filled with the home's wheel), §4.7 *`ao doctor`* (its checks; on a node they read the node); `src/shiftlead/skill.md` (*`ao` is on `PATH`*)

**Why:** seen 2026-10-24 on the contractmatch node (user `developer`). The container mounts shiftlead's virtualenv at `/shiftlead/venv`, but `/shiftlead/venv/bin` is not on PATH, so `ao` is *command not found* there. It is missing in an interactive session's shell and in the shell from Focus's **Open shell here**; only `/shiftlead/venv/bin/ao` works. The node's agent is started by its absolute path with the image's PATH, and the tmux sessions it creates inherit that PATH. TD-301 met the same gap for the hooks and worked around it: `hook_command()` in the Claude Code adapter finds `shiftlead-hook` beside the interpreter. Nothing does the same for `ao`. So a session or a person in the container has to know the install path to reach `ao` at all. The skill (*`ao` is on `PATH`*), the briefs and the docs all say `run ao …`, and those commands fail there as written. Mail, `ao progress` and `ao doing` are how a member reports, so a node member that cannot find `ao` goes silent to the org.

**Fix:** design first, in the reporter's direction:
1. **Put `/shiftlead/venv/bin` on PATH** for every shell in the container: either the generated image's `ENV PATH`, or the environment the node's agent starts with (`exec_cmd`'s `env`) so its tmux server and every session and shell it makes inherit it. The design names one in §4.4a. A `docker exec` shell a person opens by hand gets the image's PATH only, which favours the image.
2. **`ao doctor` on a node** reports *`ao` not on PATH* with the cure, when the host is a container node and `shutil.which("ao")` does not resolve to the venv's own.

**Done when** `ao` resolves on PATH in a node session, in an **Open shell here** shell and in a `docker exec` shell, after an `ao host rebuild`, and `ao doctor` on a node without it says so.

**Related:** TD-301 (the hooks off the node's PATH), TD-299 (the container nodes), TD-062 (the wheel the node is provisioned from).

---

## TD-999: The wait guard in Gemini CLI: its `BeforeTool` hook refuses an unattended session's foreground CI watch, as Claude Code's `PreToolUse` does

**Priority:** Low
**Type:** debt
**Added:** 2026-10-24 (grinder-ao-1, from TD-992)
**Owner:** designer
**Kind:** design-first
**Blocked by:** TD-1007
**Status:** Designed 2026-10-24 (the designer): the layer sets `tools.shell.backgroundCompletionBehavior: inject` and `experimental.modelSteering: true`, which in 0.65.0 is what makes a background command's end start an idle session's turn, and the hook refuses on `run_shell_command` not `is_background`, in words naming `is_background` (design §4.3 *A wait the guard refuses*, *The second adapter*). Steered to the techlead as m-d0741b96f424 (bound 12 h, lapses 2026-10-25 08:46Z). Built by TD-1007. Reviewed in eight rounds (Fable and Sonnet alternating; Sonnet READY at round 8; design history §4.3). Before: picked to build 2026-10-24 (grinder-ao-1) and handed back: in Gemini CLI a background shell's end does not wake the session, so the refusal's *run it in the background … its end wakes you* would be untrue there.
**Location:** `src/shiftlead/adapters/gemini/hook.py` (`refused_command`, `main`; the kill guard is wired there at its `run_shell_command`); design §4.3 *A wait the guard refuses* (it names Claude Code's hook alone) and *The second adapter: Gemini CLI*

**Why:** TD-992 built the wait guard in Claude Code's hook only. Gemini CLI's hook already runs the kill guard on `run_shell_command`, so the same net is one call away there: `wait_guard.waits(command)` when the call's `is_background` is not true. It also needs the same `wait` / `refuse_wait` round trip to the host agent, whose `rpc_hook` already answers it.

**What the build found (2026-10-24, grinder-ao-1, read in the installed `@google/gemini-cli` bundle):** `run_shell_command`'s background form is `is_background` (confirmed). What happens when a background command settles is the tool's `tools.shell.backgroundCompletionBehavior` setting: `silent` (the default: *quietly exits in background*), `inject` (*automatically returns output to agent*, through the tool's injection service, kind `background_completion`) or `notify`. Shiftlead's Gemini layer (`src/shiftlead/adapters/gemini/`) sets none of it, so today a Gemini member that moved its watch to the background, as the refusal tells it to, is woken by nothing when the watch ends — the opposite of §4.10's premise. So the design has to say, before any wiring: whether the layer sets `inject` (and whether an injection wakes an idle session or waits for its next prompt, to read on a live walk), or whether the home's own wake (the doorbell, §4.10) covers it; and only then the refusal's words for Gemini.

**Fix (as filed, now waiting on that):** design first in the same PR: §4.3 says the Gemini hook refuses too, naming its block form (exit 2 with the reason on stderr, as the kill guard's). Then wire it in `gemini/hook.py`, with a test beside its kill guard's.

**Done when** (as filed; TD-1007's supersedes it) an unattended Gemini session's foreground `gh pr checks <n> --watch` is blocked with `wait_guard.REASON`, and one with `is_background` true, or on an interactive record, is not.

**Related:** TD-992, TD-991, TD-785 (the kill guard in Gemini CLI).

## TD-1000: A session asks another team's or repo's question seat — `ao msg --team` / `--repo`, the org-wide `ask` edge, and `ao td add --repo` for another repo

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-24 (the designer, from TD-995)
**Owner:** grinder
**Kind:** live-check #2342
**Waits:** event — an interactive contractmatch session's `ao msg --repo samscrape "…"`; read 2026-10-25 09:42Z (grinder-ao-1, #2342 live in 2734a3e): no contractmatch session has asked (`ao-contractmatch-cm-mcp` idle, `ao-contractmatch-cm-queue@contractmatch` closed), and samscrape's techlead seat `ao-samscrape-techlead-sam-1` is closed with `asks_waiting` 0, so nothing has asked it yet
**Status:** Built in four slices (grinder-ao-2): (1) the edge — `message_edge`'s `question seat`, the one-open-question count, the chain walks with `follow`'s `id@host` fix — #2339; (2) `ao msg --team` / `--repo` — #2340; (3) the ledger request from a session — #2341 (merged by the techlead); (4) `techlead.md` and `skill.md` — #2342. The live check, once #2342 is live (`ao promote status`): an interactive contractmatch session's `ao msg --repo samscrape "…"` reaches samscrape's techlead seat and fills it, and the seat's reply lands in the session's inbox — read the seat's record (`ao status -v`), the ask in its inbox and the reply in the asker's (`ao inbox --thread <id>` as the person), never pressed on the live home.
**Location:** design §4.10 *An entry handed to a seat* and §4.8's person-only list (the session's call for another repo); `src/sessionorc/mail.py` (`message_edge`, `message_gate`: the kind, the `pr`/`cites`, the thread and the sender's open asks join the call), `src/sessionorc/agent_mail.py` (the `msg` RPC: the gate per addressee after `follow`, the `team`/`repo` address), `src/sessionorc/agent_inbox.py` (`rpc_entry_add`: `person_only` gives way to *a session, for another repo*), `src/shiftlead/cli.py` (`msg`'s `--team` / `--repo`; `td add` from a session, `_td_repo`, `_org_here`; `resolve`'s refusal from `msg`), `src/shiftlead/briefs/techlead.md` (the entry section and who it takes questions from), `src/shiftlead/skill.md` (the mail paragraph and its edge list); design §4.10 *to a question seat*, *A team or a repo as the address*; §4.7 *Mail*, *Entries*; §4.9b *The seat*; §4.1; §9 invariant 9

**Why:** TD-995: on 2026-10-24 contractmatch's session on the contractmatch node, asked to send samscrape a ledger request, found every way closed. `ao msg samscrape` resolved no session. The node could not read the org for an id. The gate would refuse another project anyway. `ao td add --repo` is a person's only. So it printed a command for the person to run.

**Fix:**
- **The edge.** `message_edge` gains `question seat`, tried after every existing edge:
  - The target's `seat` has `trigger: asks`, and the message is an `ask` carrying neither `pr` nor `cites`.
  - The sender has no open `ask` (no `closed_reason`) along this edge to the same seat, the sender's records along its `superseded_by` chain counted as one. The count is read in the target record's inbox (an open `ask` whose `from_` is a record of the chain), since a fill moves the seat's mail to its new record. A second one is refused naming the first; a reply, a lapse or a close frees it.
  - Its reverse is a `reply` from a record whose own `seat` has `trigger: asks`, whose `reply_to` is an `ask` in the sender's own inbox (however that `ask` came). The target must be that ask's `from_`, or a record its `superseded_by` chain reaches, since `follow` rewrites the addressee before the gate runs.
  - Both chain walks (this one and the count above) re-address a node record's `superseded_by` with `_from_host` to the `id@host` key `_graph()` uses; `follow` today reads the raw id and misses a node's chain, and is fixed to do the same.
  - `message_gate` takes what it needs to read this, and its refusal names the new edge.
- **The address.** `ao msg --team <team>` / `--repo <repo>` (mutually exclusive, and refused beside addressees, the text the only word) sends `team` or `repo` in the RPC's params in place of `to`, and the kind defaults to `ask`. The home resolves it from `_graph()`'s records:
  - `--team` is the record of that `team` (team names are unique, `org.yml`'s `teams:` keys) whose `seat.trigger` is `asks`, which is not `superseded_by` and whose state is not `closed`. A live one wins over one on call.
  - `--repo` is every such record whose `Path(repo).name` is the name given, read from the record, no registry needed. One record, or refused naming the teams.
  - Registries are read only to word *no registered repo <repo>*: the home's `hosts.local_host().repos()` and each node's answer to the home's `repos` request over the mux (as `rpc_host_repos` does); a node that does not answer within its timeout is named as unread, never waited on past it.
  - The resolved id is the record's `id@host` where it has one. The refusals are §4.10's words.
  - The sender's own team or repo resolves the same way. An `ask` that passes an earlier edge (sideways, project) has no open-question limit; only an `ask` passing this edge alone is limited.
  - A team with two `asks` seats resolves to the one whose `seat.tags` is true (the techlead seat); two and none such: refused naming them.
- **The ledger request.** `rpc_entry_add` accepts a session caller when the repo it names is not the caller's own (own: the resolved seat record's `repo` equals the caller's record's `Session.repo` on the same host; a same-named repo on another host is another repo; a caller whose record has no `repo` counts every repo as another), resolving repo and seat as `--repo` does, from the records (`team` choosing, as `ao td add --team` does; a `team` with no seat record on that repo is refused naming the teams that have one). The session path is tried only for a caller `person_only` would refuse: the person's own shell (`as_person`, TD-801) keeps today's handed entry. It sends the `ask` from the session through `message_gate` (a helper shared with `rpc_msg`, so the open-question limit and `MAILBOX_DEPTH` hold) carrying `entry` and **not** `handed`, with **no bound** (as `agent_inbox.py`'s handed entry has none), so nothing makes the seat owe the person an outcome and the open `ask` keeps an exited seat refilled (`asks_waiting`) until it replies after the merge. For the caller's own repo it refuses as `person_only` does today, its words naming the branch and `ao finding`. A session's call carrying `draft` is refused in words.
  - `ao td add` from a session with no `--repo` is refused at the client in the same words, reading no registry.
  - `ao td add` from a session (`SHIFTLEAD_SESSION` set) sends `repo` as typed, and `team` where given, and skips `_td_repo`, `_org_here` and `teams.entry_teams`, which read what a node does not have.
- **`techlead.md`**:
  - Its entry section takes an `ask` carrying `entry` from a session too: another repo's session asking for an entry in this repo. The seat judges it, drafts the entry and lands it by PR, or replies why not. The seat replies once the PR is merged, naming it, or with why not; the open `ask` (no bound) is what holds it on call. What only the person can settle goes up with `ao msg --pass-up <id> --recommend "…"`, not the handed entry's `--thread`, which a session's request (not handed) is refused; a pass-up closes the seat's copy (`asked_person`) and the person's answer goes to the asker, so the seat's part ends there and the asker asks again if it still wants the entry.
  - Its paragraph on whom it takes questions from names a question from another team's or project's session as a question to answer, not an instruction.
  - Its sentence *except the entry the person hands you* widens to the entry a question asks for.
- **The hint.** `resolve`'s *no session named <name> here*, raised for `ao msg`, ends *— a team or a repo is addressed with `--team` or `--repo`*.
- **`skill.md`.** Its edge list gains the question seat. Its mail paragraph names `ao msg --team` / `--repo` for a question to another team or repo, and `ao td add --repo <X>` for another repo's ledger.

**Done when:**
- `message_gate` tests:
  - An `ask` from a session of project A to a techlead seat of project B passes.
  - A second `ask` from the same sender to that seat, the first open, is refused naming it; once the first lapses (or is replied to), a second passes; a resumed sender with its predecessor's ask open is refused; so is a second `--team` ask after the first filled the seat (a new record). A node sender resumed with its predecessor's ask open is refused too, and the seat's reply to that ask reaches the resumed node record (`id@host`).
  - A `reply` to a cross-project session from a record whose seat is not `asks` is refused, even with `reply_to` an `ask` in its inbox.
  - A second `ao td add --repo B` from the same session while its first entry request is open is refused naming the first.
  - The seat's `reply` to a cross-project `ask` that has lapsed still passes and lands on the asker's thread.
  - An `ask` there carrying `pr` or `cites` is refused, and a `note` and a `steer` there are refused.
  - The seat's `reply` with `reply_to` that `ask` passes, also after the asker was resumed (`superseded_by`). Its `reply` to a different entry, or to a session that never asked, is refused.
  - A seat whose trigger is not `asks` is refused an `ask` from another project.
  - Every existing edge's test still passes.
- `msg` RPC tests at the home:
  - `team=` reaches the seat record that is not superseded (on call, so the `ask` fills it).
  - `repo=` with one seat reaches it, a node's seat under `id@host` included; with two it is refused naming both teams.
  - An unknown team, a team never started, a team with no question seat and an unregistered repo are each refused in the design's words.
- `entry_add` tests:
  - From a session in repo A for repo B, an `ask` from the session to B's seat carrying `entry`, with `handed` false and no bound; the seat's `--reply-to` closes it, and while it is open the seat's `asks_waiting` counts it.
  - For repo A it is refused naming the branch and `ao finding`; a same-named repo whose seat is on another host is not A. With a `draft` it is refused.
  - From the person it is unchanged, the person's own shell (`as_person`) included: still a handed entry.
- CLI tests:
  - `ao msg --team t "q"` and `ao msg --repo r "q"` send an `ask`.
  - `ao msg x --team t "q"` is refused.
  - `ao msg --repo <own repo> "q"` from a team member reaches its own seat.
  - `ao msg nosuch "x"` ends with the `--team` / `--repo` hint.
  - `ao td add --repo r "w"` with `SHIFTLEAD_SESSION` set sends `repo: "r"` without reading `org.yml`.
- A live check on the home, once live: an interactive contractmatch session's `ao msg --repo samscrape "…"` reaches samscrape's techlead seat and fills it, and the seat's reply lands in the session's inbox.

**Related:** TD-995 (its design), TD-1001 (the parser), TD-582 (the project edge), TD-218 / TD-219 (Hand to the techlead), TD-723.

## TD-1004: The generated node Dockerfile links `/usr/local/bin/ao` to the venv's `ao`, so `ao` is on `PATH` in a container node

**Priority:** Low
**Type:** debt
**Added:** 2026-10-24 (the designer, from TD-998)
**Owner:** grinder
**Kind:** live-check #2333
**Waits:** event — contractmatch's next `ao host rebuild contractmatch` (a person's press at the home); read 2026-10-24 21:27Z (grinder-ao-1, #2333 live): container adf6ba2ae675 was created 2026-10-11 13:09Z, before #2333 merged (20:57Z), so its image holds no link yet
**Status:** Built 2026-10-24 (grinder-ao-2, #2333): `dockerfile_text` writes the guarded link after the tmux step and the machine layers, before `USER <image user>`; its path is `containers.PATH_AO`, its target `INSIDE_VENV`'s `bin/ao`, and `test_the_dockerfile_links_ao_onto_path_after_tmux_and_before_the_images_user` holds the line and its place. Left: the live check in *Done when*, once #2333 is live and contractmatch is rebuilt.
**Location:** `src/sessionorc/containers.py` (`dockerfile_text`); `tests/test_containers.py`; design §4.4a (the generated Dockerfile, *The link puts `ao` on every shell's `PATH`*)

**Why:** TD-998: on the contractmatch node, `ao` was *command not found* in every session and shell. The node's agent starts by its absolute path with the image's `PATH`, and nothing puts `/shiftlead/venv/bin` on it.

**Fix:**
- `dockerfile_text` adds, in its root step after tmux, `RUN [ -e /usr/local/bin/ao ] || [ -L /usr/local/bin/ao ] || { install -d -o root -g root -m 0755 /usr/local/bin && ln -s /shiftlead/venv/bin/ao /usr/local/bin/ao; }`. The target is built from `INSIDE_VENV`, never a literal. A base image's own `/usr/local/bin/ao` is kept, a dangling link included (`-L`), so the build never fails on it (TD-1005 reports it).
- Nothing else changes: the agent's start script, `exec_cmd`'s env and the image's `PATH` stay as they are.

**Done when:**
- A `dockerfile_text` test asserts the `RUN` line, with its `-e` and `-L` guards, after the tmux step and before `USER <image user>`.
- A live check, once live: after `ao host rebuild contractmatch`, `ao` resolves (`command -v ao`) in a node session, in an **Open shell here** shell, and in `docker exec -it <cid> bash -l`.

**Related:** TD-998 (its design), TD-1005, TD-301 (the hook command beside the interpreter).

## TD-1007: Gemini CLI's layer wakes a session at a background command's end, and its hook refuses an unattended foreground CI watch

**Priority:** Low
**Type:** debt
**Added:** 2026-10-24 (the designer, from TD-999)
**Owner:** grinder
**Kind:** live-check #2343
**Waits:** event — the person re-runs the Gemini layer's `sudo install` line, then an unattended Gemini session's next CI watch; read 2026-10-25 09:42Z (grinder-ao-1, #2343 live in 2734a3e): `ao doctor` reads *Gemini layer stale*, and no Gemini session runs on the home
**Status:** Built 2026-10-25 (grinder-ao-1, #2343): `LAYER_SETTINGS` holds `inject` and `modelSteering`; `gemini/hook.py`'s `waits_in_the_foreground` sends `wait: true` only under `SHIFTLEAD_GEMINI_WAKES=1`, which `launch` sets when `layer_wakes()` holds, and blocks with `wait_guard.GEMINI_REASON` on `refuse_wait`; the stale note names the missing wake only for a layer without the two settings. Left: the live check in *Done when*, once #2343 is live and the person has re-run the layer's `sudo install` line.
**Location:** `src/shiftlead/adapters/gemini/__init__.py` (`LAYER_SETTINGS`, `layer_wakes`, `launch`, the doctor note), `src/shiftlead/adapters/gemini/hook.py` (`WAKES_ENV`, `refused_command`, `main`), `src/shiftlead/wait_guard.py` (the reason's words per background form); `tests/test_gemini_adapter.py` (the hook, beside the kill guard's), `tests/test_gemini_setup.py` (the launch with the `home` fixture's temp `MACHINE_LAYER`, the stale note) and `tests/test_gemini_guards.py` (its note assertion); design §4.3 *A wait the guard refuses*, *The second adapter: Gemini CLI*

**Why:** TD-999: in Gemini CLI 0.65.0 a background command's end wakes nothing by default, so the refusal's *its end wakes you* would be untrue there. With `inject` the completion is queued, and an idle session takes it as a turn only with `experimental.modelSteering` on.

**Fix:**
- `LAYER_SETTINGS` gains `"tools": {"shell": {"backgroundCompletionBehavior": "inject"}}` and `"experimental": {"modelSteering": True}`. Its comment names why. The wanted copy changes, so `ao doctor` reads the installed layer as *stale* until the person re-runs the `sudo install` line.
- `wait_guard` keeps `REASON` (Claude Code's words, byte for byte, as its test pins them) and gains `GEMINI_REASON`, naming `is_background: true` (§4.3).
- `gemini/hook.py`: on `BeforeTool` of `run_shell_command`, when the kill guard does not refuse, `tool_input.get("is_background") is not True` (a string or a missing field is the foreground, as `claude_code/hook.py` reads `run_in_background`) and `wait_guard.waits(command)` holds, `main` sets `params["wait"] = True` on the translated `BeforeTool` event, as it sets `mail`. The event goes through `report()`'s existing 3-second call, inside the tool's 10-second `HOOK_TIMEOUT_MS`, with no longer wait. A reply with `refuse_wait: true` prints `GEMINI_REASON` on stderr and exits `BLOCK` before any other output. Gemini's `BeforeTool` has no subagent marker, so no main-thread test is read. No reply (the host agent down, or past the wait) lets the call run, as Claude Code's does. `report()` strips `wait` from the queued copy, beside `session` and `mail`, so the drained event is applied unanswered.
- The wait is asked only when the session was launched under a layer that holds both new settings, since Gemini CLI reads its settings once, at launch, and a reinstall reaches no running session. One helper reads a layer: `layer_wakes(path: Path | None = None) -> bool` in `__init__.py`, resolving `path or MACHINE_LAYER` at call time, false for a missing, unreadable or non-JSON layer or one without `tools.shell.backgroundCompletionBehavior: "inject"` and `experimental.modelSteering: true`. `launch` calls it after `machine_reading()` (a second read, as the doctor's; a layer replaced between the two is the one the tool reads at launch, so the later read is the truer) and, when it holds, adds `SHIFTLEAD_GEMINI_WAKES=1` to the session's env (the constant `WAKES_ENV` in `gemini/hook.py`, beside `START_CONTEXT_ENV`). The hook reads only that variable, never the file: `main` asks the wait only after `waits()` holds and `os.environ.get(WAKES_ENV) == "1"`; otherwise the watch runs (§4.3 *A wait the guard refuses*). The hook reads no record: the reply's `refuse_wait`, decided by the host agent from the record's `unattended`, is the gate.
- The doctor's system note for a stale layer (`__init__.py`, the `words` / `refused` text) stops saying *a Gemini session gets no hooks*, which is a refused layer's case, and says the installed layer is not this install's; only when `layer_wakes()` on the reading's path is false does it add (a second read of the file; a change between the two only rewords the note, whose key refreshes) that a background command's end wakes no Gemini session until it is reinstalled. The note's key carries that reading beside the digest and the state, so the wording refreshes when it changes. `wait_guard`'s docstring stops saying *on the main thread* of every hook: that is Claude Code's test alone.

**Done when:**
- Hook tests: an unattended record's foreground `timeout 1800 gh pr checks 12 --watch` is blocked with the Gemini words. So is one whose `is_background` is missing or the string `"true"`. One with `is_background: true`, one on an interactive record (no `refuse_wait`), and one with no reply all run. A command the kill guard refuses is refused for that alone, and the wait is not asked.
- A layer test: `layer_settings()` holds both new keys. The hook tests that block set `SHIFTLEAD_GEMINI_WAKES=1` in the hook's env; one without it (a session launched under a stale layer) lets the unattended foreground watch run and sends no `wait`. Launch tests, with the existing fixture's temp `MACHINE_LAYER`: a layer written from `layer_settings()` puts `SHIFTLEAD_GEMINI_WAKES=1` in the spec's env, and a stale copy without the two keys does not. `layer_wakes()` tests: missing, unreadable, non-JSON and keyless layers are false. Doctor tests: the stale note no longer says *gets no hooks*, and it names the missing wake only for a stale layer without the two settings, not for one stale for another reason that holds them.
- An unreachable host agent queues the event without `wait`.
- A live check, once live: with the layer reinstalled, an unattended Gemini session's `gh pr checks <n> --watch` with `is_background: true` ends its turn. The watch's end then starts a new turn (`BeforeAgent`, its prompt the steering wrapper, the record `working`) without a prompt typed. An `ao send` to a working Gemini session steers its turn.

**Related:** TD-999 (its design), TD-991 / TD-992 (the wait guard in Claude Code), TD-785 (the kill guard in Gemini CLI), TD-871 (the machine's layer).

## TD-1009: ShiftLead requires dev-cadence, and the person's briefs, start prompts and preferences live in their dev-cadence layer repo

**Priority:** Medium
**Type:** feature
**Added:** 2026-10-25 (Paul, in the TD-993 conversation; drafted by ao-shiftlead-prompts)
**Owner:** paul
**Kind:** decision
**Status:** Proposed — [ADR 2026-10-25](decisions/2026-10-25-shiftlead-requires-dev-cadence.md), with its dev-cadence companion (dev-cadence TD-129, *pinned, not synced*). The builds are filed once Paul decides.
**Blocked by:** decision (paul) — the ADR's question: require dev-cadence in every served repo, and keep the person's ShiftLead texts in a `shiftlead/` directory of their layer repo
**Location:** `docs/decisions/2026-10-25-shiftlead-requires-dev-cadence.md`; design §8 (*recommends dev-cadence and requires only a ledger*), §5 (*The layout slots*), §4.7 (`ao repo init`), §4.8 (brief supplements), §4.9b (TD-657's preference layers); `src/shiftlead/repoconfig.py` (`entry_text`, `layout`), `src/sessionorc/cadence.py`, `src/sessionorc/sync.py`

**Why:** Paul, 2026-10-25, after TD-993 made the start context visible: *as soon as users can see it they will want the ability to modify it*; then *we talked previously about letting someone use a different cadence mechanism (other than dev-cadence) but I wonder if that is needless complication, especially given that we are building personal prefs into dev-cadence now*. ShiftLead keeps a path for a repo without dev-cadence that no repo uses, and has no home of the person's own for its briefs and start prompts (`entry.md` and `work.md` cannot be changed at all), while dev-cadence's personal layer (its TD-126) already follows the person across repos and machines.

**Fix:** Paul decides the ADR. If decided: the design sections above change first, then one build entry each for the adopt-or-refuse in `ao repo add`, the removed fallbacks and `ao repo init`, the `shiftlead/` layer reader with the brief, entry and work additions, TD-657's preferences moved before TD-662 builds, and the Session card row's sources (with TD-993).

**Done when** the ADR's Status reads decided (or rejected) and, if decided, its build entries are filed.

**Related:** TD-993, TD-657, TD-662, TD-681, TD-588; dev-cadence TD-126, TD-128, TD-129; ADR 2026-10-12, ADR 2026-10-08.
