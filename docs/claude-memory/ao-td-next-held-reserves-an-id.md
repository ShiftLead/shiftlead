---
name: ao-td-next-held-reserves-an-id
description: `ao td next` (and `--held`) takes an id from the home's counter every time it runs; never run it as a probe, and take ids only right before committing the entry
metadata:
  type: feedback
---

`ao td next` hands out the next free id and records it on origin's counter, so every call burns one, `--held`
included: `--held` also lands the entry held once it's filed. On 2026-10-28 a call made only to check the home
answered took TD-1198 for nothing, as a doubled call had taken TD-1148 the day before. To see that the home
answers, use a read (`ao repo <name>`, `ao status`), never `ao td next`. See [[td-ids-live-in-pr-diffs]].
