---
name: designer-run-lessons-2026-10-13
description: A §4.5a row's first cells are test keys — add a pointer at the row's end; a design that changes a view names the host function that builds it; the full doc-bound suite takes ~5 min, so run it in the background
metadata:
  type: feedback
---

- **A §4.5a row's first two cells are what doc-bound tests find it by.** For example, `tests/test_ui.py` matches `startswith("| Focus composer | **Send** |")`. A pointer added to a row goes at the end of its last cell, never into the control's name. TD-665's first push broke `test_the_composer_says_whether_send_starts_a_turn_or_steers_one` with `StopIteration` that way.
- **Before pushing a §4.5a edit, run the tests that read it**: `grep -ln "4\.5a" tests/*.py`. That set takes about 5 minutes, so run it in the background. `test_ui.py`, `test_design_doc.py` and the help tests alone are the quick check.
- **"The record's view" is `agent_serve._view`**, not `Session.view()`, which only trims `to_dict()`. A field derived from the adapter goes there, before the early return for a node's own records.
- **A capability that replaces name checks lists the old checks in its build entry.** `adapter == "shell"` appeared in nine places; listing them is what makes "keyed on the capability" true, and it covers `command` runs too.

**Why:** each of these came up as a fact-check finding or a test failure in the TD-665 round, and each cost a fix-up commit.
**How to apply:** in any design round that edits §4.5a rows or adds a view field. See [[design-help-text-is-bound-to-help-py]].
