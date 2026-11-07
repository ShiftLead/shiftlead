"""The ledger's entry headers, read (design §4.4 *Repo facts*, TD-176 slice 1).

A repo's ledger (`.shiftlead.yml`'s `ledger:`, else `docs/ledger` where that is a directory, else
`docs/technical_debt.md`: `ledger_path`) is a v1 file or a v2 directory of one file per entry (agent-cadence
TD-160), read through ledgerboard's one `load()` with this module's `fs_io` or `git_io` (§4.4 **Either
layout**, TD-1144) — the same text either way, of entries, each `## TD-NNN: title` followed by header fields —
`**Priority:**`, `**Owner:**`, `**Kind:**`, `**Type:**`, `**Blocked by:**`. This module is the one reader of
those fields: the Org's Repo facet and the Repo page count what it returns, and `tests/test_ledger.py` holds
the repo's own ledger to its rules through the same reader. Every line shape — a heading, a field, a `Blocked by`
item, `Answers:` — is ledgerboard's (`sessionorc.ledgerboard`, the vendored release, ADR 2026-10-12,
TD-585); what a field is *for* is this module's. **Pickable is derived** from `Blocked by:` by cadence §2.4's
rule (TD-228), the rule agent-cadence's `scripts/ledger.py` applies, and `tests/test_ledger_derived.py` holds
the two readers equal; a `**Pickable:**` line a ledger still writes is not read.

Two reads. `entries` parses one version of the file: an entry counts while its section is in it.
`history` reads the file's git history in the checkout, so *opened* and *closed* in a window mean
the first commit whose file holds an entry's section and the first whose file no longer does.
Both are pure reads of files and git; neither writes anything.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from sessionorc import ledgerboard as lb
from sessionorc import mail, paths
from sessionorc.models import owner_word

# origin's default branch as last fetched; the two usual names when `origin/HEAD` was never set
DEFAULT_REFS = ("origin/HEAD", "origin/main", "origin/master")
DEFAULT = "docs/technical_debt.md"  # the `ledger:` default, as `shiftlead.repoconfig` has it
LEDGER_REL, ARCHIVE_REL = DEFAULT, "docs/technical_debt_archive.md"  # agent-cadence's `ledger.py`'s names
LEDGER_DIR_REL = "docs/ledger"  # a v2 ledger (dev-cadence TD-160): the default where it is a directory

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
# detail block is (agent-cadence's `MAX_DETAIL_LINES`).
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


WAITS = ("until", "event")  # what a `waiting` mark is `on` (design §4.4 *An entry says what it waits for*)


def is_gate(item: str) -> bool:
    """Whether one `blocked_by` item is an `until` or `event` gate as ledgerboard writes it (design §4.4 *An
    entry says what it waits for*, TD-1395): what the page kind reads past, and a wait, never a block."""
    g = lb.parse_gates(item)
    return bool(g["until"] or g["events"]) and not (g["ids"] or g["decisions"] or g["bad"] or g["retired"])


def gates_of(blocked_raw: str | None, section: str) -> dict[str, Any] | None:
    """An entry's `until` and `event` gates (design §4.4 *An entry says what it waits for*, TD-1395), read
    through ledgerboard's `parse_gates`: `{until: [dates], events: [{name, why}]}`, `why` the first line of
    the entry's `**Event (<name>):**` section ('' for none); None when its `Blocked by:` holds neither.
    `section` is the entry's text from its heading."""
    g = lb.parse_gates(blocked_raw)
    if not (g["until"] or g["events"]):
        return None
    words = {s["name"]: s["words"] for s in lb.event_sections(section) if s.get("name")}
    return {"until": list(g["until"]), "events": [{"name": n, "why": words.get(n, "")} for n in g["events"]]}


def only_gated(entry: Mapping[str, Any]) -> bool:
    """Whether what keeps an entry from pickable is at most its `until` and `event` gates (TD-1395): no open
    id, no decision, no unreadable item and no open part."""
    return not entry.get("parts_open") and all(is_gate(str(b)) for b in entry.get("blocked_by") or [])


def until_of(blocked_raw: str | None) -> str:
    """The words after a `decision (<who>)` item's dash, as written — what the Queue card's row reads as
    *held until <them>* (design §4.5 screen 12, §4.5a *Queue card: what needs the person*, TD-795);
    '' when the line has no decision, nothing after it, or a list going on past it."""
    old = lb.parse_gates(blocked_raw)["old_form"]  # v2.4: the old form's text, read only as the last item
    return old[1].lstrip("—–-").strip() if old else ""


def answers_of(value: str) -> tuple[list[str], list[str], int | None]:
    """An `**Answers:**` line read in the board's `Answers:` grammar (cadence §3.5), by ledgerboard's
    split and mark: the items split on `|` (`\\|` a literal bar), the closing full stop dropped, each
    split on its first ` — ` into its label and what it leads to (§4.10 *The answers' split*, TD-913),
    and the index of the one whose label is marked ` (default)` — None unless exactly one is (cadence
    §3.5, TD-066: at most one, and with two there is no single recommendation). `(labels, consequences,
    default)`. The value is the field alone, so a `Due:` or `Decided:` in it is words, not a board item's
    trailing field."""
    out: list[str] = []
    consequences: list[str] = []
    marked: list[int] = []
    for raw in lb.ANSWER_SPLIT_RE.split((value or "").strip().rstrip(".")):
        # split as `mail.split_answer` does, uncapped: a ledger answer is what a decided line writes (TD-913)
        words, _sep, consequence = raw.replace("\\|", "|").strip().partition(mail.CONSEQUENCE_SEP)
        words, consequence = words.strip(), consequence.strip()
        if lb.DEFAULT_MARK_RE.search(words):
            words = lb.DEFAULT_MARK_RE.sub("", words).strip()
            if words:
                marked.append(len(out))
        if words:
            out.append(words)
            consequences.append(consequence)
    return out, consequences, marked[0] if len(marked) == 1 else None


def ask_of(body: str) -> str:
    """The entry's `**Ask:**` line, from it to the next blank line, folded to one line and its name dropped —
    the one sentence its Queue item leads with (§4.10 *An item leads with one sentence*, TD-913); '' when the
    body has none. Read from the body, as `detail_of` reads Why and Fix, never from the header block."""
    lines = body.split("\n")
    at = next((i for i, ln in enumerate(lines) if (m := lb.FIELD_RE.match(ln)) and m.group(1) == "Ask"), None)
    if at is None:
        return ""
    out: list[str] = []
    while at < len(lines) and lines[at].strip():
        out.append(lines[at])
        at += 1
    return " ".join(" ".join(out).split()).removeprefix("**Ask:**").strip()


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


def xrepo_ids(raw: str | None) -> list[str]:
    """An entry's `<repo>#TD-NNN` `Blocked by:` items, in order, each id written `TD-NNN` — the edges
    that join a card across repos (§4.4 *The Queue*, TD-769), whether they still block or not."""
    out: list[str] = []
    for item in lb.parse_blocked(raw)[0] if raw else []:
        if (m := lb.XREPO_ITEM_RE.match(item)) and (x := f"{m.group(1)}#{_norm(m.group(2))}") not in out:
            out.append(x)
    return out


def ids_in(text: str | None) -> set[str]:
    """The ids with a `## TD-NNN:` heading in a ledger or an archive, comments dropped."""
    return {f"TD-{n:03d}" for n in lb.heading_nums(text)}


