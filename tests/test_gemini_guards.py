# ruff: noqa: F811 — `home` and `start` are test_gemini_setup's fixtures, imported and named as parameters
"""TD-887 (the test audit of #2110 and #2113, TD-875 slices 1 and 2): the Gemini layer's guards, each
under a test that fails when it is reverted — the symlink bound, the atomic and same-bytes write, the
unreadable layer's readings, the setup note's words, key and fallbacks, and one broken adapter beside
the rest in the tick's note and the node's build (design §4.3 *The second adapter: Gemini CLI*)."""

from __future__ import annotations

import json
import os

import pytest
from conftest import kill_private_server, private_socket_name
from test_gemini_adapter import rooted
from test_gemini_setup import home, start  # noqa: F401 — the fixtures, shared

from sessionorc import adapters, containers
from sessionorc.agent import HostAgent
from sessionorc.tmux import Tmux
from shiftlead.adapters import gemini
from shiftlead.adapters.gemini import GeminiAdapter


class Broken:
    """An adapter whose optional readings raise."""

    name = "broken"

    def setup_note(self):
        raise RuntimeError("broken setup note")

    def machine_layers(self, hook):
        raise RuntimeError("broken machine layer")


def test_a_symlink_loop_reads_loops_within_the_bound(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.symlink_to(b)
    b.symlink_to(a)
    calls = []
    inner = rooted()

    def lstat(p):
        calls.append(p)
        if len(calls) > 100:  # past the bound: fail, never spin
            raise AssertionError("the symlink loop was not bounded")
        return inner(p)

    monkeypatch.setattr(gemini, "_lstat", lstat)
    assert gemini.insecure(a).endswith(" loops") and len(calls) <= 41


def test_a_failed_write_leaves_the_old_copy_whole_and_the_same_bytes_are_not_written(home, monkeypatch):
    p = gemini.wanted_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("old")

    def refuse(src, dst):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(gemini.os, "replace", refuse)
        with pytest.raises(OSError, match="disk full"):
            gemini.write_layer()
    assert p.read_text() == "old"  # an overlapping launch never reads half a file
    gemini.write_layer()
    os.utime(p, ns=(10**9, 10**9))
    gemini.write_layer()  # the same bytes: left alone
    assert p.stat().st_mtime_ns == 10**9


def test_an_unreadable_layer_reads_missing_and_invalid_json_reads_unresolved(home):
    m = gemini.MACHINE_LAYER
    m.mkdir()  # a directory where the file should be: unreadable
    r = gemini.machine_reading()
    assert r["state"] == "missing" and r["why"]
    m.rmdir()
    m.write_text("{not json")
    r = gemini.machine_reading()
    assert r["state"] == "unresolved" and r["why"].startswith("unreadable: ")


def test_an_insecure_layers_note_says_not_root_owned(home, monkeypatch):
    gemini.MACHINE_LAYER.write_text(gemini.write_layer().read_text())
    monkeypatch.setattr(gemini, "_lstat", rooted(mine=str(gemini.MACHINE_LAYER)))
    note = GeminiAdapter(binary="gemini").setup_note()
    assert note["key"].endswith(":insecure")
    assert note["text"].startswith(
        "The Gemini layer is not root-owned, so a Gemini session gets no hooks and is refused."
    )


def test_a_profiles_file_that_does_not_load_gives_no_note(home):
    (home / "home" / "profiles.yml").write_text("default: nowhere\nprofiles:\n  gem: {adapter: gemini}\n")
    assert GeminiAdapter(binary="gemini").setup_note() is None


async def test_a_changed_wanted_copy_with_the_same_reading_is_noted_again(home, start):
    (first,) = await start()
    key = json.loads((home / "home" / "setup_notes.json").read_text())["gemini"]
    digest, reading = key.split(":")
    assert len(digest) == 12 and reading == "missing"
    gemini.LAYER_SETTINGS["ui"]["hideTips"] = False  # a new wanted copy; the layer still missing
    try:
        (again,) = await start()
    finally:
        gemini.LAYER_SETTINGS["ui"]["hideTips"] = True
    assert "not installed" in again


async def test_a_broken_adapter_and_a_corrupt_store_hold_up_no_note(home, start, monkeypatch):
    monkeypatch.setitem(adapters._REGISTRY, "broken", Broken())
    (home / "home" / "setup_notes.json").write_text("{corrupt")
    (note,) = await start()
    assert "not installed" in note


async def test_no_profiles_file_reads_nothing_and_raises_nothing(home):
    (home / "home" / "profiles.yml").unlink()
    a = HostAgent(tmux=Tmux(socket_name=private_socket_name()))
    try:
        await a._setup_notes()
        await a._setup_notes()
        assert [e for e in a.person_inbox if "Gemini layer" in e.text] == []
    finally:
        kill_private_server(a.tmux)


def test_a_broken_adapters_layer_is_left_out_of_the_node_not_the_node(home, tmp_path, monkeypatch):
    monkeypatch.setitem(adapters._REGISTRY, "broken", Broken())
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    assert containers.write_layers(ctx) == [(str(gemini.MACHINE_LAYER), "layer-0.json")]
