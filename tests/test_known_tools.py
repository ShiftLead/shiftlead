"""The Tools page's known tools without an adapter (design §4.2b, TD-1971)."""

from __future__ import annotations

from pathlib import Path

from sessionorc import adapters
from shiftlead.adapters.known import KNOWN_TOOLS


def test_known_tools_are_read_through_the_registry_and_found_on_the_path_alone(tmp_path, monkeypatch):
    stub = tmp_path / "codex"
    stub.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")  # never run
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    rows = {r["name"]: r for r in adapters.known_tools()}
    assert set(rows) == {r["name"] for r in KNOWN_TOOLS}
    assert rows["codex"]["path"] == str(stub) and rows["opencode"]["path"] is None


def test_a_row_whose_tool_has_an_adapter_is_the_adapters(monkeypatch):
    monkeypatch.setattr(adapters, "names", lambda: ["codex", "shell"])
    assert "codex" not in {r["name"] for r in adapters.known_tools()}


def test_core_names_no_known_tool():
    src = Path(adapters.__file__).read_text(encoding="utf-8").lower()
    assert all(f'"{r["name"]}"' not in src for r in KNOWN_TOOLS)
