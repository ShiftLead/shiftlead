# ADR 2026-10-12: three repos — records holds the ledger and board formats once, dev-cadence is how a repo works, ShiftLead is how sessions are run

**Status:** proposed 2026-10-12 (Paul, in session `ao-dc-decouple`), Fable READY after four rounds (2026-10-12); Sonnet READY after three rounds; Fable's check of those changes adopted (2026-10-12), confirmation round under way; awaiting Paul's acceptance.
**Date:** 2026-10-12
**Supersedes:** the placement of the ledger and board formats in [ADR 2026-10-08](2026-10-08-agentorc-dev-cadence-split.md);
the rest of that ADR stands. Its Status line gains "superseded in part by ADR 2026-10-12 (the formats'
placement); the rest stands" (cadence §7.5's one edit), in build 3.
**Related:** design §5, §8; dev-cadence TD-093, TD-095, TD-099, TD-101, TD-102 (the tool-neutral work),
TD-100 (archived: the session adapter, and its plan's scope line, dev-cadence PR #235); dev-cadence's
[2026-09-26 tracker decision](https://github.com/ShiftLead/dev-cadence/blob/main/docs/plans/2026-09-26-tracker-integration-one-interface.md).

## Context

Both repos moved to the ShiftLead GitHub org on 2026-10-11. Paul, 2026-10-12: dev-cadence should apply
to any repo and any session — Claude Code, Codex, an on-prem model, a person — with no ShiftLead on the
machine; ShiftLead should recommend dev-cadence but not require it; and the two must not drift.

The 2026-10-08 ADR placed the ledger and board formats in dev-cadence and let ShiftLead keep second
readers, held equal by parity tests. That is where drift lives today (line counts at shiftlead
`0ff0a369`, dev-cadence `origin/main`):

| Format | dev-cadence | ShiftLead |
|---|---|---|
| Ledger | `files/scripts/ledger.py` (611 lines), which imports `nudge_user_attention` for the roster | `src/sessionorc/ledger.py` (698), its own `ROW_RE`-like table reader in `sessionorc/reports.py`, and its own `Answers:` grammar on ledger entries (TD-565) |
| Board, read | `parse_board()`, `item_key()`, `item_refs()`, `item_head()`, `detail_block()`, `closed_items()`, `KIND_RE`, `ARCHIVE_AT` in `files/scripts/nudge_user_attention.py` (1,809 lines in all) | `src/shiftlead/ui/inbox.py` runs that script's `--report --json` (preferring a dev-cadence clone's `files/` copy, TD-278) and adds its own `SUBHEAD_RE`/`CONTEXT_RE`/`REPLY_MARK_RE`; `sessionorc/workorders.py` loads the script to get `item_key()` |
| Board, edit | `files/scripts/board_edit.py` (289): `edit_line()` and the `{tool}: …` commit subject | `src/sessionorc/board.py` (685): its own `edit_line()`, `message()` and read regexes (`ANSWERS_RE`, `DECIDED_RE`, `CONTEXT_RE`, `HEAD_RE`, `SESSION_RE`) |
| Commit subjects of board edits | written by `board_edit.py`; read by `check_cadence.py` `BOARD_EDIT_MSG_RE` and `STAMP_LINE_RE` (the carve-out classes) | written by `board.py` `message()` |

cadence §7's parity table already marks ShiftLead's ledger reader "until it reads through this one", and
some rows "this repo's side only". §2.12 already says "What to *do* with a field — lanes, routing,
which session a new entry opens — is the orchestrator's, never the cadence's."

ShiftLead also leans on dev-cadence beyond the formats, each degrading silently when a file is absent:
the repo roster (`sessionorc/hosts.py`, `~/.config/dev-cadence/repos.txt`), the merge gate
(`sessionorc/cadence.py` runs `scripts/check_cadence.py`), convention notices
(`sessionorc/conventions.py`), worktree setup (`sessionorc/gitinfo.py`, `scripts/hydrate_worktree.sh`),
the SessionStart line (`adapters/claude_code`, `CADENCE_HOOK_LINE`), and built-in briefs that name this
repo's own layout (`briefs/grinder.md`: `pdm run test`; `team_skill.md` says so).

## Options

1. **Keep two repos and the parity pairs.** Drift is caught after the fact, by tests on one side.
   Rejected: it is the thing Paul named.
2. **Two repos; ShiftLead runs dev-cadence's scripts as its readers.** One implementation, but ShiftLead
   would depend on a 1,809-line script whose other 90% is the cadence's process (delivery, forge lines,
   sweeps), and the formats stay bundled with a process ShiftLead says is optional.
