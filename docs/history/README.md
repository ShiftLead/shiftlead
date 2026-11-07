# The design's history, one file per ledger entry

The dated record of how the design (`docs/design.md`, `docs/design/`) came to say what it says, written from
the cut — the merge of TD-1513 — on (design §4.4 *Two PRs' records merge in either order*). Every line before
the cut is in [`../design-history.md`](../design-history.md), which is never written again.
`scripts/history.py <section>` prints a section's whole record from both; `grep -rn <text> docs/design-history.md
docs/history/` is the plain read.

**Which file.** A line goes to `TD-<n>.md`, the ledger entry of the PR that writes it — a design PR's, a
build's own, a bought round's own (TD-1510's, not TD-1453's) — the line naming any other entry it is about. A
PR that works for no entry writes `<YYYY-MM-DD>-<slug>.md`: the day the file is made, and the branch lowercased
with every character outside `[a-z0-9]` written `-` and runs collapsed (`td-fix/Board_Edit` →
`2026-11-07-td-fix-board-edit.md`). There is no subdirectory. A `TD-<n>.md` names an entry the ledger holds,
open or archived, so the entry is filed on the same branch or is already on main; the session that renumbers
an entry (`ledger.py renumber`) `git mv`s its history file in the same PR.

**The file's shape.** Only `## §<section>` headings, the section's number as `docs/design.md`'s index writes
it (`## §6`, `## §4.4a`, `## §4.10`; `## §title` for the title and status), each over that entry's dated
lines for the section — `- YYYY-MM-DD (…): …`, the machine's local day as `date` prints it, with indented
continuation lines if any. Blank lines are allowed anywhere; nothing else is (no `# ` title, no prose). A
later line is appended at its heading's end, a new heading at the file's end: the reader sorts the lines,
newest first, so two PRs for one entry that meet at a heading's tail resolve by keeping both lines.
`tests/test_history.py` holds this shape.