def parts_of_open(archive: str | None, open_: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The archived parts of each open parent (ADR 2026-10-27 §3, TD-1130): by the parent's id written
    `TD-NNN`, the archived ids whose `Part of:` names it, in archive order, its line parsed as an open
    entry's is."""
    live = {_norm(e["id"]) for e in open_}
    out: dict[str, list[str]] = {}
    for e in lb.entries(archive or ""):
        par = lb.parse_part_of(e.get("part_of_raw"))[0]
        if par and _norm(par) in live and (tid := _norm(e["id"])) not in out.get(_norm(par), []):
            out.setdefault(_norm(par), []).append(tid)
    return out


def builds_open(entry: dict[str, Any]) -> bool:
    """Whether an open entry has open builds, the guard that keeps **Done…** off its row (§4.5 screen 12,
    §4.9c, TD-1130): some open entry names it in `Part of:` (`parts_open`). What its `Blocked by:` names is
    a blocker, never a build (TD-1133's backfill)."""
    return bool(entry.get("parts_open"))


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


# the person's owner word, as this ledger's `Fields:` line declares it (§4.4 *Repo facts*): the `<person>` of every
# `decision (<person>)` the code writes or reads, held here once (§4.4 *Holding an entry is a decision on it*)
PERSON_OWNER = "paul"


def decided_by(entry: dict[str, Any], who: str) -> bool:
    """Whether the entry's `Blocked by:` still names `decision (<who>)`, the holder compared
    lower-cased, so `decision (Paul)` is `paul`'s (TD-367)."""
    return any(
        b.startswith("decision (") and b[len("decision (") : -1].strip().lower() == who
        for b in entry.get("blocked_by") or []
    )


def kind_of(entry: dict[str, Any]) -> str:
    """The page's kind for an entry (§4.4 *Repo facts*, TD-418), tested in this order so each has
    one: *for you* — what waits on the person, and only that (TD-367): blocked by `decision (paul)`
    (an Owner holds nothing, TD-1375); *blocked* — `Blocked by:` holds any item other than a `decision (…)` (an open
    id, a cross-repo or unreadable one), whatever the Kind and whatever decision stands beside it — an `until`
    or `event` gate aside, which the kinds read past so they count what a waiting entry is (TD-1395);
    or some open entry names it in `Part of:` (`parts_open`, TD-1130);
    *design* — `Kind: design-first` (a decision owed to the designer is that `Kind:`, TD-1296); *live check* —
    `Kind: live-check`, its build live or not; *pickable* — pickable, `Kind: build` or none;
    *evaluation* — `Kind: evaluation`, which no lane takes since the anchor seat is retired (§4.9b
    *No anchor seat*), so `flags` names each; else *other*, a residue that should be empty (`flags`),
    an unblocked `Kind: decision` that is not the person's among it."""
    if decided_by(entry, PERSON_OWNER):
        return "for-you"
    blocks = [b for b in entry.get("blocked_by") or [] if not is_gate(b)]  # read past a wait (TD-1395)
    if any(not b.startswith("decision (") for b in blocks) or entry.get("parts_open"):
        return "blocked"
    if entry.get("kind") == "design-first":
        return "design"
    if entry.get("kind") == "live-check":
        return "live-check"
    if (entry.get("pickable") == "yes" or only_gated(entry)) and entry.get("kind") in ("", "build"):
        return "pickable"
    if entry.get("kind") == "evaluation":
        return "evaluation"
    return "other"


NO_KIND = "fits no page kind — check its Owner, Kind and Blocked by"
NO_LANE = "no lane takes an evaluation — write it as a build whose Fix is the write-up, or as design-first"


def flags(entries: list[dict[str, Any]]) -> list[str]:
    """This reader's flag on each entry no page kind takes (§4.4 *Repo facts*, TD-418), on each
    evaluation, which no lane takes (§4.9b *No anchor seat*, TD-757): the Repo page's *other* list and
    `ao repo` say it, and the bar still draws the entry."""
    out = [f"{e['id']}: {NO_KIND}" for e in entries if e.get("for_page") == "other"]
    return out + [f"{e['id']}: {NO_LANE}" for e in entries if e.get("for_page") == "evaluation"]


def _buildlike(entry: dict[str, Any]) -> bool:
    """`free-pick`'s kinds: `build` or unwritten, and a live check that reads `live: yes` (§4.9b)."""
    return entry.get("kind") in ("", "build") or (entry.get("kind") == "live-check" and entry.get("live") == "yes")


def lane_matches(lane: list[str], entry: dict[str, Any], team: str | None = None) -> bool:
    """Whether an entry belongs to a lane (design §6 rule 6, TD-195), by its header and never its
    prose. A word: `design-first` is a pickable entry with `Kind: design-first`; `free-pick` a
    pickable one whose kind is `build` or unwritten (TD-228), or a live check whose build is live
    (§4.9b, TD-323), so a live check not yet live, an evaluation and a decision match no lane; a
    reference, or any other word, matches nothing until a role gives it a meaning here. **An
    `owner:<word>` narrows the rest** (TD-214, TD-227): with one or more, the entry's `Owner:` must
    be one named or absent, so `[free-pick, owner:grinder]` leaves the designer's entries out; it
    matches nothing by itself. A **work
    order** — a decided board line, `board:<key>` (§4.4 *Board write-back*, TD-384) — is in every
    `free-pick` lane, whatever `owner:` words stand beside it, and so is a red PR's, `pr:<n>` (TD-613):
    the grinders' pick list, since the anchor seat is retired (§4.9b *No anchor seat*, TD-757). **An
    entry still settling** (`settling`: the home's mark, §4.4 *A new entry settles before it is pickable*,
    TD-710), **or waiting** (`waiting`, §4.4 *An
    entry says what it waits for*, TD-716), matches no lane. **`team`** is the lane's record's (§4.4 *An
    entry names its team*, TD-730): an entry marked `needs_team` matches nothing; one with a `team`
    matches only a lane of that team, case-folded; a lane with no team ('' or None) narrows nothing;
    a work order carries no team and matches as its own rule says."""
    if entry.get("settling") or entry.get("waiting"):
        return False
    owners = {o for w in lane if (o := owner_word(w))}
    if not entry.get("work_order"):
        if entry.get("needs_team"):
            return False
        mine_team = str(entry.get("team") or "").casefold()
        if team and mine_team and mine_team != team.casefold():
            return False
    if entry.get("work_order"):
        # a decided board line has no owner, and `owner:<word>` never narrows one out (TD-384); nor a
        # red PR's (TD-613): both are on the grinders' pick list (§4.9b *No anchor seat*)
        return "free-pick" in lane and entry.get("pickable") == "yes"
    mine = str(entry.get("owner") or "").lower()
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
    waiting}]`. Each lane is read with its record's `team` (§4.4 *An entry names its team*, TD-730), and
    an entry marked `needs_team` is in no kind, no `rest` and no member's `ids`; another team's entry is in
    no `rest` of a team's records. None where no record
    carries a lane: nothing is drawn."""
    lanes = [(list(r["lane"]), str(r.get("team") or "")) for r in records if r.get("lane")]
    if not lanes:
        return None
    open_ = [e for e in entries if e.get("for_page") in LANE_KINDS]
    taken = {e["id"] for e in open_ if any(lane_matches(lane, e, t) for lane, t in lanes)}
    waits = {
        e["id"]: e for e in open_ if e.get("waiting") and any(lane_matches(lane, _unwaited(e), t) for lane, t in lanes)
    }
    by_owner: dict[str, list[str]] = {}
    ours = {t.casefold() for _, t in lanes if t}  # another team's entry is in its own team's rest, not this one's
    for e in open_:
        withheld = e.get("settling") or e.get("waiting") or e.get("needs_team")
        if ours and str(e.get("team") or "") and str(e["team"]).casefold() not in ours:
            continue
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
        team = str(r.get("team") or "")
        ids = [e["id"] for e in entries if e["id"] not in held and lane_matches(list(r["lane"]), e, team)]
        waiting = [
            e["id"]
            for e in entries
            if e.get("waiting") and e["id"] not in held and lane_matches(list(r["lane"]), _unwaited(e), team)
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
    """The entry as a lane would read it once its wait ends (TD-716): its `waiting` mark dropped, and one kept
    from pickable by its `until` and `event` gates alone read pickable with them removed (TD-1395), as
    ledgerboard gives it `pickable: no` with them in `blocked_by`."""
    out = {k: v for k, v in entry.items() if k != "waiting"}
    if entry.get("gates") and only_gated(entry):
        out["blocked_by"], out["pickable"] = [], "yes"
    return out


def _word_matches(word: str, entry: dict[str, Any]) -> bool:
    if entry.get("pickable") != "yes":
        return False
    if word == "design-first":
        return entry.get("kind") == "design-first"
    if word == "free-pick":
        return bool(entry.get("work_order")) or _buildlike(entry)
    return False


def declared_teams(text: str) -> tuple[str, ...]:
    """The repo's teams, in order: the `Team` vocabulary of the ledger's `Fields:` line, as ledgerboard's
    `declared` reads it, each lower-cased (§4.4 *An entry names its team*, TD-730); () for none."""
    return lb.declared(text)[0].get("team", ())


def team_need(entry: dict[str, Any], teams: Collection[str]) -> str:
    """Why an entry needs a team (§4.4 *An entry names its team*, *What the reader marks*, TD-730): `unknown
    <name>` wherever a vocabulary is declared and its `team` is not in it; `untagged` where the vocabulary
    names two or more and the entry, of a kind a lane takes, names none; else ''. Names compare case-folded."""
    names = {n.casefold() for n in teams}
    team = str(entry.get("team") or "").casefold()
    if names and team and team not in names:
        return f"unknown {team}"
    if len(names) >= 2 and not team and entry.get("for_page") in LANE_KINDS:
        return "untagged"
    return ""


def kept_waiting_of(section: str) -> dict[str, str]:
    """The newest `kept waiting: <gate> — by …` Log line's date of one entry's section, by gate, the gate
    compared as ledgerboard does (spaces folded, lower case) — `{"decision (paul)": "2026-11-04"}` — or {}
    (design §4.4 *The card's status*, TD-1368). Read from the Log itself, never `gate_age`, which also counts
    `gate added` and a reassignment; an entry whose Log cannot be read has none."""
    if "kept waiting:" not in section:
        return {}  # most entries: no Log line to parse on every ledger read
    try:
        lines = lb.log_lines(section)
    except Exception:  # noqa: BLE001 — an entry ledgerboard refuses has no Log to read
        return {}
    out: dict[str, str] = {}
    for ln in lines:
        if ln.get("kind") == "kept-waiting" and ln.get("date") and ln.get("gate"):
            gate = " ".join(str(ln["gate"]).split()).lower()
            if str(ln["date"]) > out.get(gate, ""):
                out[gate] = str(ln["date"])
    return out


def entries(
    text: str,
    archive: str | None = None,
    resolve: Resolve | None = None,
    live: Live | None = None,
    *,
    rank_text: str | None = None,
    repo: str = "",
) -> list[dict[str, Any]]:
    """Every entry of one version of the file, in file order: `id`, `title`, the header fields
    `priority`, `owner`, `kind` as their first word ('' when absent), `type` (`debt` unwritten or
    unknown), `blocked_by` — what still blocks, as the script lists it: open ids, `decision (<who>)`,
    an unread item quoted — `blocked_ids`, the whole line's local ids, archived ones kept —
    `xrepo_ids`, its `<repo>#TD-NNN` ids — and `pickable`, `yes` or `no`, derived by cadence §2.4's rule (§4.4
    *Repo facts*, TD-228) as ledgerboard's `pickable` derives it (TD-585): blocked while `Blocked by:`
    names an id not in `archive` (open, or in neither file), a decision, or an item it cannot read, or
    while an open entry names it in `Part of:` — `parts_open`, those entries' ids, kept out of `blocked_by`,
    beside `part_of`, its own line's parent or None (cadence §2.4, TD-1130); an id headed twice is blocked
    by what blocks either (ledgerboard keys its reading by id). A
    `<repo>#TD-NNN` item asks `resolve` for `(state, why)`, and anything but `archived` keeps the
    block; with no `resolve` it is unresolved. A written `**Pickable:**` line is not read (TD-228
    slice 4): what blocks an entry is said in `Blocked by:`. `for_page` is the page's kind. A field
    is read only from the entry's own section. A `Kind: live-check` entry also carries `built`, the
    PRs its line names, and `live`, `yes` when `live` says every one of them is live and `no`
    otherwise — no callable, no PR named (§4.9b, TD-323). `sig` is a hash of the entry's section text,
    which the home's settle clock compares (§4.4 *A new entry settles before it is pickable*, TD-710).
    An entry whose `Blocked by:` holds an `until` or `event` gate has `gates` (`gates_of`, TD-1395); whether
    it still waits is the home's clock's, its `waiting` mark (`settle.mark_waits`). An entry whose Log carries a `kept
    waiting` line has `kept_waiting`, the newest such line's date by gate (`kept_waiting_of`, TD-1368). `team`
    is its `**Team:**` line's first word ('' for none), and `needs_team: {why}` marks an entry `team_need`
    finds lacking (§4.4 *An entry names its team*, TD-730).
    **The rank** (§4.4 *The Queue*, TD-769): `rank_text` is the rank file's text beside the ledger
    (`lb.rank_path`; None, no lines) and `repo` the implicit key's last part, so each entry carries its
    `key` — its rank line's, else its implicit key — `lined` (it has a line), its card's `card_key`, and
    `order`, its place in ledgerboard's pick order (the rank: cards by key, then dependency within a
    card); the list itself stays in file order."""
    t = strip_comments(text)
    teams = declared_teams(text)
    heads = list(lb.HEADING_RE.finditer(t))
    derived: dict[str, list[str]] = {}
    parts: dict[str, list[str]] = {}
    held: set[str] = set()
    ranked: dict[str, dict[str, Any]] = {}
    for n, r in enumerate(
        lb.pickable(t, archive or "", resolve, rank_text=rank_text, repo=repo, today=datetime.now(UTC).date())[
            "entries"
        ]
    ):
        got = derived.setdefault(r["id"], [])
        got += [b for b in r["blocked_by"] if b not in got]
        got = parts.setdefault(r["id"], [])
        got += [p for p in r["parts_open"] if p not in got]
        if not r["pickable"]:
            held.add(r["id"])
        ranked.setdefault(r["id"], {"key": r["key"], "card_key": r["card_key"], "order": n, "part_of": r["part_of"]})
    lined = {int(tid[3:]) for tid in lb.rank(rank_text or "")[0]}
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
            "xrepo_ids": xrepo_ids(read["blocked_raw"]),
            "parts_open": list(parts[m.group(1)]),
            "pickable": "no" if m.group(1) in held else "yes",
            **ranked[m.group(1)],
            "lined": int(m.group(1)[3:]) in lined,
            "sig": hashlib.sha256(t[m.start() : nxt.start() if nxt else len(t)].encode()).hexdigest()[:16],
        }
        if gates := gates_of(read["blocked_raw"], t[m.start() : nxt.start() if nxt else len(t)]):
            e["gates"] = gates  # what `settle.mark_waits` reads a wait from (§4.4, TD-1395)
        if e["kind"] == "live-check":
            e["built"] = built(fields.get("kind", ""))
            e["live"] = "yes" if live is not None and e["built"] and all(live(n) for n in e["built"]) else "no"
        e["for_page"] = kind_of(e)
        e["team"] = _word(fields.get("team", ""))
        if why := team_need(e, teams):
            e["needs_team"] = {"why": why}
        # an Inbox row's reading (TD-565) on every open entry, which opens with its Why and Fix
        added = DATE.search(fields.get("added", ""))
        e["added"] = added.group(0) if added else ""
        body = t[m.end() : nxt.start() if nxt else len(t)]
        e["detail"] = detail_of(body)
        if kept := kept_waiting_of(t[m.start() : nxt.start() if nxt else len(t)]):
            e["kept_waiting"] = kept  # the newest `kept waiting` date per gate (§4.4 *The card's status*, TD-1368)
        if e["for_page"] == "for-you":
            e["answers"], e["consequences"], e["default"] = answers_of(fields.get("answers", ""))
            e["ask"] = ask_of(body)  # its one sentence (§4.10 *An item leads with one sentence*, TD-913)
            e["until"] = until_of(read["blocked_raw"])
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


Io = tuple[lb.Ls, lb.Read]  # (ls, read), as `lb.load()` takes them


def fs_io(root: Path | str) -> Io:
    """(ls, read) over the working tree of `root`, paths relative to it: `ls` a directory's file names
    (None for anything that is not a directory), `read` a file's text (None for anything that is not one)."""
    base = Path(root)

    def ls(path: str) -> list[str] | None:
        p = base / path
        return sorted(x.name for x in p.iterdir() if x.is_file()) if p.is_dir() else None

    def read(path: str) -> str | None:
        try:
            return (base / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    return ls, read


def common_parent(rel: str) -> str:
    """The common parent of a ledger path and its v1 archive's — the directory `layout_at` looks in."""
    parent = PurePosixPath(rel).parent.as_posix()
    return "" if parent == "." else parent


def git_io(root: Path | str, ref: str, under: str = "", timeout: float = 10.0, rel: str = "") -> Io | None:
    """(ls, read) over the tree at `ref` in `root`, or None when it cannot be listed: one `git ls-tree` of
    `under` (empty: the top level, and there `ledger/` and `rel` — the ledger asked for, where it is a
    directory — never the tree recursively), and a
    read of a v2 entry file or `README.md` fetches its directory's others with it in one `git cat-file
    --batch` — only those, never the directory's other files; any other path is fetched alone. agent-cadence's
    `files/scripts/ledger.py` `git_io` is the worked example (TD-1144)."""
    if under:
        listed = _git(root, "ls-tree", "-r", "-z", "--full-tree", ref, "--", under, timeout=timeout)
    else:
        top = _git(root, "ls-tree", "-z", "--full-tree", ref, timeout=timeout)
        dirs = dict.fromkeys(d for d in (PurePosixPath(LEDGER_DIR_REL).name, rel) if d and not d.endswith(".md"))
        sub = _git(root, "ls-tree", "-r", "-z", "--full-tree", ref, "--", *dirs, timeout=timeout)
        listed = None if top is None or sub is None else top + sub
    if listed is None:
        return None
    blobs: dict[str, str] = {}
    for rec in listed.split("\0"):
        meta, tab, path = rec.partition("\t")
        if tab and meta.split()[1:2] == ["blob"]:
            blobs[path] = meta.split()[2]
    cache: dict[str, str | None] = {}

    def ls(path: str) -> list[str] | None:
        pre = f"{path.rstrip('/')}/" if path else ""
        if path in blobs or not any(p.startswith(pre) for p in blobs):
            return None
        return sorted(p[len(pre) :] for p in blobs if p.startswith(pre) and "/" not in p[len(pre) :])

    def batched(name: str) -> bool:
        return name == lb.LEDGER_README or bool(lb.ENTRY_FILE_RE.match(name))

    def read(path: str) -> str | None:
        if path not in blobs:
            return None
        if path not in cache:
            d, _, name = path.rpartition("/")
            want = [path]
            if batched(name):
                want += [
                    p
                    for p in blobs
                    if p != path and p.rpartition("/")[0] == d and p not in cache and batched(p.rpartition("/")[2])
                ]
            try:
                cp = subprocess.run(
                    ["git", "-C", str(root), "cat-file", "--batch"], capture_output=True, timeout=timeout,
                    input="".join(blobs[p] + "\n" for p in want).encode(), check=False,
                )  # fmt: skip
                data = cp.stdout if cp.returncode == 0 else b""
            except (OSError, subprocess.TimeoutExpired):
                data = b""
            at = 0
            for p in want:
                nl = data.find(b"\n", at)
                head = data[at:nl].split() if nl >= 0 else []
                if len(head) != 3 or head[1] != b"blob":
                    cache[p] = None
                    break
                size = int(head[2])
                body = data[nl + 1 : nl + 1 + size]
                cache[p] = body.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
                at = nl + 1 + size + 1
        return cache.get(path)

    return ls, read


def layout_at(rel: str, arel: str | None, io: Io) -> tuple[str, str | None]:
    """(ledger, archive) as the tree `io` reads holds them: `rel` and `arel` when `rel` is there, else the
    other layout's beside it — a split came between (dev-cadence TD-160): a v1 file's `ledger/` directory
    (its archive inside it, so None), or a directory's v1 file and archive. agent-cadence's
    `files/scripts/ledger.py` `layout_at`, copied; `tests/test_ledger_layout.py` holds the two equal."""
    if io[0](rel) is not None or io[1](rel) is not None:
        return rel, arel
    here = PurePosixPath(rel).parent
    if rel.endswith(".md"):
        return (here / PurePosixPath(LEDGER_DIR_REL).name).as_posix(), None
    led, arch = ((here / PurePosixPath(n).name).as_posix() for n in (LEDGER_REL, ARCHIVE_REL))
    return led, arch


def v2_faults(led: str, io: Io) -> list[str]:
    """Why the v2 ledger at `led` may not be read as its files say (§4.4 *A faulted v2 ledger is reported, not
    read*), or []: `lb.v2_problems()`'s words, and a `README.md` that declares no `Ledgerboard: 2` (a directory
    is v2 by its shape; `format_major` reads a missing line as 1). [] for a v1 file."""
    ls, read = io
    if ls(led) is None:
        return []
    out = lb.v2_problems(led, ls, read)
    if lb.format_major(read(f"{led}/{lb.LEDGER_README}") or "") == 1:
        out.append(f"{led}/{lb.LEDGER_README} declares no `Ledgerboard: 2` — a directory is a v2 ledger")
    return out


def read_pair(rel: str, io: Io) -> tuple[str, str | None, str | None, list[str]]:
    """(ledger path, ledger text, archive text, faults) of the ledger named `rel`, through `layout_at`, so a
    path from before or after a split still reads: a v2 directory through `lb.load()` (its archive "" when it
    has none), a v1 file with the archive beside it (None when there is none). The text is None when neither
    layout is there, and the path then `rel` as asked; it is None too for a faulted v2 directory, whose
    `v2_faults` are the last element (never read, since `load()` would join a file into its neighbour)."""
    ls, read = io
    led, arel = layout_at(rel, archive_path(rel) if rel.endswith(".md") else None, io)
    if ls(led) is not None:
        if faults := v2_faults(led, io):
            return led, None, None, faults
        text, archive = lb.load(led, ls, read)
        return led, text, archive, []
    text = read(led)
    return (led, text, read(arel or archive_path(led)), []) if text is not None else (rel, None, None, [])


def fault_words(rel: str, faults: list[str]) -> str:
    """A faulted v2 ledger's error, as an unreadable file's is said: `<path> is faulted: <each fault>`."""
    return f"{rel} is faulted: {'; '.join(faults)}"


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


@dataclass
class Compare:
    """One read of the ledger against `origin/<default>` (§4.4 *The ledger is read against origin, as the board
    is*, TD-1471): `io` the overlay — each id's files origin's or the checkout's by the rule — `origin` the
    reading's `{source, case, files}`, `ref` the remote-tracking ref where it exists (the history's revision),
    `base` the merge-base, `paths` both layouts' paths, `taken` the paths read from origin (absent there: deleted),
    `present` those of them origin holds, and `error` where the compare's own git failed."""

    io: Io
    origin: dict[str, Any]
    ref: str | None = None
    base: str | None = None
    paths: tuple[str, ...] = ()
    taken: frozenset[str] = frozenset()
    present: frozenset[str] = frozenset()
    error: str | None = None


def _null_io() -> Io:
    return (lambda p: None), (lambda p: None)


def layout_paths(rel: str) -> tuple[str, ...]:
    """Both layouts' paths of the ledger at `rel`, as `layout_at` reads them: a v1 file, its archive and its
    rank file, then the `ledger/` directory beside them (a split on either side reads as that side has it)."""
    if rel.endswith(".md"):
        led, d = rel, layout_at(rel, archive_path(rel), _null_io())[0]
    else:
        led, d = layout_at(rel, None, _null_io())[0], rel
    return led, archive_path(led), lb.rank_path(led), d


def _unit(path: str, d: str, v1: Collection[str]) -> str:
    """The unit `path` is read by (the rule is by id, never by file): an entry's id, open or archived, under the
    v2 directory `d`; `v1` for a one-file ledger and its archive file together; any other file — the README, a
    rank file — its own path."""
    if path.startswith(f"{d}/"):
        sub, _, leaf = path[len(d) + 1 :].rpartition("/")
        if sub in ("", lb.LEDGER_ARCHIVE) and (m := lb.ENTRY_FILE_RE.match(leaf)):
            return f"id:{int(m.group(1))}"
        return path
    return "v1" if path in v1 else path


def _z_pairs(out: str) -> list[tuple[str, str]]:
    """`git diff --name-status -z`'s records: (status letter, path)."""
    parts = out.split("\0")
    return [(parts[i][:1], parts[i + 1]) for i in range(0, len(parts) - 1, 2) if parts[i]]


def _batch(root: Path | str, blobs: Mapping[str, str], timeout: float) -> dict[str, str]:
    """The texts of `blobs` (path → blob sha), in one `git cat-file --batch`; a path it cannot give is left out."""
    want = sorted(blobs)
    try:
        cp = subprocess.run(
            ["git", "-C", str(root), "cat-file", "--batch"], capture_output=True, timeout=timeout,
            input="".join(blobs[p] + "\n" for p in want).encode(), check=False,
        )  # fmt: skip
        data = cp.stdout if cp.returncode == 0 else b""
    except (OSError, subprocess.TimeoutExpired):
        data = b""
    out: dict[str, str] = {}
    at = 0
    for p in want:
        nl = data.find(b"\n", at)
        head = data[at:nl].split() if nl >= 0 else []
        if len(head) != 3 or head[1] != b"blob":
            break
        size = int(head[2])
        text = data[nl + 1 : nl + 1 + size].decode("utf-8", errors="replace")
        out[p] = text.replace("\r\n", "\n").replace("\r", "\n")
        at = nl + 1 + size + 1
    return out


def compare(root: Path | str, rel: str, branch: str | None = None, timeout: float = 10.0) -> Compare:
    """The ledger at `rel` read against `origin/<default>` as last fetched (§4.4 *The ledger is read against
    origin, as the board is*, TD-1471), fetching nothing: origin's changes since the merge-base of `HEAD` and it
    (`theirs`) and the checkout's, committed, staged, unstaged or untracked (`ours`), over both layouts' paths,
    `--no-renames -z`. By id: an id `theirs` holds and `ours` does not, or one origin moved into or out of
    `archive/`, is read as origin has it (absent where origin deleted it); a one-file ledger and its archive are
    one unit; every other file is the checkout's. `origin` is `{source, case, files}`. `branch` is the default
    branch's name (`workorders.default_branch`), found here when None. Never raises: a git that fails is
    `error`, and no `origin/<default>` reads the checkout (`case` *skipped*)."""
    fs = fs_io(root)
    paths = layout_paths(rel)

    def plain(case: str, ref: str | None = None) -> Compare:
        return Compare(fs, {"source": "checkout", "case": case, "files": 0}, ref=ref, paths=paths)

    if branch is None:
        got = default_ref(root, timeout=timeout)
        branch = got.removeprefix("origin/") if got else None
    ref = f"refs/remotes/origin/{branch}"
    if not branch or not (_git(root, "rev-parse", "--verify", "-q", ref, timeout=timeout) or "").strip():
        return plain("skipped")
    held = _git(root, "ls-tree", "--name-only", "-z", ref, "--", *paths, timeout=timeout)
    if held is None:
        return Compare(fs, {}, error=f"git could not list origin/{branch}")
    if not held.strip("\0"):
        return plain("none", ref)
    base = (_git(root, "merge-base", "HEAD", ref, timeout=timeout) or "").strip()
    if not base:
        return plain("both", ref)
    theirs_out = _git(root, "diff", "--name-status", "--no-renames", "-z", base, ref, "--", *paths, timeout=timeout)
    ours_out = _git(root, "diff", "--name-only", "--no-renames", "-z", base, "--", *paths, timeout=timeout)
    new_out = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *paths, timeout=timeout)
    if theirs_out is None or ours_out is None or new_out is None:
        return Compare(fs, {}, error=f"git could not compare the ledger with origin/{branch}")
    theirs = _z_pairs(theirs_out)
    d, v1 = paths[3], set(paths[:2])
    t_units: dict[str, set[str]] = {}
    for _, p in theirs:
        t_units.setdefault(_unit(p, d, v1), set()).add(p)
    o_units: dict[str, set[str]] = {}
    for p in (ours_out + new_out).split("\0"):
        if p:
            o_units.setdefault(_unit(p, d, v1), set()).add(p)
    archive_dir = f"{d}/{lb.LEDGER_ARCHIVE}"

    def moved(unit: str) -> bool:
        """Origin moved the id into or out of `archive/`: a delete in one place and an add in the other."""
        where = {(s, p.rpartition("/")[0] == archive_dir) for s, p in theirs if p in t_units[unit]}
        return unit.startswith("id:") and any(("D", a) in where and ("A", not a) in where for a in (True, False))

    taken: set[str] = set()
    for u in (u for u in t_units if u not in o_units or moved(u)):
        for p in t_units[u] | o_units.get(u, set()):
            taken.add(p)
            if u.startswith("id:"):  # one id is one file: its other placement is origin's too (absent there)
                taken |= {f"{d}/{p.rpartition('/')[2]}", f"{archive_dir}/{p.rpartition('/')[2]}"}
        if u == "v1":
            taken |= v1
    case = {(True, True): "both", (True, False): "behind", (False, True): "local"}.get(
        (bool(t_units), bool(o_units)), "matches"
    )
    files = len(taken & {p for _, p in theirs})
    origin = {"source": "origin" if files else "checkout", "case": case, "files": files}
    if not taken:
        return Compare(fs, origin, ref=ref, base=base, paths=paths)
    listed = _git(root, "ls-tree", "-r", "-z", "--full-tree", ref, "--", *sorted(taken), timeout=timeout)
    if listed is None:
        return Compare(fs, {}, error=f"git could not list origin/{branch}")
    blobs: dict[str, str] = {}
    for rec in listed.split("\0"):
        meta, tab, p = rec.partition("\t")
        if tab and meta.split()[1:2] == ["blob"] and p in taken:
            blobs[p] = meta.split()[2]
    texts = _batch(root, blobs, timeout) if blobs else {}
    if len(texts) != len(blobs):  # a blob origin lists and git could not give: an error, never an absent entry
        return Compare(fs, {}, error=f"git could not read the ledger's files on origin/{branch}")
    fs_ls, fs_read = fs

    def read(path: str) -> str | None:
        if path not in taken:
            return fs_read(path)
        return texts.get(path)

    def ls(path: str) -> list[str] | None:
        got = fs_ls(path)
        pre = f"{path.rstrip('/')}/" if path else ""
        names = set(got or [])
        for p in taken:
            if p.startswith(pre) and "/" not in p[len(pre) :]:
                names.discard(p[len(pre) :])
                if p in blobs:
                    names.add(p[len(pre) :])
        if got is None and not any(p.startswith(pre) for p in blobs):
            return None
        return sorted(names)

    return Compare((ls, read), origin, ref=ref, base=base, paths=paths, taken=frozenset(taken),
                   present=frozenset(blobs))  # fmt: skip


