"""The Grok Build adapter's launch (design §4.3 *The third adapter: Grok Build*, TD-1637 slice 7): the argv by
absolute path, the session id, resume, the permission flags, the environment every launch sets, the hook file
written into the profile's own home, the home and credential reads, and the machine's note for a missing binary."""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import pytest

from shiftlead.adapters import grok
from shiftlead.adapters.grok import GrokAdapter


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        "default: gk\nprofiles:\n"
        f"  gk: {{adapter: grok, account: paul, model: grok-code-fast, config_dir: {tmp_path / 'g'}}}\n"
        f"  asks: {{adapter: grok, account: paul, permission_prompts: ask, config_dir: {tmp_path / 'g'}}}\n"
        f"  close: {{adapter: grok, account: paul, permission_prompts: all, config_dir: {tmp_path / 'g'}}}\n"
        "  own: {adapter: grok, account: paul, extra_args: [--x1, v1], unattended_args: [--yolo],"
        f" config_dir: {tmp_path / 'g'}}}\n"
    )
    binary = tmp_path / "bin" / "grok"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    (tmp_path / "person").mkdir()  # the launch home's source and the managed file: never the developer's (TD-1836)
    monkeypatch.setattr(grok, "PERSON_HOME", tmp_path / "person")
    monkeypatch.setattr(grok, "MANAGED_SETTINGS", tmp_path / "etc" / "managed-settings.json")
    return tmp_path


def ad(home: Path) -> GrokAdapter:
    return GrokAdapter(binary=str(home / "bin" / "grok"), hook_cmd="/venv/bin/shiftlead-hook")


def test_launch_argv_env_and_the_hook_file(home):
    spec = ad(home).launch(profile="", resume=None, prompt="do it", unattended=False, cwd=home, name="t1")
    assert spec.argv[:3] == [str(home / "bin" / "grok"), "--session-id", spec.adapter_id] and uuid.UUID(spec.adapter_id)
    assert spec.argv[3:] == ["--model", "grok-code-fast"] and spec.model == "grok-code-fast"
    assert spec.first_prompt == "do it" and not any("do it" in a for a in spec.argv)  # typed, never passed
    env = spec.env
    assert env["GROK_HOME"] == str(home / "g")
    assert env["GROK_DISABLE_AUTOUPDATER"] == "1" and env["GROK_FOLDER_TRUST"] == "0"
    for tool in ("CLAUDE", "CURSOR"):
        assert env[f"GROK_{tool}_HOOKS_ENABLED"] == "false" and env[f"GROK_{tool}_MCPS_ENABLED"] == "false"
    assert env["GROK_DEFAULT_SELECTED_PERMISSION"] == "allow_once"
    assert env["GROK_SESSION_END_HOOKS_TIMEOUT_MS"] == "10000"
    assert env["XAI_API_KEY"] == "" and env["GROK_CODE_XAI_API_KEY"] == ""  # no fallback to a key's bill
    doc = json.loads((home / "g" / "hooks" / "shiftlead.json").read_text())
    assert set(doc["hooks"]) == set(grok.HOOK_EVENTS)
    for groups in doc["hooks"].values():
        assert groups == [
            {"hooks": [{"type": "command", "command": "/venv/bin/shiftlead-hook --adapter grok", "timeout": 10}]}
        ]  # no matcher: every tool reaches the hook


def test_the_hook_file_is_rewritten_only_when_it_differs_and_the_persons_files_stay(home):
    hooks = home / "g" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "mine.json").write_text('{"hooks": {}}')
    path = grok.write_hook_file(home / "g", "/a/shiftlead-hook")
    first = path.stat().st_mtime_ns
    assert grok.write_hook_file(home / "g", "/a/shiftlead-hook") == path and path.stat().st_mtime_ns == first
    grok.write_hook_file(home / "g", "/b/shiftlead-hook")  # another venv's launch writes its own path back
    assert "/b/shiftlead-hook --adapter grok" in path.read_text()
    assert (hooks / "mine.json").read_text() == '{"hooks": {}}'
    assert sorted(p.name for p in hooks.iterdir()) == ["mine.json", "shiftlead.json"]  # no temporary file left


