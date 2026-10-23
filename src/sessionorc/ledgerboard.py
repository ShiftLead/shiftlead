# ledgerboard v1.3 sha256:db17c348ccfc676da0790bef88084c2de1b20324df228d04806cfcc9bbe7cc09
# SYNCED FILE — canonical copy: ShiftLead/ledgerboard ledgerboard.py (vendored by dev-cadence as files/scripts/ledgerboard.py)
# Edit it there and release; an edit made in a consumer's copy is overwritten by the next vendor or sync.
"""The ledger and board formats, defined once (SPEC.md).

A **ledger** (``docs/technical_debt.md``) is a file of ``## TD-NNN: title`` entries, each with a
header block of ``**Name:** value`` fields, a summary table, and an archive beside it. A **board**
(``docs/user_attention.md``) is a file of ``- [ ] [kind] YYYY-MM-DD (session …) — text`` items with
trailing ``Due:``/``Answers:``/``Decided:`` fields, reply tails and a detail block.

Everything here is a pure function over text: no git, no network, no file system, no roster.
What a caller needs from outside the text is passed in — the cross-repo resolver of
``pickable()``, today's date. Two consumers vendor this file (dev-cadence's scripts, ShiftLead);
neither keeps a second parser of either format.

Sections: the ledger (entries, ``Fields:``, ``Blocked by``, derived pickable, ``check``); the rank
(cards, keys, the rank file, the pick order); the board
(items, the item record, keys and refs); edits (``edit_line``, composing an item, the commit
subject of a write and its parser); line predicates for diff walkers; the format version.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
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
CADENCE_FIELDS = ("priority", "type", "added", "status", "blocked by", "location")  # the spec's own fields
PRIORITY_RE = re.compile(r"^\*\*Priority:\*\*\s*(\w+)", re.MULTILINE)
BLOCKED_RE = re.compile(r"^\*\*Blocked by:\*\*[ \t]*(.*?)[ \t]*$", re.MULTILINE)  # one line only
TYPE_RE = re.compile(r"^\*\*Type:\*\*[ \t]*(.*?)[ \t]*$", re.MULTILINE)
TYPES = ("debt", "feature")  # pick order within a Priority; the first is the default
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)  # the seed template's example entry lives in one
ID_ITEM_RE = re.compile(r"^TD-(\d+)$")
XREPO_ITEM_RE = re.compile(r"^([\w.-]+(?:/[\w.-]+)?)#(TD-\d+)$")
DECISION_RE = re.compile(r"\bdecision\s*\(([^)]+)\)", re.IGNORECASE)
WORD_RE = re.compile(r"[^\s,;]+")
PRIORITIES = ("high", "medium", "low")
EDIT_ERRORS = ("pickable-disagrees", "undeclared-field")  # information on a standing ledger, an error in a new edit

# A resolver answers one ``<repo>#TD-NNN`` item: ``(state, why)`` or a mapping carrying at least
# ``state`` and ``why`` (any other keys ride along into the entry's ``cross_repo``). ``state`` is
# ``open | archived | unresolved``; ``why`` says why it is unresolved, else "".
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
    `## TD-001: …` that is not an entry. Priority, Type and Blocked by come from the header
    block; one written further down the body is still read (the safe direction) and flagged."""
    text = COMMENT_RE.sub("", text)
    out = []
    for m in HEADING_RE.finditer(text):
        nxt = SECTION_RE.search(text, m.end())  # a body ends at the next `## ` heading of any kind
        body = text[m.end(): nxt.start() if nxt else len(text)]
        fields = header_block(body)
        below = []
        for key, rx in (("priority", PRIORITY_RE), ("type", TYPE_RE), ("blocked by", BLOCKED_RE)):
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
                    "blocked_raw": blocked, "fields": fields, "below": below})
    return out


def rows(text: str) -> list[dict]:
    """The summary table's rows, in order: {id, title, priority} (comments dropped)."""
    return [{"id": m.group(1), "title": m.group(3), "priority": m.group(4)}
            for m in ROW_RE.finditer(COMMENT_RE.sub("", text))]


