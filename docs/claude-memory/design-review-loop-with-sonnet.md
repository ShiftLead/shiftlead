---
name: design-review-loop-with-sonnet
description: How many review rounds a design gets is cadence §4.8; when rounds keep finding holes in one mechanism, ask whether it is needed
metadata:
  type: feedback
---

How many rounds a review gets — one for a wording, rounds until the reviewers agree for a mechanism or
a rule — is cadence §4.8; here a design's Fable and Sonnet rounds both iterate until they agree. Merge
nothing the round is still changing: [[hold-a-design-until-its-round-ends]]. Asked to review a design,
deliver the findings first and wait for Paul's go. Once each round returns only a follow-on of the last
adoption, Fable may close the loop, recording the override in design-history.md and the entry's Status
(TD-103, 2026-09-22; Paul accepted it).

**When rounds keep finding gaps in the same mechanism, ask whether the mechanism is needed** (TD-722
amendment, #1850, 2026-10-15). Fable rounds 1–3 and Sonnet round 2 each found new lifecycle holes in
the per-repo anchor seat (who controls it, how it winds down, what refills it). Paul then asked what
the anchor did that nothing else could. The answer was nothing: it never promotes, §6 *Pull* keeps the
checkout current, and every job ends as a PR any worktree can make. The seat was retired instead, and
the review converged in two more rounds.

**How to apply:** after two rounds of findings in one part's lifecycle, list that part's jobs and their
other takers before patching again, and offer removal as the recommendation if every job has one.
See [[shiftlead-td-grind-mechanics]].
