# What the design review rounds find, and where else it could be caught (2026-11-11)

**Status:** an analysis, for discussion. It decides nothing. Paul asked for it on 2026-11-11 while planning
how to spend the account's usage well: the design rounds are where the designer's tokens go, and the
question was which of their findings need a design review at all.

**What was read:** the 41 review records with `Source: rounds` under `docs/reviews/` at commit `df866eeb8`
(the six backfilled records have no tokens and no finding labels and are left out). They hold 651 reviews
and 3,120 findings, dated 2026-11-03 to 2026-11-11.

**The data is kept beside this file**, in [`2026-11-11-design-review-findings/`](2026-11-11-design-review-findings/):
`labels.csv` (one row per finding), `classify-prompt.md` (the instructions the labellers were given),
`patterns.csv` and `pattern-prompt.md` (the second pass, below) and `tables.py`, which rebuilds every table
below from the records at that commit and the labels.

## How the findings were labelled

Seven Sonnet 5.5 agents each read about 440 findings of their own, and one record they all shared, and gave each one four labels, by reading the row and
the rows of the same design that cite it, not by keyword:

- **kind**, what was wrong: `wording`, `naming`, `xref` (a stale or wrong pointer), `test` (a missing test),
  `bookkeeping` (the ledger entry, not the design), `unspecified` (the design silent or ambiguous on a
  behaviour), `contradiction`, `false-claim` (a false statement about the existing code or docs),
  `wrong-mechanism` (the mechanism would not work), `unsure`.
- **origin**: `original` (in the plan as first written) or `fix-induced` (it reopens, corrects or follows an
  earlier finding's fix).
- **catch**, where it would most cheaply have been caught with no design review: `mechanical` (a script, no
  model), `builder` (the builder cannot write the code without resolving it), `pr-review`, `test`, `live`
  (only in the running system), `design-only` (only reasoning about the design finds it), `none`.
- **area**, the subsystem.

**How far to trust them.** Every agent also labelled the same 41-finding record (TD-1286). Pairwise
agreement was 88% on kind, 90% on origin, 84% on area and 76% on catch; on the yes-or-no question *is this
deferrable* (below) it was 93%. `catch` is a judgement about something that did not happen and is the
softest column. Of the 295 rows whose own text says they reopen, correct, refine or extend a finding, 293
are labelled `fix-induced`. One agent reported realigning its hand-typed labels partway through its batch;
its rows pass that check (45 of 46). A record's finding text is often written as the fix, not the complaint,
so `kind` is inferred for many rows.

## What the reviews find

| What was wrong | findings | share | reviewer said build-changing | reviewer said minor |
|---|---|---|---|---|
| unspecified | 1,273 | 41% | 227 | 1,036 |
| wrong-mechanism | 553 | 18% | 381 | 172 |
| false-claim | 394 | 13% | 129 | 258 |
| xref | 233 | 7% | 14 | 216 |
| bookkeeping | 207 | 7% | 21 | 182 |
| wording | 132 | 4% | 0 | 131 |
| contradiction | 123 | 4% | 45 | 77 |
| test | 116 | 4% | 7 | 109 |
| unsure | 65 | 2% | 3 | 62 |
| naming | 24 | 1% | 1 | 23 |

**The reviewers' *minor* label is wide.** Call a finding *deferrable* when its kind is wording, naming, xref,
test or bookkeeping. Of the 2,266 findings the reviewers labelled minor, 661 (29%) are deferrable and 1,543
(68%) are not: most are a behaviour the design left open. The cadence's own definition of build-changing
(*two builders reading the plan as written would build different things*) covers those.

## Where each would have been caught with no design review

| Caught by | findings | share |
|---|---|---|
| the builder | 1,682 | 54% |
| a script | 510 | 16% |
| design reasoning only | 419 | 13% |
| a test of the built code | 208 | 7% |
| nothing depends on it | 184 | 6% |
| the running system only | 49 | 2% |
| the PR review | 40 | 1% |
| unsure | 28 | 1% |

- 468 findings (15%) are `design-only` or `live`: what a design review alone buys. 271 of them are a wrong
  mechanism and 67 a contradiction.
- 1,200 of the 1,273 unspecified findings are `builder`: the builder would have had to decide.
- The 510 mechanical findings are 225 stale pointers, 153 bookkeeping and 78 false claims a grep would show.
  285 of them were raised by fact-checks.

## A fix breeds findings

| Round | findings | follow from an earlier fix | share |
|---|---|---|---|
| 1 | 991 | 66 | 7% |
| 2 | 706 | 178 | 25% |
| 3 | 475 | 139 | 29% |
| 4 | 385 | 108 | 28% |
| 5 and later | 563 | 285 | 51% |

A quarter of all findings (776) follow from an earlier round's fix. Following the citations forward (a later
finding of the same design that names an earlier one by id, transitively):

