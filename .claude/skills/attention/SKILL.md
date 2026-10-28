---
name: attention
description: What needs my attention? — this repo's user-attention board in full, due-date-ordered, and one line per other registered repo (its open and due counts). Pass "all" for every repo's board in full, or a repo's name for that one. Pass "fetch" to also compare each board against its origin (pushed cross-machine state). Pass "remote" for the everything view — fetch plus GitHub discovery, and GitLab's for hosts remote_repos.txt names (TD-110), of boards in repos not present on this machine.
---

# Attention — machine-wide board report

Read [`docs/procedures/attention.md`](../../../docs/procedures/attention.md) — in a repo that pins dev-cadence, the file `dev-cadence path procedures/attention.md` prints — and follow it; the whole procedure lives there,
where an agent in any tool can run it (TD-093); this file holds no rule of its own. An argument of `all` or a repo's name picks which repos are shown in full, `fetch` or `remote` that form of the report, and they combine; none means this repo, plain.
