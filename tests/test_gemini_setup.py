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

from sessionorc import adapters, agent_tick, containers
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
    # stale for a setting other than the wake: hooks still run, and nothing is said of the wake (TD-1007)
    assert stale.startswith("The Gemini layer is stale: the installed layer is not this install's. Run this once")
    assert "no hooks" not in stale and "wakes no" not in stale


def _layer_without_the_wake() -> dict:
    doc = json.loads(gemini.wanted_file().read_text())
    del doc["tools"], doc["experimental"]
    return doc


async def test_a_stale_layer_without_the_wake_says_so_in_its_note(home, start):
    """TD-1007 (design §4.3 *The second adapter*): a layer installed before the two settings is stale,
    and its note says a background end wakes no Gemini session and the foreground watch is not
    refused; the key carries the reading, so the wording refreshes once the layer holds them."""
    gemini.write_layer()
    gemini.MACHINE_LAYER.write_text(json.dumps(_layer_without_the_wake()))
    note = GeminiAdapter(binary="gemini").setup_note()
    assert note["key"].endswith(":stale:no-wake")
    assert note["text"].startswith(
        "The Gemini layer is stale: the installed layer is not this install's. Until it is reinstalled, a "
        "background command's end wakes no Gemini session launched under it, and its foreground CI watch is "
        "not refused. Run this once on this machine:"
    )
    assert "no hooks" not in note["text"]
    (said,) = await start()
    assert "wakes no Gemini session" in said


def test_a_launch_says_in_its_env_whether_its_layer_wakes(home):
    """TD-1007: a layer written from `layer_settings()` puts `SHIFTLEAD_GEMINI_WAKES=1` in the launch's
    env; a stale copy without the two settings does not, and `layer_wakes` reads each layer so."""
    from shiftlead.adapters.gemini import hook

    ad = GeminiAdapter(binary="gemini")
    gemini.MACHINE_LAYER.write_text(gemini.write_layer().read_text())
    assert gemini.layer_wakes()
    assert ad.launch(profile="gem", resume=None, prompt=None, unattended=True, cwd=home).env[hook.WAKES_ENV] == "1"
    gemini.MACHINE_LAYER.write_text(json.dumps(_layer_without_the_wake()))
    assert not gemini.layer_wakes()
    assert hook.WAKES_ENV not in ad.launch(profile="gem", resume=None, prompt=None, unattended=True, cwd=home).env


def test_layer_wakes_is_false_for_a_missing_unreadable_or_keyless_layer(home, tmp_path):
    wanted = gemini.write_layer()
    assert gemini.layer_wakes(wanted)
    assert not gemini.layer_wakes(tmp_path / "nowhere.json")  # missing
    assert not gemini.layer_wakes(tmp_path)  # unreadable: a directory
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert not gemini.layer_wakes(bad)
    bad.write_text("[1, 2]")
    assert not gemini.layer_wakes(bad)
    bad.write_text(
        json.dumps(
            {"tools": {"shell": {"backgroundCompletionBehavior": "silent"}}, "experimental": {"modelSteering": True}}
        )
    )
    assert not gemini.layer_wakes(bad)
    bad.write_text(
        json.dumps(
            {"tools": {"shell": {"backgroundCompletionBehavior": "inject"}}, "experimental": {"modelSteering": "true"}}
        )
    )
    assert not gemini.layer_wakes(bad)
    gemini.MACHINE_LAYER.write_text(wanted.read_text())
    assert gemini.layer_wakes()  # the default path, read at call time


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


async def test_one_agent_reads_again_on_a_profiles_change_or_an_hour_on_and_not_between(home):
    """The throttle: a second read with `profiles.yml` unchanged inside the hour reads nothing, so an
    install meanwhile is not seen; an hour on, it is, and the key is forgotten for a later undoing."""
    store = home / "home" / "setup_notes.json"
    a = HostAgent(tmux=Tmux(socket_name=private_socket_name()))
    try:
        await a._setup_notes()
        assert list(json.loads(store.read_text())) == ["gemini"]
        gemini.MACHINE_LAYER.write_text(gemini.wanted_file().read_text())  # installed
        await a._setup_notes()
        assert list(json.loads(store.read_text())) == ["gemini"]  # not read: nothing changed it knows of
        a._setup_read_at -= agent_tick.SETUP_EVERY
        await a._setup_notes()
        assert json.loads(store.read_text()) == {}  # read: ok, forgotten
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
