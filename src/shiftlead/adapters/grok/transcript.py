"""Grok Build's session log as the neutral shape (design §4.3 *The third adapter: Grok Build*, *Reads*, TD-1637).

A session's log is `updates.jsonl` in its own directory, `<GROK_HOME>/sessions/<the cwd, encoded>/<id>/`, one
ACP session-update event a line (`{timestamp, method, params: {sessionId, update: {sessionUpdate, …}}}`), the
tool writing each message once, whole; `summary.json` beside it holds the model (`current_model_id`). The
directory of the cwd is the tool's own encoding (a slug and a hash, with a `.cwd` file, for a long path), so the
log is found by the session id's own directory, never by encoding the path. Read on 1.0.77. Only here are the
tool's field names known — `sessionUpdate`, `content`, `toolCallId`, `rawInput`, `rawOutput` — and none leaves
this module.

What each update becomes:

- `user_message_chunk`: a **prompt**;
- `agent_thought_chunk`: a **thought**; `agent_message_chunk`: **text** — a chunk following one of its own kind
  with nothing between joins it, should the tool ever stream one message in parts;
- `tool_call`: a **tool**, its call line from `rawInput`; the `tool_call_update` that completes it (`status`)
  carries its **result**, the update's text, else the terminal's `output_for_prompt`;

and every other update (`hook_execution`, `turn_completed`, `current_mode_update`, a tool call's interim
updates) is skipped. A failed call is not marked (`marks_errors` is not declared): no capture holds one yet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc.adapters import Transcript, TranscriptEntry

LOG = "updates.jsonl"
SUMMARY = "summary.json"
RESULT_CAP = 20_000  # characters of one tool result carried (the reader folds it anyway)
CALL_CAP = 200  # characters of a call's one line
CALL_KEYS = ("command", "path", "file_path", "pattern", "query", "url", "prompt", "description")
JOINED = {"agent_thought_chunk": "thought", "agent_message_chunk": "text"}
DONE = frozenset({"completed", "failed"})


def sessions_root(home: Path) -> Path:
    return home / "sessions"


def find(root: Path, session_id: str) -> Path | None:
    """`<root>/*/<session_id>/updates.jsonl`, the newest where two cwds hold one; None for an id that could name
    another directory (a separator, a glob character, a dot path) or has no log."""
    if not session_id or any(c in session_id for c in "/\\*?[]") or session_id in (".", ".."):
        return None
    try:
        found = [p for p in root.glob(f"*/{session_id}/{LOG}") if p.is_file()]
    except OSError:
        return None
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def model(path: Path) -> str | None:
    """The model the session runs, from `summary.json` beside its log; None where it is missing or names none."""
    try:
        doc = json.loads((path.parent / SUMMARY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    got = doc.get("current_model_id") if isinstance(doc, dict) else None
    return str(got) if isinstance(got, str) and got else None


def _at(rec: dict) -> str | None:
    ts = rec.get("timestamp")
    if not isinstance(ts, int | float) or isinstance(ts, bool):
        return None
    try:
        return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _update(rec: dict) -> dict:
    params = rec.get("params")
    up = params.get("update") if isinstance(params, dict) else None
    return up if isinstance(up, dict) else {}


def _text(content: Any) -> str:
    """An update's text: a `{type: text, text}` block, or a list of `{type: content, content: {…}}` wrappers."""
    if isinstance(content, dict):
        if isinstance(content.get("content"), dict):
            return _text(content["content"])
        return str(content.get("text") or "") if content.get("type") == "text" else ""
    if isinstance(content, list):
        return "\n".join(t for t in (_text(c) for c in content) if t)
    return ""