def pick_repo[K](repo: str, paths: Mapping[K, str], names: Mapping[K, str] | None = None) -> K | None:
    """The one checkout a `<repo>` names (§4.4 *Repo facts*, ledgerboard's target design §3.2, TD-1371): a `<repo>`
    with a `/` is an origin path (`owner/name`, deeper for a nested group) and matches a checkout's `paths` value —
    its lowercased `origin_path` — exactly, else, where no checkout's path equals it, as the last components of one;
    a bare `<repo>` matches a checkout's directory name in `names`. Case is folded. None for no checkout, or two."""
    want = repo.lower().strip("/")
    if "/" in want:
        hits = [k for k, p in paths.items() if p and p == want]
        if not hits:
            hits = [k for k, p in paths.items() if p and p.endswith("/" + want)]
    else:
        hits = [k for k, n in (names or {}).items() if n.lower() == want]
    return hits[0] if len(hits) == 1 else None


class Registry:
    """Resolves `<repo>#TD-NNN` through the home's registry (§4.4 *Repo facts*: the host's
    `repos()`), as the script's roster does: `<repo>` is a checkout's directory name, or its origin's
    path, exact before suffix (`pick_repo`); that checkout's ledger (`ledger_path`, either layout) and its
    archive are read at `origin/<default>`, or in the working tree where that ref is missing. Each repo is read
    once, and only when asked; a name two checkouts share, a checkout not listed, a ledger that cannot be read or
    is a faulted v2 directory (`v2_faults`), or an id in neither file is `unresolved`, which keeps the
    block. Each answer is ledgerboard's `(state, why)`, `why` empty unless it is unresolved (TD-585)."""

    def __init__(self, roots: list[str]) -> None:
        self.roots = [Path(r) for r in roots]
        self._read: dict[Path, tuple[set[str], set[str]] | None] = {}
        self._why: dict[Path, str] = {}  # why a checkout's ledger reads as None: unreadable, or faulted
        self._origins: dict[Path, str] = {}

    def _origin(self, root: Path) -> str:
        """The checkout's origin path (ledgerboard's `origin_path`, lowercased), "" where it has no readable origin."""
        if root not in self._origins:
            self._origins[root] = lb.origin_path((_git(root, "remote", "get-url", "origin") or "").strip()) or ""
        return self._origins[root]

    def _find(self, repo: str) -> Path | None:
        if "/" in repo:
            return pick_repo(repo, {r: self._origin(r) for r in self.roots})
        return pick_repo(repo, {}, {r: r.name for r in self.roots})

    def _repo(self, root: Path) -> tuple[set[str], set[str]] | None:
        if root not in self._read:
            ref = default_ref(root)
            rel = ledger_path(root)
            io = fs_io(root) if ref is None else git_io(root, ref, common_parent(rel), rel=rel)
            at, led, arch, faults = read_pair(rel, io) if io is not None else (rel, None, None, [])
            if led is None:
                self._why[root] = fault_words(at, faults) if faults else f"{rel} cannot be read"
            self._read[root] = None if led is None else (ids_in(led), ids_in(arch))
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
            return "unresolved", f"{root}'s {self._why[root]}"
        tid = _norm(m.group(2))
        if tid in got[1]:
            return "archived", ""
        if tid in got[0]:
            return "open", ""
        return "unresolved", f"{m.group(2)} is in neither {root.name}'s ledger nor its archive"


