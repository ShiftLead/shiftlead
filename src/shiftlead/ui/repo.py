"""The Repo page (design §4.5 screen 11): the PR rows and their standing, the ledger's lists, the doing
chips, who serves the repo for what, and the grouping of a team's cards. Moved out of
`shiftlead.ui.app` unchanged (TD-196) and re-exported from it, so a route, a template or a test reads
each name from the app as before.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import ledger
from sessionorc import settle as settle_mod
from sessionorc.models import (
    has_control,
    stop_note,
)
from shiftlead import doctor, repoconfig, review, teamrun, teams
from shiftlead import org as orgmod

from . import uiconf
from .cards import DEAD, NO_TEAM, card_order, group_place, prs_waiting, state_counts, unseen_count
from .common import _age, host_name, live_divider, promote_reading
from .inbox import work_note, work_started
from .org import (
    COMPLETED_WORD,
    FACETS,
    WINDOWS,
    _https,
    compact_line,
    completed_in,
    drawn_facets,
    lane_count,
    repo_facet,
    repo_named,
    team_lanes,
    team_repo,
    team_summary,
)
from .spend import team_figure

# -- Add entry (design §4.9 *Add an entry to the ledger*, §4.5a **Add entry…**, TD-219 slice 3) -------

ENTRY_PREFIX = "entry"  # the session and its worktree: `entry-<n>`, the first number free in the repo
ENTRY_TRIES = 200  # how far the first free number is looked for before the press is refused
# §4.5a *Add entry form: Name* (TD-677): a typed name §4.1's slug would change — the name check would
# read the slug while the worktree and its branch took the name raw
ENTRY_SLUG_WHY = (
    "lowercase letters and digits, with single - between them: "
    "the name is the session's, its worktree's and its branch's"
)


def entry_branch_exists(root: str, name: str) -> bool:
    """Whether `root` has the local branch `name` — `git worktree add` would check it out rather than
    start a new one, so **Open a session** takes no such name (§4.5a *Add entry form: Name*, TD-677)."""
    try:
        cp = subprocess.run(
            ["git", "-C", root, "rev-parse", "--verify", "-q", f"refs/heads/{name}"], capture_output=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return cp.returncode == 0


def entry_role(org: orgmod.Org, team: str, type_: str, files: teams.Files | None = None) -> str:
    """The role **Open a session** starts for `type_`: the team's `entries:` word for it, else, for a
    feature, its current flow's design stage (§4.9c item 4), else the techlead; `plain` where no team
    services the repo (§4.9 *Where there is no seat*). `files` reads a machine node's checkout across
    the link (`host_files`, TD-1064), so a feature there opens its flow's design role as here."""
    t = org.teams.get(team) if team else None
    if t is None:
        return "plain"
    here = host_name()
    return teams.entry_role(org, t, type_, t.host or here, here, files=files)


def entry_line(role: str, host: str = "") -> str:
    """The one line under **Open a session** (§4.5a), the page's whole sentence: what the press will start,
    and the host it starts on where that is the team's on another host (TD-1064). No name, which the **Name**
    box beside the button shows, and no *no team* tail, which **Hand to the techlead**'s reason says (TD-1190)."""
    on = f" on {host}" if host else ""
    return f"Starts an interactive {role} session in a new worktree{on}, with your words in its composer, not sent."


# the teams that service a checkout: `shiftlead.teams`' since TD-218 slice 4, where `ao td add` reads it too
entry_teams = teams.entry_teams


def entry_hand(servicing: list[dict[str, str]], records: Mapping[str, dict[str, Any]]) -> dict[str, str]:
    """**Hand to the techlead**'s state on the Add entry form (§4.5a): `{team, to, name, why, line}`.
    `why` is the reason the button is disabled — *no team services this repo*, *this team has no
    techlead seat*, *<seat>: the techlead seat has no checkout on its host* — else empty; `line` is
    §4.10's *When it is read* for an `ask` with no bound in the form's voice (TD-1190): a seat on call —
    no record, or one `exited` or `closed`, `read_when`'s test — *No techlead is running: …*; else the
    record's own sentence (`refill`), a capital first and a full stop at its end."""
    if not servicing:
        return {"team": "", "to": "", "name": "", "why": "no team services this repo", "line": ""}
    first = servicing[0]
    if not first.get("seat"):
        lead = first.get("techlead") or ""
        why = f"{lead}: the techlead seat has no checkout on its host" if lead else "this team has no techlead seat"
        return {"team": first["team"], "to": "", "name": "", "why": why, "line": ""}
    rec = records.get(first["seat"])
    if not rec or rec.get("state") in ("exited", "closed"):
        line = "No techlead is running: one starts on the next tick and reads it first."
    else:
        rw = rec.get("read_when")
        line = str(rw.get("refill") or "") if isinstance(rw, dict) else ""
        line = line[:1].upper() + line[1:] + ("" if not line or line.endswith((".", "!", "?")) else ".")
    return {"team": first["team"], "to": first["seat"], "name": first["name"], "why": "", "line": line}


# -- the Repo page (design §4.5 screen 11, TD-176 slice 5) -------------------------------------------

# the page's seven kinds, each a list with its `#debt-<key>` anchor (§4.5 screen 11, §4.4 *Repo facts*, TD-418)
LEDGER_LISTS = (
    ("pickable", "pickable"),
    ("design", "design"),
    ("for-you", "for you"),
    ("live-check", "live check"),
    ("blocked", "blocked"),
    ("evaluation", "evaluation"),
    ("other", "other"),
)
# each kind's row flag (§4.4 *Repo facts*), the words `ledger.flags` uses: an *other* row fits no page
# kind, and an *evaluation* row is in no lane since the anchor seat retired (§4.9b *No anchor seat*, TD-757)
LEDGER_FLAG = ledger.NO_KIND
LEDGER_FLAGS = {"other": ledger.NO_KIND, "evaluation": ledger.NO_LANE}
LEDGER_FOLD = 4  # a list folds past this many rows, with *+n more*
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
LOCAL_ID = re.compile(r"TD-(\d+)")  # a `blocked_by` item that is a local id, not a decision or `<repo>#` item


def _tid(item: str) -> str:
    """A local id written `TD-NNN`, as the archive's are (`TD-42` and `TD-042` are one entry), or ''."""
    m = LOCAL_ID.fullmatch(item.strip())
    return f"TD-{int(m.group(1)):03d}" if m else ""


