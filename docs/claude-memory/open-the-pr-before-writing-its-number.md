---
name: open-the-pr-before-writing-its-number
description: A PR number is written only after the forge returned it — cadence §2.8
metadata:
  type: feedback
---

Cadence §2.8 (dev-cadence TD-137): a PR number is the forge's, written into the ledger, a doc or a PR body
only after `gh pr create` printed it. The same goes for `ao progress done <ref> --pr N`.
Related: [[shiftlead-td-grind-mechanics]].
