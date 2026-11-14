# The trial of the new design shape: report

The report of TD-1722's trial (design §4.9c *The trial of the new shape*). Its rows and scripts are under
[`2026-11-12-design-trial/`](2026-11-12-design-trial/README.md); each build of the trial writes its own section here
(TD-1774 the replays, TD-1775 the baseline, TD-1776 the reading).

## The baseline

The ten designs the first ten real designs are read against: the ten with a `Source: rounds` record whose last
design PR merged last before #3682, leaving out the three replayed, the shape's own designs and TD-1711, the plan
they are parts of (the techlead's ruling, m-effae5549771): TD-1550, TD-1573, TD-1671, TD-1650, TD-1567, TD-1543,
TD-1590, TD-1568, TD-1556 and TD-1577. Measured on 2026-11-13 and 2026-11-14 (TD-1775); the rows, the scripts that
rebuild each table and how each file was made are in
[`2026-11-12-design-trial/baseline/`](2026-11-12-design-trial/baseline/README.md).

**Cost.** All ten have transcripts, so all ten are costed: $590.29 over 3,267 lines added, $18.07 per hundred lines
pooled, a median of **$15.15** per hundred lines across the ten (from $12.83, TD-1577, to $39.92, TD-1573). The
designers' own turns are $204.27 of it, the reviewers' $386.02. All ten merged before TD-1788 did (#3742), so each
ran under the designer's 300k bound. A designer session worked several designs' branches in turn, so each turn is
kept under one design by the branch it ran on: 360 reviewer rows the cost model counts under TD-1543 are TD-1550's
and TD-1590's here (TD-1800).

**Findings.** 1,177 findings over 55 rounds, **21.4 per round**; **14%** a script would catch (`mechanical`; the
analysis found 16%) and **34%** `fix-induced` (TD-1550's 50% the most, TD-1650's 17% the least); **226** in the hard
situations raised after round 1, **22.6 a design** as the mean (83, 8.3 a design, raised by Sonnet's design reviews
alone); and **104** (9%) outside the hard situations and `design-only`. 385 of the findings keep the analysis's
labels, being in its 41 records; the other 792 were labelled by **Sonnet 5.5** (two classify labellers on kind and
origin, which agreed on 663 and 649 of them, a third on the 242 rows where they differed, one pattern labeller). If
the reading's labeller model is not Sonnet 5.5, the reading labels the baseline again with it.

**Escapes** are TD-1776's, traced at the reading with the real designs', since the baseline's build windows are still
open. `escapes.py` lists each design's candidates for the trace labeller: run over TD-1650 on 2026-11-14, it lists
both builds' PRs (#3571, #3572), the three findings of TD-1726's review, and two candidate fix PRs (#3572, a sibling
build, and the cost model's #3674), each for the labeller to judge.
