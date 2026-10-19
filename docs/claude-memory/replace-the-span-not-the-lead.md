---
name: replace-the-span-not-the-lead
description: when a design edit replaces a section, the edit script replaces the whole span (lead through last item), never the lead sentence alone — #2154's first fact-check found the old items still standing under the new text
metadata:
  type: feedback
---

Rewriting §4.5 screen 11 for TD-900 (2026-10-18), the edit script replaced the lead sentence ("Under them … the lists behind the numbers") with the new board text and left the old numbered items 1–3 in place under it, so the design described both shapes at once. A fact-check round caught it (#2154).

**Why:** a replacement anchored on a lead is only as wide as the lead; the items that follow are the section's content, and nothing fails when they stay.

**How to apply:** when a section is replaced, locate its start and the start of what follows it (the next heading or item that survives) and replace that whole slice; keep what must survive by extracting it from the slice, not by leaving the slice. Then grep the file for the old items' first words. Related: [[edit-script-asserts-before-writing]], [[design-review-loop-with-sonnet]].
