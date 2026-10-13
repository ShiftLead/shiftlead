---
name: attention
description: Machine-wide "what needs my attention?" — every registered repo's user-attention board in one due-date-ordered report. Pass "fetch" to also compare each board against its origin (pushed cross-machine state). Pass "remote" for the everything view: fetch plus GitHub discovery (GitHub only, TD-104) of boards in repos not present on this machine.
---

<!-- SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/.claude/skills/attention/SKILL.md
     Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one). -->

# Attention — machine-wide board report

Read [`docs/procedures/attention.md`](../../../docs/procedures/attention.md) and follow it — the whole procedure lives there,
where an agent in any tool can run it (TD-093); this file holds no rule of its own. An argument of `fetch` or `remote` means that form of the report; none means the plain one.
