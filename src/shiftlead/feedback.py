"""`ao feedback digest` (design §4.7 *Feedback*, TD-1491, TD-1716): seats' transcripts over a window, condensed.

For each record, in the order given, the CLI asks the record's host for its `conversations` in the window, leaves
out what `--skip` names, the caller's own conversation and what an earlier record's call returned, and reads each
conversation's digest through `transcript_digest`, calling again with `next` until it is null. It writes the
text to `<dir>/<record id>.txt`, or `<record id>.1.txt` and on past `--part-bytes`, each conversation under its
`## <id> · <profile> · <first> → <last>` header, and returns the index §4.7 gives. `--list` returns the listing
alone and writes nothing. Nothing here knows a tool or a socket: `call(method, **params)` is the RPC.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

from sessionorc.adapters import instant
from sessionorc.agent_common import DIGEST_TIMEOUT
from sessionorc.client import CALL_TIMEOUT, AgentError
from sessionorc.digest import zone_of

UPSTREAM = "ShiftLead/shiftlead"  # the public repo a feedback report is for (§4.7 *Reports from other installs*)
PART_BYTES = 250_000  # a part's bound by default: about a fifth of an agent's context
PART_BYTES_MIN = 65_536  # under this refused: one entry is written to 64 KiB at most
WAIT = DIGEST_TIMEOUT + CALL_TIMEOUT  # the CLI's wait on each call, so the host's bound reaches it as its error
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROMPT = re.compile(r"^\d\d:\d\d >( |$)")

Call = Callable[..., Any]


# ── the run's zone and window ─────────────────────────────────────────────────────────────────


def local_zone(now: datetime | None = None) -> dict[str, Any]:
    """`{name, offset}`: the IANA name of the zone this machine runs in (`TZ`'s, else `/etc/localtime`'s, as
    `date` reads them; null when it has none) and its UTC offset in minutes now."""
    name: str | None = (os.environ.get("TZ") or "").lstrip(":") or None
    if name is None:
        try:
            target = os.readlink("/etc/localtime")
        except OSError:
            target = ""
        _, sep, rest = target.partition("zoneinfo/")
        name = rest if sep and rest else None
    zone = zone_of({"name": name}) if name else None
    if zone is UTC:
        name, zone = None, None  # a name this machine cannot resolve: the offset alone, read from the system
    now = (now or datetime.now(UTC)).astimezone(zone)
    off = now.utcoffset()
    return {"name": name, "offset": int(off.total_seconds() // 60) if off is not None else 0}


def resolve_when(text: str, zone: tzinfo) -> datetime:
    """A `--since` or `--until`: a local day (its midnight in `zone`) or an RFC 3339 instant, as UTC."""
    text = text.strip()
    if DAY.match(text):
        try:
            day = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{text!r} is not a day") from None
        return day.replace(tzinfo=zone).astimezone(UTC)
    got = instant(text)
    if got is None:
        raise ValueError(f"{text!r} is neither a local day (YYYY-MM-DD) nor an RFC 3339 instant with its offset")
    return got.astimezone(UTC)


def utc(at: datetime) -> str:
    """An instant as the index and the RPCs write it: RFC 3339, UTC, `Z`."""
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def local(at: str | None, zone: tzinfo) -> str:
    """An RPC's UTC instant as the headers and the `--list` table write it: `YYYY-MM-DD HH:MM` in the run's zone."""
    got = instant(at)
    return got.astimezone(zone).strftime("%Y-%m-%d %H:%M") if got is not None else "?"


# ── the records' listings ─────────────────────────────────────────────────────────────────────


@dataclass
class Record:
    seat: str
    id: str
    marks_errors: bool | None = None
    conversations: list[dict[str, Any]] = field(default_factory=list)  # the listing, after the skips
    error: str | None = None
    failed: str | None = None
    written: list[dict[str, Any]] = field(default_factory=list)  # the digest's index rows
    parts: list[str] = field(default_factory=list)
    bytes: int = 0


def own_conversation(call: Call, caller: str | None) -> str | None:
    """The calling session's own conversation: its record's `adapter_id`, None where there is no such record."""
    if not caller:
        return None
    try:
        records = call("list")
    except AgentError:
        return None
    for s in records or []:
        if s.get("id") == caller:
            return s.get("adapter_id") or None
    return None


# ── a record's parts ──────────────────────────────────────────────────────────────────────────


@dataclass
class _Unit:
    conv: dict[str, Any]
    head: bool = False  # a conversation's header (`continued` set on one a part repeats)
    continued: bool = False
    day: str = ""  # an entry's local day
    lines: list[str] = field(default_factory=list)  # an entry's lines as written
    prompt: bool = False


def header(conv: dict[str, Any], zone: tzinfo, continued: bool = False) -> str:
    first, last = local(conv.get("first_at"), zone), local(conv.get("last_at"), zone)
    tail = " (continued)" if continued else ""
    return f"## {conv.get('id')} · {conv.get('profile')} · {first} → {last}{tail}"


def entries(text: str) -> list[tuple[str | None, list[str]]]:
    """A reply's text as its entries, each with the day line written before it, if any: a line led by two
    spaces continues the entry before it, `=== <day> ===` is a day line, and any other line opens an entry."""
    out: list[tuple[str | None, list[str]]] = []
    day: str | None = None
    for line in text.split("\n") if text else []:
        if line.startswith("  ") and out:
            out[-1][1].append(line)
        elif line.startswith("=== ") and line.endswith(" ===") and len(line) > 8:
            day = line[4:-4]
        else:
            out.append((day, [line]))
            day = None
    return out


class Parts:
    """A record's text, split into parts as it is written (design §4.7): past the bound, a new part starts at a
    conversation's header, else, inside a conversation larger than a part, at the last prompt before the
    bound, else before the entry that passes it — never inside an entry, and a part always holds one. A part
    that starts inside a conversation repeats its header with *(continued)* and its day line. Only the part
    being written is held; the ones before it are on disk."""

    def __init__(self, out: Path, rid: str, bound: int, zone: tzinfo) -> None:
        self.out, self.rid, self.bound, self.zone = out, rid, bound, zone
        self.units: list[_Unit] = []
        self.size = 0
        self.last_day: str | None = None  # the last day line in the part being written, under its last header
        self.files: list[Path] = []
        self.lines: dict[str, int] = {}  # every line written per conversation, header lines left out
        self.bytes = 0
        self._started: set[str] = set()

    # the part as text, and what each unit adds to it

    def _render(self, units: list[_Unit], count: bool = False) -> str:
        rows: list[str] = []
        day: str | None = None
        for u in units:
            if u.head:
                rows.append(header(u.conv, self.zone, u.continued))
                day = None
                continue
            n = 0
            if u.day != day:
                rows.append(f"=== {u.day} ===")
                day, n = u.day, 1
            rows.extend(u.lines)
            if count:
                cid = str(u.conv.get("id"))
                self.lines[cid] = self.lines.get(cid, 0) + n + len(u.lines)
        return "".join(r + "\n" for r in rows)

    def _cost(self, u: _Unit) -> int:
        if u.head:
            return len((header(u.conv, self.zone, u.continued) + "\n").encode())
        body = sum(len((r + "\n").encode()) for r in u.lines)
        return body + (len(f"=== {u.day} ===\n".encode()) if u.day != self.last_day else 0)

    def _append(self, u: _Unit) -> None:
        self.size += self._cost(u)
        self.units.append(u)
        self.last_day = None if u.head else u.day

    def _reset(self, units: list[_Unit]) -> None:
        self.units, self.size, self.last_day = [], 0, None
        for u in units:
            self._append(u)

    # writing

    def add(self, conv: dict[str, Any], day: str, lines: list[str]) -> None:
        cid = str(conv.get("id"))
        if cid not in self._started:
            self._started.add(cid)
            self._append(_Unit(conv, head=True))
        u = _Unit(conv, day=day, lines=lines, prompt=bool(PROMPT.match(lines[0])))
        while any(not x.head for x in self.units) and self.size + self._cost(u) > self.bound:
            self._split(u)
        self._append(u)

    def _split(self, incoming: _Unit) -> None:
        units = self.units
        first = next(i for i, x in enumerate(units) if not x.head)  # the part's first entry stays in it
        at = len(units)
        heads = [i for i in range(first + 1, len(units)) if units[i].head]
        if heads and self._fits(units[heads[-1] :] + [incoming]):
            at = heads[-1]
        else:
            lo = heads[-1] if heads else first
            prompts = [i for i in range(max(lo, first) + 1, len(units)) if units[i].prompt]
            if prompts:
                at = prompts[-1]
        while at > first + 1 and units[at - 1].head:
            at -= 1  # a header is never left at a part's end with no line under it
        self._write(units[:at])
        rest = units[at:]
        if not rest or not rest[0].head:
            conv = (rest[0] if rest else incoming).conv
            rest = [_Unit(conv, head=True, continued=True), *rest]
        self._reset(rest)

    def _fits(self, units: list[_Unit]) -> bool:
        return len(self._render(units).encode()) <= self.bound

    def _write(self, units: list[_Unit]) -> None:
        path = self.out / f"{self.rid}.{len(self.files) + 1}.txt"
        data = self._render(units, count=True).encode()
        path.write_bytes(data)
        self.files.append(path)
        self.bytes += len(data)

    def close(self) -> list[Path]:
        """Write the last part: `<record id>.txt` when it is the only one."""
        if any(not u.head for u in self.units):
            if self.files:
                self._write(self.units)
            else:
                path = self.out / f"{self.rid}.txt"
                data = self._render(self.units, count=True).encode()
                path.write_bytes(data)
                self.files.append(path)
                self.bytes += len(data)
        self.units = []
        return self.files

    def discard(self) -> None:
        for p in self.files:
            p.unlink(missing_ok=True)
        self.files, self.bytes, self.lines, self.units = [], 0, {}, []


def clear_record(out: Path, rid: str) -> None:
    """Remove the record's own `<record id>.txt` and `<record id>.<n>.txt` an earlier run left in `out`."""
    mine = re.compile(re.escape(rid) + r"(\.\d+)?\.txt")
    for p in out.iterdir() if out.is_dir() else []:
        if mine.fullmatch(p.name) and p.is_file():
            p.unlink()


