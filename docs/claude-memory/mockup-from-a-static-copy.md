---
name: mockup-from-a-static-copy
description: Mock a Sessions-page change by editing a static copy of the live page in Playwright; prefix the mockup's classes and never nest links
metadata:
  type: reference
---

A fast way to mock a change to a live ShiftLead page, with real data: read-only Playwright against the live UI ([[headless-screenshots-on-kmaster]]). Then:
1. read the numbers the mockup needs from the DOM;
2. save `outerHTML` with the `<script>`s stripped and a `<base href>` added;
3. `set_content` that copy and replace the part being redesigned with injected HTML and CSS;
4. shoot it at 1600 and 400 px.

Worked examples, one shape per argument: `docs/mockups/reviews/td1189-src/td1189_shots.py` and `docs/mockups/reviews/rollup-src/rollup_shots.py`.

Two traps from TD-1203 (2026-10-28); the second is what broke its rows:
- **Prefix every mockup class** (`ru-…`). `app.css` already defines short generic names — `.st`, `.off`, `.age`, `.grow`, `.row`, `.bar`, `.kind`, `.meta`, `.pill` — so an unprefixed mockup class can pick up the page's rules. Check a name against `app.css`, or prefix them all.
- **Never put a link inside a link.** Cloned page parts carry `<a class="bseg">` segments. Inside an `<a>` row, the HTML parser closes the outer link at the inner one, which scatters the row into empty boxes. Turn cloned links into `<span>`s, or make the row a non-link element.

Also: an empty `data-team=""` section is a repo's no-team strip (the person's sessions in that repo), not a duplicate repo.
