"""A conversation's digest (design §4.7 *Feedback*, TD-1491): the `transcript_digest` read's text.

`digest` pages an adapter's `read_transcript` back from the file's end until it holds a dated entry older
than the window, gives each entry an instant (the latest of its own and those before it, so a continued
read neither repeats nor loses an entry), keeps the window's entries, and writes them one line form per
kind, each led by its local `HH:MM` and a mark: `>` a prompt, `<` the assistant's text, `✗` a failed call,
`·` a run of other calls or a subagent, `—` a compaction. A thought writes nothing. A reply that would pass
`REPLY_BYTES` as JSON ends at the last prompt before that point, else the last entry, and says where the
next reply starts (`next`). Nothing here knows a tool: it reads the neutral entries (§4.3).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sessionorc.adapters import Transcript, TranscriptEntry, instant

PAGE_TURNS = 100  # prompts one page of the backward read asks for
REPLY_BYTES = 4 * 1024 * 1024  # a reply as the JSON line it is sent as: half the RPC's frame
REPLY_SLACK = 4096  # what the reply's other fields and the last run's line may add to the text's own bytes
ENTRY_BYTES = 64 * 1024  # any one entry as written
CALL_CHARS = 120  # a failed call's `<call>`
RESULT_LINES = 3  # a failed call's result: its first lines, or
RESULT_CHARS = 300  # its first characters, whichever is shorter
PROMPT_LINES = 3  # a prompt's first lines
CUT = " (cut)"
EMPTY: dict[str, Any] = {"text": "", "lines": 0, "next": None}


def zone_of(zone: dict | None) -> tzinfo:
    """The caller's zone (`{name, offset}`): the name where this host resolves it, else the offset in minutes,
    else UTC."""
    zone = zone if isinstance(zone, dict) else {}
    name = zone.get("name")
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    offset = zone.get("offset")
    if isinstance(offset, int) and not isinstance(offset, bool) and -24 * 60 < offset < 24 * 60:
        return timezone(timedelta(minutes=offset))
    return UTC


@dataclass
class _Timed:
    entry: TranscriptEntry
    at: datetime  # the entry's instant: the latest of its own and those before it
    raw: str  # that instant as written, at its own precision


def read_back(read: Callable[[int | None], Transcript | None], since: datetime) -> list[TranscriptEntry] | None:
    """The entries `read` gives paging back by `before` from the file's end until a page holds a dated entry
    older than `since` or the file's start is reached — one page more where that page opens undated, so its
    first entries take their instant from the entries before them; None when the first read finds no file."""
    entries: list[TranscriptEntry] = []
    before: int | None = None
    first, extra = True, False
    while True:
        t = read(before)
        if t is None:
            return None if first else entries
        first = False
        entries = list(t.entries) + entries
        older = extra or any((at := instant(e.at)) is not None and at < since for e in t.entries)
        if older and not extra and t.entries and instant(t.entries[0].at) is None and t.before is not None:
            extra = True
        elif older or t.before is None or (before is not None and t.before >= before):
            return entries
        before = t.before


def timed(entries: list[TranscriptEntry], first_at: str | None) -> list[_Timed]:
    """Each entry with its instant (design §4.7): an undated one takes the instant before it (the conversation's
    `first_at` when it is first), and one dated earlier than the entry before it takes that entry's."""
    out: list[_Timed] = []
    cur, raw = instant(first_at), first_at or ""
    if cur is None:
        cur, raw = datetime.min.replace(tzinfo=UTC), ""
    for e in entries:
        at = instant(e.at)
        if at is not None and at > cur:
            cur, raw = at, str(e.at)
        out.append(_Timed(e, cur, raw))
    return out


def _cap(block: str) -> str:
    """An entry's written block cut to `ENTRY_BYTES`, at a character boundary, ending *(cut)*."""
    data = block.encode("utf-8")
    if len(data) <= ENTRY_BYTES:
        return block
    room = ENTRY_BYTES - len(CUT.encode("utf-8"))
    return data[:room].decode("utf-8", errors="ignore") + CUT


def _lines(lead: str, text: str) -> str:
    """A first line led by `lead`, further lines indented two spaces."""
    rows = text.split("\n") or [""]
    return "\n".join([f"{lead} {rows[0]}".rstrip(), *(f"  {r}" for r in rows[1:])])


def _call(e: TranscriptEntry) -> str:
    call = e.call if len(e.call) <= CALL_CHARS else e.call[: CALL_CHARS - 1] + "…"
    return f"{e.name}({call})"


def _result(e: TranscriptEntry) -> str:
    if e.result is None:
        return "(no result)"
    rows = e.result.split("\n")[:RESULT_LINES]
    text = "\n".join(rows)
    return text if len(text) <= RESULT_CHARS else text[: RESULT_CHARS - 1] + "…"