def parse_blocked(raw: str) -> tuple[list[str], list[str], list[str]]:
    """(entry ids — ``TD-NNN`` or ``<repo>#TD-NNN`` — decision holders, unreadable items) of one Blocked by value."""
    ids, who, bad = [], [], []
    d = DECISION_RE.search(raw)
    if d:
        who.append(d.group(1).strip())
        rest = raw[d.end():].strip()
        if rest.startswith(","):  # a list continuing past the decision: it was not written last
            bad.append(f"after the decision: {rest[1:].strip()}")
        raw = raw[: d.start()]  # otherwise what follows the decision is its pointer, never read
    for item in (x.strip() for x in raw.split(",")):
        if not item:
            continue
        if ID_ITEM_RE.match(item) or XREPO_ITEM_RE.match(item):
            ids.append(item)  # a `<repo>#TD-NNN` item is resolved by pickable()'s resolver, not here
        else:
            bad.append(item)
    return ids, who, bad


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
             rank_text: str | None = None, repo: str = "") -> dict:
    """Every live entry in pick order, with its derived pickable, open blockers and raw fields; plus flags.

    **Pickable is derived, never written:** an entry is pickable when it has no Blocked by field,
    or every entry it names is archived and it names no decision. ``resolve`` answers a
    ``<repo>#TD-NNN`` item (see ``Resolve``); without one, such an item keeps its block.
    ``undeclared`` also flags a header field with no vocabulary, when the ledger declares any.

    **Pick order is the rank** (SPEC *The rank*): ``rank_text`` is the rank file's text (None or
    "": no lines), ``repo`` the last component of an implicit key. Each record carries its ``key``
    (its line's, else its implicit key) and its ``card_key``; entries sort by card, then within a
    card by dependency, then key."""
    live = entries(ledger)
    live_nums = {_num(e["id"]) for e in live}
    archived = heading_nums(archive)
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
    for e in live:
        n = _num(e["id"])
        prio = e["priority"] or table.get(n) or "?"
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
               "key": keys[e["id"]], "card_key": ""}
        if e["blocked_raw"] is not None:
            ids, who, bad = parse_blocked(e["blocked_raw"])
            for item in bad:
                flags.add(f"⚠ {e['id']}: cannot read Blocked by item {item!r} — "
                          "write TD-NNN or decision (<who>)", e["id"], "blocked by", "blocked-item")
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
                    continue
                bn = _num(b)
                if bn in live_nums:
                    open_ids.append(b)
                elif bn not in archived:
                    flags.add(f"⚠ {e['id']}: Blocked by {b}, which names no entry in the ledger or the archive",
                              e["id"], "blocked by", "blocked-unknown")
                    open_ids.append(b)  # unknown: keep the block — the safe direction
            if not open_ids and not who and not bad:
                flags.add(f"ℹ {e['id']}: every blocker is archived ({', '.join(ids)}) — pickable; "
                          "the Blocked by field can go", e["id"], "blocked by", "blockers-archived")
            else:
                rec["blocked_by"] = open_ids + [f"decision ({w})" for w in who] + [repr(b) for b in bad]
                rec["pickable"] = False
        written = first_word(e["fields"].get("pickable"))
        if written in ("yes", "no") and (written == "yes") != rec["pickable"]:
            flags.add(f"ℹ {e['id']}: its Pickable line says {written}, the derived pickable is "
                      f"{'yes' if rec['pickable'] else 'no'} — the line is only a field (cadence.md §2.12)",
                      e["id"], "pickable", "pickable-disagrees")
        (pick if rec["pickable"] else blocked).append(rec)
    order = _card_order(live, keys, lined)
    for r in pick + blocked:
        r["card_key"] = order[r["id"]][1]
    for lst in (pick, blocked):
        lst.sort(key=lambda r: order[r["id"]][0])
    everything = sorted(pick + blocked, key=lambda r: order[r["id"]][0])
    return {"pickable": pick, "blocked": blocked, "entries": everything, "flags": list(flags),
            "flag_recs": flags.recs, "declared": {k: list(v) for k, v in vocab.items()}}


def check(ledger: str, archive: str, old: str | None = None, resolve: Resolve | None = None,
          rank_text: str | None = None) -> list[dict]:
    """The ledger's flags: {level, id, field, kind, text, standing}. ``old`` is the ledger before
    an edit (None: every ⚠ is an error and nothing is standing). With it, a flag on an entry whose
    header block is unchanged — or a Fields: flag under an unchanged declaration — is standing:
    information, whatever it was. On a changed or new entry, EDIT_ERRORS are errors too. ``rank_text``
    adds the rank file's flags (never standing: the file is a tool's)."""
    recs = [dict(r, standing=False)
            for r in pickable(ledger, archive, resolve, undeclared=True, rank_text=rank_text)["flag_recs"]]
    if old is None:
        return recs
    before = {e["id"]: e["fields"] for e in entries(old)}
    changed = {e["id"] for e in entries(ledger) if before.get(e["id"]) != e["fields"]}
    decl_changed = declarations(old) != declarations(ledger)
    for r in recs:
        counts = True if r["kind"] == "rank" else decl_changed if r["id"] is None else r["id"] in changed
        if not counts:
            r["standing"], r["level"] = True, "info"
        elif r["kind"] in EDIT_ERRORS:
            r["level"] = "error"
        r["text"] = ("⚠" if r["level"] == "error" else "ℹ") + r["text"][1:]
    return recs


