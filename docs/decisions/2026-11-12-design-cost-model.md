# The design cost model: what applying a round's fixes costs the designer (2026-11-12)

**Status:** a measurement, for TD-1721 and TD-1722. It decides nothing. TD-1764 filed it because the cheaper way
to design (TD-1711, [the plan](2026-11-11-fable-reset-plan.md)) moves the applying of a review round's fixes
from the designer to a Sonnet seat, design-coord (TD-1721). Whether that saves anything depends on what share
of the designer's spend goes to applying fixes, and nobody had that number.

**The answer.** Over five designs, applying fixes is **51% of the designer's own spend** pooled ($45.20 of
$88.82). Per design it is 42% to 57%. That is above the quarter line TD-1764 proposed, so TD-1721 is free to start.

**Three facts the plan did not assume:**

1. **The designer is not Fable.** Every designer turn on kmaster since 2026-10-14, about 22,000 of them, ran on
   `claude-opus-5-5`, but for two `<synthetic>` lines. Fable (`claude-fable-5-1`, then `-5-2`) runs only as a design *reviewer*.
2. **The reviewers cost twice what the designer does.** The five designs' reviewers spent $173.85, against
   the designer's $88.82. Fable reviews alone were $118.04 of that. The designer's fix turns are 17% of a
   design's whole spend.
3. **Most of the designer's cost is cache reads.** Opus 5.5's cache-read weight ($0.20 per million tokens)
   is Sonnet's. Moving the same fix turns to a fresh Sonnet context therefore saves only what the smaller
   context saves: 14% at a 60k-token start ($38.78 against $45.20). It costs more than it saves once the
   seat needs about 70k tokens to hold the design and its review record (step 4 below).

What would cut a design's spend most is the Fable review rounds and the context the designer carries, not
the model that applies the fixes. That is for TD-1721's designer and TD-1722's trial to weigh.

**The data is kept beside this file**, in [`2026-11-12-design-cost-model/`](2026-11-12-design-cost-model/):
- `extract.py` reads the designer's transcripts, one row per API response;
- `tables.py select` picks the five designs' turns and phases them into `turns.csv`;
- `tables.py` prints every table below from `turns.csv` alone.

`turns.csv` holds tokens, times, models, branches and each tool call's *class* (`work`, `edit`, `book`, `mail`,
`agent`). It holds no transcript text and no command text.

## Method

**The sample** (step 1). Five designs with a `Source: rounds` review record whose rounds have ended, none of
TD-1557, TD-1569 or TD-1470:

| design | rounds | length |
|---|---|---|
| TD-1436 | 3 | short |
| TD-1650 | 4 | median |
| TD-1443 | 4 | median |
| TD-1434 | 5 | long |
| TD-1543 | 11 | long |

Short means three rounds or fewer, median four, long five or more. Four rounds is the most common count among
the `rounds` records, and the cap.

**Where each design's turns are** (step 2). Claude Code writes `gitBranch` on every transcript line, and every
design ran on branches of its own. Those branches come from each design's merged PRs
(`gh pr list --search "TD-n in:title"`):

| design | branches |
|---|---|
| TD-1436 | `td1436-answer-latency` |
| TD-1650 | `td1650-design` |
| TD-1443 | `td-1443-design` |
| TD-1434 | `td1434-seat-mode-flip`, `td1434-round5` (TD-1454) |
| TD-1543 | `td1543-design-have-a-session-do-it`, `td-1676-round9`, `td1702-round10`, `td1708-round11` |

The designer's transcripts are under `~/.claude/projects/-home-kmaster-shiftlead--claude-worktrees-designer-ao-1/`,
and all of them still exist. A design's turns are:
- the main-thread turns on its branches, in every session that has any;
- in each such session, the turns on the worktree's own branch (`HEAD`, `designer-ao-1`, `main`) next to them:
  back from the design's first turn to the session's last turn on another branch, and between its turns.

A design may span several sessions (TD-1543: nine). The reviewers are the subagents whose first turn falls in a
design session's window. Their spend is counted apart from the designer's.

**A turn** is one API response, keyed by the message id. Claude Code writes one line per content block, all with
the same usage; one is kept. Its tokens are the four kinds the response's `usage` gives: input, cache read,
cache write and output. Its context is their sum without the output.

**Phases.** A reviewer's report reaching the designer is an event in the transcript:
- a background Agent's `task-notification` whose summary names an Agent;
- a subagent's hand-back;
- a foreground Agent call's result.

Over each design's turns in time order:
- **sending and waiting on reviews**: a turn that starts a reviewer (an Agent call), and every turn after it
  until the next report;
- **applying fixes**: every turn from a report to the next reviewer started;
- **drafting**: every turn before the first reviewer is started;
- **bookkeeping** overrides drafting, applying and the waiting turns, never a turn that starts a reviewer: a turn whose every tool call is the ledger, the board, the review record,
  the history, or the PR and its merge (`ledger.py`, `board_edit`, `docs/reviews/`, `gh`, `git add/commit/push`,
  `ao progress`, `ao td`, `ao pr`, `check_cadence`, `precheck`, `forge.py`). Mixed with mail, it is still bookkeeping;
- **other** overrides them the same way: a turn whose every call is mail or a record read (`ao inbox`, `ao msg`,
  `ao doing`, `ao status`, `ao repo`, the attention board).

