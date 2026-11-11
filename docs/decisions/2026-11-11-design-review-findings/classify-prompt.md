# Classify design-review findings

You are labelling rows from shiftlead's design review records. Each line of your input file is one finding raised by a reviewer (or fact-checker) on a software design plan before it was built:
`id` (design:finding), `round`, `by`, `role` (design | fact-check), `model`, `topic`, `finding`, `label` (the reviewer's own: build-changing | minor), `status`.
Note: the `finding` text is often written as the resolution (what the design now says after the fix) rather than as the complaint. Read `topic`, `finding` and `status` together to infer what was wrong.

Judge every row by reading it. Do NOT write a keyword or regex classifier; a script may only be used to read the input in chunks and to append your labels to the output. Use only the row and its neighbours in the same design (rows that cite it or that it cites). Do not read the repo. When the row does not let you tell, use `unsure` — never guess.

For each row output one JSON object on one line with exactly these keys:

- `id`: copied from the input.
- `kind`, what was wrong, one of:
  - `wording`: phrasing, clarity, grammar, tone; meaning unchanged.
  - `naming`: a name, term or label is inconsistent or poorly chosen; behaviour unchanged.
  - `xref`: a pointer is stale or wrong (section number, TD id, file path, PR number, a duplicated statement elsewhere left out of step).
  - `test`: a test is missing, or should be added or changed; the behaviour itself was already clear.
  - `bookkeeping`: the ledger entry or build split, not the design: Done when, slices, Blocked by, ids, owners, review-record housekeeping.
  - `unspecified`: the design was silent or ambiguous about a behaviour, so two builders could build different things.
  - `contradiction`: the design contradicted itself, another section, or an already-decided rule.
  - `false-claim`: a statement about the existing code, docs or system was untrue.
  - `wrong-mechanism`: the stated mechanism would not work, or has a bug, race or missed case.
  - `unsure`.
- `origin`, one of:
  - `fix-induced`: the row reopens, corrects, refines or follows from an earlier finding's fix (it says so, e.g. "reopens F12", "corrects F22", or it plainly addresses text an earlier row in the same design introduced).
  - `original`: a defect in the plan as first written, as far as the row shows.
  - `unsure`.
- `catch`, where this would most cheaply have been caught if no design reviewer had raised it, one of:
  - `mechanical`: a script, grep, link check or doc-bound test could find it with no model.
  - `builder`: the builder could not write the code without hitting and resolving it.
  - `pr-review`: a reviewer reading the build's diff would see it.
  - `test`: an ordinary test of the built code would fail.
  - `live`: it would only show in the running system, after merge.
  - `design-only`: only reasoning about the design finds it; in code it would be silently wrong or silently different from intent.
  - `none`: nothing downstream depends on it (pure wording).
  - `unsure`.
- `area`, the subsystem the finding is about, one of: `mail` (messages between sessions, inbox, asks, replies, steers, doorbell), `queue-ui` (Queue, Inbox page, cards, pills, screens, mockups), `ledger-board` (ledger entries, gates, the attention board, decide items), `claims-progress` (claims, progress, stuck, leases, PR claims), `identity-usage` (caller identity, usage gate, spend, readings), `teams-lifecycle` (teams, seats, members, replays, schedules, starts, wind-down), `promote-smoke` (promote, rollback, smoke, precheck on main), `adapter` (tool adapters, launch flags, hooks, prompt/brief content), `cadence` (review rounds, the cadence's own rules and scripts), `nodes-hosts` (nodes, hosts, containers, links), `other`.
- `conf`: `high` or `low`, your confidence in `kind`.

Output: append to the output file in chunks of at most 80 rows as you go (so nothing is lost), valid JSON Lines, one object per input row, same order, nothing else in the file. When done, verify with a short script that the output has exactly as many lines as the input, every line parses, every `id` matches the input's in order, and every value is one of the allowed words; fix any that fail. Write nothing outside your output file. Do not run any `ao`, `git` or `gh` command.

Final report (under 120 words): row count, the verification result, and up to three patterns you noticed that the labels alone will not show.
