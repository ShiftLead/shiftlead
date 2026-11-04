# Technical Debt

Ledgerboard: 1

The plans are in [plans](plans/).

## Summary

| ID | Title |
|----|-------|
| TD-001 | The parser drops a trailing comment |

## TD-001: The parser drops a trailing comment

**Priority:** Medium
**Added:** 2026-01-02
**Status:** Open

**Why:** a comment is lost on a round trip; see [the plan](plans/parse.md#comments), [the exporter](technical_debt_archive.md#td-005-the-old-exporter-wrote-the-wrong-header) and [this entry](#td-001-the-parser-drops-a-trailing-comment).
