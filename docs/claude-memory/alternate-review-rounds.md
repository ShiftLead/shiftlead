---
name: alternate-review-rounds
description: "Design review rounds alternate Sonnet and Fable with a fix between each, never both at once"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e3291f90-1ccf-40ac-9bf1-2a84918bc057
  modified: 2026-10-19T23:54:29.259Z
---

Run design review rounds one reviewer at a time — Sonnet, fix, Fable, fix — until a round returns READY with nothing to adopt, rather than launching Fable and Sonnet in parallel on the same text.

**Why:** Paul, 2026-10-19: *it will actually be more efficient (tokenwise) to alternate sonnet and fable rounds — with fixes in between each.* Parallel rounds both find the same issues and both spend tokens re-reading text the other's findings would have changed.

**How to apply:** Start with the cheaper model. Adopt its findings, commit, then launch the other on the fixed text. Count rounds per reviewer in the ADR's review record. Related: [[design-review-loop-with-sonnet]].