def digest_record(
    call: Call,
    r: Record,
    *,
    out: Path,
    since: datetime,
    until: datetime,
    zone_arg: dict[str, Any],
    bound: int,
) -> None:
    """Read each of `r`'s listed conversations whole, `next` after `next`, into its parts. A read that fails
    ends the record there: its parts are removed and it carries the `error` and the `failed` conversation."""
    zone = zone_of(zone_arg)
    parts = Parts(out, r.id, bound, zone)
    for conv in r.conversations:
        cid = str(conv.get("id"))
        at, skip = utc(since), 0
        last_day: str | None = None  # the last day line written for this conversation
        try:
            while True:
                got = call(
                    "transcript_digest",
                    id=r.id,
                    conversation=cid,
                    profile=conv.get("profile"),
                    since=at,
                    until=utc(until),
                    zone=zone_arg,
                    skip=skip,
                    _timeout=WAIT,
                )
                for day, lines in entries(str(got.get("text") or "")):
                    last_day = day or last_day or ""
                    parts.add(conv, last_day, lines)
                nxt = got.get("next")
                if not nxt:
                    break
                step = (str(nxt.get("at") or ""), int(nxt.get("skip") or 0))
                if not step[0] or step == (at, skip):
                    raise AgentError(f"the host's next for {cid} does not move on: {nxt!r}")
                at, skip = step
        except AgentError as e:
            parts.discard()
            r.error, r.failed = str(e), cid
            r.conversations, r.marks_errors, r.written = [], None, []
            return
    parts.close()
    r.parts = [str(p) for p in parts.files]
    r.bytes = parts.bytes
    r.written = [
        {k: c.get(k) for k in ("id", "profile", "first_at", "last_at")} | {"lines": parts.lines[str(c.get("id"))]}
        for c in r.conversations
        if str(c.get("id")) in parts.lines
    ]


