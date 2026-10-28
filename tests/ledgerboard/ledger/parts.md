# Technical Debt

---

## Summary

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| TD-030 | A parent with open parts | Medium | Open |
| TD-031 | Its first part | High | Open |
| TD-032 | Its second part, after the first | Low | Open |
| TD-034 | A parent whose parts are all archived | Medium | Open |
| TD-036 | A part of an archived parent | Medium | Open |
| TD-038 | A part of an unknown entry | Low | Open |
| TD-039 | A part of another repo's entry | Low | Open |
| TD-040 | A part of two parents | Low | Open |
| TD-043 | A parent its part waits on | Medium | Open |
| TD-044 | A part blocked by its parent | Medium | Open |
| TD-045 | A grandparent | Medium | Open |
| TD-046 | Its part, a parent | Medium | Open |
| TD-047 | A grandchild blocked by its grandparent | Medium | Open |
| TD-048 | A parent that still lists its parts as blockers | Medium | Open |
| TD-049 | A listed part | Medium | Open |
| TD-050 | A listed part of a part | Medium | Open |
| TD-051 | A part of itself | Low | Open |
| TD-052 | A part whose line is below the header | Low | Open |

---

## TD-030: A parent with open parts

**Priority:** Medium
**Status:** Open
**Type:** feature

## TD-031: Its first part

**Priority:** High
**Status:** Open
**Part of:** TD-030 (its first build)

## TD-032: Its second part, after the first

**Priority:** Low
**Status:** Open
**Part of:** TD-030
**Blocked by:** TD-031

## TD-034: A parent whose parts are all archived

**Priority:** Medium
**Status:** Open

## TD-036: A part of an archived parent

**Priority:** Medium
**Status:** Open
**Part of:** TD-037

## TD-038: A part of an unknown entry

**Priority:** Low
**Status:** Open
**Part of:** TD-099

## TD-039: A part of another repo's entry

**Priority:** Low
**Status:** Open
**Part of:** far#TD-005

## TD-040: A part of two parents

**Priority:** Low
**Status:** Open
**Part of:** TD-041, TD-042

## TD-043: A parent its part waits on

**Priority:** Medium
**Status:** Open

## TD-044: A part blocked by its parent

**Priority:** Medium
**Status:** Open
**Part of:** TD-043
**Blocked by:** TD-043

## TD-045: A grandparent

**Priority:** Medium
**Status:** Open

## TD-046: Its part, a parent

**Priority:** Medium
**Status:** Open
**Part of:** TD-045

## TD-047: A grandchild blocked by its grandparent

**Priority:** Medium
**Status:** Open
**Part of:** TD-046
**Blocked by:** TD-045

## TD-048: A parent that still lists its parts as blockers

**Priority:** Medium
**Status:** Open
**Blocked by:** TD-049, TD-050

## TD-049: A listed part

**Priority:** Medium
**Status:** Open
**Part of:** TD-048

## TD-050: A listed part of a part

**Priority:** Medium
**Status:** Open
**Part of:** TD-049

## TD-051: A part of itself

**Priority:** Low
**Status:** Open
**Part of:** TD-51

## TD-052: A part whose line is below the header

**Priority:** Low
**Status:** Open

The parent's card holds it all the same.

**Part of:** TD-030
