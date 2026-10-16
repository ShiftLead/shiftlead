"""The ledger's entry headers, read (design §4.4 *Repo facts*, TD-176 slice 1).

A repo's ledger (`.shiftlead.yml`'s `ledger:`, default `docs/technical_debt.md`) is a file of
entries, each `## TD-NNN: title` followed by header fields — `**Priority:**`, `**Owner:**`,
`**Kind:**`, `**Type:**`, `**Blocked by:**`. This module is the one reader of those fields: the
Org's Repo facet and the Repo page count what it returns, and `tests/test_ledger.py` holds the
repo's own ledger to its rules through the same reader. Every line shape — a heading, a field, a
`Blocked by` item, `Answers:` — is ledgerboard's (`sessionorc.ledgerboard`, the vendored release,
ADR 2026-10-12, TD-585); what a field is *for* is this module's. **Pickable is derived** from `Blocked by:`
by cadence §2.4's rule (TD-228), the rule dev-cadence's `scripts/ledger.py` applies, and
`tests/test_ledger_derived.py` holds the two readers equal; a `**Pickable:**` line a ledger still
writes is not read.

Two reads. `entries` parses one version of the file: an entry counts while its section is in it.
`history` reads the file's git history in the checkout, so *opened* and *closed* in a window mean
the first commit whose file holds an entry's section and the first whose file no longer does.
Both are pure reads of files and git; neither writes anything.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from sessionorc import ledgerboard as lb
from sessionorc import paths
from sessionorc.models import owner_word

# origin's default branch as last fetched; the two usual names when `origin/HEAD` was never set
DEFAULT_REFS = ("origin/HEAD", "origin/main", "origin/master")
DEFAULT = "docs/technical_debt.md"  # the `ledger:` default, as `shiftlead.repoconfig` has it

# the fields ShiftLead reads further down the body when the header block lacks them, by any spelling
# (ledgerboard's `entries` reads Priority, Type and Blocked by there itself)
BELOW = ("owner", "kind", "answers")  # `answers`: a *for you* entry's, wherever it is written (TD-565)
BUILT = re.compile(r"#(\d+)")  # a `Kind: live-check #<n>` line's builds (design §4.9b, TD-323)
SQUASH = re.compile(r"\(#(\d+)\)\s*$")  # a squash commit's subject ends `(#<n>)`

# The page's seven kinds, in the order an entry is tested for them (§4.4 *Repo facts*, TD-418)
KINDS = ("for-you", "blocked", "design", "live-check", "pickable", "evaluation", "other")
LANE_KINDS = ("pickable", "design", "live-check")  # the kinds a lane word takes (§4.4 *In a team's lanes*)
PRIORITIES = ("high", "medium", "low")
TYPES = lb.TYPES  # cadence §2.11: pick order within a Priority; the first is the default
# The windows every count is kept for: the last day, week and month, rolling.
WINDOWS = {"day": timedelta(days=1), "week": timedelta(days=7), "month": timedelta(days=30)}
# A *for you* entry's reading for its Inbox row (§4.5 screen 6 *The ledger's entries that wait on you*,
# TD-565): its `**Answers:**` in cadence §3.5's form, and its Why and Fix clipped as a board item's
# detail block is (dev-cadence's `MAX_DETAIL_LINES`).
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DETAIL_FIELDS = ("Why", "Fix")
MAX_DETAIL_LINES = 20


def strip_comments(text: str) -> str:
    """The file without its HTML comments: the entry template lives in one and is headed TD-001,
    which is a real id."""
    return lb.COMMENT_RE.sub("", text)


_word = lb.first_word  # a field's first word, lower-cased: `**Kind:** build — …` is `build`


def _header(fields: dict[str, str], body: str) -> dict[str, str]:
    """ledgerboard's header fields of an entry, with ShiftLead's `BELOW` fields read from further
    down the body when the header block lacks them (the safe direction, as ledgerboard reads its
    own three); a repeated field, the first."""
    fields = dict(fields)
    for line in body.split("\n"):
        if (m := lb.FIELD_RE.match(line)) and (k := lb.field_key(m.group(1))) in BELOW and k not in fields:
            fields[k] = m.group(2)
    return fields


WAITS = ("until", "event")  # a `**Waits:**` line's first words (design §4.4 *An entry says what it waits for*)


def waits_of(value: str) -> dict[str, str] | None:
    """A `**Waits:**` line read (design §4.4 *An entry says what it waits for*, TD-715, built by TD-716):
    `{on, date, why}`, `on` its first word, `until` or `event`; `date` the first `YYYY-MM-DD` after
    `until` ('' for an `event`, or an `until` that names none); `why` the rest, its leading dash dropped.
    None for no line, or a first word outside the two (`ledger.py --check` flags that one)."""
    words = (value or "").strip()
    first = words.split()[0].lower() if words.split() else ""
    if first not in WAITS:
        return None
    rest = words[len(first) :]
    date = ""
    if first == "until" and (m := DATE.search(rest)):
        date, rest = m.group(0), rest[m.end() :]
    return {"on": first, "date": date, "why": rest.strip().lstrip("—–-").strip()}


def answers_of(value: str) -> tuple[list[str], int | None]:
    """An `**Answers:**` line read in the board's `Answers:` grammar (cadence §3.5), by ledgerboard's
    split and mark: the items split on `|` (`\\|` a literal bar), the closing full stop dropped, and
    the index of the one marked ` (default)` — None unless exactly one is (cadence §3.5, TD-066: at
    most one, and with two there is no single recommendation). The value is the field alone, so a
    `Due:` or `Decided:` in it is words, not a board item's trailing field."""
    out: list[str] = []
    marked: list[int] = []
    for raw in lb.ANSWER_SPLIT_RE.split((value or "").strip().rstrip(".")):
        words = raw.replace("\\|", "|").strip()
        if lb.DEFAULT_MARK_RE.search(words):
            words = lb.DEFAULT_MARK_RE.sub("", words).strip()
            if words:
                marked.append(len(out))
        if words:
            out.append(words)
    return out, marked[0] if len(marked) == 1 else None


