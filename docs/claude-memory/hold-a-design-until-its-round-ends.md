---
name: hold-a-design-until-its-round-ends
description: Don't merge a design-first entry or a design PR while its interactive round is still running — merged and unblocked, a lane picks it within half an hour
metadata:
  type: feedback
---

**Paul, 2026-10-15:** *don't merge new design PRs until we are ready for them to be picked up.* Merging
puts whatever the PR holds on `main`. The home's settle clock gives a new entry about 25 minutes
(TD-707/TD-710), and after that the lanes take it.

**What happened:** an interactive session filed TD-722 (one repo per team, `design-first`) in #1828 with
no `Blocked by:`, merged it at Paul's word, and started a Fable review of the proposal.
- TD-722 settled at 12:54 MDT, and designer-ao-1 designed and merged it as #1832 by 13:30, before
  Fable's findings came back.
- grinder-ao-2 then claimed the new build entry TD-724 and had #1840 under review within the hour.
- The round's amendments (a per-repo anchor, refusing old keys) changed TD-724's scope. #1840 had to
  be made a draft and TD-724 blocked by hand.

**Why:** a `design-first` entry with nothing in `Blocked by:` is in the designer's lane once it
settles, and the builds a design PR files are in the grinders' lanes the same way. Holding an entry
is the person's own act and only works while it is settling (`ao td hold`), so a session can't stop
the lane once it has merged.

**How to apply:**
- An entry filed for a design conversation still going on lands with
  `**Blocked by:** decision (paul) — <the conversation>`. The PR that ends the round drops the line.
- A design PR from an interactive round, or its build entries, stays unmerged until the reviews
  (Fable and Sonnet, [[design-review-loop-with-sonnet]]) have converged and Paul says it's ready.
  Otherwise its builds carry `Blocked by: decision (paul)` until then.
- Before a round starts, search the id in every state ([[a-park-is-a-merged-pr]],
  [[check-open-prs-before-a-design-round]]) and check `ao status` for a claim. A lane may already
  hold it.
