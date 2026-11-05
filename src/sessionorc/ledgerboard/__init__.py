# ledgerboard v2.5 sha256:be6215e12d99ab26049a7f5bc0b64722ca88b3d34e0526dbdc3419398dbdb74a
# SYNCED FILE — canonical copy: ShiftLead/ledgerboard ledgerboard/__init__.py (vendored by agent-cadence as files/scripts/ledgerboard/__init__.py)
# Edit it there and release; an edit made in a consumer's copy is overwritten by the next vendor or sync.
"""The ledger and board formats, defined once (SPEC.md).

A **ledger** (``docs/technical_debt.md``) is a file of ``## TD-NNN: title`` entries, each with a
header block of ``**Name:** value`` fields, a summary table, and an archive beside it — or, from
v2, a directory of one ``TD-NNN.md`` per entry (``docs/ledger/``) that ``load()`` reads as the same text. A **board**
(``docs/user_attention.md``) is a file of ``- [ ] [kind] YYYY-MM-DD (session …) — text`` items with
trailing ``Due:``/``Answers:``/``Decided:`` fields, reply tails and a detail block.

Everything here is a pure function over text: no git, no network, no file system, no roster.
What a caller needs from outside the text is passed in — the cross-repo resolver of
``pickable()``, today's date. Two consumers vendor this package (agent-cadence's scripts, ShiftLead);
neither keeps a second parser of either format.

Sections: the ledger (entries, ``Fields:``, ``Blocked by``, ``Part of``, derived pickable, ``check``); the rank
(cards, keys, the rank file, the pick order); the board
(items, the item record, keys and refs); the ledger as a directory (``load``, ``split``); edits (``edit_line``, composing an item, the commit
subject of a write and its parser); line predicates for diff walkers; ledger entries and their writers
(``canonical``, ``entry_text``, ``edit_entry``, v2.2; the Log, v2.4); the format version.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("ledgerboard")

# ---------------------------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------------------------

HEADING_RE = re.compile(r"^## (TD-(\d+)):\s*(.*)$", re.MULTILINE)
SECTION_RE = re.compile(r"^## ", re.MULTILINE)
ROW_RE = re.compile(r"^\|\s*(TD-(\d+))\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", re.MULTILINE)
FIELD_RE = re.compile(r"^\*\*([A-Za-z][^*:\n]*?):\*\*[ \t]*(.*?)[ \t]*$")  # one line, one field
FIELDS_DECL_RE = re.compile(r"^Fields:[ \t]*(.*?)[ \t]*$", re.MULTILINE)  # the preamble's declaration
CADENCE_FIELDS = ("priority", "type", "added", "status", "blocked by", "location", "part of",
                  "escaped from", "id take")  # the spec's own fields
PRIORITY_RE = re.compile(r"^\*\*Priority:\*\*\s*(\w+)", re.MULTILINE)
BLOCKED_RE = re.compile(r"^\*\*Blocked by:\*\*[ \t]*(.*?)[ \t]*$", re.MULTILINE)  # one line only
PART_OF_RE = re.compile(r"^\*\*Part of:\*\*[ \t]*(.*?)[ \t]*$", re.MULTILINE)  # one parent, same ledger (v2.1)
TYPE_RE = re.compile(r"^\*\*Type:\*\*[ \t]*(.*?)[ \t]*$", re.MULTILINE)
TYPES = ("debt", "feature")  # pick order within a Priority; the first is the default
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)  # the seed template's example entry lives in one
ID_ITEM_RE = re.compile(r"^TD-(\d+)$")
# A repo in an id (v2.4): a name, or `/`-separated components (owner/name, or deeper for a nested
# group), each ASCII [A-Za-z0-9_.-]+, none `.` or `..`, none starting with `-`: no URL, no host, no traversal.
REPO_PART = r"(?!\.\.?(?![A-Za-z0-9_.-]))(?!-)[A-Za-z0-9_.-]+"
REPO = rf"{REPO_PART}(?:/{REPO_PART})*"
REPO_RE = re.compile(REPO)
XREPO_ITEM_RE = re.compile(rf"^({REPO})#(TD-\d+)$")
ASK_RE = re.compile(r"^\*\*Ask:\*\*", re.MULTILINE)  # the body section a decision gate pairs with (v2.4)
WORD_RE = re.compile(r"[^\s,;]+")
PRIORITIES = ("high", "medium", "low")
EDIT_ERRORS = ("pickable-disagrees", "undeclared-field", "cycle", "legacy-part", "priority", "ask-missing",
               "gate-repeated", "blocker-superseded", "blocker-dropped",
               "blocker-unknown-status")  # information on a standing ledger, an error in a new edit

# A resolver answers one ``<repo>#TD-NNN`` item: ``(state, why)`` or a mapping carrying at least
# ``state`` and ``why`` (any other keys ride along into the entry's ``cross_repo``). ``state`` is
# ``open | archived | unresolved``; ``why`` says why it is unresolved, else "". From v2.4 an archived
# entry's mapping may carry ``status`` (its Status, read by its first word: Superseded, Dropped, a word
# this reader does not know (outside STATUS_WORDS: the block stays), else closed and done) and
# ``successor`` (a Superseded entry's id after ``by``, bare when in its own repo).
Resolve = Callable[[str], Any]


def _num(tid: str) -> int:
    return int(tid.split("-", 1)[1])


def heading_nums(text: str | None) -> set[int]:
    """The entry numbers with a ``## TD-NNN:`` heading in a ledger or archive (comments dropped)."""
    return {int(m.group(2)) for m in HEADING_RE.finditer(COMMENT_RE.sub("", text or ""))}


def field_key(name: str) -> str:
    """``Blocked by`` / ``blocked-by`` / ``BLOCKED_BY`` all read as ``blocked by``."""
    return re.sub(r"[-_\s]+", " ", name.strip()).lower()


def first_word(value: str | None) -> str:
    """A field's value: its first word, lower-cased; the rest of the line is a free comment."""
    m = WORD_RE.search(value or "")
    return m.group(0).strip("*_`").rstrip(".:").lower() if m else ""  # `**Decided` reads as decided


def _status_word(status: str | None) -> str:
    """An archived Status's word as written, for a flag (v2.4, TD-039): ``first_word()``'s strips without its
    lower-casing, or the first run itself when they leave nothing (``** Xyzzy`` names ``**``); ``""`` only
    for a Status with no first run, which reads as closed and done."""
    m = WORD_RE.search(status or "")
    if not m:
        return ""
    return m.group(0).strip("*_`").rstrip(".:") or m.group(0)


def header_block(body: str) -> dict[str, str]:
    """Every ``**Name:** value`` line of the header block: after the heading's blank lines, up to the next blank line."""
    fields: dict[str, str] = {}
    started = False
    for line in body.split("\n"):
        if not line.strip():
            if started:
                break
            continue
        started = True
        m = FIELD_RE.match(line)
        if m:
            fields.setdefault(field_key(m.group(1)), m.group(2))  # a repeated field: the first wins
    return fields


def declared(text: str) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    """The preamble's ``Fields:`` vocabularies ({key: values}) and flags for what it cannot read."""
    text = COMMENT_RE.sub("", text)
    first = HEADING_RE.search(text)
    pre = text[: first.start() if first else len(text)]
    vocab: dict[str, tuple[str, ...]] = {}
    flags = []
    for m in FIELDS_DECL_RE.finditer(pre):
        line = m.group(1).replace("`", "").split(" — ", 1)[0]
        for part in (p.strip() for p in line.split(";")):
            if not part:
                continue
            name, eq, vals = part.partition("=")
            key = field_key(name)
            values = tuple(v for v in (first_word(x) for x in vals.split("|")) if v)
            if not eq or not key or not values:
                flags.append(f"⚠ Fields: cannot read {part!r} — write Name = value | value")
            elif key in CADENCE_FIELDS:
                flags.append(f"⚠ Fields: {key!r} is the cadence's own field (cadence.md §2.12) — "
                             "its vocabulary is not redeclared; ignored")
            else:
                vocab[key] = values
    return vocab, flags


def declarations(text: str) -> list[str]:
    """The raw ``Fields:`` lines of the preamble, in order — what ``check`` compares across an edit."""
    text = COMMENT_RE.sub("", text)
    first = HEADING_RE.search(text)
    return FIELDS_DECL_RE.findall(text[: first.start() if first else len(text)])


def entries(text: str) -> list[dict]:
    """The ledger's entry bodies, in file order: id, title, priority, blocked (raw or None), fields.

    HTML comments are dropped first: the seed ledger's entry template is a commented-out
    `## TD-001: …` that is not an entry. Priority, Type, Blocked by and Part of come from the
    header block; one written further down the body is still read (the safe direction) and flagged."""
    text = COMMENT_RE.sub("", text)
    out = []
    for m in HEADING_RE.finditer(text):
        nxt = SECTION_RE.search(text, m.end())  # a body ends at the next `## ` heading of any kind
        body = text[m.end(): nxt.start() if nxt else len(text)]
        fields = header_block(body)
        below = []
        for key, rx in (("priority", PRIORITY_RE), ("type", TYPE_RE), ("blocked by", BLOCKED_RE),
                        ("part of", PART_OF_RE)):
            if key not in fields:
                bm = rx.search(body)
                if bm:
                    fields[key] = bm.group(1)
                    below.append(key)
        prio = first_word(fields.get("priority")) or None
        type_raw = fields.get("type") or None
        blocked = fields.get("blocked by") or None  # an empty field (the template's line left blank) blocks nothing
        out.append({"id": m.group(1), "title": m.group(3).strip(),
                    "priority": prio.capitalize() if prio else None,
                    "type_raw": (type_raw.split() or [None])[0] if type_raw else None,  # a value of only \r or NBSP is no Type
                    "blocked_raw": blocked, "part_of_raw": fields.get("part of") or None,
                    "fields": fields, "below": below})
    return out


_entries = entries  # for a function whose parameter is named entries (decide_lift's, as SPEC names it)


def rows(text: str) -> list[dict]:
    """The summary table's rows, in order: {id, title, priority} (comments dropped)."""
    return [{"id": m.group(1), "title": m.group(3), "priority": m.group(4)}
            for m in ROW_RE.finditer(COMMENT_RE.sub("", text))]


def parse_blocked(raw: str) -> tuple[list[str], list[str], list[str]]:
    """(entry ids — ``TD-NNN`` or ``<repo>#TD-NNN`` — decision holders, every other item) of one
    Blocked by value: ``parse_gates()`` seen as three lists. The third holds what is neither an id nor
    a decision: an ``until`` or ``event`` gate (v2.4) as the writers write it, and a retired or
    unreadable item as written —
    so a caller that reads the three as before keeps every block. A retired ``decision (designer)``
    and the old form's holder are decision holders."""
    g = parse_gates(raw)
    who = g["decisions"] + [r["holder"] for r in g["retired"] if r["kind"] != "gate"]
    rest = [f"until {d}" for d in g["until"]] + [f"event ({n})" for n in g["events"]] + \
        [r["item"] for r in g["retired"] if r["kind"] == "gate"] + g["bad"]
    return g["ids"], who, rest


# The gates of `Blocked by` (v2.4, SPEC *The ledger*): after the ids, `decision (<person>)`,
# `until YYYY-MM-DD` and `event (<name>)`. The words are read in any case and written lower.
GATE_DECISION_RE = re.compile(r"^decision[ \t]*\((?P<who>[^()]*)\)", re.IGNORECASE)
GATE_UNTIL_RE = re.compile(r"^until[ \t]+(?P<date>\S+)$", re.IGNORECASE)
GATE_EVENT_RE = re.compile(r"^event[ \t]*\((?P<name>[^()]*)\)$", re.IGNORECASE)
EVENT_NAME_RE = re.compile(r"[a-z0-9-]+")
GATE_ITEM_SEP_RE = re.compile(r"[ \t]*,[ \t]*")
RETIRED_ROLES = ("designer",)  # a role in `decision (…)`, reserved by name (SPEC *Retired words*)
# The retired words (SPEC *Retired words*): each with what replaces it. The list grows only.
RETIRED_FIELDS = {"waits": "a gate in Blocked by — until YYYY-MM-DD or event (<name>)",
                  "taken by": "Id take, the counter take's nonce",
                  "resolved": "the **Resolved:** body line of an archived entry"}
RETIRED_GATES = {"hold": "decision (<person>), with an **Ask:**"}
RETIRED_STATUS = {"designed": "Open, with Kind build", "built": "Open, with Kind live-check", "partly": "Open",
                  "live": "Open", "in": "Open"}  # an open entry's; the archived ones are migrate's to map
OLD_FORM_REPLACES = "decision (<person>), with the text in an **Ask:** section"


def parse_gates(raw: str | None) -> dict:
    """One Blocked by value read (v2.4, SPEC *The ledger*): ``{ids, decisions, until, events, retired,
    old_form, bad}``, each in the order written.

    - ``ids``: ``TD-n`` and ``<repo>#TD-n`` items; ``decisions``: each ``decision (<person>)``'s person;
      ``until``: each ``until YYYY-MM-DD``'s date (a real day); ``events``: each ``event (<name>)``'s name,
      ``[a-z0-9-]+``. The words ``decision``, ``until`` and ``event`` are read in any case.
    - ``old_form``: ``(holder, text)`` for the old form ``decision (<who>) <text>``, read only as the last
      item: a decision followed by anything but a comma or the end runs to the end of the line, which is
      its text (so it is last by construction). Else None.
    - ``retired``: ``[{item, replace, kind, holder}]``, each retired item with what replaces it: ``kind``
      ``old-form`` (and its ``holder``), ``role`` (a role in ``decision (…)``, its ``holder``) or ``gate``
      (``hold``; ``holder`` None).
    - ``bad``: every other item, as written. An empty item between commas is skipped.
    A retired or unreadable item keeps the block; ``pickable()`` reads the rest."""
    out: dict = {"ids": [], "decisions": [], "until": [], "events": [], "retired": [], "old_form": None, "bad": []}
    rest = (raw or "").strip(" \t\r")  # a CRLF file's line ending is no part of the value
    while rest:
        m = GATE_ITEM_SEP_RE.search(rest)
        item, after = (rest[: m.start()], rest[m.end():]) if m else (rest, "")
        d = GATE_DECISION_RE.match(item)
        if d and item[d.end():].strip(" \t"):  # the old form: its text runs to the end of the line
            who, text = d.group("who").strip(" \t"), rest[d.end():].strip(" \t")
            out["old_form"] = (who, text)
            out["retired"].append({"item": rest, "replace": OLD_FORM_REPLACES, "kind": "old-form", "holder": who})
            break
        rest = after
        if not item:
            continue
        u, e = GATE_UNTIL_RE.match(item), GATE_EVENT_RE.match(item)
        if ID_ITEM_RE.match(item) or XREPO_ITEM_RE.match(item):
            out["ids"].append(item)  # a `<repo>#TD-NNN` item is resolved by pickable()'s resolver, not here
        elif d and d.group("who").lower() in RETIRED_ROLES:
            out["retired"].append({"item": item, "kind": "role", "holder": d.group("who"),
                                   "replace": f"decision (<person>): {d.group('who')} is a role, reserved by name"})
        elif d and is_person(d.group("who")):
            out["decisions"].append(d.group("who"))
        elif u and _real_day(u.group("date")):
            out["until"].append(u.group("date"))
        elif e and EVENT_NAME_RE.fullmatch(e.group("name")):
            out["events"].append(e.group("name"))
        elif item.lower() in RETIRED_GATES:
            out["retired"].append({"item": item, "replace": RETIRED_GATES[item.lower()], "kind": "gate", "holder": None})
        else:
            out["bad"].append(item)
    return out


def _real_day(text: str) -> bool:
    try:
        return bool(ISO_DAY_RE.fullmatch(text)) and date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def gate_items(g: Mapping) -> list[str]:
    """The gates of a ``parse_gates()`` result, each as the writers write it, in the canonical order:
    decisions, then ``until``, then events (each group in the order written)."""
    return ([f"decision ({w})" for w in g["decisions"]] + [f"until {d}" for d in g["until"]]
            + [f"event ({n})" for n in g["events"]])


def gate_repeats(g: Mapping) -> list[str]:
    """What a ``parse_gates()`` result names more than the grammar allows: a second decision for one
    person (compared case-insensitively), a second ``until``, an event name twice."""
    out: list[str] = []
    seen: set[str] = set()
    for key, shown in ([(f"decision {w.lower()}", f"decision ({w})") for w in g["decisions"]]
                       + [(f"event {n}", f"event ({n})") for n in g["events"]]):
        if key in seen and shown not in out:
            out.append(shown)
        seen.add(key)
    if len(g["until"]) > 1:
        out.append(f"until (written {len(g['until'])} times)")
    return out


def _written_blocked(value: str, current: str | None = None) -> str:
    """A Blocked by value as a writer writes it (v2.4, SPEC *The ledger*): its ids in the order written,
    then its gates in the canonical order (``gate_items()``); a value holding an item the grammar does
    not read is written as given, for ``check()`` to flag. Raises Refused for the old form, which is read
    but never written, and for a gate added to an entry whose ``current`` value still holds the old form,
    whose text would swallow it."""
    g = parse_gates(value)
    if g["old_form"]:
        raise Refused(f"Blocked by in the old form (decision ({g['old_form'][0]}) with text after it) is read "
                      "but never written — write decision (<person>) and put the text in an **Ask:** section")
    was = parse_gates(current)
    if was["old_form"]:
        had = {_gate_key(x) for x in gate_items(was)} | {_gate_key(f"decision ({was['old_form'][0]})")}
        added = [x for x in gate_items(g) if _gate_key(x) not in had]
        if added:
            raise Refused(f"the entry's Blocked by is in the old form, whose text would swallow {added[0]} — "
                          "migrate it first: set decision (<person>) alone, with its text in an **Ask:** section")
    if g["bad"] or g["retired"]:
        return value
    return ", ".join(g["ids"] + gate_items(g))


def ref_key(ref: str) -> str:
    """A ref as compared (v2.4): ``<repo>#TD-n`` with its repo lowercased, any other ref as written.
    Only the comparison folds case; the text, and an item's key, keep the repo as written."""
    repo, sep, rest = ref.rpartition("#")
    return f"{repo.lower()}#{rest}" if sep and rest.startswith("TD-") and REPO_RE.fullmatch(repo) else ref


ORIGIN_SCP_RE = re.compile(r"^(?:[^@/:\s]+@)?(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*):(?P<path>[^/\s][^\s]*)$")
ORIGIN_URL_RE = re.compile(r"^(?:ssh|https)://(?:[^@/\s]*@)?(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*)(?::\d+)?"
                           r"/(?P<path>[^\s]*)$", re.IGNORECASE)


def origin_key(url: str) -> str | None:
    """A repo's pick key from its origin URL (v2.4): ``<host>/<path>``, lowercased, every path
    component kept, a trailing ``/`` and ``.git`` stripped, userinfo and port dropped (a key never
    holds a credential). It reads ssh (``git@host:path``, ``ssh://user@host:port/path``) and https
    (``https://user:token@host:port/path``). None for anything else — ``file://``, a plain local
    path, another scheme — and for a path that is not the ``<repo>`` grammar: such a repo has no origin."""
    url = str(url or "").strip()
    m = ORIGIN_URL_RE.match(url) if "://" in url else ORIGIN_SCP_RE.match(url)
    if not m:
        return None
    path = m.group("path").lower().rstrip("/")
    path = path[:-4] if path.endswith(".git") else path
    path = path.rstrip("/")
    if not path or not re.fullmatch(REPO, path):
        return None
    return f"{m.group('host').lower()}/{path}"


def origin_path(url: str) -> str | None:
    """The repo an id names from its origin (v2.4): ``origin_key``'s path part (``owner/name``, or
    deeper for a nested group), lowercased; None when the origin is not readable."""
    key = origin_key(url)
    return key.split("/", 1)[1] if key else None


def parse_part_of(raw: str | None) -> tuple[str | None, str | None]:
    """(the parent's id, what cannot be read) of one Part of value (v2.1). The parent is the
    value's first item, a ``TD-NNN`` in the same ledger; the rest of the line is a free comment,
    except a second id after a comma, which names a second parent. Another repo's entry
    (``<repo>#TD-NNN``) is never a parent: a parent's pickable needs every entry naming it."""
    first, _, rest = (raw or "").strip().partition(",")
    item = first.split()[0].rstrip(".;:") if first.split() else ""
    if not item:
        return None, None
    if XREPO_ITEM_RE.match(item):
        return None, f"names {item}, another repo's entry — a parent is in the same ledger"
    if not ID_ITEM_RE.match(item):
        return None, f"cannot read {item!r} — write TD-NNN"
    second = rest.strip().split()[0].rstrip(".;:") if rest.strip() else ""
    if ID_ITEM_RE.match(second) or XREPO_ITEM_RE.match(second):
        return None, f"names a second parent ({second}) — an entry is part of one"
    return item, None


def _parents(live: list[dict]) -> tuple[dict[str, str], dict[str, tuple[str | None, str | None]]]:
    """({part: its open parent's id as the ledger spells it}, {id: parse_part_of() of its line}) of the
    live entries; a parent matches by number, as a blocker does (``TD-7`` is ``TD-007``)."""
    num: dict[int, str] = {}
    for e in live:
        num.setdefault(_num(e["id"]), e["id"])
    parent_of, part_of = {}, {}
    for e in live:
        if e.get("part_of_raw"):
            part_of[e["id"]] = parse_part_of(e["part_of_raw"])
            par = part_of[e["id"]][0]
            if par and _num(par) in num:
                parent_of.setdefault(e["id"], num[_num(par)])
    return parent_of, part_of


def _descendants(tid: str, parts: Mapping[str, list[str]]) -> list[str]:
    """Every open part of ``tid``, and their parts, breadth first; a cycle ends the walk."""
    out, seen, todo = [], {tid}, list(parts.get(tid, ()))
    while todo:
        t = todo.pop(0)
        if t not in seen:
            seen.add(t)
            out.append(t)
            todo.extend(parts.get(t, ()))
    return out


def _waits_on(live: list[dict], parent_of: dict[str, str]) -> dict[str, set[str]]:
    """The live entries' waits-on edges (v2.1): X → Y when X is Blocked by Y, P → C when C is
    Part of P (a parent waits on its parts); local ids only, matched by number."""
    num = {}
    for e in live:
        num.setdefault(_num(e["id"]), e["id"])
    out: dict[str, set[str]] = {e["id"]: set() for e in live}
    for e in live:
        for b in parse_blocked(e["blocked_raw"] or "")[0]:
            if "#" not in b and _num(b) in num:
                out[e["id"]].add(num[_num(b)])
    for c, p in parent_of.items():
        out.setdefault(p, set()).add(c)
    return out


def _on_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """The strongly connected groups of ``edges`` that hold a cycle (two or more members, or one
    that waits on itself), each in its members' order of ``edges``; Tarjan's, iterative."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    found = []
    for root in edges:
        if root in index:
            continue
        work = [(root, iter(sorted(edges[root], key=_num)))]
        index[root] = low[root] = len(index)
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(edges.get(w, ()), key=_num))))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                group = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    group.append(w)
                    if w == v:
                        break
                if len(group) > 1 or v in edges.get(v, ()):
                    pos = {t: i for i, t in enumerate(edges)}
                    found.append(sorted(group, key=pos.__getitem__))
    return found


def _resolved(item: str, resolve: Resolve | None) -> dict:
    """One cross-repo item as a record: the resolver's answer, or unresolved when there is none."""
    if resolve is None:
        return {"item": item, "state": "unresolved", "why": "no resolver for another repo's entries"}
    got = resolve(item)
    if isinstance(got, Mapping):
        out = {"item": item, **got}
    elif isinstance(got, (tuple, list)) and len(got) == 2:
        out = {"item": item, "state": got[0], "why": got[1]}
    else:
        return {"item": item, "state": "unresolved", "why": f"the resolver returned {got!r}"}
    out["why"] = out.get("why") or ""
    if out.get("state") not in ("open", "archived", "unresolved"):
        out.update(state="unresolved", why=out["why"] or f"the resolver said {out.get('state')!r}")
    return out


def _archived_status(archive: str) -> dict[int, dict]:
    """Each archived entry's Status read (v2.4, SPEC *Superseded and dropped*), by number: ``{id, word,
    successor, status_word}`` — ``word`` ``superseded`` (``successor`` the id after its ``by``, or None),
    ``dropped``, ``unknown-status`` for a first word outside ``STATUS_WORDS`` (the block stays, TD-039), or
    ``resolved`` for any other Status (``Resolved``, ``Done``, ``Built``, ``Open``, no first run at all):
    closed and done. ``status_word`` is ``_status_word()`` of the Status, which a flag names."""
    out: dict[int, dict] = {}
    for e in entries(archive):
        status = e["fields"].get("status") or ""
        word, written = first_word(status), _status_word(status)
        by = re.search(rf"\bby[ \t]+({LOG_ID})(?![\w#/-]|\.\w)", status, re.IGNORECASE) if word == "superseded" else None
        read = ("resolved" if written == "" or word in STATUS_WORDS and word not in ("superseded", "dropped")
                else word if word in ("superseded", "dropped") else "unknown-status")
        out.setdefault(_num(e["id"]), {"id": e["id"], "word": read, "successor": by.group(1) if by else None,
                                       "status_word": written})
    return out


def _chain(start: str, live_nums: set[int], gone: Mapping[int, dict],
           resolve: Resolve | None) -> tuple[list[str], str, str]:
    """Where a blocker's requirement lives now (v2.4): ``start`` followed through each Superseded entry to its
    successor. ``(path, state, word)``: ``path`` the ids walked, ``start`` first and the end last; ``state``
    the end's — ``open``, ``resolved``, ``dropped``, ``unknown-status`` (archived with a Status word outside
    ``STATUS_WORDS``, locally or through the resolver: TD-039), ``unknown`` (no such entry), ``unresolved``
    (another repo's the resolver cannot answer, or a Superseded with no successor) or ``cycle``; ``word`` the
    end's Status word as written (``_status_word()``) when it is ``unknown-status``, else ``""``. A successor
    written bare in another repo's entry is that repo's."""
    path, seen = [], set()
    cur = start
    while True:
        key = ref_key(cur) if "#" in cur else f"#{_num(cur)}"
        if key in seen:
            return path + [cur], "cycle", ""
        seen.add(key)
        path.append(cur)
        if "#" in cur:
            x = _resolved(cur, resolve)
            if x["state"] != "archived":
                return path, x["state"], ""
            if x.get("status") is not None and not isinstance(x["status"], str):
                return path, "unresolved", ""  # a Status the resolver cannot have read: hold
            status, nxt = x.get("status") or "", x.get("successor")
            word, written = first_word(status), _status_word(status)
            if written == "":
                return path, "resolved", ""  # no first run (or no status given): closed and done, as before
            if word not in STATUS_WORDS:
                return path, "unknown-status", written
            if word == "dropped":
                return path, "dropped", ""
            if word != "superseded":
                return path, "resolved", ""
            if not isinstance(nxt, str) or not (ID_ITEM_RE.match(nxt) or XREPO_ITEM_RE.match(nxt)):
                return path, "unresolved", ""
            cur = nxt if "#" in nxt else f"{cur.rpartition('#')[0]}#{nxt}"
            continue
        n = _num(cur)
        if n in live_nums:
            return path, "open", ""
        st = gone.get(n)
        if st is None:
            return path, "unknown", ""
        if st["word"] != "superseded":
            return path, st["word"], st.get("status_word", "") if st["word"] == "unknown-status" else ""
        if st["successor"] is None:
            return path, "unresolved", ""
        cur = st["successor"]


class _Flags(list):
    """The flags as the sentences every mode prints (a list of str), with a record beside each
    for ``check``: level (error for ⚠, info for ℹ), entry id, field, kind."""

    def __init__(self) -> None:
        super().__init__()
        self.recs: list[dict] = []

    def add(self, text: str, tid: str | None, field: str, kind: str) -> None:
        self.append(text)
        self.recs.append({"level": "error" if text.startswith("⚠") else "info", "id": tid,
                          "field": field, "kind": kind, "text": text})


def pickable(ledger: str, archive: str, resolve: Resolve | None = None, undeclared: bool = False,
             rank_text: str | None = None, repo: str = "", *, today: date | str) -> dict:
    """Every live entry in pick order, with its derived pickable, open blockers and raw fields; plus flags.

    **Pickable is derived, never written:** an entry is pickable when it has no Blocked by field,
    or every entry it names is archived and it has no ``decision``, no ``event`` and no ``until`` after
    ``today`` (v2.4) — and no open entry is Part of it (v2.1; its ``parts_open``, kept apart from
    ``blocked_by``). ``today`` is required: the UTC date, a date or ``YYYY-MM-DD`` (an aware datetime
    is taken as its UTC date). ``resolve`` answers a ``<repo>#TD-NNN`` item (see ``Resolve``); without
    one, such an item keeps its block. ``undeclared`` also flags a header field with no vocabulary,
    when the ledger declares any. A parent's record carries ``parts_gates`` (v2.4): each gate that holds
    on one of its open direct parts, keyed in its canonical form, with the parts carrying it.

    **Pick order is the rank** (SPEC *The rank*): ``rank_text`` is the rank file's text (None or
    "": no lines), ``repo`` the last component of an implicit key. Each record carries its ``key``
    (its line's, else its implicit key) and its ``card_key``; entries sort by card, then within a
    card by dependency (after its blockers and its parts), then key."""
    try:
        day = utc_day(today, "pickable()'s today")
    except Refused as why:
        raise ValueError(str(why)) from None
    live = entries(ledger)
    texts = _entry_texts(ledger)
    live_nums = {_num(e["id"]) for e in live}
    archived = heading_nums(archive)
    gone = _archived_status(archive)
    parent_of, part_of = _parents(live)
    parts_open: dict[str, list[str]] = {}
    for c, par in parent_of.items():
        parts_open.setdefault(par, []).append(c)
    table = {int(m.group(2)): m.group(4) for m in ROW_RE.finditer(COMMENT_RE.sub("", ledger))}
    vocab, decl_flags = declared(ledger)
    flags = _Flags()
    for text in decl_flags:
        flags.add(text, None, "fields", "fields-decl")
    lines, rank_flags = rank(rank_text or "")
    lined = {}
    for t, k in lines.items():
        lined.setdefault(_num(t), k)  # by number: a line for TD-7 is TD-007's
    for text in rank_flags:
        flags.add(text, None, "rank", "rank")
    keys: dict[str, str] = {}
    pick, blocked = [], []
    holding: dict[str, list[str]] = {}  # each entry's gates that hold today, as written (parts_gates)
    for e in live:
        n = _num(e["id"])
        prio = e["priority"] or table.get(n) or "?"
        if first_word(prio) not in PRIORITIES:
            said = "has no Priority" if prio == "?" else f"Priority {prio!r} is not High, Medium or Low"
            flags.add(f"ℹ {e['id']}: {said} — read after Low; write High, Medium or Low",
                      e["id"], "priority", "priority")
        for key in e["fields"]:
            if key in RETIRED_FIELDS:
                flags.add(f"ℹ {e['id']}: the {key.capitalize()} field is retired — write "
                          f"{RETIRED_FIELDS[key]} (SPEC *Retired words*)", e["id"], key, "retired")
        status = first_word(e["fields"].get("status"))
        if status in RETIRED_STATUS:
            flags.add(f"ℹ {e['id']}: the Status word {status.capitalize()!r} is retired — write "
                      f"{RETIRED_STATUS[status]} (SPEC *Retired words*)", e["id"], "status", "retired")
        etype = (e["type_raw"] or TYPES[0]).lower()
        for key in e["below"]:
            flags.add(f"ℹ {e['id']}: its {key.capitalize()} line is below the header block — "
                      "read anyway; move it up (cadence.md §2.12)", e["id"], key, "below-header")
        if etype not in TYPES:
            flags.add(f"⚠ {e['id']}: unknown Type {e['type_raw']!r} — write one of "
                      f"{' | '.join(TYPES)}; read as {TYPES[0]}", e["id"], "type", "type")
            etype = TYPES[0]
        for key, allowed in vocab.items():
            v = first_word(e["fields"].get(key))
            if v and v not in allowed:
                flags.add(f"⚠ {e['id']}: {key} {v!r} is not in the preamble's Fields: vocabulary "
                          f"({' | '.join(allowed)})", e["id"], key, "vocabulary")
        if undeclared and vocab:
            for key in e["fields"]:
                if key not in CADENCE_FIELDS and key not in vocab:
                    flags.add(f"ℹ {e['id']}: field {key!r} has no vocabulary on the preamble's Fields: line — "
                              "not validated; declare it (cadence.md §2.12)", e["id"], key, "undeclared-field")
        keys.setdefault(e["id"], lined.get(n) or implicit_key(prio, etype, e["id"], repo))
        rec = {"id": e["id"], "title": e["title"], "priority": prio, "type": etype,
               "blocked_by": [], "cross_repo": [], "pickable": True, "fields": e["fields"],
               "key": keys[e["id"]], "card_key": "", "part_of": None, "parts_open": [], "parts_gates": {}}
        par, why = part_of.get(e["id"], (None, None))
        if why:
            flags.add(f"⚠ {e['id']}: its Part of {why}", e["id"], "part of", "part-of-item")
        elif par:
            rec["part_of"] = par
            if _num(par) not in live_nums:
                if _num(par) in archived:
                    flags.add(f"ℹ {e['id']}: Part of {par}, which is archived — read as an open part of a "
                              "finished parent", e["id"], "part of", "part-of-archived")
                else:
                    flags.add(f"⚠ {e['id']}: Part of {par}, which names no entry in the ledger or the archive",
                              e["id"], "part of", "part-of-unknown")
        if parts_open.get(e["id"]):
            rec["parts_open"] = list(parts_open[e["id"]])
            rec["pickable"] = False
        if e["blocked_raw"] is not None:
            g = parse_gates(e["blocked_raw"])
            ids, bad = g["ids"], g["bad"]
            for item in bad:
                flags.add(f"⚠ {e['id']}: cannot read Blocked by item {item!r} — write TD-n, <repo>#TD-n, "
                          "decision (<person>), until YYYY-MM-DD or event (<name>)", e["id"], "blocked by",
                          "blocked-item")
            for r in g["retired"]:
                flags.add(f"ℹ {e['id']}: Blocked by item {r['item']!r} is retired — write {r['replace']}; "
                          "it keeps the block (SPEC *Retired words*)", e["id"], "blocked by", "retired")
            rep = gate_repeats(g)
            if rep:
                flags.add(f"ℹ {e['id']}: Blocked by names {', '.join(rep)} more than once — at most one "
                          "decision per person, one until and differently named events", e["id"], "blocked by",
                          "gate-repeated")
            for d in g["until"]:
                if d <= day:
                    flags.add(f"ℹ {e['id']}: until {d} is reached — the gate no longer holds; drop it from "
                              "Blocked by", e["id"], "blocked by", "until-past")
            gates = [f"decision ({w})" for w in g["decisions"]] + [f"until {d}" for d in g["until"] if d > day] \
                + [f"event ({x})" for x in g["events"]]
            holding[e["id"]] = gates + [f"decision ({r['holder']})" for r in g["retired"] if r["holder"] is not None]
            if g["decisions"] and "ask" not in e["fields"] and not ASK_RE.search(texts.get(e["id"], "")):
                flags.add(f"ℹ {e['id']}: Blocked by names {', '.join(f'decision ({w})' for w in g['decisions'])} "
                          "and the entry has no **Ask:** — say what the person owes, a go included",
                          e["id"], "blocked by", "ask-missing")
            open_ids = []
            for b in ids:
                if "#" in b:
                    x = _resolved(b, resolve)
                    rec["cross_repo"].append(x)
                    if x["state"] == "open":
                        open_ids.append(b)
                    elif x["state"] == "unresolved":
                        flags.add(f"⚠ {e['id']}: cannot resolve {b} — {x['why']}; the block stays",
                                  e["id"], "blocked by", "cross-repo")
                        open_ids.append(b)  # unresolved: keep the block — the safe direction
                    elif not _ended(e["id"], b, live_nums, gone, resolve, flags, cross=True):
                        open_ids.append(b)
                    continue
                bn = _num(b)
                if bn in live_nums:
                    open_ids.append(b)
                elif bn not in archived:
                    flags.add(f"⚠ {e['id']}: Blocked by {b}, which names no entry in the ledger or the archive",
                              e["id"], "blocked by", "blocked-unknown")
                    open_ids.append(b)  # unknown: keep the block — the safe direction
                elif not _ended(e["id"], b, live_nums, gone, resolve, flags, cross=False):
                    open_ids.append(b)
            kept = [f"decision ({r['holder']})" if r["holder"] is not None else repr(r["item"]) for r in g["retired"]] \
                + [repr(b) for b in bad]  # a retired decision still names who it waits on
            if not open_ids and not gates and not kept:
                if ids:
                    now = "pickable; " if rec["pickable"] else "it still waits on its open parts; "
                    flags.add(f"ℹ {e['id']}: every blocker is archived ({', '.join(ids)}) — {now}"
                              "the Blocked by field can go", e["id"], "blocked by", "blockers-archived")
            else:
                rec["blocked_by"] = open_ids + gates + kept
                rec["pickable"] = False
            below_me = _descendants(e["id"], parts_open)
            legacy = [b for b in ids if "#" not in b and any(_num(b) == _num(d) for d in below_me)]
            if legacy:
                flags.add(f"ℹ {e['id']}: its Blocked by names {', '.join(legacy)}, Part of it — a parent's "
                          "parts keep it unpicked by their Part of line; drop them from Blocked by",
                          e["id"], "blocked by", "legacy-part")
        written = first_word(e["fields"].get("pickable"))
        if written in ("yes", "no") and (written == "yes") != rec["pickable"]:
            flags.add(f"ℹ {e['id']}: its Pickable line says {written}, the derived pickable is "
                      f"{'yes' if rec['pickable'] else 'no'} — the line is only a field (cadence.md §2.12)",
                      e["id"], "pickable", "pickable-disagrees")
        (pick if rec["pickable"] else blocked).append(rec)
    for group in _on_cycles(_waits_on(live, parent_of)):
        for t in group:
            on = f"on a waits-on cycle with {', '.join(x for x in group if x != t)}" if len(group) > 1 \
                else "waits on itself"
            flags.add(f"ℹ {t}: {on} — none of it can be picked; break it (a part is never blocked "
                      "by its parent or an ancestor)", t, "blocked by", "cycle")
    by_id = {r["id"]: r for r in pick + blocked}
    for par, kids in parts_open.items():
        if par not in by_id:
            continue
        pg: dict[str, list[str]] = {}
        canon: dict[str, str] = {}
        for kid in sorted(kids, key=_num):
            for gate in holding.get(kid, []):
                canon.setdefault(_gate_key(gate), gate)  # the lowest-numbered part's spelling
                carriers = pg.setdefault(canon[_gate_key(gate)], [])
                if kid not in carriers:  # a gate written twice on one part is one carrier
                    carriers.append(kid)
        by_id[par]["parts_gates"] = pg
    order = _card_order(live, keys, lined, parent_of)
    for r in pick + blocked:
        r["card_key"] = order[r["id"]][1]
    for lst in (pick, blocked):
        lst.sort(key=lambda r: order[r["id"]][0])
    everything = sorted(pick + blocked, key=lambda r: order[r["id"]][0])
    return {"pickable": pick, "blocked": blocked, "entries": everything, "flags": list(flags),
            "flag_recs": flags.recs, "declared": {k: list(v) for k, v in vocab.items()}}


