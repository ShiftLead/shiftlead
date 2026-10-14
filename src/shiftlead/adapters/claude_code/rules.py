"""The person's `permissions:` rules in Claude Code's own syntax (design §4.9b *The director seat*,
§4.3, TD-641): `Tool` or `Tool(specifier)`, as Claude Code's settings write them — `Bash(pdm run
test:*)`, `Edit(src/**)`, `WebFetch(domain:github.com)`, `mcp__server` — matched against a
permission prompt's tool and input. The host agent calls these through the adapter and names no
tool itself.

Conservative on purpose, since an allow here is answered with nobody looking: a rule this module
does not understand matches nothing, an *allow* of a compound shell command must cover every part
of it, and a *deny* matches when any part does.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_RULE = re.compile(r"([A-Za-z][\w-]*)(?:\((.*)\))?", re.S)
# what joins one shell command to the next; an allow must cover each part
_JOIN = re.compile(r"&&|\|\||;|\||\n|(?<![<>])&(?![>&])")
# what runs a command of its own inside a part: never covered by a prefix rule
_NESTED = re.compile(r"`|\$\(|<\(|>\(")
PATH_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Glob", "Grep"}
PATH_FIELDS = ("file_path", "notebook_path", "path")
NEVER = {"AskUserQuestion"}  # a question is the person's, never a prompt a rule answers (§9 invariant 6)


def problem(rule: str) -> str | None:
    """Why `rule` is not a rule Claude Code's syntax can carry, or None."""
    m = _RULE.fullmatch(rule.strip())
    if m is None:
        return f"{rule!r} is not Tool or Tool(specifier)"
    if m.group(2) is not None and not m.group(2).strip():
        return f"{rule!r} has an empty specifier: write the tool alone to cover every use"
    return None


def _glob(pattern: str) -> re.Pattern[str]:
    """A gitignore-style path pattern: `**` any depth, `*` and `?` within one segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            if pattern.startswith("/", i):
                out[-1] = "(?:.*/)?"
                i += 1
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def _command_matches(spec: str, command: str) -> bool:
    command = command.strip()
    if spec.endswith(":*"):
        prefix = spec[:-2].strip()
        return command == prefix or command.startswith(prefix + " ")
    if "*" in spec:
        return _glob(spec.replace("/", "\0")).fullmatch(command.replace("/", "\0")) is not None
    return command == spec.strip()


def _bash(spec: str, command: str, deny: bool) -> bool:
    parts = [p for p in _JOIN.split(command) if p.strip()]
    if not parts:
        return False
    if deny:
        return any(_command_matches(spec, p) for p in parts) or _command_matches(spec, command)
    return not _NESTED.search(command) and all(_command_matches(spec, p) for p in parts)


def _path(spec: str, tool_input: dict[str, Any], cwd: Path | None) -> bool:
    raw = next((tool_input[f] for f in PATH_FIELDS if isinstance(tool_input.get(f), str)), None)
    if raw is None:
        return False
    target = Path(os.path.realpath(Path(cwd or "/") / os.path.expanduser(raw)))
    if spec.startswith("//"):
        base, pattern = Path("/"), spec[2:]
    elif spec.startswith("~/"):
        base, pattern = Path(os.path.expanduser("~")), spec[2:]
    elif cwd is None:
        return False
    else:
        base, pattern = Path(os.path.realpath(cwd)), spec.lstrip("/")
    try:
        rel = target.relative_to(base).as_posix()
    except ValueError:
        return False
    if "/" not in pattern.rstrip("/"):
        pattern = "**/" + pattern  # gitignore: a bare name matches at any depth
    if pattern.endswith("/"):
        pattern += "**"
    return _glob(pattern).fullmatch(rel) is not None


def matches(rule: str, tool: str, tool_input: Any, *, cwd: Path | None = None, deny: bool = False) -> bool:
    """Whether `rule` covers this call of `tool` with `tool_input`. `deny` reads a compound command
    as covered when any part is; an allow needs every part."""
    m = _RULE.fullmatch(rule.strip())
    if m is None or tool in NEVER:
        return False
    name, spec = m.group(1), m.group(2)
    if name.startswith("mcp__") and spec is None:
        return tool == name or tool.startswith(name + "__")
    if name != tool:
        return False
    if spec is None:
        return True
    spec = spec.strip()
    if not spec:
        return False
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool == "Bash":
        command = tool_input.get("command")
        return isinstance(command, str) and _bash(spec, command, deny)
    if tool in PATH_TOOLS:
        return _path(spec, tool_input, cwd)
    if tool == "WebFetch" and spec.startswith("domain:"):
        host = urlparse(str(tool_input.get("url") or "")).hostname or ""
        want = spec[len("domain:") :].strip().lower()
        return bool(host) and (host == want or host.endswith("." + want))
    return False  # a specifier this module does not read matches nothing