3. **Move the formats into ShiftLead.** Rejected for the 2026-10-08 ADR's reason: every repo that runs
   the cadence without ShiftLead would depend on the orchestrator.
4. **A third repo, `records`, holding the formats once; dev-cadence and ShiftLead both consume it.**
   Chosen.

## Decision

### The three layers

| Repo | Owns | Never owns |
|---|---|---|
| **records** (`ShiftLead/records`, module `ledgerboard.py`) | The ledger and board formats as text: a spec (`SPEC.md`), one stdlib Python module, and language-neutral conformance fixtures (a Markdown input and its expected JSON). Its API is listed below. | Anything that touches the outside: git, the machine roster, forges, trackers, delivery, sweeps, sessions. When to write, who may, and what a field is *for*. |
| **dev-cadence** | How a repo works, for any session or a person: cadence.md's rules, the seed templates, the git hooks, the gate (`check_cadence.py`), sweeps and their stamps' meaning, the session-start nudge and `--report`'s process (fetch, staleness, delivery, open PRs, forge lines), worktree and anchor rules, `sync.sh`, the machine roster, and the narrow session adapter (TD-100). | A parser of a records format. A call to `ao`. |
| **ShiftLead** | How many sessions are run: the host agent, session state, teams, lanes, claims, policies, the Inbox and every UI, what a field is for (`Owner`, `Kind`, lanes), its own roster, and the board write-back's fetch, commit, push and locking. | A parser of a records format. A requirement that dev-cadence be installed. |

**The rule that keeps them in sync: no second parser.** Every reader and writer of a ledger or board, in
any repo, calls `ledgerboard.py`. A regex that recognises a ledger or board *line shape* outside it is a
finding; diff walkers (`sessionorc/ledger.py`'s `git log -p` reader, `reports.py`, `check_cadence.py`'s
board-diff classes) use records' line predicates instead. A field's value beyond its first word — except
the `Answers:` grammar — is the consumer's to read (ShiftLead's `Kind: live-check #<n>` is ShiftLead's). A behaviour that
needs a new field, edit or line shape is a records change first. Prose (cadence.md, skills, briefs)
may name a field; it describes the format's shape by reference to `SPEC.md`, never by restating it.

### The records API

Pure functions over text; anything outside the text is passed in.

