---
name: review-what-is-written-after-the-last-round
description: a design's last review round is followed by fixes, build entries and board questions nobody read; run a round on them before calling it ready
metadata:
  type: feedback
---

After a design's rounds read READY, whatever is written afterwards (the round's own fixes, the build
entries, the builds list, the board questions) gets a review round of its own before the pull request is
offered for merge.

**Why:** Paul, 2026-11-21, on TD-1954 (PR #4323), when told round 6's fixes were unread: "If that's true
lets run another review round." Rounds 7 to 9 on the entries and board questions alone found 5, then 2,
then 1 blocker: a cut-over that deadlocked with the team page design, parts that would have held the
design open for ever, entries a single Go would have started early. The design text itself had held.

**How to apply:** File the builds and board questions before the last design round where possible, so
that round reads them. Otherwise run a short round scoped to the diff since the READY commit, asking the
reviewer to write out the dependency graph from the entries' own headers (Part of, Blocked by, the
archive rule) and to say what each board answer starts. Say plainly in the report what no round has read.
See [[hold-a-design-until-its-round-ends]] and [[designed-entry-needs-blocked-by]].
