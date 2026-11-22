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

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb
from sessionorc import naming, witness, workorders
from sessionorc import rank as rank_mod
from sessionorc import synopsis as synopsis_mod
from sessionorc.mail import LEASE_TTL
from sessionorc.models import PERSON as PERSON_ADDRESS
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


def qid(repo: str, tid: str) -> str:
    """An entry across repos: `shiftlead#TD-769`, the id written `TD-NNN`."""
    return f"{repo}#{ledger_mod._norm(tid)}"


# an entry named in a mail item, a board line's `Context:` or a PR's title: `TD-n`, or `<repo>#TD-n`, the
# `<repo>` a checkout's name or its origin's path (`owner/name`, deeper for a nested group; TD-1371)
TD_REF = re.compile(r"(?<![\w-])(?:([\w.-]+(?:/[\w.-]+)*)#)?TD-(\d+)\b")


def refs(text: Any) -> list[str]:
    """The entries a text names, in order, each once: `TD-n` with its number as the ledger writes it, and an
    origin path's `<repo>` lowercased, as ledgerboard compares it (TD-1371)."""
    seen: list[str] = []
    text = str(text or "")
    for m in TD_REF.finditer(text):
        repo, n = m.group(1) or "", m.group(2)
        if repo and m.start(1) and text[m.start(1) - 1] == "/":
            repo = repo.rpartition("/")[2]  # a link's path (`/repo/<name>#TD-n`, a URL): its last part, as before
        repo = repo.lower() if "/" in repo else repo
        ref = f"{repo}#TD-{int(n):03d}" if repo else f"TD-{int(n):03d}"
        if ref not in seen:
            seen.append(ref)
    return seen


# a completed card's entry in `card_index`, keyed `kept:<ref>` so no open card's lookup meets it: only an item that
# needs the person draws there, the card then kept (§4.5 screen 12 *Recently completed*, TD-1468)
KEPT = "kept:"
# a loose card's id, `loose:<ref>` (§4.5 screen 12 *In progress*, TD-1468): an item that needs the person and names
# a ref no card holds, open or completed
LOOSE = "loose:"
# a PR's entry in `card_index`, keyed `pr:<repo>#<n>` to `("", <repo>#TD-n)` — no card's, the entry the PR names —
# which only an item that needs the person and carries a PR alone reads (`pr_entry`, TD-1468)
PR_KEY = "pr:"
# a stopped holder's card in `card_index`, keyed `holder:<record id>` to the `(card id, row qid)` of the claim its state
# row draws on (`holder_claim`, TD-1468)
HOLDER = "holder:"


# an entry's design PR in `card_index`, keyed `design:<repo>#TD-n` to `("<n>", <the repo's root>)` — no card's —
# which only an item about the entry reads (`design_prs`, §4.5 screen 6 *An item about a design links the design's
# PR*, TD-1531)
DESIGN_KEY = "design:"
# the synopsis of the entry an item about a design resolved to, keyed `synopsis:<repo>#TD-n` by the item's entry's
# spellings, to `(editor_path or "", branch, path, root)` — drawn only where the file is there (§4.5 screen 6 *A
# design links its synopsis*, TD-1536)
SYNOPSIS_KEY = "synopsis:"
# a PR whose title leads with an entry's id and the word *design* (§4.9c *The designer records its PR*): `TD-n
# design: …`, never a build's (*TD-m: … TD-n …*) or a ledger edit's (*TD-n: …*)
DESIGN_TITLE = re.compile(r"^\s*TD-(\d+)\s+design(?=[\s:]|$)", re.I)


