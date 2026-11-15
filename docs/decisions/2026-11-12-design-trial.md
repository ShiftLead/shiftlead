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

## The replays

Two of the three designs replayed on the new shape were scored; **TD-1470's replay was stopped** (below). Each
replay ran once with a clean audit, at trial commit `eab3f61` on the conformance profile, and its result, review
record, audit, turns and every scorer's output are under
[`2026-11-12-design-trial/replays/`](2026-11-12-design-trial/replays/); `replays/lines.py` rebuilds every figure
below from them (TD-1774, 2026-11-14).

**The three lines, TD-1557 and TD-1569 pooled** (101 key rows; each the replays' share less the originals' over the
same rows):

| line | replays | originals | difference | limit | crossed |
|---|---|---|---|---|---|
| scored rows silent or wrongly handled | 9 / 93 (9.7%) | 1 / 93 (1.1%) | **+8.6 points** | 10 | no |
| the same, hard situations only | 5 / 36 (13.9%) | 0 / 36 (0%) | **+13.9 points** | 10 | **yes** |
| whole key, not applicable as not handled | 12 / 96 (12.5%) | 1 / 101 (1.0%) | **+11.5 points** | 12.5 | no |

The scored rows are those neither design marked not applicable. On the whole-key line, five rows leave the
replays' count, the not-applicable rows that are false claims the replay never makes (TD-1557's F69, TD-1569's F39,
F82, F85 and F86), and none for a person's answer, since no key row's `person` is yes. Read by the
proposed rule, a replay is **clearly worse** when any line is crossed, so the hard-situations line crosses it. That
line rests on 36 rows and five silent marks, each one both scorers gave: TD-1557's F32 and F41 (concurrency), F60
(failure) and F78 (interaction), and TD-1569's F29 (interaction). No row was marked wrongly handled in either replay.

**Marks by situation** (handled · silent · wrongly handled · not applicable; *hard* marks the hard situations):

**TD-1557** (57 key rows; handled · silent · wrongly handled · not applicable)

| situation | replay | original |
|---|---|---|
| concurrency (hard) | 0 · 2 · 0 · 0 | 2 · 0 · 0 · 0 |
| failure (hard) | 2 · 1 · 0 · 0 | 3 · 0 · 0 · 0 |
| interaction (hard) | 10 · 1 · 0 · 1 | 12 · 0 · 0 · 0 |
| who (hard) | 4 · 0 · 0 · 0 | 4 · 0 · 0 · 0 |
| display | 3 · 0 · 0 · 0 | 3 · 0 · 0 · 0 |
| scope | 5 · 1 · 0 · 0 | 6 · 0 · 0 · 0 |
| shape | 9 · 1 · 0 · 1 | 11 · 0 · 0 · 0 |
| which | 3 · 0 · 0 · 1 | 4 · 0 · 0 · 0 |
| (none) | 10 · 1 · 0 · 1 | 11 · 1 · 0 · 0 |
| **all** | 46 · 7 · 0 · 4 | 56 · 1 · 0 · 0 |

**TD-1569** (44 key rows; handled · silent · wrongly handled · not applicable)

| situation | replay | original |
|---|---|---|
| concurrency (hard) | 2 · 0 · 0 · 0 | 2 · 0 · 0 · 0 |
| failure (hard) | 3 · 0 · 0 · 0 | 3 · 0 · 0 · 0 |
| interaction (hard) | 5 · 1 · 0 · 0 | 6 · 0 · 0 · 0 |
| when (hard) | 2 · 0 · 0 · 0 | 2 · 0 · 0 · 0 |
| who (hard) | 3 · 0 · 0 · 0 | 3 · 0 · 0 · 0 |
| display | 6 · 0 · 0 · 0 | 6 · 0 · 0 · 0 |
| scope | 8 · 1 · 0 · 0 | 9 · 0 · 0 · 0 |
| shape | 7 · 0 · 0 · 0 | 7 · 0 · 0 · 0 |
| which | 2 · 0 · 0 · 0 | 2 · 0 · 0 · 0 |
| (none) | 0 · 0 · 0 · 4 | 4 · 0 · 0 · 0 |
| **all** | 38 · 2 · 0 · 4 | 44 · 0 · 0 · 0 |

