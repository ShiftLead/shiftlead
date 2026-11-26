---
name: remove-a-review-copy-when-its-review-ends
description: a review clone under $SHIFTLEAD_SCRATCH/copies holds 80k-150k files; remove it as soon as its review is posted and it holds nothing unpushed
metadata:
  type: feedback
---

Remove each review copy under `$SHIFTLEAD_SCRATCH/copies/<name>` the moment its review ends (the review posted, no unpushed commit in it), not after a quiet day.

**Why:** Paul, 2026-11-26 (through the flows seat): /tmp reached 75% of its file count, mostly sessions' review copies; one designer's copies held 80,000 to 150,000 files.

**How to apply:** after a reviewer subagent's verdict is recorded, `rm -rf` the copy it read; before ending a run, `ls $SHIFTLEAD_SCRATCH/copies` and remove the finished ones. See [[scratchpad-too-long-for-unix-sockets]].
