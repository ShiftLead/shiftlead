"""What the tick's wiring fetches for an entry's `EntryFacts` (design §4.9c *The home acts only where no session will*,
TD-2051).

`ledger_read` reads the ledger and its archive once at a ref, and `entry_on` takes one entry's standing and own text
from that read. `protected_at` reads the repo's protected files from `.shiftlead.yml` at a ref, and `files_at` a pull
request's changed files at the head the caller read. Each answers None where it could not read, which is no reading:
above all a failed read of the protected files or of a pull request's files never passes a review. Nothing calls this
yet, and none of it writes anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from sessionorc import held, ledger, ledgerboard, reports
from shiftlead import repoconfig
from shiftlead.stage_read import EntryLedger, ledger_on, renumbered_on


class LedgerRead(NamedTuple):
    rel: str
    text: str
    archive: str | None


class EntryOn(NamedTuple):
    ledger: EntryLedger | None = None
    renumbered_to: str | None = None
    text: str | None = None


def ledger_read(root: Path | str, rel: str, ref: str) -> LedgerRead | None:
    """The ledger named `rel` and its archive at `ref`, either layout. None: the tree cannot be read, the ledger is not
    there, or it is faulted, whose files may not be read as they say."""
    io = ledger.git_io(root, ref, rel=rel)
    if io is None:
        return None
    path, text, archive, faults = ledger.read_pair(rel, io)
    return None if faults or text is None else LedgerRead(path, text, archive)


def entry_text(text: str, tid: str) -> str | None:
    """The one entry of the ledger's `text` whose id has `tid`'s number, from its heading to the next `## ` heading, or
    None. Comments are left out, as `ledgerboard.entries` reads them, so a commented-out template is no entry."""
    text = ledgerboard.COMMENT_RE.sub("", text)
    n = ledgerboard._num(tid)
    for m in ledgerboard.HEADING_RE.finditer(text):
        if ledgerboard._num(m.group(1)) == n:
            nxt = ledgerboard.SECTION_RE.search(text, m.end())
            return text[m.start() : nxt.start() if nxt else len(text)]
    return None


def entry_on(root: Path | str, ref: str, read: LedgerRead, tid: str) -> EntryOn:
    """Where `tid` stands in `read`, taken at `ref`: open with its own text, archived, or renumbered. An entry in
    neither file and not renumbered is the empty answer, no reading of it this pass."""
    standing = ledger_on(tid, read.text, read.archive)
    if standing is None:
        return EntryOn(renumbered_to=renumbered_on(root, ref, read.rel, tid))
    return EntryOn(standing, text=entry_text(read.text, tid) if standing.entry == "open" else None)


def protected_at(root: Path | str, ref: str) -> list[str] | None:
    """The repo's protected files, `.shiftlead.yml`'s `held:` at `ref`. Empty: the tree was read and holds no such file
    or no such key. None: it could not be read or is not valid, so an `only-when` stage keeps its review. This reads the
    file itself because `held.repo_key` answers an unreadable file with an empty list."""
    listed = ledger._git(root, "ls-tree", "--full-tree", "--name-only", ref, "--", repoconfig.FILE)
    if listed is None:
        return None
    if not listed.strip():
        return []
    text = ledger._git(root, "show", f"{ref}:{repoconfig.FILE}")
    if text is None:
        return None
    try:
        return repoconfig.held_for(repoconfig.load_text(text, root)) or []
    except ValueError:
        return None


def files_at(root: Path | str, pr: int, head: str | None) -> list[str] | None:
    """Pull request `pr`'s changed files, where its head is still `head` after they were read, so the list is that
    commit's. None: no head, a failed read, or a push or a close meanwhile."""
    if not head:
        return None
    files = held.paged_files(root, pr)
    if isinstance(files, str):
        return None
    row = reports.pr_state_row(root, pr)
    return files if row is not None and row.get("state") == "open" and row.get("head") == head else None