def _ended(tid: str, b: str, live_nums: set[int], gone: Mapping[int, dict], resolve: Resolve | None,
           flags: _Flags, *, cross: bool) -> bool:
    """Whether archived blocker ``b`` of ``tid`` releases it (v2.4, SPEC *Superseded and dropped*), flagging a
    blocker that was superseded, dropped or archived with a Status word this reader does not know. A
    Superseded one releases only when the end of its chain is Resolved; a Dropped one, one whose Status word
    is unknown (TD-039), or a chain that ends in Dropped, in an unknown word, in no entry or in a loop, keeps
    the block."""
    path, state, word = _chain(b, live_nums, gone, resolve)
    if len(path) == 1 and state == "resolved":
        return True
    where = "another repo's " if cross else ""
    if len(path) == 1 and state == "unknown-status":
        flags.add(f"ℹ {tid}: Blocked by {b}, {where}entry archived with a Status word this reader does not know "
                  f"({word}) — decide this entry: drop the blocker if its work is done, or block on what replaces "
                  "it; the block stays", tid, "blocked by", "cross-unknown-status" if cross else "blocker-unknown-status")
        return False
    if len(path) == 1 and state == "dropped":
        flags.add(f"ℹ {tid}: Blocked by {b}, {where}entry archived Dropped — decide this entry: drop the "
                  "blocker if it no longer applies, or block on what replaces it; the block stays",
                  tid, "blocked by", "cross-dropped" if cross else "blocker-dropped")
        return False
    chain = " → ".join(path)
    if state in ("open", "resolved"):
        then = "" if state == "open" else "; that entry is Resolved, so the block is lifted"
        flags.add(f"ℹ {tid}: Blocked by {b}, superseded ({chain}) — "
                  f"{'the gate sweep rewires it to' if cross else 'name'} {path[-1]} instead{then}",
                  tid, "blocked by", "cross-superseded" if cross else "blocker-superseded")
        return state == "resolved"
    why = {"dropped": "ends in an entry archived Dropped", "unknown": "ends in no entry", "cycle": "loops",
           "unresolved": "cannot be followed to its end",
           "unknown-status": "ends in an entry whose Status word this reader does not know"}[state]
    flags.add(f"ℹ {tid}: Blocked by {b}, superseded ({chain}), whose chain {why} — decide this entry; the block "
              "stays", tid, "blocked by", "cross-superseded" if cross else "blocker-superseded")
    return False


def check(ledger: str, archive: str, old: str | None = None, resolve: Resolve | None = None,
          rank_text: str | None = None, *, today: date | str) -> list[dict]:
    """The ledger's flags: {level, id, field, kind, text, standing}. ``old`` is the ledger before
    an edit (None: every ⚠ is an error and nothing is standing). With it, a flag on an entry whose
    header block is unchanged — or a Fields: flag under an unchanged declaration — is standing:
    information, whatever it was. On a changed or new entry, EDIT_ERRORS are errors too. ``rank_text``
    adds the rank file's flags (never standing: the file is a tool's). Also with ``old`` (v2.2): an
    entry that left the ledger while an open entry is still Part of it is an error,
    ``archive-open-parts``, naming the parts — never standing, since only this edit made it. Each
    open entry's Log (v2.4) adds ``log-not-last`` and ``log-line`` (``log_problems()``), standing when the
    entry's whole text is unchanged; an archived entry's Log is not read. Each open entry's events (v2.4)
    add ``event-section``, ``event-check``, ``event-ungated`` and (v2.5) ``event-undated`` (``event_problems()``, given
    each entry's old text when ``old`` is given), scoped the same way, and
    ``gate-reassigned-often`` (info) for a decision reassigned more than twice to reach it (``reassigns()``).
    ``today`` is ``pickable()``'s (v2.4): the UTC date, required."""
    recs = [dict(r, standing=False)
            for r in pickable(ledger, archive, resolve, undeclared=True, rank_text=rank_text,
                              today=today)["flag_recs"]]
    texts = _entry_texts(ledger)
    old_texts = _entry_texts(old) if old is not None else {}
    day = utc_day(today, "check()'s today")
    for tid, text in texts.items():
        for kind, why in log_problems(text):
            recs.append({"level": "error", "id": tid, "field": "log", "kind": kind, "text": f"⚠ {tid}: {why}",
                         "standing": False})
        for level, kind, why in event_problems(text, old_texts.get(tid, "") if old is not None else None, day):
            recs.append({"level": level, "id": tid, "field": "event", "kind": kind,
                         "text": f"{'⚠' if level == 'error' else 'ℹ'} {tid}: {why}", "standing": False})
        e = entries(text)
        for gate in (gate_items(parse_gates(e[0]["blocked_raw"])) if e else []):
            try:  # an entry _entry_parts() refuses (a field below its header block) has its ℹ already
                n = reassigns(text, gate) if gate.startswith("decision") else 0
            except Refused:
                n = 0
            if n > 2:
                recs.append({"level": "info", "id": tid, "field": "blocked by", "kind": "gate-reassigned-often",
                             "text": f"ℹ {tid}: {gate} was reassigned {n} times — is the decision stuck?",
                             "standing": False})
    if old is None:
        return recs
    before = {e["id"]: e["fields"] for e in entries(old)}
    changed = {e["id"] for e in entries(ledger) if before.get(e["id"]) != e["fields"]}
    rewritten = {t for t, x in texts.items() if old_texts.get(t) != x}  # a Log flag's scope: the whole entry
    decl_changed = declarations(old) != declarations(ledger)
    for r in recs:
        counts = True if r["kind"] == "rank" else decl_changed if r["id"] is None else \
            r["id"] in (rewritten if r["kind"] in TEXT_KINDS else changed)
        if not counts:
            r["standing"], r["level"] = True, "info"
        elif r["kind"] in EDIT_ERRORS:
            r["level"] = "error"
        r["text"] = ("⚠" if r["level"] == "error" else "ℹ") + r["text"][1:]
    return recs + _left_with_open_parts(old, ledger)


LOG_KINDS = ("log-not-last", "log-line")  # check()'s flags on an entry's Log (v2.4)
EVENT_KINDS = ("event-section", "event-check", "event-ungated", "event-undated")  # check()'s flags on an entry's events (v2.4; event-undated v2.5)
TEXT_KINDS = LOG_KINDS + EVENT_KINDS + ("ask-missing", "gate-reassigned-often")  # flags that read the body: scoped by the entry's whole text


def _entry_texts(text: str) -> dict[str, str]:
    """Each entry's text (its heading to the next ``## `` heading), HTML comments dropped, by id."""
    text = COMMENT_RE.sub("", text)
    out = {}
    for m in HEADING_RE.finditer(text):
        nxt = SECTION_RE.search(text, m.end())
        out.setdefault(m.group(1), text[m.start(): nxt.start() if nxt else len(text)])
    return out


def _left_with_open_parts(old: str, ledger: str) -> list[dict]:
    """``archive-open-parts`` (v2.2): each id in ``old`` and not in ``ledger`` (by number) that an open
    entry of ``ledger`` is still Part of — the parent archived, or renumbered, ahead of its parts."""
    live = entries(ledger)
    now = {_num(e["id"]) for e in live}
    left = {}
    for e in entries(old):
        if _num(e["id"]) not in now:
            left.setdefault(_num(e["id"]), e["id"])
    parts: dict[int, list[str]] = {}
    for e in live:
        par = parse_part_of(e["part_of_raw"])[0]
        if par and _num(par) in left:
            parts.setdefault(_num(par), []).append(e["id"])
    return [{"level": "error", "id": left[n], "field": "part of", "kind": "archive-open-parts", "standing": False,
             "text": f"⚠ {left[n]}: left the ledger while {', '.join(ps)} {'is' if len(ps) == 1 else 'are'} still "
                     "Part of it — archive its parts first, or point their Part of at its new id or another parent"}
            for n, ps in sorted(parts.items())]


# ---------------------------------------------------------------------------------------------
# The rank: the person's order of a ledger's entries, and the pick order it gives
# ---------------------------------------------------------------------------------------------

RANK_LINE_RE = re.compile(r"^(TD-\d+):[ \t]+(\S+)[ \t]*$")
KEY_RE = re.compile(r"^[0-9A-Za-z][|\w./-]*$", re.ASCII)  # never a leading `|`; the rest of a repo name may ride along
KEY_SEP = "|"  # the lowest character of the key order, below every other
KEY_NOTE_AT = 64  # a rank key longer than this is noted (ℹ, v2.3): respace the file; an implicit key is about 20
KEY_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"  # what midpoint() writes, in key order
BANDS = {"high": "1", "medium": "2", "low": "3"}  # an implicit key's first component; anything else is 4
RANK_HEADER = ("# The rank: one `TD-NNN: <key>` line per entry, sorted by key (ledgerboard SPEC, The rank).\n"
               "# Written by a tool; read only through ledgerboard's rank().\n")
QUEUE_ACTIONS = ("rank", "join", "prune", "respace")
QUEUE_SUBJECT_RE = re.compile(r"^queue: (?:rank|join|prune|respace) TD-\d+(?:, TD-\d+)* \([^()\s][^()]*\)$")


def rank_path(ledger_path: str) -> str:
    """The rank file of the ledger at ``ledger_path``: ``<ledger stem>_rank.yml`` beside a v1 file,
    ``rank.yml`` inside a v2 directory (a path not ending in ``.md``)."""
    if not ledger_path.endswith(".md"):
        return _sub(ledger_path, "rank.yml")
    head, sep, name = ledger_path.rpartition("/")
    stem = name[:-3] if name.endswith(".md") else name
    return f"{head}{sep}{stem}_rank.yml"


def key_order(key: str) -> tuple[int, ...]:
    """A key's sort value: code point order, except that ``|`` sorts below every other character."""
    return tuple(-1 if c == KEY_SEP else ord(c) for c in key)


def implicit_key(priority: str | None, etype: str | None, tid: str, repo: str = "") -> str:
    """The key of an entry with no rank line: Priority band, Type index, id number to six digits,
    then the repo name (``2|0|000642|shiftlead``); no repo, no last component."""
    band = BANDS.get((priority or "").lower(), "4")
    t = (etype or TYPES[0]).lower()
    k = f"{band}{KEY_SEP}{TYPES.index(t) if t in TYPES else 0}{KEY_SEP}{_num(tid):06d}"
    return f"{k}{KEY_SEP}{repo}" if repo else k


