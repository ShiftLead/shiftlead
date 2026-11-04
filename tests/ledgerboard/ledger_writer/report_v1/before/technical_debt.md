# Technical Debt

## TD-001: The parser drops a trailing comment

**Priority:** Medium
**Type:** debt
**Added:** 2026-01-02
**Status:** Open
**Location:** `src/parse.py`

**Why:** a comment at the end of a file is lost on a round trip.

**Fix:** keep the last comment.

## TD-002: A report for the weekly totals

**Priority:** Low
**Type:** feature
**Added:** 2026-01-03
**Owner:** builder
**Status:** Open
**Blocked by:** TD-001

**Why:** the totals are added up by hand each week.
