---
name: gate-a-merge-on-the-checks-exit-code
description: "Merge only on exit 0 (the cadence procedure's step 5), captured from the check itself — `check_cadence.py | head && gh pr merge` merged #398 on a FAIL"
metadata:
  type: feedback
---

The cadence procedure's step 5 (`docs/procedures/cadence.md`): merge only on exit 0. The lesson the
procedure does not state: capture that exit code from `agent-cadence run check_cadence.py` itself
(`… > out; ec=$?`), never through a pipe — `| head` gave #398 a 0 on a FAIL (2026-09-21).
Related: [[read-inbox-before-merging]].
