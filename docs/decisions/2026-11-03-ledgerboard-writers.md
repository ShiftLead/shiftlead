# ADR 2026-11-03: ledgerboard ships the file-level writers, `ledger.py` and `board.py`, beside its pure module

**Status:** decided 2026-11-02 by Paul (his go on ledgerboard's target design, ledgerboard#57, whose §1.1
*The boundary moves* names this amendment); written 2026-11-03 for TD-1326.
**Date:** 2026-11-03
**Supersedes:** in [ADR 2026-10-12](2026-10-12-ledgerboard-dev-cadence-shiftlead.md), the layer table's
**ledgerboard** row, the first line of *The ledgerboard API* ("Pure functions over text"), and the *one file*
of *How ledgerboard is consumed*, as listed under *Decision*; the rest of that ADR (the three layers, the
rule of no second parser, the API's functions, the version line) stands, and so does
[ADR 2026-10-25](2026-10-25-shiftlead-requires-dev-cadence.md)'s part.
**Related:** TD-1326 (this ADR); TD-1330 (ShiftLead's v2.3 vendor and its board writes, the first build on
it); TD-1286 (every ledger and board write goes through the helpers; its ledger half waits for v2.4);
ledgerboard's [target design](https://github.com/ShiftLead/ledgerboard/blob/main/docs/plans/target-design.md)
§1 principles 5–6, §1.1, §1.2, §7.2 (ledgerboard#57); agent-cadence#TD-206, agent-cadence#TD-213.

## Context

ADR 2026-10-12 put the ledger and board formats in a third repo, ledgerboard, to end the drift of two
consumers each reading them their own way, and drew its boundary at the formats as text: `SPEC.md`, one
stdlib module and the conformance fixtures, nothing that touches the outside. Reading moved there; writing
did not. Each consumer kept its own command-line writer over the module — agent-cadence's `ledger.py`
(1,624 lines) and `board_edit.py`, ShiftLead's `sessionorc/ledger.py` and `sessionorc/board.py` (about
2,000 lines together) — and their file handling (which files an archive move, a split or a renumber
touches; writing several files as one; refusing a write that adds a `check()` flag) is format work both
need, each written its own way (the line counts are the target design's, §1.1). That is the drift the ADR was written to end, one layer up.

Paul's rule of 2026-10-30 (TD-1286) makes every ledger and board write in a ledgerboard repo go through the
helpers, `ledger.py` and `board.py`, never by hand. With two sets of helpers, that rule would hold two
definitions of a write. ledgerboard's target design, agreed with Paul on 2026-11-02 (ledgerboard#57),
moves the writers into ledgerboard (§1.1) and more of the format's decisions into the module as pure
functions (§1.2). ledgerboard's v2.3 release cites this boundary, so the amendment lands before it.

## Options

1. **Keep the boundary; each consumer keeps its writer.** The drift stays where it is now, and Paul's
   helper rule names two different helpers. Rejected.
2. **agent-cadence's writers are the helpers, and ShiftLead runs them.** One implementation, but the
   writers would carry agent-cadence's git, roster and counter code, and ShiftLead (which calls them
   in-process from the host agent) would depend on a process layer for a file edit. It was TD-1286's
   reading before the target design. Rejected.
3. **ledgerboard ships the writers, git-free, beside the pure module; each consumer wraps them with its own
   git and policy.** Chosen (the target design's §1.1).

## Decision

1. **The ledgerboard row of the layer table now reads:**

   | Repo | Owns | Never owns |
   |---|---|---|
   | **ledgerboard** (`ShiftLead/ledgerboard`, package `ledgerboard/`) | The ledger and board formats: a spec (`SPEC.md`); the stdlib package `ledgerboard/` — the pure module as its `__init__.py` (today's `ledgerboard.py`, unchanged in role) and the two file-level writers beside it, `ledger.py` (the ledger writer) and `board.py` (the board and rank writer); and the conformance fixtures, the writers' among them (a directory before, a command, the directory after and the printed subject). | Git, the network, the machine roster, forges, trackers, delivery, running a sweep (its I/O, its event checks and its lift PRs stay the consumers'; its pure decisions are the module's), sessions, and any logic that knows either consumer. When to write, who may, and what a field is *for*. |

   The agent-cadence and ShiftLead rows stand; ShiftLead's *the board write-back's fetch, commit, push and
   locking* is exactly what a wrapper keeps (3).

2. **The module stays pure; the writers add file reading and writing, and nothing else** (target design §1
   principle 6). A writer reads the files it is given, applies the module's edit, writes them back — several
   files as one, or none — and prints the commit subject the module gives and the paths it changed. It is
   both an importable library and a command line with the same actions; ShiftLead calls it in-process.
   *The ledgerboard API*'s "Pure functions over text" now holds of the module, `ledgerboard/__init__.py`,
   and its list of functions stands, joined by §1.2's further pure functions (the next id's rule, the gate
   sweep's decisions, the lift-PR verdict, `needs_you`), none of which moves the boundary.

3. **What a writer needs from outside is passed in**, and the consumer keeps everything around the write
   (target design §1.1): the next id (`--id`, from the consumer's counter), the ledger's path, the files
   outside the ledger that name an id, cross-repo state (the resolver, as `pickable()` takes it), and who
   answered or lifted (`--by`). The writer reads the clock for its dates itself — UTC for the ledger, local
   for the board — and `--today` is a test and replay override only. Branches, commits, PRs, the id counter,
   the merge gate, attesting the session, locks and temporary worktrees stay the consumer's. A consumer's own
   `ledger.py` or `board.py` becomes a thin wrapper that does those and calls ledgerboard's writer.

4. **The rule of no second parser gains its writing half:** every write of a ledger or board file, in any
   repo, goes through ledgerboard's writers — never a consumer's own file handling, and never a hand edit
   (target design §1 principle 5; TD-1286). A behaviour that needs a new write is a ledgerboard change first,
   as a new field or line shape already is.

5. **How ledgerboard is consumed: a package, not one file.** Each consumer vendors the package whole, every
   file in it carrying the release header, and the vendor removes the old single `ledgerboard.py` in the same
   change (Python would silently prefer the package beside it). ShiftLead's wheel copy becomes the subpackage
   `src/sessionorc/ledgerboard/` (`from sessionorc import ledgerboard`, `from sessionorc.ledgerboard import
   board`); since ShiftLead also reads agent-cadence's layout through its pin, its pin bump to the release that
   carries agent-cadence's vendor and its own vendor are one PR (target design §7.2 step 0). The rest of
   *How ledgerboard is consumed* holds, read per file of the package.

## Consequences

- **Releases** (target design §1.1): v2.3 ships the package and `board.py` (with `due`, `Hide until` and a
  board's `People:`); v2.4 ships `ledger.py`. ShiftLead takes v2.3 in TD-1330, whose `sessionorc/board.py`
  calls ledgerboard's `board.py` for every write and whose Inbox reads `needs_you`; its `sessionorc/ledger.py`
  becomes a wrapper with v2.4 (TD-1286's ledger half).
- **The design follows the build, not this ADR.** Design §8 *Which side a thing lives on* says what runs:
  its ledgerboard sentence (*`SPEC.md`, one stdlib module `ledgerboard.py`, and the conformance fixtures —
  and nothing that touches the outside*) changes to this ADR's row in TD-1330's PR, when ShiftLead runs the
  package.
- A consumer's wrapper is smaller than its writer today, and a change to how a file is written is one
  ledgerboard PR plus each consumer's vendor, the price ADR 2026-10-12 already accepted for the formats.
- ledgerboard's own `AGENTS.md` and README state the same boundary, changed in its package PR (target design
  §1.1).

## Revisit triggers

- A writer needs git, the network or a consumer's state to do its job, and passing it in is not enough.
- A third consumer needs a write neither writer offers and cannot wait for a ledgerboard release.
