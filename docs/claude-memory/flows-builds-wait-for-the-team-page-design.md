---
name: flows-builds-wait-for-the-team-page-design
description: Paul holds the Flows builds (TD-2047 to TD-2055) until the team page design (TD-1153) is done, so the designs agree before building
metadata:
  type: project
---

The Flows design (TD-1954) merged as PR #4323 on 2026-11-21. Its nine builds, TD-2047 to TD-2055, stay
held by `decision (paul)`: Paul has not said go, and does not mean to until the team page design
(TD-1153) is written.

**Why:** Paul, 2026-11-21, on merging #4323: "I prefer to have the designs all be congruent before we
start building." The Tools page (TD-1953), the Flows page (TD-1954) and the team page (TD-1153) are one
frame (docs/decisions/2026-11-18-tools-flows-teams.md).

**How to apply:** Do not press, recommend or assume a Go on the Flows builds while the team page round
is open. The team page design must agree with docs/design/4.9c-flows.md: it carries the flow pick, what a
flow switch does to entries in flight, and the logins; its builds must land without format 3 running,
because the cut-over (TD-2056) waits on them. Where the team page round finds the Flows design wrong,
change the Flows design in the same round. Drop this memory once Paul says go on the builds.