def _call_line(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    value = next((args[k] for k in CALL_KEYS if isinstance(args.get(k), str) and args[k].strip()), None)
    if value is None:
        qs = args.get("questions")
        if isinstance(qs, list) and qs and isinstance(qs[0], dict) and isinstance(qs[0].get("question"), str):
            value = qs[0]["question"]
        else:
            value = json.dumps(args, ensure_ascii=False) if args else ""
    line = str(value).strip().splitlines()[0] if str(value).strip() else ""
    return line[:CALL_CAP]


def _result(up: dict) -> str:
    text = _text(up.get("content"))
    if not text.strip():
        raw = up.get("rawOutput")
        text = str(raw.get("output_for_prompt") or "") if isinstance(raw, dict) else ""
    return text[:RESULT_CAP]


def _is_prompt(rec: dict) -> bool:
    up = _update(rec)
    return up.get("sessionUpdate") == "user_message_chunk" and bool(_text(up.get("content")).strip())


def _entries(records: list[dict]) -> tuple[list[TranscriptEntry], int]:
    """These updates as entries, oldest first, and how many prompts."""
    out: list[TranscriptEntry] = []
    calls: dict[str, TranscriptEntry] = {}
    prompts = 0
    last: str | None = None  # the kind of the last chunk joined, while nothing else came between
    for rec in records:
        up = _update(rec)
        kind = up.get("sessionUpdate")
        at = _at(rec)
        if kind == "user_message_chunk":
            text = _text(up.get("content"))
            if text.strip():
                prompts += 1
                out.append(TranscriptEntry(kind="prompt", at=at, text=text))
            last = None
        elif kind in JOINED:
            text = _text(up.get("content"))
            if not text:
                continue
            if last == kind and out:
                out[-1].text += text
            else:
                out.append(TranscriptEntry(kind=JOINED[kind], at=at, text=text))
            if JOINED[kind] == "thought":
                out[-1].lines = len(out[-1].text.splitlines())
            last = kind
        elif kind == "tool_call":
            entry = TranscriptEntry(
                kind="tool", at=at, name=str(up.get("title") or ""), call=_call_line(up.get("rawInput"))
            )
            if up.get("toolCallId"):
                calls[str(up["toolCallId"])] = entry
            out.append(entry)
            last = None
        else:
            if kind == "tool_call_update" and up.get("status") in DONE:
                call = calls.get(str(up.get("toolCallId") or ""))
                if call is not None:
                    call.result = _result(up)
            last = None
    return out, prompts


def _lines(data: bytes, end: int) -> list[tuple[int, dict]]:
    """Each parsed record before byte `end` with its offset; a line that does not parse is skipped."""
    out, offset = [], 0
    for line in data[:end].splitlines(keepends=True):
        if line.strip():
            try:
                rec = json.loads(line)
            except ValueError:
                rec = None
            if isinstance(rec, dict):
                out.append((offset, rec))
        offset += len(line)
    return out


def read(path: Path, *, before: int | None = None, turns: int = 20, raw: bool = False) -> Transcript:
    """The last `turns` prompts among the records starting before byte `before` of `path`, and every record after
    each of them up to it, as neutral entries; `before` in the answer is the first of those records' offset, None
    when the read reaches the file's start. With `raw`, the last `turns` lines before `before`, as written."""
    data = path.read_bytes()
    size = len(data)
    end = size if before is None else max(0, min(int(before), size))
    turns = max(1, int(turns))
    if raw:
        lines, offset = [], 0
        for line in data[:end].splitlines(keepends=True):
            lines.append((offset, line))
            offset += len(line)
        lines = [(o, b) for o, b in lines if b.strip()][-turns:]
        start = lines[0][0] if lines else end
        return Transcript(
            path=str(path),
            size=size,
            first_at=_first_at(data),
            before=start or None,
            raw="\n".join(b.decode("utf-8", "replace").rstrip("\n") for _o, b in lines),
        )
    kept = _lines(data, end)
    start, seen = 0, 0
    for i in range(len(kept) - 1, -1, -1):
        if _is_prompt(kept[i][1]):
            seen += 1
            start = i
            if seen >= turns:
                break
    if not any(_is_prompt(rec) for _off, rec in kept[:start]):
        start = 0  # nothing a person typed is earlier: the read reaches the file's start
    window = kept[start:]
    entries, prompts = _entries([rec for _off, rec in window])
    last_at = next((a for _o, r in reversed(window) if (a := _at(r))), None)
    return Transcript(
        path=str(path),
        size=size,
        first_at=_first_at(data),
        last_at=last_at,
        turns=prompts,
        before=window[0][0] if window and start > 0 else None,
        entries=entries,
    )


def _first_at(data: bytes) -> str | None:
    for _off, rec in _lines(data, min(len(data), 64 * 1024)):
        if at := _at(rec):
            return at
    return None