| What was wrong | findings | any follow-up | three or more | a build-changing follow-up |
|---|---|---|---|---|
| unspecified | 1,273 | 14% | 2.9% | 6.5% |
| wrong-mechanism | 553 | 28% | 8.3% | 17.4% |
| false-claim | 394 | 14% | 2.3% | 7.6% |
| contradiction | 123 | 22% | 4.9% | 10.6% |
| xref | 233 | 7% | 0.4% | 0.4% |
| bookkeeping | 207 | 6% | 0.5% | 0.5% |
| wording | 132 | 5% | 0.0% | 1.5% |
| test | 116 | 9% | 0.9% | 3.4% |

So an unspecified detail usually stays a detail: about one in fifteen leads to a later build-changing
finding and about one in thirty-five to a chain of three or more. This counts only follow-ups that name the
finding, so it is a floor. The long chains are few and sit together: the six largest start in TD-1470 and
TD-1453, both about which claim on an entry or a PR counts, and a deferrable finding almost never starts one.

## By subsystem

| Subsystem | findings | reviewer said build-changing | follow from a fix |
|---|---|---|---|
| Queue and Inbox pages | 685 | 153 | 23% |
| ledger and board | 470 | 114 | 20% |
| teams and seats | 392 | 120 | 19% |
| adapters | 374 | 139 | 25% |
| mail | 344 | 98 | 23% |
| cadence | 276 | 39 | 24% |
| claims and progress | 266 | 67 | 44% |
| promote and smoke | 166 | 50 | 35% |
| identity and usage | 67 | 29 | 28% |
| nodes and hosts | 33 | 10 | 21% |

## Fable and Sonnet as reviewers

| | reviews | tokens | per review | findings | substantive | design-only or live |
|---|---|---|---|---|---|---|
| Fable, design review | 171 | 19.8M | 116k | 1,133 | 927 | 226 |
| Sonnet, design review | 180 | 15.0M | 84k | 1,020 | 794 | 148 |
| Sonnet, fact-check | 300 | 25.4M | 85k | 966 | 621 | 93 |

Per review, Fable raises more of the findings only a design review catches (1.3 against 0.8). Per token the
two are close: 88k tokens for each such finding from Fable, 102k from Sonnet, and 21k against 19k for each
substantive one. Paul's note the same day: a Fable review costs far more than a Sonnet one. If Fable's price per token is
more than about 1.16 times Sonnet's, Sonnet is the cheaper design reviewer on this data. The comparison is confounded: the two alternate on the same text, so whichever reads first takes
the findings both would have raised. What Fable finds that Sonnet would not is not measured here.

## The pattern behind each finding (the second pass)

A second run the same day, seven Sonnet 5.5 agents over the same rows with the first pass's labels given,
named the pattern behind each finding: `patterns.csv`, its instructions `pattern-prompt.md`. Agreement on the
shared record: 89% on `case` (20 rows), 86% on `fact` (4), 85% on `check` (8), 67% on `fixfail` (6); the last
is soft and the last three rest on few rows.

**The situation a design had not handled** (the 1,949 unspecified, wrong-mechanism and contradiction findings):