- **Ledger:** parse entries (heading, header block, `**Name:** value` fields, the free comment after a
  value's first word); the preamble's `Fields:` declaration and `--check`'s validation; the summary
  table's rows (`ROW_RE`); `Blocked by` parsing; derived **pickable** over the whole ledger, as both
  sides have it today: `pickable(ledger, archive, resolve)` → entries, blocked, flags, where
  `resolve(item) -> (state, why)`, state `open | archived | unresolved`, answers a cross-repo
  `<repo>#TD-NNN` and `why` goes into the flag (ShiftLead's `live` callable, its promote state, stays
  ShiftLead's, passed around the call) — dev-cadence passes a resolver over its roster and
  `origin/<default>`, ShiftLead one over its registry; the archive's shape; the `Answers:` value grammar
  wherever it appears; an imported entry's `**Tracker:**` field (`JIRA-123`, as the 2026-09-26
  decision names it), kept byte-for-byte by every edit.
- **Board:** parse items to a record — the fixtures' JSON is the API: `line, text, kind, due,
  due_error, answers, default, decided, waiting_on, replies, session, host, refs, detail`, with
  `item_head()` as a function; the today-relative fields (`overdue_days`, `due_tag`) are functions of
  `(item, today)`; `escalate` (dev-cadence's thresholds) stays nudge's. Also
  `item_refs()`, `detail_block()`, `closed_items()`, `KIND_RE`/`Kinds:`, `ARCHIVE_AT`; composing a new
  item, `item_line(text, due, session, host, context)` and `decided_line(…)`; the
  snooze/done/reply/decide edits (`edit_line()`); and one commit subject per write,
  `subject(tool, action, …)` for the four edits and `append`, with the parser `check_cadence.py` uses
  to classify it (its `board-edit` and `board-append` classes).
- **Line predicates for diff walkers:** `entry_id(line)`, `row_id(line)`, `is_item(line)`,
  `is_open_item(line)`, `is_stamp(line)`, `item_key(line)`.
- **Preamble lines:** the line shape `Name: value` and `Name: YYYY-MM-DD (…)` on a preamble is records';
  a line records does not know is kept byte-for-byte. The names `Swept:`/`Swept-deep:` and their
  thresholds stay dev-cadence's.
- **Version:** an optional `Records: <major>` preamble line, absent = 1. A reader that meets a newer
  major than it knows says so and reads nothing, rather than guessing. `item_key()`'s text for a given
  line is part of the format — ShiftLead persists `board:<sha256(item_key)[:8]>` in progress records
  (`sessionorc/workorders.py`) — so a change to it is a major.

### How records is consumed

- **One file, carried by the sync that already exists.** records publishes tagged releases. The file
  is a library (no shebang, a module docstring) and opens with two lines records writes into the
  release itself: `# ledgerboard v<x.y> sha256:<of the rest>` and `# SYNCED FILE — canonical copy:
  ShiftLead/records ledgerboard.py (vendored by dev-cadence as files/scripts/ledgerboard.py)`, so the
  release travels inside the file and no consumer's copy differs from it. dev-cadence's provenance
  test (`tests/test_sync_provenance.sh`) accepts that second form for a vendored file — the one place
  its `MARKER` is not the rule — so `SYNCED FILE` still opens it.
  dev-cadence vendors it as `files/scripts/ledgerboard.py`, a SYNC file like any other (its scripts
  import siblings by name), so the lock and `--verify` carry it with no format change.
- **ShiftLead carries two copies, held byte-equal.** As a dev-cadence consumer it has the synced
  `scripts/ledgerboard.py`; its wheel needs `src/sessionorc/ledgerboard.py` (container nodes are
  provisioned from the wheel). A ShiftLead test asserts the two are byte-equal whenever both exist, and
  that the header's hash matches the body. `src/sessionorc/ledgerboard.py` is excluded from ruff's
  format and lint in `pyproject.toml` (`scripts/` already is): it is read, never formatted, or the first
  `pdm run fmt` breaks both checks. A repo using ShiftLead without dev-cadence has only the wheel's.
- **The fixtures travel the same way, to the two repos that test the module.** dev-cadence's
  `vendor_records.sh` copies, from a records tag, `ledgerboard.py` to `files/scripts/` and the fixtures
  to `tests/records/` (beside a `MANIFEST` naming the tag and each file's sha256). ShiftLead's
  `vendor_records.sh` copies the fixtures and `src/sessionorc/ledgerboard.py` **only**:
  `scripts/ledgerboard.py` has one writer, `sync.sh`, as every SYNC file does. Fixtures are tooling, not
  SYNC: a consumer repo never receives them. Each repo's CI runs them against its copy
  (`tests/test_records_fixtures.sh`, `tests/test_records_fixtures.py`) and checks the module's header
  hash. No CI checks out another repo.
- **A new release reaches ShiftLead in one PR: the sync PR.** The sync brings the new
  `scripts/ledgerboard.py`; the same PR runs `vendor_records.sh <tag>` (the tag read from the synced
  header), which replaces the wheel copy and the fixtures, so the byte-equality test never merges a
  half-taken release and ShiftLead can never run ahead of dev-cadence's lock. A lagging ShiftLead is one
  that has not synced, never one with two versions.
- **`ledgerboard.py` is in no rule's opt-out set** in `sync.sh`: every consumer that has any of the
  scripts that import it has it.
- **dev-cadence's README rule changes:** "no version pinning beyond the lock" gains one exception — a
  vendored records release, pinned by its header.
- **Until a consumer's first sync after release 1.0**, its lock has no line for `ledgerboard.py`, so
  `--verify` cannot judge that file; the byte-equality test is ShiftLead's guard meanwhile. In
  dev-cadence itself, which has no lock of its own, CI checks the header's hash against the body.
- **A synced script and the module arrive together.** A consumer (samscrape, contractmatch) sees nothing
  until its next sync, which brings `ledgerboard.py` with the scripts that import it. build 2's
  `cadence-changes.md` entry says so: sync before running a newer `nudge_user_attention.py` by hand.

### What ShiftLead requires of a repo, and what it only uses

- **Requires:** a ledger in records format at `.shiftlead.yml`'s `ledger:` path (default
  `docs/technical_debt.md`). External trackers stay outside: per the 2026-09-26 decision, a tracker is
  mapped *into* the ledger by an importer.
- **Board:** optional, at `.shiftlead.yml`'s new `board:` path (default `docs/user_attention.md`).
  Without one, the person's channel is ShiftLead's own inbox. With one, the Inbox
  reads it **in-process through `ledgerboard.py`** and never runs `nudge_user_attention.py`; a repo with a
  board needs no dev-cadence. Boards are still read against origin (§4.5 screen 6, TD-221): ShiftLead
  reads each board twice itself — the checkout's file and `origin/<default>:<the board: path>` after
  its own fetch (git is ShiftLead's) — parses both through `ledgerboard.py`, and derives the origin note
  (unreached, behind, local, both) from the comparison, as it reads the write-back's tree. The
  Inbox's `ORIGIN_PHRASES` and `BOARD_FIELDS` go. Without dev-cadence, nothing needs to recognise a
  write-back's commit subject: the write-back merges its own PR. A ShiftLead session closes or edits a
  board line on its own work branch with a new verb, `ao board edit <done|snooze|reply> --line <n>
  --expect "<start>" …` (`--board` defaulting to `.shiftlead.yml`'s `board:`), which calls records'
  `edit_line()` and commits with `subject("shiftlead", …)` on the current branch, touching nothing else.
  `decide` is not offered: a `Decided:` is the person's answer, written only by the write-back (the
  `board_edit` RPC refuses every session, `agent_common.person_only`). `ao board edit` is a session's own
  edit on its own branch, not that RPC. Briefs name that verb in every repo, so a session never needs
  `scripts/board_edit.py`, which stays for sessions dev-cadence serves without ShiftLead. The person's
  presses keep going through `board.py`'s write-back.
- **Briefs and flows name no repo's layout.** Every repo-specific literal in `briefs/*.md`,
  `flows/**/*.md` (five: `td/build.md`, `td/design.md`, `td/review.md`, `build/build.md`, `build-review/build.md`) and
  `team_skill.md` becomes a variable, filled where `{lane}`, `{repo}` and the rest are filled today
  (`repoconfig.py`, `teams.py`): `{gate}`, `{board}`, `{ledger}` (existing), `{ledger_check}`, `{test}`,
  `{lint}`, `{design_dir}`, and `{cadence_rules}` ("read docs/cadence.md §1–§4" in a dev-cadence repo).
  A variable the repo leaves unset fills with a sentence naming the seam ("no gate: a person merges"),
  never with empty text; `{pr}` inside `{gate}` is filled after the variables. This repo's own
  specifics (`pdm run …`, `scripts/look_home.py`, `docs/design/`) move to its `.shiftlead.yml` and own
  brief. `team_skill.md`'s *A repo's brief* says the built-ins hold variables, not this repo's layout.
  A test fails on `docs/cadence.md`, `/cadence`, `scripts/`, `docs/technical_debt.md`,
  `docs/user_attention.md`, `docs/design/` or `pdm run` in those files outside a variable.
- **Uses when present, with a seam in `.shiftlead.yml` when not** (all new design, see *Builds*):
  - `gate:` a command that exits 0 for a mergeable PR (`{pr}` filled); ShiftLead judges a configured
    gate by its exit code alone. The default, when `scripts/check_cadence.py` exists, is that script
    run as today with `--json`, a known shape whose rows the review card keeps showing. With no gate,
    the review stage never merges on its own: the card says "no gate: a person merges", where today
    `sessionorc/cadence.py` returns `None` (no reading).
  - `commands:` `test` and `lint`, which fill `{test}` and `{lint}` in the built-in briefs; this repo's
    `pdm run …` moves to its own `.shiftlead.yml`.
  - `worktree_setup:` default `scripts/hydrate_worktree.sh` when present.
  - Convention notices (rule 12) and the SessionStart line run only in a dev-cadence repo; they are
    features of one, not requirements.
- **Its own roster** of repos under `~/.shiftlead/`, importing dev-cadence's `repos.txt` when it exists.
- **Says what is missing.** `ao doctor` gains repo rows, and the Repo page names each seam a repo leaves
  unset (no gate, no board, no worktree setup). Nothing degrades silently.

### What changes in the 2026-10-08 rule

It stands for everything but the formats: dev-cadence owns what a repo needs with no ShiftLead on the
machine; ShiftLead owns what needs a host agent, session state or a second session; a synced file never
calls `ao`; a behaviour only a ShiftLead session needs is an environment variable ShiftLead sets. What
changes: the formats are records', and "a second reader held equal by a parity test" is retired —
cadence §7's ledger and board rows become "both read through `ledgerboard.py`".

## Builds

Each is a ledger entry in the repo named, filed when this ADR is accepted; the design edits come first.

| # | Repo | What |
|---|---|---|
| 1 | records | Create the repo; `ledgerboard.py` moved from dev-cadence's `ledger.py` parsing, nudge's board readers and `board_edit.py`'s `edit_line()`/subject — **moved, not rewritten, except `pickable()`'s resolver**, which becomes a parameter; `SPEC.md` from the seed templates' format paragraphs and cadence §2/§3's format rules; fixtures; release v1.0 by a `release.sh` that writes the header and tags. records is a dev-cadence consumer (its own ledger, board and CI) that keeps `ledgerboard.py` as source and vendors nothing back. **Test bar:** dev-cadence's ledger, board, parity and check-cadence suites pass unchanged against the vendored module (run in build 2's branch before v1.0 is tagged), and records' fixtures are generated from them. Its subject parser also reads the three insert subjects ShiftLead writes today (`shiftlead: board …`, `shiftlead: answer …`, `shiftlead: board decide …`), for as long as a branch or PR may carry them. |
| 2 | dev-cadence | Vendor v1.0 as a SYNC file, and the provenance test's vendored form; `ledger.py`, `nudge_user_attention.py`, `board_edit.py`, `check_cadence.py` call it; the seeds and cadence.md point at `SPEC.md`; §7's rows; README's pinning exception; §3.4/§4.5: the edit is made through records' `edit_line()` — `board_edit.py`, or a session's own tool on its own branch (ShiftLead's `ao board edit`); a `cadence-changes.md` entry (sync before running a newer script by hand); `vendor_records.sh`, the fixtures test and the header-hash check; `scripts/ledgerboard.py` added to `sync.sh`'s `SYNC_FILES` and to no case of `optout_files()`; sync. |
| 3 | ShiftLead design | §5: `gate:`, `worktree_setup:`, `board:`, `commands:` read by the briefs, the roster; §4.7: `ao doctor`'s repo rows, `ao repo init` (an empty ledger); §4.5a: the Repo page's missing-seam lines and the Inbox reading in-process; §6: the review stage with no gate; §4.7 and §4.9a: `ao board edit` for a session's own branch, and *What a session does with a decided line* closing it with `ao board edit done`; §8: this ADR's rule. |
| 4 | ShiftLead | Vendor v1.0; `ledger.py`, `board.py`, `reports.py`, `workorders.py` and `ui/inbox.py` call it and drop their line-shape regexes; `board.py`'s `message()`, `item_line()` and `decided_line()` become records calls with `tool="shiftlead"`, its three insert subjects (`board`, `answer`, `board decide`) collapsing into `append`; `Registry` returns `(state, why)`; the Inbox reads checkout and origin itself and derives the origin note; the ruff exclusion; `vendor_records.sh`, the byte-equality and fixture tests. **Tests rewritten, each assertion listed in the entry:** `tests/test_board.py` (the `message()` subjects, its `DECIDED_RE` uses), `test_ui_inbox*.py`, `test_reports.py`, `test_workorders.py` and `test_ledger*.py` where they touch a dropped regex or subject. |
| 5 | ShiftLead | The seams of build 3, each its own entry: gate, commands into briefs, worktree_setup, roster import, doctor and Repo page rows, `ao repo init`, `board:`, `ao board edit`, and the briefs, flows and `team_skill.md` made free of any repo's layout with the test that holds them so. |

## Consequences

- A format change is three PRs in order: records (spec, code, fixtures, a release), then dev-cadence's
  vendor and sync, then ShiftLead's vendor. Slower than one repo; it is the price of one definition. A
  consumer may lag a release; it may not diverge from one.
- `ledgerboard.py` imports nothing of either repo; dev-cadence's `ledger.py` keeps its
  `nudge_user_attention` import only to build the resolver from the roster (`Roster.resolve` returns
  `(state, why)`, a change in build 2 as `Registry`'s is in build 4).
- External trackers (Jira, Asana) are never records': the importer that maps a tracker into the ledger
  is dev-cadence's (its TD-065, the 2026-09-26 decision), in its own repo if it ever needs a non-stdlib
  client; ShiftLead may run it on a schedule as it runs the gate. records owns only the `Tracker:` field's shape.
- dev-cadence's open tool-neutral entries (TD-093, TD-095, TD-099, TD-101, TD-102) proceed unchanged;
  records is tool-neutral already.

## Open questions

None left for the decision; the names (`records`, `ledgerboard.py`) are Paul's to change.

## Revisit triggers

- A third consumer that cannot vendor a Python file (then: a package, or a second implementation held by
  the fixtures).
- A format change that a pinned consumer cannot take within a release cycle.
- A repo wanting a ledger shape `Fields:` cannot express.
