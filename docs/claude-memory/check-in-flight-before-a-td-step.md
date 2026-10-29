---
name: check-in-flight-before-a-td-step
description: Check what is in flight before a TD step (cadence §2.9, `forge.py in-flight`); `ao msg` for leads, never a peer message
metadata:
  type: feedback
---

Cadence §2.9 (dev-cadence TD-137): `agent-cadence run forge.py in-flight TD-NNN` before a TD or one step of
one, and again right before the work starts. When a step is held elsewhere, do the conformance read of what
lands instead of building, and reach an unattended lead with `ao msg`, never Claude Code's peer message
(held for approval, it stalls the lead). Related: [[shiftlead-td-grind-mechanics]].
