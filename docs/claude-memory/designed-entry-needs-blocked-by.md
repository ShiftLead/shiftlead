---
name: designed-entry-needs-blocked-by
description: A designed entry's builds name it in "**Part of:**"; it writes no Pickable line and lists no build in Blocked by — cadence §2.4
metadata:
  type: feedback
---

Cadence §2.4: pickable is derived, never written; a designed entry is kept out of the lanes by its
open builds, each carrying `**Part of:** TD-n` (the design's id), while its `**Blocked by:**` names only
what must land first (TD-1129, since TD-1133's backfill, 2026-10-27), and `python3 scripts/ledger.py --check --since origin/main`
runs before every ledger push. See [[shiftlead-td-grind-mechanics]].
