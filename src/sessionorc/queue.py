"""The Queue's reading (design §4.4 *The Queue: cards, and the rank that orders them*, TD-769).

The person asks *where is TD-n* and *are my teams working what matters first*; the Queue answers per
effort. This module is the one owner of its reading (§4.4 *Each reading has one owner*): from the
home's repo readings (each ledger's entries with their rank keys, settle marks and PRs), each repo's
archive, the live records' claims and the person inbox's waits, it derives the **cards** — one
connected component of the open ledgers' `Blocked by:` ids across repos, with no exception — their top
entry, rows, row states, the ledger's part of each card's status, keys and order, the **completed
cards** of the archive, and the **passed-over** flags. A pure reading: nothing here writes, and what
it reads of a file is the archive, cached by the file's blob sha. The mail a card carries and the
*needs you* it adds are `shiftlead.ui.queue`'s (screen 12), since `sessionorc` never reads the
person inbox's classification.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb
from sessionorc import rank as rank_mod
from sessionorc import workorders
from sessionorc.reports import branch_ref

# A red PR nobody holds reads *stalled* this long after its `red_since` (§4.4 *A row's state*): the
# red-PR work order told a worker at `ORPHAN_AFTER` already. Not §4.2's `STALL_AFTER`, another bound.
QUEUE_STALL_AFTER = timedelta(hours=24)
# Completed cards are served this far back, the page's widest window (*month*, §4.5 screen 12)
COMPLETED_WINDOW = timedelta(days=30)
# The card's status words, by need (§4.4 *The card's status*); the reading gives the ledger's part —
# *needs you* and *steer* are raised from the mail by the page
STATUSES = ("needs you", "steer", "stalled", "blocked", "waiting", "ready")
PERSON = ledger_mod.PERSON_OWNER
NO_LANE = ("evaluation", "other")  # the page kinds no lane takes (§4.4 *Repo facts*)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# an archived entry's `Resolved:` text as the page opens it (§4.5 screen 12 *Recently completed*), clipped
RESOLVED_CLIP = 600
RESOLVED_PR = re.compile(r"\(PR #(\d+)\)")
ANY_PR = re.compile(r"#(\d+)")
# an archived entry's `**Resolved:**` line, wherever its body writes it — most write it last, under the
# header block, where ledgerboard's `fields` do not reach
ENTRY_HEAD = re.compile(r"^## (TD-\d+):", re.M)
RESOLVED_LINE = re.compile(r"^\*\*Resolved:\*\*[ \t]*(.+)$", re.M)

# the archive's entries per file: (mtime_ns, size, blob sha, entries) — re-parsed only when its blob changes
_ARCHIVES: dict[str, tuple[Any, Any, str, list[dict[str, Any]]]] = {}  # `_archive_stat`, the text's sha, entries


def qid(repo: str, tid: str) -> str:
    """An entry across repos: `shiftlead#TD-769`, the id written `TD-NNN`."""
    return f"{repo}#{ledger_mod._norm(tid)}"


# an entry named in a mail item, a board line's `Context:` or a PR's title: `TD-n`, or `<repo>#TD-n`
TD_REF = re.compile(r"(?<![\w-])(?:([\w.-]+)#)?TD-(\d+)\b")


def refs(text: Any) -> list[str]:
    """The entries a text names, in order, each once: `TD-n` with its number as the ledger writes it."""
    seen: list[str] = []
    for repo, n in TD_REF.findall(str(text or "")):
        ref = f"{repo}#TD-{int(n):03d}" if repo else f"TD-{int(n):03d}"
        if ref not in seen:
            seen.append(ref)
    return seen


def card_index(reading: Mapping[str, Any] | None) -> dict[str, tuple[str, str]]:
    """The open cards' entries (§4.5 screen 6 *Where a row is drawn*): each `<repo>#TD-n` a card holds —
    its top entry and every row, an open card's archived rows among them — to `(card id, row qid)`, and
    the bare `TD-n` too where one repo alone holds it. An entry on a completed card, or on none, is in
    no card: the item that names it stays in the Inbox."""
    out: dict[str, tuple[str, str]] = {}
    bare: dict[str, set[str]] = {}
    for c in (reading or {}).get("cards") or []:
        if not isinstance(c, Mapping) or not c.get("top"):
            continue
        for r in [c["top"], *(c.get("rows") or [])]:
            q = str(r.get("qid") or "")
            got = refs(q)
            if "#" not in q or not got:
                continue
            out.setdefault(got[0], (str(c["id"]), q))
            bare.setdefault(got[0].partition("#")[2], set()).add(got[0])
    for tid, qs in bare.items():
        if len(qs) == 1:
            out[tid] = out[next(iter(qs))]
    return out


def mail_card(about: Any, words: str, index: Mapping[str, tuple[str, str]] | None) -> tuple[str, str] | None:
    """The `(card id, row qid)` a mail item is drawn on (§4.5 screen 6 *Where a row is drawn*): the entry
    its `about` names, else the first `TD-n` of `words` (its subject and text), where an open card holds
    it; None — its home is the Inbox — for the rest. The Inbox's own `item_home` and Telegram's link
    (§4.10 *What a message says*, TD-795) read it alike."""
    named = refs(about) or refs(words)
    return (index or {}).get(named[0]) if named else None


def blob_sha(data: bytes) -> str:
    """The git blob sha of a file's bytes, as `git hash-object` gives it."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _archive_stat(path: Path) -> tuple[Any, Any]:
    """The cache's first key: a file's mtime and size; a v2 `archive/` directory's mtime, and its entry
    files' count and newest mtime (§4.4 *Completed cards*' cache, TD-1144). Raises OSError as `stat` does."""
    st = path.stat()
    if not path.is_dir():
        return st.st_mtime_ns, st.st_size
    files = [f.stat().st_mtime_ns for f in path.iterdir() if lb.ENTRY_FILE_RE.match(f.name)]
    return st.st_mtime_ns, (len(files), max(files, default=0))


