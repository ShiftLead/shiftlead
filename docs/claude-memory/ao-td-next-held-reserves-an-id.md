---
name: ao-td-next-held-reserves-an-id
description: `ao td reserve` (`ao td next` is its old name) takes an id from the home's counter every time it runs; never run it as a probe, and take ids only right before committing the entry
metadata:
  type: feedback
---

`ao td reserve` (`ao td next` is its old name, TD-1200) hands out the next free id and records it on origin's counter, so every call burns one
(`--held` is gone since TD-1297: an entry the person is still deciding lands with `Blocked by: decision (<person>)` and an Ask). On 2026-10-28 a call made only to check the home
answered took TD-1198 for nothing, as a doubled call had taken TD-1148 the day before. To see that the home
answers, use a read (`ao repo <name>`, `ao status`), never `ao td reserve`. See [[td-ids-live-in-pr-diffs]].
