---
name: alternate-review-rounds
description: Design review rounds alternate Sonnet and Fable with a fix between each, never both at once — cadence §4.8
metadata:
  type: feedback
---

Cadence §4.8 (dev-cadence TD-136): iterated rounds with more than one reviewer model run one at a time,
cheaper first, each round's fixes committed before the next starts. Here that is Sonnet, fix, Fable, fix,
until a round returns READY with nothing to adopt (Paul, 2026-10-19); count rounds per reviewer in the ADR's
review record. Related: [[design-review-loop-with-sonnet]].
