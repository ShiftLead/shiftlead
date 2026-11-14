# The planted-defect sets

A model's fitness for a role, measured before it takes the role (design §4.9b *A model's fitness, before the
role*, TD-1649). One directory per role; the fact-checker's set is the first. `pdm run judge <role> --profile <p>`
runs a set by hand, never in CI, and appends its row to `docs/judgment/<role>.md`. `tests/test_judge.py` holds each
set's shape.

## A case

`<role>/<case>/` holds two files:

- `change.patch`: a doc-only change to this repo, against the commit `case.toml` pins (a commit of `origin/main`).
  It cites no commit sha, touches neither this directory nor `docs/judgment/`, and adds no line naming either: the
  seat's repository is stripped of both.
- `case.toml`: `pinned`, the commit, and one `[[defect]]` per planted defect: its `id`, its `file` and `lines` (a
  range in the patched file), one sentence it `says`, and any number of `[[defect.refutes]]` locations (a file
  and range that shows the claim wrong). Every range is at the pushed sha: for a file the patch leaves alone, the
  pinned commit's lines. A clean case has no `[[defect]]`.

A case's locations in one file never overlap and lie more than 20 lines apart, so no one citation spans two. Each
defect is checked by hand against the code at the pinned commit, never by a model, and no two defects in a case are
refuted by the same lines. The fact-checker's set has 12 cases, 11 defects and 3 clean cases.

## The run

Each case gets a scratch repository of its own: one parentless commit of the pinned tree, stripped of the two
directories, on `main`, and the patch's commit on the branch `change`. Both commits are made with the pinned
commit's author, committer and date, so the sha is the same on every run. Both are pushed to a local bare
`origin`, and the seat works in a clone of that and nothing else. Its seat is launched as the seat smoke launches
one, with the role's brief from this checkout's `HEAD`. It is asked once, as the person, with
`fact-check PR #<the case's ordinal> at <sha>: every claim the diff makes` (`--about '#<ordinal>'`). The case ends
at the seat's reply, at its first `needs-you`, when its record reads `exited` before any reply, or after ten
minutes.

## The match, worked

A reply whose first line is no `cadence-review:` line scores the case `none`. Otherwise the reply after that line
is cut into blocks. A block starts at each top-level list marker and at each unindented paragraph outside a list.
An indented line or a nested list belongs to the block above it.

A block that names a location is a finding. A location is a token whose path is the full repo-relative path of a
file at the sha and whose line is `n` or a range `a-b`. The token is first stripped of surrounding backticks,
brackets and quotes, a trailing `.`, `,` or `:`, and a leading `a/`, `b/` or `./`. A range counts only if it is in
order, no wider than 20 lines, and inside the file. A bare basename is no location, and neither is any other
`x:n`, such as `10:30`.

In the reply's order, a finding catches every defect not yet caught whose range or refuting range it meets. A
finding that meets only defects already caught is a duplicate. One that meets none is false. A block that names no
location is not scored.

This reply is to case `02-tail-and-restarts`. D1 is the glossary's 30 lines, refuted at `agent_common.py:49`; D2
is the policy's five restarts, refuted at `agent_common.py:133`:

```text
cadence-review: BLOCK · gemini/gemini-3.5-flash-lite · docs · 5 findings
- docs/glossary.md:401 says the tail is cut from 30 lines; `src/sessionorc/agent_common.py:49` sets TAIL_LINES = 15.
- The restart ceiling is wrong (src/sessionorc/agent_common.py:133): RESTART_CEILING = 3, not five.
- docs/design/6-policies.md:2964-2965 repeats the five; checked at 10:30.
- README.md:1-40 is unchanged.
- src/sessionorc/agent_common.py:47 sets the tick, which agent_common.py:47 reads from SHIFTLEAD_TICK.
Checked against the head.
```

Its blocks score as follows:

1. The first block is a finding. It names a D1 line and a D1 refuting line, so it catches D1.
2. The second block catches D2 at its refuting line.
3. The third block meets only D2, already caught, so it is a duplicate. `10:30` is no location.
4. The fourth block names `README.md:1-40`, which is 40 lines wide and so no location. The block is not scored.
5. The fifth block names `agent_common.py:47`, a bare basename and so no location. Its full path names line 47,
   which meets no defect, so the block is a false finding.
6. The closing paragraph names no location and is not scored.

The case scores caught 2, missed 0, false 1. `tests/test_judge.py` scores this reply and holds it to that.

## The bar

A set's run passes when three things hold. Misses are at most one in ten of the planted defects in the cases
answered. Cases with a false finding are at most one in five of the cases answered. `none` is at most one in five
of the cases. A run's row says `passed` yes or no.
