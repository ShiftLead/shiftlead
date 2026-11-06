---
name: work-open-asks-before-idle
description: a seat never ends a turn listing asks it has not acted on — the doorbell never rings a read ask again
metadata:
  type: feedback
---

Before ending a turn, work every open ask in the inbox (`ao inbox`, entries marked *open*) to an answer, a hand-off, or a filed entry; never end on a list of asks "still open, not acted on".

**Why:** the doorbell rings only on mail past the `mail_decided` watermark, so an ask already read is never rung again, and only a record with a `seat` gets rule 4's idle line counting open asks; on 2026-11-06 the techlead seat ended a turn listing seven open asks and slept on them until Paul noticed and asked "why do you go idle with asks still open?" (TD-1435 files the gap). Several of those asks turned out to be already fixed or already filed — a five-minute check settles them.

**How to apply:** after the asked-for work, re-read `ao inbox` and settle each open ask: a reply with `--verdict` for a PR's ask, `--outcome` for the person's, a reply naming the entry for a filing request. On a record with no `seat` (`ao --json status`), a reply to an ask from a session you may not otherwise write to is refused (the reply exception needs a question seat, TD-1435): say so in your final report. Related: [[never-count-the-unread-inbox]], [[read-inbox-before-merging]].