def test_a_resume_an_unattended_launch_ask_and_all(home):
    a = ad(home)
    r = a.launch(profile="gk", resume="abc-123", prompt=None, unattended=True, cwd=home)
    assert r.adapter_id == "abc-123" and r.argv[1:3] == ["--resume", "abc-123"] and "--session-id" not in r.argv
    assert r.argv[-1] == "--always-approve"  # `permission_prompts: skip`, the default
    assert "--always-approve" not in a.launch(profile="gk", resume=None, prompt=None, unattended=False, cwd=home).argv
    k = a.launch(profile="asks", resume=None, prompt=None, unattended=True, cwd=home)
    assert "--always-approve" not in k.argv and "--permission-mode" not in k.argv
    c = a.launch(profile="close", resume=None, prompt=None, unattended=True, cwd=home)
    assert c.argv[-2:] == ["--permission-mode", "default"] and "--always-approve" not in c.argv


def test_a_launch_is_refused_in_words(home, tmp_path):
    yml = home / "home" / "profiles.yml"
    kept = yml.read_text()
    # registered, the adapter's `own_home` refuses a home-less profile at the load, before any launch (§4.2a)
    yml.write_text(kept + "  bare: {adapter: grok, account: paul}\n")
    with pytest.raises(ValueError, match="bare needs a config_dir of its own"):
        ad(home).launch(profile="bare", resume=None, prompt=None, unattended=False, cwd=home)
    yml.write_text(kept)
    missing = GrokAdapter(binary=str(tmp_path / "nowhere" / "grok"))
    with pytest.raises(ValueError, match=r"not installed at .*nowhere/grok .*install\.sh"):
        missing.launch(profile="gk", resume=None, prompt=None, unattended=False, cwd=home)
    (home / "g").mkdir()
    (home / "g" / "hooks").write_text("a file where the directory goes")
    with pytest.raises(ValueError, match="cannot write the Grok hook file"):
        ad(home).launch(profile="gk", resume=None, prompt=None, unattended=False, cwd=home)


def test_the_home_the_credentials_and_the_machines_note(home, tmp_path):
    a = ad(home)
    assert a.own_home == Path("~/.grok").expanduser() and not a.permission_channel and not a.start_context
    assert a.default_home({}) == Path("~/.grok").expanduser()
    assert a.default_home({"GROK_HOME": str(tmp_path / "x")}) == tmp_path / "x"
    assert a.default_home({"GROK_HOME": str(tmp_path / "x"), "SHIFTLEAD_SESSION": "s"}) == a.own_home
    from shiftlead import profiles

    gk = profiles.get("gk")
    assert a.credentials_ok(gk) is None and a.credentials_ok(dataclasses.replace(gk, config_dir=None)) is None
    (home / "g").mkdir()
    (home / "g" / "auth.json").write_text("{}")
    assert a.credentials_ok(gk) is True
    assert a.setup_note() == {"key": None}  # the binary is there
    note = GrokAdapter(binary=str(tmp_path / "nowhere" / "grok")).setup_note()
    assert note["key"] == f"missing:{tmp_path / 'nowhere' / 'grok'}" and grok.INSTALL_LINE in note["text"]
    (home / "home" / "profiles.yml").write_text("default: x\nprofiles:\n  x: {adapter: claude-code}\n")
    assert GrokAdapter(binary=str(tmp_path / "nowhere" / "grok")).setup_note() is None  # no Grok profile


