# Spending the two Fable resets well (2026-11-11)

**Status:** a draft for discussion with Paul, written from the session `fabplan`. Each item says whether it
is *agreed* (Paul has said yes), *proposed* (on the table) or *withdrawn*. The plan's own work is held as
TD-1711; the entries it names were in the ledger already. Paul called the shape right on 2026-11-11.
The evidence is [the design review findings analysis](2026-11-11-design-review-findings.md).

**Review round** (2026-11-11): a Sonnet fact-check (12 findings, 7 of them changing the plan) and a Sonnet
design review (13 build-changing, 5 minor), all applied here except one: a fact-check of only the changed
text by a second reader, which the later rounds' fact-checks and the closing one already are.

## The facts it rests on

- The account has a weekly limit over all models and a separate Fable limit. Paul holds two resets; each
  clears Fable's usage (and takes it out of the week's count), and both lapse in March.
- `ao gate` reads only the all-models week. The Claude Code adapter already parses each model's weekly
  window (`week · Fable`, TD-122), but the gate's reading carries only `week`, so nothing tells a session or
  Paul when the Fable limit is near. TD-1589 says the week's reading itself is often old.
- By `ao spend`, the designer session takes about half of a day's spend and the two grinders about a
  third. Over 2026-11-03 to 11-11 the designer session spent about $1,770 and 3.1B tokens against the
  reviewers' 60M (the two are not shown to count tokens the same way): a design's cost is the author's own
  turns, above all the turns that apply each round's fixes at 140k to 300k tokens of context.
- At 21:39 on 2026-11-11, 27 open entries name a decision of Paul's in their `Blocked by` (19 of them wait
  on nothing else) and 12 are pickable; the counts move within hours as he answers.

## Timing

Press a reset at the moment the Fable limit is hit, with work queued that needs Fable, and early enough in
the week that a second allotment can be used before the window ends. Never before the limit (the rest is
forfeited) and never in a week's last two days. A reset doubles what the sessions can do that week, not
what Paul can decide, so the decisions its work waits on are cleared first.

## A cheaper way to design

The aim is the same designs, as sound, for fewer Fable tokens. The saving is the fix loop: today the Fable
designer applies every round's fixes; here a Sonnet seat does, and Fable is asked only about the hard
findings. A script does what needs no model. The review rounds keep their cap and their stop rule (most
of the designs that ran past the cap, up to 12 rounds, did so on bought rounds and held revisions).

