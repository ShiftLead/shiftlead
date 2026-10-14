---
name: td-ids-live-in-pr-diffs
description: An open PR's TD ids are in its diff, not its title — grep every open PR's diff for `^+## TD-` before taking a number, and again at each rebase
metadata:
  type: feedback
---

To find the next free TD number, read the open PRs' **diffs**, not their titles. A PR's title names
the entry it works on, while the new ids it files sit only in its ledger diff. On 2026-10-13 (TD-646's
Fable round, PR #1675) a title search showed nothing past TD-650, and the Cloudflare build took
TD-651. Open PR #1673 already held TD-651 in its diff. The renumber to TD-653 then collided with
another PR's diff, and the final number was TD-656, after three rebases.

**Why:** main and the other open PRs take numbers while a design PR waits for CI. A collision means a
renumber, a rebase and another CI run, and a number that slips through points a reader at someone
else's entry.

**How to apply:** right before committing a new entry, and again after every rebase:

```bash
git show origin/main:docs/technical_debt.md | grep -oE '^## TD-[0-9]+' | sort -t- -k2 -n | tail -1
for n in $(gh pr list --state open --json number --jq '.[].number'); do
  gh pr diff $n | grep -oE '^\+## TD-[0-9]+'; done | sort -u
```

Take the number after the highest of both. A renumber also moves the entry to the ledger's end, for
id order (`tests/test_ledger.py`). Refines the *re-read the highest TD* bullet of
[[designer-run-lessons-2026-10-12]]; see also [[shiftlead-td-grind-mechanics]].
