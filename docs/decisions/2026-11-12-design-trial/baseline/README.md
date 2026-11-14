# The trial's baseline (TD-1775)

The ten designs the first ten real designs are read against (design §4.9c *The trial of the new shape*,
*The baseline*), measured now, before their transcripts are pruned (about 30 days): their cost, size and findings' labels, and the escape lister
that TD-1776 runs over each at the reading (their escapes are TD-1776's, since their builds' windows are still open).

## The ten

The designs with a `Source: rounds` record whose last design PR (the last in the entry's `Design PR:`) merged last
before TD-1756's merge (#3682, 2026-11-13T06:05:21Z), leaving out the three replayed (TD-1557, TD-1569, TD-1470),
the shape's own designs (TD-1720, TD-1721, TD-1722), and **TD-1711** (#3524, merged 2026-11-12T05:01Z), the plan
those three are parts of: it is the shape too, and its record is a plan reviewed by Sonnet alone, not a design
reviewed Fable then Sonnet (the techlead's ruling, m-effae5549771, 2026-11-13). TD-1577 (#3477, 2026-11-11T19:59Z)
is the tenth in its place. The ten are fixed at this measurement: a later design PR of one of them is reported and
not counted.

| design | design PRs (head branch) | last merged |
|---|---|---|
| TD-1550 | #3386 (`td1550-design`), #3487 (`td-1675-round5`), #3575 (`td1707-design`), #3590 (`td1732-round`) | 2026-11-12T17:56Z |
| TD-1573 | #3497 (`td1573-design`), #3574 (`td1703-design`) | 2026-11-12T08:49Z |
| TD-1671 | #3570 (`td1671-design`) | 2026-11-12T08:25Z |
| TD-1650 | #3569 (`td1650-design`) | 2026-11-12T07:45Z |
| TD-1567 | #3567 (`td1567-design`) | 2026-11-12T06:57Z |
| TD-1543 | #3367, #3492 (`td-1676-round9`), #3525 (`td1702-round10`), #3542 (`td1708-round11`) | 2026-11-12T04:27Z |
| TD-1590 | #3526 (`td1590-design`) | 2026-11-12T04:02Z |
| TD-1568 | #3516 (`td1568-design`) | 2026-11-12T02:23Z |
| TD-1556 | #3504 (`td1556-design`) | 2026-11-12T02:12Z |
| TD-1577 | #3410 (`td1577-design`), #3456 (`td-1652-round5`), #3477 (`td-1673-round6`) | 2026-11-11T19:59Z |

## Cost and size

`python capture.py` prints this from `turns.csv` and `sizes.csv`:

| design | lines added | designer turns | reviewer turns | designer $ | reviewers $ | $ | $ per 100 lines |
|---|---|---|---|---|---|---|---|
| TD-1550 | 980 | 685 | 1160 | 47.74 | 97.49 | 145.23 | 14.82 |
| TD-1573 | 140 | 264 | 404 | 17.46 | 38.43 | 55.89 | 39.92 |
| TD-1671 | 112 | 111 | 101 | 6.04 | 11.30 | 17.33 | 15.48 |
| TD-1650 | 158 | 135 | 177 | 8.78 | 14.53 | 23.31 | 14.76 |
| TD-1567 | 185 | 151 | 262 | 9.18 | 22.44 | 31.62 | 17.09 |
| TD-1543 | 460 | 686 | 924 | 47.12 | 73.97 | 121.09 | 26.32 |
| TD-1590 | 230 | 208 | 161 | 13.33 | 16.97 | 30.30 | 13.17 |
| TD-1568 | 235 | 188 | 271 | 14.55 | 19.34 | 33.89 | 14.42 |
| TD-1556 | 240 | 230 | 541 | 15.03 | 48.98 | 64.00 | 26.67 |
| TD-1577 | 527 | 409 | 410 | 25.04 | 42.59 | 67.63 | 12.83 |
| all ten | 3267 | 3067 | 4411 | 204.27 | 386.02 | 590.29 | 18.07 |

The median of the ten's $ per hundred lines is 15.15. *Designer turns* are the designer's own turns without the
reports reaching it (the `report` rows), as the originals' main-thread turns are counted. Every one of the ten has
transcripts, so all ten are costed.

## Findings

`python labels.py` prints this from `labels.csv` and `patterns.csv`. *Mechanical* is the share whose `catch` is
`mechanical`, *fix-induced* the share whose `origin` is; *hard after round 1* counts the findings after round 1 whose
pattern `case` is one of the hard situations (interaction, concurrency, when, ends, who, failure, restart).

| design | rounds | findings | the analysis's | per round | mechanical | fix-induced | hard after round 1 |
|---|---|---|---|---|---|---|---|
| TD-1550 | 10 | 279 | 116 | 27.9 | 19% | 50% | 74 |
| TD-1573 | 5 | 129 | 0 | 25.8 | 9% | 36% | 16 |
| TD-1671 | 3 | 42 | 0 | 14.0 | 0% | 26% | 3 |
| TD-1650 | 4 | 70 | 0 | 17.5 | 3% | 17% | 10 |
| TD-1567 | 4 | 68 | 0 | 17.0 | 24% | 19% | 9 |
| TD-1543 | 11 | 209 | 149 | 19.0 | 19% | 34% | 52 |
| TD-1590 | 4 | 84 | 0 | 21.0 | 8% | 24% | 23 |
| TD-1568 | 4 | 70 | 0 | 17.5 | 11% | 40% | 7 |
| TD-1556 | 4 | 88 | 0 | 22.0 | 10% | 27% | 17 |
| TD-1577 | 6 | 138 | 120 | 23.0 | 17% | 22% | 15 |
| all ten | 55 | 1177 | 385 | 21.4 | 14% | 34% | 226 (22.6 a design) |

Of the 1,177 findings, 385 (TD-1550's, TD-1543's and TD-1577's earlier rounds, whose records were among the
analysis's 41) keep the analysis's labels; the other 792 were labelled for this baseline. The two classify labellers
agreed on kind for 663 of the 792 and on origin for 649; the third read the 242 rows where they differed on either.

## The escape lister

`python escapes.py TD-<n>` lists, for one design, what TD-1776's trace labeller reads with
[`../trace-prompt.md`](../trace-prompt.md) at the reading: each build (an entry `Part of:` the design, of kind
`build`) with its build PRs merged within 28 days of the design's first design PR's merge, each build PR's numbered
review findings, and its candidate fix PRs (merged after its first build PR and within 14 days of its last, not
leading with the build's id, naming the build's or the design's id). It reads the forge and writes nothing.
[`escapes-TD-1650.txt`](escapes-TD-1650.txt) is its run over TD-1650 on 2026-11-14, two days into that design's
window: both its builds merged, TD-1726's review raised three findings, and the fix candidates are a sibling build
(TD-1727's #3572) and the cost model's #3674, which names TD-1650; which, if any, is an escape is the trace
labeller's to judge.

## How each file was made

- **`turns.csv`** — on 2026-11-13, the cost model's [`extract.py`](../../2026-11-12-design-cost-model/extract.py) over
  every shiftlead project directory of both Claude Code profiles on this machine (`~/.claude/projects/*shiftlead*`,
  `~/.claude-conformance/projects/*shiftlead*`), so every session that worked on a design's branches is read, not only
  the designer's; then `python capture.py select <that output>`, which runs the cost model's
  [`tables.py`](../../2026-11-12-design-cost-model/tables.py) `select` (its Method step 2: the design's branches, the
  launch-branch turns next to them, the reviewers by their first turn) one design at a time, since `select` phases
  the rows it picks in place. Its columns are the cost model's. One designer session works several designs' branches
  in turn, so 555 turns were picked for two designs (TD-1543 with TD-1550 and with TD-1590, TD-1556 with TD-1568),
  nearly all reviewers whose first turn fell in both designs' windows; each is kept once, under the design whose
  branches hold its own branch, a reviewer on a launch branch under the design that holds most of its rows'
  branches, and any other under the design of its session's next turn on a design's branch. Before that, TD-1650's
  and TD-1543's rows matched the cost model's own `turns.csv` turn for turn; after it TD-1650's still do, and TD-1543
  keeps 1,660 of the 2,020 rows the cost model gives it: the other 360, nearly all reviewers on `td1550-design` and
  `td1590-design`, are TD-1550's and TD-1590's, designs the cost model did not select, so it counted them under
  TD-1543 (TD-1800).
- **`sizes.csv`** — `python capture.py sizes`: each design PR's additions under `docs/design/`, `docs/ledger/` and
  `docs/synopses/`, by `git show --numstat` of its squash commit.
- **Prices** are the cost model's weights (`tables.py` `WEIGHTS`, `ao spend`'s defaults).
- **`labels.csv`, `patterns.csv`** — `python labels.py merge labellers`: every finding of the ten records, read at
  `labels.py` `RECORDS` as the analysis's `tables.py` reads them. A finding the analysis labelled keeps its labels;
  every other was labelled on 2026-11-13 and 2026-11-14 by Sonnet 5.5 agents with the analysis's
  [`classify-prompt.md`](../../2026-11-11-design-review-findings/classify-prompt.md) (labellers `a-` and `b-` apart,
  a third, `c-`, blind to the two, on the rows where they differed on kind or origin, whose kind and origin stand
  there; catch and area the first's) and then
  [`pattern-prompt.md`](../../2026-11-11-design-review-findings/pattern-prompt.md) (one labeller, `p-`, given the
  merged labels). Their outputs are in [`labellers/`](labellers/); `labels.py inputs`, `thirds` and `pinputs` wrote
  their inputs.