def midpoint(a: str | None, b: str | None) -> str:
    """A key strictly between ``a`` and ``b`` (None: that end is open), written from KEY_DIGITS
    after a shared prefix, never ending in the lowest digit it writes — so there is room again."""
    for k in (a, b):
        if k is not None and not KEY_RE.match(k):
            raise Refused(f"not a key: {k!r}")
    lo, hi = a or "", b
    if hi is not None and key_order(lo) >= key_order(hi):
        raise Refused(f"no key between {a!r} and {b!r}: they are not in order")
    out, i, between = [], 0, None
    while True:
        ca = lo[i] if i < len(lo) else None
        cb = hi[i] if hi is not None and i < len(hi) else None
        if hi is not None and cb is None:
            if between:  # b ran out while it was followed: the longest prefix of b above a is between
                return between
            raise Refused(f"no key between {a!r} and {b!r}")
        if ca is not None and ca == cb:
            out.append(ca)
            i += 1
            continue
        low = key_order(ca)[0] if ca is not None else -2
        high = key_order(cb)[0] if cb is not None else 1 << 21
        fits = [d for d in KEY_DIGITS[1:] if low < ord(d) < high]
        if fits:
            return "".join(out) + fits[len(fits) // 2]
        if ca is not None:  # keep a's character: from here on anything above a's rest is below b
            out.append(ca)
            hi = None
        elif ord(KEY_DIGITS[0]) < high:  # below b's character only the lowest digit fits: take it, b is passed
            out.append(KEY_DIGITS[0])
            hi = None
        elif cb == KEY_DIGITS[0] and i + 1 < len(hi) or cb == KEY_SEP or not out:  # follow b and go deeper
            out.append(cb)
            if len(out) > len(lo) and KEY_RE.match("".join(out)) and "".join(out) != hi:
                between = "".join(out)  # a proper prefix of b, longer than a: a fallback when b runs out
        else:  # the separator, the lowest character, is below b's: take it, b is passed
            out.append(KEY_SEP)
            hi = None
        i += 1


def rank(text: str) -> tuple[dict[str, str], list[str]]:
    """A rank file's ``{id: key}`` and flags: ⚠ for a line it cannot read or a repeated id (the
    first wins), ℹ for a blank line, a comment below the first entry, lines out of key order, or (v2.3) a
    key longer than KEY_NOTE_AT characters."""
    keys: dict[str, str] = {}
    flags: list[str] = []
    seen_entry, last = False, None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            flags.append(f"ℹ rank line {n}: blank — ignored")
            continue
        if line.startswith("#"):
            if seen_entry:
                flags.append(f"ℹ rank line {n}: a comment below the first entry — comments come first")
            continue
        m = RANK_LINE_RE.match(line)
        if not m or not KEY_RE.match(m.group(2)):
            flags.append(f"⚠ rank line {n}: cannot read {line!r} — write TD-NNN: <key>")
            continue
        seen_entry = True
        tid, key = m.groups()
        if tid in keys:
            flags.append(f"⚠ rank line {n}: {tid} again — its first line holds ({keys[tid]})")
            continue
        if last is not None and key_order(key) < key_order(last):
            flags.append(f"ℹ rank line {n}: {tid} is out of key order — the file is sorted by key")
        if len(key) > KEY_NOTE_AT:
            flags.append(f"ℹ rank line {n}: {tid}'s key is {len(key)} characters, over {KEY_NOTE_AT} — respace the file")
        keys[tid], last = key, key
    return keys, flags


def set_rank(text: str, lines: Mapping[str, str | None]) -> str:
    """The rank file with the given ids' lines set (a key) or removed (None); every other line
    byte for byte. A new line goes before the first entry line whose key sorts above it."""
    for tid, key in lines.items():
        if not ID_ITEM_RE.match(tid):
            raise Refused(f"not an entry id: {tid!r}")
        if key is not None and not KEY_RE.match(key):
            raise Refused(f"not a key: {key!r}")
    nl = "\r\n" if "\r\n" in text else "\n"  # a new line takes the file's own ending
    src = text.splitlines(keepends=True) if text else [ln + nl for ln in RANK_HEADER.splitlines()]
    if src and not src[-1].endswith("\n"):
        src[-1] += nl
    kept = []
    for line in src:
        m = RANK_LINE_RE.match(line.rstrip("\r\n"))
        if not (m and m.group(1) in lines):
            kept.append(line)
    for tid, key in sorted(((t, k) for t, k in lines.items() if k is not None),
                           key=lambda tk: (key_order(tk[1]), _num(tk[0]))):
        at = len(kept)
        for j, line in enumerate(kept):
            m = RANK_LINE_RE.match(line.rstrip("\r\n"))
            if m and (key_order(m.group(2)), _num(m.group(1))) > (key_order(key), _num(tid)):
                at = j
                break
        kept.insert(at, f"{tid}: {key}{nl}")
    out = "".join(kept)
    got, _ = rank(out)
    want = {t: k for t, k in lines.items() if k is not None}
    if any(got.get(t) != k for t, k in want.items()) or any(t in got for t, k in lines.items() if k is None):
        raise Refused("the rank file does not read back as written")  # a repeated id it cannot set alone
    return out


def _spread(lo: str | None, hi: str | None, n: int) -> list[str]:
    """`n` keys strictly between `lo` and `hi` (None: open), in order, by halving the gap with midpoint()."""
    if n <= 0:
        return []
    m = midpoint(lo, hi)
    left = (n - 1) // 2
    return [*_spread(lo, m, left), m, *_spread(m, hi, n - 1 - left)]


def respace(text: str, ledger: str, *, fixed: Iterable[str] = (), repo: str = "") -> tuple[str, list[str]]:
    """The rank file with its keys shortened, and the ids whose keys changed (v2.3, SPEC *The rank*), moving
    nothing relative to a key it does not own. The fixed points are the keys of the ledger's open entries
    that have no line (their implicit keys, ``repo`` their last component), every key in ``fixed`` (another
    repo's, which a caller sorts beside these), the two ends of each band's range of implicit keys for ids past
    every id read (where an entry filed later sorts), and any line's key equal to one of them or inside such a range. The other lines' keys
    between two consecutive fixed points are rewritten to short keys inside that same gap, in the same order,
    equal keys staying equal. Every other line is kept byte for byte (``set_rank()``). Refused for a rank file
    the reader flags ⚠."""
    lines, flags = rank(text)
    bad = [f for f in flags if f.startswith("⚠")]
    if bad:
        raise Refused("the rank file has lines the reader cannot use: " + "; ".join(bad))
    for k in fixed:
        if not KEY_RE.match(k):
            raise Refused(f"not a key: {k!r}")
    lined_nums = {_num(t) for t in lines}
    recs = pickable(ledger, "", lambda _x: ("unresolved", "respace reads no other repo"), rank_text="",
                    repo=repo, today=date.min)["entries"]  # keys and order only: neither reads today
    points = {r["key"] for r in recs if _num(r["id"]) not in lined_nums} | set(fixed)
    # an entry filed later has an implicit key in its band past every id read: each band's range of those
    # stays a gap no rewritten key enters, so a respace never moves a line across where a new entry will sort
    nxt = max([_num(r["id"]) for r in recs] + [_num(t) for t in lines] + [0]) + 1
    future = []  # each band's range of implicit keys for ids past every id read, both ends included
    for band in sorted(set(BANDS.values()) | {"4"}):
        for t in range(len(TYPES)):
            lo, hi = (f"{band}{KEY_SEP}{t}{KEY_SEP}{n:06d}" for n in (min(nxt, 999999), 999999))
            future.append(tuple(f"{k}{KEY_SEP}{repo}" if repo else k for k in (lo, hi)))
    points |= {k for rng in future for k in rng}

    def in_future(k: str) -> bool:
        return any(key_order(lo) <= key_order(k) <= key_order(hi) for lo, hi in future)
    # a line's key equal to a fixed point, or inside a future range (where an id the ledger has not read, an
    # archived one's successor, may sort on either side of it), is itself fixed
    points |= {k for k in lines.values() if k in points or in_future(k)}
    order = sorted(points, key=key_order)
    gaps: dict[tuple[str | None, str | None], list[str]] = {}
    for k in sorted({k for k in lines.values() if k not in points}, key=key_order):
        lo = next((p for p in reversed(order) if key_order(p) < key_order(k)), None)
        hi = next((p for p in order if key_order(p) > key_order(k)), None)
        gaps.setdefault((lo, hi), []).append(k)
    new_key: dict[str, str] = {}
    for (lo, hi), ks in gaps.items():
        new_key.update(zip(ks, _spread(lo, hi, len(ks))))
    changed = {t: new_key[k] for t, k in lines.items() if k in new_key and new_key[k] != k}
    if not changed:
        return text, []
    out = set_rank(text, changed)
    got, _ = rank(out)
    before = sorted(points | set(lines.values()), key=key_order)
    def rel(a: str, b: str) -> int:
        return (key_order(a) > key_order(b)) - (key_order(a) < key_order(b))
    after = {k: new_key.get(k, k) for k in before}
    if any(rel(after[a], after[b]) != rel(a, b) for a in before for b in before) \
            or any(in_future(k) or in_future(v) for k, v in new_key.items()) \
            or any(got[t] != new_key.get(k, k) for t, k in lines.items()):
        raise Refused("the respaced keys would not keep the file's order: nothing written")
    return out, sorted(changed, key=_num)


def components(ents: list[dict]) -> list[dict]:
    """The connected components of ``ents`` (``entries()`` of a ledger or an archive) over their
    Blocked by ids and their Part of parent (v2.1), both directions: ``{ids, others, cross_repo}`` — the members in file order, the
    local ids they name that are not among ``ents`` (an archived or unknown entry: not a member,
    joins nothing), and the ``<repo>#TD-NNN`` ids they name, for a caller to join across repos.
    Components are in the file order of their first member."""
    order = [e["id"] for e in ents]
    present: dict[int, str] = {}  # by number, as pickable() reads a blocker: TD-7 is TD-007
    for t in order:
        present.setdefault(_num(t), t)
    parent = {t: t for t in order}

    def find(t: str) -> str:
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t
    named: dict[str, tuple[list[str], list[str]]] = {}
    for e in ents:
        ids = parse_blocked(e["blocked_raw"])[0] if e.get("blocked_raw") else []
        par = parse_part_of(e.get("part_of_raw"))[0]
        if par and all(_num(par) != _num(b) for b in ids if "#" not in b):
            ids = [*ids, par]  # another repo's entry is never a parent: parse_part_of() reads none
        others, xrepo = [], []
        for b in ids:
            if "#" in b:
                xrepo.append(b)
            elif _num(b) in present:
                if _num(b) != _num(e["id"]):
                    parent[find(present[_num(b)])] = find(e["id"])
            else:
                others.append(b)
        named[e["id"]] = (others, xrepo)
    groups: dict[str, dict] = {}
    for t in order:
        g = groups.setdefault(find(t), {"ids": [], "others": [], "cross_repo": []})
        if t in g["ids"]:
            continue  # a repeated heading: one member
        g["ids"].append(t)
        for key, vals in zip(("others", "cross_repo"), named[t]):
            g[key].extend(v for v in vals if v not in g[key])
    return list(groups.values())


def _card_order(live: list[dict], keys: dict[str, str], lined: dict[int, str],
                parent_of: Mapping[str, str] | None = None) -> dict[str, tuple[tuple, str]]:
    """Each live entry's (sort value, card key). The card key is the best lined key among the card's
    members when any has a line, else the best implicit key; the sort value is that key, the card's
    lowest id, then the entry's place in the card — after every member it is blocked by and every
    part of it (``parent_of``: {part: parent}), else by key."""
    out: dict[str, tuple[tuple, str]] = {}
    raw = {e["id"]: e["blocked_raw"] for e in live}
    for comp in components(live):
        ids = comp["ids"]
        card = min((keys[t] for t in ids if _num(t) in lined), key=key_order, default=None) \
            or min((keys[t] for t in ids), key=key_order)
        low = min(_num(t) for t in ids)
        num = {_num(t): t for t in ids}
        deps = {t: {num[_num(b)] for b in parse_blocked(raw[t] or "")[0]
                    if "#" not in b and _num(b) in num and num[_num(b)] != t} for t in ids}
        for c, par in (parent_of or {}).items():
            if par in deps and c in deps and c != par:
                deps[par].add(c)
        left, pos = set(ids), 0
        while left:
            ready = [t for t in left if not deps[t] & left] or list(left)  # a cycle: key order breaks it
            nxt = min(ready, key=lambda t: (key_order(keys[t]), _num(t)))
            out[nxt] = ((key_order(card), low, pos), card)
            left.discard(nxt)
            pos += 1
    return out


# ---------------------------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------------------------

ITEM_RE = re.compile(r"^\s*-\s*\[ \]\s+(?P<text>.+)$")
# The board is append-only: closing an item ticks it and appends `Closed: YYYY-MM-DD — why.`,
# never deletes it; closed items are archived later, once ARCHIVE_AT of them sit on the board.
CLOSED_ITEM_RE = re.compile(r"^\s*-\s*\[[xX]\]\s+(?P<text>.+)$")
CLOSED_RE = re.compile(r"(?:^|(?<=[.?!]\s))Closed:\s*(?P<date>\d{4}-\d{2}-\d{2})\b.*$")
ARCHIVE_AT = 10
DUE_RE = re.compile(r"\bDue:\s*(?P<due>\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
# Two optional TRAILING fields, in this order, after Due: —
#   … Due: YYYY-MM-DD. Answers: approve | hold. Decided: approve (YYYY-MM-DD).
# Answers: is written by whoever raised the item (`|`-separated, `\|` for a literal bar); Decided:
# only on a person's action. Both are anchored to the end of the line, start a sentence (line
# start, or after `. ` / `? ` / `! `), and are read only after the item's Due: when it has one —
# so "check Answers: yes" in an item's prose, dated or not, parses as neither field.
DECIDED_RE = re.compile(r"(?:^|(?<=[.?!]\s))Decided:\s*(?P<text>(?:(?!\bDecided:).)+?)\s*"
                        r"\((?P<date>\d{4}-\d{2}-\d{2})\)\.?\s*$")
ANSWERS_RE = re.compile(r"(?:^|(?<=[.?!]\s))Answers:\s*(?P<answers>(?:(?!\bAnswers:).)*?)"
                        r"(?:[.?!]\s+Lifts:.*|\.?\s*(?:\bDecided:.*)?)$")
# `Lifts: a | b.` (v2.3): which of a decide's answers lift the gate its Context names, after its Answers: and
# ahead of its Decided:; written only when it is not `Go` alone, so none means `Go`. What a lift does is v2.4's.
LIFTS_RE = re.compile(r"(?<=[.?!]\s)Lifts:\s*(?P<lifts>(?:(?!\b(?:Lifts|Answers):).)*?)\.?\s*(?:\bDecided:.*)?$")
# A reply — what the person said back on the item's own line: ` — <name>, YYYY-MM-DD: <words>`,
# after the item's Due: and ahead of its trailing Answers:/Decided:/Closed: fields, any number of
# them in a row. <name> is any short run with no comma or dash.
REPLY_TAIL_RE = re.compile(r" — (?P<by>[^\s,—][^,—]{0,39}), (?P<date>\d{4}-\d{2}-\d{2}): ")
ANSWER_SPLIT_RE = re.compile(r"\s*(?<!\\)\|\s*")
# A due date written in a shape DUE_RE cannot read (2026-9-5, 2026-02-30, "Due 2026-09-05"
# without the colon). Only a DATE-SHAPED token counts, so prose about the field is never one.
DUE_ATTEMPT_RE = re.compile(r"\bDue:?\s*(?P<raw>\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,4})?)\b", re.IGNORECASE)
# An item's KIND — one optional word before its date, `- [ ] decide 2026-09-27 (…)`. Only a word
# followed by a date is a kind, so prose that happens to start with "act" is not.
KINDS = ("decide", "act", "look", "watch", "fyi")
KIND_RE = re.compile(r"^(?P<kind>decide|act|look|watch|fyi)\s+(?=\d{4}-\d{2}-\d{2}\b)", re.IGNORECASE)
# At most one answer's label ends in " (default)" — the asker's recommendation.
DEFAULT_MARK_RE = re.compile(r"\s*\(default\)$", re.IGNORECASE)
# An answer may say what it leads to after its first " — ": `<label> (default) — <consequence>`.
CONSEQUENCE_SEP = " — "
# A live look's (a `look`'s) answers, in exactly these words, so a tool can draw the same two buttons.
LIVE_LOOK_ANSWERS = ("Works", "Not right: <what>")
# The second of them is a FORM, its slot the person's words: offered as `Not right:` alone or with
# one `<…>` placeholder. `Not right: wrong repo` is a complete answer, not the form.
NOT_RIGHT = "Not right:"
NOT_RIGHT_FORM_RE = re.compile(r"Not right:\s*(?:<[^<>]*>)?")
# An item's bold head: its first `**…**` run, the line's title where it has one.
BOLD_RE = re.compile(r"\*\*(?P<bold>.+?)\*\*")
# The head: `[kind] YYYY-MM-DD (session <name> on <host>…)`, name and host optionally backticked.
# Boards also write `(session `ab12cd34` / `worker-2` on host, branch x)`: the session is the
# first name, the host the first word after ` on ` anywhere inside the parentheses.
HEAD_RE = re.compile(r"^(?:[A-Za-z]+\s+)?\d{4}-\d{2}-\d{2}\s*\(session\s+`?(?P<session>[^\s`,;)]+)`?(?P<rest>[^)]*)")
HEAD_HOST_RE = re.compile(r"\bon\s+`?([^\s`,;)]+)")
CONTEXT_RE = re.compile(r"\bContext:\s*(?P<ctx>.*?)(?=\s+(?:Parts|Due|Hide until|Answers|Lifts|Decided|Closed):|$)")
# `Parts: TD-15, TD-16.` (v2.3): the parts of the parent a decide's Context names that the question asks about,
# right after Context: and ahead of Due:. Its ids are no Context refs. What a lift does with them is v2.4's.
PARTS_RE = re.compile(r"\s+Parts:\s*(?P<ids>.*?)(?=\s+(?:Due|Hide until|Answers|Lifts|Decided|Closed):|$)")
# `Hide until: D.` (v2.3): the item is left out of what needs the person until D, its Due: untouched. It
# starts a sentence and is read only after the item's Due:, or after its Context: when it has none (an fyi).
HIDE_RE = re.compile(r"(?:^|(?<=[.?!]\s))Hide until:\s*(?P<date>\d{4}-\d{2}-\d{2})\b")
HIDE_KEY_RE = re.compile(r"\s*\bHide until:\s*\d{4}-\d{2}-\d{2}\b\.?")  # what item_key strips, as it strips Due:
# A TD ref in prose (v2.4): `<repo>#TD-n` with the repo as XREPO_ITEM_RE has it, read only at the
# start or after whitespace, ASCII punctuation other than `/ . - @ : # _ \`, or a typographic dash or
# quote (REF_BEFORE), and not a repo whose first component is a `TD-n`; or a bare `TD-n` with no `#`
# before it. Anything else before a repo (a letter, a combining mark, a zero-width character, a path
# or URL) makes it the tail of a longer word, so a bad repo is no ref at all, never a shorter one.
REF_BEFORE = "\\s!\"$&'()*+,;<=>?\\[\\]^`{|}~—–“”‘’«»…"
REF_TD_RE = re.compile(rf"(?<![^{REF_BEFORE}])(?!TD-\d+[/#]){REPO}#TD-\d+|(?<!#)TD-\d+")
REF_PR_RE = re.compile(r"\bPRs?\s*#\d+(?:\s*(?:/|,|&|and)\s*#\d+)*")  # PR #12 · PRs #12/#13 · PR #12, #13
REF_BRANCH_RE = re.compile(r"^(?P<said>branch\s+)?`?(?P<name>[A-Za-z0-9][\w./-]*)`?$")
REF_FILE_RE = re.compile(r"\.\w{1,5}$")  # docs/plans/x.md is a path, not a branch


def _trailer(text: str) -> str:
    """The part of an item the trailing fields may live in: after its Due:, if any."""
    m = DUE_RE.search(text)
    return text[m.end():] if m else text


def _raw_answers(text: str) -> list[str]:
    m = ANSWERS_RE.search(_trailer(text))
    if not m:
        return []
    parts = (a.replace("\\|", "|").strip() for a in ANSWER_SPLIT_RE.split(m.group("answers")))
    return [a for a in parts if a]


def split_answer(answer: str) -> tuple[str, str, bool]:
    """One written answer as (label, consequence, marked): split on its first ` — ` (a
    dashless answer is all label, its consequence ""), the ` (default)` mark read and
    stripped at the label's end — or at the answer's very end, where a whole answer was
    marked before v1.3."""
    label, sep, cons = answer.partition(CONSEQUENCE_SEP)
    label, cons = label.strip(), cons.strip()
    if not sep and label.endswith(CONSEQUENCE_SEP.rstrip()):
        label = label[: -len(CONSEQUENCE_SEP.rstrip())].rstrip() or label  # `B —`: an empty consequence
    marked = bool(DEFAULT_MARK_RE.search(label))
    if marked:
        label = DEFAULT_MARK_RE.sub("", label) or label
    elif sep and DEFAULT_MARK_RE.search(cons):
        marked, cons = True, DEFAULT_MARK_RE.sub("", cons)
    return label, cons, marked


def parse_answers(text: str) -> list[str]:
    """The item's `Answers:` labels, in order, any ` (default)` mark stripped and any
    ` — <consequence>` left out (parse_consequences); [] when none."""
    return [split_answer(a)[0] for a in _raw_answers(text)]


def parse_consequences(text: str) -> list[str]:
    """What each of the item's answers leads to, parallel to parse_answers(): the text after
    its first ` — `, "" for an answer that says none."""
    return [split_answer(a)[1] for a in _raw_answers(text)]


def parse_default(text: str) -> str | None:
    """The label marked ` (default)`, without the mark; None when no answer is marked, or
    more than one is (no single recommendation to show)."""
    marked = [label for label, _, m in map(split_answer, _raw_answers(text)) if m]
    return marked[0] if len(marked) == 1 and marked[0] else None


# A person's name (v2.3, target design §3.1): dot-separated runs of letters, digits, `_` and `-`, compared
# case-insensitively. `People:` lists them; `Decided: <label> (by <person>) (D).` records who answered.
PERSON = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
PERSON_RE = re.compile(PERSON)
DECIDED_BY_RE = re.compile(r"^(?P<label>.*\S)\s+\(by (?P<by>" + PERSON + r")\)$")
PEOPLE_RE = re.compile(r"^People:(?P<names>.*)$")
CONTEXT_ANY_GATE_RE = re.compile(r"\b(?:decision \(" + PERSON + r"\)|event \([A-Za-z0-9][\w.-]*\))")  # a gate the Context names (v2.3: its one entry)
CONTEXT_GATE_RE = re.compile(r"\bdecision \((?P<person>" + PERSON + r")\)")


def _decided_parts(text: str) -> tuple[str, str | None, date] | None:
    """(label, by, date) of the item's `Decided:` field, or None (absent or a bad date). Only a final
    `(by <person>)` before the date, `<person>` in the person grammar, is split off as `by` (v2.3)."""
    m = DECIDED_RE.search(_trailer(text))
    if not m:
        return None
    try:
        day = datetime.strptime(m.group("date"), "%Y-%m-%d").date()  # noqa: DTZ007  # a civil date, as Due:
    except ValueError:
        return None
    b = DECIDED_BY_RE.match(m.group("text"))
    return (b.group("label"), b.group("by"), day) if b else (m.group("text"), None, day)


def parse_decided(text: str) -> tuple[str, date] | None:
    """The item's `Decided: <label> [(by <person>)] (YYYY-MM-DD)` field as (label, date), or None (absent or
    a bad date). The label is the answer alone: a final `(by <person>)` is parse_decided_by()'s (v2.3)."""
    got = _decided_parts(text)
    return (got[0], got[2]) if got else None


def parse_decided_by(text: str) -> str | None:
    """Who gave the item's `Decided:` answer — its final `(by <person>)` (v2.3) — or None."""
    got = _decided_parts(text)
    return got[1] if got else None


def is_person(name: object) -> bool:
    """Whether `name` is a person's name in the person grammar (v2.3)."""
    return isinstance(name, str) and PERSON_RE.fullmatch(name) is not None


def _people_line(content: str) -> tuple[int, str] | None:
    """(1-based line, names text) of the board's first `People:` line above its first item, or None."""
    for n, ln in enumerate(content.splitlines(), start=1):
        if ANY_ITEM_RE.match(ln):
            return None
        m = PEOPLE_RE.match(ln.rstrip())
        if m:
            return n, m.group("names")
    return None


def board_people(content: str) -> list[str] | None:
    """The names the board's `People:` preamble line lists (v2.3), as written, in order — or None when
    it has none. The line is read only above the board's first item; its names are comma-separated.
    A name outside the person grammar, a duplicate or an empty list is returned as it stands, for
    board_problems() to flag; compare names case-insensitively."""
    got = _people_line(content)
    if got is None:
        return None
    return [n.strip() for n in got[1].split(",")] if got[1].strip() else []


def reply_span(text: str) -> tuple[int, int] | None:
    """(start, end) of the item's reply tails, or None: from the first ` — <name>, <date>: `
    after its Due: to its trailing Answers:/Decided:/Closed: fields, or the line's end. Read
    only after the Due: — prose shaped like a reply before it is the item's own."""
    due = DUE_RE.search(text)  # the item's own Due: is its first, as _trailer reads it — a reply may name one
    m = REPLY_TAIL_RE.search(text, due.end() if due else 0)
    if m is None:
        return None
    ends = [f.start() for f in (r.search(text, m.end()) for r in (ANSWERS_RE, DECIDED_RE, CLOSED_RE)) if f]  # a Lifts: follows Answers:
    end = min(ends) if ends else len(text)
    return m.start(), m.start() + len(text[m.start():end].rstrip())


def _hide_match(text: str) -> re.Match | None:
    """The item's `Hide until:` field as the reader finds it: after its Due:, or after its Context: when it
    has none, and ahead of its replies; None when it has none."""
    due = DUE_RE.search(text)
    if due:
        start = due.end()
    else:
        c = CONTEXT_RE.search(text)
        if c is None:
            return None
        start = c.start()
    # it ends at the first reply or trailing field: an answer's, a Decided: text's or a reply's words are no field
    span = reply_span(text)
    ends = [f.start() for f in (r.search(text, start) for r in (ANSWERS_RE, DECIDED_RE, CLOSED_RE)) if f]
    end = min([*ends, *([span[0]] if span else []), len(text)])
    return HIDE_RE.search(text, start, end)


def parse_lifts(text: str) -> list[str] | None:
    """The labels of the item's `Lifts:` field (v2.3), `\\|` read as a bar, or None when it has none (which
    means `Go`). Read as Answers: is, in the trailer after its Due:."""
    trailer = _trailer(text)
    a = ANSWERS_RE.search(trailer)
    if not a:
        return None  # it follows Answers: — a reply's or a Decided: text's words are never the field
    d = DECIDED_RE.search(trailer, a.start())
    m = LIFTS_RE.search(trailer[: d.start()] if d else trailer, a.start())
    if not m:
        return None
    parts = (a.replace("\\|", "|").strip() for a in ANSWER_SPLIT_RE.split(m.group("lifts")))
    return [a for a in parts if a]


def parse_parts(text: str) -> list[str]:
    """The ids of the item's `Parts:` field (v2.3), in order, each once, or [] when it has none: every
    `TD-NNN` (or `<repo>#TD-NNN`) in it. It is read only where the item's Context: ends, as its next field, and
    never inside a reply's words."""
    c = CONTEXT_RE.search(text)
    m = PARTS_RE.match(text, c.end()) if c else None
    span = reply_span(text)
    if m and span and span[0] <= m.start("ids") < span[1]:
        m = None
    out: list[str] = []
    for x in REF_TD_RE.finditer(m.group("ids") if m else ""):
        if ref_key(x.group(0)) not in {ref_key(o) for o in out}:
            out.append(x.group(0))
    return out


def parse_hide_until(text: str) -> date | None:
    """The item's `Hide until:` date, or None: none, or not a date."""
    m = _hide_match(text)
    try:
        return date.fromisoformat(m.group("date")) if m else None
    except ValueError:
        return None


def parse_replies(text: str) -> list[tuple[str, str, str]]:
    """The item's replies in order, each (by, YYYY-MM-DD, words); [] when it has none."""
    span = reply_span(text)
    if span is None:
        return []
    tails = text[span[0]:span[1]]
    marks = list(REPLY_TAIL_RE.finditer(tails))
    return [(m.group("by"), m.group("date"), tails[m.end():(nxt.start() if nxt else len(tails))].strip())
            for m, nxt in zip(marks, [*marks[1:], None])]


@dataclass
class BoardItem:
    text: str
    due: date | None
    line: int = 0  # 1-based line in the board; 0 when parsed from a string with no file
    answers: list[str] = field(default_factory=list)  # the labels
    default: str | None = None  # the label marked ` (default)`
    consequences: list[str] = field(default_factory=list)  # parallel to answers; "" for none
    # A decided item is NOT done: it stays on the board, and stays due, until whoever acts on
    # it closes it — but it is no longer the person's to-do.
    decided: tuple[str, date] | None = None
    decided_by: str | None = None  # who gave the Decided: answer, its `(by <person>)` (v2.3)
    bad_due: str | None = None  # the text after "Due:" when it is not a date
    kind: str | None = None  # decide | act | look | watch | fyi, or None when unmarked
    fyi_due: bool = False  # an fyi item that carries a Due: anyway — ignored, and flagged
    # The item's detail block — the lines under it indented deeper than its `-`, common indent
    # removed. No edit touches it: Due:/Answers:/Decided:/replies stay on the head line.
    detail: list[str] = field(default_factory=list)
    hide_until: date | None = None  # `Hide until:` (v2.3): left out of what needs the person until then
    lifts: list[str] | None = None  # `Lifts:` (v2.3): the answers that lift; None means `Go`
    parts: list[str] = field(default_factory=list)  # `Parts:` (v2.3): the parts a parent's question asks about

    def hidden(self, today: date) -> bool:
        """Left out of what needs the person today: a `Hide until:` still ahead. A decided item is a session's
        work order and is never hidden."""
        return self.hide_until is not None and self.decided is None and today < self.hide_until

    @property
    def todo(self) -> bool:
        """The person's to-do: decide, act, look, or unmarked."""
        return self.kind not in ("watch", "fyi")

    @property
    def waiting_on(self) -> str:
        """Who the item waits on: a decided item is a work order, no longer the person's."""
        return "session" if self.decided else "person"

    def overdue_days(self, today: date) -> int | None:
        """Days at-or-past due (0 = due today); None if no due date or not yet due."""
        if self.due is None or self.due > today:
            return None
        return (today - self.due).days


def item_key(line: str) -> str:
    """An item line with what an edit may change taken out — the tick, the Closed:, Decided: and
    Due: fields and `Hide until:` (v2.3; an edit may also end the sentence before them) and its reply tails — so the open
    and the closed copy of one item, or a snoozed or replied-to one, compare equal.

    Indentation is kept (a re-indented line is not an edit), and a collision needs the whole
    `date (session …) — text` equal. **Part of the format:** consumers persist keys derived from
    this text, so a change to what it returns for a given line is a major version."""
    line = re.sub(r"^(\s*-\s*)\[[ xX]\]", r"\1[ ]", line)
    line = re.sub(r"\s*" + CLOSED_RE.pattern, "", line)
    line = re.sub(r"\s*" + DECIDED_RE.pattern, "", line)
    span = reply_span(line)
    if span:
        line = line[: span[0]] + line[span[1]:]
    line = HIDE_KEY_RE.sub("", line)  # v2.3: a hide moves no key (the one exception to the rule above)
    line = re.sub(r"\s*(?:" + DUE_RE.pattern + r")\.?", "", line, flags=re.IGNORECASE)
    return line.rstrip(" .")


def closed_items(content: str) -> list[str]:
    """The board's closed (`- [x]`) item lines."""
    return [ln for ln in content.splitlines() if CLOSED_ITEM_RE.match(ln)]


def parse_closed_items(content: str) -> list[BoardItem]:
    """The board's (or its archive's) closed items, in order, each read as parse_board() reads an open one
    (v2.4): its trailing `Closed:` field cut first, since the fields before it are anchored at the line's
    end. Each keeps its 1-based line and its detail block."""
    lines = content.splitlines()
    shown = []
    for ln in lines:
        m = CLOSED_ITEM_RE.match(ln)
        if m is None:
            shown.append("" if ANY_ITEM_RE.match(ln) else ln)  # an open item is not read here; its line stays
            continue
        c = CLOSED_RE.search(m.group("text"))
        text = (m.group("text")[: c.start()] if c else m.group("text")).rstrip()
        shown.append(f"{ln[: m.start('text')].replace('[x]', '[ ]').replace('[X]', '[ ]')}{text}" if text else "")
    return parse_board("\n".join(shown), warn=False)


# The answers that only keep a gate waiting (v2.4): they never lift, and an item whose Context names a gate
# is closed by one (SPEC *The board*).
WAITING_ONLY = ("keep waiting", "not yet")
ANSWERED_BY_RE = re.compile(r"^Answered by:(?P<value>.*)$")
ANSWERED_BY = ("owner", "any")  # who may give a lifting answer on the board; absent means owner


def waiting_only(label: object) -> bool:
    """Whether ``label`` is one of the two waiting-only answers, `Keep waiting` and `Not yet`, compared
    case-insensitively (v2.4)."""
    return isinstance(label, str) and " ".join(label.split()).rstrip(".").lower() in WAITING_ONLY


def _answered_by_line(content: str) -> tuple[int, str] | None:
    for n, ln in enumerate(content.splitlines(), start=1):
        if ANY_ITEM_RE.match(ln):
            return None
        m = ANSWERED_BY_RE.match(ln.rstrip())
        if m:
            return n, m.group("value")
    return None


def answered_by(content: str) -> str | None:
    """The board's `Answered by:` preamble line (v2.4), its value stripped as written, or None when it has
    none (which means `owner`). Read only above the board's first item; a value other than `owner` or
    `any` (in any case) is returned as it stands, for board_problems() to flag."""
    got = _answered_by_line(content)
    return got[1].strip() if got else None


def _item_text(item: BoardItem | str) -> str:
    if isinstance(item, BoardItem):
        return item.text
    m = ITEM_RE.match(item) or CLOSED_ITEM_RE.match(item)
    return m.group("text").strip() if m else item.strip()


def _item_gate(text: str) -> tuple[str | None, str | None]:
    """(the one entry ref, the one gate) an item's Context names, each None when it names none or more
    than one."""
    c = CONTEXT_RE.search(_gate_body(text))
    ctx = c.group("ctx") if c else ""
    refs = list(dict.fromkeys(ref_key(x.group(0)) for x in REF_TD_RE.finditer(ctx)))
    gates = list(dict.fromkeys(" ".join(g.group(0).split()) for g in CONTEXT_ANY_GATE_RE.finditer(ctx)))
    ref = next((x.group(0) for x in REF_TD_RE.finditer(ctx)), None) if len(refs) == 1 else None
    return ref, gates[0] if len(gates) == 1 else None


def _lifting(label: str, lifts: list[str] | None) -> bool:
    """Whether ``label`` lifts: one of the item's `Lifts:` (`Go` when it has none), compared
    case-insensitively, and never a waiting-only answer."""
    said = " ".join(label.split()).lower()
    return not waiting_only(label) and said in {" ".join(x.split()).lower() for x in (lifts or ["Go"])}


def closes(item: BoardItem | str, label: str, entries_after: Mapping[str, str]) -> bool:
    """Whether answering ``label`` on ``item`` (a line or a BoardItem) closes it in the same write (v2.4, SPEC
    *The board*): on an item whose Context names a gate, a waiting-only answer, and a lifting one when the
    Context names this repo's entry (a bare ``TD-n``) and nothing listed still carries the gate after the
    write — neither that entry nor any `Parts:` id, read from ``entries_after`` (id to text; an id it lacks
    carries nothing). Any other answer is a work order and leaves it open."""
    text = _item_text(item)
    ref, gate = _item_gate(text)
    if gate is None:
        return False
    if waiting_only(label):
        return True
    if ref is None or "#" in ref or not _lifting(label, parse_lifts(text)):
        return False
    by_num = {_num(k): v for k, v in entries_after.items() if _is_id(k)}
    return not any(_carried(by_num.get(_num(x)), gate) for x in [ref, *parse_parts(text)] if "#" not in x)


def detail_block(lines: list[str], lineno: int) -> list[str]:
    """The detail block under the item on 1-based line `lineno` — the run of lines right after it
    indented deeper than its `-`, ended by a blank line, a line no deeper than the item, or another
    item. Returned with the block's common indent removed, so its own nesting survives."""
    indent = len(lines[lineno - 1]) - len(lines[lineno - 1].lstrip())
    block = []
    for ln in lines[lineno:]:
        if not ln.strip() or len(ln) - len(ln.lstrip()) <= indent \
                or ITEM_RE.match(ln) or CLOSED_ITEM_RE.match(ln):
            break
        block.append(ln.rstrip())
    cut = min(len(b) - len(b.lstrip()) for b in block) if block else 0
    return [b[cut:] for b in block]


def parse_board(content: str, *, warn: bool = True) -> list[BoardItem]:
    """The board's open items, in order, with their fields parsed.

    An open item whose closed twin is also on the board (item_key equal) is closed: a merge that
    took both sides of a close keeps both lines, and the tick wins."""
    items = []
    closed = {item_key(ln) for ln in closed_items(content)}
    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        m = ITEM_RE.match(line)
        if not m or (closed and item_key(line) in closed):
            continue
        text = m.group("text").strip()
        due = None
        dm = DUE_RE.search(text)
        if dm:
            try:
                due = datetime.strptime(dm.group("due"), "%Y-%m-%d").date()  # noqa: DTZ007  # civil dates by design
            except ValueError:
                if warn:
                    logger.warning("Unparseable Due date in item, treating as undated: %s", text[:80])
        bad = None
        if due is None and (am := DUE_ATTEMPT_RE.search(text)):
            bad = am.group("raw")
        km = KIND_RE.match(text)
        kind = km.group("kind").lower() if km else None
        fyi_due = kind == "fyi" and (due is not None or bad is not None)
        if kind == "fyi":
            due, bad = None, None  # an fyi is never due
        items.append(BoardItem(text=text, due=due, line=lineno, answers=parse_answers(text),
                               default=parse_default(text), consequences=parse_consequences(text),
                               decided=parse_decided(text), decided_by=parse_decided_by(text), bad_due=bad,
                               kind=kind, fyi_due=fyi_due,
                               detail=detail_block(lines, lineno), hide_until=parse_hide_until(text),
                               lifts=parse_lifts(text), parts=parse_parts(text)))
    return items


def item_head(text: str) -> tuple[str | None, str | None]:
    """(session, host) from the item's `(session <name> on <host>)` head; None for what it lacks."""
    m = HEAD_RE.match(text)
    if not m:
        return None, None
    h = HEAD_HOST_RE.search(m.group("rest"))

    def named(v: str | None) -> str | None:
        return None if v is None or v.lower() == "n/a" else v  # the Format line's `or n/a`
    return named(m.group("session")), named(h.group(1) if h else None)


def item_refs(text: str) -> list[str]:
    """What `Context:` names, in order, each once: `TD-NNN` (or `<repo>#TD-NNN`), `PR #N`,
    `branch <name>`. TD ids and PR numbers are read wherever they stand (`PRs #12/#13` and
    `PR #12, #13` give both). A branch is best-effort: a part (`/` or `,` separated) that says
    `branch <name>`, or that is one bare token shaped like a branch name — it has a `-`, `_`
    or `/` and no file extension — so a word, a path to a file or a session id is not one."""
    m = CONTEXT_RE.search(text)
    if not m:
        return []
    ctx = m.group("ctx")
    found = [(x.start(), x.group(0)) for x in REF_TD_RE.finditer(ctx)]
    spans = [x.span() for x in REF_TD_RE.finditer(ctx)]
    for x in REF_PR_RE.finditer(ctx):
        spans.append(x.span())
        found += [(x.start() + n.start(), f"PR #{n.group(1)}") for n in re.finditer(r"#(\d+)", x.group(0))]
    for p in re.finditer(r"(?:(?!\s/\s|,).)+", ctx):
        if any(s < p.end() and e > p.start() for s, e in spans):
            continue
        b = REF_BRANCH_RE.match(p.group(0).strip(" /").rstrip("."))  # the scan leaves a separator's "/ " on a part
        if b and b.group("name").lower() != "n/a" and not REF_FILE_RE.search(b.group("name")) \
                and (b.group("said") or re.search(r"[-_/]", b.group("name"))):
            found.append((p.start(), f"branch {b.group('name')}"))
    refs: list[str] = []
    for _, ref in sorted(found):
        if ref_key(ref) not in {ref_key(r) for r in refs}:
            refs.append(ref)
    return refs


def due_tag(item: BoardItem, today: date) -> str:
    """4-way due tag: 'Nd overdue' / 'due today' / 'due YYYY-MM-DD' / 'no due date'."""
    days = item.overdue_days(today)
    if days is not None:
        return "due today" if days == 0 else f"{days}d overdue"
    if item.due is not None:
        return f"due {item.due.isoformat()}"
    return "no due date"


def item_notes(item: BoardItem, today: date) -> list[str]:
    """The item's notes on its `Hide until:` against ``today`` (v2.4), in rule order: they inform and never
    refuse, so no gate reads them. ``hide-spent``: a hide on an item not hidden today (its date has come, or the
    item is decided). ``hide-late``: a hidden item whose hide is after its readable `Due:`. At most one applies."""
    hide = item.hide_until
    if hide is None:
        return []
    if not item.hidden(today):
        if item.decided is not None:
            return [f"hide-spent: a decided item is never hidden, so Hide until: {hide.isoformat()} hides nothing"]
        return [f"hide-spent: Hide until: {hide.isoformat()} has come, so it hides nothing; a snooze replaces it"]
    if item.due is not None and hide > item.due:
        return [f"hide-late: Hide until: {hide.isoformat()} is after Due: {item.due.isoformat()}, "
                "so the item stays hidden past its deadline"]
    return []


def item_record(item: BoardItem, today: date) -> dict:
    """The item as one JSON-ready record — the board's API, and the fixtures' shape. The
    today-relative fields (``overdue_days``, ``due_tag``, ``hidden``, ``notes``) are computed against ``today``."""
    return {
        "line": item.line,
        "text": item.text,
        "due": item.due.isoformat() if item.due else None,
        "overdue_days": item.overdue_days(today),
        "due_tag": due_tag(item, today),
        "answers": item.answers,
        "default": item.default,
        "consequences": item.consequences,
        "decided": ({"text": item.decided[0], "date": item.decided[1].isoformat()}
                    if item.decided else None),
        "decided_by": item.decided_by,  # v2.3
        "waiting_on": item.waiting_on,
        "due_error": item.bad_due,
        "kind": item.kind,
        **dict(zip(("session", "host"), item_head(item.text))),
        "refs": item_refs(item.text),
        "replies": [{"by": by, "date": d, "text": t} for by, d, t in parse_replies(item.text)],
        "detail": item.detail,
        "hide_until": item.hide_until.isoformat() if item.hide_until else None,
        "hidden": item.hidden(today),
        "notes": item_notes(item, today),  # v2.4
        "lifts": item.lifts,  # v2.3
        "parts": item.parts,  # v2.3
    }


NEEDS_CLASSES = ("decided", "overdue", "due", "bad_due", "undated", "watch", "fyi")


def needs_you(board: str, today: date) -> list[tuple[BoardItem, str, int | None]]:
    """What needs the person (v2.3): every open item not hidden (a decided one never is), each with one class
    and a signed `days`, in one order. A decided item (`decided`, `days` the decision's age) is a session's
    work order and comes first, oldest decision first. The person's to-do follow by date: `overdue` (days
    past due, most first), `due` (0 on the due date, negative days until it; soonest first), then `bad_due`
    (a Due: the reader cannot read) and `undated`, as the board orders them. Then every `watch` item, ordered
    the same way and carrying its signed days (None when undated), then every `fyi` (never due: days None)."""
    def days(it: BoardItem) -> int | None:
        return (today - it.due).days if it.due else None

    def dated(group: list[BoardItem]) -> list[BoardItem]:
        on = sorted((it for it in group if it.due), key=lambda it: (-days(it), it.line))
        return on + [it for it in group if not it.due and it.bad_due] + \
            [it for it in group if not it.due and not it.bad_due]

    live = [it for it in parse_board(board, warn=False) if not it.hidden(today)]
    decided = sorted((it for it in live if it.decided), key=lambda it: (it.decided[1], it.line))
    rest = [it for it in live if not it.decided]
    out = [(it, "decided", (today - it.decided[1]).days) for it in decided]
    for it in dated([it for it in rest if it.todo]):
        d = days(it)
        cls = "overdue" if d is not None and d > 0 else "due" if d is not None else \
            "bad_due" if it.bad_due else "undated"
        out.append((it, cls, d))
    out += [(it, "watch", days(it)) for it in dated([it for it in rest if it.kind == "watch"])]
    out += [(it, "fyi", None) for it in rest if it.kind == "fyi"]
    return out


# ---------------------------------------------------------------------------------------------
# Edits: one item line rewritten, a new item composed, and the commit subject of each write
# ---------------------------------------------------------------------------------------------

EDIT_ACTIONS = ("snooze", "due", "done", "decide", "reply")  # `due` (v2.3) moves Due:; `snooze` hides until
FIELDS_RE = re.compile(r"\s+\b(?:Context|Parts|Due|Hide until|Answers|Lifts|Decided):")
FIELD_NAME_RE = re.compile(r"\b(?:Context|Parts|Hide until|Answers|Lifts|Decided|Closed):")  # in a reply, the reader would read the field
ANY_FIELD_RE = re.compile(r"\b(Context|Parts|Due|Hide until|Answers|Lifts|Decided|Closed):")
SESSION_RE = re.compile(r"\(session ([^\s,)]+)")  # as written: a backticked name keeps its backticks
EDIT_HEAD_CHARS = 60


class Refused(Exception):
    """The edit was not made, and why, in words a person reads."""


def edit_head(text: str) -> str:
    """What the item is about, for a commit subject: after its `date (session …) — ` prefix,
    before its `Context:`/`Due:`/`Answers:`/`Decided:` fields, markdown bold dropped, clipped."""
    span = reply_span(text)  # a reply's words are the person's: never part of the head
    text = text[: span[0]] if span else text
    what = text.split(" — ", 1)[1] if " — " in text else text
    what = FIELDS_RE.split(what, 1)[0].replace("*", "").strip() or text
    return what if len(what) <= EDIT_HEAD_CHARS else what[: EDIT_HEAD_CHARS - 1] + "…"


def bold_head(text: str) -> str | None:
    """The item's bold head — its first `**…**` run, whitespace collapsed — or None. A reply's
    words are the person's, never the head; the fallback and any clipping are the caller's."""
    span = reply_span(text)
    if span:
        text = text[: span[0]] + text[span[1] :]
    m = BOLD_RE.search(text)
    head = " ".join(m.group("bold").split()) if m else ""
    return head or None


def is_not_right_form(answer: str) -> bool:
    """Whether an offered answer is the live look's `Not right: <what>` form — `Not right:` alone
    or with one `<…>` placeholder, whitespace collapsed — rather than a complete answer."""
    return bool(NOT_RIGHT_FORM_RE.fullmatch(" ".join(str(answer).split())))


def fill_not_right(said: str, offered: list[str]) -> str | None:
    """`said`, whitespace collapsed, when it fills a `Not right: <what>` form among `offered`;
    None when no form is offered or `said` does not start `Not right:`. Refused when it says
    nothing past the form — `Not right:` alone, or the form as offered."""
    said = " ".join(str(said or "").split())
    if not said.startswith(NOT_RIGHT) or not any(is_not_right_form(a) for a in offered):
        return None
    if is_not_right_form(said):
        raise Refused("Not right needs its words: say what is off")
    return said


def _sentence(body: str) -> str:
    """`body` ending a sentence, so a field written after it starts one (the reader's rule)."""
    head = body.rstrip()
    return head if head.endswith((".", "?", "!")) else f"{head}."


def _trailing_field_start(body: str, after_due: bool = False) -> int | None:
    """Where the item's Answers:/Decided: trailer begins, for inserting a Due: before it — or,
    `after_due`, a reply: then only as the reader finds the fields, after the Due:."""
    due = DUE_RE.search(body) if after_due else None
    off = due.end() if due else 0
    starts = [m.start() for m in (ANSWERS_RE.search(body, off), DECIDED_RE.search(body, off)) if m]
    return min(starts) if starts else None


def edit_line(body: str, action: str, *, to: date | None = None, answer: str | None = None,
              why: str | None = None, reply: str | None = None, by: str | None = None,
              today: date | None = None, close: bool = False) -> str:
    """The open item line `body` (no line ending) after `action` — snooze (hidden until `to`), due (its
    Due: moved to `to`), done (with
    `why`), decide (`answer`; with `close`, v2.4, also closed: `Closed: <today> — kept waiting.` for a
    waiting-only answer, `— lifted.` for a lifting one, on an item whose Context names a gate — closes()
    says when), reply (`reply`, by `by`); raises Refused. Every edit is re-parsed
    and refused if the reader would not read back what was meant."""
    today = today or date.today()  # noqa: DTZ011  # a civil date, as the readers use
    if ITEM_RE.match(body) is None:
        raise Refused("the line is not an open item")
    if close and action != "decide":
        raise Refused("only a decide closes the item it answers (close)")
    if action == "done":
        why = " ".join((why or "").split()).rstrip(".?!")  # the field supplies its one period
        fld = f"Closed: {today.isoformat()}{f' — {why}' if why else ''}."
        head = re.sub(r"^(\s*-\s*)\[ \]", r"\1[x]", body, count=1).rstrip()
        new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} {fld}"
        m = CLOSED_RE.search(new)
        if ITEM_RE.match(new) or not CLOSED_ITEM_RE.match(new) or not m \
                or m.group("date") != today.isoformat() or item_key(new) != item_key(body):
            raise Refused("the reader would not read the item back as closed today with its "
                          "text unchanged")
        return new
    text = ITEM_RE.match(body).group("text")
    if action in ("snooze", "due") and to is None:
        raise Refused(f"a {action} needs its date")
    if action == "snooze":  # v2.3: hide the item until `to`; its Due:, the real deadline, stays
        h = _hide_match(body)
        if h:
            new = body[: h.start("date")] + to.isoformat() + body[h.end("date"):]
        else:
            d = DUE_RE.search(body)
            if d:
                at = d.end()
                rest = body[at + 1:] if body[at:at + 1] == "." else body[at:]  # the Due: gets its period
                new = f"{body[:at]}. Hide until: {to.isoformat()}.{rest}"
            else:
                starts = [x for x in ((reply_span(body) or (None,))[0], _trailing_field_start(body)) if x is not None]
                at = min(starts) if starts else len(body)
                head, rest = body[:at].rstrip(), body[at:]
                if rest and not rest.startswith(" "):
                    rest = " " + rest
                new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} Hide until: {to.isoformat()}.{rest}"
        was, got = parse_board(body, warn=False), parse_board(new, warn=False)
        if not got or not was or got[0].hide_until != to or got[0].due != was[0].due \
                or (got[0].answers, got[0].consequences, got[0].default, got[0].decided, got[0].decided_by, got[0].kind,
                    got[0].lifts, got[0].parts) \
                != (was[0].answers, was[0].consequences, was[0].default, was[0].decided, was[0].decided_by, was[0].kind,
                    was[0].lifts, was[0].parts) \
                or parse_replies(new) != parse_replies(body) or item_refs(new) != item_refs(body) \
                or item_key(new) != item_key(body):
            raise Refused(f"after the edit the reader does not read Hide until: {to.isoformat()} "
                          "with the item's other fields unchanged")
        return new
    if action == "due":  # the real deadline moves (what snooze did before v2.3)
        m = DUE_RE.search(body)
        if m:
            new = body[: m.start("due")] + to.isoformat() + body[m.end("due"):]
        else:
            at = _trailing_field_start(body)
            span = reply_span(body)  # a reply is read only after the Due:, so the date goes ahead of it
            h = _hide_match(body)  # and Due: stands ahead of a Hide until:
            if h:
                new = f"{body[: h.start()].rstrip()} Due: {to.isoformat()}. {body[h.start():]}"
            elif span:
                head = body[: span[0]].rstrip()
                new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} Due: {to.isoformat()}.{body[span[0]:]}"
            elif at is None:
                head = body.rstrip()
                new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} Due: {to.isoformat()}."
            else:
                new = f"{body[:at].rstrip()} Due: {to.isoformat()}. {body[at:]}"
        got = parse_board(new, warn=False)
        if not got or got[0].due != to or got[0].answers != parse_answers(text) \
                or got[0].consequences != parse_consequences(text) or got[0].default != parse_default(text) \
                or got[0].decided != parse_decided(text) or got[0].decided_by != parse_decided_by(text) \
                or got[0].hide_until != parse_hide_until(text) or got[0].lifts != parse_lifts(text) \
                or got[0].parts != parse_parts(text):
            raise Refused(f"after the edit the reader does not read Due: {to.isoformat()} "
                          "with the item's other fields unchanged")
        return new
    if action == "decide":
        answer = " ".join((answer or "").split())
        if not answer:
            raise Refused("the answer is empty")
        if DECIDED_BY_RE.match(answer):
            raise Refused("an answer may not end in `(by <name>)` — the reader would read it as who answered; "
                          "say it in other words")
        by = " ".join((by or "").split()) or None
        if by is not None and not is_person(by):
            raise Refused(f"who answered, {by!r}, is not a person's name (letters, digits, `_`, `-`, dot-separated)")
        fld = f"Decided: {answer}{f' (by {by})' if by else ''} ({today.isoformat()})."
        if parse_decided(text) is not None:
            m = DECIDED_RE.search(body)
            new = f"{body[: m.start()].rstrip()} {fld}"
        else:
            # the field starts a sentence (the reader's rule): end an unpunctuated item first
            head = body.rstrip()
            new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} {fld}"
        if close:  # v2.4: the answer closes the item in the same write
            if _item_gate(text)[1] is None:
                raise Refused("only an item whose Context names a gate is closed by its answer")
            reason = "kept waiting" if waiting_only(answer) else "lifted" if _lifting(answer, parse_lifts(text)) else None
            if reason is None:
                raise Refused(f"{answer!r} neither lifts nor only keeps waiting — a work order stays open")
            closed = re.sub(r"^(\s*-\s*)\[ \]", r"\1[x]", new, count=1) + f" Closed: {today.isoformat()} — {reason}."
            got = parse_closed_items(closed)
            m = CLOSED_RE.search(closed)
            was = parse_board(body, warn=False)[0]
            if ITEM_RE.match(closed) or len(got) != 1 or not m or m.group(0) != f"Closed: {today.isoformat()} — {reason}." \
                    or got[0].decided != (answer, today) or got[0].decided_by != by \
                    or (got[0].answers, got[0].lifts, got[0].parts, got[0].consequences, got[0].default, got[0].due) \
                    != (was.answers, was.lifts, was.parts, was.consequences, was.default, was.due) \
                    or item_key(closed) != item_key(body):
                raise Refused(f"the reader would not read back 'Decided: {answer}' and the item closed "
                              f"{reason} today, with its other fields unchanged — rephrase the answer")
            return closed
        got = parse_board(new, warn=False)
        if not got or got[0].decided != (answer, today) or got[0].decided_by != by \
                or got[0].answers != parse_answers(text) or got[0].lifts != parse_lifts(text) \
                or got[0].parts != parse_parts(text) \
                or got[0].consequences != parse_consequences(text) or got[0].default != parse_default(text) \
                or got[0].due != parse_board(body, warn=False)[0].due:
            raise Refused(f"the reader would not read back 'Decided: {answer}' with the item's "
                          "other fields unchanged — rephrase the answer")
        return new
    if action == "reply":
        words, by = " ".join((reply or "").split()), " ".join((by or "").split())
        if not words:
            raise Refused("the reply is empty — a reply needs its words")
        if FIELD_NAME_RE.search(words):
            raise Refused("a reply may not carry Context:, Parts:, Hide until:, Answers:, Lifts:, Decided: or Closed: — the reader "
                          "would read it as the field; say it in other words")
        if (DUE_RE.search(words) or DUE_ATTEMPT_RE.search(words)) and not DUE_RE.search(body):
            raise Refused("this item has no Due: date, so a reply may not carry one — the "
                          "reader would take it for the item's; snooze sets its date")
        tail = f" — {by}, {today.isoformat()}: {words}"
        at = _trailing_field_start(body, after_due=True)
        if at is None:
            new = body.rstrip() + tail
        else:
            # ahead of the fields the reader anchors at the line's end: a reply never
            # un-decides an item, and never becomes part of its last answer
            head = body[:at].rstrip() + tail
            new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} {body[at:]}"
        was, got = parse_board(body, warn=False)[0], parse_board(new, warn=False)
        replies = parse_replies(new)
        if not got or (got[0].due, got[0].answers, got[0].consequences, got[0].decided, got[0].decided_by,
                       got[0].lifts, got[0].parts) \
                != (was.due, was.answers, was.consequences, was.decided, was.decided_by, was.lifts, was.parts) \
                or parse_default(got[0].text) != parse_default(text) \
                or item_refs(got[0].text) != item_refs(text) \
                or replies[:-1] != parse_replies(body) or not replies \
                or replies[-1][:2] != (by, today.isoformat()) or replies[-1][2].rstrip(".") != words.rstrip(".") \
                or item_key(new) != item_key(body):
            raise Refused("the reader would not read the reply back, by that name, with the "
                          "item's other fields unchanged — rephrase it (or its name)")
        return new
    raise Refused(f"unknown action {action}")


# The writer's rules for a new item (v2.3). The reader reads whatever a line carries; these say
# what a writer writes. An item with no kind takes act's rule.
DETAIL_PARTS = ("context", "question", "caveats", "recommended")  # a detail block's parts, in order
DETAIL_KEYS = (*DETAIL_PARTS, "otherwise")  # `otherwise` is written on the Recommended bullet
DECIDE_NEEDS = ("context", "question", "recommended")
WRITER_FIELD_RE = re.compile(r"\b(?:Context|Parts|Hide until|Answers|Lifts|Decided|Closed):|\b(?i:due):")  # Due: in any case, as DUE_RE
DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HEAD_NAME_BAD_RE = re.compile(r"[\s`,;)]")  # what would end a head's name early, as HEAD_RE reads it


def _item_words(value: object, what: str) -> str:
    """`value` with its whitespace collapsed; refused when empty, more than one line, or carrying
    a field's name (the reader would read it as the field)."""
    raw = str(value if value is not None else "").strip()
    if len(raw.splitlines()) > 1:
        raise Refused(f"{what} is one line: put the rest on that line")
    words = " ".join(raw.split())
    if not words:
        raise Refused(f"{what} is empty")
    if WRITER_FIELD_RE.search(words):
        raise Refused(f"{what} may not carry Context:, Parts:, Due:, Hide until:, Answers:, Lifts:, Decided: or Closed: — the "
                      "reader would read it as the field; say it in other words")
    return words


def _civil_date(value: object, what: str) -> str:
    """`value` when it is a date written YYYY-MM-DD; refused otherwise."""
    s = str(value)
    if DATE_ONLY_RE.fullmatch(s):
        try:
            date.fromisoformat(s)
            return s
        except ValueError:
            pass
    raise Refused(f"{what} as YYYY-MM-DD, not {value!r}")


def _detail_lines(detail: Mapping, label: str | None) -> list[str]:
    """The detail block's lines from `detail`'s parts: each part a bullet two spaces in, its
    further strings nested bullets four in. `label` opens Recommended (a decide's default)."""
    if not isinstance(detail, Mapping):
        raise Refused("detail is a mapping of the block's parts")
    unknown = sorted(str(k) for k in detail if k not in DETAIL_KEYS)
    if unknown:
        raise Refused(f"a detail block's parts are {', '.join(DETAIL_KEYS)}, not {', '.join(unknown)}")
    if not isinstance(detail.get("otherwise", ""), str):
        raise Refused("the detail block's otherwise is a string")
    if "otherwise" in detail and "recommended" not in detail:
        raise Refused("otherwise is written on the Recommended bullet: give recommended too")
    out = []
    for part in DETAIL_PARTS:
        if part not in detail:
            continue
        value = detail[part]
        if not isinstance(value, (str, list, tuple)) or not all(isinstance(v, str) for v in value):
            raise Refused(f"the detail block's {part} is a string, or a list of strings")
        values = [value] if isinstance(value, str) else list(value)
        if not values:
            raise Refused(f"the detail block's {part} is empty")
        words = _sentence(_item_words(values[0], f"the detail block's {part}"))
        if part == "recommended":
            if label is not None:
                words = f"{label}{CONSEQUENCE_SEP}{words}"
            if "otherwise" in detail:
                other = _item_words(detail["otherwise"], "the detail block's otherwise")
                words += f" **Otherwise:** {_sentence(other)}"
        out.append(f"  - **{part.capitalize()}:** {words}")
        out += [f"    - {_item_words(v, f'a nested bullet under {part}')}" for v in values[1:]]
    return out


def _answer_parts(answers: object) -> list[tuple[str, str]]:
    """Each offered answer as (label, consequence), whitespace collapsed; refused where the reader
    would read it otherwise."""
    if not isinstance(answers, (list, tuple)) or not all(isinstance(a, str) for a in answers):
        raise Refused("answers is a list of strings, one answer each")
    parts = []
    for a in answers:
        said = _item_words(a, "an answer")
        if REPLY_TAIL_RE.search(said):
            raise Refused("an answer's consequence may not read as a reply (` — <name>, <date>: `) — "
                          "say it in other words")
        label, sep, cons = said.partition(CONSEQUENCE_SEP)
        label, cons = label.strip(), cons.strip()
        if not label or (sep and not cons):
            raise Refused(f"an answer is `<label>` or `<label> — <consequence>`, not {said!r}")
        if DEFAULT_MARK_RE.search(label) or DEFAULT_MARK_RE.search(cons):
            raise Refused("an answer may not carry ` (default)`: the mark is the writer's — give default")
        parts.append((label, cons))
    labels = [p[0] for p in parts]
    if len(set(labels)) != len(labels):
        raise Refused("two answers have the same label: each answer needs its own")
    return parts


def _a_kind(kind: str | None) -> str:
    return "an item with no kind" if kind is None else f"{'an' if kind[0] in 'aeiou' else 'a'} {kind}"


def item_line(text: str, due: str | None, today: str, session: str | None, host: str | None,
              context: str | None, *, kind: str | None = None, answers: list[str] | None = None,
              default: int | None = None, detail: Mapping | None = None, hide_until: str | None = None,
              lifts: list[str] | None = None) -> str:
    """A new item, in the board's own format, with its line ending and its detail block —
    `- [ ] [<kind> ]<today> (<head>) — <text> Context: <context>.[ Due: <due>.][ Hide until: <date>.][ Answers: <answers>.]
    [ Lifts: <labels>.]`, `lifts` (v2.3, a decide's) naming which of its answers lift, written unless it is `Go` alone,
    the head ``session `<name>` on <host>``, ``session `<name>` `` or `n/a`. What each kind takes
    (a decide its answers and detail block, a look the fixed pair, an fyi no Due:) is SPEC
    *Edits*; refused, with why, for what the writer does not write and for any result the
    reader would not read back as exactly the item meant."""
    if kind is not None and kind not in KINDS:
        raise Refused(f"a kind is one of {', '.join(KINDS)}, not {kind!r}")
    words = _sentence(_item_words(text, "a board line's text"))
    today = _civil_date(today, "today is written")
    if kind == "fyi":
        if due is not None:
            raise Refused("an fyi carries no Due: date — give due as None")
    elif due is None:
        raise Refused(f"{_a_kind(kind)} needs its Due date")
    else:
        due = _civil_date(due, "a board line needs a Due date")
    if host is not None and session is None:
        raise Refused("a host is written only with its session: give the session too")
    for what, name in (("session", session), ("host", host)):
        if name is not None and (not str(name) or HEAD_NAME_BAD_RE.search(str(name))):
            raise Refused(f"a {what} name holds no whitespace and none of ` , ; ) — not {name!r}")
    ctx = _item_words(context, "the context").removesuffix(".") if str(context or "").strip() else ""
    ctx = ctx or "none"

    offered = _answer_parts(answers) if answers is not None else []
    if kind == "decide":
        if len(offered) < 2:
            raise Refused("a decide offers two or more answers")
        if default is not None and (type(default) is not int or not 0 <= default < len(offered)):
            raise Refused(f"default is the index of one of the {len(offered)} answers, not {default!r}")
        missing = [p for p in DECIDE_NEEDS if p not in (detail or {})]
        if missing:
            raise Refused(f"a decide needs its detail block's {', '.join(missing)}")
    elif kind == "look":
        if answers is not None:
            raise Refused("a look's answers are the writer's (Works | Not right: <what>): give none")
        if default is not None and (type(default) is not int or default != 0):
            raise Refused("a look's default is 0 (Works), or None")
        offered = [(a, "") for a in LIVE_LOOK_ANSWERS]
    else:
        if answers is not None:
            raise Refused(f"{_a_kind(kind)} carries no answers: a question with answers is a decide")
        if default is not None:
            raise Refused("default marks one of a decide's or a look's answers: there are none")

    lifted: list[str] = []
    if lifts is not None:
        if kind != "decide":
            raise Refused("only a decide names the answers that lift (lifts)")
        by_label = {lbl.lower(): lbl for lbl, _ in offered}
        for x in lifts:
            name = " ".join(str(x or "").split())
            if name.lower() not in by_label:
                raise Refused(f"a lifting answer is one of the item's answers, not {name!r}")
            if by_label[name.lower()] in lifted:
                raise Refused(f"{name!r} is named twice among the lifting answers")
            lifted.append(by_label[name.lower()])
        if not lifted:
            raise Refused("lifts names one or more of the answers, or is None (`Go`)")
        if [x.lower() for x in lifted] == ["go"]:
            lifted = []  # `Go` alone is what no Lifts: means: it is not written
    if kind == "decide" and (lifted or lifts is not None or CONTEXT_ANY_GATE_RE.search(ctx)) \
            and len({ref_key(x.group(0)) for x in REF_TD_RE.finditer(ctx)}) != 1:
        raise Refused("a decide that lifts a gate names exactly one entry in its context")
    waits = [x for x in lifted if waiting_only(x)]
    if waits:
        raise Refused(f"{waits[0]!r} only keeps the gate waiting — it never lifts (v2.4)")
    label = offered[default][0] if offered and default is not None else None
    lines = _detail_lines(detail, label if kind == "decide" else None) if detail is not None else []

    def written(lbl: str, cons: str, marked: bool) -> str:
        return (lbl.replace("|", "\\|") + (" (default)" if marked else "")
                + (CONSEQUENCE_SEP + cons.replace("|", "\\|") if cons else ""))
    head = f"session `{session}`{f' on {host}' if host is not None else ''}" if session is not None else "n/a"
    body = f"{f'{kind} ' if kind else ''}{today} ({head}) — {words} Context: {ctx}."
    if due is not None:
        body += f" Due: {due}."
    if hide_until is not None:
        hide_until = _civil_date(hide_until, "hide_until")
        body += f" Hide until: {hide_until}."
    if offered:
        body += f" Answers: {' | '.join(written(lbl, c, i == default) for i, (lbl, c) in enumerate(offered))}."
    if lifted:
        body += f" Lifts: {' | '.join(x.replace('|', chr(92) + '|') for x in lifted)}."
    new = "".join(f"{ln}\n" for ln in [f"- [ ] {body}", *lines])

    got = parse_board(new, warn=False)
    meant = (kind, due, [lbl for lbl, _ in offered], [c for _, c in offered], label,
             (session, host), item_refs(f"Context: {ctx}."), [ln[2:] for ln in lines])
    if len(got) != 1 or closed_items(new) or sum(bool(ANY_ITEM_RE.match(ln)) for ln in new.splitlines()) != 1 \
            or (got[0].kind, got[0].due and got[0].due.isoformat(), got[0].answers, got[0].consequences,
                got[0].default, item_head(got[0].text), item_refs(got[0].text), got[0].detail) != meant \
            or got[0].decided is not None or parse_replies(got[0].text) or got[0].fyi_due or got[0].bad_due \
            or (got[0].hide_until and got[0].hide_until.isoformat()) != hide_until \
            or got[0].lifts != (lifted or None) or got[0].parts:
        raise Refused("the board's reader would not read this item back as meant — rephrase it")
    return new


