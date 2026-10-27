---
name: dates-and-pr-numbers-are-local-and-real
description: In ShiftLead's ledger and design, dates are the machine's LOCAL date (run `date`); a PR number is the forge's (cadence §2.8)
metadata:
  type: feedback
---

Two things a ledger or design edit gets wrong silently, and a reviewer has to catch:

**The date is the local date.** kmaster is MDT (UTC−6), so a session working past 18:00 local sees UTC timestamps a day ahead — `git log --date=iso` and `date` are the truth, the `Z` stamps in records and mail are not. I wrote `2026-09-21` into TD-029 and TD-083 on the evening of 2026-09-20 because the mail and commit *times* said so.

**A PR number is the forge's**: cadence §2.8 (dev-cadence TD-137).

**Why:** a wrong date sends a future reader to the wrong place, and fails no test — the fact-check is the only thing between it and main.

**How to apply:** before any ledger or design edit that carries a date, run `date`. Related: [[pdm-run-fmt-sweeps-other-sessions-files]].
