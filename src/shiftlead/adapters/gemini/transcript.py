"""Gemini CLI's chats as the neutral shape (design §4.3 *The second adapter: Gemini CLI*, *Reads*, TD-786).

A session's chat is one JSON object per line under `<home>/.gemini/tmp/<slug>/chats/`, in a file named
`session-<UTC minute>[-<n>]-<id[:8]>.jsonl` whose first record names the session (`sessionId`); a
subagent's chats are under `chats/<parent id>/`. **A record is written again under its id as it grows**,
and patch records amend earlier ones — `$set` the metadata (or every message at once), `$patch` a
message's content and its tool calls' results, `$rewindTo` drops a message and everything after it — so
the reader replays the file as the tool's own reader does (0.64.0's `createJsonlRecordAccumulator`)
before mapping `user` and `gemini` records to neutral entries. Only here are the tool's field names
known — `type`, `content`, `thoughts`, `toolCalls`, `functionResponse`, `tokens` — and none of them
leaves this module.

What each message becomes:

- a `user` record's text parts: a **prompt** — unless it is the tool's own `<session_context>` preamble,
  which no person typed and which is left out, as Claude Code's start context is;
- a `user` record's `functionResponse` parts: the **result** of the tool call they answer, by its id;
- a `gemini` record: its thoughts as one **thought**, its text as **text**, each of its tool calls as a
  **tool** with the result the call carries;

and every other record (`info`, `warning`, `error`) is skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sessionorc.adapters import Link, Transcript, TranscriptEntry
from shiftlead.adapters.claude_code.transcript import urls_in

PREAMBLE = "<session_context>"  # the tool's own first user record: the workspace it set up, not a prompt
HEAD = 64 * 1024  # bytes read from a file's start for its first record
TAIL = 256 * 1024  # bytes read from the end for the last turn (`context`, `model_in_use`)
RESULT_CAP = 20_000  # characters of one tool result carried (the reader folds it anyway)
CALL_CAP = 200  # characters of a call's one line
# which argument is the call's line, in order, as the pane draws `Shell(<command>)` or `ReadFile(<path>)`
CALL_KEYS = ("command", "file_path", "absolute_path", "dir_path", "path", "pattern", "url", "query", "prompt")
WINDOW = 1_048_576  # the tool's own token limit for the Gemini models (design §4.3 `context`)
GEMMA_WINDOW = 256_000  # and for a Gemma one


def chats_root(home: Path) -> Path:
    """Where the tool keeps every project's chats under a home (`GEMINI_CLI_HOME`)."""
    return home / ".gemini" / "tmp"


def session_of(path: Path) -> str | None:
    """The `sessionId` of a chat's first record, None when it names none."""
    try:
        with path.open("rb") as f:
            head = f.read(HEAD)
        d = json.loads(head.split(b"\n", 1)[0])
    except (OSError, ValueError):
        return None
    sid = d.get("sessionId") if isinstance(d, dict) else None
    return sid if isinstance(sid, str) else None