def ledger_path(root: Path | str) -> str:
    """The checkout's ledger, relative to it (§4.4 **Either layout**, TD-1144): `.shiftlead.yml`'s `ledger:`
    when it names one (a trailing `/` dropped), else `docs/ledger` where that is a directory, else
    `docs/technical_debt.md`. An unreadable `.shiftlead.yml` names none, as it does for `shiftlead.repoconfig`.
    A set path gone from the tree is read through `layout_at` by every reader, as a carried one is."""
    if (got := ledger_set(root)) is not None:
        return got
    return ledger_default(root)


def ledger_default(root: Path | str) -> str:
    """The unset `ledger:` of the checkout at `root`: `docs/ledger` where that is a directory, else
    `docs/technical_debt.md` (§4.4 *Either layout*) — `shiftlead.repoconfig.load` resolves its default by it."""
    return LEDGER_DIR_REL if (Path(root) / LEDGER_DIR_REL).is_dir() else DEFAULT


def ledger_set(root: Path | str) -> str | None:
    """`.shiftlead.yml`'s `ledger:`, a trailing `/` dropped, or None where it names none."""
    try:
        doc = yaml.safe_load(paths.repo_file(root).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    got = doc.get("ledger") if isinstance(doc, dict) else None
    return got.strip().rstrip("/") if isinstance(got, str) and got.strip().rstrip("/") else None


@dataclass
class Change:
    """One entry's life in the file's history: when its section first appeared, and when it left
    (None while it is still there) — and `pr`, the PR whose squash merge removed it: the closing
    commit's subject's `(#n)` (`SQUASH`), None for a commit with none, a direct push (TD-604) — and `sha`,
    that closing commit, which the promote reading tests for *live* (§4.5 screen 11 *Merged*, TD-904)."""

    id: str
    title: str
    opened: datetime
    closed: datetime | None = None
    pr: int | None = None
    sha: str | None = None


Event = tuple[str | None, datetime | None, int | None, dict[str, str], set[str]]  # sha, at, pr, added, removed


def _commit_line(line: str) -> tuple[str | None, datetime | None, int | None]:
    """A `\\x00C <sha> <iso> <subject>` line's sha, instant and squash PR."""
    parts = line.split(" ", 3)
    try:
        at = datetime.fromisoformat(parts[2].strip())
    except (IndexError, ValueError):
        at = None
    m = SQUASH.search(parts[3]) if len(parts) > 3 else None
    return (parts[1] if len(parts) > 1 else None), at, (int(m.group(1)) if m else None)


def _log_events(out: str, skip: set[str]) -> list[Event]:
    """Each commit of `git log --reverse -p --unified=0`: a heading on a `+` line is in the file after that
    commit, on a `-` line it left."""
    events: list[Event] = []
    for line in out.splitlines():
        if line.startswith("\x00C "):
            events.append((*_commit_line(line), {}, set()))
        elif events and line[:1] in "+-" and (tid := lb.entry_id(line[1:])) and tid not in skip:
            if line[0] == "+":
                events[-1][3][tid] = line[1:].partition(":")[2].strip()
            else:
                events[-1][4].add(tid)
    return events


def _dir_events(out: str, directory: str, titles: dict[str, str]) -> tuple[list[Event], set[str]]:
    """Each commit of a v2 directory's `git log --reverse --name-status`: a `TD-NNN.md` added directly under
    it opens its entry (its title `titles`'), one removed from there closes it; and the shas of the commits
    that add its `README.md` (the split)."""
    events: list[Event] = []
    split: set[str] = set()
    for line in out.splitlines():
        if line.startswith("\x00C "):
            events.append((*_commit_line(line), {}, set()))
            continue
        status, _, path = line.partition("\t")
        if not events or status not in ("A", "D"):
            continue
        d, _, name = path.rpartition("/")
        if status == "A" and path == f"{directory}/{lb.LEDGER_README}" and events[-1][0]:
            split.add(events[-1][0])
        if d == directory and (m := lb.ENTRY_FILE_RE.match(name)):
            tid = f"TD-{m.group(1)}"  # spelled as its heading spells it, as the file is named
            if status == "A":
                events[-1][3][tid] = titles.get(tid, "")
            else:
                events[-1][4].add(tid)
    return events, split


def _replay(events: list[Event]) -> dict[str, Change]:
    """Every entry's life from the commits' events in order. A heading both removed and added in one commit
    (an entry moved in the file, its title edited) stays. An entry closed and later re-added is open again
    from its first opening."""
    life: dict[str, Change] = {}
    present: set[str] = set()
    for sha, at, pr, added, removed in events:
        if at is None:
            continue
        for tid in removed - set(added):
            if tid in present:
                present.discard(tid)
                life[tid].closed, life[tid].pr, life[tid].sha = at, pr, sha
        for tid, title in added.items():
            if tid not in life:
                life[tid] = Change(tid, title, at)
            else:
                life[tid].title = title or life[tid].title
                if tid not in present:
                    life[tid].closed, life[tid].pr, life[tid].sha = None, None, None
            present.add(tid)
    return life


def _parse_log(out: str, skip: set[str]) -> dict[str, Change]:
    """The changes from `git log --reverse -p --unified=0` of a v1 file (`_log_events`, `_replay`)."""
    return _replay(_log_events(out, skip))


def _log(root: Path | str, timeout: float, *args: str) -> str | None:
    try:
        cp = subprocess.run(
            ["git", "log", "--first-parent", "--diff-merges=first-parent", "--reverse", "--no-renames", *args],
            capture_output=True, text=True, errors="replace", timeout=timeout, cwd=str(root),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.stdout if cp.returncode == 0 else None


def history(
    root: Path | str,
    rel: str,
    text: str = "",
    timeout: float = 30.0,
    *,
    io: Io | None = None,
    ref: str | None = None,
) -> dict[str, Change] | None:
    """Every entry's opened / closed instants from the ledger's git history in `root`, or None
    when git could not be asked (not a repo, git missing, a timeout) — *could not look*, never
    *nothing changed*. `text` is the ledger as it stands (`load()`'s, for a directory), so the ids of
    headings that sit only in a comment (the entry template's) are left out. A file rewritten without a
    history reads as opened at its first commit, which is all its history says. A v2 directory's
    `--name-status` log is merged with its v1 file's patches (never its archive's), *Across a split* (§4.4
    *Its history*): the commit adding the directory's `README.md` opens and closes nothing, so an entry keeps
    its v1 opening and one closed before the split stays closed. `ref` is the revision the log walks —
    `origin/<default>` where the ref exists (§4.4 *The ledger is read against origin*, TD-1471), else `HEAD` — and
    `io` the reading's (the compare's overlay), which gives the layout and the archive's titles."""
    io = io or fs_io(root)
    rev = ref or "HEAD"
    skip = {m.group(1) for m in lb.HEADING_RE.finditer(text)} - {
        m.group(1) for m in lb.HEADING_RE.finditer(strip_comments(text))
    }
    fmt = "--format=%x00C %H %cI %s"
    if io[0](rel) is None:
        out = _log(root, timeout, fmt, "-p", "--unified=0", rev, "--", rel)
        return None if out is None else _parse_log(out, skip)
    # the v1 file beside the directory, by agent-cadence's names (`layout_at`): a custom-named v1 file is not read
    v1 = layout_at(rel, None, _null_io())[0]
    one = _log(root, timeout, fmt, "-p", "--unified=0", rev, "--", v1)
    two = _log(root, timeout, fmt, "--name-status", rev, "--", rel)
    order = _log(root, timeout, "--format=%H", rev, "--", v1, rel)
    if one is None or two is None or order is None:
        return None
    archive = lb.load(rel, *io)[1]
    titles = {m.group(1): m.group(3).strip() for m in lb.HEADING_RE.finditer(f"{text}\n{archive}")}
    events, split = _dir_events(two, rel, titles)
    at = {sha: i for i, sha in enumerate(order.split())}
    old = _log_events(one, skip)
    split &= {e[0] for e in old if e[4]}  # a split moves v1 headings out; a ledger born v2 opens its files
    merged = sorted(old + events, key=lambda e: at.get(e[0] or "", -1))
    return _replay([e for e in merged if e[0] not in split])


def stamp(root: Path | str, branch: str | None = None) -> tuple[str, float, str | None] | None:
    """What the tick's change test compares (§4.4 *What changes with no one file*): the resolved ledger
    path, its newest mtime — a v1 file's own; a directory's newest among itself, its `archive/`, the
    `TD-NNN.md` files of both and its `README.md`, its `rank.yml` alone left out, so a rank write re-reads
    nothing — and `origin/<default>`'s sha (§4.4 *The ledger is read against origin*, TD-1471), so a fetch that
    moves origin re-reads the ledger; `branch` is the default branch's name, found here when None. A ledger only
    origin holds stamps an mtime of 0; None only when neither side has one. A path that resolves anew always
    differs."""
    io = fs_io(root)
    rel = layout_at(ledger_path(root), None, io)[0]
    if branch is None:
        got = default_ref(root)
        branch = got.removeprefix("origin/") if got else None
    sha = (_git(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}") or "").strip() if branch else ""
    base = Path(root) / rel
    try:
        if not base.is_dir():
            return rel, base.stat().st_mtime, sha or None
        times = [base.stat().st_mtime]
        for d in (base, base / lb.LEDGER_ARCHIVE):
            if not d.is_dir():
                continue
            times.append(d.stat().st_mtime)
            for f in d.iterdir():
                if f.name == lb.LEDGER_README and d == base or lb.ENTRY_FILE_RE.match(f.name):
                    times.append(f.stat().st_mtime)
        return rel, max(times), sha or None
    except OSError:
        return (rel, 0, sha) if sha else None


def _origin_times(root: Path | str, cmp: Compare, timeout: float = 10.0) -> dict[str, float]:
    """The committer time of origin's last commit touching each ledger file since the merge-base, from one walk
    (`git log --first-parent base..origin/<default>`, newest first, `_log`'s merge flags but never `--reverse`):
    the first time a file appears is its last commit."""
    if not (cmp.taken and cmp.base and cmp.ref):
        return {}
    try:
        cp = subprocess.run(
            ["git", "log", "--first-parent", "--diff-merges=first-parent", "--no-renames", "--format=%x00%ct",
             "--name-only", f"{cmp.base}..{cmp.ref}", "--", *cmp.paths],
            capture_output=True, text=True, errors="replace", timeout=timeout, cwd=str(root),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out: dict[str, float] = {}
    for rec in cp.stdout.split("\0") if cp.returncode == 0 else ():
        head, _, names = rec.partition("\n")
        try:
            at = float(head.strip())
        except ValueError:
            continue
        for name in names.splitlines():
            if name.strip():
                out.setdefault(name.strip(), at)
    return out


def written(root: Path | str, rel: str, got: list[dict[str, Any]], cmp: Compare | None = None) -> None:
    """Each entry's `written` (§4.4 *Repo facts*, TD-1331): its own `TD-NNN.md`'s in a v2 ledger, the one
    file's in a v1 ledger, as epoch seconds — for a file read from origin (`cmp`, TD-1471), the committer time of
    origin's last commit touching it since the merge-base; the checkout's mtime otherwise, and for a file read
    from origin that no commit since the merge-base touches (it has the checkout's text); None where the file
    cannot be stat'd. What the Queue reads to tell a held entry's file written after the person's answer (*The
    card's status*, TD-1316)."""
    times = _origin_times(root, cmp) if cmp is not None else {}
    is_dir = (cmp.io if cmp is not None else fs_io(root))[0](rel) is not None

    def when(path: str) -> float | None:
        if cmp is not None and path in cmp.present and path in times:
            return times[path]
        try:
            return (Path(root) / path).stat().st_mtime
        except OSError:
            return None

    one = None if is_dir else when(rel)
    for e in got:
        e["written"] = when(f"{rel}/{_norm(e['id'])}.md") if is_dir else one


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
        io = git_io(root, sha, common_parent(rel), timeout=timeout, rel=rel)
        led, text, archive, faults = read_pair(rel, io) if io is not None else (rel, None, None, [])
        if faults:
            return None, f"{fault_words(led, faults)} at {ref} {sha[:8]}"
        if text is None:
            return None, f"no {rel} at {ref} {sha[:8]}"
        return entries(text, archive, resolve, live), f"{ref} at {sha[:8]}"
    return None, "no origin/<default> here"


def _count(stamps: list[datetime], now: datetime) -> dict[str, int]:
    return {w: sum(1 for t in stamps if t > now - span) for w, span in WINDOWS.items()}


def repo_key(root: Path | str) -> str:
    """A repo's name as an implicit key's last part (§4.4 *The rank*): the checkout's directory name,
    lower-cased into ledgerboard's key alphabet."""
    return Path(root).name.lower()


# an archived entry's `**Resolved:**` line, wherever its body writes it — most write it last, under the
# header block, where ledgerboard's `fields` do not reach
ENTRY_HEAD = re.compile(r"^## (TD-\d+):", re.M)
RESOLVED_LINE = re.compile(r"^\*\*Resolved:\*\*[ \t]*(.+)$", re.M)


def archived_entries(archive: str | None) -> list[dict[str, Any]]:
    """ledgerboard's `entries()` of an archive's text, each entry's `fields` carrying its `resolved` line
    wherever the body writes it (§4.4 *Completed cards*)."""
    if not archive:
        return []
    text = strip_comments(archive)
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
    return ents


def archived(io: Io, rel: str) -> list[dict[str, Any]]:
    """The archive's entries of the ledger at `rel` as `io` reads it (`archived_entries`): a v1 archive file, or
    a v2 ledger's `archive/` — through the compare's overlay, the archive the Queue reads (§4.4 *The ledger is
    read against origin*, TD-1471), so one id never reads open and archived at once. None to read, none."""
    return archived_entries(read_pair(rel, io)[2])


def read(
    root: Path | str,
    now: datetime,
    *,
    with_history: bool = True,
    rel: str | None = None,
    resolve: Resolve | None = None,
    live: Live | None = None,
    branch: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """The ledger reading (`reading`) and the archive's entries it was read with (`archived_entries`), both
    through one compare against origin (`compare`, TD-1471); the archive None where the reading is an error."""
    want = rel or ledger_path(root)
    cmp = compare(root, want, branch)
    if cmp.error:
        return {"path": want, "error": cmp.error, "at": now.isoformat()}, None
    io = cmp.io
    rel, text, archive, faults = read_pair(want, io)
    if faults:  # no entry of it is read: the reading's ledger is an error with the words
        return {"path": rel, "error": fault_words(rel, faults), "at": now.isoformat()}, None
    if text is None:
        why = "cannot be read" if (Path(root) / rel).exists() else "No such file or directory"
        return {"path": rel, "error": f"{rel}: {why}", "at": now.isoformat()}, None
    rank_text = io[1](lb.rank_path(rel))  # none: every entry's key is its implicit one
    got = entries(text, archive, resolve, live, rank_text=rank_text, repo=repo_key(root))
    done_parts = parts_of_open(archive, got)
    for e in got:
        e["parts_archived"] = list(done_parts.get(_norm(e["id"]), []))
    written(root, rel, got, cmp)
    out: dict[str, Any] = {
        "path": rel,
        "entries": got,
        "by_priority": {p: sum(1 for e in got if e["priority"] == p) for p in PRIORITIES},
        "by_kind": {k: sum(1 for e in got if e["for_page"] == k) for k in KINDS},
        "archived": sorted(
            ids_in(archive) & {b for e in got for b in e["blocked_ids"]} | {a for e in got for a in e["parts_archived"]}
        ),
        "declared_teams": list(declared_teams(text)),
        "needs_team": [e["id"] for e in got if e.get("needs_team")],
        "origin": cmp.origin,
        "at": now.isoformat(),
    }
    gone = archived_entries(archive)
    if not with_history:
        return out, gone
    # origin's log where origin holds the ledger; the checkout's where it has none to compare (`none`, `skipped`)
    life = history(root, rel, text, io=io, ref=cmp.ref if cmp.origin.get("case") != "none" else None)
    if life is None:
        out["history_error"] = "git could not read the ledger's history"
        return out, gone
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
            "sha": c.sha if c.closed else None,
        }
        for c in recent
    ]
    return out, gone


def reading(
    root: Path | str,
    now: datetime,
    *,
    with_history: bool = True,
    rel: str | None = None,
    resolve: Resolve | None = None,
    live: Live | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """The ledger reading of one checkout (§4.4 *Repo facts*): `{path, entries, by_priority, by_kind, archived,
    origin, windows, recent, at}`, or `{path, error}` when the file cannot be read, or the compare against origin
    failed. Each file is read against `origin/<default>` as last fetched (`compare`, §4.4 *The ledger is read
    against origin, as the board is*, TD-1471), and `origin` says where it came from: `{source, case, files}`.
    The archive beside the ledger
    (`archive_path`; none there, nothing archived) and `resolve` — the home's `Registry` — derive each entry's
    `pickable`; `live` — the home's `LiveReader` — a live check's `live`; the rank file beside the ledger
    (`lb.rank_path`) gives each entry its `key` and `order`. `windows` is `{day|week|month: {opened, closed}}` from
    the history — origin's log where the ref exists — and `recent` the entries opened or closed in the longest
    window, newest first — both absent when the history was not read, and marked `history_error` when git could not
    be asked. `archived` is the archived ids
    some entry's `blocked_ids` names, or whose `Part of:` names an open entry (TD-1130), never the whole archive
    (§4.5 screen 11 *Its builds*, TD-693); each entry carries `parts_archived`, the archived ids naming it in
    `Part of:`.
    `declared_teams` is the `Fields:` line's `Team` vocabulary in its order, and `needs_team` the ids marked so
    (§4.4 *An entry names its team*, TD-730)."""
    return read(root, now, with_history=with_history, rel=rel, resolve=resolve, live=live, branch=branch)[0]


def completed(recent: list[dict[str, Any]] | None, prs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """*What closed, and by which PR* (design §4.4 *Repo facts*, TD-604): the ledger reading's `recent`
    entries that closed, newest first, each `{id, title, closed, pr, sha, author, branch, url}` — `pr` the
    closing commit's squash number (None: a direct push), `sha` that commit (TD-904), and `author`,
    `branch` and `url` the month's PR reading's by that number (empty where it holds none), so a view can
    name the session whose branch it was. The archive is not read."""
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
                "sha": e.get("sha"),
                "author": str((p or {}).get("author") or ""),
                "branch": str((p or {}).get("branch") or ""),
                "url": str((p or {}).get("url") or ""),
            }
        )
    out.sort(key=lambda c: datetime.fromisoformat(str(c["closed"])), reverse=True)  # offsets differ by committer
    return out
