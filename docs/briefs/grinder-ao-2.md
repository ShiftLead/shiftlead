This is the shiftlead repo's part of the grinder brief for **grinder-ao-2**, the second grinder of the **ao-grind** team, beside its sibling **grinder-ao-1**.

**Your standing rules are your sibling's.** Read `docs/briefs/grinder-ao-1.md` in full and follow every paragraph of it — where you work, the first reads and **the reading rule under them (never read the design (`docs/design/`) or the ledger whole: `scripts/ledger.py --pickable`, then the entry and the sections it names)**, the live ShiftLead you run inside, *The gate here*, the lane's exclusions, the standing rules — as this repo's part of your brief beside this file. This file adds nothing to it but your name: the two grinders share one lane (below).

## One lane, both packages (TD-749, 2026-10-15)
The grinders no longer divide the code: you and grinder-ao-1 each pick the highest-ranked pickable entry nobody holds (`ao repo`'s order, design §4.8 *Choosing in a free-pick lane*), whether its fix is in `src/shiftlead/`, `src/sessionorc/` or both. Whose package an entry's files are in is no longer a reason to pass over a higher one — a sibling's lease is; held paths' review, not a file line, is what keeps a merge safe, and a conflict between the two of you costs a rebase.

- **A claim names the files it touches that a live sibling's claim also touches**: read your sibling's claims (`ao repo`, *holds* and *doing*) before yours, tell it with `ao msg` when they meet, and whichever of you merges second rebases right before its review.
- **A page change follows its design.** An entry whose Status says its design round has not landed is not pickable until it has: §4.5a first (a control that is not in that table does not exist) and the mockups from `docs/mockups/gen.py`.
