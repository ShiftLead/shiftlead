"""TD-875 slice 2 (design §4.3 *The second adapter: Gemini CLI* — *The person meets the step at setup*, *A
container node needs no sudo*): the host agent tells the person the Gemini layer's line once per wanted
copy and reading, and a container node's root stage installs the node's own wanted copy root-owned."""

from __future__ import annotations

import json
import os
import time

import pytest
from conftest import kill_private_server, private_socket_name
from test_gemini_adapter import rooted

from sessionorc import adapters, containers
from sessionorc.agent import HostAgent
from sessionorc.tmux import Tmux
from shiftlead.adapters import gemini
from shiftlead.adapters.gemini import GeminiAdapter


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text("profiles:\n  gem: {adapter: gemini}\n")
    machine = tmp_path / "etc" / "gemini-settings.json"
    machine.parent.mkdir()
    monkeypatch.setattr(gemini, "MACHINE_LAYER", machine)
    monkeypatch.setattr(gemini, "_lstat", rooted())
    adapters.names()  # loaded, then Gemini beside them: its entry point waits for TD-785
    monkeypatch.setitem(adapters._REGISTRY, "gemini", GeminiAdapter(binary="gemini"))
    return tmp_path


@pytest.fixture
def start(home):
    """A host agent's start: a fresh agent each call, its first `_setup_notes` read; what it noted."""
    made: list[HostAgent] = []

    async def run() -> list[str]:
        a = HostAgent(tmux=Tmux(socket_name=private_socket_name()))
        made.append(a)
        before = len(a.person_inbox)  # the inbox on disk: the earlier starts' notes
        await a._setup_notes()
        return [e.text for e in a.person_inbox[before:] if e.from_ == "system" and "Gemini layer" in e.text]

    yield run
    for a in made:
        kill_private_server(a.tmux)


def touch(p):
    os.utime(p, ns=(time.time_ns(), time.time_ns() + 10**9))


async def test_a_start_with_no_layer_notes_the_line_once_and_again_when_the_copy_or_reading_changes(home, start):
    (note,) = await start()
    first = note.split("\n\n")[0]
    assert first == (
        "The Gemini layer is not installed, so a Gemini session gets no hooks and is refused. "
        "Run this once on this machine:"
    )
    assert gemini.INSTALL_LINE in note
    assert await start() == []  # the same wanted copy, the same reading: said once
    gemini.MACHINE_LAYER.write_text(gemini.wanted_file().read_text())  # the person ran the line
    assert await start() == []  # ok: nothing to say, and the key is forgotten
    gemini.MACHINE_LAYER.unlink()
    (again,) = await start()  # installed, then gone: said again
    assert "not installed" in again
    doc = json.loads(gemini.wanted_file().read_text())
    gemini.MACHINE_LAYER.write_text(json.dumps(doc))
    assert await start() == []
    gemini.LAYER_SETTINGS["ui"]["hideTips"] = False  # a build that changed the settings: a new wanted copy
    try:
        (stale,) = await start()
    finally:
        gemini.LAYER_SETTINGS["ui"]["hideTips"] = True
    assert stale.startswith("The Gemini layer is stale, so a Gemini session gets no hooks. Run this once")


async def test_no_gemini_profile_no_note_and_a_profile_gained_is_read_on_the_next_tick(home, start):
    profiles = home / "home" / "profiles.yml"
    profiles.write_text("profiles:\n  claude: {adapter: claude-code}\n")
    a = HostAgent(tmux=Tmux(socket_name=private_socket_name()))
    try:
        await a._setup_notes()
        assert [e for e in a.person_inbox if "Gemini layer" in e.text] == []
        await a._setup_notes()  # `profiles.yml` unchanged: not read again
        profiles.write_text("profiles:\n  claude: {adapter: claude-code}\n  gem: {adapter: gemini}\n")
        touch(profiles)
        await a._setup_notes()
        assert len([e for e in a.person_inbox if "Gemini layer" in e.text]) == 1
    finally:
        kill_private_server(a.tmux)


def test_the_containers_root_stage_installs_the_nodes_own_layer_root_owned(home, tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "layer-9.json").write_text("{}")  # an earlier build's
    layers = containers.write_layers(ctx)
    assert layers == [(str(gemini.MACHINE_LAYER), "layer-0.json")] and not (ctx / "layer-9.json").exists()
    doc = json.loads((ctx / "layer-0.json").read_text())
    cmd = doc["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert cmd == "/shiftlead/venv/bin/shiftlead-hook --adapter gemini"  # the node's hook, never the home's
    df = containers.dockerfile_text("base", "dev", [("/etc/shiftlead/gemini-settings.json", "layer-0.json")])
    root = df.split("USER root")[1].split("USER dev")[0]
    assert "COPY layer-0.json /tmp/shiftlead-layer-0.json" in root
    assert (
        "RUN install -d -o root -g root -m 0755 /etc/shiftlead && install -o root -g root -m 0644 "
        "/tmp/shiftlead-layer-0.json /etc/shiftlead/gemini-settings.json && rm -f /tmp/shiftlead-layer-0.json"
    ) in root
    assert df.rstrip().endswith("USER dev")
