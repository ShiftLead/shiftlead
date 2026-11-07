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
    elsewhere*, TD-1509): a row that names its repo never draws on another repo's card; no `repo` leaves them bare,
    looked up by `card_index`'s one-repo rule."""
    found = list(found)
    if not repo:
        return found
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


def mail_repo(q: Any, records: Mapping[str, Any], name_of: Callable[[Any], str]) -> str | None:
    """The entry's entry point of the repo helper (§4.10, §4.5 screen 6 *A mail item's bare ref is its sender's
    repo's*, TD-1467), the one place its order is written: its stamped `repo` (a name, as the send wrote it), else its
    orphan stamp's `repo` (TD-213: the asker's checkout then), else its sender's live record's `repo` — `records`,
    `{bare id: root}` — each root named by `name_of`; None where all three find none, and its bare refs stay bare.
    `item_home` reads it through `asker_repos`, `answered_hold` per question, and Telegram's link alike."""
    if stamped := str(_get(q, "repo") or "").strip():
        return stamped
    orphaned = _get(q, "orphaned")
    if isinstance(orphaned, Mapping) and (name := name_of(orphaned.get("repo"))):
        return name
    return name_of(records.get(naming.split_address(str(_get(q, "from_") or ""))[0])) or None


def asker_repos(
    questions: Iterable[Any], records: Iterable[Any], roots: Mapping[str, str] | None = None
) -> dict[str, str]:
    """`{mail id: repo}` for the person inbox's items (§4.5 screen 6 *A bare ref elsewhere*, TD-1509; *A mail item's
    bare ref is its sender's repo's*, TD-1467): each item's repo by `mail_repo`'s order — its stamped `repo`, else its
    orphan stamp's, else its asker's record's (`from_` looked up in `records`: live, ended or kept; `Session`s or
    their view dicts) — a checkout's root named as the reading names it (`roots`, `{name: root}`, the repo whose
    root it is) or else by its last component. An item with none is left out, and its bare refs stay bare."""
    named: dict[str, str] = {}

    def name_of(root: Any) -> str:
        key = str(root or "")
        if key and key not in named:
            hit = next((n for n, r in (roots or {}).items() if _same_dir(key, r)), None)
            named[key] = hit or _repo_name(key)
        return named.get(key, "")

    by_id: dict[str, Any] = {}
    for r in records:
        rid, root = _get(r, "id"), _get(r, "repo")
        if rid and root:
            by_id.setdefault(str(rid), root)
    out: dict[str, str] = {}
    for q in questions:
        mid = _get(q, "id")
        if mid and (repo := mail_repo(q, by_id, name_of)):
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
    `<repo>#TD-n` to itself, `<origin path>#TD-n` to it where `origins` give the repo one (TD-1371), and the
    bare `TD-n` to it only where exactly one open member across the repos carries it — two repos' `TD-n` link
    to neither."""
    out: dict[str, str] = {}
    bare: dict[str, set[str]] = {}
    for q in qids:
        out[q] = q
        name, _, tid = q.partition("#")
        if path := (origins or {}).get(name):
            out.setdefault(f"{path}#{tid}", q)
        bare.setdefault(tid, set()).add(q)
    for tid, qs in bare.items():
        if len(qs) == 1:
            out[tid] = next(iter(qs))
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
    and no longer than `ANSWERED_DONE_FOR` past the outcome's `at`; never on any other outcome."""
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
    if best is None:
        return None
    closed, q = best
    outcome = _get(q, "outcome")
    asker = naming.split_address(str(_get(q, "from_") or ""))[0]
    if not outcome:
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


def open_decided_covers(
    boards: Mapping[str, Iterable[Mapping[str, Any]]],
    entries: Mapping[str, Mapping[str, Any]],
    refs_open: Mapping[str, str],
    *,
    person_only: bool = False,
) -> set[str]:
    """Every entry an open decided board line covers (`covers`), over every board the home reads (`boards` by repo
    name, each `{items}`): such an entry's line is its row now, *Waiting on them* while it waits on its session
    (§4.5 screen 6, TD-565, TD-1364). A decided `fyi` line is no work order and covers nothing; any other decided
    line is a work order whoever wrote it, as the home's own press writes `(by <its person>)` — save with
    `person_only`, the rows' read, which skips a line `Decided:` by someone else as `board_hold` does, so the
    Inbox hides no row the Queue still asks about."""
    out: set[str] = set()
    for repo, bl in boards.items():
        for b in bl or ():
            for it in (b.get("items") or ()) if isinstance(b, Mapping) else ():
                if not isinstance(it, Mapping) or not it.get("decided") or it.get("kind") == "fyi":
                    continue
                by = str(it.get("decided_by") or "").strip().lower()
                if person_only and by and by != PERSON:
                    continue
                out |= covers(it.get("refs") or (), it.get("parts") or (), repo, entries, refs_open)
    return out


