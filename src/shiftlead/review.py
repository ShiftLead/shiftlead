"""Whether a PR waits for its reader (design §4.9b *The reader*, TD-093): the author's own `ao`
reads its record's `review` and checks the PR's changed files against `held:`. For that read the host agent only
stores the setting; once the PR has merged, the home checks the same thing itself (§6 rule 11).

`held:` is a list of path globs: a pattern names paths from the repo root, `**` spans any number
of directories, `*` and `?` stay inside one, and a pattern ending in `/` names everything under
that directory. Nothing else is special — `[abc]` is those five characters, not a class.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from functools import lru_cache
from typing import Any

# the glob match, the files read and `addressed` are `sessionorc`'s since §6 rule 11 reads them at
# the home (TD-258 slice 2; TD-349 for a chain): the package rule runs one way, so `ao pr held`
# reads them from there
from sessionorc.held import GH_TIMEOUT, addressed, held_paths, match, matches, pr_files  # noqa: F401
from sessionorc.models import PERSON, review_links


def setting(review: Any) -> dict[str, Any] | None:
    """A record's `review` with the design's defaults filled in — `held` every PR, `bound` two
    hours — whatever wrote it. A `ValueError` for a shape that holds nothing and says nothing: an
    empty `held:` is not *hold everything*, and not *hold nothing* either."""
    if not review:
        return None
    if isinstance(review, dict) and isinstance(review.get("chain"), list):
        # a flow's chain (§4.9c, TD-315): its links as written, `held` their union — the record's
        # shape is the host agent's check (`normalize_review`); whose turn it is, is slice 4's
        links = [dict(x) for x in review_links(review)]
        if not links:
            raise ValueError(f"review is not a setting: {review!r}")
        held = list(dict.fromkeys(g for x in links for g in x.get("held") or ["**"]))
        return {"chain": links, "held": held, "bound": str(review.get("bound") or "2h")}
    if not isinstance(review, dict) or not review.get("reader"):
        raise ValueError(f"review is not a setting: {review!r}")
    held = review.get("held", ["**"])
    if isinstance(held, str):
        held = [held]
    if not held or not all(isinstance(g, str) and g.strip() for g in held):
        raise ValueError(f"review: held is a list of path globs, not {held!r}")
    return {"reader": str(review["reader"]), "held": list(held), "bound": str(review.get("bound") or "2h")}


def walk(links: list[dict[str, Any]], asks: list[dict[str, Any]] | None, *, older: bool = False) -> dict[str, Any]:
    """Where a held PR stands along its chain (§4.9c *Whose turn it is*, TD-315 slice 4): `links` the
    record's links that hold the PR, in the flow's order, and `asks` its author's asks carrying the
    PR as `pr_reads` gives them (None: the home did not say). Each link gets a `state` — `passed` (its
    reader's last answer was `pass` or `merged`), `asked` (an ask is open, or answered with no verdict; one
    closed with no reply reads as never asked),
    `findings`, `next` (the first link not passed, never asked: the author's turn to ask it) or
    `later` — and `at`, the time of what set it. `turn` is the first link not passed, None once every
    link has passed or when the home did not say; `merges` the last link's reader, the one that
    merges. The older `{reader, held}` (`older`) takes every ask of the PR as its reader's, whoever it
    was addressed to; a chain matches each ask to a link by its addressee. A chain names each seat
    once — two stages of one role are refused — so no ask counts for two links."""
    rows: list[dict[str, Any]] = []
    turn: dict[str, Any] | None = None
    readers = [str(x.get("reader") or "") for x in links]
    for link in links:
        row = {"stage": link.get("stage"), "reader": link.get("reader"), "held": list(link.get("paths") or [])}
        if asks is None:
            row["state"], row["at"] = "unknown", None
        else:
            mine = [a for a in asks if older or any(addressed(x, readers) == link["reader"] for x in a["to"])]
            last = mine[-1] if mine else None
            if last is not None and last.get("open") is False and last.get("replied_at") is None:
                # closed with no reply landed — taken to the person, lapsed or expired (§4.9b *Why it did
                # not answer*, TD-1430): the link is the author's to ask again, never still `asked`
                last = None
            if last is None:
                row["state"], row["at"] = ("later" if turn is not None else "next"), None
            elif last.get("verdict") in ("pass", "merged"):
                row["state"], row["at"] = "passed", last.get("replied_at")
            elif last.get("verdict") == "findings":
                row["state"], row["at"] = "findings", last.get("replied_at")
            else:
                row["state"], row["at"] = "asked", last.get("at")
        if turn is None and row["state"] != "passed":
            turn = row
        rows.append(row)
    return {
        "chain": rows,
        "turn": turn["reader"] if turn is not None and asks is not None else None,
        "merges": rows[-1]["reader"] if rows else None,
    }


# what a reader's reply came to, as the PR standing words it (§4.9c *What is shown*)
STANDING_WORDS = {"pass": "passed by", "merged": "merged by", "findings": "findings from"}


def standing(
    reads: dict[str, Any] | None, names: dict[str, str], age: Callable[[str], str]
) -> dict[int, dict[str, str]]:
    """Each open PR's standing with its readers (§4.5 screen 11, §4.9c *What is shown*, TD-704), by number,
    for the Repo page and `ao repo`: worded from the repo reading's `pr_orders.reads` (§4.4 *The PR's
    reads*), the value the stage chip reads too. One word per addressee, in the order the asks were sent, a
    seat by `names` (its record's name), else its id: `open`, *waiting on <name> · <age>*; `answered`, *passed
    by*, *findings from* or *merged by <name>* by its verdict, *reviewed by <name>* for none; `closed`,
    nothing. The person's entry reads *waiting on you · <age>* while open and *with you* once answered without
    `again` while no other entry is newer; otherwise nothing. `cls` is `wait` while the turn is the reader's,
    the author's or the person's (an open ask, findings, the person's), else `done`."""
    out: dict[int, dict[str, str]] = {}
    for pr, entries in (reads or {}).items():
        if not str(pr).isdigit() or not isinstance(entries, list):
            continue
        rows = sorted((x for x in entries if isinstance(x, dict)), key=lambda x: str(x.get("at") or ""))
        parts: list[tuple[str, bool]] = []
        for x in rows:
            to, at, state = str(x.get("to") or ""), str(x.get("at") or ""), x.get("state")
            if to == PERSON:
                if state == "open":
                    parts.append((f"waiting on you · {age(at)}", True))
                elif state == "answered" and not x.get("again") and all(str(y.get("at") or "") <= at for y in rows):
                    parts.append(("with you", True))
                continue
            name = names.get(to) or to
            if state == "open":
                parts.append((f"waiting on {name} · {age(at)}", True))
            elif state == "answered":
                v = x.get("verdict")
                word = f"{STANDING_WORDS[v]} {name}" if v in STANDING_WORDS else f"reviewed by {name}"
                parts.append((word, v == "findings"))
        if parts:
            cls = "wait" if any(w for _, w in parts) else "done"
            out[int(pr)] = {"word": " · ".join(w for w, _ in parts), "cls": cls}
    return out


def unasked_reader(teams: list[list[dict[str, Any]]], held: list[str]) -> str | None:
    """The reader an *unasked* PR's tag names (design §4.4 *A held PR nobody asked is marked, never
    ordered*, TD-790), for the Repo page and `ao repo` alike: `teams` the servicing teams' members, in
    the Org's order, and `held` the PR's held paths. The first team whose members' `review` holds a
    touched path gives it: the first link whose `held` matches one of the paths (as `ao pr held` walks
    a chain, so under named sets a `ui` stage is not named for a PR outside its set), that link's
    seat by name — the team's member named so, else carrying it as its role — else `person` (a team
    without a seat). None where no servicing team has a reader."""
    for members in teams:
        links = [x for m in members for x in review_links(m.get("review"))]
        if not links:
            continue
        link = next((x for x in links if match(held, x.get("held") or ["**"])), None)
        if link is None:
            continue
        reader = str(link.get("reader") or "")
        if reader == PERSON:
            return PERSON
        named = [str(m.get("name") or "") for m in members]
        if reader in named:
            return reader
        seat = next(
            (m for m in members if m.get("role") == reader and (m.get("seat") or m.get("role") == "techlead")), None
        )
        return str(seat.get("name") or seat["id"]) if seat else PERSON
    return None


def unasked(r: dict[str, Any], number: int, teams: list[list[dict[str, Any]]]) -> dict[str, Any] | None:
    """The *unasked* tag of open PR `number` in the reading `r` (§4.4, §4.5 screen 11, TD-790): the PR
    is in the reading's `pr_orders.unasked` — never re-derived here — and a servicing team has a
    reader. `paths` the PR's held paths, `reader` as `unasked_reader` names it, `created` the PR's.
    None otherwise: the tag is drawn nowhere."""
    if number not in ((r.get("pr_orders") or {}).get("unasked") or []):
        return None
    p = next(
        (x for x in (r.get("prs") or {}).get("open") or [] if isinstance(x, dict) and x.get("number") == number), None
    )
    paths = [str(x) for x in (p or {}).get("held") or []]
    reader = unasked_reader(teams, paths)
    if reader is None:
        return None
    return {"paths": paths, "reader": reader, "created": str((p or {}).get("created") or "")}


def unasked_hint(number: int, tag: dict[str, Any]) -> str:
    """What the tag's title, and `ao repo`'s line after the age, tell the author (§4.5 screen 11)."""
    return f"post its review, then ao msg --kind ask --pr {number} {tag['reader']}"


_REMOTE = re.compile(
    r"^(?:https://(?:[^@/\s]+@)?|ssh://git@|git@)github\.com[:/](?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?/?$"
)


@lru_cache(maxsize=64)
def _github(directory: str) -> str:
    try:
        cp = subprocess.run(
            ["git", "-C", directory, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = _REMOTE.match(cp.stdout.strip()) if cp.returncode == 0 else None
    return f"https://github.com/{m.group('slug')}" if m else ""


def repo_web(directory: str | None) -> str:
    """The web address of the checkout at `directory` — its `origin` on GitHub — or "" when that
    cannot be said; `pr_url`'s base, for a page that links PR numbers it learns later (TD-150)."""
    return _github(str(directory)) if directory else ""


def pr_url(directory: str | None, pr: int) -> str:
    """The web link of PR `pr` in the checkout at `directory` — its `origin` on GitHub — or "" when
    that cannot be said (no directory, no origin, another forge): the Inbox then draws `#<n>` bare
    (design §4.5a, TD-093). The remote is read once per directory."""
    base = _github(str(directory)) if directory else ""
    return f"{base}/pull/{int(pr)}" if base else ""
