"""The adapter conformance suite's checks and harnesses (design §4.3 *The conformance suite*, TD-784).

The checks are tool-neutral: each takes what an adapter returned and raises `AssertionError` when it
is not the neutral shape. A harness is the one tool-specific part, kept here and never in the
adapter: where its tool keeps the files the adapter reads (so a fixture can be put there), and the
field names of the tool's own records that must never leave the adapter.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shlex
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

from sessionorc import adapters
from sessionorc.adapters import ENTRY_KINDS, OPTIONAL_METHODS, Conversation, Link, Prompt, Transcript, TranscriptEntry
from sessionorc.identity import Proc
from sessionorc.models import State

FIXTURES = Path(__file__).parent / "fixtures"
STATES = frozenset(get_args(State))
ENTRY_FIELDS = frozenset(f.name for f in dataclasses.fields(TranscriptEntry))
TRANSCRIPT_FIELDS = frozenset(f.name for f in dataclasses.fields(Transcript))
CONTEXT_FIELDS = frozenset({"tokens", "at", "window"})
TURN_FIELDS = frozenset(
    {"at", "id", "source", "offset", "response", "model", "input", "output", "cache_read", "cache_write", "cost"}
    | {"conversation", "cwd", "subagent"}  # whose turn it is (§4.3, §4.4 *Spend per seat*, TD-830)
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


def check_conversations(got: object) -> None:
    assert isinstance(got, list), f"conversations returned {got!r}, not a list"
    for c in got:
        assert isinstance(c, Conversation), f"{c!r} is not a Conversation"
        assert c.id and isinstance(c.size, int) and c.size > 0, f"{c!r}"
        assert adapters.instant(c.first_at) and adapters.instant(c.last_at), f"{c!r} carries an instant that is none"
        assert adapters.instant(c.first_at) <= adapters.instant(c.last_at), f"{c!r} ends before it starts"
    assert got == adapters.oldest_first(got), "conversations are not oldest first"


def check_prompts(got: object) -> None:
    assert isinstance(got, tuple) and len(got) == 3, f"prompts returned {got!r}, not (prompts, reply, cursor)"
    found, reply, cursor = got
    assert isinstance(cursor, int) and cursor >= 0, f"cursor {cursor!r}"
    assert reply is None or isinstance(reply, str), f"leading reply {reply!r}"
    for p in found:
        assert isinstance(p, Prompt), f"{p!r} is not a Prompt"
        assert isinstance(p.text, str) and p.text and len(p.text) <= 300, f"text {p.text!r}"
        assert p.reply is None or (isinstance(p.reply, str) and len(p.reply) <= 200), f"reply {p.reply!r}"
        assert p.drawn is None or isinstance(p.drawn, str), f"drawn {p.drawn!r}"
        assert isinstance(p.whole, bool), f"whole {p.whole!r}"


def pane_row(row: str) -> str:
    """A pane row as the jump compares it (design §4.6 *A jump to a prompt*): leading whitespace stripped,
    trailing spaces trimmed, a non-breaking space read as a space."""
    return row.replace("\xa0", " ").strip()


def check_spend(got: object, tool_fields: frozenset[str]) -> None:
    assert isinstance(got, dict) and {"turns", "cursors", "reason"} <= set(got), f"spend returned {got!r}"
    for turn in got["turns"]:
        assert set(turn) == TURN_FIELDS, f"a turn's fields are {sorted(turn)}, not the neutral ones"
        for kind in TOKEN_KINDS:
            n = turn[kind]
            assert isinstance(n, int) and not isinstance(n, bool) and n >= 0, f"{kind} is {n!r}"
    check_neutral(got["turns"], tool_fields)


def hook_reading(params: dict[str, Any] | None) -> dict[str, Any]:
    """The state and pending kind an adapter's hook params stand for, restated from the host agent's
    `agent_hook.rpc_hook` (not called): a `permission` event waits on the person as `needs-you`; None
    reports nothing."""
    if params is None:
        return {"state": None}
    if params.get("kind") == "permission":
        return {"state": "needs-you", "pending": "permission"}
    kind = (params.get("pending") or {}).get("kind")
    return {"state": params.get("state"), **({"pending": kind} if kind else {})}


def check_hook_reading(got: dict[str, Any]) -> None:
    check_state(got["state"])
    assert got.get("pending") in (None, "permission", "question"), f"pending kind {got.get('pending')!r}"


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


# -- the seat's life (design §4.3 *A seat's life end to end, in CI, with no model*, TD-1647) ------------


def suite_bin(tmp: Path, monkeypatch: Any) -> Path:
    """The suite's own `shiftlead-hook` and `ao`, first on `PATH` (the test's, so a launch's layer names this
    hook, and the pane's, which the stub's wrapper exports): each runs this interpreter on the code under test."""
    import shiftlead

    d = tmp / "suite-bin"
    d.mkdir(parents=True, exist_ok=True)
    src = Path(shiftlead.__file__).resolve().parents[1]  # the code under test, a worktree's own
    for name, entry in (("shiftlead-hook", "shiftlead.hook_entry"), ("ao", "shiftlead.cli")):
        f = d / name
        f.write_text(
            f"#!/bin/sh\nPYTHONPATH={shlex.quote(str(src))}${{PYTHONPATH:+:$PYTHONPATH}} "
            f"exec {shlex.quote(sys.executable)} -c "
            f'\'import sys; from {entry} import main; sys.argv[0] = "{name}"; sys.exit(main())\' "$@"\n',
            encoding="utf-8",
        )
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
    return d


def _flag(argv: list[str], *names: str) -> str | None:
    """The value after the first of `names` in `argv`, or None."""
    for i, a in enumerate(argv[:-1]):
        if a in names:
            return argv[i + 1]
    return None


# -- the harnesses: where each tool keeps its files ------------------------------------------------


class ClaudeCodeHarness:
    """Claude Code keeps a session's transcript at `<config dir>/projects/<munged cwd>/<id>.jsonl`, and
    hands each hook payload to `shiftlead-hook`, whose `translate` makes the host agent's `hook` params."""

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

    skip_flags = ("--dangerously-skip-permissions",)

    def stub_setup(self, tmp: Path, monkeypatch: Any) -> None:
        """Nothing for the layer, which is the `--settings` file the launch writes; the suite's hook on `PATH`."""
        suite_bin(tmp, monkeypatch)

    def hook_command(self, argv: list[str], env: dict[str, str]) -> str:
        """The hook command the launch's `--settings` layer names for every event."""
        layer = json.loads(Path(_flag(argv, "--settings") or "").read_text(encoding="utf-8"))
        return layer["hooks"]["Stop"][0]["hooks"][0]["command"]

    def session_id(self, argv: list[str], env: dict[str, str]) -> tuple[str | None, str]:
        """The launch's `--session-id` or `--resume`, and the payload field that carries a captured one."""
        return _flag(argv, "--session-id", "--resume"), "session_id"

    def hook_params(self, payload: dict[str, Any], *, at_composer: bool) -> dict[str, Any] | None:
        from shiftlead.adapters.claude_code.hook import translate

        return translate(payload, at_composer=at_composer)

    def place_transcript(self, tmp_path: Path, src: Path, session_id: str) -> Path:
        """Put the fixture where the adapter looks for `session_id`'s transcript; the session's cwd."""
        from shiftlead.adapters.claude_code import munge

        cwd = tmp_path / "repo"
        d = tmp_path / "cc" / "projects" / munge(cwd)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{session_id}.jsonl").write_bytes(src.read_bytes())
        return cwd

    def place_conversations(self, tmp_path: Path, entry: dict, name: str) -> Path:
        """Put the manifest's `conversations` directory where the adapter looks for the cwd's conversations,
        each file under its own name; the cwd."""
        from shiftlead.adapters.claude_code import munge

        cwd = tmp_path / "convs"
        d = tmp_path / "cc" / "projects" / munge(cwd)
        d.mkdir(parents=True, exist_ok=True)
        for src in sorted(fixture(name, entry["dir"]).glob("*.jsonl")):
            (d / src.name).write_bytes(src.read_bytes())
        return cwd