def run(
    call: Call,
    records: list[tuple[str, str]],
    *,
    since: datetime,
    until: datetime,
    zone: dict[str, Any],
    out: Path | None,
    skip: list[str],
    own: str | None,
    bound: int = PART_BYTES,
    list_only: bool = False,
) -> dict[str, Any]:
    """The run: the `--list` listing, or the digest and its index (design §4.7 *Feedback*)."""
    leave = set(skip) | ({own} if own else set())
    index_records: list[dict[str, Any]] = []
    claimed: set[str] = set()
    cleared: set[str] = set()
    for seat, rid in records:
        r = Record(seat=seat, id=rid)
        if not list_only and out is not None and rid not in cleared:
            cleared.add(rid)  # a record named twice keeps what its first reading wrote
            clear_record(out, rid)
        try:
            got = call("conversations", id=rid, since=utc(since), until=utc(until), _timeout=WAIT)
        except AgentError as e:
            r.error = str(e)
        else:
            rows = list(got.get("conversations") or [])
            r.marks_errors = got.get("marks_errors")
            r.conversations = [c for c in rows if c.get("id") not in leave and c.get("id") not in claimed]
            if not list_only and out is not None:
                digest_record(call, r, out=out, since=since, until=until, zone_arg=zone, bound=bound)
            if r.error is None:
                claimed.update(str(c.get("id")) for c in rows)
            elif r.failed:
                claimed.add(r.failed)  # no later record reads the conversation whose read failed
        if list_only:
            convs = [{k: c.get(k) for k in ("id", "profile", "first_at", "last_at", "size")} for c in r.conversations]
            index_records.append(
                {
                    "seat": r.seat,
                    "id": r.id,
                    "marks_errors": r.marks_errors,
                    "conversations": convs,
                    "error": r.error,
                    "failed": None,
                }
            )
        else:
            index_records.append(
                {
                    "seat": r.seat,
                    "id": r.id,
                    "marks_errors": r.marks_errors,
                    "conversations": r.written,
                    "parts": r.parts,
                    "bytes": r.bytes,
                    "error": r.error,
                    "failed": r.failed,
                }
            )
    return {"since": utc(since), "until": utc(until), "records": index_records}