def _block(e: TranscriptEntry, hhmm: str) -> str | None:
    """An entry kept as a line of its own, or None for one folded into a run (an ordinary call) or left out
    (a thought)."""
    if e.kind == "prompt":
        rows = e.text.split("\n")
        more = f"\n(+{len(rows) - PROMPT_LINES} lines)" if len(rows) > PROMPT_LINES else ""
        return _lines(f"{hhmm} >", "\n".join(rows[:PROMPT_LINES]) + more)
    if e.kind == "text":
        return _lines(f"{hhmm} <", e.text)
    if e.kind == "compaction":
        return f"{hhmm} — compacted —"
    if e.kind == "sidechain":
        return f"{hhmm} · subagent, {e.count} entries"
    if e.kind == "tool":
        if e.sidechain is not None:
            n = e.sidechain.count
            if e.error:
                return _lines(f"{hhmm} ✗", f"{_call(e)} → {_result(e)}, subagent {n} entries")
            return f"{hhmm} · subagent {_call(e)}, {n} entries"
        if e.error:
            return _lines(f"{hhmm} ✗", f"{_call(e)} → {_result(e)}")
    return None


def _folded(e: TranscriptEntry) -> bool:
    return e.kind == "tool" and e.sidechain is None and not e.error


def _run_line(run: list[_Timed], zone: tzinfo) -> str:
    counts = Counter(t.entry.name for t in run)
    order = sorted(counts, key=lambda n: (-counts[n], [t.entry.name for t in run].index(n)))
    hhmm = run[0].at.astimezone(zone).strftime("%H:%M")
    return f"{hhmm} · {len(run)} calls ({', '.join(f'{n} {counts[n]}' for n in order)})"


def render(window: list[_Timed], zone: tzinfo) -> tuple[list[str], list[int]]:
    """The window's lines, and for each entry the text's byte length once it is written (a run's line counted
    at its first call): what the cut reads."""
    out: list[str] = []
    sizes: list[int] = []
    run: list[_Timed] = []
    day: str | None = None
    total = 0

    def put(block: str, at: datetime) -> None:
        nonlocal day, total
        d = at.astimezone(zone).strftime("%Y-%m-%d")
        if d != day:
            day = d
            out.append(f"=== {d} ===")
            total += len(json.dumps(out[-1])) - 1
        out.append(block)
        total += len(json.dumps(block)) - 1  # as the JSON escapes it, its newline counted

    def flush() -> None:
        if run:
            put(_run_line(run, zone), run[0].at)
            run.clear()

    for t in window:
        if _folded(t.entry):
            if not run:
                total += 80  # the run's line, written at its end, counted at its first call
            run.append(t)
        else:
            block = _block(t.entry, t.at.astimezone(zone).strftime("%H:%M"))
            if block is not None:
                flush()
                put(_cap(block), t.at)
        sizes.append(total)
    flush()
    return out, sizes


def digest(
    read: Callable[[int | None], Transcript | None],
    *,
    first_at: str | None | Callable[[], str | None],
    since: datetime,
    until: datetime,
    zone: tzinfo,
    skip: int = 0,
    limit: int = REPLY_BYTES,
) -> dict[str, Any] | None:
    """`{text, lines, next}` for the window `[since, until)` of the conversation `read` pages back through
    (`read(before)` → a page of `PAGE_TURNS` prompts), less the first `skip` entries at the instant `since`.
    None when the conversation has no file."""
    entries = read_back(read, since)
    if entries is None:
        return None
    if callable(first_at):
        first_at = first_at()  # the conversation's, known once the first page is read
    window = [t for t in timed(entries, first_at) if since <= t.at < until]
    at_since = sum(1 for t in window if t.at == since)
    window = window[min(max(0, skip), at_since) :]
    if not window:
        return dict(EMPTY)
    _out, sizes = render(window, zone)
    end = len(window)
    room = limit - REPLY_SLACK
    if sizes[-1] > room:
        end = next(i for i, s in enumerate(sizes) if s > room)  # the entry that passes the point
        prompt = max((i for i in range(1, end) if window[i].entry.kind == "prompt"), default=None)
        end = max(1, prompt if prompt is not None else end)
    out, _sizes = render(window[:end], zone)
    nxt = None
    if end < len(window):
        first_out = window[end]
        same = [i for i, t in enumerate(window) if t.at == first_out.at]
        consumed = sum(1 for i in same if i < end) + (min(max(0, skip), at_since) if first_out.at == since else 0)
        nxt = {"at": first_out.raw, "skip": consumed}
    if not out:
        return {"text": "", "lines": 0, "next": nxt}
    text = "\n".join(out)
    return {"text": text, "lines": text.count("\n") + 1, "next": nxt}
