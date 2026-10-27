---
name: wait-for-ci-with-gh-pr-checks-watch
description: kmaster's gh (2.46) has no `--json` on `pr checks`; a wait loop built on it errors every round and never exits — use `gh pr checks N --watch` in the background, until TD-940's `ao pr wait` lands
metadata:
  type: feedback
---

On kmaster `gh pr checks N --json …` prints *unknown flag: --json* (gh 2.46.0): an `until` loop whose
condition captures that output fails every round and spins until someone asks whether something is
broken (four waits in the ao-paul session, 2026-10-21, while CI had passed each time). Wait with
`gh pr checks N --watch` as a background command — it exits when the checks finish, non-zero on a
failure — then run `scripts/check_cadence.py --pr N` and merge on its exit code. After a push, main
may have moved during the nine-minute CI: a `merge conflicts` refusal means rebase and watch again.

**Why:** Paul, 2026-10-21: *our waits seem to keep hanging.* The cause was the flag, not CI.

**How to apply:** never put a `gh` invocation you have not run once in the foreground into a wait
loop's condition. TD-940 (`ao pr wait <n>`) replaces the loop with the home's folded reading;
see [[no-checks-means-conflicting]] and [[gate-a-merge-on-the-checks-exit-code]].

**Since TD-1035 (2026-10-26)** PRs gate on a local `cadence/precheck`, not GitHub Actions (stopped over billing): see [[precheck-and-merge-in-one-command]].
