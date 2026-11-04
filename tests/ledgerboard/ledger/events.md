# Ledger

Ledgerboard: 2

## TD-201: An event with its section, its text holding quotes

**Priority:** Medium
**Blocked by:** event (vendor-ships)

**Why:** the vendor's copy must carry the release.

**Event (vendor-ships):** the vendor's repo carries the new release.
check: file-contains acme/vendor@main files/lib.py "say "v2.4" here"

## TD-202: One event with its section, one without

**Priority:** Medium
**Blocked by:** event (merged), event (shipped)

**Event (merged):** the tools PR is merged.
check: pr-merged acme/tools#12

## TD-203: Sections whose gates are gone

**Priority:** Low

**Event (lifted):** the deploy reached the commit.
check: ref-includes acme/tools@deploy/prod 0123abc

**Event (stale):** the page went live.
check: pr-merged acme/site#4

**Log:**
- 2026-01-02: filed by kim, session plan-1: "wait for the deploy"
- 2026-01-02: gate added: event (lifted)
- 2026-01-09: gate lifted: event (lifted) — by box-1; ref-includes passed; acme/tools@0123abcdef

## TD-204: A section named twice

**Priority:** Low
**Blocked by:** event (twice)

**Event (twice):** one.
check: pr-merged acme/tools#1

**Event (twice):** two.
check: pr-merged acme/tools#2

## TD-205: Sections the reader refuses

**Priority:** Low
**Blocked by:** event (no-check), event (two-checks), event (after), event (unknown), event (no-words), event (confined)

**Event (no-check):** nothing says how to tell.

**Event (two-checks):** two ways to tell.
check: pr-merged acme/tools#1
check: pr-merged acme/tools#2

**Event (after):** a line follows the check.
check: pr-merged acme/tools#1
and then some words.

**Event (unknown):** a type the format does not have.
check: url-up https://example.invalid/

**Event (no-words):**
check: pr-merged acme/tools#1

**Event (confined):** a path that climbs out.
check: file-contains acme/tools ../secrets "key"

**Event (Bad-Name):** a name outside the grammar.
check: pr-merged acme/tools#1
