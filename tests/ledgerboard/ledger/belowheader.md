# Ledger

Ledgerboard: 2

## TD-701: A decision gate written below the header block

**Priority:** Low

**Blocked by:** decision (Alex)

**Why:** the gate's line was typed after a blank line, so the reader lifts it and flags it.

**Ask:** say go on the export format.

## TD-702: A decision reassigned three times, after the entry above

**Priority:** Medium
**Blocked by:** decision (Sam)

**Why:** the check reads every entry, so this one's note still comes after the one above.

**Ask:** say go on the import format.

**Log:**
- 2026-01-02: gate added: decision (Robin)
- 2026-01-03: gate reassigned: decision (Robin) → decision (Alex) — by Robin; away
- 2026-01-04: gate reassigned: decision (Alex) → decision (Robin) — by Alex; back
- 2026-01-05: gate reassigned: decision (Robin) → decision (Sam) — by Robin; Sam owns it
