---
name: precheck-and-merge-in-one-command
description: "The precheck runs ~12 min and main moves the ledger under it: run precheck, the cadence check and the merge as one background command, so a green run merges before main moves again"
metadata:
  type: feedback
---

Since TD-1035, PRs are gated on `cadence/precheck`, which the session records with `dev-cadence run precheck.py --pr N`. It is the whole suite on one core, ~12 minutes (TD-1068 parallelises it). On 2026-10-26 a ledger-only PR (#2408) was prechecked six times:
- two flaky failures of TD-1050's container test, and one of `test_a_restart_is_written_afresh`, which passes alone;
- two green runs, after each of which main had moved the ledger, so the PR conflicted and every rebase needed a new precheck.
The sixth merged because precheck, gate and merge ran in one command:

```bash
dev-cadence run precheck.py --pr N > pre.txt 2>&1; echo "precheck $?"
dev-cadence run check_cadence.py --pr N > gate.txt 2>&1; rc=$?
[ $rc = 0 ] && gh pr merge N --squash && gh pr view N --json state -q .state
```

Run it in the background, after the PR's `headRefOid` matches the pushed head.

**Why:** separate steps leave minutes between green and merge, and the ledger's Summary table moves every few minutes.

**How to apply:** fold review evidence and the fact-check in before the precheck, so it runs on the final head. Never run two prechecks at once (TD-1052 fills `/tmp`). A flake in a test the PR does not touch is rerun, and named in the ledger if it is new. See [[gate-a-merge-on-the-checks-exit-code]], [[summary-table-conflicts-resolve-row-wise]].
