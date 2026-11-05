"""The home's witness log (design §4.4 *The home keeps a log of what it witnesses*, TD-1295, TD-1386).

One line a record, `{id, at, kind, repo, text}`, in `witnessed/<YYYY-MM>.jsonl` under the home's store, one
file per UTC month of `at`, appended to and never rewritten; `witnessed/start` is the instant the home first
ran with the log, written once at the agent's start, and nothing dated before it is written. Every writer goes
through `append`, which the agent runs on its loop. Kept `WITNESS_KEEP_MONTHS`: the current month and the
twelve before it. A record of a kind not in `KINDS` is never written."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import paths

log = logging.getLogger(__name__)

WITNESS_KEEP_MONTHS = 13  # the current month and the twelve before it (a constant, not a setting)
# the `<repo>` id (ledgerboard SPEC v2.4: the origin's path, lowercased) of the repo the package is built
# from: an event of the install rather than of a repo it services (a host's rebuild, push turned on) is
# written tied to it (§4.4 *A repo's id*, TD-1390)
OWN_REPO = "shiftlead/shiftlead"

# Each kind's text, and whether its records may count for a public ledger: the host file's `public_kinds`
# is written from the flags (§4.4 *The kinds*, *The host file*; TD-045 rule 11).
KINDS: dict[str, dict[str, Any]] = {
    "precheck-fail": {
        "text": "<repo>#<n> or <repo>@main, the head's first 12 hex, status <id>, then the failing tests it holds",
        "public": True,
    },
    "press": {"text": "<word> <target>", "public": True},
}
HOST_FILE = "host-log.toml"  # the host file (rule 9), in the home's store: written once, then the person's

# The press words (`witness_press`), each saying whether it carries a `dir` the record's repo is mapped from.
PRESS_WORDS: dict[str, bool] = {
    "apply": True,
    "start": True,
    "new-session": True,
    "host-rebuild": False,
    "send-to-reviewer": True,
    "push-on": False,
}

ID_RE = re.compile(r"[A-Za-z0-9_.@/-]+")
RED_STATES = ("failure", "error")  # a commit status's words for red, as `promote.py` reads them
_FAILED_LINE = re.compile(r"^FAILED ([^\s(]\S*)", re.M)  # pytest's `FAILED <node id> - …`, not `FAILED (errors=1)`
_STATUS_TOKEN = re.compile(r"(?:^|\s)status (\S+)(?=\s|$)")  # a `precheck-fail` record's status id
_MONTH_RE = re.compile(r"(\d{4})-(\d{2})\.jsonl")


def directory() -> Path:
    return paths.home() / "witnessed"


def _utc(at: datetime) -> datetime:
    return at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)


def _iso(at: datetime) -> str:
    return _utc(at).isoformat().replace("+00:00", "Z")


def _parse(v: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return _utc(at)


def month_file(at: datetime, root: Path | None = None) -> Path:
    at = _utc(at)
    return (root or directory()) / f"{at.year:04d}-{at.month:02d}.jsonl"


def start(root: Path | None = None) -> datetime | None:
    """The instant the log begins, or None before it was written (or when it cannot be read)."""
    try:
        return _parse((root or directory()).joinpath("start").read_text(encoding="utf-8").strip())
    except OSError:
        return None


def ensure_start(now: datetime | None = None, root: Path | None = None) -> datetime:
    """Write `start` once, at the agent's start, when it is absent; the instant the log begins."""
    got = start(root)
    if got is not None:
        return got
    d = root or directory()
    d.mkdir(parents=True, exist_ok=True)
    at = _utc(now or datetime.now(UTC))
    (d / "start").write_text(_iso(at) + "\n", encoding="utf-8")
    return at


def _month_index(at: datetime) -> int:
    return at.year * 12 + at.month - 1


