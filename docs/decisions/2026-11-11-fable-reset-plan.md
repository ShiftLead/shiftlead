# Spending the two Fable resets well (2026-11-11)

**Status:** a draft for discussion with Paul, written from the session `fabplan`. Each item says whether it
is *agreed* (Paul has said yes), *proposed* (on the table) or *withdrawn*. The plan's own work is held as
TD-1711; the entries it names were in the ledger already. Paul called the shape right on 2026-11-11.
The evidence is [the design review findings analysis](2026-11-11-design-review-findings.md).

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
- On the evening of 2026-11-11, 39 open entries name a decision of Paul's in their `Blocked by` (20 of them
  wait on nothing else) and 10 are pickable.

## Timing

Press a reset at the moment the Fable limit is hit, with work queued that needs Fable, and early enough in
the week that a second allotment can be used before the window ends. Never before the limit (the rest is
forfeited) and never in a week's last two days. A reset doubles what the sessions can do that week, not
what Paul can decide, so the decisions its work waits on are cleared first.

## A cheaper way to design

The aim is the same designs, as sound, for fewer Fable tokens. The saving is the fix loop: today the Fable
designer applies every round's fixes; here a Sonnet seat does, and Fable is asked only about the hard
findings. A script does what needs no model. The review rounds keep their cap and their stop rule (the
designs that ran past the cap, up to 12 rounds, did so on bought rounds and held revisions).

| Step | Who | What | Status |
|---|---|---|---|
| 1. Before drafting | a script, a Sonnet agent | The other design text that names the mechanism; the facts of the code the design touches | proposed |
| 2. The draft | Fable (the designer seat) | Writes the design against a short checklist of the situations designs here miss, and checks every function, flag or record it names as it writes | proposed |
| 3. The pre-review script | called by the author | Must pass before any reviewer reads. Largest first: one statement in two places drifted apart, a path or symbol that should exist, entry fields out of step, counts, ids, section references | **agreed**; who supplies the terms to look for is open |
| 4. The rounds | reviewers, as today | Each finding is raised with the situation it is about. The fact-check reads the code behind behaviour claims, the script having taken the rest | proposed |
| 5. The fixes | Sonnet (a second seat) | Collates a round's findings, applies the fixes, checks any code a fix names, reruns the script | proposed |
| 6. The hard findings | Fable, asked by the Sonnet seat | Findings about two actors at once, interaction with another rule, restarts, endings, timing, actors and error paths go back to Fable as one narrow question each | proposed |

**Why this shape.** The 3,120 findings divide by what was wrong:

| Group | share | only a design review or live use would catch |
|---|---|---|
| wording, naming, pointers, tests, bookkeeping | 23% | 4% |
| a false claim about what exists | 13% | 10% |
| detail: shape, scope, which one, display, first run, another node, proof | 37% | 11% |
| the hard situations of step 6 | 25% | 34% |
| could not tell | 2% | |

The builder would meet 84% of the detail group. Across the groups, 16% of findings are a script's to catch.
Of the false claims, two thirds (263 of 394) are found after round 1 and at least 177 are in text a fix
had changed, since a later round's fact-check reads only what changed. A quarter of all findings follow
from an earlier fix. Designs already get about seven fact-checks each.

**Two seats, not one seat that changes model** (Paul, 2026-11-11). The Sonnet seat starts from the design's
branch and its review record, which are files, so it needs nothing from the Fable session's context; a
second seat is a fresh context by construction, and `ao spend` shows each seat's cost with no new measure.
Changing model inside one session would discard the prompt cache anyway.

**The checklist** is distilled from the 1,949 general questions the second pass wrote, weighted to the hard
situations. Not yet written.

## The trial

1. **Replay three past designs** with the new shape, from the commit before each design's PR, in a worktree
   that is never merged: one short, one of median length, one long (a claims design such as TD-1470).
   Their review records are the answer key: for each hard finding the old rounds raised, does the new
   design handle it? That measures effectiveness, which new designs cannot, and pairing removes the spread
   between designs (1 to 12 rounds). The cost is about three designs' tokens for output that is thrown away.
2. **Then the next real designs** run the new shape, read against the baseline: 3.6 findings only a design
   review would catch for each design in round 1 and 1.4 in round 2, a median of 4 rounds, 25 to 29% of
   later findings following from a fix, and each seat's spend for each design.
3. **What would stop it:** more hard findings left unhandled in the replays than the old rounds left, or a
   higher share of findings following from a fix.

Wanted for step 2: spend for each design (`ao spend --entries` lists a day's finished entries with their
cost; whether that is a design's whole cost across days is to be checked), and whether a PR-review finding
or a fix after a merge traces to its design, which nothing records.

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

- **Reset 1** is pressed at the first Fable-limit hit after the new design shape has passed its trial, so
  the doubled week is spent at the better rate: the messaging review's designs and the efficiency builds.
  A limit hit before then is waited out; the resets lapse in March, not sooner.
- **Reset 2** goes to Paul's other projects, when the cost of a merged PR is measurably down and the target
  repo has a team, a full lane and its decisions cleared; no later than mid-January.

## The order

1. TD-1589 (through TD-1696) and the Fable reading. 2. The pre-review script. 3. The checklist. 4. The second seat and the
hand-back. 5. The three replays. 6. Real designs on the new shape. 7. Reset 1.

## Open

- Whether the pre-review script is given its terms by the author or parses the PR.
- Who reviews: Fable then Sonnet as today, or Sonnet alone. In tokens for each finding only a design review
  would catch Fable is about 16% cheaper, and for each substantive finding about 10% dearer; what Fable
  finds that Sonnet would miss is not measured.
- How the Sonnet seat hands a finding back, and how the Fable seat answers without reloading the design.
- Whether steps 1 and 2 need the Sonnet fact pack, or the write-time check is enough.

## Withdrawn

- *A cap of two design rounds.* Rounds 3 and 4 each still raise, for each design that reaches them, about
  0.8 and 0.7 findings only a design review would catch; a round costs the designer at most about $10 (an
  estimate: the designer session's $1,770 over about 175 rounds, its other work included), and a flaw that
  escapes costs at least a fix PR and, live, far more.
- *Fable does the design reviews* (it costs far more for each review; Paul).
- *Every minor finding goes to the builder* (two thirds of the findings labelled minor are substantive).
- *More fact-check rounds* (there are about seven for each design, and close to half of the false claims
  are in text a fix changed after the last one read it).