def _board_lines(boards: Mapping[str, Iterable[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Every `decide` line of the boards, open (`items`) and closed (`carried`), as one shape: `{repo, key, open,
    decided, said, by, refs, parts, closed, to, at, session}` — `decided` None for an open line not yet answered,
    `said` its `Decided:` words."""
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
                            "said": str(d.get("text") or "") if d else "",
                            "refs": [str(r) for r in it.get("refs") or () if refs(r)],
                            "parts": [str(p) for p in it.get("parts") or ()], "closed": None, "to": [],
                            "at": int(it.get("line") or 0), "session": str(it.get("session") or "")})  # fmt: skip
            for c in b.get("carried") or ():
                if not isinstance(c, Mapping) or not isinstance(c.get("decided"), Mapping):
                    continue
                out.append({"repo": repo, "key": str(c.get("key") or ""), "open": False,
                            "decided": str(c["decided"].get("date") or ""), "by": c.get("decided_by"),
                            "said": str(c["decided"].get("text") or ""),
                            "refs": [str(r) for r in c.get("refs") or ()],
                            "parts": [str(p) for p in c.get("parts") or ()],
                            "closed": dict(c.get("closed") or {}), "to": [str(t) for t in c.get("to") or ()],
                            "at": int(c.get("at") or 0), "session": ""})  # fmt: skip
    return out


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
    (an open line before a closed one, then the later `Closed:`, then the smaller `at`) alone decides: an open
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
    picked: tuple[tuple[Any, ...], dict[str, Any], list[str]] | None = None
    for ln in _board_lines(boards):
        named = [q for r in ln["refs"] + ln["parts"] if (q := _line_qid(r, ln["repo"], refs_open))]
        if me not in named and (parent is None or parent not in named):
            continue
        if ln["decided"] is None:
            return None  # an open undecided line covering the member asks again
        if ln["by"] and str(ln["by"]).strip().lower() != PERSON:
            continue  # a line decided by someone else is not the person's answer
        closed = (ln["closed"] or {}).get("date") or ""
        k = (ln["decided"], ln["open"], closed, -ln["at"])
        if picked is None or k > picked[0]:
            picked = (k, ln, [me, *named])
    if picked is None:
        return None
    _, ln, covered = picked
    line = {"key": ln["key"], "open": ln["open"], "to": list(ln["to"]), "said": ln["said"]}
    held = next((claims[q] for q in covered if q in claims), None)  # a covered member's holder, the member first
    if ln["open"]:
        asker = claims.get(ln["key"]) or held or live.get(ln["session"]) or "a pick"
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
    open_: dict[str, Mapping[str, Any]] = {}
    for name, r in rs.by_name.items():
        for e in r["ledger"]["entries"]:
            if isinstance(e, Mapping) and e.get("id"):
                open_.setdefault(qid(name, e["id"]), e)
    boards = {n: list((r.get("boards") or {}).get("boards") or ()) for n, r in rs.by_name.items()}
    pressing = _pressing(open_, boards, open_refs(open_, rs.origins))

    def mark(row: Any) -> Any:
        if not isinstance(row, Mapping) or row.get("archived") or row.get("with_you"):
            return row
        if (applying := pressing.get(str(row.get("qid") or ""))) is None:
            return row
        return {**row, "state": applying_words(applying), "needs": None, "answered": None, "applying": applying}

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
    each entry links (`design_prs`, TD-1531)."""
    rs = _Repos(repos)
    records = list(records)
    # every record's state by id, ended ones too: an answered question's asker exited or closed is gone (TD-1316)
    states = {str(r.id): str(getattr(r, "state", "") or "") for r in records}
    names = {str(r.id): str(getattr(r, "name", "") or r.id) for r in records}
    questions = list(questions)
    askers = asker_repos(questions, records, rs.roots)  # a question's bare `TD-n` is its asker's repo's (TD-1509)
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
    claims: dict[str, str] = {}
    live: dict[str, str] = {}
    for rec in sorted(recs, key=lambda r: str(r.id)):
        live.setdefault(str(rec.id), str(rec.id))
        live.setdefault(str(getattr(rec, "name", "") or rec.id), str(rec.id))
        if not getattr(rec, "unattended", False):
            continue
        home = rs.of_record(rec)
        for p in rec.progress:
            at = _aware(p.at)
            if p.status != "claimed" or at is None or now - at >= LEASE_TTL:
                continue
            if p.ref.startswith(workorders.PREFIX):
                claims.setdefault(p.ref, str(rec.id))
            elif home and re.fullmatch(r"TD-\d+", p.ref):
                claims.setdefault(qid(home, p.ref), str(rec.id))

    pressing = _pressing(open_, boards, linked)
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
            st, needs, mine = _state(e, held.get(q, []), prs.get(q), recs, set(waiting), now)
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
            if answered and answered.get("until"):
                st = f"waits until {answered['until']}"  # the person's own *not yet*, until the re-ask (TD-1368)
            elif answered:
                answered["name"] = names.get(answered["asker"], answered["asker"])
                st = f"answered — waiting on {answered['name']}"
            applying = pressing.get(q) if not mine else None  # *with you* first, then the mark (TD-1508)
            if applying:
                st, needs, answered = applying_words(applying), None, None  # the mark is no need of the person
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
                "answered": answered,
                "applying": applying,
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
            "with_you": None,
            "answered": None,
            "applying": None,
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
    # `Owner: paul` holds nothing (TD-1375): the gate is the need, and the Owner says it is the person's to do
    need = (
        ("owner" if str(e.get("owner") or "").lower() == PERSON else "decision")
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
    entry that waits on the person (`decision (paul)`: an Owner alone holds nothing, TD-1375), else its first
    `decision (paul)` entry by key, else the top entry — by key alone, never by what is claimed, so two presses
    choose the same entry."""
    by_key = sorted(members, key=lambda q: _key_sort(keyed[q], q))
    owned = [q for q in by_key if str(open_[q].get("owner") or "").lower() == PERSON and _own(open_[q])]
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
    session holds (`with_you`, TD-1281), or whose question the person answered (`answered`, TD-1316), which
    keeps its `needs`, is no need."""
    if any(r["needs"] and not r.get("with_you") and not r.get("answered") for r in rows):
        return "needs you"
    if any(r["state"] == "stalled" for r in rows):
        return "stalled"

    def waits(e: Mapping[str, Any]) -> bool:
        if e.get("waiting") or e.get("settling"):
            return True
        if e.get("kind") == "live-check" and e.get("live") != "yes":
            return True
        # blocked only by open ids (a gate is the `waiting` mark's, TD-1395)
        ids = [b for b in e.get("blocked_by") or [] if not ledger_mod.is_gate(b)]
        # an open part counts as an open id its parent is blocked by (TD-1130)
        return bool(ids or e.get("parts_open")) and all(not b.startswith("decision (") for b in ids)

    if any(e.get("unreachable") for e in ents) or all(e.get("for_page") in NO_LANE for e in ents):
        return "blocked"
    if all(waits(e) for e in ents):
        return "waiting"
    return "ready"


def _own(e: Mapping[str, Any]) -> bool:
    """The person's own member (§4.4 *Waiting*): `Blocked by: decision (paul)` — an `Owner: paul` alone holds
    nothing (TD-1375)."""
    return ledger_mod.decided_by(dict(e), PERSON)


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
    own waits — an `until` or `event` gate in force, a live check whose build is not live, settling, blocked by open
    ids or open parts once the person's own are set aside, blocked past the org's reach, or no lane takes it — and at
    least one is not the person's own. The leaf is a member that waits for a reason of its own, the first
    that applies: the top entry with a gate, the earliest `until` date, an event, settling, a
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
        why = str(w.get("why") or "")  # the Event line's words (TD-1395)
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
