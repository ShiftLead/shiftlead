---
name: remove-a-review-copy-when-its-review-ends
description: a review clone under $SHIFTLEAD_SCRATCH/copies holds 80k-150k files; release it by renaming it to copies/.gone-<name> as soon as its review is posted, never rm -rf
metadata:
  type: feedback
---

Release each review copy under `$SHIFTLEAD_SCRATCH/copies/<name>` the moment its review ends (the review posted, no unpushed commit in it), not after a quiet day. A released copy goes with no hold, whatever it carries, so push anything in it first.

**Why:** Paul, 2026-11-26 (through the flows seat): /tmp reached 75% of its file count, mostly sessions' review copies; one designer's copies held 80,000 to 150,000 files.

**How to apply:** after a reviewer subagent's verdict is recorded, rename the copy it read: `mv $SHIFTLEAD_SCRATCH/copies/<name> $SHIFTLEAD_SCRATCH/copies/.gone-<name>`, never an `rm -rf`, which an unattended seat's permissions refuse; the next hourly or pressure pass removes it (design §4.6 *A seat releases its own*). Before ending a run, `ls $SHIFTLEAD_SCRATCH/copies` and release the finished ones the same way. See [[scratchpad-too-long-for-unix-sockets]].
