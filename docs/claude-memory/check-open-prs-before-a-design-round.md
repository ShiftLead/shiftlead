---
name: check-open-prs-before-a-design-round
description: Check what is in flight before a design round (cadence §2.9) — a restarted run's own open PRs too
metadata:
  type: feedback
---

Cadence §2.9 (dev-cadence TD-137): `dev-cadence run forge.py in-flight TD-NNN` before designing an entry; a
PR that exists makes the round a reconciliation against it, never a second design. It applies to the
designer's own restarted run: its design PRs sit open on a steer while `main` reads *Open*, and
`ao status -v`'s *waiting on you: TD-NNN until …* on the run's record names them (2026-10-04). So the run's first read, before `ao progress claim`, is
`gh pr list --state open` and each PR's last comment (the handoff).
Related: [[a-park-is-a-merged-pr]].
