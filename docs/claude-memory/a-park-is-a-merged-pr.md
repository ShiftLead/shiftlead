---
name: a-park-is-a-merged-pr
description: A park holds once its PR is merged (cadence §3.6); re-search the id's PRs in every state (§2.9)
metadata:
  type: feedback
---

Cadence §3.6 (dev-cadence TD-138): a park, hold or `Blocked by:` takes effect only once merged, since the
designer reads the board on `main`; and §2.9 (TD-137): `forge.py in-flight TD-NNN` lists the id's PRs in any
state, so run it again at the start of the round. From a cloud session, which has no `gh`, read the park PR's
`merged: true` with the GitHub MCP's `pull_request_read`. Related: [[cloud-design-round]],
[[check-open-prs-before-a-design-round]].