def design_builds(
    entries: Collection[Mapping[str, Any]],
    archived: Collection[str],
    held: Mapping[str, str],
    prs: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """**Its builds** (§4.5 screen 11, §4.5a *Repo page: its builds line*, TD-693, read from `Part of:` by
    TD-1130): for each entry that entries name in `Part of:` (its `parts_open` and `parts_archived`), by its
    id, `{builds, done}` — `builds` those ids in id order. Each build is
    `{id, state, pr, url, held, blocked_by, row}`: `state` *archived* (in `archived`, which holds the archived parts),
    else *review* with its holder's claim `pr` and its `url` (`prs`, the motion rows'), else *held* by `held`'s
    names, else *open*; `blocked_by` the entry's other builds its own `blocked_by` still names; `row` the id as
    the ledger writes it when it has a row to link to, else ''. `done` is every build archived. And by each
    build's ledger id, the design it builds (the back-link): its own `Part of:` parent, an open row, from the
    same pass."""
    by_tid = {_tid(str(e.get("id") or "")): e for e in entries}
    held_t = {_tid(k): v for k, v in held.items() if _tid(k)}
    prs_t = {_tid(k): v for k, v in prs.items() if _tid(k) and isinstance(v.get("pr"), int)}
    gone = {_tid(a) for a in archived}
    lines: dict[str, dict[str, Any]] = {}
    back: dict[str, list[str]] = {}
    for e in entries:
        parts = [_tid(str(x)) for x in [*(e.get("parts_open") or []), *(e.get("parts_archived") or [])]]
        ids = sorted({x for x in parts if x}, key=lambda x: int(x[3:]))
        if not ids:
            continue
        mine = {_tid(b) for b in ids}
        builds = []
        for b in ids:
            tid, row = _tid(b), by_tid.get(_tid(b))
            if tid in gone:
                builds.append(
                    {"id": tid, "state": "archived", "pr": None, "url": "", "held": "", "blocked_by": [], "row": ""}
                )
                continue
            if row is not None:
                back.setdefault(str(row["id"]), []).append(str(e["id"]))
            state = "review" if tid in prs_t else "held" if held_t.get(tid) else "open"
            blocked = [x for x in (_tid(str(y)) for y in (row or {}).get("blocked_by") or []) if x in mine and x != tid]
            builds.append(
                {
                    "id": str(row["id"]) if row else tid,
                    "state": state,
                    "pr": (prs_t.get(tid) or {}).get("pr"),
                    "url": (prs_t.get(tid) or {}).get("url") or "",
                    "held": held_t.get(tid, ""),
                    "blocked_by": blocked,
                    "row": str(row["id"]) if row else "",
                }
            )
        lines[str(e["id"])] = {"builds": builds, "done": all(x["state"] == "archived" for x in builds)}
    return lines, back


def missing_seams(r: Mapping[str, Any]) -> dict[str, Any]:
    """**missing seams** (§4.5a *Repo page: missing seams*, TD-591, TD-1011): from the repo facts' `seams`
    and nothing read here, the words `ao doctor`'s **repos** line says — `lines`, one per warning (the
    ledgerboard release warning among them), drawn under the title, and `unserved`, one per lack that
    leaves the repo unserved, drawn in the warning colour in place of Technical debt: each a list of
    `(text, code)` parts, a back-quoted cure drawn as code. Both empty when the repo is served and nothing
    warns, or the seams are not read yet."""
    seams = r.get("seams") if isinstance(r.get("seams"), dict) else None
    return {
        "lines": [_parts(w) for w in doctor.missing_seams(seams, r.get("root") or "<checkout>")],
        "unserved": [_parts(w) for w in doctor.lacks(seams, r.get("root") or "")],
    }


def _parts(words: str) -> list[tuple[str, bool]]:
    """`words` as `(text, code)` parts, each back-quoted span a code part."""
    return [(part, i % 2 == 1) for i, part in enumerate(words.split("`")) if part]


def pr_rows(
    r: Mapping[str, Any],
    members: Collection[dict[str, Any]],
    standing: Mapping[int, dict[str, Any]],
    now: datetime,
    fleet: Collection[dict[str, Any]] = (),
    teams: list[list[dict[str, Any]]] | None = None,
    home: str = "",
) -> list[dict[str, Any]]:
    """**Open PRs** (§4.5 screen 11): every open PR, newest last, with its author — the member whose
    branch it is, else the GitHub login — its age, *draft*, its standing with the techlead
    (`standing`, by number; nothing when no entry names it), and `red` for one that reads red or
    conflicting — its word, how long, and past `ORPHAN_AFTER` whose it is among `fleet`'s records
    (`teamrun.red_prs`, TD-613); `not_run` for one whose CI never started (TD-686), drawn *CI never ran*;
    `unasked` for a held PR nobody asked, in the standing's place (§4.4, TD-790): `teams` the servicing
    teams' members in the Org's order, whose reader the tag names (`review.unasked`); `fork` for a fork's PR,
    its tag's title (TD-1285), and `fork_line` while it is ready to precheck (`teamrun.ready_to_precheck`):
    `{line, diff, title}`, the person's `--fork-ok` line, the PR's diff and *type it in a terminal on
    <home>, where <root> is* (`home` the home's host name, TD-1292)."""
    by_branch = {str((m.get("git") or {}).get("branch") or ""): m for m in members if isinstance(m.get("git"), dict)}
    reds = {x["number"]: {**x, "age": _age(x["red_since"], now)} for x in teamrun.red_prs(r, fleet, now)}
    rows = []
    for p in (r.get("prs") or {}).get("open") or []:
        if not isinstance(p, dict) or not isinstance(p.get("number"), int):
            continue
        who = by_branch.get(str(p.get("branch") or ""))
        st = standing.get(p["number"])
        tag = None if st else review.unasked(dict(r), p["number"], teams or [])
        rows.append(
            {
                "number": p["number"],
                "title": str(p.get("title") or ""),
                "url": str(p.get("url") or ""),
                "author": {"id": who["id"], "name": who.get("name") or who["id"]} if who else None,
                "login": str(p.get("author") or ""),
                "age": _age(p.get("created"), now),
                "draft": bool(p.get("draft")),
                "standing": st,
                "unasked": {
                    "word": f"unasked · {_age(tag['created'], now)}",
                    "title": f"touches held paths ({', '.join(tag['paths'])}): {review.unasked_hint(p['number'], tag)}"
                    " — where your own ao pr held says held",
                }
                if tag
                else None,
                "red": reds.get(p["number"]),
                # CI that never started is the person's, drawn apart from red (§4.4, TD-686)
                "not_run": p.get("not_run") if p.get("checks") == "not_run" else None,
                # a fork's PR is in no lane; its precheck is the person's (§4.5 screen 11 *Review*, TD-1292)
                "fork": {"title": fork_title(p)} if p.get("fork") else None,
                "fork_line": {
                    "line": str(p["precheck_line"]),
                    "diff": f"{str(p.get('url') or '').rstrip('/')}/files",
                    "title": line_title(home, str(r.get("root") or "")),
                }
                if teamrun.ready_to_precheck(p)
                else None,
            }
        )
    return rows


def line_title(home: str, root: str) -> str:
    """The `--fork-ok` line's title (§4.5 screen 11 *Review*, TD-1292): where to type it — the home's host,
    where the checkout is, since every reading is the home's."""
    return f"type it in a terminal on {home or 'the home'}, where {root or 'its checkout'} is"


FORK_TITLE = (
    "a fork's PR: its CI runs in the forge's sandbox, and its precheck runs its code here, "
    "so the precheck is yours alone, after reading the diff"
)


def fork_title(p: Mapping[str, Any]) -> str:
    """The **fork** tag's title (§4.5 screen 11 *Review*, TD-1285): what a fork's PR is, and, with `checks`
    *none*, that no CI ran on its head yet, or, with *red* or `not_run`, that a first-time contributor's run
    may wait for the person's approval on the forge."""
    checks = p.get("checks")
    if checks == "none":
        return f"{FORK_TITLE}; no CI on this head yet"
    if checks in ("red", "not_run"):
        return f"{FORK_TITLE}; a first-time contributor's run may be waiting for your approval on the forge"
    return FORK_TITLE


COMPLETED_FOLD = 8  # Recently completed folds past this many rows, with *+n more* (§4.5 screen 11, TD-604)


def completed_rows(
    r: Mapping[str, Any], fleet: Collection[dict[str, Any]], now: datetime, promotes: Any = None
) -> dict[str, dict[str, Any]]:
    """**Recently completed** (§4.5 screen 11 item 3, TD-604), one list per window of the page's one
    picker: `{rows, fold, word}` by *day*, *week* and *month*, each row the entry's id and title, the
    PR whose squash merge closed it (`pr`, a link: the PR reading's page, else the remote's; None —
    *no PR* — for a close by a commit that names none), who opened that PR — the session among
    `fleet`'s records whose branch is the PR's head (a link to its Focus), else the GitHub login —
    and the close's age. Newest first, as the reading keeps them; nothing on it is a control. `promotes` is
    the `host` reading's: in a repo with a `promote:` block each window carries `divider`, the line between
    what is not yet live and what is (`common.live_divider`, TD-904), its rows not yet live put first."""
    by_branch = {
        str((s.get("git") or {}).get("branch") or ""): s
        for s in fleet
        if isinstance(s.get("git"), dict) and (s.get("git") or {}).get("branch")
    }
    web = _https(str(r.get("remote") or ""))
    p = promote_reading(promotes, r.get("root")) if r.get("root") else None
    out = {}
    for w in WINDOWS:
        rows = []
        for c in completed_in(r, w, now):
            pr, who = c.get("pr"), by_branch.get(str(c.get("branch") or "")) if c.get("branch") else None
            rows.append(
                {
                    "id": str(c.get("id") or ""),
                    "title": str(c.get("title") or ""),
                    "pr": pr,
                    "url": str(c.get("url") or "") or (f"{web}/pull/{pr}" if web and pr is not None else ""),
                    "author": {"id": who["id"], "name": who.get("name") or who["id"]} if who else None,
                    "login": str(c.get("author") or ""),
                    "age": _age(c.get("closed"), now),
                    "sha": c.get("sha"),
                }
            )
        divider = live_divider(p, rows, Path(str(p.get("root") or "")).name, now) if p else {}
        out[w] = {
            "rows": rows,
            "fold": max(0, len(rows) - COMPLETED_FOLD),
            "word": COMPLETED_WORD[w],
            "divider": divider,
        }
    return out


def repo_window(params: Any) -> str:
    """The window whose Recently completed rows the page sends (§4.5 *Page loads*: *only what is shown*,
    TD-882): the URL's `win` (the facet's *closed* link carries one), else *day*; an unknown one reads as *day*."""
    w = str(params.get("win") or "")
    return w if w in WINDOWS else "day"


def send_folds(
    lists: list[dict[str, Any]], completed: dict[str, dict[str, Any]], win: str, opened: Collection[str]
) -> str:
    """What the page sends of its folded lists (§4.5 *Page loads*: *only what is shown*, TD-882): each
    Technical debt list its rows up to the fold (`sent`), each Recently completed window up to `win` its
    rows up to its fold, and a window wider than `win` none (`sent` None: not read); a list `opened` names
    — its key (`pickable`, `completed-week`) or the id of a row in it, for an anchor to a row not yet sent —
    goes whole. `rows` and `fold` stay whole, so every count and *+n more* still reads the whole list.
    Returns the window loaded, for the page to know what a wider pick must read."""
    keys = set(opened)
    for ln in lists:
        whole = ln["key"] in keys or any(e.get("id") in keys for e in ln["rows"])
        ln["sent"] = ln["rows"] if whole else ln["rows"][:LEDGER_FOLD]
    reach = WINDOWS.index(win)
    for w, c in completed.items():
        key = f"completed-{w}"
        c["sent"] = None if WINDOWS.index(w) > reach else c["rows"] if key in keys else c["rows"][:COMPLETED_FOLD]
    return win


def pr_standing(seats: list[tuple[str, list[Any], list[Any]]], now: datetime) -> dict[int, dict[str, Any]]:
    """Each PR's standing with the team's readers (§4.5 screen 11, §4.9c *What is shown*): `seats`
    one `(name, inbox, sent)` per seat of the team, read as a person's read — `review.standing`,
    the words `ao repo` prints too, aged against `now`."""
    return review.standing(seats, lambda at: _age(at, now))


def ledger_lists(
    r: Mapping[str, Any],
    motion: Collection[dict[str, Any]],
    lanes: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """**Technical debt** (§4.5 screen 11): the open entries in seven lists by the page's kind, each
    row id, title, priority and owner, *held by <name>* when a member claims it and *blocked by …*
    from the entry's `blocked_by` (§4.4 *Repo facts*), and a live check *live check* or *waits for
    its build to be live* with its build's PRs (§4.9b, TD-323; the template's), sorted by priority
    then id; `fold` the rows past the fold; an *other* row carries `flag`, this reader's flag on it.
    A design's row carries `builds`, its builds line, and a build's `builds_of`, the designs it builds
    (`design_builds`, TD-693).
    The board's open decided lines, the lanes' work orders
    (§4.5a *Repo page: decided lines*, TD-384), come first in *pickable*, each with its `decided`
    and, held by nobody, `pickable_by`: the teams whose lanes (`teamrun.repo_lanes`') take it, None
    where the ledger was not read and the lanes could not be (`lanes` None or the entries unread).
    An entry the home's settle clock withholds carries `settle`, *settles in 7m*, drawn with no press
    (§4.5a *Repo page: settles in 7m on an entry*, TD-710); one whose wait stands carries `wait`, *waits
    until 10-16* or *waits: <words>*, and `wait_line`, its `Waits:` line whole (TD-716); `held` is the
    claim's, as ever."""
    now = now or datetime.now(UTC)
    held = {x["ref"]: ", ".join(w["name"] for w in x["members"]) for x in motion}
    entries = [e for e in ((r.get("ledger") or {}).get("entries") or []) if isinstance(e, dict)]
    builds, builds_of = design_builds(
        entries,
        (r.get("ledger") or {}).get("archived") or [],
        held,
        {x["ref"]: {"pr": x.get("pr"), "url": x.get("pr_url")} for x in motion},
    )
    known = lanes is not None and teamrun.lane_entries(r) is not None
    orders = [
        {
            **e,
            "held": held.get(e["id"], ""),
            "pickable_by": [t for t, got in (lanes or {}).items() if e["id"] in (got.get("pickable") or ())]
            if known
            else None,
        }
        for e in teamrun.work_orders(r)
    ]
    out = []
    for key, label in LEDGER_LISTS:
        rows = sorted(
            (
                {
                    **e,
                    "held": held.get(e["id"], ""),
                    "settle": settle_mod.words(e, now),
                    # what it waits for (§4.5a *Repo page: waits mark*, TD-716): the line whole on hover
                    "wait": teamrun.wait_words(e, short=True),
                    "wait_line": teamrun.wait_line(e),
                    **({"flag": LEDGER_FLAGS[key]} if key in LEDGER_FLAGS else {}),
                    "builds": builds.get(e["id"]),
                    "builds_of": builds_of.get(e["id"], []),
                }
                for e in entries
                if e.get("for_page") == key
            ),
            key=lambda e: (PRIORITY_RANK.get(e.get("priority") or "", 9), e["id"]),
        )
        if key == "pickable":
            rows = orders + rows  # the person has answered: nothing in a ledger outranks it
        out.append({"key": key, "label": label, "rows": rows, "fold": max(0, len(rows) - LEDGER_FOLD)})
    return out


def debt_cards(queue: Mapping[str, Any] | None, name: str, lists: list[dict[str, Any]]) -> dict[str, Any] | None:
    """**Technical debt cards** (§4.5 screen 11 item 2, §4.5a *Repo page: Technical debt cards*, TD-770):
    the Queue's cards one of whose open members is this repo's, whole and in the reading's order (In
    progress first, then Up next by key), for the Queue's partials — or None where the home serves no
    cards (a node, a home before its first tick, an older home), and the page draws the kind lists.

    Each row (the card's `top` and its `rows`) gains `show`, its id as this page writes it, `afters`, its
    `after` so written (TD-1130), `anchor`, the id a `#TD-n` link finds (this repo's rows alone), and `ext`,
    what the ledger row carried beyond the Queue's (`ledger_lists`' row for the entry, its kind's `label`
    as `kind_label`): the owner, *needs a team*, the settle mark, the builds line,
    the live check's words. An open entry of the repo no card holds yet (filed since the home's last
    reading) is drawn as a card of its own after them, with no moves. `upnext` is the whole Up next
    order, every repo's — a move's neighbours are the adjacent cards in it (§4.4 *A move lands*) —
    each card's id; `ids` on a card are its open members, which `rank_move` takes."""
    cards = [c for c in (queue or {}).get("cards") or [] if isinstance(c, Mapping) and c.get("top")]
    if not cards:
        return None
    ext: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for e in lst["rows"]:
            if not e.get("work_order"):
                ext[str(e["id"])] = {**e, "kind_label": lst["label"]}

    def _shown(q: str, name: str) -> str:  # `TD-n` for this repo's own, `<repo>#TD-n` for another's
        repo, _, tid = q.rpartition("#")
        return tid if repo == name else q

    def row(r: Mapping[str, Any]) -> dict[str, Any]:
        own = r.get("repo") == name
        return {
            **r,
            "priority": str(r.get("priority") or "").lower(),
            "show": _shown(str(r.get("qid") or ""), name),
            "afters": [_shown(str(a), name) for a in r.get("after") or []],
            "anchor": str(r.get("id") or "") if own and not r.get("archived") else "",
            "ext": ext.get(str(r.get("id"))) if own and not r.get("archived") else None,
        }

    out: list[dict[str, Any]] = []
    drawn: set[str] = set()
    for c in cards:
        if name not in (c.get("repos") or ()):
            continue
        top, rows = row(c["top"]), [row(r) for r in c.get("rows") or []]
        drawn.update(r["anchor"] for r in (top, *rows) if r["anchor"])
        out.append({**c, "top": top, "rows": rows, "ids": list(c.get("order") or [c["id"]])})
    # filed since the reading: a card of its own, unranked, so no entry of the ledger goes undrawn
    for i, e in ext.items():
        if i in drawn:
            continue
        q = f"{name}#{i}"
        top = row({"qid": q, "repo": name, "id": i, "title": e.get("title") or "", "priority": e.get("priority"),
                   "state": "", "holder": None, "archived": False, "after": []})  # fmt: skip
        out.append({"id": q, "top": top, "rows": [], "ids": [q], "group": "", "place": None, "status": "", "new": True})
    upnext = [str(c["id"]) for c in cards if c.get("group") == "up_next"]
    return {"cards": out, "upnext": upnext}


def team_notes(r: Mapping[str, Any], defs: Collection[str], fleet: list[dict[str, Any]]) -> dict[str, Any]:
    """The lines under the Technical debt heading's lanes lines (§4.5 screen 11, §4.4 *An entry names its
    team*, TD-764): `needs`, the repo's *needs a team* line as `ao repo` prints it — `{ids, to}`, `to`
    *handed to <seat>* or why nobody is (`teamrun.tagging_seat`) — or None where no entry needs one; and
    `stale`, each `{text, ids}`, *the ledger declares db, which no definition holds* with the entries that
    carry it, or *the ledger leaves out ops, which this repo defines* (`teams.stale_teams`, over `defs`,
    the names of the definitions this page reads). A ledger not read says nothing."""
    led = r.get("ledger") or {}
    if not isinstance(led, dict) or "error" in led or "declared_teams" not in led:
        return {"needs": None, "stale": []}
    declared = [str(t) for t in led.get("declared_teams") or []]
    entries = [e for e in led.get("entries") or [] if isinstance(e, dict)]
    need = [str(e["id"]) for e in entries if e.get("needs_team")]
    needs = None
    if need:
        seat, why = teamrun.tagging_seat(fleet, Path(str(r.get("root") or "")).resolve(), declared)
        needs = {"ids": need, "to": f"handed to {seat}" if seat else why}
    stale = [
        {"text": f"the ledger declares {s['team']}, which no definition holds", "ids": s["ids"]}
        if s["kind"] == "declared"
        else {"text": f"the ledger leaves out {s['team']}, which this repo defines", "ids": []}
        for s in teams.stale_teams(declared, defs, entries)
    ]
    return {"needs": needs, "stale": stale}


def doing_chips(rows: Collection[dict[str, Any]], teams: Collection[str] = ()) -> list[dict[str, Any]]:
    """The Doing section's filter chips (§4.5a *Repo page: doing filters*): where two or more teams
    service the repo a chip per team first, in `teams`' order (`team`, *db (12)*), then *all (n)* and
    one per doer in the feed, the busiest first (`who`). A team pick and a doer pick AND."""
    tally: dict[str, int] = {}
    for d in rows:
        tally[d["name"]] = tally.get(d["name"], 0) + 1
    per_team = (
        [{"team": t, "label": t, "n": sum(1 for d in rows if d.get("team") == t)} for t in teams]
        if len(teams) > 1
        else []
    )
    return (
        per_team
        + [{"who": "", "label": "all", "n": len(rows)}]
        + [{"who": w, "label": w, "n": n} for w, n in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]
    )


def repo_items(layout: list[dict[str, Any]] | None, name: str) -> list[dict[str, Any]]:
    """The Repo page's top (§4.5 screen 11 *The page is the repo's group of the Org, expanded*,
    TD-740): the Org's layout items of the repo `name` — its line with the Repo facet, every
    servicing team's whole card in the Org's order, then its no-team strip — never a copy of them.
    The client keeps them from the Org's deltas by the same test (`AO.repoItems`)."""
    return [
        g
        for g in layout or []
        if (g.get("kind") == "repo" and g.get("repo") == name)
        or (g.get("kind") in ("team", "strip") and g.get("repo") == name)
    ]


def repo_doing(items: Collection[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The Repo page's **Doing** (§4.5 screen 11 item 5): every servicing team's kept calls, each
    row carrying its `team`, newest first, and the doer column's width across them."""
    rows = [
        {**d, "team": g["team"]}
        for g in items
        if g.get("kind") == "team" and g.get("summary")
        for d in g["summary"].get("doing") or []
    ]
    rows.sort(key=lambda d: d.get("at") or "", reverse=True)  # ISO instants: the text sorts as the time
    width = max((int(g["summary"].get("doer_w") or 1) for g in items if g.get("summary")), default=1)
    return rows, width


def compact_in(
    v: dict[str, Any], fleet: Collection[dict[str, Any]], repos: Mapping[str, Any] | None = None, repo: str = ""
) -> dict[str, Any]:
    """Mark `v` compact when it is a member of a team (§4.5a *card: compact*): a `team` badge, live
    or not — a team with nothing live draws its summary and compact cards too, once unfolded
    (TD-192). The full card stays in its repo's no-team strip or *No repo*. With `repos`, the home's
    repo facts, it carries **the lane's count** (TD-428) as `team_groups` gives it, read from the same
    lanes reading over `fleet` — of `repo`, the team's definition's (TD-725), else the repo its
    members sit in."""
    if v.get("team"):
        v["compact"], v["compact_line"] = True, compact_line(v, repos)
        if repos is not None and v.get("lane"):
            fleet = list(fleet)
            r = repo_named(repo, repos) if repo else None
            r = r or team_repo([s for s in fleet if s.get("team") == v["team"]], repos)
            v["lane_count"] = lane_count(v, team_lanes(str(v["team"]), fleet, r))
    return v


def who_for_what(roles: Collection[Mapping[str, Any]], views: Collection[Mapping[str, Any]]) -> list[str]:
    """The team's **who for what** lines, drawn in its help panel (design §4.5a ***i*** mark, §4.8 *A role says when to
    message it*; TD-162, built by TD-171): one phrase per role the definition names, in its order,
    from the role's `message:` line — the definition's words, never a session's. A role one session
    holds reads *<line> → <name>*, and an empty seat *(on call)* after the name; a role several
    hold reads *<Label>: <line>*, since no one name answers for them. A role with no line is left
    out, and a team whose roles carry none has no line at all (an empty list). The line comes from
    a view of a session holding the role, which resolved it with the repo's and the org's layers;
    where no session holds it yet, from the built-in preset."""
    by_name = {str(v.get("name") or ""): v for v in views}
    out: list[str] = []
    for r in roles:
        role, names = str(r.get("role") or ""), [str(n) for n in r.get("names") or ()]
        held = [by_name[n] for n in names if n in by_name]
        line = next((str(v.get("message_line") or "") for v in held if v.get("message_line")), "")
        line = line or str((repoconfig.PRESETS.get(role) or {}).get("message") or "")
        if not line:
            continue
        if len(names) == 1:
            v = by_name.get(names[0])
            empty = bool(r.get("seat")) and (v is None or v.get("seat") or v.get("state") in ("exited", "closed"))
            out.append(f"{line} → {names[0]}{' (on call)' if empty else ''}")
        else:
            label = next(
                (str(v.get("role_label")) for v in held if v.get("role_label")), repoconfig.default_label(role)
            )
            out.append(f"{label}: {line}")
    return out


def flow_head(fv: Mapping[str, Any] | None, *, live: bool) -> dict[str, Any]:
    """A team header's flow (design §4.5a *team groups*, *team card **flow changed — Apply***; §4.9c):
    `flow`, the current one or "" for a team that lists none; `flow_strip`, its stages and the
    person; `flow_lines`, what is drawn under the header: a pick that is not one it lists, each listed
    flow it cannot follow — the current one first, with the flows it could — and a repo not read
    from here; and `flow_changed`, a live team's members whose records differ from what the flow compiles
    to, each `{name, act, line}`, with `definition_changed` when the mark reads **definition changed —
    Apply** (§4.5a, TD-399): the team runs no flow, or every difference is a seat it lacks. A team with
    nothing live keeps only its renames and removals (§4.9 *A member renamed or removed*, TD-703)."""
    every = list((fv or {}).get("differences") or [])
    diffs = every if live else [d for d in every if d.get("act") in teamrun.MOVED]
    if not fv or not fv.get("flow"):
        # a team that runs no flow is read on its seats alone (§4.9c, TD-399): one it lacks is the mark
        return {
            "flow": "",
            "flow_strip": "",
            "flow_lines": [],
            "flow_changed": diffs,
            "definition_changed": bool(diffs),
        }
    rows = list(fv.get("flows") or [])
    now = next((r for r in rows if r.get("current")), {})
    lines = [str(fv["flow_note"])] if fv.get("flow_note") else []
    could = [r["name"] for r in rows if not r.get("current") and not r.get("cannot") and not r.get("unread")]
    if now.get("cannot"):  # the flow it runs first, with the flows it could follow
        lines.append(str(now["cannot"]) + (f" (it could follow {', '.join(could)})" if could else ""))
    lines += [str(r["cannot"]) for r in rows if r.get("cannot") and not r.get("current")]
    if unread := next((r["unread"] for r in rows if r.get("unread")), ""):
        lines.append(f"flows not read from here: {unread}")
    return {
        "flow": str(fv["flow"]),
        "flow_strip": str(now.get("strip") or ""),
        "flow_lines": lines,
        "flow_changed": diffs,
        "definition_changed": teamrun.definition_changed(diffs, fv["flow"]),
    }


def _stopped(mark: Any) -> bool:
    """Whether a `work_waiting` mark is a stopped team's (§6 rule 8 *A team that stopped*, TD-781)."""
    return isinstance(mark, Mapping) and isinstance(got := mark.get("stopped"), Mapping) and bool(got)


def team_groups(
    views: list[dict[str, Any]],
    rows: Collection[dict[str, Any]] = (),
    repos: Mapping[str, Any] | None = None,
    doing: Mapping[str, Any] | None = None,
    work: Mapping[str, Any] | None = None,
    flows: Mapping[str, Any] | None = None,
    balance: Mapping[str, Any] | None = None,
    needs: Collection[dict[str, Any]] = (),
    spend: Mapping[str, Any] | None = None,
    repo_page: bool = False,
) -> list[dict[str, Any]] | None:
    """Design §4.5a Sessions **team groups** (§4.9, §9 invariant 9): the grid grouped by the `team` badge,
    derived from the views on every render and every delta, never stored. `rows` is the definitions
    (`teamrun.rows`). `None` when no session carries a badge and nothing is defined — the page then
    renders the flat grid, with no header anywhere. A team with nothing live keeps its group
    (2026-09-18): dead cards under a team's name are still that team's, and a definition no session
    carries is a group with no members, because its card is where Start lives.

    The badge decides the group; `controllers` decides the manager: the one member holding
    `control` that other members of the same group list as a controller. A group without one
    has no manager card and its header says so. Within a group the manager comes first, then the rest in
    urgent-first order (the same `rank`, `name` key the flat grid sorts by); the client re-sorts
    per group in Pinned mode. In this list: the teams with something live, the sessions with no
    badge (*No repo*'s label: `org_layout` splits them by repo for the Sessions page, TD-725), then the
    teams with nothing live. Each team group carries its `repo` (the definition's) and its `order`
    (the definition's place), which `org_layout` orders a repo's teams by.

    A manager carrying a different badge from its members — which `ao team start` never produces, but a
    hand-typed `ao new --team` can — is still found, by looking across the whole fleet rather than
    only inside the group (review of PR #117). Its card stays where its own badge puts it; the
    header names it and says so, because moving the card would contradict the badge.

    A team carries its **summary** (TD-176 slice 3, §4.5a *team card: summary*) from `repos` (the
    home's repo facts) and `doing` (its doing log), live or not — a team with nothing live shows what
    it left once unfolded (TD-192) — and its members are marked compact; its header then drops the
    state counts, which the member cards say, but for the fold.

    `work` is the home's `work_waiting` marks by team (`host`'s `work`, §6 rule 8): a wound-down
    team's header says *n entries waiting since <t>* from its mark, and a live one *started <t> for
    …* from its records' `restarts` (§4.5a team card **work waiting** note).

    `flows` is each team's `teamrun.flow_view`, read when the page was drawn and not per delta
    (§4.9c *What is shown*): the header's flow and strip, the lines under it while the definition
    cannot follow its flow, and, on a live team, *flow changed — Apply* (`flow_head`).

    `balance` is the home's balance marks by team (`host`'s `balance`, §6 *Balance*, TD-330): every
    mark, one with no `repo` too, which no checkout's reading in `repos` carries.

    `spend` is today's `seats` row by team (`Readings.team_spend`): the header's **spend** figure (§4.5a
    *team card: spend*, TD-832), absent while the team spent nothing today.

    `repo_page`: the Repo page's cards draw no Repo facet, its line drawing it always; on the Sessions page
    every card that draws a summary draws it first (§4.5a *team card: Repo facet*, TD-1189)."""
    defs = {str(r["name"]): r for r in rows}
    order = {name: i for i, name in enumerate(defs)}  # definition order, within a repo (§4.9 *The Sessions page*)
    by_team: dict[str, list[dict[str, Any]]] = {name: [] for name in defs}
    for v in views:
        by_team.setdefault(str(v.get("team") or NO_TEAM), []).append(v)
    if not any(t != NO_TEAM for t in by_team):
        return None
    groups: list[dict[str, Any]] = []
    marks = teamrun.balance_marks(
        {str(k): v for k, v in (repos or {}).items() if isinstance(v, dict)}, {"balance": balance or {}}
    )
    for team in sorted(by_team):
        members = sorted(by_team[team], key=card_order)
        manager, manager_elsewhere = None, False
        if team != NO_TEAM:
            named = {c for m in members for c in (m.get("controllers") or [])}
            # The fleet, not just this group: a manager whose own badge differs is still this group's
            # manager, and saying "managed by you" over a group that plainly has one would be a lie.
            managers = sorted(
                (v for v in views if has_control(v.get("capabilities")) and v["id"] in named),
                key=lambda v: (str(v.get("team") or "") != team, v["rank"], v["name"]),  # our own badge first
            )
            if managers:
                manager = managers[0]
                if manager in members:
                    members.remove(manager)
                    members.insert(0, manager)
                else:
                    manager_elsewhere = True
        projects = sorted({str(m.get("project")) for m in members if m.get("project")})
        row = defs.get(team) or {}
        mark = (work or {}).get(team)  # the home's `work_waiting` mark (§6 rule 8), if any
        # live, concluded, wound down and Forget all read the team's unattended sessions: a person's
        # session in it keeps nothing live (design §4.9 *A person in the team*, TD-173)
        crew = [m for m in members if not teamrun.persons(m)] if team != NO_TEAM else members
        live = sum(1 for m in crew if m.get("state") not in DEAD)
        people = [m for m in members if teamrun.persons(m) and m.get("state") not in DEAD] if team != NO_TEAM else []
        c = row.get("concluded")
        # the definition's rows read the raw records; a view that disagrees about what is live (a
        # delta between the two reads) is not drawn concluded — Wind down is the safe offer then
        concluded = c if live and isinstance(c, dict) and len(c.get("names") or ()) == live else None
        # never a person's card, live or closed: Forget all is a team act (§4.9 *A person in the team*)
        dead = [m for m in crew if not m.get("seat") and m.get("state") in DEAD] if team != NO_TEAM and not live else []
        ready = sum(1 for m in members if (m.get("slot") or {}).get("ccls") == "ready" and m.get("state") == "idle")
        waiting = prs_waiting(members) if team != NO_TEAM else None
        # `needs`: the Inbox's *Needs you* rows, whose open asks from a member are its *asked you* line (TD-354)
        # the team's repo is its definition's `repo:`; a badge no definition holds, where its records sit
        # (§4.9 *The Sessions page*, TD-725) — the heading `org_layout` draws it under
        repo_name = str(row.get("repo") or "") if team != NO_TEAM else ""
        if team != NO_TEAM and not repo_name:
            repo_name = str((team_repo(members, repos or {}) or {}).get("name") or "")
        summary = (
            team_summary(team, members, repos, doing, waiting, needs=needs, fleet=views, repo=repo_name)
            if team != NO_TEAM
            else None
        )
        if summary:
            lanes = ((summary.get("repo") or {}).get("ledger") or {}).get("lanes")
            for m in members:
                m["compact"], m["compact_line"] = True, compact_line(m, repos)
                m["lane_count"] = lane_count(m, lanes)  # the member's own count, in its pill (TD-428)
            # a team with nothing live draws only the facets that hold something (TD-418); the Repo page's
            # cards draw no Repo facet, its line drawing it (§4.5a *team card: Repo facet*, TD-1189)
            drawn = drawn_facets(summary) if not live else [f for f in FACETS if f != "repo" or summary.get("repo")]
            summary["drawn"] = [f for f in drawn if f != "repo" or not repo_page]
        groups.append(
            {
                "team": team,
                "label": team or "No repo",
                "repo": repo_name,
                "order": (0, order[team], "") if team in order else (1, 0, team),
                # the header names its manager only when that card is in another group (TD-095: its
                # name, state and line are on its own card, the first here); `role_label` is what it
                # is called there (§4.8 *The names*, TD-076): *Manager*, or its role's own label.
                "manager": {k: manager.get(k) for k in ("id", "name", "state", "role_label")} if manager else None,
                "manager_elsewhere": manager_elsewhere,  # its card sits under its own badge, not here
                "members": members,
                "ids": [m["id"] for m in members],
                "projects": projects or ([row["project"]] if row.get("project") else []),
                "needs": sum(1 for m in members if m.get("state") == "needs-you"),
                "prs_waiting": waiting,
                "spend": team_figure(team, (spend or {}).get(team)) if team != NO_TEAM else None,
                "summary": summary,
                "live": live,
                # the header's own facts (design §4.5 *The card's anatomy*, TD-095): where the
                # team's sessions are, once, and how many are in each state — never its manager's
                # name, state or line, which are on the manager's card, the first in the group
                "place": group_place(members),
                # drawn only while folded (TD-418): unfolded, the member cards say it
                "counts": state_counts(members),
                "unseen_n": unseen_count(members),  # *n unseen* after them, in the accent blue (TD-1228)
                # …and, on any team, folded or not, how many wait for a person's Close — a mark
                # (TD-156 (b): a concluded team's idle cards were folded away and read as already closed)
                "ready": ready,
                # a definition exists, so the group's card carries Start, or Stop / Stop now (§4.5a)
                "defined": team in defs,
                "source": row.get("source"),
                "in_org": bool(row.get("in_org")),  # Members… edits org.yml's teams only (TD-172)
                # the repo whose `.shiftlead.yml` defines it, for the disabled Members…'s reason (TD-229)
                "source_repo": Path(row["source"]).parent.name if row.get("source") and not row.get("in_org") else "",
                "def_manager": row.get("manager"),  # the definition's word, for a card with no sessions yet
                "def_members": row.get("members"),
                "def_techlead": row.get("techlead"),  # the seat's name (§4.9b), when the definition has one
                # every seat the definition names, once each: a stopped team's rollup row stubs those with no
                # counted card (§4.5a *Sessions: rollup*, TD-1204), never a person-held manager
                "seat_names": seat_names(row),
                # *nothing running* and *nothing left to run* are different facts (§4.9a)
                "wound_down": row.get("wound_down"),
                "wound_down_age": row.get("wound_down_age"),
                "by_tick": bool(row.get("by_tick")),  # *· by the tick*: rule 9 wound it down (§6, TD-241)
                # who, how soon and why (§4.5a *wound down* note, TD-265): `teamrun.wound_down_note`'s reading
                "wound_after": row.get("after") or "",
                "closed_by": row.get("closed_by") or "",
                "manager_why": row.get("manager_why") or "",
                # §4.5a team card **work waiting** note (§6 rule 8, TD-227): display only, beside *wound
                # down* or a stopped team's *stopped* (TD-781)
                "work_note": work_note(mark) if not live and (row.get("wound_down") or _stopped(mark)) else None,
                # …and a defined team with no crew record, what its lanes hold (*A team with no record*, TD-781):
                # `teamrun.lanes`' distinct ids, the tooltip Start's line; nothing when empty or unread
                "lanes_hold": (row.get("lanes_hold") or 0) if not live and not row.get("records") else 0,
                "lanes_line": row.get("lanes_line") or "",
                "work_started": work_started(crew) if live and team != NO_TEAM else None,
                # §4.5a team card **over its line** note (§6 *Balance*, TD-239): the home's mark, display only
                "balance_note": teamrun.balance_note(marks[team]) if live and team in marks else "",
                # §4.5a team card **stops** note (§6 *Team stop time*, TD-337): the team's own setting,
                # on a live team alone — a team with nothing live has the *starts* note's slot
                "stops_note": stop_note({"run_until": until}) if live and (until := uiconf.team_until(team)) else "",
                # live, and every live session idle and declared (§4.5a, TD-099): drawn like a
                # stopped team — sorted with them, Start alone, though it opens unfolded (TD-194) —
                # since a wind-down would only wake the manager to find nothing to wind down
                "concluded": concluded,
                # a live, defined team that is not: why there is no Start, a clause per session
                # that keeps it from the reading (§4.5a *team groups*, TD-241)
                "not_concluded": list(row.get("not_concluded") or []) if live and concluded is None else [],
                "concluded_age": row.get("concluded_age") if concluded else "",
                "stopped": not live or concluded is not None,
                # a person's live sessions in the team, named apart in Wind down's and Stop now's
                # confirm: a team act never stops an interactive session (§4.9, §9 invariant 5)
                "stays": [teamrun.stays_line(m) for m in people],
                # design §4.5a team card **Forget all** (TD-071 item 1): on a team with nothing live,
                # the Forget each card carries, on every card but those with the dirty / unpushed
                # flag — Forget drops the record that points at the worktree, and unpushed work would
                # lose its only pointer, so those are named apart and forgotten one at a time. A seat
                # with nobody in it is neither: its card never offers Forget while the definition
                # names it (`next_act`), and Forget all does not go round that
                "forget": [m for m in dead if not m.get("flag")],
                "forget_kept": [m for m in dead if m.get("flag")],
                # design §4.5a team header **✉ n** (TD-071 item 2): what the fold hides of the cards'
                # unread chips — display only, the mail stays where it is (§4.10)
                "unread": sum(int(m.get("unread") or 0) for m in members),
                # design §4.5a ***i*** mark **who for what** (§4.8, TD-171): whom to write to, by role
                "who": who_for_what((defs.get(team) or {}).get("roles") or (), views) if team != NO_TEAM else [],
                # design §4.5a *team groups*: the flow it runs and its strip, and *flow changed — Apply*
                **flow_head((flows or {}).get(team), live=bool(live) and team in defs),
            }
        )
    # what is running is read first; the no-team group is never "stopped" — nothing there starts as one
    # …and among the live teams, one with a session that needs a person comes first (2026-09-18)
    groups.sort(
        key=lambda g: (2 if g["team"] and g["stopped"] else 1 if not g["team"] else 0, not g["needs"], g["team"])
    )
    return groups


def seat_names(row: Mapping[str, Any]) -> list[str]:
    """The session names a team's definition (`teamrun.rows`' row) names, in its order, once each: its
    roles' holders, its manager, its techlead seat and its seats — never `person`, a person-held manager."""
    names = [str(n) for r in row.get("roles") or () for n in r.get("names") or ()]
    names += [str(x) for x in (row.get("manager"), row.get("techlead")) if x]
    names += [str(x.get("name")) for x in row.get("seats") or () if isinstance(x, dict) and x.get("name")]
    return [n for i, n in enumerate(names) if n != "person" and n not in names[:i]]


# the keys the client keys the page's elements on, each kind its own prefix, so no name meets another's
TEAM_KEY, STRIP, REPO_LINE, HEADING, NO_REPO = "team:", "strip:", "repo:", "head:", "norepo"


def strip_group(key: str, label: str, members: list[dict[str, Any]], repo: str, project: str) -> dict[str, Any]:
    """A section of sessions with no team: a repo's no-team strip, or *No repo* (§4.9 *The Sessions page*).
    Not a card: no header but its words, no summary, no controls, never folded."""
    members = sorted(members, key=card_order)
    return {
        "kind": "strip" if repo else "norepo",
        "key": key,
        "team": NO_TEAM,
        "label": label,
        "repo": repo,
        "project": project,
        "manager": None,
        "members": members,
        "ids": [m["id"] for m in members],
        "live": sum(1 for m in members if m.get("state") not in DEAD),
        "summary": None,
        "defined": False,
    }


def repo_line(
    name: str,
    r: Mapping[str, Any] | None,
    teams: list[dict[str, Any]],
    fleet: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any] | None:
    """The **Repo facet** a repo's line draws (§4.5a *team card: Repo facet*, §4.9 *The Sessions page*,
    TD-725) while no card of the repo shows one (TD-1189), and always on the Repo page. Its lanes *i*
    carries one line per team on the repo; its bars' hovers are the first such team's. None where this host
    reads no repo of that name: the line is then its name alone."""
    if r is None:
        return None
    lines = [got for g in teams if (got := team_lanes(str(g["team"]), fleet, r))]
    lanes = {**lines[0], "text": "\n".join(x["text"] for x in lines)} if lines else None
    waiting = prs_waiting([m for g in teams for m in g.get("members") or []])
    return repo_facet(r, now, waiting, lanes, fleet)


def org_layout(
    groups: list[dict[str, Any]] | None,
    repos: Mapping[str, Any] | None,
    projects: Collection[orgmod.Project] = (),
    fleet: Collection[dict[str, Any]] = (),
    now: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """The Sessions page down from the rollup (§4.9 *The Sessions page*, §4.5a *team groups*, TD-725), from
    `team_groups`' groups: **project → repo → team**. The headings are in the org file's order — each
    project, its `title` else its name, with its repos in its list's order — then the repos no project
    lists, in the registry's order (`repos`, the home's readings), then any team's repo neither names.
    **A project of one repo draws one heading**, the repo's: its line is the heading. Under each repo,
    its **line** (its name and the Repo facet, which the client shows only while no card of the repo shows
    its own, TD-1189), its **teams** —
    the live and concluded first, then those with nothing live, each in definition order — and a
    **no-team strip** of the repo's sessions with no team badge. Then a team whose repo is not told,
    and last **No repo**, the sessions in no registered repo. A registered repo with no team is its
    line alone; a project's repo this host neither reads nor has a team on is not drawn.

    Each item carries `kind` (`heading`, `repo`, `team`, `strip`, `norepo`) and `key`, which the
    client keys its elements on. None for the flat page."""
    if groups is None:
        return None
    now = now or datetime.now(UTC)
    fleet = list(fleet)
    readings = {str(r["name"]): r for r in (repos or {}).values() if isinstance(r, dict) and r.get("name")}
    by_root = {
        str(Path(root).resolve()): str(r["name"])
        for root, r in (repos or {}).items()
        if isinstance(r, dict) and r.get("name")
    }
    roots = {name: root for root, name in by_root.items()}  # *New session here*'s directory (TD-1204)
    teams = [g for g in groups if g["team"] != NO_TEAM]
    loose = next((g["members"] for g in groups if g["team"] == NO_TEAM), [])
    by_repo: dict[str, list[dict[str, Any]]] = {}
    for g in teams:
        by_repo.setdefault(str(g.get("repo") or ""), []).append(g)
    strays: dict[str, list[dict[str, Any]]] = {}
    for m in loose:
        name = by_root.get(str(Path(str(m["repo"])).resolve()), "") if m.get("repo") else ""
        strays.setdefault(name, []).append(m)
    heads: list[tuple[str, str, list[str]]] = []
    listed: set[str] = set()
    for p in projects:
        heads.append((p.name, p.title or p.name, list(p.repos)))
        listed.update(p.repos)
    rest = [n for n in readings if n not in listed]
    rest += [n for n in by_repo if n and n not in listed and n not in readings]
    # a repo in no project is its own heading, under no project's key: a project named like it is another's
    heads += [("", n, [n]) for n in rest]
    out: list[dict[str, Any]] = []
    for key, label, names in heads:
        names = [n for n in names if n in readings or n in by_repo or n in strays]
        if not names:
            continue
        if len(names) > 1:
            out.append({"kind": "heading", "key": HEADING + key, "label": label, "project": key, "repos": names})
        for n in names:
            here = sorted(by_repo.pop(n, []), key=lambda g: (not g["live"], g["order"]))
            out.append(
                {
                    "kind": "repo",
                    "key": REPO_LINE + n,
                    "repo": n,
                    "project": key,
                    "heading": len(names) == 1,  # the repo's line is the heading (§4.9)
                    "url": f"/repo/{n}",
                    "root": roots.get(n, ""),
                    "facet": repo_line(n, readings.get(n), here, fleet, now),
                }
            )
            out += [{**g, "kind": "team", "key": TEAM_KEY + g["team"], "project": key} for g in here]
            if mine := strays.pop(n, []):
                said = f"{len(mine)} session{'' if len(mine) == 1 else 's'}, no team"
                out.append({**strip_group(STRIP + n, said, mine, n, key), "root": roots.get(n, "")})
    # a team whose repo is told nowhere (a badge whose records sit in no registered repo), then *No repo*
    left = sorted((g for gs in by_repo.values() for g in gs), key=lambda g: (not g["live"], g["order"]))
    out += [{**g, "kind": "team", "key": TEAM_KEY + g["team"], "project": ""} for g in left]
    if nowhere := [m for ms in strays.values() for m in ms]:
        out.append(strip_group(NO_REPO, "No repo", nowhere, "", ""))
    return out
