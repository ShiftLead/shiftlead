---
name: td-ids-live-in-pr-diffs
description: Take a TD id, and a renumber's, from `ao td reserve` — cadence §2.10; never number by hand
metadata:
  type: feedback
---

Cadence §2.10: every new ledger id, and every renumber's, comes from `ao td reserve [--count n]` (here the
front end), else `agent-cadence run ledger_next_id.py` — never by hand (TD-942 → 951 → 964 on 2026-10-22, PR #2240).
See also [[designer-run-lessons-2026-10-12]], [[shiftlead-td-grind-mechanics]].