def detail_of(body: str) -> list[str]:
    """The entry's **Why** and **Fix** paragraphs, each from its `**Name:**` line to the next blank
    line, at most `MAX_DETAIL_LINES` lines in all — what a *for you* row folds under *details*."""
    lines = body.split("\n")
    out: list[str] = []
    for name in DETAIL_FIELDS:
        at = next((i for i, ln in enumerate(lines) if (m := lb.FIELD_RE.match(ln)) and m.group(1) == name), None)
        if at is None:
            continue
        while at < len(lines) and lines[at].strip():
            out.append(lines[at].rstrip())
            at += 1
    return out[:MAX_DETAIL_LINES]


def _norm(tid: str) -> str:
    """An id by its number, as the script compares them: `TD-42` and `TD-042` are one entry."""
    return f"TD-{int(tid[3:]):03d}"


def blocked_ids(raw: str | None) -> list[str]:
    """An entry's whole `Blocked by:` ids, in order (§4.5 screen 11 *Its builds*, TD-693): the local
    `TD-NNN` items alone, no `<repo>#` item, no decision, each written `TD-NNN` as the archive's are,
    archived ones kept — unlike `blocked_by`, which is what still blocks."""
    out: list[str] = []
    for item in lb.parse_blocked(raw)[0] if raw else []:
        if "#" not in item and (tid := _norm(item)) not in out:
            out.append(tid)
    return out


def ids_in(text: str | None) -> set[str]:
    """The ids with a `## TD-NNN:` heading in a ledger or an archive, comments dropped."""
    return {f"TD-{n:03d}" for n in lb.heading_nums(text)}


# a `<repo>#TD-NNN` item → `(state, why)`, ledgerboard's resolver: `archived`, `open` or `unresolved`
Resolve = lb.Resolve
Live = Callable[[int], bool]  # a PR number → whether its squash commit is in the repo's live commit


def built(value: str) -> list[int]:
    """The builds a `**Kind:** live-check #<n>` line names (design §4.9b *A live check is a
    grinder's once its build is live*, TD-323): the `#<n>` after the kind's word, one or several,
    separated by spaces or commas. Anything else after the word — prose, nothing — names none, and
    the word itself is read as before."""
    m = lb.WORD_RE.search(value or "")
    rest = [t for t in re.split(r"[\s,]+", (value or "")[m.end() :] if m else "") if t]
    nums = [BUILT.fullmatch(t) for t in rest]
    return [int(x.group(1)) for x in nums] if rest and all(nums) else []


class LiveReader:
    """The home's `live` for one checkout (design §4.9b, TD-323): PR `n` is live when the commit on
    `origin/<default>` whose subject ends `(#n)` is an ancestor of `live`, the promote reading's live
    commit (§6 *Promote*). **Unknown is never live**: no live commit, no default branch here, no such
    commit, or git failing all read False. The log is read once, and only when asked."""

    def __init__(self, root: Path | str, live: str | None) -> None:
        self.root, self.live = root, live
        self._squash: dict[int, str] | None = None
        self._seen: dict[int, bool] = {}

    def __call__(self, n: int) -> bool:
        if not self.live:
            return False
        if n not in self._seen:
            if self._squash is None:
                self._squash = {}
                ref = default_ref(self.root)
                for line in ((_git(self.root, "log", "--format=%H %s", ref) if ref else None) or "").splitlines():
                    sha, _, subject = line.partition(" ")
                    if (m := SQUASH.search(subject)) and int(m.group(1)) not in self._squash:
                        self._squash[int(m.group(1))] = sha
            sha = self._squash.get(n)
            self._seen[n] = bool(sha) and _git(self.root, "merge-base", "--is-ancestor", sha, self.live) is not None
        return self._seen[n]