def decided_line(title: str, ref: str, answers: list[str], default: int | None, words: str, today: str,
                 by: str | None = None) -> str:
    """A new item already decided, for a person's answer given elsewhere (on a ledger entry):
    `- [ ] decide <today> (person) — <title>. Context: <ref>. Due: <today>. Answers: a | b (default).
    Decided: <words> [(by <by>)] (<today>).` with its line ending; `by`, who answered (v2.3), is a person's
    name. An answer may carry its consequence,
    `<label> — <consequence>`; the mark goes on the label. Refused for empty words, words
    carrying a field's name or ending in `(by …)`, a `by` outside the person grammar, or a line the reader
    would not read back."""
    head = ANY_FIELD_RE.sub(r"\1", " ".join(str(title or "").split())).rstrip(".") or ref
    said = " ".join(str(words or "").split())
    if not said:
        raise Refused("a decision needs its words: one of the entry's answers, or what you typed")
    if FIELD_NAME_RE.search(said):
        raise Refused("an answer may not carry Context:, Parts:, Hide until:, Answers:, Lifts:, Decided: or Closed: — say it in other words")
    if DECIDED_BY_RE.match(said):
        raise Refused("an answer may not end in `(by <name>)` — the reader would read it as who answered; "
                      "say it in other words")
    by = " ".join(str(by or "").split()) or None
    if by is not None and not is_person(by):
        raise Refused(f"who answered, {by!r}, is not a person's name (letters, digits, `_`, `-`, dot-separated)")
    if any(REPLY_TAIL_RE.search(" ".join(str(a).split())) for a in answers or ()):
        raise Refused("an answer's consequence may not read as a reply (` — <name>, <date>: `) — say it in other words")
    def opt(a: str, marked: bool) -> str:
        label, cons, _ = split_answer(ANY_FIELD_RE.sub(r"\1", " ".join(str(a).split())).replace("|", "\\|"))
        return label + (" (default)" if marked else "") + (CONSEQUENCE_SEP + cons if cons else "")
    opts = [opt(a, i == default) for i, a in enumerate(answers or ()) if str(a).strip()]
    tail = f" Answers: {' | '.join(opts)}." if opts else ""
    body = f"decide {today} (person) — {_sentence(head)} Context: {ref}. Due: {today}.{tail} Decided: {said}{f' (by {by})' if by else ''} ({today})."
    d, c = DECIDED_RE.search(body), CONTEXT_RE.search(body)
    got = _decided_parts(body)
    if d is None or got is None or got[:2] != (said, by):
        raise Refused(f"the board's reader would not read back 'Decided: {said}': say it in other words")
    if c is None or c.group("ctx").rstrip(".") != ref:
        raise Refused(f"the board's reader would not read back 'Context: {ref}' on this entry's line")
    return f"- [ ] {body}\n"


# The item gate (v2.3): the form the writers write, said of one line (item_problem), a line
# rewritten into it where its item key allows (canonical_item), and a board's new lines judged
# (board_problems). Each problem opens with its rule's tag: open, kind, head, text, context, due,
# answers, extra.
GATE_HEAD_RE = re.compile(r"(?P<date>\S+) \((?P<head>[^()]*)\) — ")
GATE_HEAD_FORM_RE = re.compile(r"session `(?P<session>[^\s`,;)]+)`(?: on (?P<host>[^\s`,;)]+))?|n/a|person")
GATE_FIELD_RE = re.compile(r"\b(?P<name>Context|Parts|Hide until|Answers|Lifts|Decided|Closed|(?i:due)):")
GATE_HIDE_RE = re.compile(r"Hide until:[ \t]*(?P<date>[^\s.]*)(?P<period>\.?)(?P<more>.*)")
GATE_DUE_RE = re.compile(r"(?P<name>(?i:due)):[ \t]*(?P<date>[^\s.]*)(?P<period>\.?)(?P<more>.*)")
GATE_DUE_ALONE_RE = re.compile(r"(?i:due):\s*\d{4}-\d{2}-\d{2}\.?")
LOOK_ANSWERS = ("Works | Not right: <what>", "Works (default) | Not right: <what>")


def _gate_body(text: str) -> str:
    """An item's text after its `- [ ] `, with its reply tails and its `Decided:` field taken out:
    a reply's words and a Decided: text are the person's, and hold no field of the line's."""
    span = reply_span(text)
    if span:
        text = text[: span[0]] + text[span[1]:]
    trailer = _trailer(text)
    d = DECIDED_RE.search(trailer)
    if d:
        text = text[: len(text) - len(trailer) + d.start()].rstrip()
    return text


def item_problem(line: str) -> str | None:
    """Why `line` is not an open item line as the writers write it (SPEC *The form the writers
    write*), or None. Each problem opens with its rule's tag; several are joined by `; `."""
    line = line.removesuffix("\n").removesuffix("\r")
    m = ITEM_RE.match(line)
    if m is None:
        return "open: not an open item"
    problems: list[str] = []
    if not line.startswith("- [ ] ") or line[6:7].isspace():  # a tab or any other whitespace after the box too
        problems.append("open: an item line opens `- [ ] ` at column 0, single-spaced")
    if line != line.rstrip():
        problems.append("extra: whitespace at the line's end")
    text = m.group("text").rstrip()
    decided = parse_decided(text) is not None
    body = _gate_body(text)

    kind, rest, bad_kind = None, body, False
    first = body.split(" ", 1)[0]
    if re.fullmatch(r"[A-Za-z]+", first):  # a word before the date: a kind, or a fault
        if first in KINDS:
            kind = first
        else:
            problems.append(f"kind: {first!r} is not a kind: one of {', '.join(KINDS)}, in lower case")
            bad_kind = True  # its answers are judged by no kind's rule
        rest = body[len(first):].lstrip(" ")
    h = GATE_HEAD_RE.match(rest)
    if h is None:
        problems.append("head: a date then `(session `<name>` on <host>)`, `(session `<name>`)`, `(n/a)` "
                        "or `(person)`, then ` — `")
        cut = rest.find(" — ")
        if cut < 0:
            return "; ".join(problems)
        date_s, head, words = None, None, rest[cut + 3:]
    else:
        date_s, head, words = h.group("date"), h.group("head"), rest[h.end():]
        try:
            _civil_date(date_s, "")
        except Refused:
            problems.append(f"head: {date_s!r} is not a date as YYYY-MM-DD")
        if not GATE_HEAD_FORM_RE.fullmatch(head):
            problems.append(f"head: `({head})` is not `(session `<name>` on <host>)`, `(session `<name>`)`, "
                            "`(n/a)` or `(person)`")
        elif head == "person" and not decided:
            problems.append("head: `(person)` stands only on a decided line")

    fields = list(GATE_FIELD_RE.finditer(words))
    named = [(f, "Due" if f.group("name").lower() == "due" else f.group("name")) for f in fields]
    lowered = [n for _, n in named]
    if "Context" not in lowered:
        problems.append("context: no `Context:`")
    elif lowered.count("Context") > 1:
        problems.append("context: `Context:` stands more than once")
    # The text runs to Context:, or with none to the first field; a field inside it is the text's fault,
    # but a lone `Due: <date>.` right before Context: is a Due: out of its place.
    text_end = fields[lowered.index("Context")].start() if "Context" in lowered else \
        (fields[0].start() if fields else len(words))
    item_text, kept, moved = words[:text_end], [], False
    for f, n in named:
        if f.start() >= text_end:
            kept.append((f, n))
        elif n == "Due" and "Context" in lowered and not item_text[: f.start()].strip() == "" \
                and GATE_DUE_ALONE_RE.fullmatch(words[f.start(): text_end].strip()):
            problems.append("due: `Due:` stands before `Context:`; it follows Context")
            item_text, moved = words[: f.start()], True
            kept.append((f, n))
        else:
            problems.append(f"text: names a field ({f.group('name')}:): say it in other words")
    if not item_text.strip():
        problems.append("text: empty")
    elif not item_text.rstrip().endswith((".", "?", "!")):
        problems.append("text: does not end a sentence (`.`, `?` or `!`)")
    kept.sort(key=lambda fn: fn[0].start())
    order = [n for _, n in kept]
    segs: dict[str, list[str]] = {}
    for i, (f, n) in enumerate(kept):
        stop = kept[i + 1][0].start() if i + 1 < len(kept) else len(words)
        if n == "Due" and moved and stop > text_end and f.start() < text_end:
            stop = text_end
        segs.setdefault(n, []).append(words[f.start(): stop].strip())
    ctx = None
    if lowered.count("Context") == 1:
        c = re.fullmatch(r"Context:\s*(?P<words>.*)", segs["Context"][0])
        ctx = c.group("words")
        if not ctx.rstrip("."):
            problems.append("context: empty")
        elif not ctx.endswith("."):
            problems.append("context: does not end with its period")
    dues = segs.get("Due", [])
    due_s = None
    if kind == "fyi":
        if dues:
            problems.append("due: an fyi carries no `Due:`")
    elif not dues:
        problems.append("due: no `Due:` (every kind but fyi carries one)")
    elif len(dues) > 1:
        problems.append("due: `Due:` stands more than once")
    else:
        d = GATE_DUE_RE.fullmatch(dues[0])
        due_s = d.group("date")
        if d.group("name") != "Due":
            problems.append(f"due: spelled {d.group('name')!r}, not `Due:`")
        try:
            _civil_date(due_s, "")
        except Refused:
            problems.append(f"due: {due_s!r} is not a date as YYYY-MM-DD")
        if not d.group("period"):
            problems.append("due: no period after its date")
        if d.group("more").strip():
            problems.append(f"extra: {d.group('more').strip()!r} after `Due:`")
        i = order.index("Due")
        if not moved and i > 0 and order[i - 1] not in ("Context", "Parts"):
            problems.append(f"due: `Due:` stands after `{order[i - 1]}:`; it follows Context")
    hides = segs.get("Hide until", [])
    hide_s = None
    if len(hides) > 1:
        problems.append("hide: `Hide until:` stands more than once")
    elif hides:
        hd = GATE_HIDE_RE.fullmatch(hides[0])
        hide_s = hd.group("date")
        try:
            _civil_date(hide_s, "")
        except Refused:
            problems.append(f"hide: {hide_s!r} is not a date as YYYY-MM-DD")
        if not hd.group("period"):
            problems.append("hide: no period after its date")
        if hd.group("more").strip():
            problems.append(f"extra: {hd.group('more').strip()!r} after `Hide until:`")
        i = order.index("Hide until")
        after = "Due" if "Due" in order else "Parts" if "Parts" in order else "Context"
        if i == 0 or order[i - 1] != after:
            problems.append(f"hide: `Hide until:` follows {after}")
    parts = segs.get("Parts", [])
    parts_s = None
    if len(parts) > 1:
        problems.append("parts: `Parts:` stands more than once")
    elif parts:
        pm = re.fullmatch(r"Parts:\s*(?P<ids>.*?)(?P<period>\.?)", parts[0])
        parts_s = pm.group("ids")
        ids = parts_s.split(", ")
        if kind != "decide":
            problems.append(f"parts: {_a_kind(kind)} carries no `Parts:`: only a decide asks about a parent's parts")
        if not all(ID_ITEM_RE.fullmatch(x) or XREPO_ITEM_RE.fullmatch(x) for x in ids):
            problems.append("parts: `Parts:` lists entry ids, `TD-n` or `<repo>#TD-n`, separated by `, `")
        elif len({ref_key(x) for x in ids}) != len(ids):  # a repo in any case is one repo
            problems.append("parts: an id stands twice")
        if not pm.group("period"):
            problems.append("parts: no period after its ids")
        i = order.index("Parts")
        if i == 0 or order[i - 1] != "Context":
            problems.append("parts: `Parts:` follows Context")
    answers = segs.get("Answers", [])
    raw = None
    if len(answers) > 1:
        problems.append("answers: `Answers:` stands more than once")
    elif answers:
        a = re.fullmatch(r"Answers:\s*(?P<raw>.*?)(?P<period>\.?)", answers[0])
        raw = a.group("raw")
        if not a.group("period"):
            problems.append("answers: no period after its answers")
        last = [n for n in order if n != "Lifts"][-1]
        if last not in ("Answers", "Due"):  # a Due: after Answers: is the due rule's
            problems.append(f"answers: `{last}:` stands after `Answers:`")
    lifts_seg = segs.get("Lifts", [])
    lifts_s = None
    if len(lifts_seg) > 1:
        problems.append("lifts: `Lifts:` stands more than once")
    elif lifts_seg:
        lm = re.fullmatch(r"Lifts:\s*(?P<raw>.*?)(?P<period>\.?)", lifts_seg[0])
        lifts_s = lm.group("raw")
        named_lifts = [x.replace("\\|", "|").strip() for x in ANSWER_SPLIT_RE.split(lifts_s)] if lifts_s else []
        offered_labels = {split_answer(x.replace("\\|", "|").strip())[0].lower()
                          for x in (ANSWER_SPLIT_RE.split(raw) if raw else [])}
        if kind != "decide":
            problems.append(f"lifts: {_a_kind(kind)} carries no `Lifts:`: only a decide's answer lifts")
        if not named_lifts or not all(named_lifts):
            problems.append("lifts: `Lifts:` names one or more of the answers")
        elif [x.lower() for x in named_lifts] == ["go"]:
            problems.append("lifts: `Lifts: Go.` is what no `Lifts:` means: leave it out")
        else:
            off = [x for x in named_lifts if x.lower() not in offered_labels]
            if off:
                problems.append(f"lifts: not one of the item's answers: {', '.join(off)}")
            if len({x.lower() for x in named_lifts}) != len(named_lifts):
                problems.append("lifts: an answer stands twice")
            waits = [x for x in named_lifts if waiting_only(x)]
            if waits:
                problems.append(f"lifts: {', '.join(waits)} only keeps the gate waiting — it never lifts")
        if not lm.group("period"):
            problems.append("lifts: no period after its answers")
        i = order.index("Lifts")
        if i == 0 or order[i - 1] != "Answers":
            problems.append("lifts: `Lifts:` follows Answers")
    if kind == "decide" and ctx is not None and (parts or lifts_seg or CONTEXT_ANY_GATE_RE.search(ctx)) \
            and len({ref_key(x.group(0)) for x in REF_TD_RE.finditer(ctx)}) != 1:
        problems.append("context: a decide that lifts a gate names exactly one entry in its Context")
    for name in ("Decided", "Closed"):
        if name in order:
            problems.append(f"text: names a field ({name}:) where none is read")
    offered = [split_answer(x.replace("\\|", "|").strip()) for x in ANSWER_SPLIT_RE.split(raw)] if raw else []
    marks = sum(mk for _, _, mk in offered)
    if bad_kind:
        pass
    elif decided:
        if marks > 1:
            problems.append("answers: more than one marked ` (default)`")
    elif kind == "decide":
        labels = [lb for lb, _, _ in offered]
        if len(offered) < 2:
            problems.append("answers: a decide carries two or more answers")
        elif len(set(labels)) != len(labels) or not all(labels):
            problems.append("answers: each answer has its own label")
        if marks > 1:
            problems.append("answers: more than one marked ` (default)`")
    elif kind == "look":
        if raw not in LOOK_ANSWERS:
            problems.append("answers: a look carries exactly `Works | Not right: <what>`, "
                            "`Works` marked ` (default)` or not")
    elif raw is not None:
        problems.append(f"answers: {_a_kind(kind)} carries no answers: a question with answers is a decide")

    if not problems:
        want = (f"{f'{kind} ' if kind else ''}{date_s} ({head}) — {item_text.strip()} Context: {ctx}"
                f"{f' Parts: {parts_s}.' if parts_s is not None else ''}"
                f"{f' Due: {due_s}.' if due_s else ''}{f' Hide until: {hide_s}.' if hide_s else ''}"
                f"{f' Answers: {raw}.' if raw is not None else ''}{f' Lifts: {lifts_s}.' if lifts_s is not None else ''}")
        if body != want:
            problems.append("extra: spacing, or words outside the line's parts")
    return "; ".join(problems) or None


def canonical_item(line: str) -> str:
    """`line`, an open item line, rewritten into the form the writers write, keeping its item key
    and every word; Refused, naming what a person must fix, where that cannot be done (SPEC
    *The form the writers write*). It respells the `Due:` field, adds the period after its date,
    moves a `Due:` that directly follows the text's sentence to after `Context:`, and adds
    Context's period, each only where the key is kept. Idempotent; the line ending is kept."""
    ending = line[len(line.rstrip("\r\n")):]
    new = line[: len(line) - len(ending)]
    if ITEM_RE.match(new) is None:
        raise Refused("open: not an open item")
    d = DUE_RE.search(new)
    if d:
        new = new[: d.start()] + "Due:" + new[d.start() + 4:]  # the field DUE_RE first finds, never a reply's
        d = DUE_RE.search(new)
        if not new[d.end():].startswith("."):
            new = new[: d.end()] + "." + new[d.end():]
    c = CONTEXT_RE.search(new)
    mv = re.search(r"(?<=[.?!]) (?P<due>Due: \d{4}-\d{2}-\d{2}\.)(?= Context:)", new)
    if mv and c and c.start() > mv.start():
        tail = new[mv.end():].rstrip()
        if re.fullmatch(r" Context: [^:]*?", tail) and not reply_span(new[mv.end():]):
            ctx = tail[len(" Context: "):]
            new = f"{new[: mv.start()]} Context: {ctx}{'' if ctx.endswith('.') else '.'} {mv.group('due')}"
    c = CONTEXT_RE.search(new)
    if c:
        end = c.end("ctx")
        span = reply_span(new)
        if span and c.start("ctx") <= span[0] < end:  # an fyi's replies follow its Context
            end = span[0]
        words = new[c.start("ctx"): end].rstrip()
        stop = c.start("ctx") + len(words)
        if words and not words.endswith("."):
            new = new[:stop] + "." + new[stop:]
    if new == line[: len(line) - len(ending)]:
        problem = item_problem(new)
        if problem:
            raise Refused(problem)
        return line
    was, got = parse_board(line, warn=False), parse_board(new, warn=False)

    def fields(it: BoardItem) -> tuple:
        return (it.kind, it.due, it.hide_until, it.answers, it.consequences, it.default, it.decided, it.decided_by,
                it.lifts, it.parts, parse_replies(it.text), item_refs(it.text), item_head(it.text))
    if item_key(new) != item_key(line[: len(line) - len(ending)]) or len(was) != 1 or len(got) != 1 \
            or fields(was[0]) != fields(got[0]):
        raise Refused("the rewrite would change the line's item key or what the reader reads: "
                      "fix the line by hand — " + (item_problem(line) or "its form"))
    problem = item_problem(new)
    if problem:
        raise Refused(problem)
    return new + ending


def people_problems(board: str) -> list[tuple[int, str]]:
    """(1-based line, problem) for the board's `People:` preamble line (v2.3): a note, opening `ℹ`, when
    it has none (line 0) — a lift on such a board takes ordinary review — and a fault for a line that
    lists no name, a name outside the person grammar, a name twice (case-insensitively), or a second
    `People:` line above the first item."""
    got = _people_line(board)
    if got is None:
        return [(0, "ℹ people: no `People:` line — nobody is named who may answer this board's items")]
    n, _ = got
    names = board_people(board) or []
    out = []
    if not names:
        out.append((n, "people: `People:` lists no name"))
    bad = [x for x in names if not is_person(x)]
    if bad:
        out.append((n, f"people: not a person's name: {', '.join(repr(x) for x in bad)}"))
    seen: set[str] = set()
    twice = [x for x in names if is_person(x) and (x.lower() in seen or seen.add(x.lower()))]
    if twice:
        out.append((n, f"people: named twice: {', '.join(twice)}"))
    lines = board.splitlines()
    for m in range(n, len(lines)):
        if ANY_ITEM_RE.match(lines[m]):
            break
        if PEOPLE_RE.match(lines[m].rstrip()):
            out.append((m + 1, "people: a second `People:` line — the first is read"))
    return out


def answered_by_problems(board: str) -> list[tuple[int, str]]:
    """(1-based line, problem) for the board's `Answered by:` preamble line (v2.4): a value other than `owner`
    or `any`, and a second such line above the first item. None means `owner`, and is no problem."""
    got = _answered_by_line(board)
    if got is None:
        return []
    n, value = got
    out = []
    if value.strip().lower() not in ANSWERED_BY:
        out.append((n, f"answered by: `Answered by:` is owner or any, not {value.strip()!r}"))
    lines = board.splitlines()
    for m in range(n, len(lines)):
        if ANY_ITEM_RE.match(lines[m]):
            break
        if ANSWERED_BY_RE.match(lines[m].rstrip()):
            out.append((m + 1, "answered by: a second `Answered by:` line — the first is read"))
    return out


def board_problems(board: str, old: str | None = None) -> list[tuple[int, str]]:
    """(1-based line, problem) for each open item line of `board` that item_problem() faults and
    that is new: no item line of `old`, open or closed, has its item key. Every `- [ ]` line at any
    indent is judged but an open twin of a closed one; closed lines never are; `old=None`
    judges every open line. A new `decide` line whose Context names a gate, `decision (<person>)`, is
    also faulted when the board's `People:` does not list that person. First come the board's
    `People:` problems (people_problems(), v2.3), whose note on a board with none opens `ℹ` and is no
    fault; then its `Answered by:` problems (answered_by_problems(), v2.4). The board's gate: a consumer calls
    it on the board as the edit leaves it, with the board as the edit found it."""
    closed = {item_key(ln) for ln in closed_items(board)}
    known = None if old is None else {item_key(ln) for ln in old.splitlines() if ANY_ITEM_RE.match(ln)}
    people = board_people(board)
    on = {x.lower() for x in people or []}
    out = people_problems(board) + answered_by_problems(board)
    for n, ln in enumerate(board.splitlines(), start=1):
        if not ITEM_RE.match(ln) or item_key(ln) in closed or (known is not None and item_key(ln) in known):
            continue
        problems = [p] if (p := item_problem(ln)) else []
        text = ITEM_RE.match(ln).group("text").strip()
        k = KIND_RE.match(text)
        c = CONTEXT_RE.search(_gate_body(text))
        if people is not None and k and k.group("kind").lower() == "decide" and c:
            off = [g.group("person") for g in CONTEXT_GATE_RE.finditer(c.group("ctx"))
                   if g.group("person").lower() not in on]
            if off:
                problems.append(f"context: the gate's person {', '.join(off)} is not on the board's `People:`")
        if problems:
            out.append((n, "; ".join(problems)))
    return out


def _lf_lines(text: str) -> list[str]:
    """`text`'s lines, each with its own ending, split at `\\n` alone: a person's text may hold a
    character `str.splitlines()` also breaks at (U+2028, a form feed), and a move never splits a line."""
    return re.findall(r"[^\n]*\n|[^\n]+\Z", text)


def archive_closed(board: str, archive: str) -> tuple[str, str]:
    """(board, archive) after the archive: each closed item line with its detail block, and each open
    line whose key a closed line shares (its twin, C5) with its block, moved in board order and byte
    for byte to the archive's end; every other board line kept byte for byte. Refused for a board
    with no closed item, for a shape it would split (a nested moving item, one with an item nested
    under it, one whose block a blank line breaks), and for a result the reader reads otherwise.
    When to archive is the consumer's (ARCHIVE_AT)."""
    lines = _lf_lines(board)
    bare = [ln.rstrip("\r\n") for ln in lines]
    closed = {item_key(ln) for ln in bare if CLOSED_ITEM_RE.match(ln)}
    if not closed:
        raise Refused("the board has no closed item to archive")

    def deep(ln: str) -> int:
        return len(ln) - len(ln.lstrip())

    def blank(i: int) -> bool:
        return not bare[i].strip()

    def item(i: int) -> bool:
        return bool(ITEM_RE.match(bare[i]) or CLOSED_ITEM_RE.match(bare[i]))
    runs: list[tuple[int, int]] = []
    for i, ln in enumerate(bare):
        if not (CLOSED_ITEM_RE.match(ln) or (ITEM_RE.match(ln) and item_key(ln) in closed)):
            continue
        where = f"line {i + 1}"
        if deep(ln):
            raise Refused(f"{where}: a closed item nested under another: move it to the left edge first")
        j = i + 1
        while j < len(bare) and not blank(j) and deep(bare[j]) > deep(ln) and not item(j):
            j += 1
        if j < len(bare) and item(j) and deep(bare[j]) > deep(ln):
            raise Refused(f"{where}: an item nested under a closed one would be left behind: move it out first")
        if j < len(bare) and blank(j):
            k = j
            while k < len(bare) and blank(k):
                k += 1
            if k < len(bare) and deep(bare[k]) > deep(ln):
                raise Refused(f"{where}: a blank line breaks the closed item's detail block: join it first")
        runs.append((i, j))
    moved = [i for s, e in runs for i in range(s, e)]
    kept = [True] * len(lines)
    for i in moved:
        kept[i] = False
    for s, e in runs:  # a removal leaves no two blank lines in a row, and the file's ends as they were
        p = next((i for i in range(s - 1, -1, -1) if kept[i]), None)
        n = next((i for i in range(e, len(lines)) if kept[i]), None)
        if p is not None and n is not None and blank(p) and blank(n):
            kept[p] = False
        elif p is None and n is not None and blank(n):
            kept[n] = False
        elif n is None and p is not None and blank(p):
            kept[p] = False
    new_board = "".join(ln for ln, k in zip(lines, kept) if k)
    tail = "".join(lines[i] for i in moved)
    if not archive.strip():
        new_archive = tail
    else:
        eol = "\r\n" if _lf_lines(archive)[0].endswith("\r\n") else "\n"
        head = archive if archive.endswith("\n") else archive + eol
        arch = [ln.rstrip("\r\n") for ln in _lf_lines(head)]
        last = next(ln for ln in reversed(arch) if ln.strip())
        if not (ITEM_RE.match(last) or CLOSED_ITEM_RE.match(last) or deep(last)) and arch[-1].strip():
            head += eol
        new_archive = head + tail

    def read(text: str) -> list[BoardItem]:
        return [_dc_replace(it, line=0) for it in parse_board(text, warn=False)]
    if read(new_board) != read(board) or closed_items(new_board) or not new_archive.endswith(tail):
        raise Refused("the board's reader would not read the board back unchanged but for its closed items")
    return new_board, new_archive


def archive_subject(tool: str, count: int, session: str | None = None) -> str:
    """The commit subject of an archive write: `<tool>: archive <count> closed items (session <name>)`
    (`closed item` for one; `n/a` with no session), `count` the closed items moved, twins not counted."""
    if not tool or re.search(r"[\s()]", str(tool)):
        raise Refused(f"a tool is one word with no parenthesis, not {tool!r}")
    if type(count) is not int or count < 1:
        raise Refused(f"the count is the closed items moved, 1 or more, not {count!r}")
    if session is not None and (not session or re.search(r"[\s()]", str(session))):
        raise Refused(f"a session name holds no whitespace or parenthesis, not {session!r}")
    return f"{tool}: archive {count} closed item{'' if count == 1 else 's'} (session {session or 'n/a'})"


# The commit subject of one board write: `<tool>: <action> <head>[ to <date> | : <answer>]
# (session <name>)`; for an append, `<tool>: append <head> (session <name>)`. A reply's words stay
# on the board, never in the subject.
EDIT_SUBJECT_RE = re.compile(r"^\S+: (?P<action>snooze|due|done|decide|reply) .+ \(session [^)]+\)$")
APPEND_SUBJECT_RE = re.compile(r"^\S+: append .+ \(session [^)]+\)$")
ARCHIVE_SUBJECT_RE = re.compile(r"^\S+: archive (?:1 closed item|(?:[2-9]|[1-9]\d+) closed items) \(session [^)\s]+\)\Z")  # v2.3
# The ledger's one-time migrate commit (v2.4, SPEC *The merge gate's verdicts*): the tripwire exempts it by subject.
MIGRATE_SUBJECT_RE = re.compile(r"^ledger: migrate v(?P<release>[0-9]{1,9}(?:\.[0-9]{1,9}){0,2}) \((?P<n>[0-9]{1,9}) entries\)\Z")
# Subjects one consumer wrote for an append before this format had one; still read, so a board PR
# in flight across the change classifies as before.
LEGACY_APPEND_SUBJECT_RES = (
    re.compile(r"^shiftlead: (?:board|answer) .+ \(from [^)]+\)$"),
    re.compile(r"^shiftlead: board decide \S+ \(person\)$"),
)


def subject(tool: str, action: str, text: str, *, to: date | str | None = None, answer: str | None = None,
            session: str | None = None) -> str:
    """The one-line commit subject of a board write by `tool`: an edit of `text` (an item's text,
    the line without its `- [ ]`) or an `append` of it. `session` defaults to the one the item names."""
    if action not in (*EDIT_ACTIONS, "append"):
        raise Refused(f"unknown action {action}")
    if action in ("snooze", "due") and not to:
        raise Refused(f"a {action} needs its date")
    what = (f" to {to.isoformat() if isinstance(to, date) else to}" if action in ("snooze", "due")
            else f": {' '.join((answer or '').split())}" if action == "decide" else "")
    sm = SESSION_RE.search(text)
    who = session or (sm.group(1) if sm else "n/a")
    return f"{tool}: {action} {edit_head(text)}{what} (session {who})"


def queue_subject(tool: str, action: str, ids: list[str]) -> str:
    """The one-line commit subject of a rank file write by `tool`: ``queue: rank|join|prune TD-a, TD-b (<tool>)``,
    the ids in id order. A rank sets a moved card's lines, a join a newcomer's, a prune removes a done card's."""
    if action not in QUEUE_ACTIONS:
        raise Refused(f"unknown queue action {action}")
    if not ids or not all(ID_ITEM_RE.match(t) for t in ids):
        raise Refused(f"a queue subject names entry ids: {ids!r}")
    if not tool or not re.fullmatch(r"[^()\s][^()]*", tool):
        raise Refused(f"not a tool name: {tool!r}")
    return f"queue: {action} {', '.join(sorted(set(ids), key=_num))} ({tool})"


def migrate_subject(release: str, n: int) -> str:
    """The one-time migrate commit's subject, ``ledger: migrate v<release> (<n> entries)`` (v2.4)."""
    out = f"ledger: migrate v{release} ({n} entries)"
    if isinstance(n, bool) or not isinstance(n, int) or not MIGRATE_SUBJECT_RE.match(out):
        raise Refused(f"a migrate subject names a release (2.4) and a whole count, not {release!r} and {n!r}")
    return out


def subject_kind(line: str) -> str | None:
    """`edit`, `append` or `archive` for a board write's commit subject, `queue` for a rank file write's (or a PR
    title carrying one), `migrate` for the ledger's one-time migrate commit (v2.4); None otherwise."""
    if MIGRATE_SUBJECT_RE.match(line):
        return "migrate"
    if QUEUE_SUBJECT_RE.match(line):
        return "queue"
    if ARCHIVE_SUBJECT_RE.match(line):
        return "archive"
    if EDIT_SUBJECT_RE.match(line):
        return "edit"
    if APPEND_SUBJECT_RE.match(line) or any(r.match(line) for r in LEGACY_APPEND_SUBJECT_RES):
        return "append"
    return None


def edit_action(line: str) -> str | None:
    """The action of a board edit's commit subject (`snooze`, `due`, `done`, `decide` or `reply`), None for any
    other subject (v2.3). A `snooze … to D` meant a moved Due: before v2.3 and a hide since."""
    if subject_kind(line) != "edit":
        return None
    return EDIT_SUBJECT_RE.match(line).group("action")


# ---------------------------------------------------------------------------------------------
# Line predicates, for a reader that walks a diff line by line
# ---------------------------------------------------------------------------------------------

ANY_ITEM_RE = re.compile(r"^(\s*-\s*)\[[ xX]\]")
OPEN_ITEM_RE = re.compile(r"^\s*-\s*\[ \]\s+\S")
# A preamble stamp, `Name: <value>` — dated, `Name: YYYY-MM-DD (…)`, when no names are given. The
# shape is the format's; which names a consumer writes (`Swept:`, `Swept-deep:`) and what they
# mean are the consumer's.
STAMP_LINE_RE = re.compile(r"^(?P<name>[A-Z][\w-]*):\s")
DATED_STAMP_RE = re.compile(r"^[A-Z][\w-]*:\s+\d{4}-\d{2}-\d{2}\b")
_ENTRY_LINE_RE = re.compile(r"^## (TD-\d+):")
_ROW_LINE_RE = re.compile(r"^\|\s*(TD-\d+)\s*\|")


def entry_id(line: str) -> str | None:
    """The id of a ledger entry's heading line, or None."""
    m = _ENTRY_LINE_RE.match(line)
    return m.group(1) if m else None


def row_id(line: str) -> str | None:
    """The id of a ledger summary-table row, or None."""
    m = _ROW_LINE_RE.match(line)
    return m.group(1) if m else None


def is_item(line: str) -> bool:
    """A board item line, open or closed."""
    return bool(ANY_ITEM_RE.match(line))


def is_open_item(line: str) -> bool:
    """An open board item line with text."""
    return bool(OPEN_ITEM_RE.match(line))


def is_stamp(line: str, names: tuple[str, ...] | None = None) -> bool:
    """A stamp line: with `names`, any `Name: ` line of one of those names; without, a dated one."""
    if names is None:
        return bool(DATED_STAMP_RE.match(line))
    m = STAMP_LINE_RE.match(line)
    return bool(m) and m.group("name") in names


# ---------------------------------------------------------------------------------------------
# The ledger as a directory (v2): one file per entry, read back as one text
# ---------------------------------------------------------------------------------------------

LEDGER_README = "README.md"  # a v2 ledger's opening prose and preamble lines
LEDGER_ARCHIVE = "archive"  # a v2 ledger's archived entries, each file moved there
ENTRY_FILE_RE = re.compile(r"^TD-(\d+)\.md$")  # an entry's file, named as its heading spells the id

Ls = Callable[[str], "list[str] | None"]  # a directory's file names, or None when the path is not a directory
Read = Callable[[str], "str | None"]  # a file's text, or None when there is none


def _sub(path: str, name: str) -> str:
    return f"{path.rstrip('/')}/{name}" if path else name


def archive_path(ledger_path: str) -> str:
    """A v1 ledger's archive: ``<ledger stem>_archive.md`` beside it (``docs/technical_debt_archive.md``)."""
    return ledger_path[:-3] + "_archive.md" if ledger_path.endswith(".md") else ledger_path + "_archive.md"


def _entry_names(names: list[str]) -> list[str]:
    """The entry files among a directory's names, in id order (by number; then by name)."""
    found = [(int(m.group(1)), n) for n in names for m in [ENTRY_FILE_RE.match(n)] if m]
    return [n for _, n in sorted(found)]


def _joined(head: str | None, parts: list[str]) -> str:
    texts = [t.rstrip("\n") + "\n" for t in ([head] if head else []) + parts if t and t.strip()]
    return "\n".join(texts)


def _dir_text(path: str, names: list[str], read: Read, head: str | None = None) -> str:
    return _joined(head, [t for t in (read(_sub(path, n)) for n in _entry_names(names)) if t is not None])


def load(path: str, ls: Ls, read: Read) -> tuple[str, str]:
    """(ledger text, archive text) of the ledger at ``path``, whichever major it is written in.

    A v1 ledger is a file: its text, and its archive's beside it (``archive_path()``). A v2 ledger is
    a directory: ``README.md`` and then every ``TD-NNN.md`` in id order, joined by blank lines, is
    the text a v1 ledger would hold without its summary table; ``archive/`` gives the archive's the
    same way. Every parser here reads that text unchanged. The module opens no file: ``ls`` and
    ``read`` are the caller's (a file system, or one ``git ls-tree`` and ``git cat-file --batch`` at
    a revision), so a read at a commit is the same call. A missing file reads as empty."""
    names = ls(path)
    if names is None:
        return read(path) or "", read(archive_path(path)) or ""
    arch = _sub(path, LEDGER_ARCHIVE)
    return (_dir_text(path, names, read, head=read(_sub(path, LEDGER_README))),
            _dir_text(arch, ls(arch) or [], read))