| Situation | findings | only a design review or the live system would catch |
|---|---|---|
| shape: a field, format, name, where it is stored, exact words | 341 | 5% |
| scope: what the rule covers, which callers, pages, kinds | 312 | 12.5% |
| interaction: how it combines with an existing rule | 214 | 38% |
| which: choosing among several, tie-break, order of rules | 186 | 16% |
| when: the trigger, the clock, until when | 164 | 30% |
| display: what a screen or command shows in a state | 132 | 6% |
| failure: an error path | 115 | 23% |
| ends: closed, archived, renamed, expired | 92 | 33% |
| who: which actor does it, may do it, is told | 87 | 29% |
| empty-first: nothing there yet, old data, migration | 86 | 14% |
| concurrency: two actors or events at once | 67 | 61% |
| multi-node: a node against the home, another host | 62 | 16% |
| restart: a restart, crash, replay, promote partway | 55 | 36% |
| proof: how it is verified | 33 | 21% |
| other | 3 | |

Two groups. Shape, scope, which and display are half the findings and the builder would meet nearly all of
them. Concurrency, interaction, restart, ends, when and who are fewer and are where a design review finds
what nothing else would. `patterns.csv`'s `q` column holds, for each of the 1,949, the general question the
author should have answered, in at most twelve words: the raw material of an author's checklist.

**The check a script would run** (the 510 mechanical findings):

| Check | findings |
|---|---|
| the same statement in two places, drifted apart | 162 |
| a path, function, flag or field that should exist | 100 |
| a ledger entry's fields, parts or Done when out of step with the design | 96 |
| a count or list that can be recomputed | 42 |
| a TD id, PR number or finding id | 41 |
| a section number, heading or anchor | 34 |
| a format rule | 13 |
| other | 22 |

**The sort of fact a false claim got wrong** (394): what existing code does, 236 (60%); whether a function,
file, flag or test exists, 60; what another section says, 28; how an outside tool behaves, 28; a number, 23;
what is built or live, 18; other, 1. Only 78 of the 394 are a script's to catch; the rest need the code read.

**Why an earlier fix led to a finding** (776): it opened a new case, 199; it addressed part of the finding,
194; its own mechanism was wrong, 186; it was made in one place and another still said the old thing, 167
(116 of them a script's to catch); it changed something that was right, 15; other, 15.

## What the cost side shows, and does not

From the first pass the same day (`ao spend` and the forge, not in `tables.py`): the 651 reviews total 60.3M
tokens over the nine days, against 2.61B for the `designer-ao-1` session. The two are not shown to count
tokens the same way, and that session does other work too, so the 2% is a rough ratio; it still says the
cost of a round is the author's turns applying fixes at 140k to 300k tokens of context each, not the
reviewers. Over 2026-10-29 to 2026-11-11, 808 PRs merged against about $4,990 of `ao spend`'s estimate
across every team on the home, about $6 a PR.

**Not measured, because nothing records it:** the designer's spend per design, the cost of a build per
entry, and whether a finding in a PR review or a fix after a merge traces to a design that should have
caught it. The last is the measure of what cutting a round would cost.

## What it suggests

Offered for the discussion, not decided:

1. **A script before round 1** for pointers, ids, paths and the entry's bookkeeping: a sixth of the findings,
   no model.
2. **A lower cap for in-repo designs.** Rounds 3 and 4 cost roughly 155k and 218k reviewer tokens for each
   build-changing finding against round 1's 33k (the first pass's figures, not in `tables.py`), and from round 2 on a quarter or more of what they find is
   the last round's fixes.
3. **A narrower *minor*:** only the deferrable kinds, which a builder can take as notes at almost no risk.
4. **Who settles an unspecified detail** is the open question: 41% of the findings, more than nine in ten of
   which the builder would meet anyway, about 7% of which lead to something build-changing.
5. **Where the long chains are** (claims and progress, 44% fix-induced) says a design that keeps reopening
   one rule is better stopped and asked about than bought another round.
