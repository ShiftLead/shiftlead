"""What the tick's wiring fetches for an entry's `EntryFacts` (design §4.9c *The home acts only where no session will*,
TD-2051).

`ledger_read` reads the ledger and its archive once at a ref, and `entry_on` takes one entry's standing and own text
from that read. `protected_at` reads the repo's protected files from `.shiftlead.yml` at a ref, and `files_at` a pull
request's changed files at the head the caller read. `facts_on` takes one entry's `EntryFacts` from what the pass read
once. Each answers None where it could not read, which is no reading: above all a failed read of the protected files
or of a pull request's files never passes a review, and a holder whose sessions were not read is never read as gone.
Nothing calls this yet, and none of it writes anything.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from sessionorc import held, ledger, ledgerboard, reports
from sessionorc.models import Session
from shiftlead import repoconfig
from shiftlead.stage_read import EntryFacts, EntryLedger, ledger_on, only_when_protected, renumbered_on, rows_for

TD_ID = re.compile(r"TD-[0-9]+")


class LedgerRead(NamedTuple):
    rel: str
    text: str
    archive: str | None
    file: Callable[[str], str | None]


class EntryOn(NamedTuple):
    ledger: EntryLedger | None = None
    renumbered_to: str | None = None
    text: str | None = None


def ledger_read(root: Path | str, rel: str, ref: str) -> LedgerRead | None:
    """The ledger named `rel` and its archive at `ref`, either layout. None: the tree cannot be read, the ledger is not
    there, or it is faulted, whose files may not be read as they say."""
    io = ledger.git_io(root, ref, under=ledger.common_parent(rel), rel=rel)  # both layouts sit in that directory
    if io is None:
        return None
    path, text, archive, faults = ledger.read_pair(rel, io)
    return None if faults or text is None else LedgerRead(path, text, archive, io[1])


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
    names = tuple(dict.fromkeys((tid, f"TD-{ledgerboard._num(tid):03d}")))  # a file's name may be padded, the id not
    if standing is None:
        return EntryOn(renumbered_to=next(filter(None, (renumbered_on(root, ref, read.rel, n) for n in names)), None))
    if standing.entry != "open":
        return EntryOn(standing)
    # a directory's entry is its whole file, so a `## ` line in a code fence cannot cut its Log off
    files = () if read.rel.endswith(".md") else (read.file(f"{read.rel}/{n}.md") for n in names)
    own = next((t for t in files if t is not None), None)
    return EntryOn(standing, text=own if own is not None else entry_text(read.text, tid))


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


def rows_of(
    prs: Mapping[str, Any] | None,
    wanted: Iterable[int],
    read_one: Callable[[int], Mapping[str, Any] | None],
) -> tuple[Mapping[str, Any], ...] | None:
    """The repo's rows from its pull request reading, for `RepoFacts.rows`. None: no reading, or one whose last read
    failed and so still holds old rows. The `recent` read comes after the `open` one, so its merges and closes come
    first; its open rows come last, since they lack the fork and filing marks only the `open` read carries."""
    if not isinstance(prs, Mapping) or "error" in prs:
        return None
    opened, recent = prs.get("open") or [], prs.get("recent") or []
    return rows_for(([r for r in recent if r.get("state") != "open"], opened, recent), wanted, read_one)


class TeamFlow(NamedTuple):
    """The flow a team's records are read against this pass. `doc` is what runs, `was` the copy it replaces where the
    two differ, `put` the text to store as the team's copy once the pass has read its records, and `problems` why the
    flow in use is the last good copy rather than the current flow."""

    doc: Mapping[str, Any]
    was: Mapping[str, Any] | None = None
    put: str | None = None
    problems: tuple[str, ...] = ()


def _flow_doc(text: str | None) -> Mapping[str, Any] | None:
    if not text:
        return None
    try:
        doc = repoconfig.parse_yaml(text)
    except (yaml.YAMLError, ValueError):
        return None
    return doc if isinstance(doc, Mapping) else None


def team_flow(current: str | None, problems: Collection[str], kept: str | None) -> TeamFlow | None:
    """Which flow runs (design §4.9c: *A flow that stops passing its check keeps its last good version in use*).
    `current` is the team's flow as read now (None: unreadable), `problems` its check's, and `kept` the team's copy on
    the state branch. A passing flow runs and is to replace the copy; any other runs the copy, with the problems to
    tell the person. None: neither can run, so the team's entries have no reading this pass."""
    doc = None if problems else _flow_doc(current)
    if doc is not None:
        same = current == kept
        return TeamFlow(doc, None if same else _flow_doc(kept), None if same else current)
    last = _flow_doc(kept)
    if last is None:
        return None
    return TeamFlow(last, problems=tuple(problems) or ("the flow could not be read",))


