# Spending the two Fable resets well (2026-11-11)

**Status:** the plan Paul and the session `fabplan` reached on 2026-11-11. Paul called the shape right, then
agreed to shrink this document to its decisions and split its mechanisms into three designs (TD-1720,
TD-1721, TD-1722, parts of TD-1711, each with its own review rounds). Items are *agreed* (Paul has said
yes) or *proposed*. The evidence is [the design review findings analysis](2026-11-11-design-review-findings.md).

**Its own review** (record: `docs/reviews/TD-1711.md`): two rounds, each a Sonnet fact-check and a Sonnet
design review. Round 2 raised nine build-changing findings, four of them reopening round 1's fixes to the
trial's protocol. That is a recurring topic, and Paul's answer to it was this split: the open findings go
to the three designs as questions they must settle.

## The facts it rests on

- The account has a weekly limit over all models and a separate Fable limit. Paul holds two resets; each
  clears Fable's usage (and takes it out of the week's count), and both lapse in March.
- The Claude Code adapter already parses each model's weekly window (`week · Fable`), but the gate's
  reading today carries only `week`, so nothing tells a session or Paul when the Fable limit is near.
- By `ao spend`, the designer session is about half of a day's spend and the two grinders about a third.
  Over 2026-11-03 to 11-11 the designer session spent about $1,770 and 3.1B tokens against the reviewers'
  60M (not shown to be counted the same way): a design's cost is the author's own turns, above all the
  turns that apply each round's fixes at 140k to 300k tokens of context.
- Of 3,120 review findings: 23% are wording, naming, pointers, tests or bookkeeping; 13% a false claim
  about what exists; 37% detail (shape, scope, which one, display and the like), 84% of which a builder
  would meet anyway; 25% the hard situations (two actors at once, interaction with another rule, restarts,
  endings, timing, actors, error paths), a third of which only a design review or live use would catch.
  16% are a script's to catch. A quarter follow from an earlier fix.

## Timing and the two resets

A reset is pressed only at a Fable-limit hit, never before (the rest is forfeited), and not in a week's
last two days. It doubles what the sessions can do that week, not what Paul can decide, so the decisions
its work waits on are cleared first. Until the Fable window reaches the gate's reading, Paul sees the hit
on the account page.

- **Reset 1** goes to shiftlead: the first hit after the new design shape has passed its trial. If the trial
  has not passed by mid-December, the next hit outside a week's last two days is pressed anyway, on the
  shape as it then stands. *Proposed.*
- **Reset 2** goes to Paul's other projects: a hit once the target repo has a team, a full lane and its
  decisions cleared; from mid-January the next hit is pressed whatever the state. *Proposed.*

## A cheaper way to design

The aim is the same designs, as sound, for fewer Fable tokens. Today the Fable designer writes the design
and applies every round's fixes. In the new shape:

1. **Fable drafts**, against a short checklist of the situations designs here miss.
2. **A script runs before any reviewer reads** (*agreed*), on what the author declares: the claims the
   design makes about code, and the rules it states in more than one place.
3. **The review rounds run as today**: the fact-checks, the cap, the stop rule, the record and the
   end-of-rounds item are agent-cadence's and are kept. Reviewers name the situation each finding is about.
4. **A second, Sonnet seat, `design-coord`, carries the rounds** (*two seats, not a model switch*: agreed):
   it is the branch's only writer after the draft and applies the fixes.
5. **Fable is asked only about the hard situations**, and reads the whole design once at the end.

