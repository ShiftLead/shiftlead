# The trial's baseline (TD-1775)

The ten designs the first ten real designs are read against (design §4.9c *The trial of the new shape*,
*The baseline*), measured now, before their transcripts are pruned (about 30 days). Their findings' labels and the
escape lister follow in later slices of TD-1775; their escapes are TD-1776's, at the reading.

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
| TD-1543 | 460 | 687 | 1283 | 47.18 | 110.44 | 157.63 | 34.27 |
| TD-1590 | 230 | 208 | 161 | 13.33 | 16.97 | 30.30 | 13.17 |
| TD-1568 | 235 | 195 | 275 | 15.02 | 19.84 | 34.86 | 14.83 |
| TD-1556 | 240 | 230 | 725 | 15.03 | 63.29 | 78.31 | 32.63 |
| TD-1577 | 527 | 409 | 410 | 25.04 | 42.59 | 67.63 | 12.83 |
| all ten | 3267 | 3075 | 4958 | 204.80 | 437.31 | 642.11 | 19.65 |

The median of the ten's $ per hundred lines is 15.16. Every one of the ten has transcripts, so all ten are costed.

## How each file was made

- **`turns.csv`** — on 2026-11-13, the cost model's [`extract.py`](../../2026-11-12-design-cost-model/extract.py) over
  every shiftlead project directory of both Claude Code profiles on this machine (`~/.claude/projects/*shiftlead*`,
  `~/.claude-conformance/projects/*shiftlead*`), so every session that worked on a design's branches is read, not only
  the designer's; then `python capture.py select <that output>`, which runs the cost model's
  [`tables.py`](../../2026-11-12-design-cost-model/tables.py) `select` (its Method step 2: the design's branches, the
  launch-branch turns next to them, the reviewers by their first turn) one design at a time, since `select` phases
  the rows it picks in place. Its columns are the cost model's. TD-1543's and TD-1650's rows match the cost model's own
  `turns.csv` turn for turn.
- **`sizes.csv`** — `python capture.py sizes`: each design PR's additions under `docs/design/`, `docs/ledger/` and
  `docs/synopses/`, by `git show --numstat` of its squash commit.
- **Prices** are the cost model's weights (`tables.py` `WEIGHTS`, `ao spend`'s defaults).