class GeminiHarness:
    """Gemini CLI keeps a session's chat at `<home>/.gemini/tmp/<slug>/chats/session-<minute>-<id[:8]>.jsonl`,
    its first record naming the session, and hands each hook payload to `shiftlead-hook --adapter gemini`,
    whose `translate` makes the host agent's `hook` params."""

    tool_fields = frozenset(
        {
            "type",
            "content",
            "thoughts",
            "toolCalls",
            "functionResponse",
            "sessionId",
            "projectHash",
            "tokens",
            "cached",
            "resultDisplay",
            "displayName",
            "timestamp",
            "$set",
            "$patch",
            "$rewindTo",
        }
    )

    def profile(self, tmp_path: Path, monkeypatch: Any) -> str:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
        (home / "profiles.yml").write_text(
            f"default: t\nprofiles:\n  t: {{adapter: gemini, account: t, config_dir: {tmp_path / 'gm'}}}\n",
            encoding="utf-8",
        )
        return "t"

    skip_flags = ("--approval-mode yolo", "--approval-mode=yolo", "--yolo", "-y")

    def stub_setup(self, tmp: Path, monkeypatch: Any) -> None:
        """A scratch machine layer naming the suite's hook, the adapter's `MACHINE_LAYER` and `_lstat` patched to
        it (as tests/test_gemini_adapter.py does): the real one is root-owned under `/etc/shiftlead/`."""
        from shiftlead.adapters import gemini

        hook = suite_bin(tmp, monkeypatch) / "shiftlead-hook"
        machine = tmp / "etc" / "gemini-settings.json"
        machine.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(gemini, "MACHINE_LAYER", machine)
        monkeypatch.setattr(gemini, "_lstat", _rooted)
        machine.write_text(gemini.layer_text(str(hook)), encoding="utf-8")  # the person ran the install line

    def hook_command(self, argv: list[str], env: dict[str, str]) -> str:
        """The hook command the machine layer the launch names (`GEMINI_CLI_SYSTEM_SETTINGS_PATH`) holds."""
        layer = json.loads(Path(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).read_text(encoding="utf-8"))
        return layer["hooks"]["AfterAgent"][0]["hooks"][0]["command"]

    def session_id(self, argv: list[str], env: dict[str, str]) -> tuple[str | None, str]:
        return _flag(argv, "--session-id", "--resume"), "session_id"

    def hook_params(self, payload: dict[str, Any], *, at_composer: bool) -> dict[str, Any] | None:
        from shiftlead.adapters.gemini.hook import translate

        return translate(payload)  # every Gemini launch lands at the composer: no `at_composer` to pass

    def place_transcript(self, tmp_path: Path, src: Path, session_id: str) -> Path:
        """Put the fixture where the adapter looks for `session_id`'s chat — its captured session id
        replaced by `session_id` throughout, since the file is found by the id it names; the session's cwd."""
        cwd = tmp_path / "repo"
        project = tmp_path / "gm" / ".gemini" / "tmp" / f"repo-{session_id}"
        (project / "chats").mkdir(parents=True, exist_ok=True)
        (project / ".project_root").write_text(str(cwd), encoding="utf-8")
        data = src.read_bytes()
        captured = json.loads(data.split(b"\n", 1)[0])["sessionId"].encode()
        out = project / "chats" / f"session-2026-10-22T00-00-{session_id[:8]}.jsonl"
        out.write_bytes(data.replace(captured, session_id.encode()))
        return cwd

    def place_conversations(self, tmp_path: Path, entry: dict, name: str) -> Path:
        """Put the manifest's chats, unchanged, in one project whose `.project_root` names the cwd — a chat of
        another project and a subagent's chat beside them, which the read leaves out; the cwd."""
        cwd = tmp_path / "convs"
        project = tmp_path / "gm" / ".gemini" / "tmp" / "convs"
        other = tmp_path / "gm" / ".gemini" / "tmp" / "elsewhere"
        for p in (project, other):
            (p / "chats").mkdir(parents=True, exist_ok=True)
        (project / ".project_root").write_text(str(cwd), encoding="utf-8")
        (other / ".project_root").write_text(str(tmp_path / "elsewhere"), encoding="utf-8")
        for i, rel in enumerate(entry["files"]):
            data = fixture(name, rel).read_bytes()
            sid = json.loads(data.split(b"\n", 1)[0])["sessionId"]
            (project / "chats" / f"session-2026-10-22T00-0{i}-{sid[:8]}.jsonl").write_bytes(data)
            (other / "chats" / f"session-2026-10-22T00-0{i}-{sid[:8]}.jsonl").write_bytes(
                data.replace(sid.encode(), b"other-" + sid[6:].encode())
            )
            (project / "chats" / sid).mkdir(exist_ok=True)
            (project / "chats" / sid / "sub.jsonl").write_bytes(
                data.replace(sid.encode(), b"subagt-" + sid[7:].encode())
            )
        return cwd