def find(root: Path, session_id: str) -> Path | None:
    """The session's chat under `root` (design §4.3 `transcript_path`): a top-level file of a project's
    `chats/` named for the id's first eight characters whose first record names the id — a subagent's,
    under `chats/<parent id>/`, never — the newest where several do. None when there is none."""
    if not session_id or any(c in session_id for c in "*?[]/"):
        return None
    found = [p for p in root.glob(f"*/chats/session-*-{session_id[:8]}.jsonl") if session_of(p) == session_id]
    if not found:
        return None
    try:
        return max(found, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


def cwd_of(path: Path) -> str:
    """The directory a chat's project is (its `.project_root`, beside `chats/`), "" when unrecorded."""
    project = path.parent
    while project.name != "chats" and project != project.parent:
        project = project.parent
    try:
        return (project.parent / ".project_root").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def replay(data: bytes) -> tuple[dict[str, tuple[int, dict]], dict]:
    """The file's messages after every patch, in the tool's order — `{id: (offset of its first line,
    record)}` — and its metadata, replayed as the tool's reader does: a message written again replaces
    the earlier one in its place, `$rewindTo` drops the message it names and every later one (all of
    them when it names none), `$patch` amends a message's content and its tool calls' results, removes
    and reorders, and `$set` merges metadata, its `messages` replacing every message."""
    messages: dict[str, tuple[int, dict]] = {}
    meta: dict = {}
    offset = 0
    for line in data.splitlines(keepends=True):
        at, offset = offset, offset + len(line)
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if isinstance(d.get("$rewindTo"), str):
            ids = list(messages)
            cut = ids.index(d["$rewindTo"]) if d["$rewindTo"] in messages else 0
            for mid in ids[cut:]:
                del messages[mid]
        elif isinstance(d.get("$patch"), dict):
            _patch(messages, d["$patch"])
        elif isinstance(d.get("id"), str):
            first = messages[d["id"]][0] if d["id"] in messages else at
            messages[d["id"]] = (first, d)
        elif isinstance(d.get("$set"), dict):
            if isinstance(d["$set"].get("messages"), list):
                messages = {m["id"]: (at, m) for m in d["$set"]["messages"] if isinstance(m, dict) and _is_message(m)}
            meta.update({k: v for k, v in d["$set"].items() if k != "messages"})
        elif isinstance(d.get("sessionId"), str):
            meta.update({k: v for k, v in d.items() if k != "messages"})
    return messages, meta


def _is_message(d: dict) -> bool:
    return isinstance(d.get("id"), str) and "$patch" not in d


def _patch(messages: dict[str, tuple[int, dict]], p: dict) -> None:
    for update in [p, *(p.get("updates") or [])]:
        if not isinstance(update, dict) or not isinstance(update.get("id"), str) or update["id"] not in messages:
            continue
        rec = messages[update["id"]][1]
        if update.get("content") is not None:
            rec["content"] = update["content"]
        if isinstance(update.get("toolCalls"), list) and isinstance(rec.get("toolCalls"), list):
            for tp in update["toolCalls"]:
                tc = next((t for t in rec["toolCalls"] if isinstance(tp, dict) and t.get("id") == tp.get("id")), None)
                if tc is not None and "result" in tp:
                    tc["result"] = tp["result"]
    for mid in p.get("removeIds") or []:
        if isinstance(mid, str):
            messages.pop(mid, None)
    if isinstance(p.get("orderIds"), list):
        ordered = [i for i in dict.fromkeys(p["orderIds"]) if isinstance(i, str) and i in messages]
        rest = [i for i in messages if i not in set(ordered)]
        reordered = {i: messages[i] for i in [*rest, *ordered]}
        messages.clear()
        messages.update(reordered)


def _parts(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    return [p for p in content if isinstance(p, dict)] if isinstance(content, list) else []


def _text(content: Any) -> str:
    """The text parts of a content, a thought part (which a resume's patch writes into it) left out."""
    return "".join(str(p["text"]) for p in _parts(content) if isinstance(p.get("text"), str) and not p.get("thought"))


def _response_text(part: dict) -> str:
    """A `functionResponse` part's output as the pane would show it: its `output`, else its response."""
    resp = (part.get("functionResponse") or {}).get("response")
    out = resp.get("output") if isinstance(resp, dict) else None
    if not isinstance(out, str):
        out = "" if resp is None else json.dumps(resp, ensure_ascii=False)
    return out[:RESULT_CAP]


def _call_line(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    value = next((args[k] for k in CALL_KEYS if isinstance(args.get(k), str) and args[k].strip()), None)
    if value is None:
        value = json.dumps(args, ensure_ascii=False) if args else ""
    line = str(value).strip().splitlines()[0] if str(value).strip() else ""
    return line[:CALL_CAP]


def _is_prompt(rec: dict) -> bool:
    text = _text(rec.get("content"))
    return rec.get("type") == "user" and bool(text.strip()) and not text.lstrip().startswith(PREAMBLE)


def _entries(records: list[dict]) -> tuple[list[TranscriptEntry], int]:
    """These messages as entries, oldest first, and how many prompts."""
    out: list[TranscriptEntry] = []
    calls: dict[str, TranscriptEntry] = {}
    prompts = 0
    for rec in records:
        at = str(rec["timestamp"]) if rec.get("timestamp") else None
        kind = rec.get("type")
        if kind == "user":
            for part in _parts(rec.get("content")):
                if isinstance(part.get("functionResponse"), dict):
                    call = calls.get(str(part["functionResponse"].get("id") or ""))
                    if call is not None:
                        call.result = _response_text(part)
            if _is_prompt(rec):
                prompts += 1
                out.append(TranscriptEntry(kind="prompt", at=at, text=_text(rec.get("content"))))
            continue
        if kind != "gemini":
            continue
        thoughts = [t for t in rec.get("thoughts") or [] if isinstance(t, dict)]
        thought = "\n\n".join(
            "\n".join(s for s in (str(t.get("subject") or ""), str(t.get("description") or "")) if s) for t in thoughts
        ).strip()
        if thought:
            out.append(TranscriptEntry(kind="thought", at=at, text=thought, lines=len(thought.splitlines())))
        text = _text(rec.get("content"))
        if text.strip():
            out.append(TranscriptEntry(kind="text", at=at, text=text))
        for tc in rec.get("toolCalls") or []:
            if not isinstance(tc, dict):
                continue
            entry = TranscriptEntry(kind="tool", at=at, name=str(tc.get("name") or ""), call=_call_line(tc.get("args")))
            results = [p for p in _parts(tc.get("result")) if isinstance(p.get("functionResponse"), dict)]
            if results:
                entry.result = "\n".join(_response_text(p) for p in results)
            calls[str(tc.get("id") or "")] = entry
            out.append(entry)
    return out, prompts


def read(path: Path, *, before: int | None = None, turns: int = 20, raw: bool = False) -> Transcript:
    """The last `turns` prompts among the messages whose first line is before byte `before` of `path`, and
    every message after each of them up to it, as neutral entries; `before` in the answer is the first of
    those messages' offset, None when no message is earlier. With `raw`, the last `turns` lines before
    `before`, as the file has them. The file is replayed whole: a patch may amend any earlier message."""
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
    messages, meta = replay(data)
    kept = [(off, rec) for off, rec in messages.values() if off < end]
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
    last_at = next((str(r["timestamp"]) for _o, r in reversed(window) if r.get("timestamp")), None)
    return Transcript(
        path=str(path),
        size=size,
        first_at=str(meta.get("startTime") or "") or _first_at(data),
        last_at=last_at,
        turns=prompts,
        before=window[0][0] if window and start > 0 else None,
        entries=entries,
    )


def _first_at(data: bytes) -> str | None:
    for line in data[:HEAD].splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and (at := d.get("startTime") or d.get("timestamp")):
            return str(at)
    return None


def last_turns(path: Path):
    """The file's `gemini` records that carry tokens, newest first, from its last `TAIL` bytes: the one
    read `context` and `model_in_use` share."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - TAIL))
            chunk = f.read()
    except OSError:
        return
    for line in reversed(chunk.splitlines()):
        if b'"gemini"' not in line or b'"tokens"' not in line:
            continue
        try:
            d = json.loads(line)  # the tail's first line may be a fragment: it just fails
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("type") == "gemini" and isinstance(d.get("tokens"), dict):
            yield d


def window_for(model: str) -> int:
    return GEMMA_WINDOW if model.lower().startswith("gemma") else WINDOW


def _count(tokens: dict, key: str) -> int:
    v = tokens.get(key)
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) and v > 0 else 0


def context(path: Path) -> dict | None:
    """`{tokens, at, window}` from the last turn: the prompt it sent (`tokens.input`, which counts its
    cached tokens), stamped with the record's time, the window the tool's own for its model."""
    for d in last_turns(path):
        tokens = _count(d["tokens"], "input")
        if tokens > 0:
            return {"tokens": tokens, "at": d.get("timestamp"), "window": window_for(str(d.get("model") or ""))}
    return None


def model(path: Path) -> str | None:
    return next((str(d["model"]) for d in last_turns(path) if d.get("model")), None)


def _record_urls(d: dict) -> list[str]:
    """The URLs one message printed: a `gemini` record's text and its calls' results, a `user` record's
    function responses. A person's prompt, a thought and a call's arguments hold none."""
    texts: list[str] = []
    if d.get("type") == "gemini":
        texts.append(_text(d.get("content")))
        for tc in d.get("toolCalls") or []:
            if isinstance(tc, dict):
                texts += [
                    _response_text(p) for p in _parts(tc.get("result")) if isinstance(p.get("functionResponse"), dict)
                ]
    elif d.get("type") == "user":
        texts += [_response_text(p) for p in _parts(d.get("content")) if isinstance(p.get("functionResponse"), dict)]
    return [u for t in texts for u in urls_in(t)]


def _whole(path: Path, cursor: int) -> tuple[bytes, int, int]:
    """The file's whole lines past `cursor` (from 0 when the cursor is past its end: the tool rewrote it),
    where they start, and the cursor after the last of them. Raises OSError."""
    with path.open("rb") as f:
        size = f.seek(0, 2)
        start = cursor if 0 <= cursor <= size else 0
        f.seek(start)
        data = f.read(size - start)
    whole = data.rfind(b"\n") + 1  # a line still being written is read next time
    return data[:whole], start, start + whole


def links(path: Path, cursor: int = 0) -> tuple[list[Link], int]:
    """The URLs the chat printed past byte `cursor`, oldest first, a message written again read once at its
    last line, and the cursor after the last whole line. Raises OSError when the file cannot be read."""
    data, _start, after = _whole(path, cursor)
    last: dict[str, dict] = {}
    for line in data.splitlines():
        if b"http" not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("id"), str):
            last.pop(d["id"], None)
            last[d["id"]] = d
    out = [
        Link(url=u, at=str(d["timestamp"]) if d.get("timestamp") else None)
        for d in last.values()
        for u in _record_urls(d)
    ]
    return out, after


def turns(path: Path, cursor: int, conversation: str, cwd: str, subagent: bool) -> tuple[list[dict], int]:
    """The turns past byte `cursor` (`spend`, design §4.3 *Spend per turn*): each `gemini` record with
    tokens, the four kinds kept apart — `cache_read` the cached tokens, `input` the rest of the input,
    `output` the output and the thoughts (billed as output), no cache writes — a record written again
    counted once, at its last line, its id the turn's `id` and `response`. Raises OSError."""
    data, start, after = _whole(path, cursor)
    by_id: dict[str, dict] = {}
    pos = start
    for line in data.splitlines(keepends=True):
        offset, pos = pos, pos + len(line)
        if b'"tokens"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("type") != "gemini" or not isinstance(d.get("tokens"), dict):
            continue
        t = d["tokens"]
        cached = _count(t, "cached")
        rid = str(d.get("id") or "") or f"@{offset}"
        by_id.pop(rid, None)
        by_id[rid] = {
            "at": d.get("timestamp"),
            "id": rid,
            "source": str(path),
            "offset": offset,
            "model": str(d.get("model") or ""),
            "input": max(0, _count(t, "input") - cached),
            "output": _count(t, "output") + _count(t, "thoughts"),
            "cache_read": cached,
            "cache_write": 0,
            "cost": None,
            "response": rid,
            "conversation": conversation,
            "cwd": cwd,
            "subagent": subagent,
        }
    return list(by_id.values()), after
