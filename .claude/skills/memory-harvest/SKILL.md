---
name: memory-harvest
description: Started only by the person — harvest the process rules sessions saved as memories across every repo on this machine's roster, sort each with the person (promote, covered, exception, repo-local, craft), carry the rules to their own cadence layer, send the general ones on to dev-cadence, and open a follow-up in each source repo. Runs from any cadence repo and writes the person's layer clone by path.
---

# Memory harvest — process rules from memories, to the person's layer

Read [`docs/procedures/memory-harvest.md`](../../../docs/procedures/memory-harvest.md) — in a repo that pins dev-cadence, the file `dev-cadence path procedures/memory-harvest.md` prints — and follow it; the whole procedure lives there,
where an agent in any tool can run it (TD-093); this file holds no rule of its own. Its first step finds the person's layer clone and stops if it is not fit for the run's commits.