def list_table(index: dict[str, Any], zone: tzinfo) -> list[str]:
    """`--list`'s rows: record, conversation, profile, span in the run's zone, size; a failed record's error."""
    rows: list[str] = []
    for r in index["records"]:
        if r.get("error"):
            rows.append(f"{r['id']}  error: {r['error']}")
            continue
        if not r["conversations"]:
            rows.append(f"{r['id']}  (none in the window)")
        for c in r["conversations"]:
            span = f"{local(c.get('first_at'), zone)} → {local(c.get('last_at'), zone)}"
            rows.append(f"{r['id']}  {c.get('id')}  {c.get('profile')}  {span}  {c.get('size')}")
    return rows


def summary(index: dict[str, Any]) -> list[str]:
    """The digest's lines without `--json`: what each record wrote, or why it wrote nothing."""
    rows: list[str] = []
    for r in index["records"]:
        if r.get("error"):
            where = f" (reading {r['failed']})" if r.get("failed") else ""
            rows.append(f"{r['id']}: error{where} — {r['error']}")
        elif not r["parts"]:
            rows.append(f"{r['id']}: no conversation writes a line in the window")
        else:
            n = len(r["conversations"])
            rows.append(f"{r['id']}: {n} conversation{'s' * (n != 1)}, {r['bytes']} bytes in {', '.join(r['parts'])}")
    return rows
