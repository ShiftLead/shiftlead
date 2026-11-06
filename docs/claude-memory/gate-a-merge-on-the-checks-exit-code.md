---
name: gate-a-merge-on-the-checks-exit-code
description: "Merge only through the cadence procedure's step 5 line, whose `&&` is the gate — a check piped through `| head` merged #398 on a FAIL"
metadata:
  type: feedback
---

The cadence procedure's step 5 (`agent-cadence path procedures/cadence.md`): merge only on exit 0, through its line,
run whole as one command:

```bash
m=$(mktemp -d); agent-cadence run check_cadence.py --pr N --trailers "$m/gate"; agent-cadence run forge.py squash-message N --gate "$m/gate" --out "$m" && gh pr merge N --squash --match-head-commit "$(cat "$m/sha")" --subject "$(cat "$m/subject")" --body-file "$m/body"
```

Since TD-233 the gate is the line's `&&` before the merge: `check_cadence.py --trailers` writes what it saw, and
`forge.py squash-message` refuses a gate file that did not pass, so a failing PR reaches no merge. The `;` after the
check is deliberate — never add `&&` there — and never `--unverified` unless the procedure's own case for it applies.
The lesson the line keeps: a gate read through a pipe lies — `check_cadence.py | head` gave #398 a 0 on a FAIL
(2026-09-21), so anything else gated on the check captures its exit code from the check itself (`… > out; ec=$?`).
Related: [[read-inbox-before-merging]].
