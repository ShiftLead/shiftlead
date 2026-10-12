# ADR 2026-10-12: three repos — records holds the formats once, dev-cadence is how a repo works, ShiftLead is how sessions are run

**Status:** proposed 2026-10-12 (Paul, in session `ao-dc-decouple`), under review.
**Date:** 2026-10-12
**Supersedes:** the placement rule of [ADR 2026-10-08](2026-10-08-shiftlead-dev-cadence-split.md) for the
ledger and board formats; the rest of that ADR stands.
**Related:** design §8 *Which side a thing lives on*; dev-cadence TD-092–TD-096, TD-100 (the session
adapter, and its plan's scope line, dev-cadence PR #235); dev-cadence's
[2026-09-26 tracker decision](https://github.com/ShiftLead/dev-cadence/blob/main/docs/plans/2026-09-26-tracker-integration-one-interface.md).

## Context

Both repos moved to the ShiftLead GitHub org on 2026-10-11. Paul, 2026-10-12: dev-cadence should apply
to any repo and any session — Claude Code, Codex, an on-prem model, a person — with no ShiftLead on the
machine; ShiftLead should recommend dev-cadence but not require it; and the two must not drift.

The 2026-10-08 ADR placed the ledger and board formats in dev-cadence and let ShiftLead keep a second
reader of each, held equal by a parity test. That is where drift lives today:

| Format | dev-cadence | ShiftLead |
|---|---|---|
| Ledger | `files/scripts/ledger.py` (611 lines) | `src/sessionorc/ledger.py` (651) |
| Board, read | `parse_board()` and its helpers in `files/scripts/nudge_user_attention.py` (1,815 lines in all) | the Inbox runs that script (`ui/inbox.py`, preferring a dev-cadence clone's `files/` copy) |
| Board, edit | `files/scripts/board_edit.py` (289) | `src/sessionorc/board.py` (638) |

cadence §7's parity table already marks ShiftLead's ledger reader "until it reads through this one", and
marks some of its tests "this repo's side only". §2.12 already says that what a field *means* — lanes,
routing — is the orchestrator's, never the cadence's.

ShiftLead also leans on dev-cadence beyond the formats, each degrading silently when the file is absent:
the repo roster (`sessionorc/hosts.py`, `~/.config/dev-cadence/repos.txt`), the merge gate
(`sessionorc/cadence.py`, `scripts/check_cadence.py`), convention notices (`sessionorc/conventions.py`,
`scripts/cadence_changes.py`), worktree setup (`sessionorc/gitinfo.py`, `scripts/hydrate_worktree.sh`),
the SessionStart line (`adapters/claude_code`, `CADENCE_HOOK_LINE`), and built-in briefs that name this
repo's own layout (`briefs/grinder.md`: `pdm run test`; `team_skill.md` says so).

## Options

1. **Keep two repos and the parity pairs.** Drift is caught after the fact, by tests on one side.
   Rejected: it is the thing Paul named.
2. **Two repos; ShiftLead vendors dev-cadence's scripts as its readers.** One implementation, but
   ShiftLead's import is a 1,815-line nudge script whose other 90% is the cadence's process (delivery,
   forge lines, sweeps), and the formats stay bundled with a process ShiftLead says is optional.
3. **Move the formats into ShiftLead.** Rejected for the 2026-10-08 ADR's reason: every repo that runs
   the cadence without ShiftLead would depend on the orchestrator.
4. **A third repo, `records`, holding the formats once; dev-cadence and ShiftLead both consume it.**
   Chosen.

## Decision

### The three layers

| Repo | Owns | Never owns |
|---|---|---|
| **records** | The ledger and board formats: a spec (`SPEC.md`), one stdlib Python implementation (`records.py`), and language-neutral conformance fixtures. Parse, check, and the edits a format defines: an entry's header block and `Fields:` vocabularies, `Blocked by` and derived pickable, the archive's shape; a board item, `Kinds:`, `Due:`, `Answers:`/`Decided:`/replies, and the snooze/done/reply/decide edits with their one-line commit subject. | Any process: when to write, who may, what a field means, delivery, forges, git, sweeps, sessions. |
| **dev-cadence** | How a repo works, for any session or a person: cadence.md's rules, the git hooks, the gate (`check_cadence.py`), sweeps, the session-start nudge, worktree and anchor rules, `sync.sh`, and the narrow session adapter (TD-100: the four nets' questions only). | A second parser of a records format. A call to `ao`. |
| **ShiftLead** | How many sessions are run: the host agent, records of sessions, teams, lanes, claims, policies, the Inbox and every UI, what a field *means* (`Owner`, `Kind`, lanes). | A second parser of a records format. A requirement that dev-cadence be installed. |

**The rule that keeps them in sync: no second parser.** Every reader and writer of a ledger or board, in
either repo, calls `records.py`. A behaviour that needs a new field or edit is a records change first.

### How records is consumed

- **Vendored as one file, pinned to a release tag.** records publishes tagged releases. dev-cadence
  vendors `records.py` into `files/scripts/` and syncs it like any SYNC file, the lock recording the
  records tag beside its own commit. ShiftLead vendors the same file into `src/sessionorc/` (so it ships
  in the wheel and reaches container nodes), and records the tag in one constant.
- **Each consumer's CI holds its copy** to the tagged file's hash and runs records' fixtures against it.
  Drift becomes a visible pin lag, never a silent divergence.
- **stdlib only, Python ≥ 3.10**, one module, so a session can still read it on the spot — but a consumer
  never patches its copy: dev-cadence's `--verify` already reports a synced file's local edit as DRIFT.
- **The spec carries a version** (`records/1`). A file may declare it on its preamble line; a reader
  that meets a newer major version than it knows says so rather than guessing.

### What ShiftLead requires of a repo, and what it only uses

- **Requires:** a ledger in records format at `.shiftlead.yml`'s `ledger:` path (default
  `docs/technical_debt.md`). `ao` creates an empty one on request. A board is optional; without one the
  person's channel is ShiftLead's own inbox. Trackers stay outside: per dev-cadence's 2026-09-26
  decision, an external tracker is mapped *into* the ledger by an importer, not read by ShiftLead.
- **Uses when present, with a seam in `.shiftlead.yml` when not:**
  - `gate:` a command that exits 0 for a mergeable PR (`{pr}` filled); default
    `python3 scripts/check_cadence.py --pr {pr}` when that script exists, else none, said aloud.
  - `commands:` `test` and `lint`, which fill `{test}` and `{lint}` in the built-in briefs; this repo's
    `pdm run …` moves to its own `.shiftlead.yml`.
  - `worktree_setup:` default `scripts/hydrate_worktree.sh` when present.
  - Convention notices (rule 12) and the SessionStart line run only in a dev-cadence repo; they are
    features of one, not requirements.
- **Its own roster** of repos (`~/.shiftlead/`), importing dev-cadence's `repos.txt` when it exists.
- **Says what is missing.** `ao doctor` and the Repo page name each seam a repo leaves unset (no gate, no
  board, no worktree setup); nothing degrades silently.

### What changes in the 2026-10-08 rule

Its rule stands for everything but the formats: dev-cadence owns what a repo needs with no ShiftLead on
the machine; ShiftLead owns what needs a host agent, a session record or a second session; a synced
file never calls `ao`; a behaviour only a ShiftLead session needs is an environment variable ShiftLead
sets. What changes: the formats are records', and "a second reader held equal by a parity test" is
retired — cadence §7's ledger and board rows become "both read through `records.py`".

## Consequences

- A format change is three PRs in order: records (spec, code, fixtures, a release), then dev-cadence's
  vendor bump and sync, then ShiftLead's vendor bump. That is slower than today's one-repo change; it is
  the price of one definition. A consumer may lag a release; it may not diverge from one.
- The migration is code moved, not rewritten: `records.py` starts as dev-cadence's `ledger.py` parsing
  plus `parse_board()` and `board_edit.py`'s `edit_line()`, and the first release must pass both repos'
  existing format tests unchanged. ShiftLead's `ledger.py` and `board.py` then shrink to what is
  ShiftLead's: lanes, history from git, the registry, the write-back's fetch/commit/push and its locking.
- Fixtures are language-neutral (a Markdown input and its expected JSON), so a reader in another
  language can prove conformance without importing Python.
- dev-cadence's TD-092–TD-096 proceed unchanged; they make the process tool-neutral, and records is
  already tool-neutral.

## Open questions

- The repo and module name (`records`, `records.py`): a module named `records` collides with nothing in
  either repo today, but is generic.
- Whether `Swept:`/`Swept-deep:` stamp lines are records' (they live in the board file) or dev-cadence's
  (only its sweep writes and reads them). Proposed: records parses any `Name: value` preamble line it
  does not know and keeps it byte-for-byte; the stamps' meaning stays dev-cadence's.

## Revisit triggers

- A third consumer that cannot vendor a Python file (then: a package, or a second implementation held by
  the fixtures).
- A format change that a pinned consumer cannot take within a release cycle.
- A repo wanting a ledger shape `Fields:` cannot express.