def test_a_profiles_own_extra_and_unattended_args_reach_the_argv(home):
    """§4.3: a profile's `extra_args` pass on every launch, and its own `unattended_args` replace
    `--always-approve` on an unattended launch under `skip` (TD-1805)."""
    a = ad(home)
    i = a.launch(profile="own", resume=None, prompt=None, unattended=False, cwd=home)
    assert i.argv[3:] == ["--x1", "v1"]  # extra_args always; the unattended ones not on an attended launch
    u = a.launch(profile="own", resume=None, prompt=None, unattended=True, cwd=home)
    assert u.argv[3:] == ["--x1", "v1", "--yolo"] and "--always-approve" not in u.argv


def test_the_composer_title_and_volatile_rows_off_the_captured_panes():
    """What the conformance fixtures do not hold (design §4.3 `composer`, `title`, TD-1637 slice 13): a history
    `❯` row is never the composer, a pane with no box reads None, a title not the tool's is no name, and the
    spinner and a running tool's timer are the rows the liveness clock masks."""
    import re

    a = GrokAdapter(binary="/x/grok")
    assert a.composer(["     ❯ a submitted prompt", "  ┃  1 (●) Yes, proceed"]) is None
    assert a.composer(["  ╭────╮", "  │ ❯ hi there   │", "  ╰────╯"]) == "hi there"
    assert a.composer(["  ╭────╮", "  ╰────╯"]) is None
    assert a.title("user@host: ~/d") is None and a.title("") is None and a.title("grok") is None
    assert a.title("⠹ - Responding - grok") is None
    assert a.title("⚠ Action Required - ⠴ - Run it… - My name - grok") == "My name"
    assert a.title("⠴ - Running: git log - x… - My name - grok") == "My name"
    assert not a.state_in_title and {"composer", "title"} == set(a.implements)
    rows = ["   ⠦ Responding… 2.0s", "   ◆ Remove a.txt… 11s", "   ◆ Build… 1m 5s", "     ◆ Thought for 0.0s"]
    masked = [r for r in rows if any(re.search(p, r) for p in a.volatile_rows)]
    assert masked == rows[:3]


def test_doctor_reads_each_grok_profiles_home_its_sign_in_and_a_key_in_the_environment(home, monkeypatch):
    """`ao doctor`'s row of each Grok profile (design §4.3 *Reads*, TD-1637 slice 14): its home, `auth.json` as its
    credentials, the login line as the cure; a key in the host agent's environment noted, and a profile with no home
    of its own read as the load's refusal, the one row."""
    from shiftlead import doctor

    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_CODE_XAI_API_KEY", raising=False)
    a = ad(home)
    rows = {r["profile"]: r for r in a.doctor_profiles()}
    assert set(rows) == {"gk", "asks", "close", "own"}
    gk = rows["gk"]
    assert gk["config_dir"] == str(home / "g") and gk["account"] == "paul" and gk["metered"] is False
    assert gk["credentials"] is None and gk["login"] == f"GROK_HOME={home / 'g'} {home / 'bin' / 'grok'} login"
    assert "note" not in gk
    (got,) = doctor.profiles([{"adapter": "grok", **gk}])[:1]
    assert f"`{gk['login']}`" in got["text"]  # the cure in the adapter's own words
    (home / "g").mkdir()
    (home / "g" / "auth.json").write_text("{}")
    monkeypatch.setenv("XAI_API_KEY", "k")
    (gk,) = [r for r in a.doctor_profiles() if r["profile"] == "gk"]
    assert gk["credentials"] is True and "XAI_API_KEY" in gk["note"] and "clears" in gk["note"]
    (home / "home" / "profiles.yml").write_text("profiles:\n  bare: {adapter: grok}\n")
    (row,) = a.doctor_profiles()
    assert set(row) == {"error"} and "needs a config_dir of its own" in row["error"]


FIX = Path(__file__).parent / "conformance" / "fixtures" / "grok" / "captured" / "transcripts"


