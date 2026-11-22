---
name: flows-builds-wait-for-the-team-page-design
description: Paul holds every build of the Tools/Flows/team/switch-over frame (TD-2047 to TD-2055, TD-2059 to TD-2066, TD-2068 to TD-2072) until the designs agree and he says Go
metadata:
  type: project
---

The Flows design (TD-1954, PR #4323) and the team page design (TD-1153, PR #4332) are merged; the switch-over
design (TD-1976, design 4.9e) is the last of the set, written 2026-11-22. Every build they file stays held by
`decision (paul)`: the Flows builds TD-2047 to TD-2055, the team page builds TD-2059 to TD-2066, and the
switch-over builds TD-2068 to TD-2072. TD-2073 is the window itself, run by Paul with a session, and TD-2056
removes the old shape after it.

**Why:** Paul, 2026-11-21, on merging #4323: "I prefer to have the designs all be congruent before we
start building." The three pages and the switch-over are one frame (docs/decisions/2026-11-18-tools-flows-teams.md).

**How to apply:** Do not press, recommend or assume a Go on any of these builds; the Go answers are best given
together once the switch-over design's rounds converge. Where one design's round finds another wrong, change
the other in the same round. Drop this memory once Paul says go on the builds.
