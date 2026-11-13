"""Turns of the designer sessions, one row per API response (TD-1764): read-only on the transcripts.

Usage: python extract.py <transcript dir> > turns.csv

A turn is one assistant message id (Claude Code writes one line per content block, each carrying the same
usage; the first is kept). Each row carries the session, time, git branch, model, the four token kinds, the
context the turn carried (input + cache read + cache write) and what it did: its tool calls' names with a
short, transcript-free summary (a Bash command's first word or two, an edited file's path, an Agent call's
model), never its text; a reviewer's report reaching the designer is a row of its own (`tools` = REPORT).
Subagents (reviewers) are rows of their own with `side` = the subagent's id."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

FIELDS = [
    "session",
    "side",
    "msg",
    "ts",
    "branch",
    "model",
    "input",
    "cache_read",
    "cache_write",
    "output",
    "context",
    "tools",
]


def _what(block: dict) -> str:
    name, inp = block.get("name", "?"), block.get("input") or {}
    if name == "Bash":
        words = str(inp.get("command", "")).replace("\n", " ").split()
        words = [w for w in words if not w.startswith(("cd", "/home", "&&")) and "=" not in w[:12]]
        return "Bash:" + " ".join(words[:3])[:60]
    if name in ("Edit", "Write", "Read"):
        p = str(inp.get("file_path", ""))
        return f"{name}:{p.split('/grinder-ao-2/')[-1].split('/designer-ao-1/')[-1][-70:]}"
    if name == "Agent":
        return f"Agent:{inp.get('model') or inp.get('subagent_type') or ''}"
    return name


def rows(path: Path, session: str, side: str):
    seen = set()
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        mid = m.get("id")
        u = m.get("usage") or {}
        if not mid or mid in seen or not u:
            continue
        seen.add(mid)
        tools = [_what(b) for b in m.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
        # later blocks of the same message carry its other tool calls
        i, cr, cw, o = (
            u.get(k, 0) or 0
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
        )
        yield {
            "session": session,
            "side": side,
            "msg": mid,
            "ts": d.get("timestamp", ""),
            "branch": d.get("gitBranch", ""),
            "model": m.get("model", ""),
            "input": i,
            "cache_read": cr,
            "cache_write": cw,
            "output": o,
            "context": i + cr + cw,
            "tools": ";".join(tools),
        }


def reports(path: Path, session: str):
    """A reviewer's report reaching the designer: a background Agent's `task-notification`, a subagent's
    hand-back, or a foreground Agent call's result. One row each, `tools` = REPORT, no tokens."""
    agent_calls: set[str] = set()
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") or {}
        content = m.get("content")
        if d.get("type") == "assistant":
            for b in content or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Agent":
                    agent_calls.add(b.get("id"))
            continue
        if d.get("type") != "user":
            continue
        text = json.dumps(content)
        hit = ("<task-notification>" in text and "<summary>Agent " in text) or "[Subagent hand-back]" in text
        if not hit and isinstance(content, list):
            hit = any(
                isinstance(b, dict)
                and b.get("type") == "tool_result"
                and b.get("tool_use_id") in agent_calls
                and "Async agent launched" not in json.dumps(b.get("content"))
                for b in content
            )
        if hit:
            yield {
                "session": session,
                "side": "",
                "msg": "",
                "ts": d.get("timestamp", ""),
                "branch": d.get("gitBranch", ""),
                "model": "",
                "input": 0,
                "cache_read": 0,
                "cache_write": 0,
                "output": 0,
                "context": 0,
                "tools": "REPORT",
            }


def tools_by_msg(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "assistant":
            m = d.get("message") or {}
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    out.setdefault(m.get("id"), []).append(_what(b))
    return out


def main(root: Path) -> None:
    w = csv.DictWriter(sys.stdout, FIELDS)
    w.writeheader()
    for f in sorted(root.glob("*.jsonl")):
        sess = f.stem
        files = [(f, "")] + [(s, s.stem) for s in sorted((root / sess / "subagents").glob("*.jsonl"))]
        for p, side in files:
            tb = tools_by_msg(p)
            for r in rows(p, sess, side):
                r["tools"] = ";".join(tb.get(r["msg"], []))
                w.writerow(r)
        for r in reports(f, sess):
            w.writerow(r)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