def _place(home: Path, sid: str, cwd_dir: str = "%2Fr") -> Path:
    d = home / "g" / "sessions" / cwd_dir / sid
    d.mkdir(parents=True)
    data = (FIX / "panes.jsonl").read_bytes().replace(b"33333333-4444-4555-8666-777777777777", sid.encode())
    (d / "updates.jsonl").write_bytes(data)
    (d / "summary.json").write_bytes((FIX / "panes.summary.json").read_bytes())
    return d


def test_the_log_is_found_by_its_ids_own_directory_and_the_model_beside_it(home):
    """§4.3 *Reads* (TD-1637 slice 15): `sessions/*/<id>/updates.jsonl` under the profile's own home, whatever the
    cwd's directory is named; an id that could name another directory finds nothing; `summary.json`'s model."""
    a = ad(home)
    d = _place(home, "abc")
    assert a.transcript_path("abc", home / "anywhere", "gk") == d / "updates.jsonl"
    assert a.model_in_use("abc", home, "gk") == "grok-4.7"
    for bad in ("*", "a?c", "../g", "", ".."):
        assert a.transcript_path(bad, home, "gk") is None
    assert a.transcript_path("abc", home, "no-such-profile") is None and a.model_in_use("nope", home, "gk") is None
    (d / "summary.json").write_text("{}")
    assert a.model_in_use("abc", home, "gk") is None
    tr = a.read_transcript("abc", home, "gk")
    tool = next(e for e in tr.entries if e.kind == "tool" and e.name == "ask_user_question")
    assert tool.call == "Do you prefer red or blue?" and "Blue" in tool.result  # the question as its call line
    shell = next(e for e in tr.entries if e.name == "run_terminal_command")
    assert shell.call == "rm a.txt && mkdir made" and shell.result == "exit: 0\n"  # the terminal's own output line


def test_chunks_of_one_kind_join_until_something_else_comes(tmp_path):
    """A message streamed in parts reads as one entry; a chunk after another update starts a new one."""
    from shiftlead.adapters.grok import transcript

    def rec(ts, kind, text=None, **kw):
        up = {"sessionUpdate": kind, **({"content": {"type": "text", "text": text}} if text is not None else {}), **kw}
        return json.dumps({"timestamp": ts, "method": "session/update", "params": {"sessionId": "s", "update": up}})

    lines = [
        rec(1, "user_message_chunk", "go"),
        rec(2, "agent_thought_chunk", "a\n"),
        rec(3, "agent_thought_chunk", "b"),
        rec(4, "agent_message_chunk", "one "),
        rec(5, "agent_message_chunk", "two"),
        rec(6, "current_mode_update", currentModeId="plan"),
        rec(7, "agent_message_chunk", "three"),
    ]
    p = tmp_path / "updates.jsonl"
    p.write_text("\n".join(lines) + "\nnot json\n")
    tr = transcript.read(p)
    assert [(e.kind, e.text) for e in tr.entries] == [
        ("prompt", "go"),
        ("thought", "a\nb"),
        ("text", "one two"),
        ("text", "three"),
    ]
    assert tr.entries[1].lines == 2 and tr.turns == 1 and tr.first_at == "1970-01-01T00:00:01Z"


def test_a_profile_with_no_home_of_its_own_reads_nothing_and_the_default_profile_is_read(home):
    """A Grok profile never reads the person's `~/.grok`: one with no `config_dir` refuses the load, so nothing is
    found; `""` is the default profile's home."""
    a = ad(home)
    _place(home, "abc")
    assert a.transcript_path("abc", home, "") is not None  # the default, gk
    assert a.transcript_path("abc\0", home, "gk") is None  # a NUL in the id finds nothing, never raises
    (home / "home" / "profiles.yml").write_text(
        f"profiles:\n  bare: {{adapter: grok}}\n  gk: {{adapter: grok, config_dir: {home / 'g'}}}\n"
    )
    for p in ("bare", "gk", ""):
        assert a.transcript_path("abc", home, p) is None and a.read_transcript("abc", home, p) is None
        assert a.model_in_use("abc", home, p) is None


