# The prompt the prep-yield judges were given (TD-1720, 2026-11-12)

Two Sonnet 5.5 agents each judged half of the 510 rows of `patterns.csv` whose `check` is not `-`, given the
specification below and the row's finding text from its review record. `prep-yield.csv` holds their labels:
`judged` the check they named against this draft (whose `paths` and `counts` became the design's **claims**, `sections` its
**pointers**, `format` its **tools**; `ids` caught only a PR number and `entry` only build-entry fields, neither built), `how`
`auto`, `declared`, `already` or `none`, and `check` the design's check that catches it, or `none`.

## The specification judged against

The author of a design declares two blocks in a prep file beside the design:
- **claims**: each claim the design makes about what existing code or docs do, with `at: path:line` and optionally
  `has: "<literal the file must contain>"` (a function, flag, field name), or `run: "<read-only command>"` with
  `is: "<expected output>"` for a count or list that can be recomputed; `new: true` for a path a build will create.
- **rules**: each rule the design states in more than one place, as `find` (a phrase or regex locating every
  statement of it) and `terms` (the words, numbers and names every statement must contain).
Assume a diligent author: every rule stated in two or more places, and every claim about code, is declared;
after each round's fixes the fixer updates the terms and adds the claims.

The script runs on the PR's commit, over the text the PR adds (changed lines) and, for rules, every paragraph of
the design sections, the briefs, the open ledger entries and the synopsis. Checks:

1. **rules** — every paragraph matching a rule's `find` contains all its `terms` (drift between two statements).
2. **paths** — AUTOMATIC: every repo path written in the changed text exists at the commit (or is declared `new`
   and a build the PR files names it). DECLARED: each claim's `at` file exists and its `has` literal is in it.
3. **entry** — AUTOMATIC: for the design entry and every entry the PR adds or changes: each build carries
   `Part of: TD-<design>`, Owner and Kind; the design entry's Status names every build the PR files and nothing
   it does not; each build's Fix names a design section that exists; the review record's Design: path exists, its
   F ids are unique and sequential, each `by` names an R row, each `reopens F<n>` names an existing finding, each
   status is applied / rejected: / open / reopens; the history file docs/history/TD-<n>.md exists with a § heading;
   the Design PR section lists the PR.
4. **counts** — DECLARED only: a claim with `run:`/`is:` whose output differs.
5. **ids** — AUTOMATIC: every TD-n in the changed text exists in the ledger or archive or is filed by the PR;
   every PR #n exists on the forge; every F<n> the changed text cites exists in the record.
6. **sections** — AUTOMATIC: every §N.M in the changed text names a section file; every `§N.M *Title*` names a
   bold paragraph lead or heading in that section; every relative markdown link and its #anchor resolve.
7. **format** — AUTOMATIC: runs the repo's doc tests (synopsis shape, the §4.5a controls table against the code,
   help text) and the ledger's own `ledger.py --check --since <base>`.

**Already caught today, without the script**: `ledger.py --check` (Part of naming a missing or other-repo entry,
a second parent, Blocked by cycles, a parent blocked by its part, a decision with no Ask, a Blocked by id that
does not exist, prose waits naming ids) and the doc tests in item 7 when they are run before a review — they
are run at the PR's precheck today, after the rounds, so they do NOT reach a reviewer today.

## The instructions

For every row decide, by reading it (no keyword classifier):
- `by`: the one check (rules, paths, entry, counts, ids, sections, format) that would most plausibly have caught it,
  or `none` if no check as specified would.
- `how`: `auto` (the check catches it with no declaration by the author), `declared` (caught only because a diligent
  author declared the rule or claim), `already` (ledger.py --check would already have caught it), or `none`.
Be strict: `declared` only when the finding is the kind of drift or code fact a declaration in the specified form would
expose (a rule's terms in two statements disagree; a named symbol/flag/field absent; a recomputable count). A finding
that needs reading what code *does* is `none`. A wrong pointer to a section only counts under sections if the § number
or italic title would fail to resolve; a pointer that resolves but to the wrong rule is `none`.