def archive_entries(path: Path) -> list[dict[str, Any]]:
    """ledgerboard's `entries()` of an archive — a v1 file, or a v2 ledger's `archive/` directory joined
    by `lb.load()` — cached by the sha of its text (a stat first, so an unchanged archive is not even read),
    each entry's `fields` carrying its `resolved` line wherever the body writes it. One that cannot be read
    has none."""
    key = str(path)
    try:
        st = _archive_stat(path)
    except OSError:
        _ARCHIVES.pop(key, None)
        return []
    got = _ARCHIVES.get(key)
    if got and (got[0], got[1]) == st:
        return got[3]
    if path.is_dir():
        data = lb.load(path.name, *ledger_mod.fs_io(path.parent))[0].encode()
    else:
        try:
            data = path.read_bytes()
        except OSError:
            return []
    sha = blob_sha(data)
    if got and got[2] == sha:
        _ARCHIVES[key] = (*st, sha, got[3])
        return got[3]
    text = ledger_mod.strip_comments(data.decode("utf-8", errors="replace"))
    ents = lb.entries(text)
    resolved: dict[str, str] = {}
    heads = list(ENTRY_HEAD.finditer(text))
    for i, h in enumerate(heads):
        body = text[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        if m := RESOLVED_LINE.search(body):
            resolved.setdefault(h.group(1), m.group(1).strip())
    for e in ents:
        if "resolved" not in e["fields"] and e["id"] in resolved:
            e["fields"] = {**e["fields"], "resolved": resolved[e["id"]]}
    _ARCHIVES[key] = (*st, sha, ents)
    return ents


def _when(value: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _same_dir(a: Any, b: Any) -> bool:
    if not a or not b:
        return False
    try:
        return Path(str(a)).resolve() == Path(str(b)).resolve()
    except OSError:
        return False


class _Repos:
    """The readings by repo name, and the lookups a `<repo>#TD-n` item and a record's `repo` need."""

    def __init__(self, repos: Mapping[str, Mapping[str, Any]]) -> None:
        self.by_name: dict[str, Mapping[str, Any]] = {}
        self.roots: dict[str, str] = {}
        self.origins: dict[str, str] = {}
        for root, r in repos.items():
            led = r.get("ledger") if isinstance(r, Mapping) else None
            if not isinstance(led, Mapping) or not isinstance(led.get("entries"), list):
                continue  # a reading that failed, or none yet: nothing of it is drawn
            name = str(r.get("name") or Path(str(root)).name)
            self.by_name[name] = r
            self.roots[name] = str(r.get("root") or root)
            self.origins[name] = str(r.get("remote") or "").lower().removesuffix("/").removesuffix(".git")

    def resolve(self, repo: str) -> str | None:
        """The name of the one reading a `<repo>` of an item names: a checkout's directory name, or
        `owner/name` of its origin; none, or two, is None."""
        want = repo.lower()
        if "/" in want:
            hits = [n for n, o in self.origins.items() if o.endswith(("/" + want, ":" + want))]
        else:
            hits = [n for n in self.by_name if n.lower() == want]
        return hits[0] if len(hits) == 1 else None

    def of_record(self, rec: Any) -> str | None:
        """The reading a record works in: its `repo`, the checkout's root."""
        for name, root in self.roots.items():
            if _same_dir(getattr(rec, "repo", None), root):
                return name
        return None


def _resolved_pr(fields: Mapping[str, str]) -> int | None:
    line = str(fields.get("resolved") or "")
    m = RESOLVED_PR.search(line) or ANY_PR.search(line)
    return int(m.group(1)) if m else None


def _resolved_date(fields: Mapping[str, str]) -> str:
    m = DATE.search(str(fields.get("resolved") or ""))
    return m.group(0) if m else ""


def _resolved_text(fields: Mapping[str, str]) -> str:
    line = " ".join(str(fields.get("resolved") or "").split())
    return line if len(line) <= RESOLVED_CLIP else line[: RESOLVED_CLIP - 1].rstrip() + "…"


def _closed(fields: Mapping[str, str], close: Mapping[str, Any] | None) -> str:
    """When an archived entry closed: the closing commit's time where the repo reading's *What closed*
    holds it (TD-604), else its `Resolved:` date — what the page's windows count by."""
    return str((close or {}).get("closed") or "") or _resolved_date(fields)


def _closed_order(closed: str) -> datetime:
    """A close as an instant to order by: a commit's time, else a `Resolved:` date as the end of its day."""
    when = _when(closed if not DATE.fullmatch(closed) else f"{closed}T23:59:59+00:00")
    return when or datetime.min.replace(tzinfo=UTC)


def _key_sort(key: str, q: str) -> tuple[tuple[int, ...], int, str]:
    repo, _, tid = q.partition("#")
    return lb.key_order(key), int(tid[3:]), repo


def _holder_stuck(rec: Any, waiting: Collection[str], now: datetime) -> bool:
    """Whether a claim's holder reads idle or stuck (§4.4 *A row's state*, the holder state of TD-734
    as `sessionorc` can read it): `stalled?`, or `idle` with nothing it waits on — no open question of
    the person's or a reader's, no live subagent or background shell of its own."""
    from sessionorc import agent_common  # the tick's readers; imported late, as the agent's modules import this

    if rec.state == "stalled?":
        return True
    if rec.state != "idle" or rec.id in waiting:
        return False
    return not (agent_common.subagents_live(rec, now) or agent_common.shells_live(rec, now))


def reading(
    repos: Mapping[str, Mapping[str, Any]],
    records: Iterable[Any],
    now: datetime,
    *,
    waiting: Collection[str] = (),
    doing: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """The `queue` reading (§4.4 *The Queue*): `{cards, completed, other_work, at}`.

    `repos` are the home's repo readings by root; `records` the live graph's `Session`s (an ended one
    holds nothing); `waiting` the ids of sessions that wait on a question (the person's, or a reader
    holding their ask), which keeps an idle holder from reading *stalled*; `doing` the doing log by
    team (`{team: [{id, text, at}]}`), whose first line after a claim is a passed-over flag's reason.

    Each **card**: `id` (its top entry's `<repo>#TD-n`), `key` and `lined`, `top` and `rows` (each a row:
    `qid`, `repo`, `id`, `title`, `priority`, `state` — the one word of §4.4 *A row's state*, '' for a
    row that waits on the person, whose `needs` says how — `pr`, `holder`, `parent`, `depth`,
    `after` (its open blockers, *after TD-n*, TD-1130), `archived`, `key`), `done` and `of` (*d/m done*),
    `status` (the ledger's part), `group`
    (`in_progress`, `waiting` or `up_next`), `wait` (a Waiting card's `{column, phrase, id}`, else None;
    §4.4 *Waiting*, TD-918), `place` (Up next numbered from 1) and `places` (one `{repo, n}` per repo of its
    open members, numbered among that repo's Up next cards, TD-901), `would_be` (a Waiting card's `{repo, n}`
    per repo: its place in Up next once the wait ends), `start` (the `<repo>#TD-n` a **Start session** on the
    card starts on, `_start`, TD-912), `order` (the open members in pick order: dependency, then key), `repos`,
    `passed_over`. Cards are in key order, In progress first.
    **Completed** cards (`ids`, `top`, `titles`, `closed`, `pr`) are the archive's components no open
    entry touches, closed within `COMPLETED_WINDOW`, newest first. `other_work` is each live claim that
    names no open entry (`board:<key>`, a PR naming none), with its holder."""
    rs = _Repos(repos)
    recs = [r for r in records if getattr(r, "state", "") not in ("exited", "closed") and not r.superseded_by]
    open_: dict[str, dict[str, Any]] = {}
    for name, r in rs.by_name.items():
        for e in r["ledger"]["entries"]:
            if isinstance(e, Mapping) and e.get("id"):
                open_.setdefault(qid(name, e["id"]), {**e, "repo": name})
    archived: dict[str, dict[str, Any]] = {}  # every archived entry, by qid
    for name, r in rs.by_name.items():
        path = ledger_mod.archive_of(rs.roots[name], str(r["ledger"].get("path") or ledger_mod.DEFAULT))
        for a in archive_entries(path):
            archived.setdefault(qid(name, a["id"]), {**a, "repo": name})
    closed_at: dict[str, Mapping[str, Any]] = {}  # *What closed* (TD-604): the closing commit's time and PR
    for name, r in rs.by_name.items():
        for c in r.get("completed") or []:
            if isinstance(c, Mapping) and c.get("id"):
                closed_at.setdefault(qid(name, c["id"]), c)

    def xref(item: str) -> str | None:
        m = lb.XREPO_ITEM_RE.match(item)
        name = rs.resolve(m.group(1)) if m else None
        return qid(name, m.group(2)) if m and name else None

    # the edges: an open member's `Blocked by:` ids, local and `<repo>#`, and its `Part of:` parent, in both
    # directions (TD-1130)
    adj: dict[str, set[str]] = {q: set() for q in open_}
    blockers: dict[str, set[str]] = {q: set() for q in open_}  # the open members each one is blocked by
    parts: dict[str, set[str]] = {q: set() for q in open_}  # the open members naming each one in `Part of:`
    up: dict[str, str] = {}  # an entry, open or archived → its `Part of:` parent, open or archived
    touch: dict[str, set[str]] = {q: set() for q in open_}  # the archived entries one hop from each
    for q, e in open_.items():
        named = [qid(e["repo"], b) for b in e.get("blocked_ids") or []]
        named += [x for x in map(xref, e.get("xrepo_ids") or []) if x]
        for n in named:
            if n in open_ and n != q:
                adj[q].add(n)
                adj[n].add(q)
                blockers[q].add(n)
            elif n in archived:
                touch[q].add(n)
        if e.get("part_of") and (n := qid(e["repo"], str(e["part_of"]))) != q:
            if n in open_:
                adj[q].add(n)
                adj[n].add(q)
                parts[n].add(q)
                up[q] = n
            elif n in archived:  # an archived parent: a done group head over its open parts
                touch[q].add(n)
                up[q] = n
    names_open: dict[str, set[str]] = {}  # an archived entry → the open members its `Blocked by:` or `Part of:` names
    for a_q, a in archived.items():
        ids, _, _ = lb.parse_blocked(a.get("blocked_raw") or "") if a.get("blocked_raw") else ([], [], [])
        for b in ids:
            n = xref(b) if "#" in b else qid(a["repo"], b)
            if n in open_:
                names_open.setdefault(a_q, set()).add(n)
                touch[n].add(a_q)
        if (par := lb.parse_part_of(a.get("part_of_raw"))[0]) and (n := qid(a["repo"], par)) in open_:
            names_open.setdefault(a_q, set()).add(n)  # an archived part of an open parent: its done row
            touch[n].add(a_q)
            up[a_q] = n

    # an open member blocked past the org's reach (§4.4 *Blocked*): a decision not the person's, an id in
    # no reading (an unknown id keeps its block), a `<repo>#TD-n` no reading holds open, or an item
    # ledgerboard cannot read
    for e in open_.values():
        for b in e.get("blocked_by") or []:
            if m := re.fullmatch(r"decision \((.+)\)", b):
                far = m.group(1).strip().lower() != PERSON
            elif re.fullmatch(r"TD-\d+", b):
                far = qid(e["repo"], b) not in open_
            elif "#" in b:
                far = xref(b) not in open_
            else:
                far = True
            if far:
                # the first such item's phrase, what a Waiting card's `wait` says (§4.4 *Waiting*)
                e.setdefault("unreachable", b if b.startswith("decision (") else f"{b} unresolved")
        # the components (union-find over the open members)
    parent = {q: q for q in open_}

    def find(q: str) -> str:
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q

    for q, ns in adj.items():
        for n in ns:
            parent[find(n)] = find(q)
    comps: dict[str, list[str]] = {}
    for q in open_:
        comps.setdefault(find(q), []).append(q)

    # who holds what: a live claim on a reading's entry, an open PR naming one
    held: dict[str, list[Any]] = {}
    other: list[dict[str, Any]] = []
    for rec in recs:
        home = rs.of_record(rec)
        for p in rec.progress:
            if p.status != "claimed":
                continue
            if home and (q := qid(home, p.ref) if re.fullmatch(r"TD-\d+", p.ref) else None) in open_:
                held.setdefault(q, []).append((rec, p))
            else:  # `board:<key>`, a PR, or an id no reading holds open
                other.append({"ref": p.ref, "pr": p.pr or p.review_pr, "holder": _holder(rec)})
    prs: dict[str, dict[str, Any]] = {}  # an open entry → the open PR that names it
    for name, r in rs.by_name.items():
        for pr in (r.get("prs") or {}).get("open") or []:
            if not isinstance(pr, Mapping) or not isinstance(pr.get("number"), int):
                continue
            ref = branch_ref(pr.get("branch"))
            if ref and (q := qid(name, ref)) in open_:
                prs.setdefault(q, dict(pr))
        for q, claims in held.items():
            if open_[q]["repo"] != name or q in prs:
                continue
            for _rec, p in claims:
                n = p.pr or p.review_pr
                pr = next((x for x in (r.get("prs") or {}).get("open") or [] if x.get("number") == n), None)
                if pr is not None:
                    prs[q] = dict(pr)
                    break

    def row(q: str) -> dict[str, Any]:
        if q in open_:
            e = open_[q]
            st, needs, mine = _state(e, held.get(q, []), prs.get(q), recs, set(waiting), now)
            claim = held.get(q)
            return {
                "qid": q,
                "repo": e["repo"],
                "id": e["id"],
                "title": e.get("title") or "",
                "priority": e.get("priority") or "",
                "state": st,
                "needs": needs,
                "pr": (prs.get(q) or {}).get("number"),
                # the person's own session holding their entry is its holder whatever else claims it (TD-1281)
                "holder": mine or (_holder(claim[0][0]) if claim else None),
                "with_you": mine["name"] if mine else None,
                # what the row's controls read (§4.5 screen 12 *any open row*, TD-905): its page kind, an open
                # id in its `Blocked by:` or an open part, and a design's open builds (`ledger.builds_open`, TD-1130)
                "page": str(e.get("for_page") or ""),
                # what it waits on, apart from its state word: each open blocker, *after TD-n* (TD-1130)
                "after": sorted(blockers.get(q) or (), key=lambda b: _key_sort(str(open_[b].get("key") or ""), b)),
                "blocked_open": bool(blockers.get(q)) or bool(e.get("parts_open")),  # an open part counts (TD-1130)
                "builds_open": ledger_mod.builds_open(e),
                "key": e.get("key") or "",
                "lined": bool(e.get("lined")),
                "archived": False,
            }
        a = archived[q]
        pr = _resolved_pr(a["fields"])
        return {
            "qid": q,
            "repo": a["repo"],
            "id": a["id"],
            "title": a.get("title") or "",
            "priority": (a.get("priority") or "").lower(),
            "state": f"done #{pr}" if pr else "done",
            "needs": None,
            "pr": pr,
            "holder": None,
            "with_you": None,
            "page": "",
            "after": [],
            "blocked_open": False,
            "builds_open": False,
            "key": "",
            "lined": False,
            "archived": True,
            "closed": _closed(a["fields"], closed_at.get(q)),
            "sha": (closed_at.get(q) or {}).get("sha"),  # the closing commit, the page's live mark (TD-904)
            "resolved": _resolved_text(a["fields"]),
        }

    cards: list[dict[str, Any]] = []
    for members in comps.values():
        cards.append(_card(members, open_, blockers, parts, up, touch, row))
    for c in cards:
        if any(q in held or q in prs for q in c["members"]):
            c["group"], c["wait"] = "in_progress", None  # In progress whatever `waits` says (§4.4 *Waiting*)
        else:
            c["group"] = "waiting" if c["wait"] else "up_next"
    cards.sort(key=lambda c: (c["group"] != "in_progress", _key_sort(c["key"], c["id"])))
    rank_mod.number(cards)
    _passed_over(cards, open_, held, recs, rs, doing or {})
    for c in cards:
        del c["members"]
    return {
        "cards": cards,
        "completed": _completed(archived, open_, names_open, closed_at, xref, now),
        "other_work": other,
        "at": now.isoformat(),
    }


def _holder(rec: Any) -> dict[str, Any]:
    return {"id": rec.id, "name": rec.name, "state": rec.state}


def _state(
    e: Mapping[str, Any],
    claims: list[tuple[Any, Any]],
    pr: Mapping[str, Any] | None,
    recs: list[Any],
    waiting: set[str],
    now: datetime,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """A row's one state word, the first that applies (§4.4 *A row's state*), what it needs of the person —
    `owner` (`Owner: paul`) or `decision` (`decision (paul)`) — when it waits on them, which draws no word, and
    the person's own session where one holds such an entry: the first by id of its claims' records with
    `unattended: false`, whose name the word *with you in <name>* carries (TD-1281). The row keeps its need."""
    need = (
        "owner"
        if str(e.get("owner") or "").lower() == PERSON
        else "decision"
        if ledger_mod.decided_by(dict(e), PERSON)
        else None
    )
    if need:
        own = sorted((rec for rec, _ in claims if not getattr(rec, "unattended", False)), key=lambda r: str(r.id))
        if own:
            return f"with you in {own[0].name}", need, _holder(own[0])
        return "", need, None
    return _state_word(e, claims, pr, recs, waiting, now), None, None


def _state_word(
    e: Mapping[str, Any],
    claims: list[tuple[Any, Any]],
    pr: Mapping[str, Any] | None,
    recs: list[Any],
    waiting: set[str],
    now: datetime,
) -> str:
    """The state word of a row that needs nothing of the person, the first that applies (§4.4)."""
    red = pr is not None and (pr.get("conflicting") or pr.get("checks") == "red" or pr.get("failing"))
    if any(_holder_stuck(rec, waiting, now) for rec, _ in claims):
        return "stalled"
    if red and not claims:
        since = _when(pr.get("red_since"))
        if since and now - since >= QUEUE_STALL_AFTER and not any(workorders.holds_pr(r, dict(pr)) for r in recs):
            return "stalled"
    if red:
        word = f"#{pr['number']} conflicting" if pr.get("conflicting") else f"#{pr['number']} failing"
        return word + (" · being fixed" if claims else "")
    if pr is not None:
        return f"in review #{pr['number']}"
    if claims:
        return f"held by {claims[0][0].name}"
    if e.get("settling"):
        return "settling"
    w = e.get("waiting")
    if isinstance(w, Mapping):
        return f"waits until {w.get('until')}" if w.get("on") == "until" else "waits on an event"
    opened = [b for b in e.get("blocked_by") or [] if re.fullmatch(r"(?:[\w./-]+#)?TD-\d+", b)]
    if opened or e.get("parts_open"):  # an open blocker or an open part; the row's `after` names the blockers
        return "waiting"
    return "ready"


def _card(
    members: list[str],
    open_: Mapping[str, Mapping[str, Any]],
    blockers: Mapping[str, set[str]],
    parts: Mapping[str, set[str]],
    up: Mapping[str, str],
    touch: Mapping[str, set[str]],
    row: Any,
) -> dict[str, Any]:
    """One card from its open members: the top entry, the rows' tree, its archived rows, its key, its
    pick order and the ledger's part of its status. The tree is `Part of:` alone (§4.4 *Rows*, TD-1130):
    a row's `parent` is its `Part of:` parent where that is on the card, open or archived, else None (a
    loose row); a blocker is the row's `after`, never an edge."""
    inside = set(members)
    keyed = {q: str(open_[q].get("key") or "") for q in members}
    lined = [q for q in members if open_[q].get("lined")]
    key = min((keyed[q] for q in lined), key=lb.key_order, default=None) or min(keyed.values(), key=lb.key_order)

    def best(qs: Iterable[str]) -> str:
        return min(qs, key=lambda q: _key_sort(keyed[q], q))

    # the top entry: the open root parent with the best key — an open member with an open part on the card
    # that names no open parent on it — else the rule from before (§4.4 *The top entry*)
    roots = [q for q in members if parts[q] & inside and up.get(q) not in inside]
    designs = [q for q in members if open_[q].get("kind") == "design-first"]
    tops = roots or [q for q in designs if not any(b in inside and b in designs for b in blockers[q])]
    tops = tops or [q for q in members if not blockers[q] & inside]
    top = best(tops or members)
    # the pick order within the card: after every member it is blocked by and every open part, else by key
    left, picked = set(members), []
    while left:
        ready = [q for q in left if not (blockers[q] | parts[q]) & left] or list(left)
        q = best(ready)
        picked.append(q)
        left.discard(q)
    # archived rows: one hop from an open member, by either field
    done_rows = sorted({a for q in members for a in touch[q]})
    on_card = inside | set(done_rows)
    pi = {q: n for n, q in enumerate(picked)}

    def parent_of(q: str) -> str | None:
        p = up.get(q)
        return p if p in on_card and p != q and q != top else None

    kids: dict[str | None, list[str]] = {}
    for q in [*members, *done_rows]:
        if q != top:
            kids.setdefault(parent_of(q), []).append(q)

    def first(q: str, seen: frozenset[str] = frozenset()) -> float:
        """The pick place of a group's first open member: the order its group is drawn in."""
        if q in seen:
            return float("inf")
        own = pi.get(q, float("inf"))
        return min([own, *(first(k, seen | {q}) for k in kids.get(q) or ())])

    def place(q: str) -> tuple[float, str]:
        return (pi[q], q) if q in pi else (float("inf"), q)  # open parts in pick order, then archived by id

    rows: list[dict[str, Any]] = []
    drawn: set[str] = {top}

    def walk(q: str, depth: int) -> None:
        for k in sorted(kids.get(q) or (), key=place):
            if k in drawn:
                continue
            drawn.add(k)
            p = parent_of(k)
            rows.append({**row(k), "parent": p, "depth": depth})
            walk(k, depth + 1)

    walk(top, 1)
    for q in sorted(kids.get(None) or (), key=lambda q: (first(q), q)):
        if q not in drawn:
            drawn.add(q)
            rows.append({**row(q), "parent": None, "depth": 1})
            walk(q, 2)
    for q in [*members, *done_rows]:  # a cycle of `Part of:` lines no walk reached: loose, never lost
        if q not in drawn:
            drawn.add(q)
            rows.append({**row(q), "parent": None, "depth": 1})
    top_row = {**row(top), "parent": None, "depth": 0}
    open_rows = [top_row, *(r for r in rows if not r["archived"])]
    return {
        "id": top,
        "key": key,
        "lined": bool(lined),
        "top": top_row,
        "rows": rows,
        "done": len(done_rows),
        "of": len(members) + len(done_rows),
        "status": _status(open_rows, [open_[q] for q in members]),
        "wait": _wait(members, open_, blockers, parts, keyed, top),
        "start": _start(members, open_, keyed, top),
        "order": picked,
        "repos": sorted({open_[q]["repo"] for q in members}),
        "members": members,
        "passed_over": [],
    }


def _start(members: list[str], open_: Mapping[str, Mapping[str, Any]], keyed: Mapping[str, str], top: str) -> str:
    """The entry a **Start session** on the card starts on (§4.4 *One owner*, TD-912): its one `Owner: paul`
    entry, else its first `decision (paul)` entry by key, else the top entry — by key alone, never by what
    is claimed, so two presses choose the same entry."""
    by_key = sorted(members, key=lambda q: _key_sort(keyed[q], q))
    owned = [q for q in by_key if str(open_[q].get("owner") or "").lower() == PERSON]
    if len(owned) == 1:
        return owned[0]
    return next((q for q in by_key if ledger_mod.decided_by(dict(open_[q]), PERSON)), top)


def card_entries(card: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """A card's open entries as **Start session**'s prompt names them (§4.5 screen 12 *Three verbs: Start
    session*, TD-912): *waits on me*, its Decide and Do ledger entries (a row whose `needs` is set; a
    `needs` row with `with_you` is no want though it is listed here, TD-1281), and *the rest*, every
    other open member — each a `<repo>#TD-n`, in key order."""
    rows = [r for r in [card.get("top"), *(card.get("rows") or [])] if isinstance(r, Mapping) and not r.get("archived")]
    rows.sort(key=lambda r: _key_sort(str(r.get("key") or ""), str(r.get("qid") or "")))
    mine = [str(r["qid"]) for r in rows if r.get("needs")]
    return mine, [str(r["qid"]) for r in rows if not r.get("needs")]


def _status(rows: list[dict[str, Any]], ents: list[Mapping[str, Any]]) -> str:
    """The ledger's part of a card's status (§4.4 *The card's status*): *needs you* > *stalled* > *blocked*
    > *waiting* > *ready*; *steer*, and a question's *needs you*, are the mail's. A row the person's own
    session holds (`with_you`, TD-1281), which keeps its `needs`, is no need."""
    if any(r["needs"] and not r.get("with_you") for r in rows):
        return "needs you"
    if any(r["state"] == "stalled" for r in rows):
        return "stalled"

    def waits(e: Mapping[str, Any]) -> bool:
        if e.get("waiting") or e.get("waits") or e.get("settling"):
            return True
        if e.get("kind") == "live-check" and e.get("live") != "yes":
            return True
        # blocked only by open ids
        ids = list(e.get("blocked_by") or [])
        # an open part counts as an open id its parent is blocked by (TD-1130)
        return bool(ids or e.get("parts_open")) and all(not b.startswith("decision (") for b in ids)

    if any(e.get("unreachable") for e in ents) or all(e.get("for_page") in NO_LANE for e in ents):
        return "blocked"
    if all(waits(e) for e in ents):
        return "waiting"
    return "ready"


def _own(e: Mapping[str, Any]) -> bool:
    """The person's own member (§4.4 *Waiting*): `Owner: paul` or `Blocked by: decision (paul)`."""
    return str(e.get("owner") or "").lower() == PERSON or ledger_mod.decided_by(dict(e), PERSON)


def _wait(
    members: list[str],
    open_: Mapping[str, Mapping[str, Any]],
    blockers: Mapping[str, set[str]],
    parts: Mapping[str, set[str]],
    keyed: Mapping[str, str],
    top: str,
) -> dict[str, str] | None:
    """A card's `waits` and what it waits for (§4.4 *Waiting*, TD-918): None when it does not wait, else
    `{column, phrase, id}` read from a leaf. `waits` holds when every open member that is not the person's
    own waits — a `Waits:` line in force, a live check whose build is not live, settling, blocked by open
    ids or open parts once the person's own are set aside, blocked past the org's reach, or no lane takes it — and at
    least one is not the person's own. The leaf is a member that waits for a reason of its own, the first
    that applies: the top entry with a `Waits:` line, the earliest `Waits:` date, an event, settling, a
    live check not live, past reach — ties by key; a cycle of open ids with none is read as past reach."""
    own = {q for q in members if _own(open_[q])}
    rest = [q for q in members if q not in own]

    def by_key(q: str) -> tuple[tuple[int, ...], int, str]:
        return _key_sort(keyed[q], q)

    def far(e: Mapping[str, Any]) -> bool:
        return bool(e.get("unreachable")) or e.get("for_page") in NO_LANE

    def not_live(e: Mapping[str, Any]) -> bool:
        return e.get("kind") == "live-check" and e.get("live") != "yes"

    def of_its_own(q: str) -> bool:
        e = open_[q]
        return bool(e.get("waiting") or e.get("settling")) or not_live(e) or far(e)

    if not rest or not all(of_its_own(q) or (blockers[q] | parts[q]) - own for q in rest):
        return None
    home = top.partition("#")[0]

    def show(q: str) -> str:
        repo, _, tid = q.partition("#")
        return tid if repo == home else q

    def waited(q: str) -> dict[str, str] | None:
        w = open_[q].get("waiting")
        if not isinstance(w, Mapping):
            return None
        if w.get("on") == "until" and DATE.fullmatch(str(w.get("until") or "")):
            day = date.fromisoformat(str(w["until"]))
            words = f"{day:%b} {day.day}"
            return {"column": words, "phrase": f"waits until {words}", "id": q}
        why = str((open_[q].get("waits") or {}).get("why") or "") if isinstance(open_[q].get("waits"), Mapping) else ""
        return {"column": "event", "phrase": f"waits on {why}" if why else "waits on an event", "id": q}

    leaves = sorted((q for q in rest if of_its_own(q)), key=by_key)
    if top in leaves and open_[top].get("waiting"):
        return waited(top)
    dated = [q for q in leaves if (open_[q].get("waiting") or {}).get("until")]
    if dated:
        return waited(min(dated, key=lambda q: (str(open_[q]["waiting"]["until"]), by_key(q))))
    for q in leaves:
        if open_[q].get("waiting"):
            return waited(q)
    for q in leaves:
        if open_[q].get("settling"):
            return {"column": "settling", "phrase": "settling", "id": q}
    for q in leaves:
        if not_live(open_[q]):
            built = " ".join(f"#{n}" for n in open_[q].get("built") or ())
            return {"column": "not live", "phrase": f"not live {built}".strip(), "id": q}
    for q in leaves:
        e = open_[q]
        said = e.get("unreachable") if isinstance(e.get("unreachable"), str) else "no lane takes it"
        return {"column": "blocked", "phrase": f"blocked: {said}", "id": q}
    # no leaf: the rest wait on each other's ids alone, so a cycle runs through them; read from its
    # lowest-keyed member as past reach
    seen: list[str] = []
    q = min(rest, key=by_key)
    while q not in seen:
        seen.append(q)
        q = min((blockers[q] | parts[q]) - own, key=by_key)  # an open part waits as an open id does
    loop = sorted(seen[seen.index(q) :], key=by_key)
    names = [show(x) for x in loop]
    said = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return {"column": "blocked", "phrase": f"blocked: {said} block each other", "id": loop[0]}


def _passed_over(
    cards: list[dict[str, Any]],
    open_: Mapping[str, Mapping[str, Any]],
    held: Mapping[str, list[tuple[Any, Any]]],
    recs: list[Any],
    rs: _Repos,
    doing: Mapping[str, list[Mapping[str, Any]]],
) -> None:
    """**Passed over** (§4.4 *The rank is the pick order*): a worker holding a card ranked below an
    unclaimed pickable card in its own lane flags the card passed over, with the reason its claim's
    first `ao doing` line gives; a settling or waiting entry never triggers it."""
    rank = sorted(cards, key=lambda c: _key_sort(c["key"], c["id"]))
    at = {c["id"]: i for i, c in enumerate(rank)}
    for q, claims in held.items():
        mine = next(c for c in cards if q in c["members"])
        for rec, p in claims:
            if not rec.lane or not rec.unattended:
                continue
            home = rs.of_record(rec)  # once per claim, not per member: it resolves a path per repo
            for c in rank[: at[mine["id"]]]:
                if c is mine or c["group"] != "up_next":
                    continue
                takes = [
                    m
                    for m in c["members"]
                    if open_[m].get("pickable") == "yes"
                    and not (open_[m].get("settling") or open_[m].get("waiting"))
                    and home == open_[m]["repo"]
                    and ledger_mod.lane_matches(list(rec.lane), dict(open_[m]), rec.team or None)
                ]
                if not takes:
                    continue
                if any(f["by"] == rec.id for f in c["passed_over"]):
                    continue  # one flag per worker on a card, whichever of its claims sits below it
                why = _first_doing(doing.get(rec.team or "", []), rec.id, p.at)
                c["passed_over"].append({"by": rec.id, "name": rec.name, "holding": q, "ids": takes, "why": why})


def _first_doing(log: list[Mapping[str, Any]], rid: str, since: str) -> str:
    start = _when(since)
    for e in log:
        if e.get("id") == rid and (start is None or (_when(e.get("at")) or start) >= start):
            return str(e.get("text") or "")
    return ""


def _completed(
    archived: Mapping[str, Mapping[str, Any]],
    open_: Mapping[str, Mapping[str, Any]],
    names_open: Mapping[str, set[str]],
    closed_at: Mapping[str, Mapping[str, Any]],
    xref: Any,
    now: datetime,
) -> list[dict[str, Any]]:
    """The completed cards (§4.4 *Completed cards*): the archive's components across repos none of
    whose members an open entry names and whose own `Blocked by:` names no open id, dated by the
    latest `Resolved:` date of its members, its PR from that line, else *What closed*. `entries` are its
    members as the page opens the card — `qid`, `id`, `title`, `priority`, `closed` (`_closed`), `pr`, `sha`
    (the closing commit, TD-904) and `resolved`, the `Resolved:` text — newest first, and `at` the newest `closed`."""
    named_by_open: set[str] = set()
    for e in open_.values():
        named_by_open.update(qid(e["repo"], b) for b in e.get("blocked_ids") or [])
        named_by_open.update(x for x in map(xref, e.get("xrepo_ids") or []) if x)
        if e.get("part_of"):  # an archived parent of an open part: that card's done group head (TD-1130)
            named_by_open.add(qid(e["repo"], str(e["part_of"])))
    parent = {q: q for q in archived}

    def find(q: str) -> str:
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q

    for q, a in archived.items():
        ids = lb.parse_blocked(a.get("blocked_raw") or "")[0] if a.get("blocked_raw") else []
        for b in ids:
            n = xref(b) if "#" in b else qid(a["repo"], b)
            if n in archived and n != q:
                parent[find(n)] = find(q)
        if (par := lb.parse_part_of(a.get("part_of_raw"))[0]) and (n := qid(a["repo"], par)) in archived and n != q:
            parent[find(n)] = find(q)  # an archived part joins its archived parent's component (TD-1130)
    comps: dict[str, list[str]] = {}
    for q in archived:
        comps.setdefault(find(q), []).append(q)
    out: list[dict[str, Any]] = []
    since = (now - COMPLETED_WINDOW).date()
    for members in comps.values():
        if any(q in named_by_open or q in names_open for q in members):
            continue  # with an open card: its archived rows
        dated = [(_resolved_date(archived[q]["fields"]), q) for q in members]
        day, last = max(dated)
        when = day or (closed_at.get(last) or {}).get("closed")  # the Resolved: date; the close's where none
        try:
            if not when or date.fromisoformat(str(when)[:10]) < since:
                continue
        except ValueError:
            continue
        pr = _resolved_pr(archived[last]["fields"]) or (closed_at.get(last) or {}).get("pr")
        ents = []
        for q in members:
            a = archived[q]
            ents.append(
                {
                    "qid": q,
                    "id": a["id"],
                    "title": a.get("title") or "",
                    "priority": (a.get("priority") or "").lower(),
                    "closed": _closed(a["fields"], closed_at.get(q)),
                    "pr": _resolved_pr(a["fields"]) or (closed_at.get(q) or {}).get("pr"),
                    "sha": (closed_at.get(q) or {}).get("sha"),
                    "resolved": _resolved_text(a["fields"]),
                }
            )
        ents.sort(key=lambda e: _closed_order(e["closed"]), reverse=True)
        out.append(
            {
                "id": min(members, key=lambda q: (int(q.partition("#")[2][3:]), q)),
                "ids": members,
                "titles": {q: archived[q].get("title") or "" for q in members},
                "closed": str(when),
                "pr": pr,
                "entries": ents,
                "at": ents[0]["closed"] if ents else str(when),
            }
        )
    out.sort(key=lambda c: c["closed"], reverse=True)
    return out