class SessionsRead(NamedTuple):
    sessions: Mapping[str, Session]
    read_nodes: frozenset[str]
    open_asks: frozenset[str]


def sessions_read(graph: Mapping[str, Session], snapshotted: Collection[str]) -> SessionsRead:
    """`RepoFacts`' sessions from the home's graph, whose keys are the addresses a holder is written in. `snapshotted`
    are the nodes whose link is up and has delivered its whole snapshot since it came up: a link just up holds no
    records yet, and a link down holds old ones, so neither says a session is gone. An open ask or steer in a session's
    outbox is a wait of its own, which keeps it from reading as silent (design §4.9c act 4)."""
    waits = frozenset(address for address, s in graph.items() if any(e.open for e in s.outbox))
    return SessionsRead(graph, frozenset(snapshotted), waits)


@dataclass(frozen=True)
class RepoFacts:
    """What the tick's pass read once for a team of a repo, for `facts_on` to take each entry's part of.

    `sessions` are the records by the address a stage record's holder is written in, and `read_nodes` the nodes whose
    sessions were read this pass, so a node nobody reached is never read as its session gone. `open_asks` are the
    addresses with an open ask of their own, `merging` the entries whose merge is in flight, and `was` the flow the
    team's records were written under, read before its copy is replaced. `may_start` and `within_size` are TD-2065's.
    """

    root: Path | str
    ref: str
    read: LedgerRead
    person: str
    team: str
    now: datetime
    doc: Mapping[str, Any]
    entries: tuple[dict[str, Any], ...] = ()
    teams: Collection[str] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    held: Collection[int] = ()
    branches: Collection[str] = ()
    protected: Collection[str] | None = None
    sessions: Mapping[str, Session] | None = None
    read_nodes: Collection[str] = ()
    open_asks: Collection[str] = ()
    merging: Collection[str] = ()
    was: Mapping[str, Any] | None = None
    may_start: bool = False
    within_size: bool = False


def _files_for(repo: RepoFacts, live: Mapping[str, Any] | None) -> tuple[str | None, list[str] | None]:
    """The head and files an `only-when` stage is judged on. Nothing is asked of the forge for any other record."""
    if live is None or repo.protected is None or not live.get("pr") or not only_when_protected(live, repo.doc):
        return None, None
    row = next((r for r in repo.rows if r.get("number") == live["pr"]), None)
    head = row.get("head") if row is not None and row.get("state") == "open" else None
    return (head, files_at(repo.root, live["pr"], head)) if head else (None, None)


def _row_of(entries: Iterable[dict[str, Any]], tid: str) -> dict[str, Any] | None:
    """`tid`'s row, by number since a file's id may be padded. A work order's row is no entry's, whatever its id."""
    n = ledgerboard._num(tid)
    for e in entries:
        if not e.get("work_order") and TD_ID.fullmatch(str(e.get("id"))) and ledgerboard._num(str(e["id"])) == n:
            return e
    return None


def facts_on(repo: RepoFacts, tid: str, record: Mapping[str, Any] | None) -> EntryFacts | None:
    """`tid`'s `EntryFacts` from the pass's reads. None: its holder's sessions could not be read (`sessions` None, or
    its node unread), so its absence says nothing, and reading it as gone would offer a live session's entry again."""
    live = record if record is not None and not record.get("closed_at") else None
    holder = str(live.get("holder") or "") if live else ""
    _, at, node = holder.partition("@")
    if holder and (repo.sessions is None or (at and node not in repo.read_nodes)):
        return None
    on = entry_on(repo.root, repo.ref, repo.read, tid)
    row = _row_of(repo.entries, tid)
    read_at, files = _files_for(repo, live)
    written_under = live.get("flow") if live else None
    return EntryFacts(
        tid=tid,
        person=repo.person,
        team=repo.team,
        now=repo.now,
        doc=repo.doc,
        ledger=on.ledger,
        renumbered_to=on.renumbered_to,
        text=on.text,
        entry=row,
        named=str(row.get("team") or "") or None if row else None,
        teams=repo.teams,
        rows=repo.rows,
        held=repo.held,
        branches=repo.branches,
        was=repo.was if repo.was is not None and repo.was.get("name") == written_under else None,
        session=repo.sessions.get(holder) if holder and repo.sessions is not None else None,
        open_ask=bool(holder) and holder in repo.open_asks,
        read_at=read_at,
        files=files,
        protected=repo.protected,
        merge_running=tid in repo.merging,
        may_start=repo.may_start,
        within_size=repo.within_size,
    )