PERSON_OWNER = "paul"  # the person's owner word, as this ledger's `Fields:` line declares it (§4.4 *Repo facts*)
DESIGNER_OWNER = "designer"
ANCHOR_OWNER = "anchor"  # the anchor seat's owner word and lane word (§4.9b *The anchor seat*, §6 rule 6)


def decided_by(entry: dict[str, Any], who: str) -> bool:
    """Whether the entry's `Blocked by:` still names `decision (<who>)`, the holder compared
    lower-cased, so `decision (Paul)` is `paul`'s (TD-367)."""
    return any(
        b.startswith("decision (") and b[len("decision (") : -1].strip().lower() == who
        for b in entry.get("blocked_by") or []
    )


def kind_of(entry: dict[str, Any]) -> str:
    """The page's kind for an entry (§4.4 *Repo facts*, TD-418), tested in this order so each has
    one: *for you* — what waits on the person, and only that (TD-367): `Owner: paul`, or blocked by
    `decision (paul)`; *blocked* — `Blocked by:` holds any item other than a `decision (…)` (an open
    id, a cross-repo or unreadable one), whatever the Kind and whatever decision stands beside it;
    *design* — `Kind: design-first`, or blocked by `decision (designer)` alone; *live check* —
    `Kind: live-check`, its build live or not; *pickable* — pickable, `Kind: build` or none;
    *evaluation* — `Kind: evaluation`, an entry blocked by `decision (anchor)` alone, or an unblocked
    `Kind: decision` the anchor owns; else *other*, a residue that should be empty (`flags`)."""
    if str(entry.get("owner") or "").lower() == PERSON_OWNER or decided_by(entry, PERSON_OWNER):
        return "for-you"
    if any(not b.startswith("decision (") for b in entry.get("blocked_by") or []):
        return "blocked"
    if entry.get("kind") == "design-first" or decided_by(entry, DESIGNER_OWNER):
        return "design"
    if entry.get("kind") == "live-check":
        return "live-check"
    if entry.get("pickable") == "yes" and entry.get("kind") in ("", "build"):
        return "pickable"
    anchors = str(entry.get("owner") or "").lower() == ANCHOR_OWNER
    if entry.get("kind") == "evaluation" or decided_by(entry, ANCHOR_OWNER):
        return "evaluation"
    if entry.get("kind") == "decision" and anchors:  # unblocked: the tests above took what is blocked
        return "evaluation"
    return "other"


NO_KIND = "fits no page kind — check its Owner, Kind and Blocked by"
NO_DATE = "Waits: until names no date"  # it waits with no end (§4.4 *What a wait does*, TD-716)


def flags(entries: list[dict[str, Any]]) -> list[str]:
    """This reader's flag on each entry no page kind takes (§4.4 *Repo facts*, TD-418), and on each
    `Waits: until` that names no date (TD-716): the Repo page's *other* list and `ao repo` say it, and
    the bar still draws the entry."""
    out = [f"{e['id']}: {NO_KIND}" for e in entries if e.get("for_page") == "other"]
    return out + [
        f"{e['id']}: {NO_DATE}"
        for e in entries
        if isinstance(e.get("waits"), dict) and e["waits"].get("on") == "until" and not e["waits"].get("date")
    ]


def _buildlike(entry: dict[str, Any]) -> bool:
    """`free-pick`'s kinds: `build` or unwritten, and a live check that reads `live: yes` (§4.9b)."""
    return entry.get("kind") in ("", "build") or (entry.get("kind") == "live-check" and entry.get("live") == "yes")