def boundary(now: datetime | None = None) -> datetime:
    """The first instant of the oldest month kept, counted from the calendar, never from the files present."""
    i = _month_index(_utc(now or datetime.now(UTC))) - (WITNESS_KEEP_MONTHS - 1)
    return datetime(i // 12, i % 12 + 1, 1, tzinfo=UTC)


def read_month(f: Path) -> list[dict[str, Any]]:
    """A month file's records; an unreadable line is skipped."""
    out: list[dict[str, Any]] = []
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and _parse(r.get("at")) is not None:
            out.append(r)
    return out


def records(root: Path | None = None) -> list[dict[str, Any]]:
    """Every record kept, sorted by `at`."""
    d = root or directory()
    files = sorted(f for f in d.glob("*.jsonl") if _MONTH_RE.fullmatch(f.name)) if d.is_dir() else []
    got = [r for f in files for r in read_month(f)]
    return sorted(got, key=lambda r: _parse(r["at"]) or datetime.min.replace(tzinfo=UTC))


def new_id(at: datetime, taken: Iterable[str] = ()) -> str:
    """`w-<YYYYMMDDTHHMMSSZ>-<4 hex>`, drawn again while it collides with one in `taken`."""
    held = set(taken)
    stem = f"w-{_utc(at).strftime('%Y%m%dT%H%M%SZ')}-"
    while True:
        got = stem + secrets.token_hex(2)
        if got not in held:
            return got


def append(kind: str, repo: str, text: str, at: datetime | None = None, root: Path | None = None) -> dict | None:
    """Write one record — the one entry point, run on the agent's loop. None, and nothing written, for a
    kind not in `KINDS`, an `at` before `start`, or a log with no `start` yet; a ValueError for a kind not
    in `KINDS` or an empty `repo` (the `<repo>` id the record counts for, §4.4 *A repo's id*). `text` is one
    line."""
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a witness kind ({', '.join(KINDS)})")
    if not isinstance(repo, str) or not repo.strip():
        raise ValueError(f"a {kind} record names the repo it belongs to (its <repo> id)")
    when = _utc(at or datetime.now(UTC))
    begun = start(root)
    if begun is None or when < begun:
        return None
    f = month_file(when, root)
    taken = [str(r.get("id")) for r in read_month(f)]
    rec = {
        "id": new_id(when, taken),
        "at": _iso(when),
        "kind": kind,
        "repo": repo.strip(),
        "text": " ".join(str(text).split()),
    }
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def prune(now: datetime | None = None, root: Path | None = None) -> list[str]:
    """Delete the month files older than the months kept; the names removed."""
    d = root or directory()
    if not d.is_dir():
        return []
    oldest = _month_index(boundary(now))
    gone: list[str] = []
    for f in d.glob("*.jsonl"):
        m = _MONTH_RE.fullmatch(f.name)
        if m and int(m[1]) * 12 + int(m[2]) - 1 < oldest:
            try:
                f.unlink()
            except OSError as e:
                log.warning("pruning the witness log's %s failed: %s", f.name, e)
                continue
            gone.append(f.name)
    return sorted(gone)


def repo_named(dir: Any, roots: Iterable[str]) -> tuple[str, str] | None:
    """`(root, name)` of the registered repo `dir` is in — its real path matched against each root's real
    path — `root` the registered string as given (as the repo facts key it, never its real path) and `name`
    its basename (the registry name, for a record's text); else None. An empty `dir` is in none."""
    if not isinstance(dir, str) or not dir.strip():
        return None
    try:
        here = Path(os.path.realpath(dir))
    except (OSError, ValueError):
        return None
    best: tuple[Path, str] | None = None
    for r in roots:
        try:
            root = Path(os.path.realpath(r))
        except (OSError, ValueError):
            continue
        if (here == root or here.is_relative_to(root)) and (best is None or len(root.parts) > len(best[0].parts)):
            best = (root, str(r))
    return (best[1], Path(best[1]).name) if best is not None else None


# ── the `precheck-fail` writer (§4.4 *The kinds*, TD-1386 slice 2) ─────────────────────────────────

_recorded: dict[str, tuple[tuple[int, int], set[str]]] = {}  # a month file's status ids, by its size and mtime


def recorded_statuses(f: Path) -> set[str]:
    """The status ids the `precheck-fail` records of month file `f` name, each a whole token (`status 12`
    is never `status 123`): read on demand and cached while the file stands unchanged."""
    try:
        st = f.stat()
    except OSError:
        return set()
    key = (st.st_size, st.st_mtime_ns)
    hit = _recorded.get(str(f))
    if hit and hit[0] == key:
        return hit[1]
    ids = {
        m[1]
        for r in read_month(f)
        if r.get("kind") == "precheck-fail"
        for m in _STATUS_TOKEN.finditer(str(r.get("text") or ""))
    }
    _recorded[str(f)] = (key, ids)
    return ids


def append_precheck_fail(
    repo: str, text: str, status: Any, at: datetime, now: datetime | None = None, root: Path | None = None
) -> dict | None:
    """One red precheck status's record, unless it is already recorded — its id a whole token in the month
    file of its `created_at`, the file its record would be in, so a restart writes nothing twice — or it was
    created before the retention boundary (writing it would recreate a pruned month) or before `start`."""
    when = _utc(at)
    if when < boundary(now) or str(status) in recorded_statuses(month_file(when, root)):
        return None
    return append("precheck-fail", repo, text, when, root)


def failing_tests(log_path: Any) -> list[str]:
    """Every pytest node id a precheck run's log names on a `FAILED <id>` line, in order, once each."""
    try:
        text = Path(str(log_path)).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for m in _FAILED_LINE.finditer(text):
        if m[1] not in out:
            out.append(m[1])
    return out


def precheck_fails(
    label: str, sha: str, statuses: Iterable[Any], own: dict[str, Any] | None = None
) -> list[tuple[datetime, str, str]]:
    """`(at, text, status id)` for each red status (`failure` or `error`) of a head's `cadence/precheck`
    list, oldest first, `at` the status's `created_at`. `label` is `<repo>#<n>` or `<repo>@main`. `own` is
    the home's own run on main (`precheck.json`, `{sha, at, log, exit}`): where it exited red, the first red
    status on its sha created at or after the run began is its, and names the tests its log failed; any other
    status names none."""
    reds = []
    for s in statuses:
        if not isinstance(s, dict) or str(s.get("state") or "").lower() not in RED_STATES:
            continue
        at = _parse(s.get("created_at"))
        if at is not None and s.get("id") is not None:
            reds.append((at, str(s["id"])))
    reds.sort()
    mine = None
    o = own or {}
    failed = isinstance(o.get("exit"), int) and o["exit"] != 0  # a green or unseen run names no test
    began = _parse(o.get("at")) if o.get("sha") == sha and failed else None
    if began is not None:
        mine = next((sid for at, sid in reds if at >= began), None)
    out = []
    for at, sid in reds:
        tests = failing_tests(own.get("log")) if own and sid == mine else []
        out.append((at, " ".join([label, sha[:12], f"status {sid}", *tests]), sid))
    return out


# ── the host file (§4.4 *The host file*, TD-045 rule 9, TD-1390) ────────────────────────────────────

_HOST_COMMENT = """\
# The witness log's host file (shiftlead design §4.4 *The host file*; ledgerboard TD-045 rule 9), written
# once by the home at its start when absent and never again: it is yours to edit. A [repos."<repo>"] table
# you add replaces [repos."*"] for that repo whole: give it `public_kinds` and `path` again, or a public
# ledger's gates read *error* and the repo file's ~/.shiftlead/witnessed applies. Delete this file and the
# home writes it again at its next start.
"""


def public_kinds() -> list[str]:
    """The kinds whose records may count for a public ledger (`KINDS`' `public` flag), in table order."""
    return [k for k, v in KINDS.items() if v.get("public")]


def toml_string(s: str) -> str:
    """`s` as a TOML basic string: escaped as JSON escapes it (`\\"`, `\\\\`, control characters), which
    TOML reads the same, and U+007F, which JSON leaves bare and TOML refuses, as `\\u007F`. A UnicodeError
    for a string that cannot be encoded as UTF-8 (a path's undecodable bytes, held as surrogates)."""
    s.encode("utf-8")
    return json.dumps(s, ensure_ascii=False).replace("\x7f", "\\u007F")


def host_file(store: Path | None = None) -> Path:
    return (store or paths.home()) / HOST_FILE


def host_text(witnessed: Path) -> str:
    """What the home writes: every repo served (`[repos."*"]`), `witnessed` at the log's real folder with
    the public kinds, and that folder the one allowed root, `private` and `require_repo`."""
    where = toml_string(str(witnessed))
    kinds = ", ".join(toml_string(k) for k in public_kinds())
    return (
        f"{_HOST_COMMENT}\n"
        f'[repos."*"]\nprofiles = []\n\n'
        f'[repos."*".sources.witnessed]\npath = {where}\npublic_kinds = [{kinds}]\n\n'
        f'[[allow]]\nroot = {where}\nvisibility = "private"\nrequire_repo = true\n'
    )


def ensure_host_file(store: Path | None = None) -> bool:
    """Write the host file when it is absent, whole or not at all (a temporary file renamed), and never
    rewrite it: True when this call wrote it. A store path that cannot be encoded as UTF-8 writes none (the
    start's check then warns)."""
    store = store or paths.home()
    f = host_file(store)
    if f.exists() or f.is_symlink():
        return False
    witnessed = Path(os.path.realpath(store / "witnessed"))
    try:
        text = host_text(witnessed)
    except UnicodeError:
        log.warning("the witness log's host file is not written: the store path %r is not valid UTF-8", str(store))
        return False
    tmp = f.with_name(f".{HOST_FILE}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return True


def host_file_problem(store: Path | None = None) -> str | None:
    """Why the host file allows no reading of the current `witnessed/` — absent, unparseable, no
    `[[allow]]`, or no root covering it (equal to or a parent of its real path) — naming the file's roots
    and the folder; None when one root covers it."""
    import tomllib

    store = store or paths.home()
    f = host_file(store)
    here = Path(os.path.realpath(store / "witnessed"))
    if not f.is_file():
        return f"{f} is absent, so every host-log gate reads error (current witnessed/: {here})"
    try:
        data = tomllib.loads(f.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as e:
        return f"{f} does not parse ({e}), so every host-log gate reads error (current witnessed/: {here})"
    allow = data.get("allow")
    if not isinstance(allow, list) or not allow:
        return f"{f} has no [[allow]], so every host-log gate reads error (current witnessed/: {here})"
    roots: list[str] = []
    for a in allow:
        r = a.get("root") if isinstance(a, dict) else None
        if not isinstance(r, str):
            continue
        roots.append(r)
        try:
            root = Path(os.path.realpath(os.path.expanduser(r)))
        except (OSError, ValueError):
            continue
        if here == root or here.is_relative_to(root):
            return None
    return f"no [[allow]] root in {f} covers the current witnessed/ {here} (its roots: {', '.join(roots) or 'none'})"