**Where the rule lives.** The new shape changes only what `cadence.md` §4.8 leaves open: who applies a
round's fixes and what runs before a reviewer is sent. A repo's AGENTS.md and briefs come before
`cadence.md`, so for the trial the shape is written in shiftlead alone (the designer's and `design-coord`'s
briefs, the team's definition, one script), with the designer still the design's author of record. It goes
upstream to agent-cadence, as a proposal with shiftlead's numbers, only if it passes its trial.

## The three designs

Each is a part of TD-1711 and settles the questions listed; the findings they come from are in the review
record by id.

**TD-1720: what the author prepares before a review.** The checklist, the two declared blocks and the
script.
- The checklist: at most fifteen questions, weighted to the hard situations, drawn from
  `patterns.csv`'s questions, kept in the designer's brief; and which records it may not be drawn from (the
  replays', TD-1722).
- The claims block (each claim about what code does, with the file and line it rests on) and the
  repeated-rules block: who writes them, when a fix extends them, what the fact-check does with them.
- The script's checks, largest first: a declared rule's statements agree, paths and symbols exist, entry
  fields, counts, ids, section references. Whether the author supplies the terms (*Paul's lean*).
- The gate: no reviewer is sent a design without the script's pass line for that commit; what happens when
  the script cannot pass (a path that rightly does not exist yet, a false alarm).
- Which of the 510 script-catchable findings each check would have caught, and what `ledger.py --check`
  and the doc-bound tests catch already.

**TD-1721: `design-coord`, the seat that carries the rounds.**
- The handoff: the event at which the branch passes from the designer to `design-coord`, and what the
  designer does afterwards.
- One writer: `design-coord` holds the branch; Fable returns text or a decision, which `design-coord`
  applies. What happens if either seat ends mid-round.
- Routing: findings grouped by the text they touch; a span with any finding about concurrency, interaction,
  restart, ends, when, who or failure (or *other*, or in doubt) goes to Fable whole, with the rules it
  cites; never sent down. How every one of the reviewers' situation names routes, multi-node among them.
  Reviewers' tags will be wrong about one time in nine.
- Fable's side: a fresh session for each question or the designer's own, how large a question may be, and
  what each costs. The saving depends on this.
- The last read: what happens when it finds something, and how it ends.
- Whether any agent-cadence script, not only its prose, assumes one session ran the rounds.

**TD-1722: the trial and its measures.**
- The cost model first: from a sample of past designs' transcripts, the share of the designer's spend that
  is applying fixes; and spend for each design across days (`ao spend --entries` lists a day's finished
  entries with their cost).
- Three replays of past designs. Paul chooses them, before the checklist is written, from designs **critical
  to how shiftlead works** (so that anything new a replay finds is worth having) and whose findings the
  checklist is not drawn from; whether they may be among the cost model's sample. Each runs cut off from what came after it: later commits, review records,
  history and memory.
- How a replay is scored: what text, against what, by whom, blind to what; which old findings count; the
  denominator. Replays can show only that the change is clearly bad (*proposed*: more than one in ten of
  the problem findings left silent or wrongly handled).
- The first ten real designs on the new shape: how their findings are labelled so they compare with the
  baseline, and the pass test. Cost is read over the ten together, as the total and as how many came out
  cheaper (*Paul: six or seven of ten cheaper may still be worth it*). Paul decides.
- What is accepted: about 6% of findings are outside the hard situations and yet only a design review would
  catch them; those are fixed by Sonnet without Fable. Reviewers still raise every finding.
- Wanted, and recorded nowhere today: whether a PR-review finding or a fix after a merge traces to its design.

## The order

*Proposed.* TD-1722's cost model; TD-1720; TD-1721; TD-1722's replays; real designs on the new shape;
reset 1. Beside these and not waiting on them: the usage reading (TD-1589, through TD-1696, *agreed*) and
the Fable window in the gate's reading.

## The rest of the sharpening

*Proposed*, each to get its own entry when Paul starts it:

- **What each role is made to read.** The design is about 665k tokens in 30 files, six sections of 36k to
  101k tokens; one read stays in the context of every later turn.
- **The messaging system, reviewed whole**, with Paul, from evidence: the mail corpus and the memory files
  that exist to work around `ao msg` and `ao inbox`. A ranked findings report first.
- The prompt-cache builds from TD-1551: TD-1664 is built (#3491); TD-1669 is held on Paul's decision.

## Open

- Who reviews: Fable then Sonnet as today, or Sonnet alone. For each finding only a design review would
  catch Fable is about 14% cheaper in tokens, and for each substantive finding about 13% dearer; both are
  confounded, since the two read the same text in turn.
- The trial's thresholds and the resets' dates, proposed above.

## Withdrawn

- *A cap of two design rounds.* Rounds 3 and 4 each still raise, for each design that reaches them, about
  0.8 and 0.7 findings only a design review would catch; a round costs the designer about $10 (an
  estimate), and a flaw that escapes costs at least a fix PR and, live, far more.
- *Fable does the design reviews* (it costs far more for each review; Paul).
- *Every minor finding goes to the builder* (two thirds of the findings labelled minor are substantive).
- *More fact-check rounds* (about seven for each design already; close to half of the false claims are in
  text a fix changed after the last one read it).
- *A Sonnet fact pack before drafting* (the claims block and the script cover it).
- *The trial's protocol and the hand-back written in this plan* (they are TD-1722's and TD-1721's).