def design_prs(
    roots: Mapping[str, str],
    prs: Mapping[str, Any],
    open_: Mapping[str, Mapping[str, Any]],
    archived: Mapping[str, Mapping[str, Any]],
    synopses: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """`{<repo>#TD-n: {n, root, only, own, synopsis}}`: the design PR an item about each open or archived entry links
    (§4.5 screen 6 *An item about a design links the design's PR*, TD-1531). An entry's own: the lowest of its repo's
    open PRs (`prs`, by repo name, each `{open: [{number, title, branch, head, fork}]}`) whose title leads with its id
    and *design* and whose number is above its `Design PR:` section's last, else that last; where it has neither, its
    `Part of:` parent's own the same way — one hop, never the parent's parent. `root` is the entry's repo's, for the
    link (`review.pr_url`); `only` says no other repo holds the id, open or archived, so a bare `TD-n` may be looked
    up by it; `own` that the link is the entry's own, not its parent's. `synopsis` is the synopsis of the entry the
    link was read from (`synopsis.entry`, §4.5 screen 6 *A design links its synopsis*, TD-1536): read from the open
    design PR's head where the link is that PR, else from `origin/<default>`; `synopses` is each repo's synopsis
    reading by name (`synopsis.reading`), and a repo with none carries no `synopsis`."""
    open_design: dict[str, list[Mapping[str, Any]]] = {}
    for name, got in prs.items():
        for pr in (got or {}).get("open") or () if isinstance(got, Mapping) else ():
            n = pr.get("number") if isinstance(pr, Mapping) else None
            if isinstance(n, int) and not isinstance(n, bool) and (m := DESIGN_TITLE.match(str(pr.get("title") or ""))):
                open_design.setdefault(qid(name, f"TD-{m.group(1)}"), []).append(pr)

    def own(q: str, e: Mapping[str, Any]) -> tuple[int, Mapping[str, Any] | None] | None:
        section = [n for n in e.get("design_pr") or () if isinstance(n, int) and not isinstance(n, bool)]
        last = section[-1] if section else None
        # the section's last still open is read from its head too, so its synopsis is the branch's (TD-1536 review)
        above = sorted(
            (p for p in open_design.get(q, ()) if last is None or p["number"] >= last), key=lambda p: p["number"]
        )
        if above:
            return above[0]["number"], above[0]
        return (last, None) if last is not None else None

    held: dict[str, set[str]] = {}  # each bare id, by the repos holding it open or archived
    for q in [*archived, *open_]:
        name, _, tid = q.partition("#")
        held.setdefault(tid, set()).add(name)
    out: dict[str, dict[str, Any]] = {}
    for q, e in [*archived.items(), *open_.items()]:
        at, got = q, own(q, e)
        parent = e.get("part_of") if q in open_ else lb.parse_part_of(e.get("part_of_raw"))[0]
        if got is None and parent and (pq := qid(str(e["repo"]), str(parent))) != q:
            at, got = pq, own(pq, open_.get(pq) or archived.get(pq) or {})
        if got is None:
            continue
        root = str(roots.get(str(e["repo"])) or "")
        d: dict[str, Any] = {"n": got[0], "root": root, "only": len(held[q.partition("#")[2]]) == 1, "own": at == q}
        name, _, tid = at.partition("#")
        if (syn := synopsis_mod.entry(tid, got[1], (synopses or {}).get(name), root)) is not None:
            d["synopsis"] = syn
        out[q] = d
    return out


def card_index(reading: Mapping[str, Any] | None) -> dict[str, tuple[str, ...]]:
    """The open cards' entries (§4.5 screen 6 *Where a row is drawn*): each `<repo>#TD-n` a card holds —
    its top entry and every row, an open card's archived rows among them — to `(card id, row qid)`, and
    the bare `TD-n` too where one repo alone holds it, and `<origin path>#TD-n` where the reading's `origins`
    give the repo one (TD-1371). An entry on a completed card is in no open card: it is keyed `kept:<ref>`
    (`KEPT`, by the same three spellings, its bare one where one repo's completed cards alone hold it) to
    `(completed card id, its qid)`, which only an item that needs the person reads (TD-1468); an item that
    needs nobody and names it stays in the Inbox."""
    out: dict[str, tuple[str, str]] = {}
    bare: dict[str, set[str]] = {}
    origins = (reading or {}).get("origins") or {}
    for c in (reading or {}).get("cards") or []:
        if not isinstance(c, Mapping) or not c.get("top"):
            continue
        for r in [c["top"], *(c.get("rows") or [])]:
            q = str(r.get("qid") or "")
            got = refs(q)
            if "#" not in q or not got:
                continue
            out.setdefault(got[0], (str(c["id"]), q))
            name, _, tid = got[0].partition("#")
            if path := origins.get(name):
                out.setdefault(f"{path}#{tid}", (str(c["id"]), q))
            bare.setdefault(tid, set()).add(got[0])
    for tid, qs in bare.items():
        if len(qs) == 1:
            out[tid] = out[next(iter(qs))]
    kept_bare: dict[str, set[str]] = {}
    for c in (reading or {}).get("completed") or []:
        if not isinstance(c, Mapping) or not c.get("id"):
            continue
        ids = c.get("ids") or [e.get("qid") for e in c.get("entries") or () if isinstance(e, Mapping)]
        for q in map(str, ids or ()):
            got = refs(q)
            if "#" not in q or not got:
                continue
            out.setdefault(KEPT + got[0], (str(c["id"]), q))
            name, _, tid = got[0].partition("#")
            if path := origins.get(name):
                out.setdefault(f"{KEPT}{path}#{tid}", (str(c["id"]), q))
            kept_bare.setdefault(tid, set()).add(got[0])
    for tid, qs in kept_bare.items():
        if len(qs) == 1:
            out[KEPT + tid] = out[KEPT + next(iter(qs))]
    for pr, ref in ((reading or {}).get("pr_refs") or {}).items():
        out.setdefault(PR_KEY + str(pr), ("", str(ref)))
    for sid, q in holder_claims((reading or {}).get("holds"), out).items():
        out[HOLDER + sid] = out[q]
    # each entry's design PR (`design_prs`, TD-1531), by the same three spellings, its bare one where one repo alone
    # holds that id, open or archived (`only`)
    design_bare: dict[str, set[str]] = {}
    for q, d in ((reading or {}).get("design_prs") or {}).items():
        got = refs(q)
        if "#" not in str(q) or not got or not isinstance(d, Mapping) or not isinstance(d.get("n"), int):
            continue
        val = (str(d["n"]), str(d.get("root") or ""))
        syn = d.get("synopsis")
        sval = (  # the synopsis it resolved to, where the file is there (TD-1536)
            (
                str(syn.get("editor_path") or ""),
                str(syn.get("branch") or ""),
                str(syn.get("path")),
                str(syn.get("root")),
            )
            if isinstance(syn, Mapping) and syn.get("exists")
            else None
        )
        name, _, tid = got[0].partition("#")
        path = origins.get(name)
        for key, v in ((DESIGN_KEY, val), (SYNOPSIS_KEY, sval)):
            if v is None:
                continue
            out.setdefault(key + got[0], v)
            if path:
                out.setdefault(f"{key}{path}#{tid}", v)
        if d.get("only"):
            design_bare.setdefault(tid, set()).add(got[0])
    for tid, qs in design_bare.items():
        if len(qs) == 1:
            q = next(iter(qs))
            out[DESIGN_KEY + tid] = out[DESIGN_KEY + q]
            if SYNOPSIS_KEY + q in out:
                out[SYNOPSIS_KEY + tid] = out[SYNOPSIS_KEY + q]
    return out


def pr_refs(name: str, prs: Mapping[str, Any] | None) -> dict[str, str]:
    """`{<repo>#<n>: <repo>#TD-n}`: the entry each of a repo's PRs names (§4.5 screen 6 *Every item that needs the
    person draws on a card*, TD-1468) — an open PR's by its branch, else its title; then a PR of its month
    (`recent`) by its title, else its branch — each bare `TD-n` read as the repo's own (`own_refs`); an open PR
    naming none is read again in `recent`, title first. A PR naming no entry is left out."""
    out: dict[str, str] = {}
    for which, order in (("open", ("branch", "title")), ("recent", ("title", "branch"))):
        for pr in (prs or {}).get(which) or ():
            if not isinstance(pr, Mapping) or not isinstance(pr.get("number"), int) or isinstance(pr["number"], bool):
                continue
            key = f"{name}#{pr['number']}"
            if key in out:
                continue
            for field in order:
                text = str(pr.get(field) or "")
                got = [branch_ref(text)] if field == "branch" else refs(text)
                if got := own_refs([r for r in got if r], name):
                    out[key] = got[0]
                    break
    return out


def pr_entry(index: Mapping[str, tuple[str, str]] | None, repo: str | None, pr: Any) -> str | None:
    """The entry a PR names, `<repo>#TD-n`, as the reading's `pr_refs` read it (`card_index`'s `pr:` keys,
    TD-1468); None for no `repo`, no PR, or a PR naming none."""
    if not repo or not isinstance(pr, int) or isinstance(pr, bool):
        return None
    got = (index or {}).get(f"{PR_KEY}{repo}#{pr}")
    return got[1] if got else None


def holder_claims(holds: Any, index: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """`{record id: <repo>#TD-n}`: the claim each holder's state row draws on (§4.5 screen 6 *One place for each thing
    that needs the person*, TD-1468), among its live claims (`holds`, the reading's: `{sid, qid, source, at, n}`) on
    an entry an open card holds (`index`) — its declared claims first, the newest by `at` (one with no readable `at`
    the oldest), a tie by the later in its record's `progress` (`n`); only with none declared on an open card its
    derived ones, by the same order. A claim on an archived entry, a `board:` ref or a PR is in no `holds`, so the
    next is read."""
    best: dict[str, tuple[bool, datetime, int, str]] = {}
    oldest = datetime.min.replace(tzinfo=UTC)
    for h in holds or ():
        if not isinstance(h, Mapping):
            continue
        got = refs(h.get("qid"))
        if not got or got[0] not in index:
            continue
        n = h.get("n")
        key = (h.get("source") == "declared", _aware(h.get("at")) or oldest, n if isinstance(n, int) else -1, got[0])
        sid = str(h.get("sid") or "")
        if sid and (sid not in best or key[:3] > best[sid][:3]):
            best[sid] = key
    return {sid: k[3] for sid, k in best.items()}


def own_refs(found: Iterable[str], repo: str | None) -> list[str]:
    """`found` (`refs`'s) with each bare `TD-n` read as `repo`'s, `<repo>#TD-n` (§4.5 screen 6 *A bare ref
    elsewhere*, TD-1509): a row that names its repo never draws on another repo's card; with no `repo` it is read as
    no repo's (§4.5 screen 6 *A mail item's bare ref is its sender's repo's*, TD-1541) — only the refs written
    qualified are kept, so a bare one matches no key, the one choke point every reader of a mail item's refs
    shares."""
    found = list(found)
    if not repo:
        return [r for r in found if "#" in r]
    return list(dict.fromkeys(r if "#" in r else f"{repo}#{r}" for r in found))


def _repo_name(root: Any) -> str:
    """A checkout's name from its root, as a board line's `repo_name` reads it: the path's last component."""
    return str(root or "").rstrip("/").rpartition("/")[2]


def repo_roots(repos: Mapping[Any, Any] | None) -> dict[str, str]:
    """`{name: root}` of a `repos` reading (`{root: reading}`), each named as the reading names it — its `name`, else
    its root's last component — for `asker_repos` (TD-1509): a repo whose name differs from its directory's."""
    out: dict[str, str] = {}
    for k, r in (repos or {}).items():
        if isinstance(r, Mapping):
            root = str(r.get("root") or k)
            out.setdefault(str(r.get("name") or _repo_name(root)), root)
    return out


def record_repo(repo: Any, dir: Any, roots: Iterable[str], names: Mapping[str, str] | None = None) -> str | None:
    """The record's entry point of the repo helper (§4.10 *An envelope carries its sender's `repo`*, TD-1467): the
    registry's name for a record's repo — `witness.repo_named` over its `repo` (a worktree's record names its main
    checkout there), else its `dir`, against `roots`, the checkouts the home registers for the **record's own
    host** — named as the readings name it (`names`, `{name: root}`, `repo_roots`'), else by the root's last
    component, the name a card's qid carries (`<name>#TD-n`); None where neither is in a registered checkout. The
    send's stamp calls it, and TD-1468's holder row."""
    roots = list(roots)
    got = witness.repo_named(repo, roots) or witness.repo_named(dir, roots)
    if got is None:
        return None
    root, name = got
    return next((n for n, r in (names or {}).items() if _same_dir(root, r)), None) or name


def mail_repo(
    q: Any,
    records: Mapping[str, tuple[str, Any]],
    name_of: Callable[[str, Any], str],
    teams: Mapping[str, str] | None = None,
    home: str = "",
) -> str | None:
    """The entry's entry point of the repo helper (§4.10, §4.5 screen 6 *A mail item's bare ref is its sender's
    repo's*, TD-1467, TD-1541), the one place its order is written: its stamped `repo` (a name, as the send wrote it),
    else its orphan stamp's `repo` (TD-213: the asker's checkout then), named with the stamp's `host` as a pair (the
    home's where empty), else its sender's record — `records`, `{address: (host, root)}`, each record keyed by its
    whole address (`<id>@<host>` for another host's, the bare id for the home's, the pair's host empty for a bare
    key) — found by `from` as written, then by its bare id only where `from` is bare or names `home`, the home's own
    host, so an item from `x@node` whose record is gone never reads the home's `x`; an item the person sent reads its
    first addressee the same way. Each pair named by `name_of(host, root)`. Failing those, its envelope's `team`
    (`teams`, `team_repos`'). None where all find none: its bare refs are then read as no repo's (`own_refs`)."""
    if stamped := str(_get(q, "repo") or "").strip():
        return stamped
    orphaned = _get(q, "orphaned")
    if (
        isinstance(orphaned, Mapping)
        and orphaned.get("repo")
        and (name := name_of(_home_host(orphaned.get("host"), home), orphaned.get("repo")))
    ):
        return name
    sender = str(_get(q, "from_") or "").strip()
    if sender == PERSON_ADDRESS:
        to = _get(q, "to")
        to = to if isinstance(to, (list, tuple)) else [to]
        sender = str(to[0] or "").strip() if to else ""
    if sender:
        bare, host = naming.split_address(sender)
        got = records.get(sender)
        if got is None and (host is None or (home and host == home)):
            got = records.get(bare)
        if got is not None and (name := name_of(*got)):
            return name
    team = str(_get(q, "team") or "").strip()
    return (teams or {}).get(team) or None if team else None


def _home_host(host: Any, home: str) -> str:
    """A host as a record pair writes it: empty for the home's own (an empty one, or `home`), else as given."""
    host = str(host or "").strip()
    return "" if not host or (home and host == home) else host


def record_keys(records: Iterable[Any], home: str = "") -> dict[str, tuple[str, str, str]]:
    """`{address: (host, root, team)}` of the caller's records (§4.5 screen 6 *A mail item's bare ref is its sender's
    repo's*, TD-1541), each keyed by its whole address: a view dict's `id` as given (the home's view writes
    `<id>@<host>` for another host's record, the bare id for its own); a `Session`'s `id`, with `@<host>` added where
    its `host` is set and is not `home`. The pair's host is the key's — empty for a bare key — never a view dict's own
    `host` field; its root the record's `repo`, else its `dir`, as the send's stamp reads it. A record with no root is
    left out."""
    out: dict[str, tuple[str, str, str]] = {}
    for r in records:
        rid = str(_get(r, "id") or "").strip()
        root = str(_get(r, "repo") or _get(r, "dir") or "")
        if not rid or not root:
            continue
        if not isinstance(r, Mapping) and (h := _home_host(_get(r, "host"), home)):
            rid = f"{naming.split_address(rid)[0]}@{h}"
        host = naming.split_address(rid)[1] or ""
        out.setdefault(rid, (host, root, str(_get(r, "team") or "").strip()))
    return out


def team_repos(keyed: Mapping[str, tuple[str, str, str]], name_of: Callable[[str, Any], str]) -> dict[str, str]:
    """`{team: repo}`, the team step of `mail_repo`'s order (§4.5 screen 6, TD-1541): every record in `keyed`
    (`record_keys`' shape) with a `team`, of any role, named by `name_of(host, root)` — a record whose root names
    none skipped, one with no `team` ignored; a team whose records name exactly one repo maps to it, one naming
    several (a seat in another repo's checkout) is left out, the safe side."""
    seen: dict[str, set[str]] = {}
    for host, root, team in keyed.values():
        if team and (name := name_of(host, root)):
            seen.setdefault(team, set()).add(name)
    return {t: next(iter(ns)) for t, ns in seen.items() if len(ns) == 1}


def asker_repos(
    questions: Iterable[Any], records: Iterable[Any], roots: Mapping[str, str] | None = None, host: str = ""
) -> dict[str, str]:
    """`{mail id: repo}` for the person inbox's items (§4.5 screen 6 *A bare ref elsewhere*, TD-1509; *A mail item's
    bare ref is its sender's repo's*, TD-1467, TD-1541): each item's repo by `mail_repo`'s order — its stamped
    `repo`, else its orphan stamp's, else its sender's record (`records`: live, ended or kept; `Session`s or their
    view dicts, keyed by `record_keys` against `host`, the home's own host, which the home's callers pass and the
    UI's need not), else its team's one repo (`team_repos`). A root is named as the readings name it (`roots`,
    `{name: root}`), else — on the home's own host alone — by its last component; a node's path never by the name
    it happens to end in. An item with none is left out, and its bare refs are read as no repo's."""
    named: dict[tuple[str, str], str] = {}

    def name_of(h: str, root: Any) -> str:
        key = (str(h or ""), str(root or ""))
        if key[1] and key not in named:
            hit = next((n for n, r in (roots or {}).items() if _same_dir(key[1], r)), None)
            named[key] = hit or (_repo_name(key[1]) if not key[0] or key[0] == host else "")
        return named.get(key, "")

    keyed = record_keys(records, host)
    teams = team_repos(keyed, name_of)
    pairs = {k: (h, root) for k, (h, root, _t) in keyed.items()}
    out: dict[str, str] = {}
    for q in questions:
        mid = _get(q, "id")
        if mid and (repo := mail_repo(q, pairs, name_of, teams, host)):
            out[str(mid)] = repo
    return out


def first_ref(about: Any, words: Any, repo: str | None = None) -> str | None:
    """The one entry a mail item names (§4.5 screen 6 *Where a row is drawn*): the first ref of its `about`,
    else the first `TD-n` of `words` (its subject and text), a bare one read as `repo`'s (its asker's, `own_refs`,
    TD-1509); None where it names none."""
    named = own_refs(refs(about), repo) or own_refs(refs(words), repo)
    return named[0] if named else None


def held_refs(
    about: Any, words: Any, index: Mapping[str, Any] | None, repo: str | None = None
) -> tuple[list[str], str]:
    """A mail item's refs an open card holds, in order, and where the first was read (§4.5 screen 6 *A mail item's
    bare ref is its sender's repo's*, TD-1467): `about`'s refs first, then those of `words` (its subject and text),
    each bare `TD-n` read as `repo`'s (`own_refs`), kept where `index` holds them — its home the first, the later
    ones its mentions, never the first ref alone. `by` is `about` when the first held ref came from `about`, else
    `words`."""
    about_refs = own_refs(refs(about), repo)
    named = about_refs + [r for r in own_refs(refs(words), repo) if r not in about_refs]
    held = [r for r in named if r in (index or {})]
    return held, ("about" if held and held[0] in about_refs else "words")


def named_refs(about: Any, words: Any, repo: str | None = None) -> tuple[list[str], list[str]]:
    """Every ref a mail item names, in order — `about`'s, then those of `words` — each bare `TD-n` read as `repo`'s
    (`own_refs`), and `about`'s alone, which say where the first was read (TD-1468)."""
    about_refs = own_refs(refs(about), repo)
    return about_refs + [r for r in own_refs(refs(words), repo) if r not in about_refs], about_refs


def kept_or_loose(named: Iterable[str], index: Mapping[str, tuple[str, str]] | None) -> tuple[str, str, str] | None:
    """Where an item that needs the person draws when no open card holds its refs (§4.5 screen 6 *Every item that
    needs the person draws on a card*, TD-1468): `(card id, row qid, ref)` — the completed card that holds the first
    of `named` a completed card holds, kept (`card_index`'s `kept:<ref>`), `ref` that ref; else the loose card of
    its first ref, `loose:<ref>`, its row the ref. None — the Inbox — where it names none, or where `index` is empty
    (a home that serves no Queue)."""
    named = list(named)
    if not named or not index:
        return None
    for r in named:
        if KEPT + r in index:
            card, row = index[KEPT + r]
            return card, row, r
    return LOOSE + named[0], named[0], named[0]


_PR_ABOUT = re.compile(r"#(\d+)")


def only_pr(pr: Any, about: Any) -> int | None:
    """The PR an item carries as its only anchor (§4.5 screen 6 *Every item that needs the person draws on a card*,
    TD-1468): its `pr`, else an `about` of the shape `#n`; None otherwise. The caller has found no entry ref in it."""
    if isinstance(pr, int) and not isinstance(pr, bool):
        return pr
    m = _PR_ABOUT.fullmatch(" ".join(str(about or "").split()))
    return int(m.group(1)) if m else None


# the PR a board line's `Context:` names (§4.5 screen 6 *Every item that needs the person draws on a card*, TD-1552):
# `#n` with nothing of a word, a path or a repo before its `#` — `PR #164`, `#164` and `(#164)` read 164; `PR#164`,
# `agent-cadence#164`, `owner/name#12` and `a.b#3` read nothing
_CONTEXT_PR = re.compile(r"(?<![\w./-])#(\d+)\b")


def context_pr(text: Any) -> int | None:
    """The PR a board line's `Context:` names, its first `#n` (`_CONTEXT_PR`); None where it names none (TD-1552). The
    caller reads it only where the `Context:` names no entry."""
    m = _CONTEXT_PR.search(str(text or ""))
    return int(m.group(1)) if m else None


def pr_card(
    pr: int | None, repo: str | None, index: Mapping[str, tuple[str, str]] | None
) -> tuple[str, str, str] | None:
    """Where an item that needs the person and carries a PR alone draws (TD-1468): `(card id, row qid, ref)` — the
    open card that holds the entry the PR names (`pr_entry`), else that entry's kept or loose card
    (`kept_or_loose`); with none named, the loose card of the PR itself, `loose:<repo>#<n>`. None — the Inbox —
    with no `repo` (no repo to search, no key that is one repo's), no PR, or an empty `index`."""
    if not index or not repo or pr is None:
        return None
    if entry := pr_entry(index, repo, pr):
        if entry in index:
            card, row = index[entry]
            return card, row, entry
        return kept_or_loose([entry], index)
    ref = f"{repo}#{pr}"
    return LOOSE + ref, ref, ref


def mail_card(
    about: Any,
    words: str,
    index: Mapping[str, tuple[str, str]] | None,
    repo: str | None = None,
    needs: bool = False,
    pr: Any = None,
) -> tuple[str, str] | None:
    """The `(card id, row qid)` a mail item is drawn on (§4.5 screen 6 *Where a row is drawn*): the first of its refs
    an open card holds (`held_refs`: its `about`'s, then those of `words`, its subject and text), a bare one read as
    `repo`'s — its sender's (`mail_repo`, TD-1467) — None — its home is the Inbox — where no card holds one, unless
    it `needs` the person (an open `ask` or `steer` to them), when it draws on its kept or loose card
    (`kept_or_loose`, TD-1468) — one that names no entry but carries a PR (`pr`, or an `about` of `#n`) on the
    card of the entry that PR names, else its PR's loose card (`pr_card`). The Inbox's own `item_home` and
    Telegram's link (§4.10 *What a message says*, TD-795) read it alike."""
    held, _by = held_refs(about, words, index, repo)
    if held:
        return (index or {}).get(held[0])
    if not needs:
        return None
    named = named_refs(about, words, repo)[0]
    got = kept_or_loose(named, index) if named else pr_card(only_pr(pr, about), repo, index)
    return got[:2] if got else None


# an answered question's word holds after a `done` outcome no longer than this (§4.4 *The card's status*, TD-1316)
ANSWERED_DONE_FOR = timedelta(days=1)
_GONE = ("exited", "closed")


def open_refs(qids: Iterable[str], origins: Mapping[str, str] | None = None) -> dict[str, str]:
    """The open members' index an answered question links through (§4.4 *The card's status*, TD-1316): each
    `<repo>#TD-n` to itself, and `<origin path>#TD-n` to it where `origins` give the repo one (TD-1371). It has no
    bare `TD-n` key: a mail item's bare ref is its sender's repo's or no repo's (`own_refs`, TD-1541), and a board
    line's is its own board's (`_line_qid`)."""
    out: dict[str, str] = {}
    for q in qids:
        out[q] = q
        name, _, tid = q.partition("#")
        if path := (origins or {}).get(name):
            out.setdefault(f"{path}#{tid}", q)
    return out


def _get(o: Any, name: str) -> Any:
    """A field of a person-inbox question, a `MailEntry` (the home's) or its view dict (the UI's)."""
    if isinstance(o, Mapping):
        return o.get("from" if name == "from_" else name)
    return getattr(o, name, None)


def _aware(v: Any) -> datetime | None:
    """An aware UTC time from an ISO string (a `Z` read on 3.11+) or epoch seconds; None for anything else."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        return datetime.fromtimestamp(v, UTC)
    if not isinstance(v, str) or not v:
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def applying_words(mark: Mapping[str, Any]) -> str:
    """A press's mark as a row reads it (§4.4 *A press is drawn as it lands*, TD-1508): *answered — applying* for a
    decide, *applying <act>* for the rest."""
    act = str(mark.get("act") or "")
    return "answered — applying" if act == "decide" else f"applying {act}".strip()


def lay_applying(
    view: Mapping[str, Any], marks: Mapping[str, Mapping[Any, Mapping[str, Any]]], name: str
) -> dict[str, Any]:
    """`view` (a repo reading) with each press mark laid over it (§4.4 *A press is drawn as it lands*, TD-1508):
    `marks` `{key: {token: {act, answer, at}}}` — `board:<key>` a board line's, `ledger:<name>#TD-n` an entry's —
    each item or entry it names given `applying`, the newest standing token's fields. A copy of what it touches; the
    reading itself is never written."""
    newest = {k: dict(list(toks.values())[-1]) for k, toks in marks.items() if toks}
    if not newest:
        return dict(view)
    out = dict(view)
    bds = view.get("boards")
    if isinstance(bds, Mapping) and isinstance(bds.get("boards"), list):
        boards = []
        for b in bds["boards"]:
            if isinstance(b, Mapping) and isinstance(b.get("items"), list):
                b = {**b, "items": [
                    {**it, "applying": newest[k]} if isinstance(it, Mapping) and (k := str(it.get("key") or ""))
                    in newest else it for it in b["items"]
                ]}  # fmt: skip
            boards.append(b)
        out["boards"] = {**bds, "boards": boards}
    led = view.get("ledger")
    if isinstance(led, Mapping) and isinstance(led.get("entries"), list):
        out["ledger"] = {**led, "entries": [
            {**e, "applying": newest[k]} if isinstance(e, Mapping)
            and (k := f"ledger:{qid(name, str(e.get('id') or ''))}") in newest else e for e in led["entries"]
        ]}  # fmt: skip
    return out


def answered_hold(
    member: Mapping[str, Any],
    questions: Iterable[Any],
    states: Mapping[str, str],
    refs_open: Mapping[str, str],
    now: datetime,
    *,
    boards: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    claims: Mapping[str, str] | None = None,
    entries: Mapping[str, Mapping[str, Any]] | None = None,
    live: Mapping[str, str] | None = None,
    asker_repo: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """A `decision (paul)` member whose question the person has answered, while its asker acts on the answer
    (§4.4 *The card's status*, TD-1316): `{mid, asker, kind, closed_at, outcome}` of the newest such question
    by `closed_at`, or — where no mail question holds and `boards` are given — the board line's (`board_hold`,
    TD-1368), or None — the member then needs the person as before.

    `member` is the open entry with its `repo` and `written` (its file's mtime); `questions` the person inbox's
    entries (`MailEntry`s or their view dicts); `states` each record's state by bare id, from the **unfiltered**
    records, an absent id gone; `refs_open` the open members' index (`open_refs`) over every repo. A question
    links by its first ref (`first_ref`), a bare one read as its asker's repo's (`asker_repo`, `asker_repos`'s map,
    TD-1509), resolved through `refs_open`. The newest linked question answered by
    the person (`replied`, or `go_with_it`) holds while it owes its outcome and its asker's record is neither
    exited, closed nor absent; after a `done` outcome, while the entry's file is not written after the answer
    and no longer than `ANSWERED_DONE_FOR` past the outcome's `at`; never on any other outcome but `blocked`
    (TD-1695): one the person has not replied on holds whatever its asker's state, the file and the day, and is
    taken before a newer linked question; a replied one is read as no outcome, so it ends when its asker is gone and
    with its person-inbox copy. A `blocked` or `done` hold returns the outcome as it is."""
    if not ledger_mod.decided_by(dict(member), PERSON):
        return None
    mail = _mail_hold(member, questions, states, refs_open, now, asker_repo)
    if mail is not None or boards is None:
        return mail  # a mail question that holds wins (§4.4 *The card's status*, TD-1368)
    return board_hold(member, boards, refs_open, now, claims=claims or {}, entries=entries or {}, live=live or {})


def _mail_hold(
    member: Mapping[str, Any],
    questions: Iterable[Any],
    states: Mapping[str, str],
    refs_open: Mapping[str, str],
    now: datetime,
    asker_repo: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """`answered_hold`'s mail half (TD-1316): the newest linked question the person answered, while it holds."""
    me = qid(str(member.get("repo") or ""), str(member.get("id") or ""))
    best: tuple[datetime, Any] | None = None
    stopped: tuple[datetime, Any] | None = None  # the newest unreplied `blocked` one, which holds whatever is newer
    for q in questions:
        if _get(q, "kind") not in ("ask", "steer") or _get(q, "closed_reason") not in ("replied", "go_with_it"):
            continue
        words = f"{_get(q, 'subject') or ''} {_get(q, 'text') or ''}"
        # the question's own stamped repo first, never the member's (TD-1467), else the caller's map (`mail_repo`'s)
        own = str(_get(q, "repo") or "").strip() or (asker_repo or {}).get(str(_get(q, "id")))
        ref = first_ref(_get(q, "about"), words, own)
        if not ref or refs_open.get(ref) != me:
            continue
        at = _aware(_get(q, "closed_at"))
        if at is not None and (best is None or at > best[0]):
            best = (at, q)
        if at is not None and _blocked(_get(q, "outcome")) == "open" and (stopped is None or at > stopped[0]):
            stopped = (at, q)
    best = stopped or best
    if best is None:
        return None
    closed, q = best
    outcome = _get(q, "outcome")
    asker = naming.split_address(str(_get(q, "from_") or ""))[0]
    blocked = _blocked(outcome)
    if blocked == "open":
        pass  # work stopped on something only the person can move: it holds, whatever its asker's state (TD-1695)
    elif not outcome or blocked == "replied":
        if states.get(asker, "closed") in _GONE:
            return None  # the asker is gone with the debt unpaid: the question is the person's again
    elif not isinstance(outcome, Mapping) or outcome.get("state") != "done":
        return None
    else:
        written, done_at = _aware(member.get("written")), _aware(outcome.get("at"))
        if written is not None and written > closed:
            return None
        if done_at is None or now > done_at + ANSWERED_DONE_FOR:
            return None
    return {"mid": _get(q, "id"), "asker": asker, "kind": _get(q, "kind"), "closed_at": closed.isoformat(),
            "outcome": dict(outcome) if isinstance(outcome, Mapping) else None}  # fmt: skip


def _blocked(outcome: Any) -> str:
    """A question's `blocked` outcome (§4.10 *`blocked` is not a dead end*, TD-1694): `open` until the person
    replies on it, then `replied`; '' for any other outcome, or none."""
    if not isinstance(outcome, Mapping) or outcome.get("state") != "blocked":
        return ""
    return "replied" if outcome.get("replied") else "open"


# a decided board line still open this many civil days after its `Decided:` date is the Inbox's need again, and a
# line closed in other words holds no longer than this after its `Closed:` date (§4.5 screen 6, §4.4 *The card's
# status*, TD-1368); `shiftlead.ui.inbox` reads it from here
BOARD_WAIT_DAYS = 3
# a waiting-only answer (`— kept waiting.`) holds until its `kept waiting` Log date plus this — the sweep's own
# re-ask, one constant for the word and the sweep (§4.4 *The card's status*, TD-1368)
REASK_DAYS = lb.SWEEP_REASK_DAYS
_GATE = f"decision ({PERSON})"


def _civil(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _line_qid(ref: str, repo: str, refs_open: Mapping[str, str]) -> str | None:
    """A board line's ref as an entry across repos: a bare `TD-n` its own board's repo's, a qualified one through
    the open members' index, else as written where it names a repo by its name (TD-1355, TD-1371)."""
    got = refs(ref)
    if not got:
        return None
    if "#" not in got[0]:
        return qid(repo, got[0])
    return refs_open.get(got[0]) or got[0]


def parent_qid(member: Mapping[str, Any]) -> str | None:
    """The `<repo>#TD-n` of the entry `member` (an open entry with its `repo`) names in its `Part of:`, or None."""
    repo = str(member.get("repo") or "")
    par = lb.parse_part_of(member.get("part_of_raw"))[0] if member.get("part_of_raw") else member.get("part_of")
    return qid(repo, str(par)) if par else None


def covers(
    line_refs: Iterable[Any],
    parts: Iterable[Any],
    repo: str,
    entries: Mapping[str, Mapping[str, Any]],
    refs_open: Mapping[str, str],
) -> set[str]:
    """The entries a board line **covers** (§4.4 *The card's status*, TD-1364), as `<repo>#TD-n`: each its `Context:`
    refs (`line_refs`) or `Parts:` ids name — a bare `TD-n` its own board's repo's (`repo`), a qualified one through
    the open members' index — and each open entry of `entries` (by `<repo>#TD-n`, each with its `repo`) that is
    `Part of` one of those while it carries `decision (paul)`."""
    named = {q for r in [*line_refs, *parts] if (q := _line_qid(str(r), repo, refs_open))}
    out = set(named)
    if not named:
        return out
    for q, e in entries.items():
        if q in named or not (e.get("part_of") or e.get("part_of_raw")):
            continue
        if parent_qid(e) in named and ledger_mod.decided_by(dict(e), PERSON):
            out.add(q)
    return out


def open_decided_lines(
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    entries: Mapping[str, Mapping[str, Any]],
    refs_open: Mapping[str, str],
    *,
    person_only: bool = False,
) -> list[tuple[dict[str, Any], set[str]]]:
    """Every open decided board line the home reads (`boards` by repo name, each `{items}`) but an `fyi`, of any
    kind, beside the entries it covers (`covers`): `[({repo, key, session, decided, by}, covered)]` — the one
    enumerator `open_decided_covers` and `lift_here` read (§4.4 *Where Lift the hold is drawn*, TD-1831). A decided
    `fyi` line is no work order and covers nothing; any other decided line is a work order whoever wrote it, as the
    home's own press writes `(by <its person>)` — save with `person_only`, the rows' read, which skips a line
    `Decided:` by someone else as `board_hold` does."""
    out: list[tuple[dict[str, Any], set[str]]] = []
    for repo, bl in boards.items():
        for b in bl or ():
            for it in (b.get("items") or ()) if isinstance(b, Mapping) else ():
                if not isinstance(it, Mapping) or not it.get("decided") or it.get("kind") == "fyi":
                    continue
                by = str(it.get("decided_by") or "").strip().lower()
                if person_only and by and by != PERSON:
                    continue
                d = it.get("decided") if isinstance(it.get("decided"), Mapping) else {}
                line = {"repo": repo, "key": str(it.get("key") or ""), "session": str(it.get("session") or ""),
                        "decided": str(d.get("date") or ""), "by": it.get("decided_by")}  # fmt: skip
                out.append((line, covers(it.get("refs") or (), it.get("parts") or (), repo, entries, refs_open)))
    return out


def open_decided_covers(
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    entries: Mapping[str, Mapping[str, Any]],
    refs_open: Mapping[str, str],
    *,
    person_only: bool = False,
) -> set[str]:
    """Every entry an open decided board line covers (`covers`), over every board the home reads (`boards` by repo
    name, each `{items}`): such an entry's line is its row now, *Waiting on them* while it waits on its session
    (§4.5 screen 6, TD-565, TD-1364). The union of `open_decided_lines`' covers, so the two never disagree;
    `person_only` as there, so the Inbox hides no row the Queue still asks about."""
    out: set[str] = set()
    for _, covered in open_decided_lines(boards, entries, refs_open, person_only=person_only):
        out |= covered
    return out


def line_holder(
    key: str, session: str, covered: Iterable[str], claims: Mapping[str, str], live: Mapping[str, str]
) -> str | None:
    """Who holds an open decided line, as `board_hold` reads a holder (§4.4 *The card's status*, TD-1368; factored
    for `lift_here`, TD-1831): an unexpired claim on the line (`board:<key>`), else on a covered entry (`covered`
    in order, the member first), else the live recorded session the line names — its id, or None."""
    return (
        claims.get(key)
        or next((claims[q] for q in covered if q in claims), None)
        or (live.get(session) if session else None)
    )


def lift_case_d(
    member: Mapping[str, Any],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    entries: Mapping[str, Mapping[str, Any]],
    repo_key: str,
    held: Mapping[str, str] | None = None,
) -> bool:
    """Whether case (d) holds for `member`: `lift_case_d_item` names an item (`held` as it reads it)."""
    return lift_case_d_item(member, boards, entries, repo_key, held) is not None


def lift_case_d_item(
    member: Mapping[str, Any],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    entries: Mapping[str, Mapping[str, Any]],
    repo_key: str,
    held: Mapping[str, str] | None = None,
) -> str | None:
    """The `board:<key>` of the item for which case (d) holds for `member` (an open entry with its `repo`; §4.4
    *Lift the hold is a lift on the press*, TD-1831): an open, undecided `decide` item on the entry's own repo's board
    (`boards[member["repo"]]`, each with its `People:` names as `people`) covers it as ledgerboard's `covers()` reads
    one — its `Context:` naming exactly one entry ref and the gate `decision (<p>)` of the entry's person, no qualifier
    after the gate, the ref the entry (a bare id, or a `<repo>#TD-n` whose repo is `repo_key`), or its `Part of` parent
    with the entry among the item's `Parts:`; the board's `People:` listing the person — and lists no other gated entry:
    no `Context:` entry (the parent, where it covers through `Part of`) nor `Parts:` id, a bare id of that repo, open in
    `entries`, not the member, and carrying `decision (<p>)`. The press refuses a lift there, so the row draws none;
    §4.10's `ask --lift` is refused there too, naming the item (TD-1833). None where no item asks. `held` is
    `held_map`'s `{build: design}`: on a design with a question the item is read over the set, its held builds no
    other gated entry (§4.4 *A design's question is asked once, on the design*, TD-2026)."""
    repo = str(member.get("repo") or "")
    try:
        num = lb._num(str(member.get("id") or ""))
    except (ValueError, IndexError, TypeError, AttributeError):
        return None
    me = qid(repo, str(member.get("id") or ""))
    par = lb.parse_part_of(member.get("part_of_raw"))[0] if member.get("part_of_raw") else member.get("part_of")
    parent = lb._num(str(par)) if par and lb._is_id(str(par)) else None
    key = lb._gate_key(_GATE)

    def other_gated(ref: str) -> bool:
        if "#" in ref or not lb._is_id(ref):
            return False  # a `<repo>#TD-n` never counts here, as the tripwire's shared case keeps bare ids alone
        q = qid(repo, ref.upper())
        if held and held.get(q) == me:
            return False  # one of the design's held builds: the item reads over the set (TD-2026)
        return q != me and q in entries and bool(ledger_mod.decided_by(dict(entries[q]), PERSON))

    for b in boards.get(repo) or ():
        if not isinstance(b, Mapping) or PERSON not in {str(n).lower() for n in b.get("people") or ()}:
            continue
        for it in b.get("items") or ():
            if not isinstance(it, Mapping) or it.get("kind") != "decide" or it.get("decided"):
                continue
            ctx = str(it.get("context") or "")
            ref, gate = lb._context_gate(ctx)
            if ref is None or gate is None or lb._gate_key(gate) != key:
                continue
            g = lb.CONTEXT_ANY_GATE_RE.search(ctx)
            if g and " ".join(ctx[g.end() :].strip().rstrip(".").split()):
                continue  # a `lift` or `board <repo>` qualifier: not the sweep's ask
            at = lb._ours(ref, True, repo_key)
            parts = [str(p) for p in it.get("parts") or ()]
            if at == num:
                listed = list(parts)
            elif parent is not None and at == parent and any(lb._ours(p, True, repo_key) == num for p in parts):
                listed = [ref, *parts]
            else:
                continue
            if not any(other_gated(r) for r in listed):
                k = str(it.get("key") or "")
                return k if k.startswith("board:") else f"board:{k}"
    return None


_LIFT_REF_RE = re.compile(r"(?:(?P<repo>[^#\s]+)#)?(?P<id>TD-\d+)", re.IGNORECASE)


def lift_ask_target(repos: Mapping[str, Mapping[str, Any]], ref: str, repo: str | None) -> dict[str, Any] | None:
    """The entry an `ask --lift`'s `about` names (§4.10 *An `ask` that lifts the person's gate*, TD-1833), read from
    the home's repo readings (`repos`, by root) as the press reads it: `{root, name, id, entry, asked}` — `root` the
    reading's key, `entry` the open entry (with its `repo`) or None where the reading holds none open, `asked` the
    `board:<key>` case (d) names (`lift_case_d_item`) or None. A bare `TD-n` is `repo`'s (the asker's record's repo,
    as its envelope stamps it), a `<repo>#TD-n` the reading `<repo>` names. None where `ref` is no entry reference or
    names no reading the home has."""
    m = _LIFT_REF_RE.fullmatch(str(ref or "").strip())
    if m is None:
        return None
    rs = _Repos(repos)
    want = m.group("repo") or repo
    if not want:
        return None
    name = want if want in rs.by_name else rs.resolve(want)
    if name is None:
        return None
    root = next(
        (k for k, r in repos.items() if isinstance(r, Mapping) and str(r.get("name") or Path(str(k)).name) == name),
        None,
    )
    if root is None:
        return None
    tid = m.group("id").upper()
    open_: dict[str, dict[str, Any]] = {}
    for n, r in rs.by_name.items():
        for e in r["ledger"]["entries"]:
            if isinstance(e, Mapping) and e.get("id"):
                open_.setdefault(qid(n, e["id"]), {**e, "repo": n})
    e = open_.get(qid(name, tid))
    boards = {n: list((r.get("boards") or {}).get("boards") or ()) for n, r in rs.by_name.items()}
    held = held_map(open_, boards, open_refs(open_, rs.origins)) if e is not None else {}
    asked = lift_case_d_item(e, boards, open_, rs.origins.get(name) or name.lower(), held) if e is not None else None
    return {"root": root, "name": name, "id": tid, "entry": e, "asked": asked}


def lift_here(
    member: Mapping[str, Any],
    lines: Iterable[tuple[Mapping[str, Any], Collection[str]]],
    claims: Mapping[str, str],
    live: Mapping[str, str],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    entries: Mapping[str, Mapping[str, Any]],
    repo_key: str,
    held: Mapping[str, str] | None = None,
) -> bool:
    """Whether a Queue row draws **Lift the hold** in its ⋯ (§4.4 *Where Lift the hold is drawn*, TD-1831): the
    entry still carries `decision (paul)`, is not the person's own (`Owner:` the person: **Done** answers it), an open
    decided line covers it (`lines`, `open_decided_lines(..., person_only=True)`, the very set that hides its item),
    no holder (`line_holder`) holds any such line, the entry or another entry it covers, and case (d) does not hold
    (`lift_case_d`, read with `held`, `held_map`'s map). The caller clears it on a *with you*, an applying or an
    archived row."""
    if not ledger_mod.decided_by(dict(member), PERSON) or str(member.get("owner") or "").lower() == PERSON:
        return False
    me = qid(str(member.get("repo") or ""), str(member.get("id") or ""))
    mine = [(ln, cov) for ln, cov in lines if me in cov]
    if not mine:
        return False
    for ln, cov in mine:
        covered = [me, *sorted(q for q in cov if q != me)]
        if line_holder(str(ln.get("key") or ""), str(ln.get("session") or ""), covered, claims, live):
            return False
    return not lift_case_d(member, boards, entries, repo_key, held)


def _board_lines(boards: Mapping[str, Iterable[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Every `decide` line of the boards, open (`items`) and closed (`carried`), as one shape: `{repo, key, open,
    decided, said, by, delegate, scope, refs, parts, gate, closed, to, at, session}` — `decided` None for an open line
    not yet answered, `said` its `Decided:` words, `delegate` and `scope` a delegated answer's (ledgerboard v3.4,
    TD-1939: `by` is then the person it answered for), else None; `gate` its `Context:`'s one gate
    (`_context_gate`), else None (TD-2026)."""
    out: list[dict[str, Any]] = []
    for repo, bl in boards.items():
        for b in bl or ():
            if not isinstance(b, Mapping):
                continue
            for it in b.get("items") or ():
                if not isinstance(it, Mapping) or it.get("kind") != "decide":
                    continue
                d = it.get("decided") if isinstance(it.get("decided"), Mapping) else None
                out.append({"repo": repo, "key": str(it.get("key") or ""), "open": True,
                            "decided": str(d.get("date") or "") if d else None, "by": it.get("decided_by"),
                            "delegate": it.get("decided_delegate"), "scope": it.get("decided_scope"),
                            "said": str(d.get("text") or "") if d else "",
                            "refs": [str(r) for r in it.get("refs") or () if refs(r)],
                            "parts": [str(p) for p in it.get("parts") or ()], "closed": None, "to": [],
                            "gate": lb._context_gate(str(it.get("context") or ""))[1],
                            "at": int(it.get("at") or 0), "session": str(it.get("session") or "")})  # fmt: skip
            for c in b.get("carried") or ():
                if not isinstance(c, Mapping) or not isinstance(c.get("decided"), Mapping):
                    continue
                out.append({"repo": repo, "key": str(c.get("key") or ""), "open": False,
                            "decided": str(c["decided"].get("date") or ""), "by": c.get("decided_by"),
                            "delegate": c.get("decided_delegate"), "scope": c.get("decided_scope"),
                            "said": str(c["decided"].get("text") or ""),
                            "refs": [str(r) for r in c.get("refs") or ()],
                            "parts": [str(p) for p in c.get("parts") or ()], "gate": c.get("gate"),
                            "closed": dict(c.get("closed") or {}), "to": [str(t) for t in c.get("to") or ()],
                            "at": int(c.get("at") or 0), "session": ""})  # fmt: skip
    return out


def _line_order(ln: Mapping[str, Any]) -> tuple[Any, ...]:
    """A line's place among the lines that name one entry (§4.4 *One line answers*): an undecided open line first,
    then by `Decided:`, open before closed, the later `Closed:`, the later carried-to entry, the greater key —
    `board_hold`'s order, with the undecided open line it never compares."""
    closed = (ln.get("closed") or {}).get("date") or ""
    undecided = bool(ln.get("open")) and ln.get("decided") is None
    return (undecided, ln.get("decided") or "", bool(ln.get("open")), closed, _carried_rank(ln), ln.get("key") or "")


def held_builds(
    design: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    linked: Mapping[str, str],
    *,
    lines: list[dict[str, Any]] | None = None,
) -> list[str]:
    """A design's **held builds** (§4.4 *A design's question is asked once, on the design*, TD-2021, TD-2026), as
    `<repo>#TD-n` in key order: for an open entry (`design`, with its `repo`) carrying `decision (paul)` whose `Owner:`
    is not the person, the ids its **newest** `decide` line with a `Parts:` — open or closed, decided or not
    (`_board_lines`, `_line_order`), its `Context:` naming the design alone with that gate — lists in `Parts:`, each
    a bare id of the design's repo, open in `entries`, `Part of` the design, carrying the gate itself, not the
    person's own, and named in the `Context:` of no open undecided line of its own. [] for any other entry. `lines`
    is `_board_lines(boards)`, passed by a caller that reads many designs."""
    if not ledger_mod.decided_by(dict(design), PERSON) or str(design.get("owner") or "").lower() == PERSON:
        return []
    repo = str(design.get("repo") or "")
    me = qid(repo, str(design.get("id") or ""))
    key = lb._gate_key(_GATE)
    lines = _board_lines(boards) if lines is None else lines
    newest: dict[str, Any] | None = None
    for ln in lines:
        if not ln["parts"] or not ln.get("gate") or lb._gate_key(str(ln["gate"])) != key:
            continue
        named = {q for r in ln["refs"] if (q := _line_qid(r, ln["repo"], linked))}
        if named != {me}:
            continue
        if newest is None or _line_order(ln) > _line_order(newest):
            newest = ln
    if newest is None:
        return []
    asked = {  # the entries an open undecided line names in its own `Context:`
        q
        for ln in lines
        if ln.get("open") and ln.get("decided") is None
        for r in ln["refs"]
        if (q := _line_qid(r, ln["repo"], linked))
    }
    out: list[str] = []
    for p in newest["parts"]:
        if "#" in p or newest["repo"] != repo:
            continue  # one level, the design's repo alone
        q = _line_qid(p, repo, linked)
        e = entries.get(q or "")
        if e is None or q == me or q in out or parent_qid(e) != me:
            continue
        if not ledger_mod.decided_by(dict(e), PERSON) or str(e.get("owner") or "").lower() == PERSON:
            continue
        if q in asked:
            continue  # covered by an open undecided line of its own: it reads its own hold
        out.append(str(q))
    return sorted(out, key=lambda q: _key_sort(str(entries[q].get("key") or ""), q))


def held_map(
    entries: Mapping[str, Mapping[str, Any]],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    linked: Mapping[str, str],
) -> dict[str, str]:
    """`{build: design}` over every design with a question (§4.4 *A design's question is asked once, on the design*,
    TD-2026): `held_builds` read for each open entry of `entries`, the one reading every reader of the set reads."""
    lines = _board_lines(boards)
    out: dict[str, str] = {}
    for q, e in entries.items():
        for b in held_builds(e, entries, boards, linked, lines=lines):
            out.setdefault(b, q)
    return out


def go_builds(held: Mapping[str, str], entries: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """Each design with a question's held builds as bare ids in key order (`_key_sort`), `{design: [TD-a, …]}`, from
    `held_map`'s `{build: design}` (§4.4 *A design's question is asked once, on the design*, TD-2026): the `go_builds`
    a design's Queue row, `ledger_for_you` row and `answered.lift` carry, which **Go now** reads (TD-2027)."""
    out: dict[str, list[str]] = {}
    for b in sorted(held, key=lambda b: _key_sort(str((entries.get(b) or {}).get("key") or ""), b)):
        out.setdefault(held[b], []).append(b.rpartition("#")[2])
    return out


def _line_named(ln: Mapping[str, Any], refs_open: Mapping[str, str]) -> list[str]:
    """The entries a `_board_lines` line names in its `Context:` refs and `Parts:`, as `<repo>#TD-n`."""
    return [q for r in [*ln["refs"], *ln["parts"]] if (q := _line_qid(r, ln["repo"], refs_open))]


def covered_by_open_line(
    member: Mapping[str, Any], items: Iterable[Mapping[str, Any]], refs_open: Mapping[str, str]
) -> bool:
    """Whether an open, undecided `decide` line covers `member` (an open entry with its `repo`) — names it, or the
    entry it is `Part of`, in its `Context:` or `Parts:` — so the entry asks again (§4.4 *The card's status*,
    TD-1368). `items` are `_board_lines`' lines, open and closed alike: the open, undecided ones are kept here. One
    test, which `board_hold` and the handed cover (`handed_hold`, §4.5 screen 12 *Three verbs: Have a session do
    it*, TD-1660) both make."""
    me = qid(str(member.get("repo") or ""), str(member.get("id") or ""))
    parent = parent_qid(member)
    for ln in items:
        if not ln.get("open") or ln.get("decided") is not None:
            continue
        named = _line_named(ln, refs_open)
        if me in named or (parent is not None and parent in named):
            return True
    return False


def handed_hold(
    member: Mapping[str, Any],
    handed: Iterable[Mapping[str, Any]],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    refs_open: Mapping[str, str],
    now: datetime,
) -> dict[str, Any] | None:
    """An entry the person handed a seat by **Have a session do it** (§4.5 screen 12 *Three verbs: Have a session do
    it*, TD-1660), or None. `member` is an open entry with its `repo` that waits on the person and is not *with
    you* (the caller's test); `handed` the person's handed asks, the `inbox` read's `handed` list (`agent_mail.
    handed_list`), each the holder's copy with its `holder` and `entry`; `boards` the board readings by repo name.

    The cover holds while an ask whose `entry.refs` names the member is open — no outcome, for fewer than
    `BOARD_WAIT_DAYS` civil days from its first send's local date (`entry.handed_at`, else its `at`), or a `blocked`
    outcome, with no day bound (TD-1556) — and no open, undecided `decide` line covers the member
    (`covered_by_open_line`), which asks again. A copy moved on (`rerouted`) is skipped. Of several, the newest
    first send. `{kind: "handed", mid, asker, closed_at, outcome}`, `asker` the holder's id, `closed_at` the first
    send, `outcome` a `blocked` one as it is."""
    if covered_by_open_line(member, _board_lines(boards), refs_open):
        return None
    me = qid(str(member.get("repo") or ""), str(member.get("id") or ""))
    today = now.astimezone().date()  # the board's waits count civil days, local
    best: tuple[datetime, Mapping[str, Any], Mapping[str, Any]] | None = None
    for h in handed:
        entry = h.get("entry") if isinstance(h, Mapping) else None
        if not isinstance(entry, Mapping) or h.get("closed_reason") == "rerouted":
            continue
        outcome = h.get("outcome")
        blocked = isinstance(outcome, Mapping) and outcome.get("state") == "blocked"
        if outcome and not blocked:
            continue  # its outcome ends it: the entry is the person's again
        repo = str(entry.get("key") or "").partition(":")[0]
        if me not in {q for r in entry.get("refs") or () if (q := _line_qid(str(r), repo, refs_open))}:
            continue
        sent = _aware(entry.get("handed_at")) or _aware(h.get("at"))
        if sent is None:
            continue
        if not blocked and (today - sent.astimezone().date()).days >= BOARD_WAIT_DAYS:
            continue  # unanswered past the board's wait: the entry comes back counted
        if best is None or sent > best[0]:
            best = (sent, h, outcome if blocked else {})
    if best is None:
        return None
    sent, h, outcome = best
    return {
        "kind": "handed",
        "mid": str(h.get("id") or ""),
        "asker": naming.split_address(str(h.get("holder") or ""))[0],
        "closed_at": sent.isoformat(),
        "outcome": dict(outcome) if outcome else None,
    }


def _carried_rank(ln: Mapping[str, Any]) -> int:
    """A closed line's place among same-day answers (§4.4 *One line answers*, TD-2020): the highest `TD-m` number
    its `Closed:` carries it to, 0 where it carries to none. A later answer is carried to an entry filed later, so
    the higher number is the newer answer; the board keeps no time of day."""
    return max((int(m.group(2)) for t in ln.get("to") or () if (m := TD_REF.search(str(t)))), default=0)


def board_hold(
    member: Mapping[str, Any],
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    refs_open: Mapping[str, str],
    now: datetime,
    *,
    claims: Mapping[str, str],
    entries: Mapping[str, Mapping[str, Any]],
    live: Mapping[str, str],
) -> dict[str, Any] | None:
    """A `decision (paul)` member the person answered on the board (§4.4 *The card's status*, *A question the
    person answered on the board holds the member the same way*, TD-1368), or None — it needs the person.

    `boards` the board readings by repo name (each `{items, carried}`, *The boards*); `claims` each live record's
    unexpired claim — `board:<key>` and `<repo>#TD-n` — to its holder's id, the person's own sessions left out;
    `entries` the open entries by `<repo>#TD-n`; `live` each live record's id and name to its id.

    A `decide` line **covers** the member when its `Context:` or `Parts:` names it, or names the entry it is
    `Part of` (the member carries `decision (paul)`, or it would not be asked). An open undecided covering line
    asks again: None. Of the covering lines `Decided:` with no `by` or `by` the person, the newest by `Decided:`
    (an open line before a closed one, then the later `Closed:`, then the later carried-to entry — its highest
    `TD-m` number, `_carried_rank` — then the greater key; never the line's `at`, a position in a board file that
    says nothing of order across the archive's per-item files, TD-2020) alone decides: an open
    line holds while open; one closed *carried to TD-m* or *see TD-m* (the same words, TD-1528) while a TD-m is
    open, not covered, not the person's and `Added:` no earlier than a day before the `Decided:`; one closed
    `— kept waiting.` until its `kept waiting` Log date plus `REASK_DAYS`; one closed in other words while a live
    claim holds a covered member, within `BOARD_WAIT_DAYS` of its `Closed:`. `{kind: "board", asker, closed_at,
    outcome: None, line: {key, open, to}}`,
    `asker` a record's id, `TD-m` (`<repo>#TD-m` when not the member's repo) or *a pick*; a kept-waiting one
    `{kind: "board", until, line}`, no `asker`."""
    me = qid(str(member.get("repo") or ""), str(member.get("id") or ""))
    parent = parent_qid(member)
    today = now.astimezone().date()  # the board's dates are civil dates, local
    lines = _board_lines(boards)
    if covered_by_open_line(member, lines, refs_open):
        return None  # an open undecided line covering the member asks again
    picked: tuple[tuple[Any, ...], dict[str, Any], list[str]] | None = None
    for ln in lines:
        named = _line_named(ln, refs_open)
        if me not in named and (parent is None or parent not in named):
            continue
        if ln["by"] and str(ln["by"]).strip().lower() != PERSON:
            continue  # a line decided by someone else is not the person's answer
        closed = (ln["closed"] or {}).get("date") or ""
        k = (ln["decided"], ln["open"], closed, _carried_rank(ln), ln["key"])
        if picked is None or k > picked[0]:
            picked = (k, ln, [me, *named])
    if picked is None:
        return None
    _, ln, covered = picked
    line = {"key": ln["key"], "open": ln["open"], "to": list(ln["to"]), "said": ln["said"]}
    if ln.get("delegate"):  # a delegated answer names its delegate and scope (ledgerboard v3.4, TD-1939)
        line.update(delegate=ln["delegate"], scope=ln.get("scope"))
    held = next((claims[q] for q in covered if q in claims), None)  # a covered member's holder, the member first
    if ln["open"]:
        asker = line_holder(ln["key"], ln["session"], covered, claims, live) or "a pick"
        return {"kind": "board", "asker": asker, "closed_at": ln["decided"], "outcome": None, "line": line}
    why = str((ln["closed"] or {}).get("why") or "").strip().lower()
    if ln["to"]:
        decided = _civil(ln["decided"])
        got: list[str] = []
        for t in ln["to"]:
            tq = _line_qid(t, ln["repo"], refs_open)
            e = entries.get(tq or "")
            if e is None or tq in covered or str(e.get("owner") or "").lower() == PERSON:
                continue
            if ledger_mod.decided_by(dict(e), PERSON):
                continue
            added = _civil(e.get("added"))
            if decided is None or added is None or added < decided - timedelta(days=1):
                continue
            got.append(str(tq))
        if not got:
            return None
        tq = next((q for q in got if q in claims), got[0])
        # a bare `TD-m` is its own board's repo's (§4.5 screen 12 *Where a row is drawn*): another repo's keeps
        # its qualifier, so a carried-to agent-cadence#TD-221 never reads as this repo's TD-221 (TD-1424)
        repo, _, tid = tq.partition("#")
        asker = claims.get(tq) or (tid if repo == me.partition("#")[0] else tq)
        return {"kind": "board", "asker": asker, "closed_at": ln["decided"], "outcome": None, "line": line}
    if why.startswith("kept waiting"):
        kept = _civil((member.get("kept_waiting") or {}).get(_GATE))
        if kept is None or today >= kept + timedelta(days=REASK_DAYS):
            return None  # no `kept waiting` date inside `reask_days`: its test has ended
        until = (kept + timedelta(days=REASK_DAYS)).isoformat()
        return {"kind": "board", "until": until, "closed_at": ln["decided"], "line": line}
    if why.startswith("lifted"):
        return None
    at = _civil(ln["closed"].get("date") if ln["closed"] else None)
    if held is None or at is None or (today - at).days >= BOARD_WAIT_DAYS:
        return None
    return {"kind": "board", "asker": held, "closed_at": ln["decided"], "outcome": None, "line": line}


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
            self.origins[name] = lb.origin_path(str(r.get("remote") or "")) or ""

    def resolve(self, repo: str) -> str | None:
        """The name of the one reading a `<repo>` of an item names: a checkout's directory name, or its
        origin's path, exact before suffix (`ledger.pick_repo`, TD-1371); none, or two, is None."""
        return ledger_mod.pick_repo(repo, self.origins, {n: n for n in self.by_name})

    def of_record(self, rec: Any) -> str | None:
        """The reading a record works in: its `repo`, the checkout's root."""
        for name, root in self.roots.items():
            if _same_dir(getattr(rec, "repo", None), root):
                return name
        return None


_CLAIM_REF_RE = re.compile(r"(?:(?P<repo>[^#\s]+)#)?(?P<id>TD-\d+)", re.IGNORECASE)


def held_claims(records: Iterable[Any], repos: Mapping[str, Mapping[str, Any]], now: datetime) -> dict[str, str]:
    """The one claims helper (§4.4 *The press's checks*, *Where Lift the hold is drawn*; TD-1851, built by TD-1831):
    `{ref: session id}` of every unexpired `claimed` progress row (by `LEASE_TTL`) of a live `unattended` record (not
    `exited` or `closed`, not superseded) — the person's own records, which are not `unattended`, left out. A
    `board:<key>` claim counts from any repo's record, as it is; an entry id only from a record of the entry's repo
    (`_Repos.of_record`), keyed `<repo>#TD-n` (`qid`, the ledger's normalised id), a `<repo>#TD-n` ref counted where
    its repo is the record's own. Records are read in id order, the first claim on a ref keeping it; `repos` are the
    home's readings by root, a remote host's records counted as the reading counts them."""
    rs = _Repos(repos)
    out: dict[str, str] = {}
    for rec in sorted(records, key=lambda r: str(r.id)):
        if getattr(rec, "state", "") in ("exited", "closed") or getattr(rec, "superseded_by", None):
            continue
        if not getattr(rec, "unattended", False):
            continue
        home = rs.of_record(rec)
        for p in rec.progress:
            at = _aware(p.at)
            if p.status != "claimed" or at is None or now - at >= LEASE_TTL:
                continue
            ref = str(p.ref or "")
            if ref.startswith(workorders.PREFIX):
                out.setdefault(ref, str(rec.id))
            elif home and (m := _CLAIM_REF_RE.fullmatch(ref)):
                if m.group("repo") and rs.resolve(m.group("repo")) != home:
                    continue
                out.setdefault(qid(home, m.group("id").upper()), str(rec.id))
    return out


def design_done(e: Mapping[str, Any]) -> bool:
    """§4.8 *A finished design lets go of its derived claim* (TD-1567): an open `design-first` entry that some entry,
    open or archived, names in `Part of:` (`parts_open`, `parts_archived` — an archived part keeps it done after its
    last build archives while the entry waits on something else, §4.9c) and whose `Blocked by:` carries no
    `decision (paul)` — the gate alone, never an `Owner:`."""
    return (
        str(e.get("kind") or "") == "design-first"
        and bool(e.get("parts_open") or e.get("parts_archived"))
        and not ledger_mod.decided_by(dict(e), PERSON)
    )


def finished_designs(repos: Mapping[str, Mapping[str, Any]]) -> Callable[[Any], frozenset[str]]:
    """For a record, the ids of its repo's open entries whose design is done (`design_done`), the repo found as the
    Queue maps a record to one (`_Repos.of_record`). A record it cannot map, or a repo with no ledger reading, reads
    the empty set, so its claims are left as they are — never retired on a reading the home lacks (TD-1725)."""
    reps = _Repos(repos)
    done = {
        name: frozenset(
            str(e["id"]) for e in r["ledger"]["entries"] if isinstance(e, Mapping) and e.get("id") and design_done(e)
        )
        for name, r in reps.by_name.items()
    }

    def of(rec: Any) -> frozenset[str]:
        name = reps.of_record(rec)
        return done.get(name, frozenset()) if name is not None else frozenset()

    return of


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


def _pressing(
    open_: Mapping[str, Mapping[str, Any]], boards: Mapping[str, Iterable[Any]], linked: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    """Each open member's press mark by qid (§4.4 *A press is drawn as it lands*, TD-1508): an entry's own mark (a
    ledger decide or road), else the mark of an open board line naming it in its `Context:` or `Parts:`."""
    pressing: dict[str, dict[str, Any]] = {q: dict(e["applying"]) for q, e in open_.items() if e.get("applying")}
    for name, bl in boards.items():
        for b in bl:
            for it in (b.get("items") or ()) if isinstance(b, Mapping) else ():
                if not isinstance(it, Mapping) or not isinstance(it.get("applying"), Mapping):
                    continue
                for ref in [*(it.get("refs") or ()), *(it.get("parts") or ())]:
                    if (q := _line_qid(str(ref), name, linked)) in open_:
                        pressing.setdefault(q, dict(it["applying"]))
    return pressing


def lay_held(queue: Mapping[str, Any], repos: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The Queue held back after a restart (`_queue_pass`, TD-1471) with the press marks of `repos` (the readings
    with `lay_applying`'s marks) laid over its members, so a press during the hold is drawn at once (TD-1518): a
    marked open row reads `applying_words` with no need, as `reading` draws it; a row the person holds
    (`with_you`) keeps its state, and a marked card's status is read again over its rows where all its members are
    in the readings. `queue` is the last reading `reading` gave, never one this wrote, so a mark that clears during
    the hold leaves the row and the card as that reading drew them. A copy; `queue` is never written."""
    rs = _Repos(repos)
    open_: dict[str, dict[str, Any]] = {}
    for name, r in rs.by_name.items():
        for e in r["ledger"]["entries"]:
            if isinstance(e, Mapping) and e.get("id"):
                open_.setdefault(qid(name, e["id"]), {**e, "repo": name})
    boards = {n: list((r.get("boards") or {}).get("boards") or ()) for n, r in rs.by_name.items()}
    linked = open_refs(open_, rs.origins)
    # the facts `_status` reads, as `reading` stamps them: each member's counted open work, a design with a question
    # taking in its held builds', and each held build's design (§4.4 *A design's question is asked once*, TD-2026)
    held_by = held_map(open_, boards, linked)
    resolve = item_resolver(rs.origins)
    for q, work in with_held(open_work(open_, resolve), held_by, open_, resolve).items():
        open_[q]["open_work"] = work
    for b, d in held_by.items():
        open_[b]["held_by"] = d
    pressing = _pressing(open_, boards, linked)

    def mark(row: Any) -> Any:
        if not isinstance(row, Mapping) or row.get("archived") or row.get("with_you"):
            return row
        if (applying := pressing.get(str(row.get("qid") or ""))) is None:
            return row
        # `restart_home` stays, so the card is still *needs you* (TD-1856); the word it replaces goes
        return {**row, "state": applying_words(applying), "needs": None, "answered": None, "applying": applying,
                "lift_here": False, "restart_word": False}  # fmt: skip

    def card(c: Any) -> Any:
        if not isinstance(c, Mapping):
            return c
        top, rows = mark(c.get("top")), [mark(r) for r in c.get("rows") or ()]
        if top is c.get("top") and all(a is b for a, b in zip(rows, c.get("rows") or (), strict=True)):
            return c  # no mark on it: the card as the reading drew it
        out = {**c, "top": top, "rows": rows}
        # its status read again over the marked rows, as `reading` reads it, where every member is in the readings
        members = [str(q) for q in c.get("order") or ()]  # the open members
        if isinstance(top, Mapping) and members and all(q in open_ for q in members):
            out["status"] = _status([top, *(r for r in rows if isinstance(r, Mapping) and not r.get("archived"))],
                                    [open_[q] for q in members])  # fmt: skip
            out["stalled_holder"] = stalled_holder([top, *rows])
        return out

    return {**queue, "cards": [card(c) for c in queue.get("cards") or ()]}


def reading(
    repos: Mapping[str, Mapping[str, Any]],
    records: Iterable[Any],
    now: datetime,
    *,
    waiting: Collection[str] = (),
    doing: Mapping[str, list[Mapping[str, Any]]] | None = None,
    questions: Iterable[Any] = (),
    archived: Mapping[str, list[dict[str, Any]]] | None = None,
    host: str = "",
    handed: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The `queue` reading (§4.4 *The Queue*): `{cards, completed, other_work, origins, at}`.

    `repos` are the home's repo readings by root; `records` the live graph's `Session`s (an ended one
    holds nothing); `waiting` the ids of sessions that wait on a question (the person's, or a reader
    holding their ask), which keeps an idle holder from reading *stalled*; `doing` the doing log by
    team (`{team: [{id, text, at}]}`), whose first line after a claim is a passed-over flag's reason;
    `questions` the person inbox, whose answered questions about a held entry read *answered — waiting on
    <asker>* (`answered_hold`, TD-1316); `archived` each root's archive entries as its ledger read gave them
    (`ledger.archived`, the host agent's `_archived`, TD-1471) — read through the same compare against origin as
    the open entries, so one id never reads open and archived at once, and the Queue runs no git.

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
    names no open entry (`board:<key>`, a PR naming none), with its holder. `origins` maps each repo's name to its
    origin path, for a repo with a readable origin (`card_index`, TD-1371); `design_prs` the design PR an item about
    each entry links (`design_prs`, TD-1531). `host` is the home's own host name, against which `records` (other
    hosts' among them, `host` set) are keyed (`asker_repos`, TD-1541); `handed` the person's handed asks (the
    `inbox` read's `handed` list), whose `refs` draw an entry that waits on the person *handed to <seat>*
    (`handed_hold`, TD-1660)."""
    rs = _Repos(repos)
    records = list(records)
    # every record's state by id, ended ones too: an answered question's asker exited or closed is gone (TD-1316)
    states = {str(r.id): str(getattr(r, "state", "") or "") for r in records}
    names = {str(r.id): str(getattr(r, "name", "") or r.id) for r in records}
    questions = list(questions)
    handed = [h for h in handed if isinstance(h, Mapping)]
    askers = asker_repos(questions, records, rs.roots, host)  # a bare `TD-n` is its asker's repo's (TD-1509, TD-1541)
    recs = [r for r in records if getattr(r, "state", "") not in ("exited", "closed") and not r.superseded_by]
    open_: dict[str, dict[str, Any]] = {}
    for name, r in rs.by_name.items():
        for e in r["ledger"]["entries"]:
            if isinstance(e, Mapping) and e.get("id"):
                open_.setdefault(qid(name, e["id"]), {**e, "repo": name})
    given = archived or {}
    archived = {}  # every archived entry, by qid
    for name in rs.by_name:
        for a in given.get(rs.roots[name]) or ():
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
            if ledger_mod.is_gate(b):
                continue  # an `until` or `event` gate is a wait, never past reach (TD-1395)
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
    holds: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for rec in recs:
        home = rs.of_record(rec)
        for n, p in enumerate(rec.progress):
            if p.status != "claimed":
                continue
            if home and (q := qid(home, p.ref) if re.fullmatch(r"TD-\d+", p.ref) else None) in open_:
                held.setdefault(q, []).append((rec, p))
                # a stopped holder's state row reads which of its claims to draw on (TD-1468): `n` its place in
                # the record's `progress`, the tie's order
                holds.append({"sid": str(rec.id), "qid": q, "source": p.source, "at": p.at, "n": n})
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

    linked = open_refs(open_, rs.origins)
    # what a board answer's hold reads (§4.4 *The card's status*, TD-1368): the boards by repo, each live record's
    # unexpired claims — the person's own sessions left out — and the live records by id and name
    boards = {n: list((r.get("boards") or {}).get("boards") or ()) for n, r in rs.by_name.items()}
    claims = held_claims(recs, repos, now)
    live: dict[str, str] = {}
    for rec in sorted(recs, key=lambda r: str(r.id)):
        live.setdefault(str(rec.id), str(rec.id))
        live.setdefault(str(getattr(rec, "name", "") or rec.id), str(rec.id))

    # the fact (§4.4 *The card's status*, TD-1926): a `decision (paul)` member's counted open work, on the entry,
    # read by its rows, Lift, `_own` and `_status`'s `waits`, whatever word a row draws — a design with a question
    # taking in its held builds' (§4.4 *A design's question is asked once, on the design*, TD-2026), so it is read
    # once the boards and `linked` are
    held_by = held_map(open_, boards, linked)
    for q, work in with_held(open_work(open_, xref), held_by, open_, xref).items():
        open_[q]["open_work"] = work
    for b, d in held_by.items():
        open_[b]["held_by"] = d  # the entry stamp, on every held build whatever its row's word (TD-2026)
    go = go_builds(held_by, open_)
    pressing = _pressing(open_, boards, linked)
    # the row each live record's restart row is homed on, where its mark passes the one reader (§4.4 *The card's
    # status*, TD-1856): the claim `holder_claims` picks, as the Inbox's `item_home` picks it — every `holds` qid is
    # in `open_`, so the pick is the page's
    from sessionorc import agent_common  # the tick's readers; imported late, as the agent's modules import this

    marked = {str(rec.id) for rec in recs if agent_common.restart_waits_of(rec) is not None}
    restart_homes = {q for sid, q in holder_claims(holds, open_).items() if sid in marked}
    # the open decided lines that hide an entry's item, each with what it covers: a row's ⋯ Lift reads them (TD-1831)
    decided_lines = open_decided_lines(boards, open_, linked, person_only=True)
    # the design PR an item about each entry links (TD-1531), with its synopsis (TD-1536)
    synopses = {n: r.get("synopses") for n, r in rs.by_name.items() if isinstance(r.get("synopses"), Mapping)}
    designs = design_prs(rs.roots, {n: r.get("prs") for n, r in rs.by_name.items()}, open_, archived, synopses)

    def own_synopsis(q: str) -> dict[str, Any] | None:
        """A design entry's own line's synopsis, by its own id alone (a build's, read from its parent, is none)."""
        d = designs.get(q) or {}
        syn = d.get("synopsis")
        return dict(syn) if d.get("own") and isinstance(syn, Mapping) and syn.get("exists") else None

    def row(q: str) -> dict[str, Any]:
        if q in open_:
            e = open_[q]
            st, needs, hold, restart = _state(e, held.get(q, []), prs.get(q), recs, set(waiting), now)
            word = st
            # the need rows' `with_you` mark is the person's own session on a row that waits on them (TD-1281); on
            # any other row it holds, its record is the holder alone and the row carries no mark (TD-1567)
            mine = hold if needs else None
            claim = held.get(q)
            # *with you in <name>* first; then a held entry's answered question (§4.4 *A row's state*, TD-1316)
            answered = (
                answered_hold(
                    e,
                    questions,
                    states,
                    linked,
                    now,
                    boards=boards,
                    claims=claims,
                    entries=open_,
                    live=live,
                    asker_repo=askers,
                )  # fmt: skip
                if needs and not mine
                else None
            )
            if needs and not mine and answered is None and handed:
                # a step handed by Have a session do it, its ask open (§4.5 screen 12, TD-1660): a mail or board
                # answer wins, and the mark below is drawn over it
                answered = handed_hold(e, handed, boards, linked, now)
            if answered and answered.get("until"):
                st = f"waits until {answered['until']}"  # the person's own *not yet*, until the re-ask (TD-1368)
            elif answered:
                answered["name"] = names.get(answered["asker"], answered["asker"])
                handed_to = answered.get("kind") == "handed"
                st = f"handed to {answered['name']}" if handed_to else f"answered — waiting on {answered['name']}"
            applying = pressing.get(q) if not mine else None  # *with you* first, then the mark (TD-1508)
            if applying:
                st, needs, answered = applying_words(applying), None, None  # the mark is no need of the person
            # *waiting, then yours* (TD-1926): a member that would otherwise need the person and whose question waits
            # on open work; every word above keeps its place, and the row keeps its `needs`, marked
            fact = list(e.get("open_work") or ())
            then_yours = fact if fact and needs and not mine and not answered else None
            if then_yours:
                st = "waiting, then yours"
            # **Lift the hold** in the row's ⋯ (§4.4 *Where Lift the hold is drawn*, TD-1831): read on its own,
            # whichever answer's word the row draws; never on a *with you* row or under a press's mark
            lift = (
                not mine
                and not applying
                and not fact  # a member with counted open work draws no Lift, whatever its word (TD-1926)
                # interim (TD-2026; TD-2027 step 1 draws **Go now** there): a design with held builds draws no Lift,
                # which would lift the design alone
                and q not in go
                and lift_here(
                    e,
                    decided_lines,
                    claims,
                    live,
                    boards,
                    open_,
                    rs.origins.get(e["repo"]) or str(e["repo"]).lower(),
                    held_by,
                )
            )
            return {
                "qid": q,
                "repo": e["repo"],
                "id": e["id"],
                "title": e.get("title") or "",
                "priority": e.get("priority") or "",
                "state": st,
                "needs": needs,
                "pr": (prs.get(q) or {}).get("number"),
                # the person's own session holding their entry is its holder whatever else claims it (TD-1281,
                # TD-1567), and a *stalled* row's the record it stands for, the first stuck one by id (TD-1567)
                "holder": hold or (_holder(claim[0][0]) if claim and st != "stalled" else None),
                # the row reads a restart word (TD-1856), from `_state`'s mark and never by the words: its word
                # links the record's Focus, drawn `s-restart`
                "restart_word": restart is not None and st == word,
                # the row the restart row of a record whose mark passes the reader is homed on (`holder_claims`,
                # TD-1856), whatever word it reads: its card is *needs you*
                "restart_home": q in restart_homes,
                "with_you": mine["name"] if mine else None,
                "answered": answered,
                "applying": applying,
                "open_work": fact,  # the fact, whatever the word (TD-1926)
                "then_yours": then_yours,  # the word's mark: its counted ids, a need no test of need reads
                "lift_here": bool(lift),
                "go_builds": list(go.get(q) or ()),  # a design with a question's held builds (TD-2026)
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
                "synopsis": own_synopsis(q),  # a design entry's own line ends its title with it (TD-1536)
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
            "restart_word": False,
            "restart_home": False,
            "with_you": None,
            "answered": None,
            "applying": None,
            "open_work": [],
            "then_yours": None,
            "lift_here": False,
            "go_builds": [],
            "page": "",
            "after": [],
            "blocked_open": False,
            "builds_open": False,
            "key": "",
            "lined": False,
            "archived": True,
            "closed": _closed(a["fields"], closed_at.get(q)),
            "sha": (closed_at.get(q) or {}).get("sha"),  # the closing commit, the page's live mark (TD-904)
            "by": (closed_at.get(q) or {}).get("by"),  # who closed it, from that commit's trailers (TD-1899)
            "resolved": _resolved_text(a["fields"]),
            "synopsis": own_synopsis(q),
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
        "origins": {n: o for n, o in rs.origins.items() if o},
        # the entry each PR names, for an item that carries a PR alone (TD-1468)
        "pr_refs": {k: v for n, r in rs.by_name.items() for k, v in pr_refs(n, r.get("prs")).items()},
        # every live claim on an open entry, for a stopped holder's state row (TD-1468)
        "holds": holds,
        # the design PR an item about each entry links (TD-1531)
        "design_prs": designs,
        "at": now.isoformat(),
    }


def item_resolver(origins: Mapping[str, str]) -> Callable[[str], str | None]:
    """A `<repo>#TD-n` item's `<repo>#TD-n` qid among the readings named in `origins` (name → origin path, '' for
    none), as the Queue's reading resolves one (`_Repos.resolve`, `ledger.pick_repo`); None where no one reading is
    named."""

    def xref(item: str) -> str | None:
        m = lb.XREPO_ITEM_RE.match(item)
        name = ledger_mod.pick_repo(m.group(1), dict(origins), {n: n for n in origins}) if m else None
        return qid(name, m.group(2)) if m and name else None

    return xref


def _open_blockers(entries: Mapping[str, Mapping[str, Any]], xref: Callable[[str], str | None]) -> dict[str, set[str]]:
    """Each open entry's open `Blocked by:` ids, this repo's and a `<repo>#TD-n` `xref` resolves, by `<repo>#TD-n`."""
    out: dict[str, set[str]] = {q: set() for q in entries}
    for q, e in entries.items():
        named = [qid(str(e.get("repo") or ""), str(b)) for b in e.get("blocked_ids") or []]
        named += [x for x in map(xref, e.get("xrepo_ids") or []) if x]
        out[q] |= {n for n in named if n in entries and n != q}
    return out


def _reaches(blockers: Mapping[str, Collection[str]], start: str, target: str) -> bool:
    """Whether `start`'s open `Blocked by:` chain (`_open_blockers`) reaches `target`; a visited set guards a cycle."""
    seen, todo = {start}, [start]
    while todo:
        for b in blockers.get(todo.pop(), ()):
            if b == target:
                return True
            if b not in seen:
                seen.add(b)
                todo.append(b)
    return False


def open_work(entries: Mapping[str, Mapping[str, Any]], xref: Callable[[str], str | None]) -> dict[str, list[str]]:
    """Each `decision (paul)` member's **counted open work** (§4.4 *The card's status*, *A `decision (paul)` member
    that still waits on open work is no need*, TD-1926): the open ids in its `Blocked by:` — this repo's, and a
    `<repo>#TD-n` that `xref` resolves to an open entry — and the open entries naming it in `Part of:`, less each
    that carries `decision (paul)` itself and each whose own open `Blocked by:` chain reaches the member (its answer
    comes first; a visited set guards a cycle). An id that resolves to no open entry, and an `until` or `event`
    gate, count for nothing. `entries` are the open entries by `<repo>#TD-n`, each with its `repo`; the result
    holds only members with some, each list in key order (`_key_sort`, this repo's before another's). One builder:
    the Queue's reading, the Inbox's `ledger_for_you` and the home's refusal of a stale press all call it."""
    blockers = _open_blockers(entries, xref)
    parts: dict[str, set[str]] = {q: set() for q in entries}
    for q, e in entries.items():
        if e.get("part_of") and (n := qid(str(e.get("repo") or ""), str(e["part_of"]))) in entries and n != q:
            parts[n].add(q)

    def held(q: str) -> bool:
        return ledger_mod.decided_by(dict(entries[q]), PERSON)

    out: dict[str, list[str]] = {}
    for q in entries:
        if not held(q):
            continue
        counted = [w for w in blockers[q] | parts[q] if not held(w) and not _reaches(blockers, w, q)]
        if counted:
            out[q] = sorted(counted, key=lambda w: _key_sort(str(entries[w].get("key") or ""), w))
    return out


def with_held(
    work: Mapping[str, list[str]],
    held: Mapping[str, str],
    entries: Mapping[str, Mapping[str, Any]],
    xref: Callable[[str], str | None] | None = None,
) -> dict[str, list[str]]:
    """`open_work`'s result with each held build's counted open work added to its design's (§4.4 *A design's question
    is asked once, on the design*, TD-2026): `held` is `held_map`'s `{build: design}`; each design takes in its
    builds' ids as merged so far, without repeats and in key order (`_key_sort`), a design with none of its own
    getting the key; a design that is itself a held build is merged before its own design, innermost first, so an
    outer design takes in the inner one's merged work. A build's id whose own open `Blocked by:` chain reaches the
    design is not added, as `open_work` drops one reaching the member (its answer comes first, TD-2058; `xref` resolves
    a `<repo>#TD-n` in the chain, `open_work`'s resolver). A build keeps its own. A copy; `work` is never written."""
    out = {q: list(ids) for q, ids in work.items()}
    blockers = _open_blockers(entries, xref or (lambda _item: None))

    def depth(d: str) -> int:
        n, seen = 0, {d}
        while (d := held.get(d, "")) and d not in seen:
            seen.add(d)
            n += 1
        return n

    designs = sorted(set(held.values()), key=lambda d: (-depth(d), d))
    for d in designs:
        got = list(out.get(d) or [])
        for b, of in held.items():
            if of == d:
                got += [w for w in out.get(b) or () if w not in got and w != d and not _reaches(blockers, w, d)]
        if got:
            out[d] = sorted(got, key=lambda w: _key_sort(str((entries.get(w) or {}).get("key") or ""), w))
    return out


def _holder(rec: Any) -> dict[str, Any]:
    return {"id": rec.id, "name": rec.name, "state": rec.state}


def _state(
    e: Mapping[str, Any],
    claims: list[tuple[Any, Any]],
    pr: Mapping[str, Any] | None,
    recs: list[Any],
    waiting: set[str],
    now: datetime,
) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """A row's one state word, the first that applies (§4.4 *A row's state*), what it needs of the person —
    `owner` (`Owner: paul`) or `decision` (`decision (paul)`) — when it waits on them, which draws no word, and
    the row's holder where the word stands for one: the person's own session where one claims the entry, the
    first by id of its claims' records with `unattended: false`, whose name *with you in <name>* carries (TD-1281;
    on a row that needs nothing too, TD-1567), else a restart word's record (TD-1856), else a *stalled* row's first
    stuck record by id (TD-1567); and, fourth, the restart mark the word was read from (`agent_common.restart_waits`),
    None where it read none. The row keeps its need; the caller sets the need rows' `with_you` mark from the holder
    only where the need is set."""
    # `Owner: paul` holds nothing (TD-1375): the gate is the need, and the Owner says it is the person's to do
    need = (
        ("owner" if str(e.get("owner") or "").lower() == PERSON else "decision")
        if ledger_mod.decided_by(dict(e), PERSON)
        else None
    )
    own = sorted((rec for rec, _ in claims if not getattr(rec, "unattended", False)), key=lambda r: str(r.id))
    if need:
        if own:
            return f"with you in {own[0].name}", need, _holder(own[0]), None
        return "", need, None, None
    if not own and (marked := _restart_holder(claims)):  # before *stalled* (§4.4, TD-1856)
        rec, mark = marked
        return mark["word"], None, _holder(rec), mark
    word = _state_word(e, claims, pr, recs, waiting, now, own=own[0] if own else None)
    if own:
        return word, None, _holder(own[0]), None
    if word == "stalled":
        stuck = sorted((rec for rec, _ in claims if _holder_stuck(rec, waiting, now)), key=lambda r: str(r.id))
        return word, None, _holder(stuck[0]) if stuck else None, None
    return word, None, None, None


def _restart_holder(claims: Iterable[tuple[Any, Any]]) -> tuple[Any, dict[str, Any]] | None:
    """The first record by id among a row's claims whose mark draws a restart row (§4.4 *A holder waiting on a
    restart is not stalled*, TD-1856), with its mark — read by the one reader, never `_holder_stuck`: an idle
    holder with a live subagent, or one working at its ceiling, reads the word too."""
    from sessionorc import agent_common  # the tick's readers; imported late, as the agent's modules import this

    for rec in sorted({id(r): r for r, _ in claims}.values(), key=lambda r: str(r.id)):
        if (mark := agent_common.restart_waits_of(rec)) is not None:
            return rec, mark
    return None


def _state_word(
    e: Mapping[str, Any],
    claims: list[tuple[Any, Any]],
    pr: Mapping[str, Any] | None,
    recs: list[Any],
    waiting: set[str],
    now: datetime,
    own: Any = None,
) -> str:
    """The state word of a row that needs nothing of the person, the first that applies (§4.4). `own`, the
    person's own session claiming it (TD-1567): the row is never *stalled*, and reads *with you in <name>* where
    it would read *held by <name>*; a red PR is *· being fixed* only while some claim's record is at work."""
    red = pr is not None and (pr.get("conflicting") or pr.get("checks") == "red" or pr.get("failing"))
    if own is None and any(_holder_stuck(rec, waiting, now) for rec, _ in claims):
        return "stalled"
    if red and not claims:
        since = _when(pr.get("red_since"))
        if since and now - since >= QUEUE_STALL_AFTER and not any(workorders.holds_pr(r, dict(pr)) for r in recs):
            return "stalled"
    if red:
        word = f"#{pr['number']} conflicting" if pr.get("conflicting") else f"#{pr['number']} failing"
        fixing = any(not _holder_stuck(rec, waiting, now) for rec, _ in claims) if own is not None else bool(claims)
        return word + (" · being fixed" if fixing else "")
    if pr is not None:
        return f"in review #{pr['number']}"
    if own is not None:
        return f"with you in {own.name}"
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
        # a record's restart row is homed on one of its rows (TD-1856): the field the header and the pill read
        "restart_home": any(r.get("restart_home") for r in open_rows),
        "stalled_holder": stalled_holder([top_row, *rows]),
        "wait": _wait(members, open_, blockers, parts, keyed, top),
        "start": _start(members, open_, keyed, top),
        "order": picked,
        "repos": sorted({open_[q]["repo"] for q in members}),
        "members": members,
        "passed_over": [],
    }


def _start(members: list[str], open_: Mapping[str, Mapping[str, Any]], keyed: Mapping[str, str], top: str) -> str:
    """The entry a **Start session** on the card starts on (§4.4 *One owner*, TD-912): its one `Owner: paul`
    entry that waits on the person (`decision (paul)`: an Owner alone holds nothing, TD-1375), else its first
    `decision (paul)` entry by key, else the top entry — by key alone, never by what is claimed, so two presses
    choose the same entry."""
    by_key = sorted(members, key=lambda q: _key_sort(keyed[q], q))
    # the gate itself, not `_own`: an entry whose question waits on open work is still the one Start opens (TD-1926)
    owned = [
        q
        for q in by_key
        if str(open_[q].get("owner") or "").lower() == PERSON and ledger_mod.decided_by(dict(open_[q]), PERSON)
    ]
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


def stalled_holder(rows: Iterable[Any]) -> dict[str, Any] | None:
    """The record a card's *stalled* stands for (§4.5 screen 12 *A holder's word opens the holder*, TD-1567): the
    holder of its first *stalled* row that has one, in the card's order — the top entry, then its rows as drawn."""
    for r in rows:
        if isinstance(r, Mapping) and not r.get("archived") and r.get("state") == "stalled" and r.get("holder"):
            return dict(r["holder"])
    return None


def _status(rows: list[dict[str, Any]], ents: list[Mapping[str, Any]]) -> str:
    """The ledger's part of a card's status (§4.4 *The card's status*): *needs you* > *stalled* > *blocked*
    > *waiting* > *ready*; *steer*, and a question's *needs you*, are the mail's. A row the person's own
    session holds (`with_you`, TD-1281), or whose question the person answered (`answered`, TD-1316), which
    keeps its `needs`, is no need. A row a record's restart row is homed on (`restart_home`, TD-1856) is a need
    first, whatever word it reads."""
    if any(r.get("restart_home") for r in rows):
        return "needs you"
    if any(r["needs"] and not r.get("with_you") and not r.get("answered") and not r.get("then_yours") for r in rows):
        return "needs you"
    if any(r["state"] == "stalled" for r in rows):
        return "stalled"

    def waits(e: Mapping[str, Any]) -> bool:
        if e.get("open_work"):  # a held member whose question waits on counted open work (TD-1926)
            return True
        if e.get("waiting") or e.get("settling"):  # a live check's `event (live)` gate among them (TD-1452)
            return True
        # blocked only by open ids (a gate is the `waiting` mark's, TD-1395)
        ids = [b for b in e.get("blocked_by") or [] if not ledger_mod.is_gate(b)]
        # an open part counts as an open id its parent is blocked by (TD-1130)
        return bool(ids or e.get("parts_open")) and all(not b.startswith("decision (") for b in ids)

    # a kind no lane takes, or an entry the home marked `no_lane` (§4.4 *An entry no lane takes is marked*, TD-1573)
    if any(e.get("unreachable") for e in ents) or all(e.get("for_page") in NO_LANE or e.get("no_lane") for e in ents):
        return "blocked"
    if all(waits(e) for e in ents):
        return "waiting"
    return "ready"


def _own(e: Mapping[str, Any]) -> bool:
    """The person's own member (§4.4 *Waiting*): `Blocked by: decision (paul)` — an `Owner: paul` alone holds
    nothing (TD-1375) — with no counted open work: one with some waits as a member blocked by open ids does
    (TD-1926), read from the stamped `open_work`, never from `parts_open`."""
    return ledger_mod.decided_by(dict(e), PERSON) and not e.get("open_work")


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
    own waits — an `until` or `event` gate in force (a live check's `event (live)` among them: its `live` reading
    holds nothing, TD-1452), settling, blocked by open ids or open parts once the person's own are set aside, blocked
    past the org's reach, or no lane takes it — and at least one is not the person's own. The leaf is a member that
    waits for a reason of its own, the first that applies: the top entry with a gate, the earliest `until` date, an
    event (a live check whose reading says `no` adds *(not live #n)*), settling, past reach — ties by key; a cycle
    of open ids with none is read as past reach."""
    own = {q for q in members if _own(open_[q])}
    rest = [q for q in members if q not in own]

    def by_key(q: str) -> tuple[tuple[int, ...], int, str]:
        return _key_sort(keyed[q], q)

    def far(e: Mapping[str, Any]) -> bool:
        return bool(e.get("unreachable") or e.get("no_lane")) or e.get("for_page") in NO_LANE

    def of_its_own(q: str) -> bool:
        e = open_[q]
        return bool(e.get("waiting") or e.get("settling")) or far(e)

    def counted(q: str) -> set[str]:  # a held member's counted open work (TD-1926), else its open ids and parts
        return set(open_[q].get("open_work") or ()) or (blockers[q] | parts[q])

    if not rest or not all(of_its_own(q) or counted(q) - own for q in rest):
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
        why = str(w.get("why") or "")  # the Event line's words (TD-1395)
        phrase = f"waits on {why}" if why else "waits on an event"
        e = open_[q]
        built = " ".join(f"#{n}" for n in e.get("built") or ())
        live_gate = str(w.get("name") or "").startswith("live")  # a live check's own gate (§4.9b)
        if e.get("kind") == "live-check" and e.get("live") == "no" and built and live_gate:  # words (TD-1452)
            phrase = f"{phrase.rstrip('.')} (not live {built})"
        return {"column": "event", "phrase": phrase, "id": q}

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
                    and ledger_mod.lane_matches(list(rec.lane), dict(open_[m]), rec.team or None, rec.id)
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
    (the closing commit, TD-904), `by` (who closed it, `ledger.closed_by`, TD-1899) and `resolved`, the
    `Resolved:` text — newest first, and `at` the newest `closed`.
    Beside `ids` and `titles`, keyed alike, `types`: each member's archived `Type:` read as `ledger.entries` reads an
    open entry's (`ledger.entry_type`), so always an entry type — what a kept card's item starts its session with
    (§4.5 screen 12 *Three verbs: An item on a kept card*, TD-1618)."""
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
                    "by": (closed_at.get(q) or {}).get("by"),
                    "resolved": _resolved_text(a["fields"]),
                }
            )
        ents.sort(key=lambda e: _closed_order(e["closed"]), reverse=True)
        out.append(
            {
                "id": min(members, key=lambda q: (int(q.partition("#")[2][3:]), q)),
                "ids": members,
                "titles": {q: archived[q].get("title") or "" for q in members},
                # each member's archived `Type:`, normalised as an open entry's: what a kept card's item starts with
                "types": {q: ledger_mod.entry_type((archived[q].get("fields") or {}).get("type")) for q in members},
                "closed": str(when),
                "pr": pr,
                "entries": ents,
                "at": ents[0]["closed"] if ents else str(when),
            }
        )
    out.sort(key=lambda c: c["closed"], reverse=True)
    return out
