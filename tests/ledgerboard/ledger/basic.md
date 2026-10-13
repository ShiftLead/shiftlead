# Technical Debt

Fields: Owner = builder | designer; Kind = build | design-first

---

## Summary

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| TD-003 | Low debt first in its rank | Low | Open |
| TD-001 | A medium feature | Medium | Open |
| TD-002 | A high entry blocked on a decision | High | Open |
| TD-004 | Blocked by an open entry | Medium | Open |
| TD-005 | Blocked by an archived one | Medium | Open |
| TD-006 | Blocked in another repo | High | Open |
| TD-007 | Bad fields | Low | Open |

---

## TD-001: A medium feature

**Priority:** Medium
**Type:** feature
**Added:** 2026-01-02
**Owner:** builder
**Kind:** build
**Status:** Open
**Location:** `src/thing.py`

**Why:** a reason.

## TD-002: A high entry blocked on a decision

**Priority:** High
**Added:** 2026-01-03
**Status:** Open
**Blocked by:** decision (the owner) — the board, 2026-01-03 item

## TD-003: Low debt first in its rank

**Priority:** Low
**Added:** 2026-01-04
**Status:** Open

## TD-004: Blocked by an open entry

**Priority:** Medium
**Added:** 2026-01-05
**Status:** Open
**Blocked by:** TD-001

## TD-005: Blocked by an archived one

**Priority:** Medium
**Added:** 2026-01-06
**Status:** Open
**Blocked by:** TD-010

## TD-006: Blocked in another repo

**Priority:** High
**Added:** 2026-01-07
**Status:** Open
**Blocked by:** other-repo#TD-020, TD-099

## TD-007: Bad fields

**Priority:** Low
**Type:** chore
**Added:** 2026-01-08
**Owner:** nobody
**Status:** Open
**Blocked by:** soon, TD-001
**Pickable:** yes

**Kind:** build

<!-- Entry template:

## TD-001: Not an entry

**Priority:** High
-->
