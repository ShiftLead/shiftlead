# Spending the two Fable resets well (2026-11-11)

**Status:** a draft for discussion with Paul, written from the session `fabplan`. Only the lines under
*Decided* are decided. Nothing here is in the ledger yet.

## The facts it rests on

- The account has a weekly limit over all models and a separate Fable limit. Paul holds two resets; each
  clears Fable's usage (and takes it out of the week's count), and both lapse in March.
- `ao gate` reads only the all-models week (31% on 2026-11-11, about 17 hours into the window). Nothing on
  the home reads the Fable limit, and TD-1589 says the week's reading itself is often old.
- Where the tokens go (`ao spend`, 2026-11-11): the designer session about half, the two grinders about
  two fifths; an average turn carries about 137k tokens of context.
- 28 open entries wait on a decision from Paul; 20 are pickable.

## Timing

Press a reset at the moment the Fable limit is hit, with work queued that needs Fable, and early enough in
the week that a second allotment can be used before the window ends. Never press before the limit (the rest
is forfeited) and never in a week's last two days. Unused allotment is lost at the reset, so the aim is two
full Fable allotments in the week a reset is used.

A reset doubles what the sessions can do in that week, not what Paul can decide. The decisions the reset's
work waits on are cleared before it is pressed.

## The work

**Before the first reset, in ordinary weeks**

1. Fix the usage reading (TD-1589, its wait lifted), and find a way to read the Fable limit.
2. Land the prompt-cache builds already moving (TD-1664, TD-1669, from TD-1551).
3. Build the pre-review script (below).
4. Measure what is not measured: the designer's spend per design and per round, the cost of a build per
   entry, and whether a PR-review finding traces to its design.

**Reset 1: sharpening shiftlead**

- *Token efficiency.* Context per turn (TD-820, fresher sessions, reading handed to subagents), the
  opening every session pays for (the memory index, AGENTS.md, the skills list), which steps need Fable at
  all, and the design rounds, on the evidence of
  [the review findings analysis](2026-11-11-design-review-findings.md).
- *The messaging system, reviewed whole.* An interactive review with Paul that starts from evidence: the
  mail corpus (asks never answered, steers refused, doorbells missed, tokens per delivered message) and the
  memory files that exist to work around `ao msg` and `ao inbox`. A ranked findings report first; designs
  only after Paul agrees the shape.

**Reset 2: Paul's other projects**

Pressed when the cost of a merged PR is measurably down, the target repo has a team, a full lane and its
decisions cleared, and no later than mid-January so it is not kept until it lapses.

**How the work is split between models.** Fable for judgement: authoring designs, reading what findings
mean, the conversation with Paul. Sonnet agents for measurement, fact-checks, corpus mining and mechanical
edits. Using the Fable allotment fully is the aim; spending it on work Sonnet does as well is not.

## Decided

- TD-1589's wait is lifted (Paul, 2026-11-11; #3472).
- The review analysis is kept in the repo (#3480).
- **A pre-review script**: the mechanical sixth of the design findings (stale pointers, entry bookkeeping,
  claims a grep shows false) is checked by a script, not a model. Open within it: whether the author calls
  it with what it knows (the sections, ids and paths the design touches) or it parses the PR. Not yet filed.

## Open

- **Whether better context at drafting means fewer rounds.** The rounds keep their cap and their stop rule
  (below, *Withdrawn*). What is proposed instead is to give the author, before it drafts: the facts of the
  code the design touches, checked by a Sonnet agent (13% of findings are a false claim about what exists);
  the other design text that names the same mechanism, found by a script (4% are contradictions with
  another section, 7% stale pointers); and a checklist of the questions designs here leave open, drawn
  from the 1,273 such findings (41%). Tried on the next few designs and read against the baseline: 3.6
  original design-only findings for each design in round 1, 1.4 in round 2, a median of 4 rounds.
- **What each role is made to read.** The design is about 665k tokens in 30 files, and six sections are
  36k to 101k tokens each (§4.5a 101k, §4.5 86k, §4.4 73k, §6 71k, §4.10 51k): one read of a section stays in
  the context of every later turn. `cadence.md` is about 42k. A reader that prints one heading of a
  section, or smaller files, is the candidate; what the designer and the grinders actually read each turn
  is not yet measured (TD-820 has the designer's totals).
- **Who reviews.** Sonnet and Fable are within about 16% of each other in tokens for each such finding;
  what Fable finds that Sonnet would miss is not measured.
- **Who settles a detail the design leaves open** (41% of findings; about 7% lead to something
  build-changing, clustered in rules about shared state).
- **A narrower *minor*** (only wording, naming, pointers, tests, bookkeeping go to the builder as notes).

## Withdrawn

- *A cap of two design rounds.* Rounds 3 and 4 each still raise, for each design that reaches them, about
  0.8 and 0.7 original findings that only a design review would catch. A round costs the designer at most
  about $9 by `ao spend`'s estimate (about $1,500 over nine days across about 175 rounds, the designer's
  other work included), and a flaw that escapes costs at least a fix PR (about $6) and, live, far more. The
  stop rule already ends the rounds when one raises nothing build-changing.
- *Fable does the design reviews* (it costs far more for each review; Paul, 2026-11-11).
- *Every minor finding goes to the builder* (two thirds of the findings labelled minor are substantive).
