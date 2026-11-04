# Technical Debt Archive

## Summary

| ID |
|----|
| TD-005 |

## TD-005: The old exporter wrote the wrong header

**Priority:** Low
**Added:** 2025-12-01
**Status:** Resolved 2025-12-20

**Why:** the header named the wrong column; the parser is [TD-001](technical_debt.md#td-001-the-parser-drops-a-trailing-comment).

**Resolved:** 2025-12-20 (PR #4) — `src/export.py`