# ---------------------------------------------------------------------------------------------
# The rank: the person's order of a ledger's entries, and the pick order it gives
# ---------------------------------------------------------------------------------------------

RANK_LINE_RE = re.compile(r"^(TD-\d+):[ \t]+(\S+)[ \t]*$")
KEY_RE = re.compile(r"^[0-9A-Za-z][|\w./-]*$", re.ASCII)  # never a leading `|`; the rest of a repo name may ride along
KEY_SEP = "|"  # the lowest character of the key order, below every other
KEY_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"  # what midpoint() writes, in key order
BANDS = {"high": "1", "medium": "2", "low": "3"}  # an implicit key's first component; anything else is 4
RANK_HEADER = ("# The rank: one `TD-NNN: <key>` line per entry, sorted by key (ledgerboard SPEC, The rank).\n"
               "# Written by a tool; read only through ledgerboard's rank().\n")
QUEUE_ACTIONS = ("rank", "join", "prune")
QUEUE_SUBJECT_RE = re.compile(r"^queue: (?:rank|join|prune) TD-\d+(?:, TD-\d+)* \([^()\s][^()]*\)$")


def rank_path(ledger_path: str) -> str:
    """The rank file of the ledger at ``ledger_path``: ``<ledger stem>_rank.yml`` beside it."""
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
    first wins), ℹ for a blank line, a comment below the first entry, or lines out of key order."""
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


def components(ents: list[dict]) -> list[dict]:
    """The connected components of ``ents`` (``entries()`` of a ledger or an archive) over their
    Blocked by ids, both directions: ``{ids, others, cross_repo}`` — the members in file order, the
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


def _card_order(live: list[dict], keys: dict[str, str], lined: dict[int, str]) -> dict[str, tuple[tuple, str]]:
    """Each live entry's (sort value, card key). The card key is the best lined key among the card's
    members when any has a line, else the best implicit key; the sort value is that key, the card's
    lowest id, then the entry's place in the card — after every member it is blocked by, else by key."""
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
ANSWERS_RE = re.compile(r"(?:^|(?<=[.?!]\s))Answers:\s*(?P<answers>(?:(?!\bAnswers:).)*?)\.?\s*"
                        r"(?:\bDecided:.*)?$")
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
CONTEXT_RE = re.compile(r"\bContext:\s*(?P<ctx>.*?)(?=\s+(?:Due|Answers|Decided|Closed):|$)")
REF_TD_RE = re.compile(r"(?:[\w.-]+(?:/[\w.-]+)?#)?TD-\d+")
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


def parse_decided(text: str) -> tuple[str, date] | None:
    """The item's `Decided: <text> (YYYY-MM-DD)` field, or None (absent or a bad date)."""
    m = DECIDED_RE.search(_trailer(text))
    if not m:
        return None
    try:
        return m.group("text"), datetime.strptime(m.group("date"), "%Y-%m-%d").date()  # noqa: DTZ007  # a civil date, as Due:
    except ValueError:
        return None


def reply_span(text: str) -> tuple[int, int] | None:
    """(start, end) of the item's reply tails, or None: from the first ` — <name>, <date>: `
    after its Due: to its trailing Answers:/Decided:/Closed: fields, or the line's end. Read
    only after the Due: — prose shaped like a reply before it is the item's own."""
    due = DUE_RE.search(text)  # the item's own Due: is its first, as _trailer reads it — a reply may name one
    m = REPLY_TAIL_RE.search(text, due.end() if due else 0)
    if m is None:
        return None
    ends = [f.start() for f in (r.search(text, m.end()) for r in (ANSWERS_RE, DECIDED_RE, CLOSED_RE)) if f]
    end = min(ends) if ends else len(text)
    return m.start(), m.start() + len(text[m.start():end].rstrip())


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
    bad_due: str | None = None  # the text after "Due:" when it is not a date
    kind: str | None = None  # decide | act | look | watch | fyi, or None when unmarked
    fyi_due: bool = False  # an fyi item that carries a Due: anyway — ignored, and flagged
    # The item's detail block — the lines under it indented deeper than its `-`, common indent
    # removed. No edit touches it: Due:/Answers:/Decided:/replies stay on the head line.
    detail: list[str] = field(default_factory=list)

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
    Due: fields (an edit may also end the sentence before them) and its reply tails — so the open
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
    line = re.sub(r"\s*(?:" + DUE_RE.pattern + r")\.?", "", line, flags=re.IGNORECASE)
    return line.rstrip(" .")


