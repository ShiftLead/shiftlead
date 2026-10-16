"""The adapter conformance suite's checks and harnesses (design §4.3 *The conformance suite*, TD-784).

The checks are tool-neutral: each takes what an adapter returned and raises `AssertionError` when it
is not the neutral shape. A harness is the one tool-specific part, kept here and never in the
adapter: where its tool keeps the files the adapter reads (so a fixture can be put there), and the
field names of the tool's own records that must never leave the adapter.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

from sessionorc import adapters
from sessionorc.adapters import ENTRY_KINDS, OPTIONAL_METHODS, Link, Transcript, TranscriptEntry
from sessionorc.identity import Proc
from sessionorc.models import State

FIXTURES = Path(__file__).parent / "fixtures"
STATES = frozenset(get_args(State))
ENTRY_FIELDS = frozenset(f.name for f in dataclasses.fields(TranscriptEntry))
TRANSCRIPT_FIELDS = frozenset(f.name for f in dataclasses.fields(Transcript))
CONTEXT_FIELDS = frozenset({"tokens", "at", "window"})
TURN_FIELDS = frozenset(
    {"at", "id", "source", "offset", "response", "model", "input", "output", "cache_read", "cache_write", "cost"}
)
TOKEN_KINDS = ("input", "output", "cache_read", "cache_write")
BACKGROUND_FIELDS = frozenset({"pid", "start", "cmd"})


def agent_adapters() -> list[str]:
    """Every registered adapter that runs an agent: `shell` and `command` run none, so they are not tested."""
    return [n for n in adapters.names() if adapters.has_agent(n)]


def manifest(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name / "manifest.json").read_text(encoding="utf-8"))


def fixture(name: str, rel: str) -> Path:
    return (FIXTURES / name / rel).resolve()


# -- the checks --------------------------------------------------------------------------------


def check_declaration(ad: object) -> None:
    """`implements` names only optional methods, each declared one is there and callable, and each
    other one is absent; `permission_channel`, where set, is a bool."""
    declared = adapters.implements(ad)
    unknown = declared - set(OPTIONAL_METHODS)
    assert not unknown, f"declares methods that are not optional ones: {sorted(unknown)}"
    for m in OPTIONAL_METHODS:
        got = getattr(ad, m, None)
        if m in declared:
            assert callable(got), f"declares {m!r} but has no such method"
        else:
            assert got is None, f"has {m!r} without declaring it"
    channel = getattr(ad, "permission_channel", True)
    assert isinstance(channel, bool), f"permission_channel is {channel!r}, not a bool"


def check_state(got: object) -> None:
    assert got is None or got in STATES, f"{got!r} is not a state"


def keys(obj: object) -> Iterator[str]:
    """Every key of every mapping inside `obj`, dataclasses read as their fields."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from keys(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from keys(v)


def check_neutral(obj: object, tool_fields: frozenset[str]) -> None:
    """No field name of the tool's own records leaves the method."""
    leaked = sorted({k for k in keys(obj) if k in tool_fields})
    assert not leaked, f"tool field names leave the adapter: {leaked}"


def check_transcript(tr: object, tool_fields: frozenset[str]) -> None:
    assert isinstance(tr, Transcript), f"read_transcript returned {type(tr).__name__}, not a Transcript"
    d = tr.to_dict()
    extra = sorted(set(d) - TRANSCRIPT_FIELDS)
    assert not extra, f"transcript fields beyond the neutral ones: {extra}"

    def walk(entries: list[dict]) -> None:
        for e in entries:
            assert e["kind"] in ENTRY_KINDS, f"{e['kind']!r} is not a neutral entry kind"
            assert set(e) <= ENTRY_FIELDS, f"entry fields beyond the neutral ones: {sorted(set(e) - ENTRY_FIELDS)}"
            walk(e.get("entries") or [])
            if e.get("sidechain"):
                walk([e["sidechain"]])

    walk(d["entries"])
    check_neutral(d, tool_fields)


def entry_kinds(tr: Transcript) -> set[str]:
    return {e["kind"] for e in tr.to_dict()["entries"]}


