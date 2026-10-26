---
name: gate-a-merge-on-the-checks-exit-code
description: "Merge only on the cadence check's own exit code (the cadence procedure's step 5) — `check_cadence.py | head && gh pr merge` merged #398 on a FAIL"
metadata:
  type: feedback
---

The cadence procedure's step 5 (`docs/procedures/cadence.md`): merge only on exit 0 — captured from
`scripts/check_cadence.py` itself, never through a pipe (`| head` gave #398 a 0 on a FAIL, 2026-09-21).
Related: [[read-inbox-before-merging]].