def closed_items(content: str) -> list[str]:
    """The board's closed (`- [x]`) item lines."""
    return [ln for ln in content.splitlines() if CLOSED_ITEM_RE.match(ln)]


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
                               decided=parse_decided(text), bad_due=bad,
                               kind=kind, fyi_due=fyi_due,
                               detail=detail_block(lines, lineno)))
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
        if ref not in refs:
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


def item_record(item: BoardItem, today: date) -> dict:
    """The item as one JSON-ready record — the board's API, and the fixtures' shape. The
    today-relative fields (``overdue_days``, ``due_tag``) are computed against ``today``."""
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
        "waiting_on": item.waiting_on,
        "due_error": item.bad_due,
        "kind": item.kind,
        **dict(zip(("session", "host"), item_head(item.text))),
        "refs": item_refs(item.text),
        "replies": [{"by": by, "date": d, "text": t} for by, d, t in parse_replies(item.text)],
        "detail": item.detail,
    }


# ---------------------------------------------------------------------------------------------
# Edits: one item line rewritten, a new item composed, and the commit subject of each write
# ---------------------------------------------------------------------------------------------

EDIT_ACTIONS = ("snooze", "done", "decide", "reply")
FIELDS_RE = re.compile(r"\s+\b(?:Context|Due|Answers|Decided):")
FIELD_NAME_RE = re.compile(r"\b(?:Context|Answers|Decided|Closed):")  # in a reply, the reader would read the field
ANY_FIELD_RE = re.compile(r"\b(Context|Due|Answers|Decided|Closed):")
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
              today: date | None = None) -> str:
    """The open item line `body` (no line ending) after `action` — snooze (to `to`), done (with
    `why`), decide (`answer`), reply (`reply`, by `by`); raises Refused. Every edit is re-parsed
    and refused if the reader would not read back what was meant."""
    today = today or date.today()  # noqa: DTZ011  # a civil date, as the readers use
    if ITEM_RE.match(body) is None:
        raise Refused("the line is not an open item")
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
    if action == "snooze":
        if to is None:
            raise Refused("a snooze needs its date")
        m = DUE_RE.search(body)
        if m:
            new = body[: m.start("due")] + to.isoformat() + body[m.end("due"):]
        else:
            at = _trailing_field_start(body)
            span = reply_span(body)  # a reply is read only after the Due:, so the date goes ahead of it
            if span:
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
                or got[0].decided != parse_decided(text):
            raise Refused(f"after the edit the reader does not read Due: {to.isoformat()} "
                          "with the item's other fields unchanged")
        return new
    if action == "decide":
        answer = " ".join((answer or "").split())
        if not answer:
            raise Refused("the answer is empty")
        fld = f"Decided: {answer} ({today.isoformat()})."
        if parse_decided(text) is not None:
            m = DECIDED_RE.search(body)
            new = f"{body[: m.start()].rstrip()} {fld}"
        else:
            # the field starts a sentence (the reader's rule): end an unpunctuated item first
            head = body.rstrip()
            new = f"{head}{'' if head.endswith(('.', '?', '!')) else '.'} {fld}"
        got = parse_board(new, warn=False)
        if not got or got[0].decided != (answer, today) or got[0].answers != parse_answers(text) \
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
            raise Refused("a reply may not carry Context:, Answers:, Decided: or Closed: — the reader "
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
        if not got or (got[0].due, got[0].answers, got[0].consequences, got[0].decided) \
                != (was.due, was.answers, was.consequences, was.decided) \
                or parse_default(got[0].text) != parse_default(text) \
                or item_refs(got[0].text) != item_refs(text) \
                or replies[:-1] != parse_replies(body) or not replies \
                or replies[-1][:2] != (by, today.isoformat()) or replies[-1][2].rstrip(".") != words.rstrip(".") \
                or item_key(new) != item_key(body):
            raise Refused("the reader would not read the reply back, by that name, with the "
                          "item's other fields unchanged — rephrase it (or its name)")
        return new
    raise Refused(f"unknown action {action}")


def item_line(text: str, due: str, today: str, session: str | None, host: str | None,
              context: str | None) -> str:
    """A new item, in the board's own format —
    `- [ ] <today> (session `<name>` on <host>, or n/a) — <text>. Context: <about>. Due: <date>.`
    with its line ending. Refused for text that is empty or more than one line."""
    words = " ".join(str(text or "").split()).rstrip(".")
    if not words:
        raise Refused("a board line needs its text: what is needed, in your words")
    if "\n" in str(text).strip():
        raise Refused("a board line is one line: put the rest in the text on one line")
    try:
        date.fromisoformat(str(due))
    except ValueError:
        raise Refused(f"a board line needs a Due date as YYYY-MM-DD, not {due!r}") from None
    who = f"session `{session}` on {host}" if session else "n/a"
    ctx = " ".join(str(context or "").split()) or "none"
    return f"- [ ] {today} ({who}) — {words}. Context: {ctx}. Due: {due}.\n"


def decided_line(title: str, ref: str, answers: list[str], default: int | None, words: str, today: str) -> str:
    """A new item already decided, for a person's answer given elsewhere (on a ledger entry):
    `- [ ] decide <today> (person) — <title>. Context: <ref>. Due: <today>. Answers: a | b (default).
    Decided: <words> (<today>).` with its line ending. An answer may carry its consequence,
    `<label> — <consequence>`; the mark goes on the label. Refused for empty words, words
    carrying a field's name, or a line the reader would not read back."""
    head = ANY_FIELD_RE.sub(r"\1", " ".join(str(title or "").split())).rstrip(".") or ref
    said = " ".join(str(words or "").split())
    if not said:
        raise Refused("a decision needs its words: one of the entry's answers, or what you typed")
    if FIELD_NAME_RE.search(said):
        raise Refused("an answer may not carry Context:, Answers:, Decided: or Closed: — say it in other words")
    if any(REPLY_TAIL_RE.search(" ".join(str(a).split())) for a in answers or ()):
        raise Refused("an answer's consequence may not read as a reply (` — <name>, <date>: `) — say it in other words")
    def opt(a: str, marked: bool) -> str:
        label, cons, _ = split_answer(ANY_FIELD_RE.sub(r"\1", " ".join(str(a).split())).replace("|", "\\|"))
        return label + (" (default)" if marked else "") + (CONSEQUENCE_SEP + cons if cons else "")
    opts = [opt(a, i == default) for i, a in enumerate(answers or ()) if str(a).strip()]
    tail = f" Answers: {' | '.join(opts)}." if opts else ""
    body = f"decide {today} (person) — {_sentence(head)} Context: {ref}. Due: {today}.{tail} Decided: {said} ({today})."
    d, c = DECIDED_RE.search(body), CONTEXT_RE.search(body)
    if d is None or d.group("text") != said:
        raise Refused(f"the board's reader would not read back 'Decided: {said}': say it in other words")
    if c is None or c.group("ctx").rstrip(".") != ref:
        raise Refused(f"the board's reader would not read back 'Context: {ref}' on this entry's line")
    return f"- [ ] {body}\n"


# The commit subject of one board write: `<tool>: <action> <head>[ to <date> | : <answer>]
# (session <name>)`; for an append, `<tool>: append <head> (session <name>)`. A reply's words stay
# on the board, never in the subject.
EDIT_SUBJECT_RE = re.compile(r"^\S+: (?:snooze|done|decide|reply) .+ \(session [^)]+\)$")
APPEND_SUBJECT_RE = re.compile(r"^\S+: append .+ \(session [^)]+\)$")
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
    if action == "snooze" and not to:
        raise Refused("a snooze needs its date")
    what = (f" to {to.isoformat() if isinstance(to, date) else to}" if action == "snooze"
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


def subject_kind(line: str) -> str | None:
    """`edit` or `append` for a board write's commit subject, `queue` for a rank file write's (or a PR
    title carrying one); None otherwise."""
    if QUEUE_SUBJECT_RE.match(line):
        return "queue"
    if EDIT_SUBJECT_RE.match(line):
        return "edit"
    if APPEND_SUBJECT_RE.match(line) or any(r.match(line) for r in LEGACY_APPEND_SUBJECT_RES):
        return "append"
    return None


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
# The format version
# ---------------------------------------------------------------------------------------------

FORMAT_MAJOR = 1  # the newest major version of the formats this module reads
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
