---
name: design-review-loop-with-sonnet
description: Design sections are reviewed by Fable, changes adopted, then Sonnet rounds run until both agree it is ready for implementation
metadata:
  type: feedback
---

For a design section (e.g. design §4.10 on 2026-09-16), Paul's process is: Fable reviews and
lists ranked findings with a recommendation each; on his "adopt them", write them into the
design, TD entry and §10; then run Sonnet design-review rounds (fresh agent each round, told
what earlier rounds verified) until Sonnet says READY and Fable agrees, or Fable overrides a
Sonnet finding deliberately and records why. Record each round in §10. Then PR, Sonnet
fact-check as the cadence-review comment, cadence check, squash merge.

**Why:** Paul wants independent agreement before TD-052-scale implementation starts; §4.10 took
four Fable rounds and three Sonnet rounds to converge.
**How to apply:** when asked to review a design, deliver findings first and wait for the go;
then loop reviews to convergence rather than stopping after one. See
[[shiftlead-td-grind-mechanics]] for the cadence comment shape.

Added 2026-09-22 (TD-103, eight rounds): after round 3 each round returned one finding that was a
consistency follow-on of the previous adoption, never a new hole. Fable may close the loop then,
recording the override in design-history.md and the ledger's Status line; Paul accepted that
close without comment. Also: the rewriting agents of the docs pass kept rules and cut narrative
only (86K → 69K words), so a length target under 60% is not met on rule-dense sections.

Added 2026-10-15 (Paul): **Fable rounds iterate too**, alongside the Sonnet rounds, not as one review
up front. After the findings are adopted and written in, a fresh Fable agent reviews the written
design again, told what earlier rounds settled, until Fable has no finding beyond follow-ons of the
last adoption. Sonnet's rounds run until READY, and the design is done when both agree. The
designer's brief gets the same loop in #1842 (docs/briefs/designer-ao-1.md, a held path). Merge nothing the round is
still changing: [[hold-a-design-until-its-round-ends]].

Added 2026-10-15 (TD-722 amendment, #1850): **when rounds keep finding gaps in the same mechanism,
ask whether the mechanism is needed.** Fable rounds 1–3 and Sonnet round 2 each found new
lifecycle holes in the per-repo anchor seat (who controls it, how it winds down, what refills it).
Paul then asked what the anchor did that nothing else could. The answer was nothing: it never
promotes, §6 *Pull* keeps the checkout current, and every job ends as a PR any worktree can make.
The seat was retired instead, and the review converged in two more rounds. **How to apply:** after
two rounds of findings in one part's lifecycle, list that part's jobs and their other takers
before patching again, and offer removal as the recommendation if every job has one.
