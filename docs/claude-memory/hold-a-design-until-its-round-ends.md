---
name: hold-a-design-until-its-round-ends
description: Don't merge a design-first entry or a design PR while its interactive round is still running — merged and unblocked, a design-first entry is in a lane 10 minutes later, and a design's builds at once
metadata:
  type: feedback
---

**Paul, 2026-10-15:** *don't merge new design PRs until we are ready for them to be picked up.* Merging
puts whatever the PR holds on `main`. The home's settle clock (TD-707/TD-710) withholds a new
`design-first` entry for 10 minutes in this repo (`.shiftlead.yml` `settle:`, built-in 5), and a
`build` entry for none, so a design's builds are pickable the moment it merges.

**What happened:** an interactive session filed TD-722 (one repo per team, `design-first`) in #1828 with
no `Blocked by:`, merged it at Paul's word, and started a Fable review of the proposal.
- #1828 merged at 12:44 MDT, TD-722 settled at 12:54, and designer-ao-1 designed and merged it as
  #1832 by 13:30, before Fable's findings came back.
- grinder-ao-2 (per `ao status`) then claimed the new build entry TD-724, pickable at #1832's merge,
  and had #1840 under review within the hour.
- The round's amendments (a per-repo anchor, refusing old keys) changed TD-724's scope. #1840 had to
  be made a draft and TD-724 blocked by hand.

**Why:** a `design-first` entry with nothing in `Blocked by:` is in the designer's lane once it
settles, and the builds a design PR files are in the grinders' lanes at once (a `build` settles 0
minutes). Holding an entry is the person's own act and only works while it is settling (`ao td
hold`), so a session can't stop the lane once it has merged.

**How to apply:**
- An entry filed for a design conversation still going on lands with
  `**Blocked by:** decision (paul) — <the conversation>`. The PR that ends the round drops the line.
- A design PR from an interactive round, or its build entries, stays unmerged until the reviews
  (Fable and Sonnet, [[design-review-loop-with-sonnet]]) have converged and Paul says it's ready.
  Otherwise its builds carry `Blocked by: decision (paul)` until then.
- Before a round starts, search the id in every state ([[a-park-is-a-merged-pr]],
  [[check-open-prs-before-a-design-round]]) and check `ao status` for a claim. A lane may already
  hold it.
