---
name: stranded-work
description: Audit for work stranded by closed Claude Code sessions — approved plans never started, "awaiting the user" steps that evaporated, deploy-pending fixes, stale watch-items. Quick mode runs inline; pass "deep" to fan out agents including a session-transcript scan.
---

<!-- SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/.claude/skills/stranded-work/SKILL.md
     Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one). -->

# Stranded-Work Audit

Read [`docs/procedures/stranded-work.md`](../../../docs/procedures/stranded-work.md) and follow it — the whole procedure lives there,
where an agent in any tool can run it (TD-093); this file holds no rule of its own. An argument of `deep` means the deep mode; none means the quick one.