def lane_matches(lane: list[str], entry: dict[str, Any]) -> bool:
    """Whether an entry belongs to a lane (design §6 rule 6, TD-195), by its header and never its
    prose. A word: `design-first` is a pickable entry with `Kind: design-first`, or any entry
    blocked by `decision (designer)`; `free-pick` a
    pickable one whose kind is `build` or unwritten (TD-228), or a live check whose build is live
    (§4.9b, TD-323), so a live check not yet live, an evaluation and a decision match no lane; a
    reference, or any other word, matches nothing until a role gives it a meaning here. **An
    `owner:<word>` narrows the rest** (TD-214, TD-227): with one or more, the entry's `Owner:` must
    be one named or absent, so `[free-pick, owner:grinder]` leaves the anchor's entries out; it
    matches nothing by itself. An entry blocked by `decision (designer)` is the designer's
    (TD-367): `design-first` takes it pickable or not, and its owner reads `designer`. A **work
    order** — a decided board line, `board:<key>` (§4.4 *Board write-back*, TD-384) — is in every
    `free-pick` lane, whatever `owner:` words stand beside it, and in every `anchor` lane; a red PR's,
    `pr:<n>` (TD-613), is in every `anchor` lane, and in a `free-pick` one only when it carries
    `free_pick` (no team servicing the repo has an anchor seat). **`anchor`**
    (TD-381, TD-386: the anchor seat's lane, which a person's own anchor session reads the same) is
    every pickable entry whose `Owner:` is `anchor`, of any kind — a live check once its build is
    live — any entry blocked by `decision (anchor)`, pickable or not, its owner then reading
    `anchor`, and every work order. **An entry still settling, or held** (`settling`, `held`: the home's
    marks, §4.4 *A new entry settles before it is pickable*, TD-710), **or waiting** (`waiting`, §4.4 *An
    entry says what it waits for*, TD-716), matches no lane."""
    if entry.get("settling") or entry.get("held") or entry.get("waiting"):
        return False
    owners = {o for w in lane if (o := owner_word(w))}
    if entry.get("work_order"):
        # a decided board line has no owner, and `owner:<word>` never narrows one out (TD-384); a red
        # PR's (TD-613) is the anchor's, and `free-pick`'s only where the team context set `free_pick`
        words = (ANCHOR_OWNER,) if entry.get("pr_order") and not entry.get("free_pick") else ("free-pick", ANCHOR_OWNER)
        return any(w in words and entry.get("pickable") == "yes" for w in lane)
    mine = (
        DESIGNER_OWNER
        if decided_by(entry, DESIGNER_OWNER)
        else ANCHOR_OWNER
        if decided_by(entry, ANCHOR_OWNER)
        else str(entry.get("owner") or "").lower()
    )
    if owners and mine and mine not in owners:
        return False
    return any(_word_matches(w, entry) for w in lane if owner_word(w) is None)


UNOWNED = "unowned"  # the rest's name for an entry with no `Owner:` (§4.4 *In a team's lanes*)


def in_lanes(
    entries: list[dict[str, Any]], records: list[dict[str, Any]], held: Collection[str] = ()
) -> dict[str, Any] | None:
    """What one team's lanes take of a repo's open entries (design §4.4 *In a team's lanes*, TD-357,
    TD-361) — the one reader the team card, the Repo page and `ao repo` draw from. `entries` are the
    reading's, each with its page kind (`for_page`); `records` the team's member records, live or
    ended, whose `lane`s are the team's lanes (`lane_matches`, rule 6's one rule); `held`, the
    references a live record of the repo holds claimed. Returns `pickable`, `design` and
    `live_check`, the ids of each `LANE_KINDS` kind in the lanes; `rest`, the *pickable* entries no
    lane takes, by `Owner:` (`UNOWNED` for none) as `[{owner, n, ids}]` in falling count then name
    (*design* and *live check* have none); `members`, **each record's own count** (TD-418, built by
    TD-428): `[{id, name, ids, k}]`
    for every record with a lane — what `lane_matches` takes for its own lane that `held` does not
    hold, rule 6's view whatever the page kind, and `k`, how many live records (not ended) carry the
    identical lane, the same set of words; and `out_of_work`, each record carrying `out_of_work`
    whose own count is above 0, `[{id, name, ids}]`, read from `members`. **A waiting entry** (its
    `waiting` mark, §4.4 *An entry says what it waits for*, TD-716) is in no kind, no `rest` and no
    member's `ids`: what a lane would take but for its wait is `waiting`, `{until: [ids], event:
    [ids]}`, each member's own beside its `ids` as `waiting`, and `out_of_work_waiting` names each
    record carrying `out_of_work` whose `ids` is empty and whose `waiting` is not, `[{id, name,
    waiting}]`. None where no record carries a lane: nothing is drawn."""
    lanes = [list(r["lane"]) for r in records if r.get("lane")]
    if not lanes:
        return None
    open_ = [e for e in entries if e.get("for_page") in LANE_KINDS]
    taken = {e["id"] for e in open_ if any(lane_matches(lane, e) for lane in lanes)}
    waits = {e["id"]: e for e in open_ if e.get("waiting") and any(lane_matches(lane, _unwaited(e)) for lane in lanes)}
    by_owner: dict[str, list[str]] = {}
    for e in open_:
        withheld = e.get("settling") or e.get("held") or e.get("waiting")
        if e["for_page"] == "pickable" and e["id"] not in taken and not withheld:
            by_owner.setdefault(str(e.get("owner") or "").lower() or UNOWNED, []).append(e["id"])
    rest = [{"owner": o, "n": len(ids), "ids": ids} for o, ids in by_owner.items()]
    rest.sort(key=lambda r: (-r["n"], r["owner"]))
    # live = not ended: the UI's `cards.DEAD`, written out since sessionorc never imports shiftlead
    alive = [frozenset(r["lane"]) for r in records if r.get("lane") and r.get("state") not in ("exited", "closed")]
    members = []
    for r in records:
        if not r.get("lane"):
            continue
        ids = [e["id"] for e in entries if e["id"] not in held and lane_matches(list(r["lane"]), e)]
        waiting = [
            e["id"]
            for e in entries
            if e.get("waiting") and e["id"] not in held and lane_matches(list(r["lane"]), _unwaited(e))
        ]
        name = r.get("name") or r.get("id")
        k = alive.count(frozenset(r["lane"]))
        members.append({"id": r.get("id"), "name": name, "ids": ids, "waiting": waiting, "k": k})
    by_id = {str(r.get("id")): r for r in records}
    idle = [
        {"id": m["id"], "name": m["name"], "ids": m["ids"]}
        for m in members
        if m["ids"] and by_id.get(str(m["id"]), {}).get("out_of_work")
    ]
    idle_waiting = [
        {"id": m["id"], "name": m["name"], "waiting": m["waiting"]}
        for m in members
        if not m["ids"] and m["waiting"] and by_id.get(str(m["id"]), {}).get("out_of_work")
    ]
    return {
        **{
            k.replace("-", "_"): [e["id"] for e in open_ if e["id"] in taken and e["for_page"] == k] for k in LANE_KINDS
        },
        "rest": rest,
        "members": members,
        "out_of_work": idle,
        "waiting": {on: [i for i, e in waits.items() if (e["waiting"].get("on") or "event") == on] for on in WAITS},
        "out_of_work_waiting": idle_waiting,
    }


