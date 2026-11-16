# Ledger

Ledgerboard: 2

## TD-101: An until that is past, its id archived

**Priority:** High
**Blocked by:** TD-100, until 2026-01-10

**Why:** the date in its gate came before today.

## TD-102: An until still ahead

**Priority:** Medium
**Blocked by:** until 2026-02-01

## TD-103: An event gate

**Priority:** Medium
**Type:** feature
**Blocked by:** event (vendor-ships)

## TD-104: A decision with its Ask

**Priority:** Medium
**Blocked by:** decision (pat)

**Ask:** pat says go once the shape is agreed.

## TD-105: Each gate named twice, and no Ask

**Priority:** Low
**Blocked by:** decision (Pat), decision (pat), until 2026-02-01, until 2026-03-01, event (x), event (x)

## TD-106: Retired words

**Priority:** Low
**Status:** Built 2026-01-02
**Taken by:** 0123abcd
**Blocked by:** hold
**Waits:** until 2026-02-01 — the vendor's window

## TD-107: A role in a decision

**Priority:** Low
**Blocked by:** decision (designer)

## TD-108: A priority outside the three

**Priority:** Urgent

## TD-110: A parent whose parts carry gates

**Priority:** Medium

## TD-111: A part waiting on a decision

**Priority:** Medium
**Part of:** TD-110
**Blocked by:** decision (Pat)

**Ask:** Pat picks the layout.

## TD-112: A part waiting on a decision and an event

**Priority:** Medium
**Part of:** TD-110
**Blocked by:** TD-108, decision (pat), event (x)

**Ask:** pat says go.

## TD-113: A part whose until is past

**Priority:** Medium
**Part of:** TD-110
**Blocked by:** until 2026-01-15

## TD-114: Items the grammar does not read

**Priority:** Low
**Blocked by:** decision (Kim Lee), until 2026-02-30, event (Big), until soon

## TD-115: The words read in any case, and the old form last

**Priority:** Low
**Blocked by:** Until 2026-02-01, EVENT (y), Decision (kim) — waits on the vendor, then TD-101

## TD-116: Waits alone is never a gate

**Priority:** Low
**Waits:** until 2026-02-01

## TD-117: A part naming one gate twice

**Priority:** Low
**Part of:** TD-110
**Blocked by:** decision (zed), decision (Zed), event (x)

**Ask:** zed says go.

## TD-118: A part waiting on a role

**Priority:** Low
**Part of:** TD-110
**Blocked by:** decision (designer)

## TD-119: An Ask with no Blocked by

**Priority:** Low
**Status:** Open

**Ask:** pat says which way.

## TD-120: An Ask waiting only on a date

**Priority:** Low
**Status:** Open
**Blocked by:** until 2026-02-01

**Ask:** pat says which way, once the date comes.

## TD-121: An Ask waiting only on an event

**Priority:** Low
**Status:** Open
**Blocked by:** event (shipped)

**Ask:** pat says whether the shipped build is right.

**Event (shipped):** the tools PR is merged.
check: pr-merged acme/tools#40

## TD-122: An Ask held in the header, no gate

**Priority:** Low
**Status:** Open
**Ask:** pat says which way.

## TD-123: An Ask answered by its lift

**Priority:** Low
**Status:** Open

**Ask:** pat says go.

**Log:**
- 2026-01-02: gate added: decision (pat)
- 2026-01-05: gate lifted: decision (pat) — by pat; answer "Go"

## TD-124: An Ask lifted, then its decision added again and dropped by hand

**Priority:** Low
**Status:** Open

**Ask:** pat says go, again.

**Log:**
- 2026-01-02: gate added: decision (pat)
- 2026-01-05: gate lifted: decision (pat) — by pat; answer "Go"
- 2026-01-07: gate added: decision (pat)

## TD-125: An Ask answered by an override

**Priority:** Low
**Status:** Open

**Ask:** pat says go.

**Log:**
- 2026-01-02: gate added: decision (pat)
- 2026-01-05: gate lifted: decision (pat) — by kim; override: pat is away and the date is fixed

## TD-126: An Ask waiting on a role

**Priority:** Low
**Status:** Open
**Blocked by:** decision (designer)

**Ask:** the designer says which way.

## TD-127: An Ask held by the retired hold

**Priority:** Low
**Status:** Open
**Blocked by:** hold

**Ask:** someone says which way.

## TD-128: An Ask whose decision names no person

**Priority:** Low
**Status:** Open
**Blocked by:** decision (the owner)

**Ask:** the owner says which way.

## TD-129: A qualified Ask lead, no gate

**Priority:** Low
**Status:** Open

**Ask (earlier):** pat said go.

## TD-130: An Ask lead inside a code fence, no gate

**Priority:** Low
**Status:** Open

**Why:** the lead below is quoted, not written.

```
**Ask:** pat says go.
```

## TD-131: Two decisions, one lifted and one still carried

**Priority:** Low
**Status:** Open
**Blocked by:** decision (kim)

**Ask:** pat and kim each say go.

**Log:**
- 2026-01-02: gate added: decision (pat)
- 2026-01-02: gate added: decision (kim)
- 2026-01-05: gate lifted: decision (pat) — by pat; answer "Go"

## TD-132: An answered Ask whose Log has a line no reader reads

**Priority:** Low
**Status:** Open

**Ask:** pat says go.

**Log:**
- 2026-01-02: gate added: decision (pat)
- 2026-01-05: gate lifted: decision (pat) — by pat; answer "Go"
- an undated line

## TD-133: A lift written above a later-dated gate added line

**Priority:** Low
**Status:** Open

**Ask:** pat says go.

**Log:**
- 2026-01-09: gate lifted: decision (pat) — by pat; answer "Go"
- 2026-01-03: gate added: decision (pat)
