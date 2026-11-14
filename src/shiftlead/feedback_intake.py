"""`ao feedback intake` (design §4.7 *Feedback*, *Reports from other installs*, *The intake, in file mode*,
TD-1718, TD-1795).

A report's text is a stranger's. The intake reads `gh issue list --json number,title,body,author,createdAt`'s saved
list, keeps the titles that open `feedback report: `, takes from each body the first fenced `json` block after the
marker line, and builds its output from the report's own fields alone: each checked by the report's rules, each
`what` and `fix` through the shared rules (`feedback_report.shared`: normalize, the URL and email pass, the pattern
pass, the cut — never the names pass), the report cut to its first 40 findings and a count to 999. A refusal's
`why` is one of a fixed set naming at most a field, never a value. The build day is derived from `commit` in
shiftlead's own clone, never taken from the report.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from shiftlead import feedback_report as fr

MAX_READ = 5  # reports one `--read` prints
LIST_LIMIT = 100  # `gh issue list --limit`, so a list that long says more wait
NOT_A_REPORT = "not a report"
NO_MARKER = "no marker"
NO_PARSE = "block does not parse"
UNKNOWN_V = "unknown v"

_COMMIT_RE = re.compile(r"[0-9a-fA-F]{7,40}")
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?")
_INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})")
_FENCE_RE = re.compile(r"^```json[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


class NotTheList(ValueError):
    """Exit 2: `--issues` cannot be read, or is not gh's list."""


class _Refused(Exception):
    """A report refused, with its fixed `why`."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def _check(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """One of the report's field rules, its `Refused` turned into this report's refusal (`<field>: …`)."""
    try:
        return fn(*args, **kw)
    except fr.Refused as e:
        raise _Refused(str(e)) from None


def _block(body: Any) -> Any:
    """The first fenced `json` block after the marker line, parsed."""
    if not isinstance(body, str) or fr.MARKER not in body:
        raise _Refused(NO_MARKER)
    body = body.replace("\r\n", "\n")  # a body GitHub's form took in carries CRLF line ends
    m = _FENCE_RE.search(body, body.index(fr.MARKER) + len(fr.MARKER))
    if not m:
        raise _Refused(NO_PARSE)
    try:
        return json.loads(m.group(1))
    except (ValueError, RecursionError):
        raise _Refused(NO_PARSE) from None


def _cut_text(text: str, keep: Iterable[str]) -> tuple[str, bool]:
    """The shared rules on one string, and whether the 300-character cut dropped any of it."""
    got = fr.shared(text, keep)
    t = fr._Text(fr.normalize(text))
    fr._urls(t)
    fr._patterns(t, keep)
    return got, t.finish(cut=len(t.text) * 4 + 10**4) != got


def parse(data: Any) -> dict[str, Any]:
    """A report's block, checked and cut: `{commit, days, seats, noise, new, known, cut}`. Raises `_Refused`."""
    if not isinstance(data, dict):
        raise _Refused(NO_PARSE)
    v = data.get("v")
    if type(v) is not int or v != fr.V:  # `1.0` and `true` are no v1
        raise _Refused(UNKNOWN_V)
    commit = data.get("commit")
    if commit is not None:
        if not isinstance(commit, str):
            raise _Refused("commit: bad type")
        if not _COMMIT_RE.fullmatch(commit):
            raise _Refused("commit: not allowed")
    days = _check(fr._whole, data.get("days"), "days", fr.DAYS_MAX)
    seats = _check(fr._whole, data.get("seats"), "seats", fr.SEATS_MAX)
    noise = data.get("noise")
    if isinstance(noise, bool) or not isinstance(noise, int | float):
        raise _Refused("noise: bad type")
    if not 0 <= noise <= 1 or noise != noise:
        raise _Refused("noise: not allowed")
    capped: set[int] = set()  # the id() of each item whose count was capped

    def count(item: dict[str, Any], v: Any) -> int:
        got = _check(fr._whole, v, "count", fr.COUNT_MAX, cap=True)
        if v > fr.COUNT_MAX:
            capped.add(id(item))
        return got

    new = []
    for f in _check(fr._objects, data.get("new"), "new"):
        area = _check(fr._text, f.get("area"), "area")
        if area not in fr.AREAS:
            raise _Refused("area: not allowed")
        recurs = f.get("recurs")
        item: dict[str, Any] = {
            "area": area,
            "what": _check(fr._text, f.get("what"), "what"),
            "fix": _check(fr._text, f.get("fix"), "fix"),
        }
        item["count"] = count(item, f.get("count"))
        item["recurs"] = None if recurs is None else _check(fr._td, recurs, "recurs")
        new.append(item)
    known = []
    for k in _check(fr._objects, data.get("known"), "known"):
        repo = _check(fr._text, k.get("repo"), "repo")
        if repo not in fr.AREAS:
            raise _Refused("repo: not allowed")
        item = {"repo": repo, "id": _check(fr._td, k.get("id"), "id")}
        item["count"] = count(item, k.get("count"))
        known.append(item)
    over = max(0, len(new) + len(known) - fr.MAX_FINDINGS)
    new = new[: fr.MAX_FINDINGS]
    known = known[: fr.MAX_FINDINGS - len(new)]
    known_ids = [k["id"] for k in known]
    cut_text = 0
    for f in new:
        keep = [*known_ids, *([f["recurs"]] if f["recurs"] else [])]
        for key in ("what", "fix"):
            f[key], was_cut = _cut_text(f[key], keep)
            cut_text += was_cut
    return {
        "commit": commit,
        "days": days,
        "seats": seats,
        "noise": round(float(noise), 2),
        "new": new,
        "known": known,
        "cut": {"findings": over, "counts": sum(id(i) in capped for i in [*new, *known]), "text": cut_text},
    }


