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
    assert not a.state_in_title and {"composer", "title"} == set(a.implements)
    rows = ["   ⠦ Responding… 2.0s", "   ◆ Remove a.txt and create made directory… 11s", "     ◆ Thought for 0.0s"]
    masked = [r for r in rows if any(re.search(p, r) for p in a.volatile_rows)]
    assert masked == rows[:2]