The designer edits mostly through scripts run in Bash, not the Edit tool, so a phase is read from the review
cycle, not from which tool a turn used.

**Cost.** `ao spend`'s default weights (`sessionorc.seats.WEIGHTS`, as of 2026-10-17), $ per million tokens,
the longest model prefix winning. This home's settings set no override.

**Checked against `ao spend --entries`** (step 3). Designer and reviewers together, from `turns.csv`, set beside
the design's entries in `ao spend --entries --window week` for the weeks of 2026-11-02 and 2026-11-09:

| design | turns.csv, designer + reviewers | ao spend --entries |
|---|---|---|
| TD-1436 | $19.31 | $19.03 |
| TD-1650 | $23.31 | $22.53 |
| TD-1443 | $27.72 | $27.66 |
| TD-1434 | $34.71 | $34.32 (TD-1434 $24.75 + TD-1454 $9.57) |
| TD-1543 | $157.62 | $146.11 (TD-1543 $114 + TD-1676 $15.71 + TD-1708 $9.16 + TD-1702 $7.24) |

The first four agree within 4%. TD-1543's window takes in about 8% more than its entries. Its nine sessions
also held other claims, whose reviewers fall inside the window.

**What it leaves out.** Turns a design spent on a branch not its own are not counted, for example a ledger
fix made from another design's branch. Drafting done before a design's branch was cut, in an earlier session,
is not counted either. The low drafting figures for TD-1443 and TD-1650 (2 and 8 turns) are what the
transcripts show: their reviewers were started soon after the branch was cut.

## The designer's spend, by phase

| design | designer $ | drafting | applying fixes | reviews | bookkeeping | other |
|---|---|---|---|---|---|---|
| TD-1436 | 6.94 | 19% | **42%** | 22% | 8% | 10% |
| TD-1650 | 8.78 | 6% | **57%** | 21% | 6% | 10% |
| TD-1443 | 12.83 | 1% | **56%** | 23% | 9% | 12% |
| TD-1434 | 13.09 | 12% | **43%** | 26% | 17% | 2% |
| TD-1543 | 47.18 | 5% | **52%** | 25% | 8% | 10% |
| pooled | 88.82 | 7% | **51%** | 24% | 9% | 9% |

Pooled, applying fixes is 613 of the designer's 1,297 turns. The full table, with each phase's turns, its
tokens by kind and its median context, is `tables.py`'s first. The median context of an applying turn is 110k
tokens (TD-1436) to 375k (TD-1443).

A designer session carries the design before it. TD-1650's session came straight from TD-1567 and opened at
273k tokens. TD-1443's came from TD-1453.

**The reviewers** (Agent subagents), pooled: Fable 5.1 $32.60, Fable 5.2 $85.44, Sonnet 5.5 $52.99,
Opus 5.5 $2.82, $173.85 in all. Per design: TD-1436 $12.37, TD-1650 $14.53, TD-1443 $14.89, TD-1434 $21.62,
TD-1543 $110.44.

## Step 4: two estimates

**The same fix turns on Sonnet, from a fresh context.**

Assumptions:
- A fix run is the turns from one report to the next reviewer started. The five designs have 108 of them.
- A fresh Sonnet seat starts each run from BASE tokens, written to the cache once. BASE holds its system
  prompt and tools, the design's sections and the review record.
- The seat's context grows over the run as the designer's did.
- It takes the same turns and writes the same output.

| BASE tokens | as run (Opus 5.5) | on Sonnet, fresh | ratio |
|---|---|---|---|
| 40,000 | $45.20 | $27.69 | 0.61 |
| 60,000 | $45.20 | $38.78 | 0.86 |
| 100,000 | $45.20 | $60.97 | 1.35 |
| 150,000 | $45.20 | $88.70 | 1.96 |

Why 60k is the middle figure:
- a session's start is about 25k tokens;
- the review records are 2.4k to 10k tokens;
- the design PRs added 149 to 602 lines to the files they touched.

The saving holds only while the fresh seat's context stays well under the designer's. At Opus 5.5's weights,
the model swap itself saves nothing on cache reads. It halves the input, output and cache-write weights, but
those are two fifths of the fix turns' cost ($17.95 of $45.20; cache reads are the other $27.25).

**One question to Fable.**

Assumptions:
- The question is a span, its findings and the design paragraphs they cite, about 12k tokens. That is an
  average round's findings (about 19 findings at about 170 characters each, less than 1k tokens), plus the span
  and the cited paragraphs.
- The answer is 2k tokens out.

| where | context | $ |
|---|---|---|
| a fresh Fable session (a 25k start + the 12k question, written to the cache) | 37,000 written | 0.84 |
| a Fable session at the designer's median applying context, the question written on top | 204,598 read | 0.39 |

The second row is a price, not an option today: the designer's session is Opus 5.5, not Fable.

## Step 6

Applying fixes is 51% of the designer's spend, pooled over the sample. That is above the quarter line, so TD-1721
is not held on Paul's decision: it is free to start once this entry closes. The three facts above go to TD-1721
and TD-1722 as notes. Those are the designer's to weigh: the designer is Opus 5.5, the reviewers cost twice as
much, and the Sonnet saving depends on context size.