def _unwaited(entry: dict[str, Any]) -> dict[str, Any]:
    """The entry as a lane would read it once its wait ends (TD-716): its `waiting` mark dropped."""
    return {k: v for k, v in entry.items() if k != "waiting"}


def _word_matches(word: str, entry: dict[str, Any]) -> bool:
    if word == "design-first" and decided_by(entry, DESIGNER_OWNER):
        return True
    if word == ANCHOR_OWNER and decided_by(entry, ANCHOR_OWNER):
        return True  # a decision the anchor owes is its to make, as the designer's is (§6 rule 6)
    if entry.get("pickable") != "yes":
        return False
    if word == ANCHOR_OWNER:
        live = entry.get("kind") != "live-check" or entry.get("live") == "yes"
        return str(entry.get("owner") or "").lower() == ANCHOR_OWNER and live
    if word == "design-first":
        return entry.get("kind") == "design-first"
    if word == "free-pick":
        return bool(entry.get("work_order")) or _buildlike(entry)
    return False


def entries(
    text: str, archive: str | None = None, resolve: Resolve | None = None, live: Live | None = None
) -> list[dict[str, Any]]:
    """Every entry of one version of the file, in file order: `id`, `title`, the header fields
    `priority`, `owner`, `kind` as their first word ('' when absent), `type` (`debt` unwritten or
    unknown), `blocked_by` — what still blocks, as the script lists it: open ids, `decision (<who>)`,
    an unread item quoted — `blocked_ids`, the whole line's local ids, archived ones kept — and
    `pickable`, `yes` or `no`, derived by cadence §2.4's rule (§4.4
    *Repo facts*, TD-228) as ledgerboard's `pickable` derives it (TD-585): blocked while `Blocked by:`
    names an id not in `archive` (open, or in neither file), a decision, or an item it cannot read;
    an id headed twice is blocked by what blocks either (ledgerboard keys its reading by id). A
    `<repo>#TD-NNN` item asks `resolve` for `(state, why)`, and anything but `archived` keeps the
    block; with no `resolve` it is unresolved. A written `**Pickable:**` line is not read (TD-228
    slice 4): what blocks an entry is said in `Blocked by:`. `for_page` is the page's kind. A field
    is read only from the entry's own section. A `Kind: live-check` entry also carries `built`, the
    PRs its line names, and `live`, `yes` when `live` says every one of them is live and `no`
    otherwise — no callable, no PR named (§4.9b, TD-323). `sig` is a hash of the entry's section text,
    which the home's settle clock compares (§4.4 *A new entry settles before it is pickable*, TD-710).
    An entry whose header block carries a `**Waits:**` line has `waits` (`waits_of`, TD-716); whether it
    still waits is the home's clock's, its `waiting` mark (`settle`)."""
    t = strip_comments(text)
    heads = list(lb.HEADING_RE.finditer(t))
    derived: dict[str, list[str]] = {}
    for r in lb.pickable(t, archive or "", resolve)["entries"]:
        got = derived.setdefault(r["id"], [])
        got += [b for b in r["blocked_by"] if b not in got]
    out: list[dict[str, Any]] = []
    for m, read in zip(heads, lb.entries(t), strict=True):
        nxt = lb.SECTION_RE.search(t, m.end())
        fields = _header(read["fields"], t[m.end() : nxt.start() if nxt else len(t)])
        etype = (fields.get("type") or "").split()[0].lower() if (fields.get("type") or "").split() else ""
        blocked_by = list(derived[m.group(1)])
        e = {
            "id": m.group(1),
            "title": read["title"],
            "priority": _word(fields.get("priority", "")),
            "owner": _word(fields.get("owner", "")),
            "kind": _word(fields.get("kind", "")),
            "type": etype if etype in TYPES else TYPES[0],
            "blocked_by": blocked_by,
            "blocked_ids": blocked_ids(read["blocked_raw"]),
            "pickable": "no" if blocked_by else "yes",
            "sig": hashlib.sha256(t[m.start() : nxt.start() if nxt else len(t)].encode()).hexdigest()[:16],
        }
        if waits := waits_of(read["fields"].get("waits", "")):  # the header block's line alone (§4.4)
            e["waits"] = waits
        if e["kind"] == "live-check":
            e["built"] = built(fields.get("kind", ""))
            e["live"] = "yes" if live is not None and e["built"] and all(live(n) for n in e["built"]) else "no"
        e["for_page"] = kind_of(e)
        # an Inbox row's reading (TD-565) on every open entry: a hold is marked after the parse, and a
        # held row opens with its Why and Fix (§4.5 screen 6 *A held entry waits on the person too*, TD-736)
        added = DATE.search(fields.get("added", ""))
        e["added"] = added.group(0) if added else ""
        e["detail"] = detail_of(t[m.end() : nxt.start() if nxt else len(t)])
        if e["for_page"] == "for-you":
            e["answers"], e["default"] = answers_of(fields.get("answers", ""))
        out.append(e)
    return out


