# Technical Debt

Ledgerboard: 2

Known issues, compromises, and deferred work. Add an entry any time a problem is identified but not immediately fixed — no exceptions, however small (see [`cadence.md`](cadence.md) §2).

**This file holds open work only.** The summary table below lists exactly the entries that have a body in this file — one row each, no history. When an entry is fully resolved, move the whole body to [`technical_debt_archive.md`](technical_debt_archive.md), delete its summary row, and replace **Fix** with the resolution date plus a pointer to whichever doc/code now carries the lasting content. An entry that is only *partly* resolved stays here, with what shipped and what remains spelled out in its **Status**.

IDs are `TD-` plus a number zero-padded to three digits (four from TD-1000 on), assigned in order and never reused. Priority is a field, never part of the ID.

Two header lines follow **Added:** so a worker can filter the file instead of re-reading it (TD-118): **Owner** — who moves the entry next (`designer`, `grinder`, `paul`; the anchor seat is retired, design §4.9b *No anchor seat*). Another repo's work is never an entry here: it is filed on that repo's ledger, with `ao td add --repo <repo>` (its techlead drafts it), and what waits on it here names it as `<repo>#TD-NNN` in `Blocked by` (Paul, 2026-10-28); **Kind** — what the next step is (`build`, `design-first`, `live-check`, `evaluation`, `decision`). Every open entry carries them; keep them true when the Status changes. A third, **Waits**, is written only on an entry that is pickable and still waits on something no `Blocked by:` item names (TD-715, design §4.4 *An entry says what it waits for*): `until <date>` (*`**Waits:** until 2026-10-16 — CI runs on or after 10-16`*) or `event` (*`**Waits:** event — the next cadence-sync PR`*). What waits on the person is `Blocked by: decision (paul) — <what they must do>`, or `Owner: paul`, never a `Waits:` line. **Pickable is derived, never written** (cadence §2.4, TD-228): an entry is pickable while its `**Blocked by:**` names nothing still open and no decision, and no open entry is `Part of:` it, so what waits on another entry or on a person's word says so there, with its pointer; what nothing blocks and a grinder still cannot build — a live look, an evaluation, the person's edit — is said by its **Kind** or its **Owner**, and the Status says what is next. **Part of** (cadence §2.4, TD-1129) names the one parent an entry is a part of, in this ledger: each build of a design, and each subtask of a feature, writes `**Part of:** TD-n`, and the parent's own `Blocked by:` keeps only what must land first, never its parts (a part blocked by its parent is a cycle `ledger.py --check` refuses). A parent is ordered after its parts and archives with its last one, in that part's PR (design §4.9c *A design entry archives with its last build*); a design still listing its builds in `Blocked by:` is read the old way until it is backfilled. A `live-check` is followed on its line by its build's last merged PR — `**Kind:** live-check #<n>`, written by the PR that makes the entry a live check — and once that PR is live (`ao promote status`) the check is in a `free-pick` lane whose owner it has (design §4.9b, TD-320); cadence's script reads the word alone. A grinder's pick list is therefore `ao repo` (its pickable entries, a live check whose build is live among them), and `python3 scripts/ledger.py --list --pickable yes --owner grinder --kind build` lists the builds alone; the designer's is `--owner designer --kind design-first`. The line below is the one list of the **Owner** and **Kind** words (cadence §2.12): `scripts/ledger.py` flags a value outside it, and `tests/test_ledger.py` reads its sets from it and checks the two lines' shape, so a new word is added there and nowhere else.

Fields: Owner = designer | grinder | paul; Kind = build | design-first | live-check | evaluation | decision; Waits = until | event

---

---
<!-- Entry template:
## TD-001: Short title of the problem
**Priority:** High | Medium | Low
**Added:** YYYY-MM-DD
**Owner:** designer | grinder | paul | dev-cadence
**Kind:** build | design-first | live-check | evaluation | decision
**Status:** Open
**Location:** `path/to/file.py` (function/section)
**Why:** what's wrong, how it was found, and the reasoning — future sessions need the why, not just the symptom.
**Fix:** concrete direction(s), and what would count as done.
**Related:** other TDs, PRs, decision docs.
-->