# ── the build day, from shiftlead's own clone ─────────────────────────────────────────────────

GitRun = Callable[..., subprocess.CompletedProcess[str]]


def build_day(commit: str | None, root: str | Path, run: GitRun = fr.git) -> str | None:
    """`commit`'s committer day where it is one commit of `origin/main` in `root`, read from the object store
    (`rev-parse --disambiguate`, never a ref); `None` for a `None` commit, an ambiguous or missing one, one off
    `origin/main`, a `root` that is no checkout, or any `git` call that fails."""
    if commit is None:
        return None

    def ok(*args: str) -> str | None:
        try:
            cp = run(root, *args)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return cp.stdout.strip() if cp.returncode == 0 else None

    ids = ok("rev-parse", f"--disambiguate={commit}")
    if not ids or len(ids.split()) != 1:
        return None
    full = ids.split()[0]
    if ok("cat-file", "-t", full) != "commit":
        return None
    day = ok("log", "-1", "--format=%cs", full)
    if not day or ok("merge-base", "--is-ancestor", full, "origin/main") is None:
        return None
    return day


# ── the list ─────────────────────────────────────────────────────────────────────────────────


def read_list(path: str) -> list[dict[str, Any]]:
    """`--issues`: gh's list, each item an object with an integer `number`; else `NotTheList`."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        raise NotTheList(f"--issues cannot be read: {getattr(e, 'strerror', None) or e}") from None
    try:
        got = json.loads(raw)
    except (ValueError, RecursionError):
        raise NotTheList("--issues is not gh's list: it does not parse as JSON") from None
    if not isinstance(got, list) or not all(
        isinstance(i, dict) and isinstance(i.get("number"), int) and not isinstance(i.get("number"), bool) for i in got
    ):
        raise NotTheList("--issues is not gh's list: a list of issues with their number")
    return got


def _login(author: Any) -> str | None:
    login = author.get("login") if isinstance(author, dict) else None
    return login if isinstance(login, str) and _LOGIN_RE.fullmatch(login) else None


def _instant(v: Any) -> str | None:
    if not isinstance(v, str) or not _INSTANT_RE.fullmatch(v):
        return None
    try:
        datetime.fromisoformat(v.replace("z", "Z").replace("t", "T"))
    except ValueError:
        return None
    return v


def intake(issues: str, root: str | Path, read: Sequence[int] = (), *, run: GitRun = fr.git) -> dict[str, Any]:
    """`ao feedback intake --issues <file> --root <root> [--read <number>…]`: `{reports, refused, limit_reached}`,
    oldest first; with `read`, the named reports alone, each with its `new` and `known`. Raises `NotTheList`."""
    listed = read_list(issues)
    named = list(dict.fromkeys(read))
    if len(named) > MAX_READ:
        raise ValueError(f"--read takes at most {MAX_READ} numbers")
    reports: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    days: dict[str, str | None] = {}
    seen: set[int] = set()
    for issue in sorted(listed, key=lambda i: i["number"]):
        number = issue["number"]
        title = issue.get("title")
        if number in seen or not isinstance(title, str) or not title.startswith(fr.TITLE):
            continue
        seen.add(number)
        if named and number not in named:
            continue
        who = {"number": number, "login": _login(issue.get("author")), "created_at": _instant(issue.get("createdAt"))}
        try:
            got = parse(_block(issue.get("body")))
        except _Refused as e:
            refused.append({**who, "why": e.why})
            continue
        commit = got["commit"]
        if commit not in days:
            days[commit] = build_day(commit, root, run)
        row = {**who, "commit": commit, "build_day": days[commit], **{k: got[k] for k in ("days", "seats", "noise")}}
        if named:
            row |= {"new": got["new"], "known": got["known"]}
        else:
            row["findings"] = len(got["new"]) + len(got["known"])
        reports.append(row | {"cut": got["cut"]})
    for n in named:
        if n not in seen:
            refused.append({"number": n, "login": None, "created_at": None, "why": NOT_A_REPORT})
    return {"reports": reports, "refused": refused, "limit_reached": len(listed) >= LIST_LIMIT}
