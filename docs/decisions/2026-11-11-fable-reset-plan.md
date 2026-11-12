# Spending the two Fable resets well (2026-11-11)

**Status:** a draft for discussion with Paul, written from the session `fabplan`. Each item says whether it
is *agreed* (Paul has said yes), *proposed* (on the table) or *withdrawn*. Nothing here is in the ledger yet.
The evidence is [the design review findings analysis](2026-11-11-design-review-findings.md).

## The facts it rests on

- The account has a weekly limit over all models and a separate Fable limit. Paul holds two resets; each
  clears Fable's usage (and takes it out of the week's count), and both lapse in March.
- `ao gate` reads only the all-models week. Nothing on the home reads the Fable limit, and TD-1589 says the
  week's reading itself is often old.
- The designer session takes about half of a day's spend and the two grinders about two fifths. The
  reviewers are a few percent of the designer's tokens: a design's cost is the author's own turns, above all
  the turns that apply each round's fixes at 140k to 300k tokens of context.
- 28 open entries wait on a decision from Paul; 20 are pickable.

## Timing

Press a reset at the moment the Fable limit is hit, with work queued that needs Fable, and early enough in
the week that a second allotment can be used before the window ends. Never before the limit (the rest is
forfeited) and never in a week's last two days. A reset doubles what the sessions can do that week, not
what Paul can decide, so the decisions its work waits on are cleared first.

## A cheaper way to design

The aim is the same designs, as sound, for fewer Fable tokens: Fable writes, Sonnet does what Sonnet does as
well, and a script does what needs no model. The review rounds keep their cap and their stop rule.

| Step | Who | What | Status |
|---|---|---|---|
| 1. Before drafting | a script, a Sonnet agent | The other design text that names the mechanism; the facts of the code the design touches | proposed |
| 2. The draft | Fable (the designer seat) | Writes the design against a short checklist of the situations designs here miss, and checks every function, flag or record it names as it writes | proposed |
| 3. The pre-review script | called by the author | Must pass before any reviewer reads. Largest first: one statement in two places drifted apart, a path or symbol that should exist, entry fields out of step, counts, ids, section references | **agreed**; who supplies the terms to look for is open |
| 4. The rounds | reviewers, as today | Each finding is raised with the situation it is about. The fact-check reads the code behind behaviour claims, the script having taken the rest | proposed |
| 5. The fixes | Sonnet (a second seat) | Collates a round's findings, applies the fixes, checks any code a fix names, reruns the script | proposed |
| 6. The hard findings | Fable, asked by the Sonnet seat | Findings about two actors at once, interaction with another rule, restarts, endings, timing, actors and error paths go back to Fable as one narrow question each | proposed |

**Why this shape.** Of 3,120 findings, 16% need no model, 13% are a false claim about what exists (two
thirds of them written by the fixes, after round 1), 37% are detail a builder would meet anyway, and 25%
are the hard situations of step 6, where a design review finds what nothing else would. A quarter of all
findings follow from an earlier fix. Designs already get about seven fact-checks each.

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

Not measured today and wanted for step 2: spend for each ledger entry, and whether a PR-review finding or a
fix after a merge traces to its design.

## The rest of the sharpening

- **The usage reading** (TD-1589, its wait lifted by Paul) and a way to read the Fable limit. *Agreed* for
  TD-1589; the Fable reading is proposed.
- **The prompt-cache builds** already moving (TD-1664, TD-1669, from TD-1551).
- **What each role is made to read.** The design is about 665k tokens in 30 files, six sections of 36k to
  101k tokens each; one read stays in the context of every later turn. A reader that prints one heading, or
  smaller files, is the candidate. What sessions read each turn is not yet measured. *Proposed.*
- **The messaging system, reviewed whole**, with Paul, from evidence: the mail corpus (asks never answered,
  steers refused, doorbells missed, tokens for each delivered message) and the memory files that exist to
  work around `ao msg` and `ao inbox`. A ranked findings report first; designs after Paul agrees the shape.
  *Proposed.*

## The two resets

- **Reset 1** goes to shiftlead once the new design shape has passed its trial, so the doubled week is spent
  at the better rate: the messaging review's designs and the efficiency builds.
- **Reset 2** goes to Paul's other projects, when the cost of a merged PR is measurably down and the target
  repo has a team, a full lane and its decisions cleared; no later than mid-January.

## The order

1. TD-1589 and the Fable reading. 2. The pre-review script. 3. The checklist. 4. The second seat and the
hand-back. 5. The three replays. 6. Real designs on the new shape. 7. Reset 1.

## Open

- Whether the pre-review script is given its terms by the author or parses the PR.
- Who reviews: Fable then Sonnet as today, or Sonnet alone. In tokens for each finding only a design review
  would catch they are within about 16%; what Fable finds that Sonnet would miss is not measured.
- How the Sonnet seat hands a finding back, and how the Fable seat answers without reloading the design.
- Whether steps 1 and 2 need the Sonnet fact pack, or the write-time check is enough.

## Withdrawn

- *A cap of two design rounds.* Rounds 3 and 4 each still raise, for each design that reaches them, about
  0.8 and 0.7 findings only a design review would catch; a round costs the designer at most about $9 by
  `ao spend`'s estimate, and a flaw that escapes costs at least a fix PR and, live, far more.
- *Fable does the design reviews* (it costs far more for each review; Paul).
- *Every minor finding goes to the builder* (two thirds of the findings labelled minor are substantive).
- *More fact-check rounds* (there are about seven for each design; the false claims come from the fixes).
