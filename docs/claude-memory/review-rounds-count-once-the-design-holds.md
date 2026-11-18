---
name: review-rounds-count-once-the-design-holds
description: Paul counts a design's limited review rounds only from when the design stops changing; reads taken while he is still reshaping it are not rounds
metadata:
  type: feedback
---

While Paul is still changing a design in conversation, the model reviews run on it are reads, not the limited review rounds the cadence caps (cadence §4.8 `design-rounds`). Round 1 starts once the design holds still.

**Why:** on TD-1953's plan (2026-11-18), three reviews (Fable, Sonnet, Fable) ran while Paul kept reshaping the design. Each found new build-changing gaps, partly because the text kept moving. Paul: *as long as our design keeps changing, we have not actually started the limited review rounds.*

**How to apply:** in an interactive design round, label early reviews as pre-round reads in the plan's Status line and on the PR. Don't cite the round cap while Paul is still deciding. Start counting rounds when he says the design is settled. See [[design-review-loop-with-sonnet]], [[alternate-review-rounds]] and [[agree-the-layout-before-model-reviews]].