def check_context(got: object) -> None:
    assert isinstance(got, dict) and set(got) == CONTEXT_FIELDS, f"context is {got!r}, not {{tokens, at, window}}"
    tokens, window = got["tokens"], got["window"]
    assert isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0, f"tokens {tokens!r}"
    assert window is None or (isinstance(window, int) and tokens <= window), f"{tokens} tokens in a window of {window}"


def check_links(got: object) -> None:
    assert isinstance(got, tuple) and len(got) == 2, f"links returned {got!r}, not (links, cursor)"
    found, cursor = got
    assert isinstance(cursor, int) and cursor >= 0, f"cursor {cursor!r}"
    for link in found:
        assert isinstance(link, Link), f"{link!r} is not a Link"
        assert link.url.startswith(("http://", "https://")), f"{link.url!r} is not an http(s) URL"


def check_spend(got: object, tool_fields: frozenset[str]) -> None:
    assert isinstance(got, dict) and {"turns", "cursors", "reason"} <= set(got), f"spend returned {got!r}"
    for turn in got["turns"]:
        assert set(turn) == TURN_FIELDS, f"a turn's fields are {sorted(turn)}, not the neutral ones"
        for kind in TOKEN_KINDS:
            n = turn[kind]
            assert isinstance(n, int) and not isinstance(n, bool) and n >= 0, f"{kind} is {n!r}"
    check_neutral(got["turns"], tool_fields)


def check_background(got: object) -> None:
    assert got is None or isinstance(got, list), f"background returned {got!r}"
    for task in got or ():
        assert isinstance(task, dict) and set(task) == BACKGROUND_FIELDS, f"a task is {task!r}, not {{pid, start, cmd}}"


class RecordedProc:
    """A `ProcReader` over a `/proc` snapshot the fixture recorded: `{pid: {comm, children, cmdline, stat}}`."""

    def __init__(self, procs: dict[str, dict[str, Any]]):
        self.procs = procs

    def _get(self, pid: int) -> dict[str, Any] | None:
        return self.procs.get(str(pid))

    def stat(self, pid: int) -> Proc | None:
        p = self._get(pid)
        return Proc(pid=int(pid), **p["stat"]) if p else None

    def comm(self, pid: int) -> str | None:
        p = self._get(pid)
        return p["comm"] if p else None

    def children(self, pid: int) -> list[int] | None:
        p = self._get(pid)
        return list(p["children"]) if p else None

    def cmdline(self, pid: int) -> list[str] | None:
        p = self._get(pid)
        return list(p["cmdline"]) if p else None

    def cgroup(self, pid: int) -> str | None:
        return None


# -- the harnesses: where each tool keeps its files ------------------------------------------------


class ClaudeCodeHarness:
    """Claude Code keeps a session's transcript at `<config dir>/projects/<munged cwd>/<id>.jsonl`."""

    tool_fields = frozenset(
        {
            "type",
            "message",
            "content",
            "isSidechain",
            "uuid",
            "parentUuid",
            "sessionId",
            "session_id",
            "tool_use_id",
            "toolUseResult",
            "usage",
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "requestId",
            "timestamp",
            "gitBranch",
        }
    )

    def profile(self, tmp_path: Path, monkeypatch: Any) -> str:
        """A scratch home whose one profile's config dir is under `tmp_path`; its name."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
        (home / "profiles.yml").write_text(
            f"default: t\nprofiles:\n  t: {{account: t, config_dir: {tmp_path / 'cc'}}}\n", encoding="utf-8"
        )
        return "t"

    def place_transcript(self, tmp_path: Path, src: Path, session_id: str) -> Path:
        """Put the fixture where the adapter looks for `session_id`'s transcript; the session's cwd."""
        from shiftlead.adapters.claude_code import munge

        cwd = tmp_path / "repo"
        d = tmp_path / "cc" / "projects" / munge(cwd)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{session_id}.jsonl").write_bytes(src.read_bytes())
        return cwd


HARNESSES: dict[str, Any] = {"claude-code": ClaudeCodeHarness()}
