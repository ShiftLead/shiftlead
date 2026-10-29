---
name: agent-settings-are-the-persons
description: Never change Claude Code's (or any agent tool's) settings or permission rules without the person's say-so; propose them instead
metadata:
  type: feedback
---

When a tool's permission mode blocks routine work (2026-10-14: auto mode refused closing a superseded
PR and editing a review comment), propose the allow rule, but never add it to `.claude/settings.json`,
`~/.claude/settings.json` or another tool's config. Paul: *it should be a decision each user makes; we
should not be in the habit of changing claude/other agent settings without permission.*

**Why:** these settings belong to each person using ShiftLead and agent-cadence, not to the repo. A
convention that edits them assumes Claude Code and overrides someone else's choice.

**How to apply:** name the blocked action and the rule that would allow it, then let the person decide.
Shipped seeds keep only the hooks the cadence needs, never allow rules. See
[[design-goals-effective-non-intrusive]].
