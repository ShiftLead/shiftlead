"""The Transcript page (design §4.5 screen 9, §4.5a *Transcript*, TD-166): what a session said and
did, read from its tool's file through the `transcript` RPC (TD-165) without resuming it. The RPC
hands over the adapter's neutral entries; this module only shapes them for the template. Everything
drawn is text (TD-071): the only controls are the folds, *earlier turns* and the editor button.
"""

from __future__ import annotations

from typing import Any

from . import uiconf
from .common import editor_file, editor_file_link, editor_link

TRANSCRIPT_TURNS = 20  # the page opens on the last twenty turns, and *earlier turns* asks for twenty more


def _lines(text: Any) -> int:
    """How many lines a result holds, for its fold's label (*result · 9 lines*)."""
    s = str(text or "").rstrip("\n")
    return len(s.splitlines()) if s else 0


def entry_view(e: Any) -> dict[str, Any] | None:
    """One neutral entry as the page draws it (§4.5 screen 9): a prompt, text, a thought folded to
    *thought · n lines*, a tool call as one line with its result folded under it and a subagent's
    turns folded under the call that started them, a sidechain group, a compaction. An entry of a
    kind the page does not know is left out, as the tool's bookkeeping is."""
    if not isinstance(e, dict):
        return None
    kind = str(e.get("kind") or "")
    at = str(e.get("at") or "")
    if kind in ("prompt", "text"):
        return {"kind": kind, "at": at, "text": str(e.get("text") or "")}
    if kind == "thought":
        text = str(e.get("text") or "")
        return {"kind": kind, "at": at, "text": text, "lines": int(e.get("lines") or _lines(text))}
    if kind == "tool":
        result = e.get("result")
        side = e.get("sidechain")
        return {
            "kind": kind,
            "at": at,
            "name": str(e.get("name") or ""),
            "call": str(e.get("call") or ""),
            "result": None if result is None else str(result),
            "result_lines": _lines(result),
            "sidechain": entry_view(side) if isinstance(side, dict) else None,
        }
    if kind == "sidechain":
        entries = [v for v in (entry_view(x) for x in e.get("entries") or []) if v]
        return {"kind": kind, "at": at, "count": int(e.get("count") or 0), "entries": entries}
    if kind == "compaction":
        return {"kind": kind, "at": at}
    return None


def _size(n: Any) -> str:
    """The file's size as a person reads it: *812 KB*, *3.4 MB*."""
    try:
        b = int(n)
    except (TypeError, ValueError):
        return ""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b // 1024} KB"
    return f"{b / (1024 * 1024):.1f} MB"


def transcript_view(t: dict[str, Any]) -> dict[str, Any]:
    """The RPC's reply shaped for the page: the file's facts for the head, `before` for *earlier
    turns* (None at the file's start: no button), and the entries oldest first."""
    before = t.get("before")
    return {
        "path": str(t.get("path") or ""),
        "size": _size(t.get("size")),
        "first_at": str(t.get("first_at") or ""),
        "last_at": str(t.get("last_at") or ""),
        "turns": int(t.get("turns") or 0),
        "before": before if isinstance(before, int) and not isinstance(before, bool) else None,
        "entries": [v for v in (entry_view(e) for e in t.get("entries") or []) if v],
    }


def transcript_editor(path: str, here: bool) -> dict[str, Any] | None:
    """**VS Code** beside the head (§4.5a *Transcript*), and the Focus header's **‹›**: a file link
    (§4.6 *A file button is a file link*, TD-689) — the editor's file form with `:1`, one launch and
    no folder, since the file is the tool's and not the worktree's. Only for a record on this host:
    another host's file is not at that path here, and a container's reach link names a directory,
    not a file. None under `open_in: none`."""
    return editor_file_link(path, folder=False) if here and path else None


def transcript_paths(directory: str) -> dict[str, Any] | None:
    """What a path in a turn presses (§4.6 *A path in a transcript is a link too*, TD-691): the editor's
    file form (`file`, `{path}` unfilled) and the session's folder link sent first (`url`, `editor_link`
    of the record's `dir`; none with `folder_first: false`, so the press is one launch), as the pane's
    `editor`. The caller asks it only where the page draws its **VS Code** button; None for no links."""
    file = editor_file()
    if not file:
        return None
    folder = editor_link(directory) if directory and uiconf.file_link()["folder_first"] else None
    return {
        "label": uiconf.open_in().label,
        "file": file,
        "url": folder["url"] if folder else None,
        "wait": uiconf.file_link()["wait"],
    }