| Step | Who | What | Status |
|---|---|---|---|
| 1. The draft | Fable (the designer seat) | Writes the design against a short checklist of the situations designs here miss. Beside it, two blocks the script reads: each claim about what code does with the file and line it rests on, and each rule the design states in more than one place | proposed |
| 2. The pre-review script | called by the author | Checks that every path, symbol, id and section the design names exists, that the claims block is filled, that the places a declared rule is stated agree, and the entry's fields and counts. No reviewer is sent a design without the script's pass line for that commit | the script **agreed**; that the author supplies the terms proposed (Paul's lean) |
| 3. The rounds | reviewers, as today | Each finding is raised with the situation it is about. The fact-check samples the claims block and reads the code behind it | proposed |
| 4. The fixes | Sonnet (a second seat, `design-coord`) | Holds the design's branch from the handoff and is its only writer. Groups a round's findings by the text they touch, applies the fixes to spans with no hard finding, extends the two blocks for what a fix changes, reruns the script | proposed |
| 5. The hard findings | Fable, asked by the Sonnet seat | A span with any finding about two actors at once, interaction with another rule, restarts, endings, timing, actors or error paths goes to Fable whole: the findings, the span and the rules they cite. Fable returns the replacement text or a decision; the Sonnet seat applies it. These are the reviewers' situations concurrency, interaction, restart, ends, when, who and failure. In doubt, or on *other*, the Sonnet seat sends it up; it never sends one down. The next round is not sent until every question is answered | proposed |
| 6. The last read | Fable | Reads the whole design once after the last fix, before the closing fact-check, for coherence | proposed |

**Why this shape.** The 3,120 findings divide by what was wrong:

| Group | share | only a design review or live use would catch |
|---|---|---|
| wording, naming, pointers, tests, bookkeeping | 23% | 4% |
| a false claim about what exists | 13% | 10% |
| detail: shape, scope, which one, display, first run, another node, proof | 37% | 11% |
| the hard situations of step 5 | 25% | 34% |
| could not tell | 2% | |

The builder would meet 84% of the detail group. Across the groups, 16% of findings are a script's to catch.
Of the false claims, two thirds (263 of 394) are found after round 1 and at least 177 are in text a fix
had changed, since a later round's fact-check reads only what changed. A quarter of all findings follow
from an earlier fix. Designs already get about seven fact-checks each.

**Two seats, not one seat that changes model** (Paul, 2026-11-11). The second seat is `design-coord`
(Paul's names: design-pm or design-coord; *coord* is taken here because the org already has a manager
seat). It starts from the design's
branch and its review record, which are files, so it needs nothing from the Fable session's context; a
second seat is a fresh context by construction, and `ao spend` shows each seat's cost with no new measure.
Changing model inside one session would discard the prompt cache anyway.

**Where the rule lives.** The rounds are agent-cadence's (`cadence.md` §4.8), which shiftlead pins and does
not edit. The new shape keeps what §4.8 fixes (the fact-checks, the cap, the stop rule, the review record,
the end-of-rounds item) and changes what it leaves open: who applies a round's fixes, and what runs before
a reviewer is sent. A repo's own AGENTS.md and briefs come before `cadence.md`, and the designer's brief
already adds this repo's rule that a round is a Fable review then a Sonnet one. So for the trial the shape
is written in shiftlead alone: the designer's and `design-coord`'s briefs (`docs/briefs/`, a held path),
the team's definition and one script. The designer stays the design's author of record: it states the
class, and files the builds when the rounds end. Only if the shape passes its trial does it go upstream to
agent-cadence as a proposal, with shiftlead's numbers. The plan's class is therefore in-repo until then.

**The checklist** is distilled from the 1,949 general questions the second pass wrote, weighted to the hard
situations, at most fifteen questions, kept in the designer's brief (a held path). Not yet written.

## The trial

**Before it:** the cost model. From a sample of five past designs' transcripts, the share of the designer's
spend that is applying fixes, and by `ao spend --entries` or an entry-linked measure, spend for each design
across days. Without these the saving is an aim, not a result: it is the price difference on the tokens
moved to Sonnet, less Fable's questions, the last read and any extra rounds.

1. **Replay three past designs** with the new shape: one short, one of median length, one long, chosen by
   Paul before the checklist is written, from designs whose rounds ended after the analysis was cut
   (commit `df866eeb8`), so the checklist was not drawn from their findings. Each runs from the parent of
   its design PR's first commit, in a clone cut at that commit and never merged, with the seats' memory
   directory pointed at a copy from that commit; the transcripts are searched afterwards for any ref past it. The old review record is the answer key, kept outside
   the worktree. A separate Sonnet reader scores it, not knowing which design is the new one: for each old
   finding about the problem itself (findings about the old design's own mechanism are left out), is it
   handled, left silent or handled wrongly? The replay also runs its own rounds, and what those raise is
   counted, as is every fix the Sonnet seat applied to a finding the key calls hard.
2. **Then the next real designs** run the new shape, compared like with like: only findings a design
   review alone would catch, by round, under the same cap, set against past designs of the same subsystem;
   the share of findings following from a fix; each seat's spend for each design.
3. **What the replays can show** is only that the change is clearly bad: three designs cannot show it is
   good. Paul decides, on thresholds set before they run (proposed: stop if any replay leaves more than one
   in ten of the key's problem findings silent or wrongly handled). Cost is not a replay's stop condition:
   one design that costs more says little. The real designs are the test. Cost is read over the first ten
   of them together, as the total against what those designs would have cost and as how many of the ten
   came out cheaper (Paul, 2026-11-11: six or seven of ten cheaper may still be worth it), and the shape
   *has passed its trial* when Paul says so on those two numbers and the findings measures.

Nothing records whether a PR-review finding or a fix after a merge traces to its design; that is the
measure of what a missed flaw costs and is wanted for step 2.

**What is accepted.** The reviewers still raise every finding; what changes is who fixes it. About 6% of
all findings are outside the hard situations and yet only a design review would catch them (195 of 3,120:
123 detail, 41 false claims, 31 wording and the like), and those would now be fixed by Sonnet without Fable. Three replays test the whole package (checklist, script, second seat), not each part.

## The rest of the sharpening

- **The usage reading.** TD-1589's wait was lifted by Paul and its first two slices are live; its live
  check does not hold yet and it now waits on TD-1696. *Agreed.* Carrying the Fable window the adapter
  already parses into the gate's reading is *proposed*.
- **The prompt-cache builds** from TD-1551: TD-1664 is built (#3491); TD-1669 is held on Paul's decision.
- **What each role is made to read.** The design is about 665k tokens in 30 files, six sections of 36k to
  101k tokens each; one read stays in the context of every later turn. A reader that prints one heading, or
  smaller files, is the candidate. What sessions read each turn is not yet measured. *Proposed.*
- **The messaging system, reviewed whole**, with Paul, from evidence: the mail corpus (asks never answered,
  steers refused, doorbells missed, tokens for each delivered message) and the memory files that exist to
  work around `ao msg` and `ao inbox`. A ranked findings report first; designs after Paul agrees the shape.
  *Proposed.*

## The two resets

A reset is only ever pressed at a limit hit. Until the Fable window reaches the gate's reading, Paul sees
the hit on the account page.

- **Reset 1** is pressed at the first Fable-limit hit after the new design shape has passed its trial, so
  the doubled week is spent at the better rate: the messaging review's designs and the efficiency builds.
  If the trial has not passed by mid-December (proposed), the next hit is pressed anyway, on the shape as
  it then stands.
- **Reset 2** goes to Paul's other projects, at a limit hit once the target repo has a team, a full lane
  and its decisions cleared; from mid-January (proposed) the next hit is pressed whatever the state.

## The order

Proposed, as the trial is.

1. The cost model and spend for each design. 2. The pre-review script and the two blocks it reads. 3. The
checklist. 4. The second seat and the hand-back. 5. The three replays. 6. Real designs on the new shape.
7. Reset 1. Beside these and not waiting on them: TD-1589 (through TD-1696) and the Fable window in the
gate's reading.

## Open

- Who reviews: Fable then Sonnet as today, or Sonnet alone. In tokens for each finding only a design review
  would catch Fable is about 14% cheaper, and for each substantive finding about 13% dearer; both figures
  are confounded, since the two read the same text in turn and the first takes what both would find.
- The thresholds of the trial, and the latest date for reset 1 (both proposed above; Paul's).
- How large a question to Fable may be, and what the last read costs; the trial measures both.

## Withdrawn

- *A Sonnet fact pack before drafting.* The claims block and the script cover it.
- *A cap of two design rounds.* Rounds 3 and 4 each still raise, for each design that reaches them, about
  0.8 and 0.7 findings only a design review would catch; a round costs the designer at most about $10 (an
  estimate: the designer session's $1,770 over about 175 rounds, its other work included, and a few of
  those rounds dated before the spend's nine days), and a flaw that
  escapes costs at least a fix PR and, live, far more.
- *Fable does the design reviews* (it costs far more for each review; Paul).
- *Every minor finding goes to the builder* (two thirds of the findings labelled minor are substantive).
- *More fact-check rounds* (there are about seven for each design, and close to half of the false claims
  are in text a fix changed after the last one read it).
