## 8. Lessons carried in (agent-cadence + tdgrind)

- **One anchor per checkout** — enforced at creation, not warned about later.
- **Ledger before idle** — the stranded-work flag makes the audit continuous.
- **One writer per shared resource** — only the host agent touches tmux.
- **State from the tool, not from the screen** — scraped state is labelled, never silent.
- **A record that exists only in scrollback is not a record** — pipe-pane from the first byte.
- **A reboot must not need a human** — systemd + linger, not a cron that notices.
- **Verify a real completion, not a catalog** — `credentials_ok()` and `usage()` are live
  calls, and the UI shows when they last succeeded.

**Which side a thing lives on** (TD-159, [ADR 2026-10-08](../decisions/2026-10-08-agentorc-dev-cadence-split.md);
the formats' placement superseded by [ADR 2026-10-12](../decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md), TD-584;
its writers by [ADR 2026-11-03](../decisions/2026-11-03-ledgerboard-writers.md), TD-1330).
Three layers. **ledgerboard** (`ShiftLead/ledgerboard`) owns the ledger and board formats: a spec
(`SPEC.md`); the stdlib package `ledgerboard/` — the pure module as its `__init__.py` and the file-level
writers beside it, `board.py` (the board and rank writer) and, from v2.4, `ledger.py` (the ledger
writer); and the conformance fixtures, the writers' among them. It owns no git, network, roster, forge,
tracker, delivery, sweep I/O, session, or logic that knows either consumer, and never when to write,
who may, or what a field is *for*. ShiftLead's board writes go through `ledgerboard.board` in-process;
the lock, the temporary worktree, the commit, its push and its PR stay ShiftLead's. **agent-cadence** owns how a repo works for any session or a person with no shiftlead on the
machine: cadence.md's rules, the seeds, the git hooks, the gate (`check_cadence.py`), sweeps, the
session-start nudge, worktree and anchor rules, `sync.sh`, the machine roster. **shiftlead** owns how
many sessions are run: the host agent, session state, teams, lanes, claims, policies, the Inbox and
every UI, what a field is *for* (`Owner`, `Kind`, lanes), its own roster, and the board write-back's
fetch, commit, push and locking — and it **requires agent-cadence** in every repo it serves, while
agent-cadence stays usable with no shiftlead on the machine: the dependency runs one way, agent-cadence never
calls `ao` and never reads a layer's `shiftlead/` directory (§5 *The seams*; [ADR 2026-10-25](../decisions/2026-10-25-shiftlead-requires-dev-cadence.md),
superseding [ADR 2026-10-12](../decisions/2026-10-12-ledgerboard-dev-cadence-shiftlead.md)'s *never owns a requirement that agent-cadence be installed*). The person's
own texts — brief, entry and work additions, the director's preferences — live in their agent-cadence
layer repo, the one personal home (§4.8 *The person's own additions*).
- **No second parser.** Every reader and writer of a ledger or board, in any repo, calls
  the `ledgerboard` package; a regex that recognises a ledger or board line shape outside it is a finding, and
  a diff walker uses its line predicates. shiftlead carries the package in its wheel,
  `src/sessionorc/ledgerboard/`, vendored by `scripts/vendor_ledgerboard.sh` in the pin bump that brings
  its release; the pinned agent-cadence tree carries its own (`scripts/ledgerboard/`), and each copy's
  files' `# ledgerboard v<release> sha256:<hash>` header is the parity (§5 *The seams*, TD-1013, TD-1330); a field's value past its first word (but the `Answers:`
  grammar) is the consumer's to read; a behaviour that needs a new line shape is a ledgerboard change
  first. "A second reader held equal by a parity test" is retired: cadence §7's ledger and board rows
  read *both read through ledgerboard*.
- A synced file never calls `ao`. Where it must behave differently in an shiftlead session, it
  reads an environment variable that shiftlead's launch sets. `CADENCE_ATTENTION_SCOPE` is the
  first: the hook reads it, and every launch sets it, `own` unattended and `machine` interactive
  (§4.3, TD-425). `AGENT_MODEL` and `AGENT_MODEL_FILE` are the next (§4.2, TD-638): the commit hook
  reads the file, which the host agent rewrites when the model in use changes, so a variable set once
  at launch is not the only source and no hook asks `ao`. The hook's `ao status` branch is the one known exception until agent-cadence
  drops it, which waits on TD-425's live check telling it the variable reaches the hook.

