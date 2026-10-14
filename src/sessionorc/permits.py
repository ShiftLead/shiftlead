"""What always reaches the person, whatever a rule or the director seat says (design §4.9b *What
always reaches the person*, TD-641): a permission prompt whose input names `~/.shiftlead`,
`~/.claude`, a systemd unit, or a path outside the member's own worktree and its repo's checkout.
The host agent refuses an *allow* of such a prompt — a rule's here, the director's `permit` (TD-642)
through the same function — while a *deny* stands.

Tool-agnostic: the prompt's input is read as whatever strings it holds, never by a field or a tool
name, so an adapter's tool that names a path anywhere in its input is caught the same way.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from sessionorc import paths

# an absolute or home-relative path as it appears in a command line or a field: a `/` or `~` that
# starts a word — never the `/` inside `a/b`, `s/x/y/` or after a URL's scheme
_PATH = re.compile(r"(?<![\w.:/$}~-])(~[\w.-]*)?(/[^\s'\"`;|&<>(){}]*)")
_HOME_VAR = re.compile(r"\$\{?HOME\}?(?=/)")
_UP = re.compile(r"(?<![\w.-])((?:\.\./)+|\.\.$)")  # a relative path that climbs
_SYSTEMD = re.compile(r"\bsystemctl\b|\bjournalctl\b|\.(service|timer|socket|target)\b|/systemd/")
# a stream, never a file anyone touches: writing to one is not a path outside the worktree
_HARMLESS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
_WALK_CAP = 200  # strings read from one input; a prompt is a command line or a few fields


def _strings(value: Any, out: list[str]) -> list[str]:
    if len(out) >= _WALK_CAP:
        return out
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            _strings(v, out)
    return out


def _within(p: Path, roots: list[Path]) -> bool:
    return any(p == r or r in p.parents for r in roots)


def always_the_person(tool_input: Any, dir: str, repo: str | None) -> str | None:
    """Why this prompt is the person's alone, or None. `dir` is the member's worktree (its record's
    `dir`), `repo` its repo's checkout; a path under either is the member's own."""
    home = Path(os.path.expanduser("~"))
    held = [home / ".shiftlead", home / ".claude", paths.home()]
    roots = [Path(os.path.realpath(d)) for d in (dir, repo) if d]
    for text in _strings(tool_input, []):
        if _SYSTEMD.search(text):
            return "it names a systemd unit"
        text = _HOME_VAR.sub("~", text)
        for m in _PATH.finditer(text):
            raw = (m.group(1) or "") + m.group(2)
            if raw in _HARMLESS:
                continue
            p = Path(os.path.realpath(os.path.expanduser(raw)))
            if _within(p, held):
                return f"it names {raw}, the home's own"
            if not _within(p, roots):
                return f"it names {raw}, outside the member's worktree and checkout"
        if dir and _UP.search(text):
            for word in re.split(r"[\s'\"`;|&<>(){}=]+", text):
                if ".." in word.split("/") and not word.startswith(("/", "~")):
                    p = Path(os.path.realpath(Path(dir) / word))
                    if not _within(p, roots):
                        return f"it names {word}, outside the member's worktree and checkout"
    return None
