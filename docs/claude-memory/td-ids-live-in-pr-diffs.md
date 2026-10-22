---
name: td-ids-live-in-pr-diffs
description: Take a TD id from `ao td next`, never by hand — a renumber too; grepping open PRs' diffs is only the fallback when no home answers
metadata:
  type: feedback
---

Take every new ledger id, and every renumber's id, from `ao td next [--count n]`: the home reads main,
the archive and every open PR's diff, and also the ids it already handed out that nobody has pushed
yet, which no grep can see. On 2026-10-22 PR #2240 (td-156) numbered by hand twice: TD-942 was
already the home's to designer-ao-1 (#2238 merged first), and the hand renumber to TD-951 took an id
the home had given grinder-ao-1 at 03:42, unpushed. `ao td next` gave TD-964/965, and the collision ended.

**Why:** two sessions numbering at once take the same id, and the later one renumbers across a rebase
and another CI run (TD-651 → 653 → 656 on 2026-10-13, TD-942 → 951 → 964 on 2026-10-22). Cadence §2.10
still teaches the hand rule until dev-cadence#TD-124 lands (shiftlead TD-966).

**How to apply:** before writing an entry, `ao td next` (`--repo <name>` from another checkout); read
its stderr for *open PRs not read*. Only when no home answers (a cloud session), fall back to the
highest of main and every open PR's diff (titles miss them):

```bash
for n in $(gh pr list --state open --limit 200 --json number --jq '.[].number'); do
  gh pr diff $n | grep -oE '^\+## TD-[0-9]+'; done | sort -u
```

A new or renumbered entry goes at the ledger's end, for id order (`tests/test_ledger.py`). Also read
mail when the doorbell rings: the designer's note about TD-942 sat unread most of a day. See also
[[designer-run-lessons-2026-10-12]], [[shiftlead-td-grind-mechanics]].