def archive_path(rel: str) -> str:
    """The archive beside a ledger: its name with `_archive` before its suffix (§4.4 *Repo facts*),
    which for the default is cadence's `docs/technical_debt_archive.md`."""
    p = Path(rel)
    return str(p.with_name(f"{p.stem}_archive{p.suffix}"))


def _git(root: Path | str, *args: str, timeout: float = 10.0) -> str | None:
    try:
        cp = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, errors="replace", timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.stdout if cp.returncode == 0 else None


def default_ref(root: Path | str, timeout: float = 10.0) -> str | None:
    """`origin/<default>` as cadence §9's default-branch rule names it, the script's own: the first
    of `origin/HEAD`'s target, `init.defaultBranch`, `main` and `master` that exists on origin; None
    where none does (the working tree is read instead)."""
    names: list[str] = []
    if head := _git(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", timeout=timeout):
        names.append(head.strip().removeprefix("refs/remotes/origin/"))
    if init := _git(root, "config", "--get", "init.defaultBranch", timeout=timeout):
        names.append(init.strip())
    for name in dict.fromkeys([*names, "main", "master"]):
        if name and _git(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}", timeout=timeout):
            return f"origin/{name}"
    return None


class Registry:
    """Resolves `<repo>#TD-NNN` through the home's registry (§4.4 *Repo facts*: the host's
    `repos()`), as the script's roster does: `<repo>` is a checkout's directory name and `owner/name`
    its origin; that checkout's `docs/technical_debt.md` and its archive are read at
    `origin/<default>`, or in the working tree where that ref is missing. Each repo is read once, and
    only when asked; a name two checkouts share, a checkout not listed, a ledger that cannot be read
    or an id in neither file is `unresolved`, which keeps the block. Each answer is ledgerboard's
    `(state, why)`, `why` empty unless it is unresolved (TD-585)."""

    LEDGER, ARCHIVE = DEFAULT, archive_path(DEFAULT)

    def __init__(self, roots: list[str]) -> None:
        self.roots = [Path(r) for r in roots]
        self._read: dict[Path, tuple[set[str], set[str]] | None] = {}
        self._origins: dict[Path, str] = {}

    def _origin(self, root: Path) -> str:
        if root not in self._origins:
            url = (_git(root, "remote", "get-url", "origin") or "").strip().lower()
            self._origins[root] = url.removesuffix("/").removesuffix(".git")
        return self._origins[root]

    def _find(self, repo: str) -> Path | None:
        name = repo.lower()
        if "/" in name:
            hits = [r for r in self.roots if self._origin(r).endswith(("/" + name, ":" + name))]
        else:
            hits = [r for r in self.roots if r.name.lower() == name]
        return hits[0] if len(hits) == 1 else None

    def _repo(self, root: Path) -> tuple[set[str], set[str]] | None:
        if root not in self._read:
            ref = default_ref(root)

            def read(rel: str) -> str | None:
                if ref is not None:
                    return _git(root, "show", f"{ref}:{rel}")
                try:
                    return (root / rel).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return None

            led = read(self.LEDGER)
            self._read[root] = None if led is None else (ids_in(led), ids_in(read(self.ARCHIVE)))
        return self._read[root]

    def __call__(self, item: str) -> tuple[str, str]:
        m = lb.XREPO_ITEM_RE.match(item)
        if m is None:
            return "unresolved", f"{item!r} is not <repo>#TD-NNN"
        root = self._find(m.group(1))
        if root is None:
            return "unresolved", f"no one checkout named {m.group(1)!r} in the home's registry"
        got = self._repo(root)
        if got is None:
            return "unresolved", f"{root}'s {self.LEDGER} cannot be read"
        tid = _norm(m.group(2))
        if tid in got[1]:
            return "archived", ""
        if tid in got[0]:
            return "open", ""
        return "unresolved", f"{m.group(2)} is in neither {root.name}'s ledger nor its archive"


def ledger_path(root: Path | str) -> str:
    """The checkout's ledger file, relative to it: `.shiftlead.yml`'s `ledger:` when it names one,
    else the default. An unreadable file is the default, as it is for `shiftlead.repoconfig`."""
    try:
        doc = yaml.safe_load(paths.repo_file(root).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return DEFAULT
    got = doc.get("ledger") if isinstance(doc, dict) else None
    return got.strip() if isinstance(got, str) and got.strip() else DEFAULT


@dataclass
class Change:
    """One entry's life in the file's history: when its section first appeared, and when it left
    (None while it is still there) — and `pr`, the PR whose squash merge removed it: the closing
    commit's subject's `(#n)` (`SQUASH`), None for a commit with none, a direct push (TD-604)."""

    id: str
    title: str
    opened: datetime
    closed: datetime | None = None
    pr: int | None = None


def _parse_log(out: str, skip: set[str]) -> dict[str, Change]:
    """The changes from `git log --reverse -p --unified=0`: a commit is a `\\x00C <sha> <iso> <subject>`
    line, then its diff; a heading on a `+` line is in the file after that commit, on a `-` line it left.
    A heading both removed and added in one commit (an entry moved in the file, its title edited)
    stays. An entry closed and later re-added is open again from its first opening."""
    life: dict[str, Change] = {}
    present: set[str] = set()

    def apply(at: datetime | None, pr: int | None, added: dict[str, str], removed: set[str]) -> None:
        if at is None:
            return
        for tid in removed - set(added):
            if tid in present:
                present.discard(tid)
                life[tid].closed, life[tid].pr = at, pr
        for tid, title in added.items():
            if tid not in life:
                life[tid] = Change(tid, title, at)
            else:
                life[tid].title = title or life[tid].title
                if tid not in present:
                    life[tid].closed, life[tid].pr = None, None
            present.add(tid)

    at: datetime | None = None
    pr: int | None = None
    added: dict[str, str] = {}
    removed: set[str] = set()
    for line in out.splitlines():
        if line.startswith("\x00C "):
            apply(at, pr, added, removed)
            added, removed = {}, set()
            parts = line.split(" ", 3)
            try:
                at = datetime.fromisoformat(parts[2].strip())
            except (IndexError, ValueError):
                at = None
            m = SQUASH.search(parts[3]) if len(parts) > 3 else None
            pr = int(m.group(1)) if m else None
            continue
        if line[:1] in "+-" and (tid := lb.entry_id(line[1:])):
            if tid in skip:
                continue
            if line[0] == "+":
                added[tid] = line[1:].partition(":")[2].strip()
            else:
                removed.add(tid)
    apply(at, pr, added, removed)
    return life


def history(root: Path | str, rel: str, text: str = "", timeout: float = 30.0) -> dict[str, Change] | None:
    """Every entry's opened / closed instants from the ledger file's git history in `root`, or None
    when git could not be asked (not a repo, git missing, a timeout) — *could not look*, never
    *nothing changed*. `text` is the file as it stands, so the ids of headings that sit only in a
    comment (the entry template's) are left out. A file rewritten without a history reads as
    opened at its first commit, which is all its history says."""
    skip = {m.group(1) for m in lb.HEADING_RE.finditer(text)} - {
        m.group(1) for m in lb.HEADING_RE.finditer(strip_comments(text))
    }
    try:
        cp = subprocess.run(
            [
                "git", "log", "--first-parent", "--diff-merges=first-parent", "--reverse", "--no-renames",
                "--format=%x00C %H %cI %s", "-p", "--unified=0", "--", rel,
            ],
            capture_output=True, text=True, errors="replace", timeout=timeout, cwd=str(root),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    return _parse_log(cp.stdout, skip)


def entries_before(
    root: Path | str,
    rel: str,
    before: datetime | None,
    timeout: float = 10.0,
    resolve: Resolve | None = None,
    live: Live | None = None,
) -> tuple[list[dict[str, Any]] | None, str]:
    """The ledger's entries as the last commit of `origin/<default>` before `before` held them
    (design §6 rule 6, TD-227: `lane_seen`'s first write is the ledger at the declaration), and
    what was read — `origin/main at 1a2b3c4d` — or None and why not; the archive is read at the same
    commit, so `pickable` is derived as it was then, except that a `<repo>#TD-NNN` item is resolved at
    the other repo's `origin/<default>` as it stands now. `--before` reads committer dates, which is the
    merge's time for a squash. `before` None reads the ref's tip. Read-only: nothing is fetched."""
    for ref in DEFAULT_REFS:
        when = [f"--before={before.isoformat()}"] if before is not None else []
        sha = _git(root, "rev-list", "-1", *when, ref, timeout=timeout)
        if sha is None:
            continue  # no such ref here: the next name
        if not (sha := sha.strip()):
            return None, f"no commit of {ref} before {before.isoformat() if before else 'now'}"
        text = _git(root, "show", f"{sha}:{rel}", timeout=timeout)
        if text is None:
            return None, f"no {rel} at {ref} {sha[:8]}"
        archive = _git(root, "show", f"{sha}:{archive_path(rel)}", timeout=timeout)
        return entries(text, archive, resolve, live), f"{ref} at {sha[:8]}"
    return None, "no origin/<default> here"


def _count(stamps: list[datetime], now: datetime) -> dict[str, int]:
    return {w: sum(1 for t in stamps if t > now - span) for w, span in WINDOWS.items()}


def reading(
    root: Path | str,
    now: datetime,
    *,
    with_history: bool = True,
    rel: str | None = None,
    resolve: Resolve | None = None,
    live: Live | None = None,
) -> dict[str, Any]:
    """The ledger reading of one checkout (§4.4 *Repo facts*): `{path, entries, by_priority,
    by_kind, archived, windows, recent, at}`, or `{path, error}` when the file cannot be read. The archive
    beside the ledger (`archive_path`; none there, nothing archived) and `resolve` — the home's
    `Registry` — derive each entry's `pickable`; `live` — the home's `LiveReader` — a live check's
    `live`. `windows` is `{day|week|month: {opened, closed}}`
    from the history and `recent` the entries opened or closed in the longest window, newest first —
    both absent when the history was not read, and marked `history_error` when git could not be
    asked. `archived` is the archived ids some entry's `blocked_ids` names, never the whole archive
    (§4.5 screen 11 *Its builds*, TD-693)."""
    rel = rel or ledger_path(root)
    try:
        text = (Path(root) / rel).read_text(encoding="utf-8")
    except OSError as e:
        return {"path": rel, "error": f"{rel}: {e.strerror or e}", "at": now.isoformat()}
    try:
        archive: str | None = (Path(root) / archive_path(rel)).read_text(encoding="utf-8")
    except OSError:
        archive = None
    got = entries(text, archive, resolve, live)
    out: dict[str, Any] = {
        "path": rel,
        "entries": got,
        "by_priority": {p: sum(1 for e in got if e["priority"] == p) for p in PRIORITIES},
        "by_kind": {k: sum(1 for e in got if e["for_page"] == k) for k in KINDS},
        "archived": sorted(ids_in(archive) & {b for e in got for b in e["blocked_ids"]}),
        "at": now.isoformat(),
    }
    if not with_history:
        return out
    life = history(root, rel, text)
    if life is None:
        out["history_error"] = "git could not read the ledger's history"
        return out
    opened = [c.opened for c in life.values()]
    closed = [c.closed for c in life.values() if c.closed]
    out["windows"] = {w: {"opened": o, "closed": _count(closed, now)[w]} for w, o in _count(opened, now).items()}
    since = now - WINDOWS["month"]
    recent = [c for c in life.values() if c.opened > since or (c.closed and c.closed > since)]
    recent.sort(key=lambda c: max(c.opened, c.closed or c.opened), reverse=True)
    out["recent"] = [
        {
            "id": c.id,
            "title": c.title,
            "opened": c.opened.isoformat(),
            "closed": c.closed and c.closed.isoformat(),
            "pr": c.pr if c.closed else None,
        }
        for c in recent
    ]
    return out


def completed(recent: list[dict[str, Any]] | None, prs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """*What closed, and by which PR* (design §4.4 *Repo facts*, TD-604): the ledger reading's `recent`
    entries that closed, newest first, each `{id, title, closed, pr, author, branch, url}` — `pr` the
    closing commit's squash number (None: a direct push), and `author`, `branch` and `url` the month's
    PR reading's by that number (empty where it holds none), so a view can name the session whose
    branch it was. The archive is not read."""
    by_number = {p.get("number"): p for p in prs or () if isinstance(p, dict)}
    out = []
    for e in recent or ():
        if not isinstance(e, dict) or not e.get("closed"):
            continue
        pr = e.get("pr")
        p = by_number.get(pr) if pr is not None else None
        out.append(
            {
                "id": e.get("id"),
                "title": e.get("title") or "",
                "closed": e["closed"],
                "pr": pr,
                "author": str((p or {}).get("author") or ""),
                "branch": str((p or {}).get("branch") or ""),
                "url": str((p or {}).get("url") or ""),
            }
        )
    out.sort(key=lambda c: datetime.fromisoformat(str(c["closed"])), reverse=True)  # offsets differ by committer
    return out
