# The originals' turns (TD-1773)

The three replayed designs' turns, captured on 2026-11-13 before their transcripts are pruned (about 30 days),
by the cost model's `extract.py` over the designer's transcript directory and its Method step 2
([the cost model](../../2026-11-12-design-cost-model.md), `tables.py select`), through `capture.py` here.
`turns.csv` holds the rows in the cost model's columns; `python capture.py` prints the counts below from it.

| design | key's rounds | design PRs (branch) | original designer's main-thread turns | reviewer turns |
|---|---|---|---|---|
| TD-1557 | 1–3 | #3511 (`td1557-design`) | 195 | 275 |
| TD-1569 | 1–4 | #3465 (`td-1569-design`) | 173 | 241 |
| TD-1470 | 1–8 | #3107, #3152, #3189, #3226, #3246 | 417 | 442 |

**Main-thread turns** are the designer session's own rows, without the subagent rows and the reports reaching
it: its turns on the design's branches, with the launch-branch turns step 2 counts beside them (`HEAD`: 23 of
TD-1569's, 65 of TD-1470's). They are the figure `run --max-turns` is set from, at twice it (design §4.9c *Its
run*), which TD-1774 records before the first run.

**TD-1470's gap.** No transcript line on this machine carries round 7's branch (`td1534-td1470-round7`, #3226),
in the designer's directory or any other, so round 7's turns are not in the count: 129 on `td1470-stuck-work`
(rounds 1–4), 65 on round 5's branch, 70 on round 6's, 88 on round 8's, and the 65 launch-branch turns. Its
Hold revision (TD-1571, #3330, rounds 9 on) is outside the key and is left out.