**Cost** (each run's transcripts and each original's captured turns, read by the cost model's `extract.py` and
priced at `sessionorc.seats.WEIGHTS`; it decides nothing):

| design | replay | of it: designer · Sonnet · Fable | original | of it: designer · Sonnet · Fable |
|---|---|---|---|---|
| TD-1557 | $59.49, 6 rounds (cap) | $15.70 · $10.80 · $33.00 | $35.37, rounds 1–3 | $12.74 · $7.88 · $14.75 |
| TD-1569 | $40.93, 4 rounds | $12.59 · $10.12 · $18.22 | $39.56, rounds 1–4 | $15.71 · $7.70 · $16.14 |

TD-1557's replay ran to the wide class's cap of six rounds and ended with one build-changing fix no review had read
(F101); its original's key spans three. TD-1569's replay ran four rounds, as its original's key does.

**The audits.** Every flag of both scored runs was ruled harmless before scoring. TD-1557 run 1 had 229 flags:
`ao` named in heredocs and quoted grep patterns that the audit's splitter cuts at `|` (no stub call logged), the
replay's own diff written to `/tmp` and read back, the pinned agent-cadence tree, and pattern fragments. TD-1569 run
1 had 769 flags: 553 `/tmp` files the replay itself wrote from its own commits and read back (its repository has no
remote), 152 `ao` words in heredocs (no stub call logged), `$TMPDIR` files, and pattern fragments. The rulings are in
TD-1774's Log, the audits in each `audit.txt`.

**TD-1470 was stopped.** Its replay ended twice with no result on an API connection failure, neither run the replay's
doing: run 1 (2026-11-15 about 01:25Z) after about 15 minutes on *Connection lost mid-response*, run 2 (02:04Z) after
110 turns on *Connection refused*. Both audits are clean of anything but words in heredocs and prompts, relative
paths and `$TMPDIR` files (`replays/TD-1470/run1-audit.txt`, `run2-audit.txt`). Two such voids stop a design, so
TD-1470 is not scored, and its reading over rounds 1 to 4 (rounds 1 to 8 beside it) is not made. TD-1867 records the
stop. **The gap:** the lines rest on two designs' 101 rows instead of three keys' 182, and the trial has no replay of a
design that ran past six rounds.

**What the replays found that the originals did not.** The replays' review records raise 49 build-changing findings
(TD-1557 23, TD-1569 26). One Sonnet reader per design marked each against `origin/main`'s design at `d7f79b7`: none
is still in the live design (TD-1569 26 not live; TD-1557 20 not live, 3 unsure: F8, F21 and F81, three things
§4.4 *Decide* leaves unsaid about the answers a form hands over), so nothing is filed. The readers' marks are each
replay's `live.jsonl`.

**The scorers.** Two Sonnet 5.5 scorers marked each design, the replay and the original mixed under random labels;
a Fable 5.2 third read the rows they marked differently and every not-applicable-absent mark (TD-1557: 11 replay rows
and 2 original rows; TD-1569: 8 and 1). Twice a scorer of an original took a shortcut against the prompt's *judge every row*: TD-1557's scorer b wrote one
reason for 50 rows, and TD-1569's scorer b wrote all 44 rows in one pass without reading the tree. Each was set aside
and run again, and only the second run is committed.

**The leaks the trial accepts**, each a bias toward the new shape: the checklist is drawn from the analysis's 41
records, some later than the replays' bases; the trial commit's designer brief holds lessons from designs after every
base, the other replays' among them; and a replay files its builds as TD-9001 up where its original used the real
ids, which a scorer could read as a sign of which design it holds. **The models are today's**: the replays' designer
was Opus 5.5 and their reviewers Sonnet 5.5 and Fable 5.2, the same models the originals ran with, on 2026-11-13 to
2026-11-15.
