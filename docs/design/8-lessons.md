## 8. Lessons carried in (dev-cadence + tdgrind)

- **One anchor per checkout** — enforced at creation, not warned about later.
- **Ledger before idle** — the stranded-work flag makes the audit continuous.
- **One writer per shared resource** — only the host agent touches tmux.
- **State from the tool, not from the screen** — scraped state is labelled, never silent.
- **A record that exists only in scrollback is not a record** — pipe-pane from the first byte.
- **A reboot must not need a human** — systemd + linger, not a cron that notices.
- **Verify a real completion, not a catalog** — `credentials_ok()` and `usage()` are live
  calls, and the UI shows when they last succeeded.

**Which side a thing lives on** (TD-159, [ADR 2026-10-08](../decisions/2026-10-08-agentorc-dev-cadence-split.md);
the formats' placement superseded by [ADR 2026-10-12](../decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md), TD-584).
Three layers. **ledgerboard** (`ShiftLead/ledgerboard`) owns the ledger and board formats as text —
`SPEC.md`, one stdlib module `ledgerboard.py`, and the conformance fixtures — and nothing that touches
the outside. **dev-cadence** owns how a repo works for any session or a person with no shiftlead on the
machine: cadence.md's rules, the seeds, the git hooks, the gate (`check_cadence.py`), sweeps, the
session-start nudge, worktree and anchor rules, `sync.sh`, the machine roster. **shiftlead** owns how
many sessions are run: the host agent, session state, teams, lanes, claims, policies, the Inbox and
every UI, what a field is *for* (`Owner`, `Kind`, lanes), its own roster, and the board write-back's
fetch, commit, push and locking — and it recommends dev-cadence and requires only a ledger (§5 *The
seams*).
- **No second parser.** Every reader and writer of a ledger or board, in any repo, calls
  `ledgerboard.py`; a regex that recognises a ledger or board line shape outside it is a finding, and
  a diff walker uses its line predicates. shiftlead carries the module twice, the synced
  `scripts/ledgerboard.py` and the wheel's `src/sessionorc/ledgerboard.py`, held byte-equal by a test
  and renewed together in the one sync PR; a field's value past its first word (but the `Answers:`
  grammar) is the consumer's to read; a behaviour that needs a new line shape is a ledgerboard change
  first. "A second reader held equal by a parity test" is retired: cadence §7's ledger and board rows
  read *both read through `ledgerboard.py`*.
- A synced file never calls `ao`. Where it must behave differently in an shiftlead session, it
  reads an environment variable that shiftlead's launch sets. `CADENCE_ATTENTION_SCOPE` is the
  first: the hook reads it, and every launch sets it, `own` unattended and `machine` interactive
  (§4.3, TD-425). The hook's `ao status` branch is the one known exception until dev-cadence
  drops it, which waits on TD-425's live check telling it the variable reaches the hook.