def test_paging_back_reads_each_turn_once(home):
    """`turns` and `before` (§4.3 `read_transcript`): one turn a page, each page's `before` the next page's cursor,
    None at the file's start, and a cursor inside a line reading that line whole."""
    a = ad(home)
    _place(home, "abc")
    pages, before = [], None
    while True:
        tr = a.read_transcript("abc", home, "gk", turns=1, before=before)
        pages.append([e.text for e in tr.entries if e.kind == "prompt"])
        if tr.before is None:
            break
        before = tr.before
    assert [p[0].split()[0] for p in pages] == ["then", "Write", "Use", "Run", "line"] and all(
        len(p) == 1 for p in pages
    )
    whole = a.read_transcript("abc", home, "gk")
    mid = a.read_transcript("abc", home, "gk", before=whole.size - 5)  # inside the last line
    assert [e.text for e in mid.entries][-1] == [e.text for e in whole.entries][-1]


def test_two_cwds_holding_one_id_read_the_newer_log(home):
    """`find` (§4.3 *Reads*, TD-1822): where two cwd directories hold one session id, the newer log is read."""
    import os

    a = ad(home)
    old = _place(home, "abc", "%2Fold")
    new = _place(home, "abc", "%2Fnew")
    os.utime(old / "updates.jsonl", (1_000_000, 1_000_000))
    os.utime(new / "updates.jsonl", (2_000_000, 2_000_000))
    assert a.transcript_path("abc", home, "gk") == new / "updates.jsonl"
    os.utime(old / "updates.jsonl", (3_000_000, 3_000_000))
    assert a.transcript_path("abc", home, "gk") == old / "updates.jsonl"


def test_a_failed_call_carries_its_result_and_both_lines_are_cut_to_their_caps(tmp_path):
    """A `tool_call_update` with `status: failed` completes its call as `completed` does (`DONE`), its text the
    tool entry's result; a result over `RESULT_CAP` and a call line over `CALL_CAP` are cut to them (TD-1822)."""
    from shiftlead.adapters.grok import transcript

    def rec(ts, up):
        return json.dumps({"timestamp": ts, "method": "session/update", "params": {"sessionId": "s", "update": up}})

    long_cmd = "x" * (transcript.CALL_CAP + 50)
    long_out = "y" * (transcript.RESULT_CAP + 50)
    lines = [
        rec(1, {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "go"}}),
        rec(2, {"sessionUpdate": "tool_call", "toolCallId": "c1", "title": "run", "rawInput": {"command": "false"}}),
        rec(
            3,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "c1",
                "status": "in_progress",
                "content": {"type": "text", "text": "interim"},
            },
        ),
        rec(
            4,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "c1",
                "status": "failed",
                "content": {"type": "text", "text": "exit: 1"},
            },
        ),
        rec(5, {"sessionUpdate": "tool_call", "toolCallId": "c2", "title": "run", "rawInput": {"command": long_cmd}}),
        rec(
            6,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "c2",
                "status": "completed",
                "content": {"type": "text", "text": long_out},
            },
        ),
    ]
    p = tmp_path / "updates.jsonl"
    p.write_text("\n".join(lines) + "\n")
    failed, long_call = [e for e in transcript.read(p).entries if e.kind == "tool"]
    assert failed.call == "false" and failed.result == "exit: 1"
    assert long_call.call == long_cmd[: transcript.CALL_CAP] and long_call.result == long_out[: transcript.RESULT_CAP]


def test_an_unreadable_log_reads_as_none(home):
    """`read_transcript` answers None, never raises, for a log found but unreadable (an `OSError` on read)."""
    import os

    if os.geteuid() == 0:
        pytest.skip("root reads a mode-0 file")
    a = ad(home)
    log = _place(home, "abc") / "updates.jsonl"
    log.chmod(0)
    try:
        assert a.transcript_path("abc", home, "gk") == log
        assert a.read_transcript("abc", home, "gk") is None
    finally:
        log.chmod(0o644)