def entry_path(path: str, tid: str, ls: Ls) -> str | None:
    """The one file holding entry ``tid`` (``TD-7`` finds ``TD-007.md``) in the v2 ledger at
    ``path``, open before archived; None when there is none, or when ``path`` is a v1 file, whose
    entries all live in the text ``load()`` reads."""
    names = ls(path)
    if names is None:
        return None
    want = _num(tid)
    for d, ns in ((path, names), (_sub(path, LEDGER_ARCHIVE), ls(_sub(path, LEDGER_ARCHIVE)) or [])):
        for n in _entry_names(ns):
            if int(ENTRY_FILE_RE.match(n).group(1)) == want:
                return _sub(d, n)
    return None


def _sections(text: str) -> list[tuple[str | None, str]]:
    """``text`` cut at each `## ` heading outside an HTML comment: (the TD id, or None for any other
    heading and for the text before the first), and the section's text byte for byte."""
    hidden = [m.span() for m in COMMENT_RE.finditer(text)]  # as entries() reads them
    cuts = [m.start() for m in SECTION_RE.finditer(text)
            if not any(a <= m.start() < b for a, b in hidden)]
    out = []
    for a, b in zip([0, *cuts], [*cuts, len(text)]):
        part = text[a:b]
        m = HEADING_RE.match(part) if a in cuts else None
        if part:
            out.append((m.group(1) if m else None, part))
    return out


def split(ledger: str, archive: str) -> dict[str, str]:
    """The v2 directory of a v1 ledger and its archive: {relative path: text}. Each entry's text,
    from its heading to the next `## ` heading, is its file (trailing blank lines trimmed to one
    newline); the ledger's text before its first `## ` heading is ``README.md``, with
    ``Ledgerboard: 2`` under its title, and the ``## Summary`` section's lines other than the table
    and blanks follow it (a ``Fields:`` line there stays in the preamble); the archive's text before
    its first entry is dropped. Refused for a ledger that is not v1, another `## ` section, an id
    twice, a result that would not read back the same entries (by id), ``Fields:`` and version, or
    one ``v2_problems()`` names (an HTML comment left open in an entry)."""
    if format_major(ledger) != 1:
        raise Refused(f"the ledger declares Ledgerboard: {format_major(ledger)} — only a v1 ledger splits")
    files: dict[str, str] = {}
    seen: set[int] = set()
    readme, kept = "", []
    for where, text in (("", ledger), (LEDGER_ARCHIVE, archive)):
        for i, (tid, part) in enumerate(_sections(text)):
            if tid is None:
                if i == 0 and not part.startswith("## "):
                    readme = readme if where else part
                    continue
                title, _, rest = part.partition("\n")
                if not where and title.strip().lower() == "## summary":
                    kept += _summary_kept(rest)
                    continue
                raise Refused(f"{title!r} in the {'archive' if where else 'ledger'} is not an entry — "
                              "move it into an entry or the README first; nothing was split")
            if _num(tid) in seen:
                raise Refused(f"{tid} appears twice — one file per entry cannot hold both; nothing was split")
            seen.add(_num(tid))
            files[_sub(where, f"{tid}.md")] = part.rstrip("\n") + "\n"
    files[LEDGER_README] = _v2_readme(readme, kept)
    new_ledger, new_archive = load("", _dict_ls(files), files.get)
    for old, new, what in ((ledger, new_ledger, "ledger"), (archive, new_archive, "archive")):
        if sorted(entries(old), key=lambda e: _num(e["id"])) != entries(new):
            raise Refused(f"the split {what} would not read back the same entries — nothing was split")
    if declared(ledger) != declared(new_ledger) or declarations(ledger) != declarations(new_ledger):
        raise Refused("the split README would not declare the same Fields: — nothing was split")
    if format_major(new_ledger) != 2:
        raise Refused("the split README would not read as Ledgerboard: 2 — nothing was split")
    problems = v2_problems("", _dict_ls(files), files.get)
    if problems:
        raise Refused(f"the split would not read as its files say ({'; '.join(problems)}) — nothing was split")
    return files


def _summary_kept(rest: str) -> list[str]:
    """The ``## Summary`` section's lines but its table, verbatim (v2.4): blank lines kept, the table's
    rows taken out, and of the blank lines on its two sides one kept; leading and trailing blanks dropped."""
    out: list[str] = []
    lines = rest.splitlines()
    hidden = set()  # the lines inside an HTML comment (a template's own rows are no table)
    pos, starts = 0, []
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    joined = "\n".join(lines)
    for m in COMMENT_RE.finditer(joined):
        hidden |= {n for n, at in enumerate(starts) if m.start() <= at < m.end()}

    def row(n: int) -> bool:
        return n not in hidden and lines[n].lstrip().startswith("|")

    i = 0
    while i < len(lines):
        if row(i):
            while i < len(lines) and row(i):
                i += 1
            if out and not out[-1].strip() and i < len(lines) and not lines[i].strip():
                i += 1  # the table stood between two blank lines: one of them stays
            continue
        out.append(lines[i])
        i += 1
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _v2_readme(text: str, kept: list[str]) -> str:
    """``README.md`` from a v1 ledger's opening prose: ``Ledgerboard: 2`` under its title (any
    ``Ledgerboard: 1`` line dropped), then ``kept`` — the Summary section's lines that are not table
    (``_summary_kept()``). A ``---`` that would follow the prose's own closing ``---`` with nothing
    between them (the pair that framed the table) is dropped (v2.4)."""
    lines = [ln for ln in text.rstrip("\n").split("\n") if not VERSION_RE.match(ln)] if text.strip() else []
    at = 1 if lines and lines[0].startswith("# ") else 0
    lines[at:at] = (["", "Ledgerboard: 2"] if at else ["Ledgerboard: 2", ""])
    out = "\n".join(lines).rstrip("\n") + "\n"
    kept = list(kept)
    if kept and kept[0].strip() == "---" and lines and lines[-1].strip() == "---":
        kept.pop(0)
        while kept and not kept[0].strip():
            kept.pop(0)
    return out + ("\n" + "\n".join(kept) + "\n" if kept else "")


SPLIT_TABLE_RE = re.compile(r"\b(?:summary table|table below|the table)\b", re.IGNORECASE)
INLINE_CODE_RE = re.compile(r"(`+).*?\1")  # a code span: no link inside one
SPLIT_LINK_RE = re.compile(r"(?<!\\)\[[^\]]*\]\((?![a-z][a-z0-9+.-]*:|#|/)(?P<target>[^)\s]+)\)"
                           r"|^ {0,3}\[[^\]]+\]:\s*(?![a-z][a-z0-9+.-]*:|#|/)(?P<ref>\S+)", re.IGNORECASE)
ANY_LINK_RE = re.compile(r"(?<!\\)\[[^\]]*\]\([^)]*\)|^ {0,3}\[[^\]]+\]:\s*\S+")  # a link or definition, any target
V1_NAME_RE = re.compile(r"(?<![\w.-])technical_debt(?:_archive)?\.md\b")  # the v1 files, by LEDGER_V1_PATH's name


def split_notes(readme: str) -> list[tuple[int, str, str]]:
    """The lines of a ``README.md`` that ``split()`` wrote which may still describe the v1 layout (v2.4), for a
    caller to warn about: ``(line number, line, why)`` for a line naming the summary table, which a v2 ledger
    has none of, for one holding a relative Markdown link, which the move from beside the v1 file into the
    v2 directory breaks (a link to the v1 archive file among them), or a reference definition doing the same,
    and for one naming a v1 file (``technical_debt.md``, ``technical_debt_archive.md``) outside a link, in a code
    span too. Best effort, for a warning: a line inside a fenced code block, and a link inside a code span, are skipped;
    nothing is rewritten."""
    out, fence = [], ""
    for n, line in enumerate(readme.splitlines(), 1):
        f = FENCE_RE.match(line)
        if f:
            mark = f.group("fence")
            if not fence:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not f.group("info").strip():
                fence = ""  # CommonMark: the same character, at least as long, and no info string
            continue
        if fence:
            continue
        if SPLIT_TABLE_RE.search(line):
            out.append((n, line, "names the summary table: a v2 ledger has none"))
        for m in SPLIT_LINK_RE.finditer(INLINE_CODE_RE.sub("", line)):
            target = m.group("target") or m.group("ref")
            out.append((n, line, f"links {target} relatively: the README moved into the ledger directory"))
        spans = " ".join(m.group(0) for m in INLINE_CODE_RE.finditer(line))  # a code span shows text, never a link
        named = V1_NAME_RE.search(spans) or V1_NAME_RE.search(ANY_LINK_RE.sub("", INLINE_CODE_RE.sub(" ", line)))
        if named:
            out.append((n, line, f"names {named.group(0)}, a v1 file: the ledger is now this directory"))
    return out


def v2_problems(path: str, ls: Ls, read: Read) -> list[str]:
    """Why the v2 ledger at ``path`` may not read as its files say, or []: each ``TD-NNN.md`` must
    open with its one `## TD-NNN:` heading, the number its name's, with every HTML comment closed in
    the file, and one file per number across the ledger and its archive. A hand edit can break each
    of these, and ``load()`` would then join a file into its neighbour; a consumer calls this beside
    ``version_problem()`` before it trusts a v2 read. [] for a v1 file."""
    names = ls(path)
    if names is None:
        return []
    out, seen = [], {}
    arch = _sub(path, LEDGER_ARCHIVE)
    for d, ns in ((path, names), (arch, ls(arch) or [])):
        for n in _entry_names(ns):
            rel, want = _sub(d, n), int(ENTRY_FILE_RE.match(n).group(1))
            if want in seen:
                out.append(f"{rel}: TD-{want} has a file already ({seen[want]}) — one file per entry")
            seen.setdefault(want, rel)
            text = read(rel) or ""
            if text.count("<!--") != len(COMMENT_RE.findall(text)):
                out.append(f"{rel}: an HTML comment is not closed in the file — it would hide the next entry")
            heads = HEADING_RE.findall(COMMENT_RE.sub("", text))
            first = HEADING_RE.match(text)
            if not first or len(heads) != 1 or _num(first.group(1)) != want:
                out.append(f"{rel}: must open with its one `## TD-{want}:` heading "
                           f"(found {', '.join(h[0] for h in heads) or 'none'})")
    return out


def _dict_ls(files: Mapping[str, str]) -> Ls:
    """``ls`` over a {relative path: text} mapping, as ``load()`` takes it ("" is the root)."""
    def ls(path: str) -> list[str] | None:
        pre = f"{path.rstrip('/')}/" if path else ""
        names = [p[len(pre):] for p in files if p.startswith(pre) and "/" not in p[len(pre):]]
        if not names and not any(p.startswith(pre) for p in files):
            return None
        return sorted(names)
    return ls


# ---------------------------------------------------------------------------------------------
# Ledger entries and their writers (v2.2): one entry's text, in canonical form
# ---------------------------------------------------------------------------------------------

# The canonical header order (SPEC *Ledger entries and their edits*), spelled as written there; any
# other field follows in the file's order. A place here is a rendering rule, not a declaration:
# Owner, Kind, Taken by and Waits are not CADENCE_FIELDS.
ENTRY_ORDER = ("Priority", "Type", "Added", "Owner", "Kind", "Status", "Taken by", "Id take",
               "Blocked by", "Waits", "Part of", "Location")