def _rooted(p: Any) -> os.stat_result:
    """An `lstat` that reads every path root-owned and 0755, the machine layer's test run on a scratch file."""
    st = os.lstat(p)
    mode = stat.S_IFMT(st.st_mode) | 0o755
    return os.stat_result((mode, st.st_ino, st.st_dev, st.st_nlink, 0, 0, st.st_size, 0, 0, 0))


class GrokHarness:
    """Grok Build reads its hooks from `<GROK_HOME>/hooks/*.json`, which its launch writes ShiftLead's file into,
    and hands each payload to `shiftlead-hook --adapter grok`, whose `translate` makes the host agent's `hook`
    params; its transcript is `sessions/*/<id>/updates.jsonl` under that home."""

    tool_fields = frozenset(
        {"sessionId", "hookEventName", "toolName", "toolInput", "promptId", "subagentType"}
        | {"sessionUpdate", "toolCallId", "rawInput", "rawOutput", "content"}
    )
    skip_flags = ("--always-approve",)

    def profile(self, tmp_path: Path, monkeypatch: Any) -> str:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
        (home / "profiles.yml").write_text(
            f"default: t\nprofiles:\n  t: {{adapter: grok, account: t, config_dir: {tmp_path / 'gk'}}}\n",
            encoding="utf-8",
        )
        return "t"

    def stub_setup(self, tmp: Path, monkeypatch: Any) -> None:
        """The suite's hook first on `PATH`, and the hook file the launch writes into the case's scratch
        `GROK_HOME` naming it (`hook_path` patched: the real one is the interpreter's own `bin/`); the person's home
        the launch home mirrors and the managed Claude Code file the `all` refusal reads both patched into the
        case's directory, so the suite reads no developer's home (§4.3 *The conformance suite*)."""
        from shiftlead.adapters import grok

        hook = suite_bin(tmp, monkeypatch) / "shiftlead-hook"
        monkeypatch.setattr(grok, "hook_path", lambda: str(hook))
        person = tmp / "person-home"
        person.mkdir(exist_ok=True)
        monkeypatch.setattr(grok, "PERSON_HOME", person)
        monkeypatch.setattr(grok, "MANAGED_SETTINGS", tmp / "etc" / "claude-code" / "managed-settings.json")

    def hook_command(self, argv: list[str], env: dict[str, str]) -> str:
        """The command the hook file in the launch's `GROK_HOME` names for every event."""
        from shiftlead.adapters import grok

        doc = json.loads((Path(env["GROK_HOME"]) / grok.HOOK_FILE).read_text(encoding="utf-8"))
        return doc["hooks"]["Stop"][0]["hooks"][0]["command"]

    def session_id(self, argv: list[str], env: dict[str, str]) -> tuple[str | None, str]:
        return _flag(argv, "--session-id", "--resume"), "sessionId"

    def hook_params(self, payload: dict[str, Any], *, at_composer: bool) -> dict[str, Any] | None:
        from shiftlead.adapters.grok.hook import translate

        return translate(payload)  # every Grok launch lands at the composer: no `at_composer` to pass

    def place_transcript(self, tmp_path: Path, src: Path, session_id: str) -> Path:
        """Put the fixture where the adapter looks for `session_id`'s log — `sessions/<a cwd's directory>/<id>/`,
        its captured session id replaced by `session_id` throughout, and the `summary.json` captured beside it
        (`<name>.summary.json`) where there is one; the session's cwd."""
        cwd = tmp_path / "repo"
        data = src.read_bytes()
        captured = json.loads(data.split(b"\n", 1)[0])["params"]["sessionId"].encode()
        out = tmp_path / "gk" / "sessions" / "%2Ftmp%2Frepo" / session_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "updates.jsonl").write_bytes(data.replace(captured, session_id.encode()))
        summary = src.with_name(src.name.removesuffix(".jsonl") + ".summary.json")
        if summary.is_file():
            (out / "summary.json").write_bytes(summary.read_bytes().replace(captured, session_id.encode()))
        return cwd


HARNESSES: dict[str, Any] = {"claude-code": ClaudeCodeHarness(), "gemini": GeminiHarness(), "grok": GrokHarness()}