LEAD_RE = re.compile(r"^\*\*(?P<lead>[^*\n]+?)\*\*")  # a section's lead: its first paragraph's bold opening
FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}(?=[^`]*$)|~{3,})(?P<info>.*)$")  # a code fence's line: no lead inside one


def _entry_problem(text: str) -> str | None:
    """Why ``text`` is not one entry a writer may render, or None: it opens with its one
    `## TD-n:` heading, the only one outside its HTML comments, and every comment is closed."""
    heads = HEADING_RE.findall(COMMENT_RE.sub("", text))
    if not HEADING_RE.match(text) or len(heads) != 1:
        return (f"not one entry: an entry's text opens with its one `## TD-n:` heading (found "
                f"{', '.join(h[0] for h in heads) or 'none'}) — a v1 ledger: split first")
    if text.count("<!--") != len(COMMENT_RE.findall(text)):
        return "an HTML comment is not closed in the entry — close it first"
    return None


def _entry_parts(text: str) -> tuple[re.Match, list[tuple[str, str]], str]:
    """(the heading's match, the header block as [(name as written, value)], the body with no
    leading or trailing blank lines) of one entry, line endings normalised; raises Refused for an
    entry ``canonical()`` refuses: not one entry, a header line that is not a field, a repeated
    field, or a field below the header block that ``entries()`` would lift."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    why = _entry_problem(text)
    if why:
        raise Refused(why)
    lines = text.split("\n")
    i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    header, seen = [], set()
    while i < len(lines) and lines[i].strip():
        m = FIELD_RE.match(lines[i])
        if not m and not header:
            raise Refused(f"the paragraph after its heading is its header block, and {lines[i]!r} is not a "
                          "field — an entry with a body needs its fields first; add them by hand")
        if not m:
            raise Refused(f"its header block holds a line that is not a field: {lines[i]!r} — "
                          "join it to its field's line, or move it below the header block, by hand")
        if field_key(m.group(1)) in seen:
            raise Refused(f"its header block names {m.group(1).strip()!r} twice — keep one, by hand")
        seen.add(field_key(m.group(1)))
        header.append((m.group(1), m.group(2)))
        i += 1
    below = entries(text)[0]["below"]
    if below:
        raise Refused(f"its {', '.join(k.capitalize() for k in below)} line is below the header block, "
                      "where the reader still lifts it — move it into the header block, by hand")
    j = len(lines)
    while j > i and not lines[j - 1].strip():
        j -= 1
    while i < j and not lines[i].strip():
        i += 1
    return HEADING_RE.match(text), header, "\n".join(lines[i:j])


def _render(tid: str, title: str, header: list[tuple[str, str]], body: str) -> str:
    """One entry in canonical form: heading, blank, the header in ENTRY_ORDER (the ordered fields
    spelled as it spells them, any other as given, in the given order), blank, the body."""
    place = {field_key(n): k for k, n in enumerate(ENTRY_ORDER)}
    ordered = sorted(enumerate(header), key=lambda x: (place.get(field_key(x[1][0]), len(ENTRY_ORDER)), x[0]))
    out = [f"## {tid}: {title.strip()}".rstrip()]
    fields = [f"**{ENTRY_ORDER[place[field_key(n)]] if field_key(n) in place else n}:** {v}".rstrip()
              for _, (n, v) in ordered]
    if fields:
        out += ["", *fields]
    if body:
        out += ["", body]
    return "\n".join(out) + "\n"


def _readback(text: str) -> tuple[str, str, dict[str, str], str]:
    """What the reader reads of an entry: (id, title, fields as ``entries()`` reads them, body)."""
    e = entries(text)[0]
    return e["id"], e["title"], e["fields"], _entry_parts(text)[2]


def canonical(text: str) -> str:
    """One entry's text (a v2 ledger's ``TD-NNN.md``) in canonical form (SPEC *Ledger entries and
    their edits*): line endings normalised to ``\\n``, the heading, a blank line, the header block in
    ENTRY_ORDER and then any other field in the file's order, a blank line, the body byte for byte,
    one trailing newline. Idempotent. Raises Refused for text that is not one entry, and for a header
    block whose rendering would lose or duplicate a line — a line that is not a field, a repeated
    field, a field below the header block that ``entries()`` would lift — which a person fixes; and
    whenever the result would not read back the same id, title, fields and body."""
    m, header, body = _entry_parts(text)
    out = _render(m.group(1), m.group(3), header, body)
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    if _readback(out) != _readback(norm):
        raise Refused("the canonical form would not read back the entry's fields and body unchanged — "
                      "nothing was written")
    return out


def _entry_sections(body: str) -> list[tuple[str | None, str]]:
    """The body's sections, in order: (the lead as written — the bold run's text, ``Why:`` or
    ``Done when`` — or None for the text before the first lead; the section's text). A section is
    a paragraph opening with a bold run and every paragraph after it up to the next that does; a
    paragraph inside a code fence never opens one. Each text runs to the next lead, its trailing
    blank lines trimmed."""
    out: list[tuple[str | None, list[str]]] = []
    fence, prev_blank = "", True  # the open fence's run (``` or ~~~, its length), or ""
    for line in body.split("\n"):
        m = LEAD_RE.match(line) if prev_blank and not fence else None
        if m or not out:
            out.append((m.group("lead") if m else None, []))
        out[-1][1].append(line)
        f = FENCE_RE.match(line)
        if f and not fence:
            fence = f.group("fence")
        elif f and f.group("fence")[0] == fence[0] and len(f.group("fence")) >= len(fence) \
                and not f.group("info").strip():
            fence = ""  # closed by a bare run of its own character, at least as long
        prev_blank = not line.strip()
    found = []
    for lead, ls in out:
        while ls and not ls[-1].strip():
            ls = ls[:-1]
        if lead is not None or ls:
            found.append((lead, "\n".join(ls)))
    return found


def _section_key(lead: str) -> str:
    """A section's name for matching: its lead's ``field_key`` with a trailing colon dropped, so
    ``Done when`` and ``Done when:`` are one name; a qualified lead (``Fix (to design):``) keeps its
    whole text and so matches only itself."""
    return field_key(lead.strip().rstrip(":"))


def entry_text(tid: str, title: str, fields, sections, *, filed: Mapping | None = None) -> str:
    """A new entry in canonical form: ``## <tid>: <title>``, its ``fields`` ({name: value} or (name,
    value) pairs, one line each; an empty value is left out), then ``sections`` — (name, text) pairs or a {name: text}
    mapping, each written ``**<name>:** <text>``, a whitespace-only line emptied (in a code block
    too); a first pair with no name is the unnamed lead, written as given. Raises Refused for an id that is not ``TD-n``, an empty or multi-line title, a
    field that is not one ``**Name:** value`` line, a field named twice, and sections that would not
    read back as given (a paragraph of a section's text that opens in bold would start another).

    A Blocked by (v2.4) is written with its ids first, then its gates in the canonical order; the old
    form ``decision (<who>) <text>`` is refused.

    ``filed`` (v2.4: {today, who, session, words, while}) writes the entry's Log: its first line,
    ``filed by <who>, session <s>[, while <id>]: "<words>"``, then one ``gate added: <gate>`` for each
    gate its Blocked by is filed with, in the canonical order. With it, Added is a bare date, Status (if given)
    is ``Open``, and no section is named Log; ``today`` is a date, ``YYYY-MM-DD`` or an aware datetime."""
    if not ID_ITEM_RE.match(str(tid)):
        raise Refused(f"an entry's id is TD-n, not {tid!r}")
    title = str(title or "")
    if not title.strip() or "\n" in title.strip():
        raise Refused("an entry needs its title, on one line")
    header, seen = [], set()
    for name, value in (fields.items() if isinstance(fields, Mapping) else fields or ()):
        name, value = str(name).strip(), str(value or "").strip()
        if not value:
            continue
        if "\n" in value or "\r" in value:
            raise Refused(f"the {name} field is one line (cadence.md §2.12)")
        m = FIELD_RE.match(f"**{name}:** {value}")
        if not m or m.group(1) != name or m.group(2) != value:
            raise Refused(f"{name!r}: {value!r} would not read back as one field")
        if field_key(name) in seen:
            raise Refused(f"the field {name!r} is named twice")
        seen.add(field_key(name))
        header.append((name, _written_blocked(value) if field_key(name) == "blocked by" else value))
    pairs = list(sections.items()) if isinstance(sections, Mapping) else list(sections or ())
    if filed is not None:
        added, status = _value(header, "added"), _value(header, "status")
        if added is not None and not ISO_DAY_RE.fullmatch(added):
            raise Refused(f"a filed entry's Added is the date alone (its words go in the Log), not {added!r}")
        if status is not None and status != "Open":
            raise Refused(f"a filed entry's Status is Open (its notes go in the Log), not {status!r}")
        if any(name and _section_key(f"{name}:") == "log" for name, _ in pairs):
            raise Refused("a filed entry's Log is written from filed, not given as a section")
        day = utc_day(filed.get("today"), "filed")
        lines = [f"- {day}: {_filed_line(filed)}"]
        for gate in gate_items(parse_gates(_value(header, "blocked by"))):
            lines.append(f"- {day}: gate added: {gate}")
        pairs.append((None, "\n".join([f"**{LOG_LEAD}**", *lines])))  # written as given: lines under the lead
    if pairs and not header:
        raise Refused("an entry with sections needs at least one field: the paragraph after the heading "
                      "is the header block")
    parts, want = [], []
    for k, (name, words) in enumerate(pairs):
        words = "\n".join(ln.rstrip() if not ln.strip() else ln
                          for ln in str(words or "").replace("\r\n", "\n").split("\n")).strip("\n")
        if not words.strip():
            raise Refused(f"the section {name or '(unnamed)'!r} is empty")
        if not name:
            if k and not (filed is not None and k == len(pairs) - 1):
                raise Refused("only the first section may have no name — the text before the first lead")
            parts.append(words)
            want.append((_section_key(LOG_LEAD) if k else None, words))
            continue
        lead = f"{str(name).strip()}:"
        parts.append(f"**{lead}** {words}")
        want.append((_section_key(lead), parts[-1]))
    out = canonical(_render(str(tid), title, header, "\n\n".join(parts)))
    got = [(_section_key(lead) if lead is not None else None, t)
           for lead, t in _entry_sections(_entry_parts(out)[2])]
    if got != want or _readback(out)[2] != {field_key(n): v for n, v in header}:
        raise Refused("the entry would not read back with these fields and sections — a paragraph "
                      "opening in bold starts a section of its own; rephrase it")
    return out


ENTRY_ACTIONS = ("set", "note", "edit", "archive", "reopen", "renumber", "rename_ref")
_ENTRY_ARGS = {"set": {"fields"}, "note": {"words"}, "edit": {"section", "words"},
               "archive": {"why", "pr", "pointer", "as_is", "superseded_by", "dropped"}, "reopen": {"why"},
               "renumber": {"new"}, "rename_ref": {"old", "new"}}  # each action's keyword arguments
_DATED_ACTIONS = ("note", "archive", "reopen")  # the actions that write today's date
_TODAY_ACTIONS = _DATED_ACTIONS + ("set", "edit")  # also take today (v2.5): set and edit only to date a gate
PR_IN_TEXT_RE = re.compile(r"#\d+")  # a consumer reads the first `#<digits>` of a Resolved line as its PR
ISO_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")  # the one form a date is written in


def _is_id(x: object, other_repo: bool = False) -> bool:
    """``x`` is ``TD-n`` (or, ``other_repo``, also ``<repo>#TD-n``) and nothing more, not even a newline."""
    return isinstance(x, str) and bool(ID_ITEM_RE.fullmatch(x) or (other_repo and XREPO_ITEM_RE.fullmatch(x)))


def _one_line(what: str, words: str | None) -> str:
    """``words`` collapsed to one line, or Refused: a field, and the line written into one, is one line."""
    if words is not None and ("\n" in str(words).strip() or "\r" in str(words).strip()):
        raise Refused(f"{what} is one line (cadence.md §2.12)")
    said = " ".join(str(words or "").split())
    if not said:
        raise Refused(f"{what} needs its words")
    return said


def _value(header: list[tuple[str, str]], key: str) -> str | None:
    return next((v for n, v in header if field_key(n) == key), None)


def _with(header: list[tuple[str, str]], name: str, value: str | None) -> list[tuple[str, str]]:
    """``header`` with the field ``name`` set to ``value`` (in its place, or last), or removed for None."""
    key, out, done = field_key(name), [], False
    for n, v in header:
        if field_key(n) != key:
            out.append((n, v))
        elif value is not None and not done:
            out.append((n, value))
            done = True
    return out if done or value is None else [*out, (name, value)]


def _keyed(sections: list[tuple[str | None, str]], key: str) -> list[int]:
    return [i for i, (lead, _) in enumerate(sections) if lead is not None and _section_key(lead) == key]


def _one_copy(value: str) -> str:
    """A Blocked by value with each id named once: a later copy of an id (a local one by number, another
    repo's by ``ref_key``) dropped with its comma; the rest, gates and the old form's text among it, as written."""
    g = parse_gates(value)
    keys = [f"#{_num(x)}" if "#" not in x else ref_key(x) for x in g["ids"]]
    if len(set(keys)) == len(keys):
        return value
    out, seen, rest = [], set(), value.strip(" \t")
    while rest:
        if GATE_DECISION_RE.match(rest) and parse_gates(rest)["old_form"]:
            out.append(rest)  # the old form runs to the end of the line
            break
        m = GATE_ITEM_SEP_RE.search(rest)
        item, rest = (rest[: m.start()], rest[m.end():]) if m else (rest, "")
        if ID_ITEM_RE.match(item) or XREPO_ITEM_RE.match(item):
            k = f"#{_num(item)}" if "#" not in item else ref_key(item)
            if k in seen:
                continue
            seen.add(k)
        if item:
            out.append(item)
    return ", ".join(out)


def _rename(value: str, old: str, new: str) -> str:
    """``value`` with each id item ``old`` written ``new``; a local id matches by number (``TD-7`` is ``TD-007``)."""
    m = ID_ITEM_RE.match(old)
    if m:
        rx = re.compile(rf"(?<![\w#/.-])TD-0*{int(m.group(1))}(?!\d)")
    else:
        repo, tid = XREPO_ITEM_RE.match(old).groups()
        rx = re.compile(rf"(?<![\w/.-]){re.escape(repo)}#TD-0*{_num(tid)}(?!\d)", re.IGNORECASE)
    return rx.sub(new, value)


def dependents(ledger: str, tid: str) -> list[str]:
    """The open entries of ``ledger`` whose Blocked by names ``tid`` (a local id, matched by number), in file order."""
    return [e["id"] for e in entries(ledger) if _num(e["id"]) != _num(tid)
            and any("#" not in x and _num(x) == _num(tid) for x in parse_gates(e["blocked_raw"])["ids"])]


def archive_plan(ledger: str, archive: str, tid: str, *, superseded_by: str | None = None, dropped: bool = False,
                 resolve: Resolve | None = None) -> dict:
    """What archiving open entry ``tid`` leaves its dependents (v2.4, SPEC *Superseded and dropped*):
    ``{successor, rewire}``. Raises Refused when the archive may not go ahead.

    - Resolved (neither keyword): ``{successor: None, rewire: []}``; its dependents are released as before.
    - ``dropped``: refused while any open entry is Blocked by ``tid``, naming every one — each is decided
      first.
    - ``superseded_by`` (``TD-m`` or ``<repo>#TD-m``): the successor followed through each Superseded entry
      to the end of its chain, which ``successor`` names and the archive writes. It must be open or
      Resolved: refused when it names no entry (or one the resolver cannot answer), ends in Dropped or in a
      Status word this reader does not know (TD-039), loops,
      or is ``tid`` itself or one of its dependents (which would block on itself). ``rewire``: the
      dependents, each to get ``edit_entry(…, "rename_ref", old=tid, new=successor)`` in the same change."""
    if not _is_id(tid) or not any(_num(e["id"]) == _num(tid) for e in entries(ledger)):
        raise Refused(f"{tid!r} names no open entry")
    deps = dependents(ledger, tid)
    if dropped and superseded_by is not None:
        raise Refused("an entry is dropped or superseded, not both")
    if dropped:
        if deps:
            raise Refused(f"{tid} cannot be dropped while {', '.join(deps)} {'is' if len(deps) == 1 else 'are'} "
                          f"Blocked by it — decide each first: drop the blocker, or block it on what replaces {tid}")
        return {"successor": None, "rewire": []}
    if superseded_by is None:
        return {"successor": None, "rewire": []}
    if not _is_id(superseded_by, other_repo=True):
        raise Refused(f"superseded by another entry's TD-n or <repo>#TD-n, not {superseded_by!r}")
    live_nums = {_num(e["id"]) for e in entries(ledger)} - {_num(tid)}
    gone = dict(_archived_status(archive))
    gone[_num(tid)] = {"id": tid, "word": "superseded", "successor": superseded_by,
                       "status_word": ""}  # as the archive will read it
    path, state, word = _chain(superseded_by, live_nums, gone, resolve)
    end = path[-1]
    if "#" not in end and _num(end) == _num(tid) or state == "cycle":
        raise Refused(f"superseding {tid} by {superseded_by} loops back ({' → '.join(path)}) — name another successor")
    if state == "dropped":
        raise Refused(f"the successor's chain ({' → '.join(path)}) ends in an entry archived Dropped — a successor is "
                      "open or Resolved")
    if state == "unknown-status":
        raise Refused(f"the successor's chain ({' → '.join(path)}) ends in an entry archived with a Status word this "
                      f"reader does not know ({word}) — a successor is open or Resolved")
    if state in ("unknown", "unresolved"):
        what = "names no entry in the ledger or the archive" if state == "unknown" else "cannot be resolved"
        via = "" if len(path) == 1 else f" (its chain: {' → '.join(path)})"
        raise Refused(f"the successor {end} {what}{via} — a successor exists, open or Resolved")
    own = [d for d in deps if "#" not in end and _num(d) == _num(end)]
    if own:
        raise Refused(f"{own[0]} is Blocked by {tid} and is its successor: it would block on itself — name another "
                      "successor, or take the blocker off it first")
    if "#" not in end:  # a successor that waits, through its own blockers, on a dependent would close a loop
        edges = {_num(e["id"]): [_num(x) for x in parse_gates(e["blocked_raw"])["ids"] if "#" not in x]
                 for e in entries(ledger)}
        dep_nums, seen, todo = {_num(d): d for d in deps}, set(), [_num(end)]
        while todo:
            n = todo.pop()
            for m in edges.get(n, []):
                if m in dep_nums:
                    raise Refused(f"the successor {end} waits on {dep_nums[m]}, which is Blocked by {tid}: rewired, "
                                  "they would block on each other — name another successor, or untangle them first")
                if m not in seen and m != _num(tid):
                    seen.add(m)
                    todo.append(m)
    return {"successor": end, "rewire": deps}


# ---------------------------------------------------------------------------------------------
# The Log (v2.4): an entry's dated history, the body's last section
# ---------------------------------------------------------------------------------------------

LOG_LEAD = "Log:"
LOG_LINE_RE = re.compile(r"^- (?P<date>\d{4}-\d{2}-\d{2}): (?P<words>\S.*?)$")
# The writer prefixes (SPEC *The Log*): `note` refuses words that begin with one, and a lifted
# Status note that would is written `note: <text>`.
LOG_PREFIXES = ("filed by ", "gate added:", "gate lifted:", "gate reassigned:", "kept waiting:",
                "gate lift skipped:", "was:", "archived:", "reopened —")
LOG_TOKEN = r"[A-Za-z0-9_.@/-]+"  # who, a session, a host: no spaces, commas, colons or quotes
LOG_ID = rf"(?:{REPO}#)?TD-\d+"  # the ids Blocked by takes
LOG_GATE = r"decision \(" + PERSON + r"\)|until \d{4}-\d{2}-\d{2}|event \([a-z0-9-]+\)"
LOG_LIFT_SUFFIX = rf"; board {REPO}|; no board item|; shared board item left open"
# Each writer-made shape, tried in this order; a quoted label or words run to the line's last `"`.
LOG_SHAPES = (
    ("filed", re.compile(rf"filed by (?P<who>{LOG_TOKEN}), session (?P<session>{LOG_TOKEN})"
                         rf"(?:, while (?P<while>{LOG_ID}))?: \"(?P<words>.*)\"")),
    ("gate-added", re.compile(rf"gate added: (?P<gate>{LOG_GATE})")),
    ("gate-lifted", re.compile(rf"gate lifted: (?P<gate>decision \({PERSON}\)|event \([a-z0-9-]+\)) — by "
                               rf"(?P<by>{LOG_TOKEN}); answer \"(?P<label>.*)\"(?P<suffix>{LOG_LIFT_SUFFIX})?")),
    ("gate-lifted", re.compile(rf"gate lifted: (?P<gate>decision \({PERSON}\)) — by (?P<by>{LOG_TOKEN}); "
                               r"override: (?P<why>\S.*)")),
    ("gate-lifted", re.compile(rf"gate lifted: (?P<gate>event \([a-z0-9-]+\)) — by (?P<by>{LOG_TOKEN}); "
                               r"(?P<check>[a-z0-9-]+) passed; (?P<evidence>\S+)")),
    ("gate-lifted", re.compile(rf"gate lifted: (?P<gate>until \d{{4}}-\d{{2}}-\d{{2}}) — by (?P<by>{LOG_TOKEN}); "
                               r"date reached")),
    ("gate-lift-skipped", re.compile(rf"gate lift skipped: (?P<id>{LOG_ID}) no longer carries "
                                     rf"(?P<gate>decision \({PERSON}\)|event \([a-z0-9-]+\))")),
    ("kept-waiting", re.compile(rf"kept waiting: (?P<gate>{LOG_GATE}) — by (?P<by>{LOG_TOKEN}); "
                                r"answer \"(?P<label>.*)\"")),
    ("gate-reassigned", re.compile(rf"gate reassigned: (?P<gate>decision \({PERSON}\)) → "
                                   rf"(?P<to>decision \({PERSON}\)) — by (?P<by>{LOG_TOKEN}); (?P<why>\S.*)")),
    ("archived", re.compile(r"archived: (?P<word>[A-Za-z]+) — (?P<why>\S.*)")),
    ("reopened", re.compile(r"reopened — (?P<why>\S.*)")),
    ("was", re.compile(r"was: (?P<status>\S.*)")),
)
# The Status words, in two roles: the head words status_notes_to_log() reads (SPEC *The Log*), the four
# of the target table and the reserved ones v2.5's migrate maps away; and the words an archived blocker's
# Status is known by (SPEC *Superseded and dropped*, TD-039). A word added here is one pickable() reads:
# as closed and done, unless it joins Superseded's or Dropped's rules; a word outside it keeps the block.
# Whoever adds one decides both roles.
STATUS_WORDS = ("open", "resolved", "superseded", "dropped", "designed", "built", "partly", "live", "in",
                "done", "moved", "obe")
# The head, read whole or not at all: the word is followed by its end, a `:`, its date or `by`; a date
# or a `by <id>` there is part of the head, and is followed by the end, whitespace or a `:`. So
# `In progress`, `Open, held`, `Resolved 2026-10-03.` and `Open 2026-01-01T10:00` are prose.
STATUS_HEAD_RE = re.compile(
    r"^(?P<word>[A-Za-z]+)\.?(?=$|:|[ \t]+\d{4}-\d{2}-\d{2}|[ \t]+by[ \t])"
    r"(?:[ \t]+(?P<date>\d{4}-\d{2}-\d{2})(?![\d-])|(?![ \t]+\d{4}-\d{2}-\d{2}))"
    rf"(?:[ \t]+by[ \t]+(?P<by>{LOG_ID})|(?![ \t]+by[ \t]))"
    r"(?=$|:|[ \t])")
WAS_CUT = " — was: "
LOG_AGE_KINDS = ("gate-added", "kept-waiting", "gate-reassigned")


def log_line(line: str) -> dict | None:
    """One Log line read: {date, kind, text} and the shape's parts, or None for a line that is not
    ``- YYYY-MM-DD: words``. ``kind`` is a writer shape's (``filed``, ``gate-added``, ``gate-lifted``,
    ``gate-lift-skipped``, ``kept-waiting``, ``gate-reassigned``, ``archived``, ``reopened``, ``was``),
    ``note`` for any other words, or ``malformed`` for words that begin with a writer prefix and do
    not take its shape. A ``gate-lifted`` line also says ``via``: answer, override, check or date."""
    m = LOG_LINE_RE.match(line.rstrip("\r"))
    if not m:
        return None
    words = m.group("words")
    out = {"date": m.group("date"), "text": words}
    for k, (kind, rx) in enumerate(LOG_SHAPES):
        s = rx.fullmatch(words)
        if s:
            out["kind"] = kind
            out.update({n: v for n, v in s.groupdict().items() if v is not None})
            if kind == "gate-lifted":
                out["via"] = ("answer", "override", "check", "date")[k - 2]
            return out
    out["kind"] = "malformed" if words.startswith(LOG_PREFIXES) else "note"
    return out


def _log_section(sections: list[tuple[str | None, str]]) -> int | None:
    at = _keyed(sections, "log")
    if len(at) > 1:
        raise Refused(f"the body has {len(at)} Log sections — merge them by hand")
    return at[0] if at else None


def _log_body_lines(section_text: str) -> list[str]:
    """A Log section's lines after its lead, blank lines dropped."""
    first, _, rest = section_text.partition("\n")
    after = first[first.index("**", 2) + 2:].strip() if first.startswith("**") else first
    return ([after] if after else []) + [ln for ln in rest.split("\n") if ln.strip()]


def log_lines(text: str) -> list[dict]:
    """The Log of one entry's text, in file order: each line as ``log_line()`` reads it, or
    {date: None, kind: "unreadable", text} for a line that is not ``- YYYY-MM-DD: words``."""
    sections = _entry_sections(_entry_parts(text)[2])
    at = _log_section(sections)
    if at is None:
        return []
    return [log_line(ln) or {"date": None, "kind": "unreadable", "text": ln}
            for ln in _log_body_lines(sections[at][1])]


def log_problems(text: str) -> list[tuple[str, str]]:
    """Why one entry's Log is not as its writers write it: [(kind, sentence)] — ``log-not-last`` (a
    section follows the Log, or two Logs) and ``log-line`` (a line that is not ``- YYYY-MM-DD:
    words``, or a writer prefix not in its shape)."""
    try:
        sections = _entry_sections(_entry_parts(text)[2])
    except Refused:
        return []
    at = _keyed(sections, "log")
    if not at:
        return []
    out = []
    if len(at) > 1:
        out.append(("log-not-last", f"its body has {len(at)} Log sections — the Log is one section, the body's last"))
    elif at[0] != len(sections) - 1:
        out.append(("log-not-last", "a section follows its Log — the Log is the body's last section; "
                    "move the section above it"))
    for ln in _log_body_lines(sections[at[-1]][1]):
        got = log_line(ln)
        if got is None:
            out.append(("log-line", f"its Log line {ln!r} is not `- YYYY-MM-DD: words`"))
        elif got["kind"] == "malformed":
            out.append(("log-line", f"its Log line {ln!r} begins with a writer's prefix but not in its shape"))
    return out


def _gate_key(gate: str) -> str:
    """A gate compared: a person's name in any case."""
    return " ".join(gate.split()).lower()


def gate_age(text: str, gate: str) -> date | None:
    """The date ``gate`` (as written in Blocked by) has waited since, on one entry (SPEC *The Log*):
    its latest ``gate added``, ``kept waiting`` or ``gate reassigned`` (to it) Log line; else the
    Log's first line; else the Added date; else None."""
    key, latest, first = _gate_key(gate), None, None
    for rec in log_lines(text):
        if rec["date"] is None:
            continue
        first = first or rec["date"]
        if rec["kind"] in LOG_AGE_KINDS and _gate_key(rec.get("to") or rec["gate"]) == key:
            latest = rec["date"] if latest is None or rec["date"] >= latest else latest
    if latest or first:
        return date.fromisoformat(latest or first)
    added = ISO_DAY_RE.search(_value(_entry_parts(text)[1], "added") or "")
    return date.fromisoformat(added.group(0)) if added else None


def gate_added(text: str, gate: str) -> date | None:
    """When ``gate`` (as written in Blocked by) was added, on one entry (v2.5, SPEC *The Log*): the date of
    the last ``gate added`` Log line for it in the Log's order (never by date), compared as ``gate_age()``
    compares; None when there is none, or when a ``gate lifted`` line for it follows that line. Unlike
    ``gate_age()``, it never falls back, and a Log that cannot be read gives None."""
    key, found = _gate_key(gate), None
    try:
        recs = log_lines(text)
    except Refused:  # a Log no reader can read (an entry canonical() refuses, two Logs): no day to count from
        return None
    for rec in recs:
        if rec["date"] is None or rec["kind"] not in ("gate-added", "gate-lifted") or _gate_key(rec["gate"]) != key:
            continue
        found = rec["date"] if rec["kind"] == "gate-added" else None
    try:
        return date.fromisoformat(found) if found else None
    except ValueError:  # a line shaped as a date that is no day (2026-02-30): no day to count from
        return None


def utc_day(value: object, what: str) -> str:
    """A ledger date as ``YYYY-MM-DD`` (SPEC: every ledger date is the UTC date): a date, or a
    ``YYYY-MM-DD`` string, as given; an aware datetime turned into its UTC date. Refused: a naive
    datetime (its zone unknown), and anything else."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise Refused(f"{what} is a naive datetime — pass an aware one (it is turned into its UTC date) or a date")
        return value.astimezone(timezone.utc).date().isoformat()
    try:
        if not isinstance(value, date) and not (isinstance(value, str) and ISO_DAY_RE.fullmatch(value)):
            raise ValueError
        return (value if isinstance(value, date) else date.fromisoformat(value)).isoformat()
    except ValueError:
        raise Refused(f"{what} needs today's date as YYYY-MM-DD, not {value!r}") from None


def _log_text(words: str) -> str:
    """Lifted prose as a Log line's words: one that would read as a writer's line becomes ``note: …``."""
    return f"note: {words}" if words.startswith(LOG_PREFIXES) else words


def _log_insert(sections: list[tuple[str | None, str]], lines: list[tuple[str, str]], *,
                by_date: bool) -> list[tuple[str | None, str]]:
    """``sections`` with ``lines`` ([(date, words)]) in the Log, which is made at the end when there is
    none: appended (a writer's own line), or each among the lines by date, after any of an equal
    date (a lifted note). Refused when a section follows the Log."""
    sections = list(sections)
    at = _log_section(sections)
    if at is None:
        sections.append((LOG_LEAD, f"**{LOG_LEAD}**"))
        at = len(sections) - 1
    elif at != len(sections) - 1:
        raise Refused("a section follows the entry's Log, which is the body's last — move it above the Log, by hand")
    first, _, rest = sections[at][1].partition("\n")
    have = [ln for ln in rest.split("\n") if ln.strip()]
    for day, words in lines:
        new = f"- {day}: {words}"
        if not by_date:
            have.append(new)
            continue
        pos, last = len(have), None
        for i, ln in enumerate(have):
            m = LOG_LINE_RE.match(ln)
            last = m.group("date") if m else last
            if last is not None and last > day:
                pos = i
                break
        have.insert(pos, new)
    sections[at] = (sections[at][0], "\n".join([first, *have]))
    return sections


def _fallback_day(header: list[tuple[str, str]], sections: list[tuple[str | None, str]]) -> str | None:
    """The date an undated Status note takes: the ``**Resolved:**`` line's (or the older header field's),
    else Added's."""
    for text in [sections[i][1] for i in _keyed(sections, "resolved")] + [_value(header, "resolved") or ""]:
        m = ISO_DAY_RE.search(text)
        if m:
            return m.group(0)
    m = ISO_DAY_RE.search(_value(header, "added") or "")
    return m.group(0) if m else None


def _lift_status(header: list[tuple[str, str]], sections: list[tuple[str | None, str]]
                 ) -> tuple[list[tuple[str, str]], list[tuple[str | None, str]], bool]:
    """(header, sections, read): the Status's notes lifted into Log lines (SPEC *The Log*), or the
    two unchanged when there is nothing to lift; ``read`` is False when the Status is there and not
    one ``status_notes_to_log()`` reads (an unknown word, or text with no date to give it)."""
    status = _value(header, "status")
    if not status or not status.strip():
        return header, sections, True
    m = STATUS_HEAD_RE.match(status)
    if not m or m.group("word").lower() not in STATUS_WORDS:
        return header, sections, False
    head = status[:m.end()].rstrip()
    rest = status[m.end():]
    if not rest.strip():
        return header, sections, True
    tail, *was = rest.split(WAS_CUT)
    tail = tail.strip()
    if tail.startswith(":"):
        tail = tail[1:].strip()
    fallback = _fallback_day(header, sections)
    day = m.group("date") or fallback
    lines = []
    if tail:
        lines.append((day, _log_text(tail)))
    for w in was:
        w = w.strip()
        if w:
            inner = STATUS_HEAD_RE.match(w)
            lines.append(((inner and inner.group("date")) or fallback, f"was: {w}"))
    if any(d is None for d, _ in lines):
        return header, sections, False
    return _with(header, "Status", head), _log_insert(sections, lines, by_date=True), True


def status_notes_to_log(text: str) -> str:
    """One entry's text with its Status notes moved into its Log (SPEC *The Log*), in canonical form.
    The Status read is ``<Word>[.] [D] [by <id>] [[:] <tail>] [ — was: <Status>]…`` with a known word
    (``STATUS_WORDS``): the tail becomes one Log line, verbatim, dated by the Status's date, else the
    ``**Resolved:**`` line's, else Added's; each ``— was:`` segment one ``was: <Status>`` line, dated
    by its own date or the same. Lines go in among the Log's by date, after any of an equal date; a
    line that would begin with a writer's prefix is written ``note: <text>``. The Status is left as
    ``<Word> [D] [by <id>]``. The word is not in bold and is followed by its end, ``.``, ``:``, its
    date or ``by``; a date or ``by <id>`` there is followed by the end, whitespace or ``:``. An unknown word, a Status with nothing after its head, or text with no date to give it: the
    text is returned as given, not reformatted. Refused for an entry ``canonical()`` refuses, and when
    there are notes to lift into a Log that is not the body's last section."""
    m, header, body = _entry_parts(canonical(text))
    sections = _entry_sections(body)
    new_header, new_sections, _ = _lift_status(header, sections)
    if new_header == header:
        return text
    return canonical(_render(m.group(1), m.group(3), new_header, "\n\n".join(t for _, t in new_sections)))


def _filed_line(filed: Mapping, what: str = "filed") -> str:
    """``filed by <who>, session <s>[, while <id>]: "<words>"`` from {who, session, words, while}."""
    who, session, w = (str(filed.get(k) or "") for k in ("who", "session", "while"))
    for name, v in (("who", who), ("session", session)):
        if not re.fullmatch(LOG_TOKEN, v):
            raise Refused(f"{what}: {name} is a token with no spaces, commas, colons or quotes, not {v!r}")
    if w and not re.fullmatch(LOG_ID, w):
        raise Refused(f"{what}: while names an entry (TD-n or <repo>#TD-n), not {w!r}")
    words = _one_line(f"{what}'s words", filed.get("words"))
    return f"filed by {who}, session {session}{f', while {w}' if w else ''}: \"{words}\""


def _before_log(sections: list[tuple[str | None, str]]) -> int:
    """Where a section a writer adds goes: before the Log, else at the end."""
    at = _log_section(sections)
    return len(sections) if at is None else at


def _status_to_log(header: list[tuple[str, str]], sections: list[tuple[str | None, str]], day: str
                   ) -> tuple[list[tuple[str, str]], list[tuple[str | None, str]]]:
    """Before archive or reopen replace the Status: its notes lifted into the Log; a Status that
    cannot be read that way copied whole into one ``was: <value>`` line, dated by the fallbacks
    (the Resolved line, Added), else ``day``."""
    header, sections, read = _lift_status(header, sections)
    status = _value(header, "status")
    if not read and status and status.strip():
        sections = _log_insert(sections, [(_fallback_day(header, sections) or day, f"was: {status.strip()}")],
                               by_date=True)
    return header, sections


def edit_entry(text: str, action: str, *, today: date | str | None = None, fields: Mapping[str, str] | None = None,
               words: str | None = None, section: str | None = None, why: str | None = None,
               pr: int | None = None, pointer: str | None = None, as_is: bool = False,
               superseded_by: str | None = None, new: str | None = None, old: str | None = None,
               dropped: bool = False) -> str:
    """One entry's text after ``action`` (``ENTRY_ACTIONS``), in canonical form; raises Refused. The
    edits (SPEC *Ledger entries and their edits*; from v2.4 note, archive and reopen write the Log):

    - ``set`` (``fields``: {name: value}; an empty value removes the field); a Blocked by (v2.4) is
      written with its ids first, then its gates in the canonical order, and refused in the old form,
      or when it adds a gate to an entry whose Blocked by still holds the old form; from v2.5 each gate
      it adds that the entry did not carry is logged ``- <today>: gate added: <gate>`` in that order;
    - ``note`` (``words``): the Status's notes lifted into the Log (``status_notes_to_log``), then
      ``- <today>: <words>`` appended to it; refused for words that begin with a Log writer's prefix;
    - ``edit`` (``section``, ``words``): that named section's paragraphs replaced by ``words``, its lead
      kept; a section the body lacks is added after the first Why, else before the first Done when,
      Related or Log, else at the end; the Log itself is refused;
    - ``archive`` (``why``; ``pr``, an int or None; ``pointer``; ``as_is``; or ``superseded_by``, ``TD-n`` or
      ``<repo>#TD-n``; or ``dropped``, v2.4: Status ``Dropped <today>`` and ``archived: Dropped — <why>``,
      the rest kept; ``archive_plan()`` says first which dependents each leaves, or refuses): the
      Status's notes lifted (one it cannot read copied whole into a ``was:`` line), then the archived
      form — Status ``Resolved <today>`` and Fix replaced by ``**Resolved:** <today> (PR #<pr>) —
      <pointer>`` (after the whole Fix with ``as_is``; before the Log when no section is named exactly
      Fix), any earlier ``**Resolved:**`` section and header ``Resolved`` removed, and the Log line
      ``archived: Resolved — <why>``; or Status ``Superseded <today> by <id>`` and ``archived:
      Superseded — <why>``, with the rest kept;
    - ``reopen`` (``why``): the Status lifted as for archive, then ``Open``, and the Log line
      ``reopened — <why>``; a header ``Resolved`` moves to a ``**Resolved:**`` section before the Log;
      refused when the entry has both;
    - ``renumber`` (``new``): the heading's id; ``rename_ref`` (``old``, ``new``): that id rewritten in
      Blocked by, Part of and a Log ``filed by`` line's ``while``; a Blocked by that then names an id twice
      keeps its first copy (v2.4).

    ``today`` is the caller's date, required by note, archive and reopen, and taken by set and edit (v2.5),
    which require it only to date a gate: set's Blocked by adding one, or edit making a carried gate's
    Event section a new or changed ``host-log`` check, which appends ``gate added: event (<name>)`` (none is
    read here): a date,
    ``YYYY-MM-DD``, or an aware datetime, written as its UTC date; a naive datetime is refused. A writer
    that appends to the Log refuses one that is not the body's last section. Every edit is refused for an entry
    ``canonical()`` refuses, and unless the result reads back exactly the change meant — the id,
    title, fields (as ``entries()`` reads them) and sections — and nothing else. Validity (a
    vocabulary, a Blocked by item, a cycle) is ``check()``'s, which the caller runs on the result."""
    if action not in ENTRY_ACTIONS:
        raise Refused(f"unknown action {action}")
    given = {k for k, v in (("fields", fields), ("words", words), ("section", section), ("why", why),
                            ("pr", pr), ("pointer", pointer), ("as_is", as_is or None),
                            ("superseded_by", superseded_by), ("new", new), ("old", old),
                            ("dropped", dropped or None)) if v is not None}
    stray = sorted(given - _ENTRY_ARGS[action]) + (["today"] if today is not None and action not in _TODAY_ACTIONS else [])
    if stray:
        raise Refused(f"{action} takes no {', '.join(stray)}")
    day = utc_day(today, action) if action in _DATED_ACTIONS or today is not None else ""
    m, header, body = _entry_parts(canonical(text))
    tid, title = m.group(1), m.group(3).strip()
    title_read = entries(canonical(text))[0]["title"]  # as the reader reads it: an HTML comment dropped
    sections = _entry_sections(body)
    body_changed = False

    if action == "set":
        if not fields:
            raise Refused("set needs the fields to set")
        keys = [field_key(str(n)) for n in fields]
        if len(set(keys)) != len(keys):
            raise Refused("set names one field twice")
        for name, value in fields.items():
            name = str(name).strip()
            if not value or not str(value).strip():
                header = _with(header, name, None)
                continue
            value = _one_line(f"the {name} field", value)
            if field_key(name) == "blocked by":
                current = _value(header, "blocked by")
                value = _written_blocked(value, current)
                was = parse_gates(current)
                had = {_gate_key(x) for x in gate_items(was)} | (
                    {_gate_key(f"decision ({was['old_form'][0]})")} if was["old_form"] else set())
                added = []
                for x in gate_items(parse_gates(value)):  # a gate named twice is logged once, as first written
                    if _gate_key(x) not in had:
                        had.add(_gate_key(x))
                        added.append(x)
                if added and not day:
                    raise Refused(f"set adds {', '.join(added)}, which the Log dates — pass today (v2.5)")
                if added:
                    sections = _log_insert(sections, [(day, f"gate added: {x}") for x in added], by_date=False)
                    body_changed = True
            fm = FIELD_RE.match(f"**{name}:** {value}")
            if not fm or fm.group(1) != name or fm.group(2) != value:
                raise Refused(f"{name!r}: {value!r} would not read back as one field")
            header = _with(header, name, value)
    elif action == "note":
        said = _one_line("a note", words)
        if said.startswith(LOG_PREFIXES):
            raise Refused(f"a note may not begin with a Log writer's prefix ({', '.join(repr(x.strip()) for x in LOG_PREFIXES)}) "
                          "— say it in other words")
        header, sections, _ = _lift_status(header, sections)
        sections = _log_insert(sections, [(day, said)], by_date=False)
        body_changed = True
    elif action == "edit":
        name = _one_line("the section's name", section).rstrip(":").strip()
        if not name:
            raise Refused("edit needs the section's name")
        if _section_key(name) == "log":
            raise Refused("the Log is written by its writers (note, archive, reopen), never replaced by edit")
        said = "\n".join(ln.rstrip() if not ln.strip() else ln
                         for ln in str(words or "").replace("\r\n", "\n").split("\n")).strip("\n")
        if not said.strip():
            raise Refused(f"the section {name!r} needs its words")
        at = _keyed(sections, _section_key(name))
        if len(at) > 1:
            raise Refused(f"the body has {len(at)} sections named {name!r} — edit it by hand")
        before = parse_event_section(sections[at[0]][1]) if at else None
        if at:
            sections[at[0]] = (sections[at[0]][0], f"**{sections[at[0]][0]}** {said}")
        else:
            why_at = _keyed(sections, "why")
            ends = sorted(_keyed(sections, "done when") + _keyed(sections, "related") + _keyed(sections, "log"))
            pos = why_at[0] + 1 if why_at else ends[0] if ends else len(sections)
            sections.insert(pos, (f"{name}:", f"**{name}:** {said}"))
        after = parse_event_section(sections[at[0] if at else pos][1])
        carried = parse_gates(_value(header, "blocked by"))["events"]
        if after["name"] in carried and not after["problem"] and after["check"]["type"] == "host-log" and (
                before is None or before["problem"] or before["check"]["type"] != "host-log"
                or _host_log_key(before["check"]) != _host_log_key(after["check"])):  # a changed question: a new wait
            gate = f"event ({after['name']})"
            if not day:
                raise Refused(f"edit makes {gate}'s host-log check a new wait, which the Log dates — pass today (v2.5)")
            sections = _log_insert(sections, [(day, f"gate added: {gate}")], by_date=False)
        body_changed = True
    elif action == "archive":
        said = _one_line("the archive's why", why)
        if dropped:
            if pr is not None or pointer is not None or as_is or superseded_by is not None:
                raise Refused("a dropped entry keeps its Why and Fix, and nothing replaces it: no pr, pointer, "
                              "as_is or superseded_by")
            header, sections = _status_to_log(header, sections, day)
            header = _with(header, "Status", f"Dropped {day}")
            sections = _log_insert(sections, [(day, f"archived: Dropped — {said}")], by_date=False)
            body_changed = True
        elif superseded_by is not None:
            if pr is not None or pointer is not None or as_is:
                raise Refused("a superseded entry keeps its Why and Fix: no pr, pointer or as_is")
            if not _is_id(superseded_by, other_repo=True) or ("#" not in superseded_by and _num(superseded_by) == _num(tid)):
                raise Refused(f"superseded by another entry's TD-n or <repo>#TD-n, not {superseded_by!r}")
            header, sections = _status_to_log(header, sections, day)
            header = _with(header, "Status", f"Superseded {day} by {superseded_by}")
            sections = _log_insert(sections, [(day, f"archived: Superseded — {said}")], by_date=False)
            body_changed = True
        else:
            if pr is not None and (isinstance(pr, bool) or not isinstance(pr, int) or pr < 1):
                raise Refused(f"a PR is the forge's number, not {pr!r}")
            ptr = _one_line("the pointer", pointer) if pointer is not None else ""
            if pr is None and PR_IN_TEXT_RE.search(ptr):
                raise Refused("with no PR, the pointer may not hold #<digits>: a reader would take it for the PR")
            line = f"**Resolved:** {day}{f' (PR #{pr})' if pr is not None else ''}{f' — {ptr}' if ptr else ''}"
            header, sections = _status_to_log(header, sections, day)
            header = _with(_with(header, "Status", f"Resolved {day}"), "Resolved", None)
            sections = [s for i, s in enumerate(sections) if i not in _keyed(sections, "resolved")]
            fix = _keyed(sections, "fix")
            if len(fix) > 1:
                raise Refused(f"the body has {len(fix)} sections named Fix — archive it by hand")
            if not fix:
                sections.insert(_before_log(sections), ("Resolved:", line))
            elif as_is:
                sections.insert(fix[0] + 1, ("Resolved:", line))
            else:
                sections[fix[0]] = ("Resolved:", line)
            sections = _log_insert(sections, [(day, f"archived: Resolved — {said}")], by_date=False)
            body_changed = True
    elif action == "reopen":
        said = _one_line("the reopen's why", why)
        held = _value(header, "resolved")
        if held is not None and _keyed(sections, "resolved"):
            raise Refused("it has both a Resolved field and a **Resolved:** section — merge them by hand, then reopen")
        header, sections = _status_to_log(header, sections, day)
        header = _with(header, "Status", "Open")
        if held is not None:
            header = _with(header, "Resolved", None)
            sections.insert(_before_log(sections), ("Resolved:", f"**Resolved:** {held}".rstrip()))
        sections = _log_insert(sections, [(day, f"reopened — {said}")], by_date=False)
        body_changed = True
    elif action == "renumber":
        if not _is_id(new):
            raise Refused(f"renumber needs the new TD-n, not {new!r}")
        if _num(new) == _num(tid):
            raise Refused(f"{tid} is numbered {_num(tid)} already — a renumber gives it another number")
        tid = new
    else:  # rename_ref
        for x in (old, new):
            if not _is_id(x, other_repo=True):
                raise Refused(f"rename_ref names entry ids (TD-n or <repo>#TD-n), not {x!r}")
        for key in ("blocked by", "part of"):
            v = _value(header, key)
            if v is not None:
                header = [(n, _rename(x, old, new) if field_key(n) == key else x) for n, x in header]
        v = _value(header, "blocked by")
        if v is not None:  # a dependent that already named the new id keeps one copy (v2.4)
            header = [(n, _one_copy(x) if field_key(n) == "blocked by" else x) for n, x in header]
        at = _log_section(sections)
        if at is not None:  # the one Log token rewritten: a filed line's `while`, never other prose
            first, _, rest = sections[at][1].partition("\n")
            lines = []
            for ln in rest.split("\n"):
                rec = log_line(ln)
                if rec and rec["kind"] == "filed" and rec.get("while") and _rename(rec["while"], old, new) != rec["while"]:
                    ln = ln.replace(f", while {rec['while']}: ", f", while {_rename(rec['while'], old, new)}: ", 1)
                lines.append(ln)
            if lines != rest.split("\n"):
                sections[at] = (sections[at][0], "\n".join([first, *lines]))
                body_changed = True

    if body_changed and any(re.search(r"\n[ \t]*\n", c.group(0)) for c in COMMENT_RE.finditer(body)):
        raise Refused("an HTML comment in the body spans paragraphs, so a section's edit could land inside "
                      "it — edit by hand")
    new_body = "\n\n".join(t for _, t in sections) if body_changed else body
    out = canonical(_render(tid, title, header, new_body))
    want = (tid, title_read, {field_key(n): v for n, v in header},
            [(_section_key(lead) if lead is not None else None, t) for lead, t in sections])
    e = entries(out)[0]
    got = (e["id"], e["title"], e["fields"],
           [(_section_key(lead) if lead is not None else None, t) for lead, t in _entry_sections(_entry_parts(out)[2])])
    if got != want:
        raise Refused(f"after the {action} the entry would not read back as meant, with the rest unchanged — "
                      "rephrase it, or edit by hand")
    return out


# ---------------------------------------------------------------------------------------------
# The next id (v2.4): the counter's reading, and the merge gate's judgement of each new id's take
# ---------------------------------------------------------------------------------------------

COUNTER_BRANCH = "cadence/ledger-ids"  # the counter: a branch on origin, never merged, holding one file
COUNTER_FILE = "LAST"  # the last id given, as a number
TAKE_SUBJECT_RE = re.compile(r"^TD-(\d{1,9})(?:\.\.TD-(\d{1,9}))? \[skip ci\]$")
TAKE_NONCE_RE = re.compile(r"[0-9a-f]{32}")
TAKE_RANGE_MAX = 100  # the widest range a take is read as giving; the writers take at most 10
TAKE_FIELDS = ("by", "branch", "host", "take")
UNHASHED_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[^\s@]+@[^\s@]+\.[^\s@]+",
                         re.IGNORECASE)  # a bare session id or an email address, which a take publishes


def _tid(n: int) -> str:
    """An id at the ledger's width: three digits, more past 999."""
    return f"TD-{n:03d}"


def ids_held(files: Mapping[str, str]) -> set[int]:
    """Every id the files of a ledger and its archive hold (v2.4, SPEC *The next id*), as numbers: each
    file's headings and table rows outside HTML comments, and each entry file's name (``TD-NNN.md``, its
    path's last part). ``files`` maps a path to its text, in either layout. Refused when a file declares a
    newer major of the format than this module reads: its ids cannot be judged."""
    out: set[int] = set()
    for path, text in files.items():
        text = text or ""
        if format_major(text) > FORMAT_MAJOR:
            raise Refused(f"{path} declares Ledgerboard: {format_major(text)}, newer than this module reads "
                          f"({FORMAT_MAJOR}) — its ids are not read")
        m = ENTRY_FILE_RE.match(str(path).replace("\\", "/").rsplit("/", 1)[-1])
        if m:
            out.add(int(m.group(1)))
        bare = COMMENT_RE.sub("", text)
        out |= heading_nums(bare) | {int(r.group(2)) for r in ROW_RE.finditer(bare)}
    return out


def next_id(last: str | None, ids: Iterable[int], floor: int | None = None) -> tuple[int, list[str]]:
    """(the next id's number, warnings) (v2.4): one above the highest of the counter's ``LAST`` (its text;
    absent or not a number is ignored, with a warning), ``ids`` (ids_held() of the default branch, and any
    the caller adds) and ``floor`` (a front end's own last-given id)."""
    warnings: list[str] = []
    raw = (last or "").strip()
    top = [*ids, floor or 0]
    if raw.isascii() and raw.isdigit() and len(raw) <= 18:  # a number a counter could reach, never a giant
        top.append(int(raw))
    else:
        warnings.append(f"the counter's {COUNTER_FILE} is {'not a number (' + raw[:20] + ')' if raw else 'absent'}"
                        " — ignored; the ledger, archive and floor decide")
    return max(top) + 1, warnings


def parse_take(subject: str, body: str) -> dict | None:
    """One counter commit read as a take (v2.4, SPEC *The next id*): ``{ids, by, branch, host, take}`` — the
    ids its subject gives (``TD-n [skip ci]`` or the range ``TD-a..TD-b [skip ci]``, in order) and its body's
    ``name: value`` fields, those it has. None for a commit that is not a take's: another subject, a range that
    runs backwards or is wider than ``TAKE_RANGE_MAX``."""
    m = TAKE_SUBJECT_RE.match((subject or "").strip())
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    if lo < 1 or hi < lo or hi - lo + 1 > TAKE_RANGE_MAX:
        return None
    out: dict = {"ids": list(range(lo, hi + 1))}
    for ln in (body or "").splitlines():
        k, sep, v = ln.partition(":")
        if sep and k.strip() in TAKE_FIELDS and k.strip() not in out:  # names as written; the first wins
            if k.strip() != "take" or TAKE_NONCE_RE.fullmatch(v.strip()):  # a nonce is 32 lower-case hex, or none
                out[k.strip()] = v.strip()
    return out


def _take_named(t: Mapping) -> str:
    """A take as a failure names it: its by, date and short sha, never its nonce."""
    return f"{t.get('by') or 'unknown'} on {str(t.get('date') or '?')[:10]} ({str(t.get('sha') or '?')[:7]})"


def judge_takes(new_ids: Iterable[int], takes: Iterable[Mapping], entries: Iterable[str], branch: str | None,
                default: str, accept_taken_by: bool = False) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The merge gate's judgement of each new id against the counter's takes (v2.4, SPEC *The next id*):
    (fails, warns), each a list of (kind, text). ``takes`` are every take the counter holds, each a record
    of ``ids``, ``sha``, ``date``, ``by``, ``branch``, ``host`` and ``take`` (parse_take()'s, with the commit's
    sha and date); ``entries`` the ledger and archive texts holding the new entries; ``branch`` the one they
    are for and ``default`` the default branch. With no takes, nothing is judged.

    - ``id-untaken`` (fail): an id no take gave, at or above the counter's first; ``id-before-counter``
      (warn): one below it.
    - An id's ``Id take`` is judged alone wherever it is present: the nonce of any take that gave it passes
      (a range's for each of its ids; either take of an id given twice); ``id-take`` (fail): a nonce of
      another id's take (naming both ids) or of no take. A missing one is ``id-no-take`` (fail), unless
      ``accept_taken_by`` (the consumer's transition): then a ``Taken by`` naming a giving take's ``by`` warns
      ``id-no-take``, one naming another fails ``id-taken-by``, and none warns ``id-no-taken-by`` when a giving
      take has a ``by`` and the ledger declares no ``Fields:`` vocabulary (whose check would refuse the field).
    - An id whose entry is in none of ``entries`` is not judged past ``id-untaken``.
    - ``id-branch`` (warn): the take names a branch that is neither ``default`` nor ``branch``;
      ``id-by-unhashed`` (warn): its ``by`` is a bare session id or an email address.
    A failure names a take by its by, date and short sha, never its nonce."""
    takes = [t for t in takes if t.get("ids")]
    fails: list[tuple[str, str]] = []
    warns: list[tuple[str, str]] = []
    if not takes:
        return fails, warns
    gave: dict[int, list[Mapping]] = {}
    by_nonce: dict[str, list[Mapping]] = {}
    for t in takes:
        for n in t["ids"]:
            gave.setdefault(int(n), []).append(t)
        if t.get("take"):
            by_nonce.setdefault(str(t["take"]).strip(), []).append(t)
    first = min(gave)
    new = sorted({int(n) for n in new_ids})
    nobody = [n for n in new if n not in gave and n >= first]
    before = [n for n in new if n not in gave and n < first]
    if nobody:
        fails.append(("id-untaken", f"{', '.join(map(_tid, nobody))} handed out by nobody: the counter gave no such "
                      "id — take ids from the counter, and an id its fallback printed with its claim"))
    if before:
        warns.append(("id-before-counter", f"{', '.join(map(_tid, before))} below the counter's first take "
                      f"({_tid(first)}): older than the counter, not judged against it"))
    fields: dict[int, dict] = {}
    texts = [t or "" for t in entries]
    for t in texts:
        for e in _entries(t):
            fields.setdefault(_num(e["id"]), e["fields"])
    vocab = bool(texts) and bool(declared(texts[0])[0])  # a Fields: line refuses Taken by, so none is asked for
    wrong, missing, legacy, mismatch, untagged, elsewhere, unhashed = [], [], [], [], [], [], []
    for n in (n for n in new if n in gave and n in fields):  # an id with no entry given is not judged
        mine = gave[n]
        f = fields.get(n, {})
        nonce = (f.get("id take") or "").strip()
        used = mine
        if nonce:
            hit = [t for t in mine if str(t.get("take") or "").strip() == nonce]
            if hit:
                used = hit
            else:
                other = by_nonce.get(nonce, [])
                if other:
                    ids = sorted({int(x) for t in other for x in t["ids"]})
                    wrong.append(f"{_tid(n)}'s Id take is the take of {', '.join(map(_tid, ids))} "
                                 f"({_take_named(other[0])}), not one of {_tid(n)}'s ({'; '.join(map(_take_named, mine))})")
                else:
                    wrong.append(f"{_tid(n)}'s Id take names no take the counter holds — {_tid(n)} was handed out "
                                 f"by {'; '.join(map(_take_named, mine))}")
        elif not accept_taken_by:
            missing.append(f"{_tid(n)} (handed out by {'; '.join(map(_take_named, mine))})")
        else:
            said = first_word(f.get("taken by"))
            hit = [t for t in mine if said and first_word(t.get("by")) == said]
            if hit:
                used = hit
                legacy.append(_tid(n))
            elif said:
                handed = ", ".join(dict.fromkeys((t.get("by") or "unknown") for t in mine))
                mismatch.append(f"{_tid(n)} was handed to {handed}, not {said}")
            elif any(t.get("by") for t in mine) and not vocab:
                untagged.append(_tid(n))
        if any((t.get("branch") or "").strip() and (t.get("branch") or "").strip() not in (default, branch or "")
               for t in used):
            elsewhere.append(f"{_tid(n)} ({', '.join(dict.fromkeys(str(t.get('branch')).strip() for t in used))})")
        if any(UNHASHED_RE.search(str(t.get("by") or "")) for t in used):
            unhashed.append(_tid(n))
    if wrong:
        fails.append(("id-take", "; ".join(wrong) + " — write the Id take of the take that gave this id"))
    if missing:
        fails.append(("id-no-take", f"no **Id take:** on {', '.join(missing)} — write its take's nonce in the header"))
    if mismatch:
        fails.append(("id-taken-by", "; ".join(mismatch) + " — an id is the session's the counter handed it to; "
                      "take this entry its own"))
    if legacy:
        warns.append(("id-no-take", f"a matching **Taken by:** but no **Id take:** on {', '.join(legacy)} — write its "
                      "take's nonce in the header"))
    if untagged:
        warns.append(("id-no-taken-by", f"no **Id take:** or **Taken by:** on {', '.join(untagged)} — write its "
                      "take's nonce in the header"))
    if elsewhere:
        warns.append(("id-branch", f"taken for another branch: {', '.join(elsewhere)}"))
    if unhashed:
        warns.append(("id-by-unhashed", f"{', '.join(unhashed)} taken by a bare session id or an email address, "
                      "which the counter publishes — take ids with a hashed by"))
    return fails, warns


# ---------------------------------------------------------------------------------------------
# Lifting a gate (v2.4): one text edit every route writes, and the decide lift that composes it
# ---------------------------------------------------------------------------------------------

ARCHIVED_WORDS = ("resolved", "superseded", "dropped", "done", "moved", "obe")  # a Status only an archived entry has
LIFT_SUFFIX_RE = re.compile(rf"board (?P<repo>{REPO})|no board item|shared board item left open")
EVIDENCE_PR_RE = re.compile(rf"(?P<repo>{REPO})#(?P<n>[0-9]{{1,18}})")
EVIDENCE_AT_RE = re.compile(rf"(?P<repo>{REPO})@(?P<sha>[0-9a-f]{{7,40}})")
LOG_TOKEN_RE = re.compile(LOG_TOKEN)


def _host_log_evidence_ok(ev: str, source: str) -> bool:
    """A ``host-log`` lift's evidence (v2.5): a token of ``[A-Za-z0-9_.@/-]+``, the check's own source then ``/``
    and an id holding no empty, ``.`` or ``..`` segment, or ``@`` and ``YYYYMMDDTHHMMSSZ`` (its shape, not the calendar)."""
    if not LOG_TOKEN_RE.fullmatch(ev):
        return False
    if ev.startswith(f"{source}@"):
        return bool(HOST_LOG_AT_RE.fullmatch(ev[len(source) + 1:]))
    return ev.startswith(f"{source}/") and all(x not in ("", ".", "..") for x in ev[len(source) + 1:].split("/"))


def _one_gate(gate: object) -> str:
    """``gate`` as the writers write it — ``decision (<person>)``, ``until YYYY-MM-DD`` or ``event (<name>)`` —
    or Refused."""
    g = parse_gates(gate if isinstance(gate, str) else "")
    items = gate_items(g)
    if len(items) != 1 or g["ids"] or g["bad"] or g["retired"]:
        raise Refused(f"a gate is decision (<person>), until YYYY-MM-DD or event (<name>), one of them, not {gate!r}")
    return items[0]


def _blocked_items(raw: str | None) -> list[str]:
    """One Blocked by value's items as written, in order; the old form's last item runs to the line's end."""
    out, rest = [], (raw or "").strip(" \t\r")
    while rest:
        m = GATE_ITEM_SEP_RE.search(rest)
        item, after = (rest[: m.start()], rest[m.end():]) if m else (rest, "")
        d = GATE_DECISION_RE.match(item)
        if d and item[d.end():].strip(" \t"):
            out.append(rest)
            break
        if item:
            out.append(item)
        rest = after
    return out


def _item_gate_key(item: str) -> str | None:
    """The canonical key of one Blocked by item that is a readable gate, else None."""
    g = parse_gates(item)
    items = gate_items(g)
    return _gate_key(items[0]) if len(items) == 1 and not g["old_form"] else None


def _carried(text: str | None, gate: str) -> str | None:
    """The gate as the open entry ``text``'s Blocked by writes it (its person's spelling), or None when the
    entry is missing, archived or does not carry it."""
    if not text or not entries(text):
        return None
    e = entries(text)[0]
    if first_word(e["fields"].get("status")) in ARCHIVED_WORDS:
        return None
    key = _gate_key(gate)
    return next((x for x in gate_items(parse_gates(e["blocked_raw"])) if _gate_key(x) == key), None)


def _logged(text: str, what: str, value: str | None, lines: list[str], day: str) -> str:
    """The entry with its Blocked by set to ``value`` (None or "" removes the field) and ``lines`` appended to
    its Log, all dated ``day``; refused unless it reads back as exactly that."""
    m, header, body = _entry_parts(canonical(text))
    tid, title = m.group(1), m.group(3).strip()
    title_read = entries(canonical(text))[0]["title"]
    header = _with(header, "Blocked by", value or None)
    sections = _log_insert(_entry_sections(body), [(day, w) for w in lines], by_date=False)
    if any(re.search(r"\n[ \t]*\n", c.group(0)) for c in COMMENT_RE.finditer(body)):
        raise Refused("an HTML comment in the body spans paragraphs, so the Log line could land inside it — edit by hand")
    out = canonical(_render(tid, title, header, "\n\n".join(t for _, t in sections)))
    want = (tid, title_read, {field_key(n): v for n, v in header},
            [(_section_key(lead) if lead is not None else None, t) for lead, t in sections])
    e = entries(out)[0]
    got = (e["id"], e["title"], e["fields"],
           [(_section_key(lead) if lead is not None else None, t) for lead, t in _entry_sections(_entry_parts(out)[2])])
    tail = log_lines(out)[-len(lines):] if lines else []
    if got != want or [r["text"] for r in tail] != lines or any(r["kind"] in ("note", "malformed") for r in tail):
        raise Refused(f"after the {what} the entry would not read back as meant — edit by hand")
    return out


def _without(text: str, gate: str) -> tuple[str, str | None]:
    """(the gate as the entry writes it, its Blocked by without that gate), or Refused when it does not carry
    it; the other items keep their order and spelling (canonical when every one is readable)."""
    e = entries(text)[0]
    key = _gate_key(gate)
    items = _blocked_items(e["blocked_raw"])
    old = parse_gates(e["blocked_raw"])["old_form"]
    if old and _gate_key(f"decision ({old[0]})") == key:
        raise Refused(f"the entry's Blocked by holds {gate} in the old form — migrate it first: set "
                      "decision (<person>) alone, with its text in an **Ask:** section")
    at = next((i for i, x in enumerate(items) if _item_gate_key(x) == key), None)
    if at is None:
        raise Refused(f"{e['id']} does not carry {gate}")
    written = gate_items(parse_gates(items[at]))[0]
    rest = items[:at] + items[at + 1:]
    value = ", ".join(rest)
    g = parse_gates(value)
    return written, (", ".join(g["ids"] + gate_items(g)) if not (g["bad"] or g["retired"]) else value)


def lift_gate(text: str, gate: str, by: str, *, answer: str | None = None, evidence: str | None = None,
              suffix: str | None = None, override: str | None = None, today: date | str,
              people: list[str] | None = None, answered_by: str | None = None) -> str:
    """One open entry's text with ``gate`` removed from its Blocked by and the matching `gate lifted` Log line
    appended (v2.4, SPEC *Lifting a gate*): the one text edit every route writes — the person's ``set by=``,
    a host's event and ``until`` lifts, the cross-repo decision lift — and that decide_lift() composes. The
    inputs match one shape exactly, and anything else is refused:

    - ``decision (<p>)``: ``answer`` (never a waiting-only one), and ``suffix`` at most one of ``board <repo>``,
      ``no board item``, ``shared board item left open``; ``by`` is the gate's person, unless ``people`` (the
      board's `People:`) and ``answered_by`` ``any`` are passed, when it is anyone listed. Or ``override``
      (its why, required), when ``by`` may be any person: ``override: <why>``;
    - ``event (<name>)`` lifted by a person: ``answer``, with ``by`` on ``people``, which is then required;
    - ``event (<name>)`` lifted by a host: ``evidence``, ``<repo>#<n>`` for a ``pr-merged`` check,
      ``<repo>@<sha>`` for ``file-contains`` and ``ref-includes``, of the check's own repo (and PR), or (v2.5)
      for ``host-log`` the check's own source then ``/`` and the record's id (no empty, ``.`` or ``..``
      segment) or ``@`` and its UTC time as ``YYYYMMDDTHHMMSSZ``; the check type read from the entry's Event
      section; ``by`` is the host's token;
    - ``until D``: none of them; ``today`` (the UTC date) must have reached D.

    An emptied Blocked by is removed; the Log line carries the gate as the entry wrote it and ``by`` as given."""
    day = utc_day(today, "lift_gate()'s today")
    gate = _one_gate(gate)
    if not entries(text):
        raise Refused("lift_gate takes one entry's text")
    if first_word(entries(text)[0]["fields"].get("status")) in ARCHIVED_WORDS:
        raise Refused(f"{entries(text)[0]['id']} is archived — a gate is lifted only on an open entry")
    given = [k for k, v in (("answer", answer), ("evidence", evidence), ("suffix", suffix), ("override", override))
             if v is not None]
    by = " ".join(str(by or "").split())

    def only(*allowed: str) -> None:
        stray = [k for k in given if k not in allowed]
        if stray:
            raise Refused(f"lifting {gate} takes no {', '.join(stray)}")

    def label() -> str:
        said = _one_line("the answer", answer)
        if not said:
            raise Refused(f"lifting {gate} by a person's answer needs the answer")
        if waiting_only(said):
            raise Refused(f"{said!r} only keeps the gate waiting — it never lifts")
        return said
    on = {x.lower() for x in people or []}
    if answered_by is not None and answered_by.lower() not in ANSWERED_BY:
        raise Refused(f"Answered by is owner or any, not {answered_by!r}")
    if gate.startswith("decision"):
        person = gate[len("decision ("):-1]
        if not is_person(by):
            raise Refused(f"who lifts, {by!r}, is not a person's name")
        if override is not None:
            only("override")
            why = _one_line("the override's why", override)
            if not why:
                raise Refused("an override lift needs its why")
            written, value = _without(text, gate)
            return _logged(text, "lift", value, [f"gate lifted: {written} — by {by}; override: {why}"], day)
        only("answer", "suffix")
        said = label()
        tail = ""
        if suffix is not None:
            s = " ".join(str(suffix).split()).removeprefix("; ")
            if not LIFT_SUFFIX_RE.fullmatch(s):
                raise Refused(f"a suffix is board <repo>, no board item or shared board item left open, not {suffix!r}")
            tail = f"; {s}"
        if people is not None and (answered_by or "").lower() == "any":
            if by.lower() not in on:
                raise Refused(f"{by} is not on the board's People: ({', '.join(people)}) — only a listed person answers")
        elif by.lower() != person.lower():
            raise Refused(f"only {person} lifts {gate}, not {by} (the set route's, or a board without Answered by: any)")
        written, value = _without(text, gate)
        return _logged(text, "lift", value, [f"gate lifted: {written} — by {by}; answer \"{said}\"{tail}"], day)
    if override is not None:
        raise Refused(f"an override lifts a decision, not {gate}")
    if gate.startswith("until"):
        only()
        if not LOG_TOKEN_RE.fullmatch(by):
            raise Refused(f"who lifts, {by!r}, is a token of [A-Za-z0-9_.@/-]")
        if day < gate[len("until "):]:
            raise Refused(f"{gate} is not reached on {day}")
        written, value = _without(text, gate)
        return _logged(text, "lift", value, [f"gate lifted: {written} — by {by}; date reached"], day)
    name = gate[len("event ("):-1]
    if evidence is not None:
        only("evidence")
        if not LOG_TOKEN_RE.fullmatch(by):
            raise Refused(f"the host, {by!r}, is a token of [A-Za-z0-9_.@/-]")
        secs = [s for s in event_sections(text) if s["name"] == name]
        chk = secs[0]["check"] if len(secs) == 1 and not secs[0]["problem"] else None
        if chk is None:
            raise Refused(f"the entry has no readable **Event ({name}):** section to say which check passed")
        ev = " ".join(str(evidence).split())
        if chk["type"] == "host-log":
            if not _host_log_evidence_ok(ev, chk["source"]):
                raise Refused(f"a host-log check's evidence is {chk['source']}/<record id> or "
                              f"{chk['source']}@<YYYYMMDDTHHMMSSZ>, of its own source, not {evidence!r}")
            written, value = _without(text, gate)
            return _logged(text, "lift", value, [f"gate lifted: {written} — by {by}; host-log passed; {ev}"], day)
        m = (EVIDENCE_PR_RE if chk["type"] == "pr-merged" else EVIDENCE_AT_RE).fullmatch(ev)
        want = "<repo>#<n>, the merged PR" if chk["type"] == "pr-merged" else "<repo>@<sha>, where it was read"
        if not m or m.group("repo").lower() != chk["repo"].lower() \
                or (chk["type"] == "pr-merged" and int(m.group("n")) != chk["n"]):
            raise Refused(f"a {chk['type']} check's evidence is {want} of its own check, not {evidence!r}")
        written, value = _without(text, gate)
        return _logged(text, "lift", value, [f"gate lifted: {written} — by {by}; {chk['type']} passed; {ev}"], day)
    only("answer")
    said = label()
    if people is None:
        raise Refused(f"lifting {gate} by a person's answer needs the board's People:, who may answer it")
    if not is_person(by) or by.lower() not in on:
        raise Refused(f"{by} is not on the board's People: ({', '.join(people)}) — only a listed person answers")
    written, value = _without(text, gate)
    return _logged(text, "lift", value, [f"gate lifted: {written} — by {by}; answer \"{said}\""], day)


def reassign_gate(text: str, frm: str, to: str, *, by: str, why: str, today: date | str) -> str:
    """One open entry's text with ``decision (<frm>)`` replaced by ``decision (<to>)`` and the Log line
    ``gate reassigned: decision (<frm>) → decision (<to>) — by <by>; <why>`` (v2.4, SPEC *Lifting a gate*: the
    ``set`` route's reassign, which resets the gate's age). Refused: ``to`` the same person (in any case), an
    entry that does not carry ``frm``'s decision or already carries ``to``'s, and an empty why. Whether ``to``
    has a board is the consumer's to check."""
    day = utc_day(today, "reassign_gate()'s today")
    a, b, by = (" ".join(str(x or "").split()) for x in (frm, to, by))
    for who in (a, b, by):
        if not is_person(who):
            raise Refused(f"{who!r} is not a person's name")
    if a.lower() == b.lower():
        raise Refused(f"a reassign names another person: decision ({a}) is already {b}'s")
    said = _one_line("the reassign's why", why)
    if not said:
        raise Refused("a reassign needs its why")
    old = parse_gates(entries(text)[0]["blocked_raw"])["old_form"] if entries(text) else None
    if old and old[0].lower() == a.lower():
        raise Refused(f"the entry's Blocked by holds decision ({a}) in the old form — migrate it first: set "
                      "decision (<person>) alone, with its text in an **Ask:** section")
    if not entries(text) or _carried(text, f"decision ({a})") is None:
        raise Refused(f"the entry does not carry decision ({a}) on an open entry")
    if _carried(text, f"decision ({b})") is not None:
        raise Refused(f"the entry already waits on decision ({b}) — lift decision ({a}) instead")
    written, value = _without(text, f"decision ({a})")
    value = _written_blocked(", ".join(x for x in (value, f"decision ({b})") if x), entries(text)[0]["blocked_raw"])
    return _logged(text, "reassign", value, [f"gate reassigned: {written} → decision ({b}) — by {by}; {said}"], day)


def reassigns(text: str, gate: str) -> int:
    """How many times the gate ``gate`` (as the entry carries it) was reassigned to reach it: the run of
    ``gate reassigned`` Log lines leading to it, newest first, ending at a ``gate added`` or ``gate lifted`` of the
    gate it has reached (v2.4; check() notes one past two)."""
    n, cur = 0, _gate_key(gate)
    for rec in reversed(log_lines(text)):
        if rec["kind"] == "gate-reassigned" and _gate_key(rec["to"]) == cur:
            n, cur = n + 1, _gate_key(rec["gate"])
        elif rec["kind"] in ("gate-added", "gate-lifted") and _gate_key(rec["gate"]) == cur:
            break  # the gate was added afresh (or lifted, before it): the run ends there
    return n


def decide_lift(item_line: str, entries: Mapping[str, str], label: str, by: str, today: date | str,
                board_people: list[str] | None, answered_by: str | None) -> dict[str, str]:
    """The decide lift's ledger half (v2.4, SPEC *The decide lift*): ``{id: new_text}`` for each entry the answer
    ``label``, given by ``by``, changes, from the ``decide`` item ``item_line`` (the base board line) and
    ``entries`` (id to base text: its Context entry and each `Parts:` id). ``board_people`` and
    ``answered_by`` are the base board's `People:` (None: none, and its checks are skipped) and `Answered by:`
    (None: ``owner``). Whichever gate the Context names, ``decision (<p>)`` or ``event (<name>)``:

    - a lifting label (one of `Lifts:`, `Go` when it has none, compared in any case; never a waiting-only one)
      lifts the gate through lift_gate() on the Context entry, if it carries it, and on each listed part that
      does; each listed part that no longer does is logged on the Context entry as ``gate lift skipped``;
    - a waiting-only label (`Keep waiting`, `Not yet`) logs ``kept waiting`` on each of those that still carries
      it; for a decision, so does any other label; for an event, any other label writes nothing.

    Refused: an item that is not a ``decide`` naming one entry and one gate; another repo's entry (its lift is
    a tool PR there); a Context entry missing or archived; a `Parts:` id missing, of another repo, or not `Part
    of` the Context entry; a gate's person not on `People:`; an answerer not on `People:`, or, for a decision
    under ``owner``, not the gate's person."""
    day = utc_day(today, "decide_lift()'s today")
    got = parse_board(item_line if ITEM_RE.match(item_line) else "", warn=False)
    if len(got) != 1 or got[0].kind != "decide":
        raise Refused("decide_lift takes one open decide item line")
    item = got[0]
    ref, gate = _item_gate(item.text)
    if ref is None or gate is None:
        raise Refused("the item's Context names no one entry and one gate, decision (<person>) or event (<name>)")
    gate = _one_gate(gate)
    if "#" in ref:
        raise Refused(f"{ref} is another repo's entry — its lift is a tool PR there, through lift_gate")
    said = _one_line("the answer", label)
    by = " ".join(str(by or "").split())
    if not said:
        raise Refused("the answer is empty")
    if not is_person(by):
        raise Refused(f"who answered, {by!r}, is not a person's name")
    if answered_by is not None and answered_by.lower() not in ANSWERED_BY:
        raise Refused(f"Answered by is owner or any, not {answered_by!r}")
    on = {x.lower() for x in board_people or []}
    person = gate[len("decision ("):-1] if gate.startswith("decision") else None
    if board_people is not None:
        if person is not None and person.lower() not in on:
            raise Refused(f"the gate's person {person} is not on the board's People: ({', '.join(board_people)})")
        if by.lower() not in on:
            raise Refused(f"{by} is not on the board's People: ({', '.join(board_people)}) — only a listed person answers")
    owner = board_people is None or (answered_by or "owner").lower() == "owner"
    if person is not None and owner and by.lower() != person.lower():
        raise Refused(f"only {person} answers for {gate} on a board whose Answered by is owner, not {by}")
    by_num: dict[int, tuple[str, str]] = {}
    for k, v in entries.items():
        if _is_id(k):
            by_num.setdefault(_num(k), (k, v))
    if _num(ref) not in by_num or not _entries(by_num[_num(ref)][1]):
        raise Refused(f"{ref}, the item's Context entry, is not among the entries given")
    key, ctx_text = by_num[_num(ref)]
    if first_word(_entries(ctx_text)[0]["fields"].get("status")) in ARCHIVED_WORDS:
        raise Refused(f"{ref}, the item's Context entry, is archived — the answer lifts nothing; it takes review")
    parts = []
    for p in item.parts:
        if "#" in p:
            raise Refused(f"{p} is another repo's entry — a part is Part of its parent, in the same ledger")
        if _num(p) not in by_num or not _entries(by_num[_num(p)][1]):
            raise Refused(f"{p}, a part the item lists, is not among the entries given")
        pe = _entries(by_num[_num(p)][1])[0]
        par = parse_part_of(pe["part_of_raw"])[0]
        if par is None or "#" in par or _num(par) != _num(ref):
            raise Refused(f"{p}, a part the item lists, is not Part of {ref} — the snapshot does not match")
        parts.append(by_num[_num(p)])
    lifting = _lifting(said, item.lifts)
    if not lifting and not waiting_only(said) and person is None:
        return {}  # an event's work order ("Rewrite the check", "Drop the entry"): no ledger line
    out: dict[str, str] = {}
    targets = [(key, ctx_text), *parts]
    skipped = []
    for k, t in targets:
        written = _carried(t, gate)
        if written is None:
            if lifting and (k, t) != (key, ctx_text):
                skipped.append(_entries(t)[0]["id"])
            continue
        if lifting:
            out[k] = lift_gate(t, gate, by, answer=said, today=day,
                               people=board_people if board_people is not None else ([by] if person is None else None),
                               answered_by="any" if not owner else None)
        else:
            out[k] = _logged(t, "answer", _entries(t)[0]["blocked_raw"],
                             [f"kept waiting: {written} — by {by}; answer \"{said}\""], day)
    if skipped:
        spelled = _carried(ctx_text, gate) or gate
        out[key] = _logged(out.get(key, ctx_text), "lift", _entries(out.get(key, ctx_text))[0]["blocked_raw"],
                           [f"gate lift skipped: {s} no longer carries {spelled}" for s in skipped], day)
    return out


# ---------------------------------------------------------------------------------------------
# Events (v2.4): an event gate's section and its typed check
# ---------------------------------------------------------------------------------------------

EVENT_NEAR_RE = re.compile(r"^event\s*\(", re.IGNORECASE)  # a lead read as an Event section's, to say what is wrong with it
CHECK_LINE_RE = re.compile(r"^check:[ \t]+(?P<check>\S.*?)[ \t]*$")
# The check types (SPEC *Events*): each type's arguments, as written after its name. A new type states
# its four outcomes (CHECK_OUTCOMES) in SPEC and comes in a format PR.
CHECK_TYPES = {"pr-merged": "<repo>#<n>", "file-contains": '<repo>[@<ref>] <path> "<text>"',
               "ref-includes": "<repo>@<ref> <commit>",
               "host-log": '<source> [kind <kind>] [times <N>] "<text>"'}  # v2.5: answered by a host's reader
CHECK_OUTCOMES = ("passed", "not yet", "impossible", "error")
CHECK_N_RE = re.compile(r"[0-9]{1,18}")  # a forge's PR number; capped, so int() never meets a giant
CHECK_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
REF_BAD_CHARS = set("~^:?*[\\ #%&=+")  # git's, revision syntax's, and URL or query syntax in a forge API call
PATH_BAD_CHARS = set('*?[]#%"\\')  # a glob character, URL syntax in a forge path, the text's quote, a backslash
CHECK_ARG_SEP_RE = re.compile(r"[ \t]+")  # arguments are separated by spaces and tabs, never other whitespace
HOST_LOG_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")  # a host-log source or kind (v2.5): a name, never a path
HOST_LOG_TIMES_RE = re.compile(r"[1-9][0-9]{0,2}")  # a host-log count: 1 to 999, no leading zero
HOST_LOG_AT_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z")  # a host-log evidence's time, YYYYMMDDTHHMMSSZ (its shape only)
HOST_LOG_ID_MAX = 80  # the longest record id the evidence carries; a longer one falls back to the record's time


def _ref_problem(ref: str) -> str | None:
    """Why ``ref`` is not a ref a check may name (git's ``check-ref-format --allow-onelevel`` rules, a
    leading ``-``, ``..``, ``@{``, ``:``, any of ``^~?*[\\#%&=+``, whitespace or anything outside
    printable ASCII), or None."""
    if not ref:
        return "an empty ref"
    if ref.startswith("-"):
        return f"the ref {ref!r} starts with - (it would read as an option)"
    if ".." in ref or "@{" in ref or ref == "@":
        return f"the ref {ref!r} holds .., @{{ or is @ (revision syntax)"
    if any(c in REF_BAD_CHARS or not " " < c < "\x7f" for c in ref):
        return (f"the ref {ref!r} holds a character it may not: one git refuses or revision, URL or query syntax "
                "uses (~^:?*[\\#%&=+), whitespace, a control, or anything outside ASCII")
    if ref.endswith(("/", ".")) or "//" in ref:
        return f"the ref {ref!r} ends with / or ., or holds //"
    if any(not part or part.startswith(".") or part.endswith(".lock") for part in ref.split("/")):
        return f"the ref {ref!r} has a component that starts with . or ends with .lock"
    return None


def _path_problem(path: str) -> str | None:
    """Why ``path`` is not a path a check may read (absolute, an empty, ``.``, ``..`` or ``.git`` segment, a
    leading ``-``, a glob character, ``#``, ``%``, a quote, a backslash, whitespace, a control or anything
    outside printable ASCII), or None."""
    if not path:
        return "an empty path"
    if path.startswith("/"):
        return f"the path {path!r} is absolute"
    if path.startswith("-"):
        return f"the path {path!r} starts with - (it would read as an option)"
    segs = path.split("/")
    if ".." in segs:
        return f"the path {path!r} has a .. segment"
    if any(x in ("", ".") or x.lower() == ".git" for x in segs):
        return f"the path {path!r} has an empty, . or .git segment"
    if any(c in PATH_BAD_CHARS or not " " < c < "\x7f" for c in path):
        return (f"the path {path!r} holds a glob character, URL syntax (# or %), a quote, a backslash, "
                "whitespace, a control, or anything outside ASCII")
    return None


def _repo_problem(repo: str) -> str | None:
    return None if REPO_RE.fullmatch(repo) else \
        f"the repo {repo!r} is not a name or /-separated components of ASCII [A-Za-z0-9_.-] (none . or .., none starting with -)"


def parse_check(value: str) -> dict:
    """One ``check:`` line's value read (v2.4, SPEC *Events*): ``{type, repo, …, problem}``. By type:
    ``pr-merged`` gives ``n`` (an int); ``file-contains`` ``ref`` (None: the default branch), ``path`` and
    ``text``; ``ref-includes`` ``ref`` and ``commit``; ``host-log`` (v2.5, no ``repo``) ``source``, ``kind`` (None
    when absent), ``times`` (an int, 1 when absent) and ``text``. ``problem`` is None, or why ``check()`` refuses
    it: an unknown type, a missing or extra argument, or an argument outside its confinement. Arguments
    are separated by spaces; the text runs from its opening ``"`` to the line's last ``"`` and nothing
    follows it. Text is matched literally by the host, never as a pattern."""
    value = (value or "").strip(" \t")
    kind, rest = (CHECK_ARG_SEP_RE.split(value, maxsplit=1) + [""])[:2]
    out: dict = {"type": kind, "problem": None}

    def bad(why: str) -> dict:
        out["problem"] = why
        return out
    if kind not in CHECK_TYPES:
        return bad(f"unknown check type {kind!r} — one of {', '.join(CHECK_TYPES)}")
    text = None
    if kind in ("file-contains", "host-log"):  # the two types whose last argument is quoted text
        q = rest.find('"')
        if q < 0 or rest.rfind('"') == q:
            return bad(f'{kind} needs its text in quotes: {kind} {CHECK_TYPES[kind]}')
        if rest[rest.rfind('"') + 1:].strip(" \t"):
            return bad("nothing may follow the quoted text")
        if not rest[:q].endswith((" ", "\t")):
            return bad("the quoted text is an argument of its own: a space comes before its opening quote")
        text, rest = rest[q + 1: rest.rfind('"')], rest[:q]
        if not text.strip(" \t"):
            return bad("the quoted text is empty")
        if any(c < " " or c == "\x7f" for c in text):
            return bad("the quoted text holds a control character")
    args = [a for a in CHECK_ARG_SEP_RE.split(rest) if a]
    if kind == "host-log":
        return _host_log_args(out, args, text)
    want = {"pr-merged": 1, "file-contains": 2, "ref-includes": 2}[kind]
    if len(args) != want:
        return bad(f"{kind} takes {CHECK_TYPES[kind]}")
    if kind == "pr-merged":
        repo, sep, n = args[0].rpartition("#")
        out.update(repo=repo)
        if not sep:
            return bad(f"pr-merged takes {CHECK_TYPES[kind]}")
        if not CHECK_N_RE.fullmatch(n):
            return bad(f"the PR number {n!r} is not 1 to 18 of [0-9]")
        out["n"] = int(n)
        return bad(_repo_problem(repo)) if _repo_problem(repo) else out
    repo, at, ref = args[0].partition("@")
    out.update(repo=repo, ref=ref if at else None)
    if _repo_problem(repo):
        return bad(_repo_problem(repo))
    if kind == "ref-includes" and not at:
        return bad(f"ref-includes takes {CHECK_TYPES[kind]}: the ref is required")
    if at and _ref_problem(ref):
        return bad(_ref_problem(ref))
    if kind == "file-contains":
        out.update(path=args[1], text=text)
        return bad(_path_problem(args[1])) if _path_problem(args[1]) else out
    out["commit"] = args[1]
    if not CHECK_COMMIT_RE.fullmatch(args[1]):
        return bad(f"the commit {args[1]!r} is not 7 to 40 of [0-9a-f]")
    return out


def _host_log_args(out: dict, args: list[str], text: str) -> dict:
    """A ``host-log`` check's arguments before its text (v2.5): the source, then optionally ``kind`` and its token,
    then optionally ``times`` and its count, in that order — one, three or five tokens."""
    out.update(source=args[0] if args else None, kind=None, times=1, text=text)
    shape = f"host-log takes {CHECK_TYPES['host-log']}"
    if len(args) not in (1, 3, 5):
        out["problem"] = shape
        return out
    if not HOST_LOG_TOKEN_RE.fullmatch(args[0]):
        out["problem"] = f"the source {args[0]!r} is not 1 to 40 of [a-z0-9-], not starting with - (a name, never a path)"
        return out
    rest = args[1:]
    if rest and rest[0] == "kind":
        if not HOST_LOG_TOKEN_RE.fullmatch(rest[1]):
            out["problem"] = f"the kind {rest[1]!r} is not 1 to 40 of [a-z0-9-], not starting with -"
            return out
        out["kind"], rest = rest[1], rest[2:]
    if rest and rest[0] == "times":
        if not HOST_LOG_TIMES_RE.fullmatch(rest[1]):
            out["problem"] = f"the count {rest[1]!r} is not 1 to 999, with no leading zero"
            return out
        out["times"], rest = int(rest[1]), rest[2:]
    if rest:
        out["problem"] = f"{shape}: kind, then times, each once, in that order"
    return out


def parse_event_section(text: str) -> dict:
    """One ``**Event (<name>):**`` section read (v2.4, SPEC *Events*): ``{name, words, check, problem,
    first}`` (``first``: its first line as written; ``name`` None when its lead is not an Event's).
    It is two lines: the lead and the event in plain words, then exactly one ``check: <type> <args>``
    (``check`` is ``parse_check()``'s reading of it, or None). ``problem`` is None, or why ``check()``
    refuses the section: a name outside ``[a-z0-9-]+``, no words, no ``check:`` line, more than one, a
    line after it, words past the first line, or the check's own problem."""
    lines = [ln.rstrip(" \t") for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    m = re.match(r"^\*\*Event \((?P<name>[^()]*)\):\*\*(?P<words>.*)$", lines[0] if lines else "")
    out: dict = {"name": m.group("name") if m else None, "words": "", "check": None, "problem": None,
                 "first": lines[0] if lines else ""}
    if not m:
        out["problem"] = "not an Event section: its lead is **Event (<name>):**"
        return out
    out["words"] = m.group("words").strip()
    checks = [i for i, ln in enumerate(lines) if ln.startswith("check:")]
    if not EVENT_NAME_RE.fullmatch(out["name"]):
        out["problem"] = f"the event name {out['name']!r} is not [a-z0-9-]+"
    elif not m.group("words").strip():
        out["problem"] = "its first line says the event in plain words, after the lead"
    elif not checks:
        out["problem"] = "it has no check: line — the last line is check: <type> <args>"
    elif len(checks) > 1:
        out["problem"] = f"it has {len(checks)} check: lines — exactly one"
    elif checks[0] != len(lines) - 1:
        out["problem"] = "a line follows its check: line — the check is the section's last line"
    elif checks[0] != 1:
        out["problem"] = "its words run past the first line — the event in plain words is one line, the check the second"
    else:
        cm = CHECK_LINE_RE.match(lines[checks[0]])
        out["check"] = parse_check(cm.group("check")) if cm else None
        if out["check"] is None:
            out["problem"] = "its check: line names no check — check: <type> <args>, a space after the colon"
        elif out["check"]["problem"]:
            out["problem"] = f"its check: {out['check']['problem']}"
    return out


def event_sections(text: str) -> list[dict]:
    """Every ``**Event (…):**`` section of one entry's text, in order, each as ``parse_event_section()``
    reads it."""
    try:
        body = _entry_parts(text)[2]
    except Refused:
        body = text.split("\n", 1)[1] if "\n" in text else ""
    return [parse_event_section(t) for lead, t in _entry_sections(body.replace("\r\n", "\n"))
            if lead is not None and EVENT_NEAR_RE.match(lead)]


def event_problems(text: str, old_text: str | None = None, today: date | str | None = None
                   ) -> list[tuple[str, str, str]]:
    """What ``check()`` says of one open entry's events (v2.4, SPEC *Events*): [(level, kind, sentence)].
    ``event-section`` (error): an ``event (<name>)`` gate with no section, or two sections of one name;
    ``event-check`` (error): a section ``parse_event_section()`` refuses; ``event-ungated`` (info): a
    section whose gate is gone with no ``gate lifted: event (<name>)`` Log line to say why; ``event-undated``
    (error, v2.5): a gate whose section's check is ``host-log`` with no ``gate added`` day (``gate_added()``),
    or, given ``old_text`` (the entry before an edit, ``""`` for none) and ``today``, whose wait the edit
    changed and did not date anew (SPEC *Events*)."""
    found = entries(text)
    gates = parse_gates(found[0]["blocked_raw"])["events"] if found else []
    secs = event_sections(text)
    out: list[tuple[str, str, str]] = []
    names = [x["name"] for x in secs]
    for n in dict.fromkeys(gates):
        if n not in names:
            out.append(("error", "event-section", f"Blocked by names event ({n}) and the entry has no "
                        f"**Event ({n}):** section — its words, then check: <type> <args>"))
    for n in dict.fromkeys(names):
        if names.count(n) > 1:
            out.append(("error", "event-section", f"it has {names.count(n)} **Event ({n}):** sections — one per "
                        "name; a re-added gate reuses its section"))
    try:
        lifted = {r["gate"] for r in log_lines(text) if r["kind"] == "gate-lifted"}
    except Refused:
        lifted = set()
    for x in secs:
        if x["problem"]:
            led = f"**Event ({x['name']}):**" if x["name"] is not None else repr(x["first"])
            out.append(("error", "event-check", f"its {led} section: {x['problem']}"))
        if x["problem"] and (x["name"] is None or not EVENT_NAME_RE.fullmatch(x["name"])):
            continue  # its lead or name is refused already: no gate could name it
        if x["name"] not in gates and f"event ({x['name']})" not in lifted:
            out.append(("info", "event-ungated", f"its **Event ({x['name']}):** section has no event "
                        f"({x['name']}) gate, and no gate lifted: event ({x['name']}) Log line says why"))
    for n in dict.fromkeys(gates):
        chk = _host_log_check(secs, n)
        if chk is None:
            continue
        gate = f"event ({n})"
        if gate_added(text, gate) is None:
            out.append(("error", "event-undated", f"its {gate} gate's host-log check has no gate added: {gate} Log "
                        "line to count from (none, or a gate lifted after the last)"))
        elif old_text is not None and today is not None and _wait_changed(old_text, n, chk) \
                and not _dated_anew(old_text, text, gate, utc_day(today, "today")):
            out.append(("error", "event-undated", f"its {gate} gate's host-log wait is new or changed, and no "
                        f"gate added: {gate} Log line dated today dates it anew"))
    return out


def _host_log_check(secs: list[dict], name: str) -> dict | None:
    """The ``host-log`` check of the one readable ``**Event (<name>):**`` section, as ``lift_gate`` reads it, or None."""
    mine = [x for x in secs if x["name"] == name]
    if len(mine) != 1 or mine[0]["problem"] or mine[0]["check"] is None or mine[0]["check"]["type"] != "host-log":
        return None
    return mine[0]["check"]


def _host_log_key(chk: dict) -> tuple:
    return chk["source"], chk["kind"], chk["times"], chk["text"]


def _wait_changed(old_text: str, name: str, chk: dict) -> bool:
    """Whether, against the entry's old text, ``event (<name>)`` is newly carried, or its ``host-log`` check is new,
    became ``host-log`` or changed its source, kind, count or text (v2.5): spacing alone is no change."""
    found = entries(old_text) if old_text else []
    if not found or name not in parse_gates(found[0]["blocked_raw"])["events"]:
        return True
    was = _host_log_check(event_sections(old_text), name)
    return was is None or _host_log_key(was) != _host_log_key(chk)


def _dated_anew(old_text: str, text: str, gate: str, today: str) -> bool:
    """A changed wait dated anew (v2.5, SPEC *Events*): (a) the gate's ``gate added`` lines in the new Log, as
    (date, gate) pairs in Log order, are its old ones followed by at least one more, the last dated L; (b) floor
    ≤ L ≤ today, the floor the old Log's latest readable date, else the entry's Added date, else none, lowered
    to today when after it; (c) with an old ``gate added`` line for the gate (the last dated P), L is today or
    after P. An old or new Log that cannot be read is never dated anew."""
    key = _gate_key(gate)
    try:
        old_recs = log_lines(old_text) if old_text and entries(old_text) else []
        new_recs = log_lines(text)
    except Refused:
        return False

    def added(recs: list[dict]) -> list[tuple[str, str]]:
        return [(r["date"], key) for r in recs if r["kind"] == "gate-added" and _gate_key(r["gate"]) == key]
    was, now = added(old_recs), added(new_recs)
    if len(now) <= len(was) or now[:len(was)] != was:
        return False
    last = now[-1][0]
    dates = [r["date"] for r in old_recs if r["date"] is not None]
    if dates:
        floor = max(dates)
    else:
        m = ISO_DAY_RE.search(_value(_entry_parts(text)[1], "added") or "")
        floor = m.group(0) if m else None
    if floor is not None and floor > today:
        floor = today
    if (floor is not None and last < floor) or last > today:
        return False
    return not was or last == today or last > was[-1][0]


def first_instant(since: date | str) -> datetime:
    """The first instant a ``host-log`` check counts (v2.5, SPEC *Host-log checks*): 00:00 UTC of the day after
    ``since`` (``gate_added()``'s date, or ``YYYY-MM-DD``), an aware datetime."""
    day = date.fromisoformat(utc_day(since, "since"))
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)


def _host_log_token(source: str, rec: Mapping) -> str:
    rid = rec.get("id")
    if isinstance(rid, str) and len(rid) <= HOST_LOG_ID_MAX and _host_log_evidence_ok(f"{source}/{rid}", source):
        return f"{source}/{rid}"
    return f"{source}@{rec['at'].astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def count_host_log(records: Iterable[Mapping], chk: Mapping, since: date | str, *, public_only: bool) -> dict:
    """A ``host-log`` check counted over the records a reader yields (v2.5, SPEC *Host-log checks*):
    ``{"outcome": "passed" | "not yet", "count", "evidence"}``. A record ``{at, kind, text, id, public}`` counts when
    ``at`` is at or after ``first_instant(since)``, its ``kind`` equals the check's (when it names one), its
    ``text`` (a string) contains the check's text, and, with ``public_only``, ``public`` is true. ``count`` is
    every counted record; passed when it reaches the check's ``times``, the evidence the N-th by ``at``, then
    ``id`` (none first). Refused: ``chk`` not a ``host-log`` record without a problem, a record whose ``at`` is
    not an aware datetime. Reading errors are the reader's, which this cannot see."""
    if not isinstance(chk, Mapping) or chk.get("type") != "host-log" or chk.get("problem"):
        raise Refused("count_host_log takes parse_check()'s record of a host-log check with no problem")
    start = first_instant(since)
    counted = []
    for rec in records:
        at = rec.get("at")
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise Refused(f"a record's at is an aware datetime, not {at!r}")
        txt = rec.get("text")
        if (at >= start and isinstance(txt, str) and chk["text"] in txt
                and (chk["kind"] is None or rec.get("kind") == chk["kind"])
                and (not public_only or rec.get("public") is True)):
            counted.append(rec)
    counted.sort(key=lambda r: (r["at"], (0, "") if r.get("id") is None else (1, str(r.get("id")))))
    n = chk["times"]
    passed = len(counted) >= n
    return {"outcome": "passed" if passed else "not yet", "count": len(counted),
            "evidence": _host_log_token(chk["source"], counted[n - 1]) if passed else None}


# ---------------------------------------------------------------------------------------------
# The gate sweep (v2.4): what a host's periodic sweep files, closes and lifts — decided here, its I/O the host's
# ---------------------------------------------------------------------------------------------

COVER_STATES = ("open", "decided", "closed", "closed-decided")  # covers()'s states; the first two cover
SWEEP_REASK_DAYS = 30  # the consumer's numbers' defaults (SPEC *The gate sweep*); the rules are the module's
SWEEP_EVENT_AGE_DAYS = 30
# Each sweep item's condition, by the fixed words its text carries (its head), tried in this order. A `decide`
# item keyed to a decision gate and carrying none of them is the decision's own item: its condition is
# `uncovered`.
SWEEP_HEADS = (("no-board", "has no board"), ("broken", "Event check broken"),
               ("impossible", "can no longer happen"), ("still", "Still waiting on"),
               ("audit", "holds no decided item"))
SWEEP_KINDS = {"no-board": "act", "broken": "act", "impossible": "decide", "still": "decide", "audit": "act",
               "uncovered": "decide"}
SWEEP_DECISION_ANSWERS = ("Go", "Not yet")
SWEEP_IMPOSSIBLE_ANSWERS = ("Drop the gate", "Rewrite the check", "Drop the entry")
SWEEP_STILL_ANSWERS = ("Keep waiting", "Drop the gate", "Rewrite the check")
SWEEP_EVENT_LIFTS = ("Drop the gate",)


def _board_name(board: Sequence) -> str:
    """A board's name in the sweep's output: its origin's pick key, else its checkout basename."""
    return origin_key(board[0] or "") or str(board[1])


def _board_pick_key(board: Sequence) -> tuple:
    """The person's-board pick order (SPEC *The gate sweep*): keyed boards bytewise by origin_key, then the
    boards with no readable origin by lowercased basename."""
    key = origin_key(board[0] or "")
    return (0, key.encode()) if key else (1, str(board[1]).lower().encode())


def _own_board(boards: Sequence[Sequence], repo: str) -> Sequence | None:
    by_path = [b for b in boards if origin_path(b[0] or "") == repo.lower()]
    return (by_path or [b for b in boards if str(b[1]).lower() == repo.lower()] or [None])[0]


def _ours(ref: str | None, own: bool, repo: str) -> int | None:
    """The number of this repo's entry ``ref`` names, read on a board (``own``: this repo's), or None: on this
    repo's board a bare ``TD-n``, and on any board ``<repo>#TD-n`` naming this repo (case-insensitively)."""
    if not ref:
        return None
    other, sep, tid = ref.rpartition("#")
    if not sep:
        return _num(ref) if own and _is_id(ref) else None
    return _num(tid) if other.lower() == repo.lower() and _is_id(tid) else None


def _sweep_context(text: str, own: bool, repo: str) -> tuple[int, str, str] | None:
    """An item's Context read as the sweep keys it: (this repo's entry number, the gate's key, the qualifier
    after the gate — ``""``, ``lift`` or ``board <repo>``, lowercased), or None when it names no entry of this
    repo with one gate."""
    ref, gate = _item_gate(text)
    num = _ours(ref, own, repo)
    if num is None or gate is None:
        return None
    c = CONTEXT_RE.search(_gate_body(text))
    ctx = c.group("ctx") if c else ""
    g = CONTEXT_ANY_GATE_RE.search(ctx)
    qual = " ".join(ctx[g.end():].strip().rstrip(".").split()).lower() if g else ""
    return num, _gate_key(gate), qual


def _sweep_head(text: str) -> str | None:
    return next((cond for cond, words in SWEEP_HEADS if words in text), None)


def _read_boards(boards: Sequence[Sequence], repo: str) -> list[dict]:
    """Every item of every board read, open and closed (the board's and its archive's), each with what the
    sweep compares: {board, own, item, line (the open item's line as written, else None), state, ctx, head}."""
    out = []
    mine = _own_board(boards, repo)
    for b in boards:
        name, own = _board_name(b), b is mine
        text, archive = str(b[2] or ""), str(b[3] or "")
        lines = text.splitlines()
        reads = [(it, lines[it.line - 1], "decided" if it.decided else "open") for it in parse_board(text, warn=False)]
        reads += [(it, None, "closed-decided" if it.decided else "closed")
                  for src in (text, archive) for it in parse_closed_items(src)]
        for it, line, state in reads:
            out.append({"board": name, "own": own, "item": it, "line": line, "state": state,
                        "ctx": _sweep_context(it.text, own, repo), "head": _sweep_head(it.text),
                        "people": board_people(text)})
    return out


def _names_entry(r: dict, num: int, gate_key: str, parent: int | None, repo: str) -> bool:
    """Whether a read item names entry ``num`` and the gate, or its parent with the gate and the entry among
    its `Parts:` snapshot."""
    if r["ctx"] is None or r["ctx"][1] != gate_key or r["ctx"][2]:
        return False
    if r["ctx"][0] == num:
        return True
    return parent is not None and r["ctx"][0] == parent and any(
        _ours(p, r["own"], repo) == num for p in r["item"].parts)


def _covers(reads: list[dict], num: int, gate: str, parent: int | None, repo: str) -> list[dict]:
    key = _gate_key(gate)
    d = GATE_DECISION_RE.match(gate)
    who = d.group("who").lower() if d else None
    return [r for r in reads if r["item"].kind == "decide" and _names_entry(r, num, key, parent, repo)
            and (who is None or who in {p.lower() for p in (r["people"] or [])})]


def covers(entry_text: str, gate: str, boards: Sequence[Sequence], repo: str) -> list[tuple[str, BoardItem, str]]:
    """The board items that ask about one entry's gate (v2.4, SPEC *The gate sweep*): each ``decide`` item whose
    Context names the entry and the gate, or names the entry's parent (its ``Part of``) with the gate and the
    entry among its ``Parts:``, on a board whose ``People:`` lists the gate's person (an event gate has no
    person, so any board). ``boards`` is ``[(origin_url, basename, text, archive_text)]``; ``repo`` this repo's
    ``origin_path`` (else its basename), which a ``<repo>#TD-n`` ref must name. On this repo's own board (its
    origin path, else its basename, is ``repo``) a bare ``TD-n`` is this repo's. Returns ``[(board name, item,
    state)]``, the board named by its ``origin_key``, else its basename, and the state ``open``, ``decided``
    (open, with ``Decided:``), ``closed`` or ``closed-decided`` (closed, on the board or in its archive). Only
    ``open`` and ``decided`` cover."""
    ents = entries(entry_text)
    if not ents:
        raise Refused("covers() reads one entry's text, and this has no `## TD-n:` heading")
    gate = _one_gate(gate)
    parent, _ = parse_part_of(ents[0]["part_of_raw"])
    return [(r["board"], r["item"], r["state"])
            for r in _covers(_read_boards(boards, repo), _num(ents[0]["id"]), gate,
                             _num(parent) if parent else None, repo)]


def _entry_ask(text: str, title: str) -> str:
    """The entry's Ask as one line: its ``**Ask:**`` section's words, else its title."""
    try:
        sections = _entry_sections(_entry_parts(text)[2])
    except Refused:
        sections = []
    at = _keyed(sections, "ask")
    if at:
        words = " ".join(sections[at[0]][1].split())
        words = words[len("**Ask:**"):].strip() if words.startswith("**Ask:**") else words
        if words:
            return words
    return title


def _answered_within(r: dict, today: date, days: int) -> bool:
    """A read item answered without a lift within ``days`` of ``today``: its ``Decided:`` label does not lift
    and its date is newer than the window."""
    it = r["item"]
    return bool(it.decided) and not _lifting(it.decided[0], it.lifts) and (today - it.decided[1]).days < days


def _log(text: str) -> list[dict]:
    """The entry's Log, or nothing when its body cannot be read (two Log sections, no heading)."""
    try:
        return log_lines(text) if text else []
    except Refused:
        return []


def _kept_waiting_within(text: str, gate: str, today: date, days: int) -> bool:
    key = _gate_key(gate)
    for rec in _log(text):
        if rec["kind"] == "kept-waiting" and _gate_key(rec["gate"]) == key and rec["date"]:
            if (today - date.fromisoformat(rec["date"])).days < days:
                return True
    return False


def _gone(reads_num: int, gate: str, parts: list[str], own: bool, repo: str,
          open_texts: Mapping[int, str], known: set[int]) -> bool | None:
    """Whether the gate is gone from an item's Context entry and every listed part: True, False, or None when
    the Context entry is in neither the ledger nor the archive (its item is left for a person)."""
    if reads_num not in known:
        return None
    nums = [reads_num] + [n for n in (_ours(p, own, repo) for p in parts) if n is not None]
    return not any(_carried(open_texts.get(n), gate) for n in nums)


def _outcome(results: Mapping, tid: str, name: str) -> tuple[str | None, str | None]:
    """A check's (outcome, evidence) from ``results``: a bare outcome, or an ``(outcome, evidence)`` pair; an
    empty pair, or none at all, is no outcome."""
    got = results.get((tid, name))
    if isinstance(got, (tuple, list)):
        return (got[0] if got else None, got[1] if len(got) > 1 else None)
    return (got, None)


def _sweep_text(cond: str, tid: str, gate: str, extra: str = "") -> str:
    name = gate[gate.index("(") + 1: -1] if "(" in gate else gate
    return {"no-board": f"{gate} on {tid} has no board: no board read lists {name} in its People.",
            "broken": f"Event check broken on {tid}: the check for {gate} errors.",
            "impossible": f"{gate} on {tid} can no longer happen.",
            "still": f"Still waiting on {gate} for {tid}?",
            "audit": f"{tid}'s {gate} was lifted by an answer on {extra}'s board, which holds no decided item "
                     f"for {tid}."}[cond]


def _sweep_item(cond: str, tid: str, ref: str, gate: str, *, ask: str = "", title: str = "", extra: str = "",
                reask_days: int = SWEEP_REASK_DAYS) -> dict:
    """One item the sweep files, as ``item_line()``'s arguments (the host adds today, its Due:, session and
    host): {text, context, kind, answers, default, detail, lifts}."""
    kind = SWEEP_KINDS[cond]
    ctx = f"{ref} {gate}" + (" board " + extra if cond == "audit" else "")
    out: dict = {"text": ask if cond == "uncovered" else _sweep_text(cond, tid, gate, extra), "context": ctx,
                 "kind": kind, "answers": None, "default": None, "detail": None, "lifts": None}
    if cond == "uncovered":
        name = gate[gate.index("(") + 1: -1]
        out.update(answers=list(SWEEP_DECISION_ANSWERS), detail={
            "context": f"{tid} ({title}) waits on {gate}, and no board item asked for it",
            "question": ask,
            "recommended": f"Only {name} can say: Go lifts the gate, and Not yet keeps it waiting, asked again "
                           f"in {reask_days} days"})
    elif cond == "impossible":
        out.update(answers=list(SWEEP_IMPOSSIBLE_ANSWERS), lifts=list(SWEEP_EVENT_LIFTS), detail={
            "context": f"The check for {gate} on {tid} says it can no longer happen",
            "question": "Drop the gate, rewrite its check, or drop the entry?",
            "recommended": "Only the person who knows why it waits can say"})
    elif cond == "still":
        out.update(answers=list(SWEEP_STILL_ANSWERS), default=0, lifts=list(SWEEP_EVENT_LIFTS), detail={
            "context": f"{tid} has waited on {gate} for more than its age limit, and its check says not yet",
            "question": "Keep waiting, drop the gate, or rewrite its check?",
            "recommended": f"it is asked again in {reask_days} days"})
    return out


def sweep(entries: Iterable[str], boards: Sequence[Sequence], results: Mapping, today_utc: date | str,
          today_local: date | str, reask_days: int = SWEEP_REASK_DAYS, event_age_days: int = SWEEP_EVENT_AGE_DAYS,
          repo: str = "") -> dict:
    """What one sweep of this repo's ledger does (v2.4, SPEC *The gate sweep*): ``{to_file: {board: [item]},
    to_close: {board: [item key]}, lifts: [{id, gate, kind, evidence}]}``, each board named as ``covers()``
    names it. It keeps no state: the boards and the ledger's Log are its state, so a second run over its own
    writes files and closes nothing.

    ``entries`` are this repo's ledger and archive texts (an entry is open unless its Status is an archived
    one); ``boards`` ``[(origin_url, basename, text, archive_text)]``, this repo's own among them; ``results``
    maps ``(TD-n, event name)`` to a check's outcome (``passed``, ``not yet``, ``impossible``, ``error``) or to
    ``(outcome, evidence)``; ``today_utc`` dates the Log's ages and an ``until``, ``today_local`` the boards'
    ``Decided:`` dates; ``repo`` is this repo's ``origin_path`` (else its basename). Each item filed is
    ``item_line()``'s arguments, the host adding today, its Due:, session and host."""
    today_u = date.fromisoformat(utc_day(today_utc, "today_utc"))
    if isinstance(today_local, datetime):
        today_local = today_local.date()  # the caller's own civil date: its zone is the caller's
    today_l = date.fromisoformat(_civil_date(today_local.isoformat() if isinstance(today_local, date)
                                             else today_local, "today_local is written"))
    for what, n in (("reask_days", reask_days), ("event_age_days", event_age_days)):
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise Refused(f"{what} is a whole number of days, not {n!r}")
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
        raise Refused(f"repo is this repo's origin path (owner/name) or its basename, not {repo!r}")
    own = _own_board(boards, repo)
    if own is None:
        raise Refused(f"boards holds no board of {repo}: its own board is where event items go")
    own_name = _board_name(own)
    texts: dict[int, str] = {}
    open_texts: dict[int, str] = {}
    for t in entries:
        for tid, body in _entry_texts(str(t or "")).items():
            n = _num(tid)
            if n in open_texts:
                continue  # the ledger's open copy is read over an archived one
            texts[n] = body
            e = _entries(body)[0]
            if first_word(e["fields"].get("status")) not in ARCHIVED_WORDS:
                open_texts[n] = body
    known = set(texts)
    reads = _read_boards(boards, repo)
    to_file: dict[str, list[dict]] = {}
    to_close: dict[str, list[str]] = {}
    lifts: list[dict] = []
    filed: set[tuple] = set()

    def add(board: str, num: int, gate: str, cond: str, item: dict, qual: str = "") -> None:
        """File ``item`` unless this run already filed its identity (a gate written twice, a lift logged twice)."""
        key = (board, num, _gate_key(gate), cond, qual)
        if key not in filed:
            filed.add(key)
            to_file.setdefault(board, []).append(item)

    def same(r: dict, num: int, gate: str, cond: str, qual: str = "") -> bool:
        return (r["ctx"] == (num, _gate_key(gate), qual) and r["head"] == cond
                and r["item"].kind == SWEEP_KINDS[cond])

    def may_file(num: int, gate: str, cond: str, text: str, qual: str = "") -> bool:
        """§1.2's one filing rule: no item of this identity open or decided on any board read, none answered
        within the re-ask window, and no `kept waiting` line for the gate within it."""
        mine = [r for r in reads if same(r, num, gate, cond, qual)]
        if any(r["state"] in ("open", "decided") for r in mine):
            return False
        if any(_answered_within(r, today_l, reask_days) for r in mine):
            return False
        return not _kept_waiting_within(text, gate, today_u, reask_days)

    for num in sorted(open_texts):
        text = open_texts[num]
        e = _entries(text)[0]
        tid = e["id"]
        parent, _ = parse_part_of(e["part_of_raw"])
        pnum = _num(parent) if parent else None
        for gate in gate_items(parse_gates(e["blocked_raw"])):
            if gate.startswith("until "):
                if date.fromisoformat(gate[len("until "):]) <= today_u:
                    lift = {"id": tid, "gate": gate, "kind": "until", "evidence": "date reached"}
                    if lift not in lifts:
                        lifts.append(lift)
                continue
            if gate.startswith("decision "):
                found = _covers(reads, num, gate, pnum, repo)
                if any(r["state"] in ("open", "decided") for r in found):
                    continue
                if any(_answered_within(r, today_l, reask_days) for r in found):
                    continue
                if _kept_waiting_within(text, gate, today_u, reask_days):
                    continue
                who = gate[gate.index("(") + 1: -1].lower()
                fit = [b for b in boards if who in {p.lower() for p in (board_people(str(b[2] or "")) or [])}]
                pick = own if own in fit else (min(fit, key=_board_pick_key) if fit else None)
                if pick is None:
                    if may_file(num, gate, "no-board", text):
                        add(own_name, num, gate, "no-board", _sweep_item("no-board", tid, tid, gate))
                    continue
                ref = tid if pick is own else f"{repo.lower()}#{tid}"
                add(_board_name(pick), num, gate, "uncovered", _sweep_item(
                    "uncovered", tid, ref, gate, ask=_entry_ask(text, e["title"]), title=e["title"],
                    reask_days=reask_days))
                continue
            name = gate[len("event ("): -1]
            got, evidence = _outcome(results, tid, name)
            if got == "passed":
                lift = {"id": tid, "gate": gate, "kind": "event", "evidence": evidence}
                if lift not in lifts:  # an event written twice lifts once
                    lifts.append(lift)
                continue
            cond = {"error": "broken", "impossible": "impossible"}.get(got or "")
            if cond is None and got == "not yet":
                try:
                    age = gate_age(text, gate)
                except Refused:
                    age = None
                cond = "still" if age is not None and (today_u - age).days > event_age_days else None
            if cond and may_file(num, gate, cond, text):
                add(own_name, num, gate, cond, _sweep_item(cond, tid, tid, gate, reask_days=reask_days))
        for rec in _log(text):  # the `; board <repo>` audit: a cross-repo lift whose board shows no answer
            if rec["kind"] != "gate-lifted" or not rec.get("suffix", "").startswith("; board "):
                continue
            there = rec["suffix"][len("; board "):]
            if _audit_satisfied(reads, boards, there, repo, tid):
                continue
            gate = rec["gate"]
            if may_file(num, gate, "audit", "", f"board {there.lower()}"):
                add(own_name, num, gate, "audit", _sweep_item("audit", tid, tid, gate, extra=there),
                    f"board {there.lower()}")

    for r in reads:
        if r["state"] not in ("open", "decided") or r["ctx"] is None:
            continue
        if _sweep_closes(r, reads, boards, results, open_texts, texts, known, repo):
            keys = to_close.setdefault(r["board"], [])
            k = item_key(r["line"])
            if k not in keys:
                keys.append(k)
    return {"to_file": to_file, "to_close": to_close, "lifts": lifts}


def _audit_satisfied(reads: list[dict], boards: Sequence[Sequence], there: str, repo: str, tid: str) -> bool:
    """Whether the board a `; board <repo>` Log line names holds, open, closed or archived, an item with a
    ``Decided:`` whose Context names ``<this repo>#TD-n``. A board not read holds nothing."""
    named = _own_board(boards, there)
    if named is None:
        return False
    name = _board_name(named)
    want = f"{repo.lower()}#{tid}"
    for r in reads:
        if r["board"] != name or not r["item"].decided:
            continue
        ref, _ = _item_gate(r["item"].text)
        if ref is not None and ref_key(ref) == want:
            return True
    return False


def _sweep_closes(r: dict, reads: list[dict], boards: Sequence[Sequence], results: Mapping,
                  open_texts: Mapping[int, str], texts: Mapping[int, str], known: set[int], repo: str) -> bool:
    """The close rule (SPEC *The gate sweep*): whether the sweep closes one open item about this repo's entry."""
    it, (num, gate_key, qual) = r["item"], r["ctx"]
    _, gate = _item_gate(it.text)
    if it.decided and not waiting_only(it.decided[0]) and not _lifting(it.decided[0], it.lifts):
        return False  # a work order waits for whoever acts on it
    if qual.startswith("board "):
        if num not in known:
            return False  # an entry in neither the ledger nor the archive: its item is left for a person
        if r["head"] != "audit" or it.kind != "act" or not r["own"]:
            return False
        there = qual[len("board "):]
        tid = _entries(texts[num])[0]["id"] if num in texts else _tid(num)
        lines = [x for x in _log(texts.get(num, "")) if x["kind"] == "gate-lifted"
                 and _gate_key(x["gate"]) == gate_key and x.get("suffix", "").lower() == f"; board {there}"]
        return not lines or _audit_satisfied(reads, boards, there, repo, tid)
    if qual not in ("", "lift"):
        return False
    gone = _gone(num, gate, it.parts, r["own"], repo, open_texts, known)
    if gone is None:
        return False
    head = r["head"]
    if qual == "lift":
        return gone
    if head == "no-board" and it.kind == "act":
        text = texts.get(num, "")
        parent, _ = parse_part_of(_entries(text)[0]["part_of_raw"]) if text else (None, None)
        covered = any(x["state"] in ("open", "decided") for x in _covers(
            reads, num, gate, _num(parent) if parent else None, repo))
        return gone or covered
    tid = _entries(texts[num])[0]["id"]
    got = _outcome(results, tid, gate[len("event ("): -1])[0] if gate.startswith("event (") else None
    if head == "broken" and it.kind == "act":
        return gone or (got is not None and got != "error")
    if head == "still" and it.kind == "decide":
        return gone or got == "impossible"
    if it.kind == "decide":
        return gone
    return False


# ---------------------------------------------------------------------------------------------
# The merge gate's verdicts (v2.4): the lift-PR verdict, the tripwire and the coverage check
# ---------------------------------------------------------------------------------------------

BOARD_PATH = "docs/user_attention.md"  # the paths a tree is read at (SPEC *The merge gate's verdicts*)
BOARD_ARCHIVE_PATH = "docs/user_attention_archive.md"
LEDGER_DIR = "docs/ledger"  # a v2 ledger; a tree with no file under it holds a v1 ledger at LEDGER_V1_PATH
LEDGER_V1_PATH = "docs/technical_debt.md"
COVERING = ("open", "decided")  # the covers() states that cover


def _tree_ls(tree: Mapping[str, str]) -> Ls:
    def ls(path: str) -> list[str] | None:
        pre = path.rstrip("/") + "/"
        under = [k[len(pre):] for k in tree if k.startswith(pre)]
        return sorted(x for x in under if x and "/" not in x) if under else None
    return ls


def _tree_ledger(tree: Mapping[str, str]) -> tuple[dict[int, str], dict[int, str], bool]:
    """(each open entry's text, each archived entry's text, both by number, and whether the ledger is v2) of
    the ledger a tree holds. An entry the ledger's text holds with an archived Status counts as archived."""
    ls = _tree_ls(tree)
    v2 = ls(LEDGER_DIR) is not None
    led, arch = load(LEDGER_DIR if v2 else LEDGER_V1_PATH, ls, lambda p: tree.get(p))
    open_t: dict[int, str] = {}
    closed_t: dict[int, str] = {}
    for tid, body in _entry_texts(arch).items():
        closed_t.setdefault(_num(tid), body)
    for tid, body in _entry_texts(led).items():
        e = _entries(body)[0]
        (closed_t if first_word(e["fields"].get("status")) in ARCHIVED_WORDS else open_t).setdefault(_num(tid), body)
    return open_t, closed_t, v2


def _tree_board(tree: Mapping[str, str], repo: str) -> tuple[str, str, str, str]:
    """This repo's own board as the sweep's board tuple, read from a tree."""
    return ("", repo, str(tree.get(BOARD_PATH) or ""), str(tree.get(BOARD_ARCHIVE_PATH) or ""))


def _check_repo(repo: object) -> None:
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
        raise Refused(f"repo is this repo's origin path (owner/name) or its basename, not {repo!r}")


def _decisions(text: str | None) -> list[str]:
    """The ``decision (<p>)`` gates the open entry ``text`` carries, as it writes them."""
    if not text or not _entries(text):
        return []
    return [g for g in gate_items(parse_gates(_entries(text)[0]["blocked_raw"])) if GATE_DECISION_RE.match(g)]


def _new_log(base: str | None, head: str) -> list[dict]:
    """The head's Log lines the base did not have (compared as written, each once)."""
    seen: dict[tuple, int] = {}
    for r in log_lines(base) if base else []:
        seen[(r["date"], r["text"])] = seen.get((r["date"], r["text"]), 0) + 1
    out = []
    for r in log_lines(head):
        k = (r["date"], r["text"])
        if seen.get(k):
            seen[k] -= 1
        else:
            out.append(r)
    return out


def _board_line_reads(text: str) -> dict[str, list[tuple[str, BoardItem]]]:
    """Every item line of a board's (or archive's) text by its item key: each (line, item), read open or closed."""
    out: dict[str, list[tuple[str, BoardItem]]] = {}
    for ln in text.splitlines():
        if ITEM_RE.match(ln):
            got = parse_board(ln, warn=False)
        elif CLOSED_ITEM_RE.match(ln):
            got = parse_closed_items(ln)
        else:
            continue
        if got:
            out.setdefault(item_key(ln), []).append((ln, got[0]))
    return out


def _lifted_close(line: str) -> bool:
    m = CLOSED_ITEM_RE.match(line)
    c = CLOSED_RE.search(m.group("text")) if m else None
    return bool(c) and c.group(0).rstrip().endswith("— lifted.")


def tripwire(base_tree: Mapping[str, str], head_tree: Mapping[str, str], subject: str, repo: str) -> list[tuple[str, str]]:
    """The tripwire on a `decision (<p>)` removed (v2.4, SPEC *The merge gate's verdicts*): ``[(kind, text)]``,
    each a removal the diff does not account for. It runs on every PR, the ``set by=`` route included. Trees map
    each path to its text, the ledger and this repo's board and archive at SPEC's paths; only this repo's own
    board is read, at the base and at the head, never another repo's, so the verdict is the same on every
    machine. An entry that stays open and loses a `decision (<p>)` is accounted for by a ``gate reassigned`` or
    ``override:`` line for it, or by a new ``gate lifted … answer`` line whose suffix fits the board:

    - none: an item covering the gate at the base (covers(), state ``open`` or ``decided``) carries a new or
      changed `Decided:` at the head, decided or closed, or, already decided, is newly closed ``— lifted.``;
    - ``; no board item``: nothing covers it at the base nor at the head;
    - ``; shared board item left open``: an item covering it at the base still covers it at the head, and
      another entry it lists (its Context entry or a `Parts:` id) still carries the gate;
    - ``; board <repo>``: ``<repo>`` names a repo other than this one.

    A ``by`` other than the gate's person is flagged, unless the lift has no suffix, the base board says
    `Answered by: any` and lists ``by`` on `People:`, and the covering item's head `Decided:` names ``by``.
    Exempt: an entry the diff archives, and the migrate commit (its subject, ``ledger: migrate v<release> (<n>
    entries)``). The tripwire is forgeable, and says so: a well-formed hand edit passes it, and review is the
    backstop."""
    _check_repo(repo)
    if MIGRATE_SUBJECT_RE.match(subject or ""):
        return []
    b_open, _, _ = _tree_ledger(base_tree)
    h_open, _, _ = _tree_ledger(head_tree)
    b_board, h_board = _tree_board(base_tree, repo), _tree_board(head_tree, repo)
    b_lines, h_lines = b_board[2].splitlines(), h_board[2].splitlines()  # as parse_board() numbers them
    b_archived = set(b_board[3].splitlines())
    h_reads = _board_line_reads("\n".join([*h_lines, *(x for x in h_board[3].splitlines() if x not in b_archived)]))
    people = board_people(b_board[2])
    anyone = (answered_by(b_board[2]) or "").lower() == "any"
    flags: list[tuple[str, str]] = []
    for num in sorted(b_open):
        btext, htext = b_open[num], h_open.get(num)
        if htext is None:
            continue  # archived (exempt) or gone: the tripwire reads an entry that stays open
        tid = _entries(htext)[0]["id"]
        new = _new_log(btext, htext)
        for gate in _decisions(btext):
            key = _gate_key(gate)
            if _carried(htext, gate) is not None:
                continue
            person = GATE_DECISION_RE.match(gate).group("who").strip()
            if any((r["kind"] == "gate-reassigned" and _gate_key(r["gate"]) == key)
                   or (r["kind"] == "gate-lifted" and r.get("via") == "override" and _gate_key(r["gate"]) == key)
                   for r in new):
                continue
            lifts = [r for r in new if r["kind"] == "gate-lifted" and r.get("via") == "answer"
                     and _gate_key(r["gate"]) == key]
            if not lifts:
                flags.append(("tripwire-unanswered", f"{tid} drops {gate} with no answer logged — a gate is lifted "
                              "by its person's answer, reassigned (gate reassigned) or overridden (override:)"))
                continue
            rec = lifts[-1]
            suffix, by = rec.get("suffix", ""), rec["by"]
            cov_b = [(it, s) for _, it, s in covers(btext, gate, [b_board], repo) if s in COVERING]
            cov_h = [(it, s) for _, it, s in covers(htext, gate, [h_board], repo) if s in COVERING]
            answered_here = []  # the covering items the head answers: (base item, head line, head item)
            for it, s in cov_b:
                bl = b_lines[it.line - 1]
                for hl, hit in h_reads.get(item_key(bl), []):
                    closed = bool(CLOSED_ITEM_RE.match(hl))
                    gained = hit.decided is not None and (hit.decided, hit.decided_by) != (it.decided, it.decided_by)
                    newly_lifted = it.decided is not None and closed and _lifted_close(hl) and hit.decided is not None
                    if gained or newly_lifted:
                        answered_here.append((it, hl, hit))
            if suffix.startswith("; board "):
                there = suffix[len("; board "):]
                if not REPO_RE.fullmatch(there) or there.lower() == repo.lower():
                    flags.append(("tripwire-board", f"{tid} lifts {gate} on board {there}, which is this repo's own "
                                  "— its answer is on this board, written as Decided:"))
            elif suffix == "; no board item":
                if cov_b or cov_h:
                    flags.append(("tripwire-no-board-item", f"{tid} lifts {gate} with no board item, but an open "
                                  "item on this repo's board asks it — answer that item"))
            elif suffix == "; shared board item left open":
                still = {item_key(b_lines[it.line - 1]) for it, _ in cov_b} & {
                    item_key(h_lines[it.line - 1]) for it, _ in cov_h}
                shared = False
                for it, _ in cov_h:
                    if item_key(h_lines[it.line - 1]) not in still:
                        continue
                    ref, _g = _item_gate(it.text)
                    listed = [x for x in [ref, *it.parts] if x and "#" not in x and _num(x) != num]
                    if any(_carried(h_open.get(_num(x)), gate) is not None for x in listed):
                        shared = True
                if not shared:
                    flags.append(("tripwire-shared", f"{tid} lifts {gate} leaving a shared board item open, but no "
                                  "item it covers still asks another listed entry"))
            elif not answered_here:
                flags.append(("tripwire-no-decided", f"{tid} lifts {gate}, and no item covering it on this repo's "
                              "board gains a Decided: in the same diff"))
            if by.lower() != person.lower():
                ok = (not suffix and anyone and people is not None and by.lower() in {p.lower() for p in people}
                      and any((hit.decided_by or "").lower() == by.lower() for _, _, hit in answered_here))
                if not ok:
                    flags.append(("tripwire-by", f"{tid} lifts {gate} by {by}, not {person} — only the gate's "
                                  "person answers, or anyone listed on a board whose Answered by is any"))
    return flags


def uncovered_decisions(base_tree: Mapping[str, str], head_tree: Mapping[str, str], boards: Sequence[Sequence],
                        repo: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The merge gate's coverage check (v2.4, SPEC *The merge gate's verdicts*): ``(refusals, flags)``, each
    ``[(kind, text)]``. ``boards`` are the other repos' boards read (the sweep's tuples); this repo's own board is
    read from ``head_tree`` in place of any that names it. A `decision (<p>)` an open entry gains in the diff
    is refused when this repo's board lists ``<p>`` on `People:` and no item on it covers the gate (covers(),
    state ``open`` or ``decided``), and flagged when the board does not list ``<p>``, since its coverage then
    depends on another repo's board, which not every machine reads. A new `decide` item on this repo's board
    whose Context names a decision and none of whose answers lifts (one of its `Lifts:`, `Go` when it has none,
    never a waiting-only one) is refused. Refusals rest on this repo's own board alone."""
    _check_repo(repo)
    own = _tree_board(head_tree, repo)
    mine = _own_board(boards, repo)
    reads = [own, *[b for b in boards if b is not mine]]
    b_open, _, _ = _tree_ledger(base_tree)
    h_open, _, _ = _tree_ledger(head_tree)
    people = {p.lower() for p in board_people(own[2]) or []}
    refusals: list[tuple[str, str]] = []
    flags: list[tuple[str, str]] = []
    for num in sorted(h_open):
        htext = h_open[num]
        tid = _entries(htext)[0]["id"]
        for gate in _decisions(htext):
            if _carried(b_open.get(num), gate) is not None:
                continue
            person = GATE_DECISION_RE.match(gate).group("who").strip()
            cov = [(b, s) for b, _, s in covers(htext, gate, reads, repo) if s in COVERING]
            if any(b == _board_name(own) for b, _ in cov):
                continue
            if person.lower() in people:
                refusals.append(("decision-uncovered", f"{tid} gains {gate} and no open decide item on this repo's "
                                 "board asks it — file the item in the same PR"))
            else:
                where = ", ".join(dict.fromkeys(b for b, _ in cov))
                flags.append(("decision-elsewhere", f"{tid} gains {gate}, and this repo's board does not list {person}: "
                              + (f"covered on {where}, which not every machine reads" if where else
                                 "no board read covers it — the sweep files its item")))
    base_keys = {item_key(ln) for ln in str(base_tree.get(BOARD_PATH) or "").splitlines()
                 if ITEM_RE.match(ln) or CLOSED_ITEM_RE.match(ln)}
    lines = own[2].splitlines()  # as parse_board() numbers them
    for it in parse_board(own[2], warn=False):
        ln = lines[it.line - 1]
        if it.kind != "decide" or item_key(ln) in base_keys:
            continue
        _, gate = _item_gate(it.text)
        if gate is None or not GATE_DECISION_RE.match(gate):
            continue
        if not any(_lifting(a, it.lifts) for a in it.answers):
            refusals.append(("decision-no-lift", f"the new decide item on line {it.line} asks {gate} and none of "
                             f"its answers lifts it ({' | '.join(it.lifts or ['Go'])})"))
    return refusals, flags


def _verdict_day(value: object, what: str) -> date:
    return date.fromisoformat(utc_day(value, what))


def lift_pr_verdict(base_tree: Mapping[str, str], head_tree: Mapping[str, str], files: Sequence[str], subject: str,
                    commits: int, created_at: date | datetime | str, merged_at: date | datetime | str | None,
                    repo: str) -> dict:
    """The lift-PR verdict (v2.4, SPEC *The merge gate's verdicts*): ``{carve_out, flags, review}`` for a PR whose
    one changed board item gains a `Decided:` and whose Context names a gate. ``carve_out`` is whether it is a
    decide lift the person's answer reviews; else ``review`` names, as ``[(kind, text)]``, the first condition
    that sends it to ordinary review. ``flags`` are tripwire()'s over the same trees.

    Trees map paths to texts (SPEC's paths); ``files`` are the PR's changed paths, ``subject`` its commit's
    subject, ``commits`` its commit count; ``created_at`` and ``merged_at`` (None while open) the forge's dates,
    each a date or an aware datetime (taken as its UTC date). The carve-out needs: (a0) the base board declares
    `People:`; (a) the subject's action is ``decide``; one commit; the board diff one item, which gains a
    `Decided: <label> (by <p>)` and no other answer had, its head line ``edit_line(base line, "decide", label,
    by, D, close=closes(…))`` byte for byte; (c) for this repo's entry, a v2 ledger whose changed files are
    exactly those decide_lift() changes, each byte-equal to its result, every new Log line one date T, with T
    within a day of ``created_at`` and not after the merge; for another repo's entry, the board alone, the
    gate's person and the answerer on `People:`; and the `Decided:` date D within ``created_at − 1`` and the
    merge (else ``created_at``) ``+ 1``. (d), a PR only, is the consumer's: this judges a PR."""
    flags = tripwire(base_tree, head_tree, subject, repo)
    created = _verdict_day(created_at, "created_at")
    merged = None if merged_at is None else _verdict_day(merged_at, "merged_at")
    if merged is not None and merged < created:
        raise Refused(f"merged_at {merged} is before created_at {created}")
    if isinstance(commits, bool) or not isinstance(commits, int) or commits < 0:
        raise Refused(f"commits is the PR's commit count, not {commits!r}")
    one = timedelta(days=1)

    def review(kind: str, text: str) -> dict:
        return {"carve_out": False, "flags": flags, "review": [(kind, text)]}
    b_text, h_text = base_tree.get(BOARD_PATH), head_tree.get(BOARD_PATH)
    if b_text is None or h_text is None:
        return review("lift-no-board", f"the PR has no board at {BOARD_PATH} at its base and head")
    b_lines, h_lines = str(b_text).split("\n"), str(h_text).split("\n")
    diff = [n for n in range(max(len(b_lines), len(h_lines)))
            if n >= len(b_lines) or n >= len(h_lines) or b_lines[n] != h_lines[n]]
    if len(b_lines) != len(h_lines) or len(diff) != 1:
        return review("lift-board-diff", "the board diff is not one item line changed in place")
    end = "\r" if b_lines[diff[0]].endswith("\r") else ""
    if h_lines[diff[0]].endswith("\r") != bool(end):
        return review("lift-board-diff", "the answered line changes its line ending")
    bl, hl = b_lines[diff[0]].removesuffix(end), h_lines[diff[0]].removesuffix(end)
    if not ITEM_RE.match(bl) or not (ITEM_RE.match(hl) or CLOSED_ITEM_RE.match(hl)) or item_key(bl) != item_key(hl):
        return review("lift-board-diff", "the changed board line is not one open item answered in place")
    b_item = parse_board(bl, warn=False)[0]
    h_item = (parse_board(hl, warn=False) if ITEM_RE.match(hl) else parse_closed_items(hl))[0]
    ref, gate = _item_gate(b_item.text)
    if h_item.decided is None:
        return review("lift-not-answered", "the changed item gains no Decided:")
    if gate is None or b_item.kind != "decide":
        return review("lift-no-gate", "the answered item is not a decide whose Context names one entry and one gate")
    if b_item.decided is not None:
        return review("lift-reanswer", "the item was answered already — a re-answer takes ordinary review")
    people = board_people(str(b_text))
    if people is None:
        return review("lift-a0", "the base board declares no People: line, so who may answer is unchecked")
    if edit_action(subject or "") != "decide":
        return review("lift-subject", f"the commit's subject is not a board decide: {subject!r}")
    if commits != 1:
        return review("lift-commits", f"a lift PR is one commit, squash-merged; this has {commits}")
    label, d = h_item.decided
    by = h_item.decided_by
    if by is None:
        return review("lift-no-by", "the Decided: names no answerer (by <person>)")
    if not (created - one <= d <= (merged or created) + one):
        return review("lift-decided-date", f"the Decided: date {d} is outside {created - one} .. {(merged or created) + one}")
    answered = answered_by(str(b_text))
    if "#" in ref:
        other = ref.rpartition("#")[0]
        if other.lower() == repo.lower():
            return review("lift-own-ref", f"{ref} names this repo's entry as another repo's")
        if list(files) != [BOARD_PATH]:
            return review("lift-files", f"another repo's entry is answered on the board alone: {list(files)}")
        on = {p.lower() for p in people}
        person = GATE_DECISION_RE.match(gate).group("who").strip() if GATE_DECISION_RE.match(gate) else None
        if person is not None and person.lower() not in on:
            return review("lift-people", f"the gate's person {person} is not on the board's People:")
        if by.lower() not in on:
            return review("lift-people", f"{by} is not on the board's People:")
        if person is not None and (answered or "owner").lower() == "owner" and by.lower() != person.lower():
            return review("lift-people", f"only {person} answers {gate} on a board whose Answered by is owner")
        entries_given: dict[str, str] = {}
        result: dict[str, str] = {}
    else:
        b_open, b_closed, v2 = _tree_ledger(base_tree)
        if not v2:
            return review("lift-v1", "a v1 ledger's lift is not recomputed — it takes ordinary review")
        entries_given = {}
        for x in [ref, *b_item.parts]:
            n = _num(x) if _is_id(x) else None
            got = b_open.get(n, b_closed.get(n)) if n is not None else None
            if got is not None:
                entries_given[_entries(got)[0]["id"]] = got
        ls = _tree_ls(base_tree)
        h_ls = _tree_ls(head_tree)
        days = set()
        for f in files:
            if f.startswith(LEDGER_DIR + "/") and f in base_tree and f in head_tree:
                body = head_tree[f]
                if _entries(body):
                    days |= {r["date"] for r in _new_log(base_tree[f], body) if r["date"]}
        if len(days) > 1:
            return review("lift-log-date", f"the new Log lines carry more than one date: {sorted(days)}")
        t = date.fromisoformat(days.pop()) if days else created
        try:
            result = decide_lift(bl, entries_given, label, by, t, people, answered)
        except Refused as e:
            return review("lift-refused", f"decide_lift refuses it: {e}")
        if result and not (created - one <= t <= min(created + one, merged or created + one)):
            return review("lift-log-date", f"the Log date {t} is outside {created - one} .. "
                          f"{min(created + one, merged or created + one)}")
        want = {BOARD_PATH}
        for tid, text in result.items():
            path = entry_path(LEDGER_DIR, tid, ls)
            if path is None or path.startswith(LEDGER_DIR + "/" + LEDGER_ARCHIVE + "/") \
                    or entry_path(LEDGER_DIR, tid, h_ls) != path:
                return review("lift-files", f"{tid}'s file is not one open file at the base and head")
            if head_tree.get(path) != text:
                return review("lift-ledger", f"{path} is not what decide_lift writes, byte for byte")
            want.add(path)
        if len(list(files)) != len(set(files)) or set(files) != want:
            return review("lift-files", f"the PR changes {sorted(set(files))}, and a lift changes {sorted(want)}")
    try:
        close = closes(bl, label, {**entries_given, **result})
        line = edit_line(bl, "decide", answer=label, by=by, today=d, close=close)
    except Refused as e:
        return review("lift-board-line", f"the decide writer refuses the answer: {e}")
    if line != hl:
        return review("lift-board-line", "the answered line is not what the decide writer writes, byte for byte")
    return {"carve_out": True, "flags": flags, "review": []}


# ---------------------------------------------------------------------------------------------
# The format version
# ---------------------------------------------------------------------------------------------

FORMAT_MAJOR = 2  # the newest major version of the formats this module reads
VERSION_RE = re.compile(r"^Ledgerboard:\s*(\d+)\s*$", re.MULTILINE)


def format_major(text: str) -> int:
    """The major version a ledger or board declares on its `Ledgerboard: N` preamble line (before its
    first entry or item); 1 when none. Nothing here calls it: a reader calls ``version_problem``
    before it trusts what it parsed."""
    pre = COMMENT_RE.sub("", text)
    first = re.search(r"^(?:## TD-\d+:|\s*-\s*\[[ xX]\]\s)", pre, re.MULTILINE)  # the first entry or item
    m = VERSION_RE.search(pre[: first.start() if first else len(pre)])
    return int(m.group(1)) if m else 1


def version_problem(text: str) -> str | None:
    """Why this module must not read `text`, or None: a declared major newer than it knows."""
    major = format_major(text)
    if major > FORMAT_MAJOR:
        return (f"this file declares Ledgerboard: {major}, newer than this ledgerboard.py reads "
                f"({FORMAT_MAJOR}) — vendor a newer release; nothing was read")
    return None
