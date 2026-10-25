"""§4.4 *Repo facts* **The seams** (§5 *The seams*; TD-584, built by TD-591 slice 1): the host agent's
reading of what a repo has — its ledger parsing through ledgerboard and its major, `board:` and
`worktree_setup:` each set, defaulted or absent, whether it is served (TD-1011: dev-cadence's tree, the
gate and the ledger) and its warnings — on the repo reading as `seams`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import cadence, gitinfo, seams, workorders

LEDGER = "# Technical debt\n\n## TD-001: One thing\n\n**Priority:** Low\n**Status:** Open.\n\n---\n"


def make(tmp_path: Path, name: str = "r", ledger: str | None = LEDGER) -> Path:
    root = tmp_path / name
    (root / "docs").mkdir(parents=True)
    if ledger is not None:
        (root / "docs" / "technical_debt.md").write_text(ledger, encoding="utf-8")
    return root


@pytest.mark.unit
def test_a_repo_with_only_a_ledger_has_every_other_seam_absent(tmp_path):
    root = make(tmp_path)
    got = seams.reading(root)
    assert got["ledger"] == {"path": "docs/technical_debt.md", "state": "ok", "major": 1, "entries": 1, "why": None}
    for key in ("board", "worktree_setup"):
        assert got[key] == {"state": "absent", "value": None}, key
    assert "gate" not in got, "the gate is no seam of the file's (TD-1011)"


@pytest.mark.unit
def test_dev_cadences_files_are_the_defaults_and_shiftlead_yml_sets_each(tmp_path):
    root = make(tmp_path)
    (root / workorders.BOARD).write_text("# Board\n")
    (root / "scripts").mkdir()
    (root / cadence.SCRIPT).write_text("")
    hydrate = root / gitinfo.HYDRATE
    hydrate.write_text("#!/bin/sh\n")
    hydrate.chmod(0o755)
    got = seams.reading(root)
    assert got["board"] == {"state": "defaulted", "value": "docs/user_attention.md"}
    assert got["worktree_setup"] == {"state": "defaulted", "value": gitinfo.HYDRATE}
    (root / ".shiftlead.yml").write_text(
        "ledger: notes/debt.md\nboard: notes/board.md\ngate: make gate PR={pr}\nworktree_setup: make setup\n"
    )
    got = seams.reading(root)
    assert got["board"] == {"state": "set", "value": "notes/board.md"}
    assert cadence.gate(root) == cadence.DEFAULT_GATE, "a gate: key is read by nothing"
    assert got["worktree_setup"] == {"state": "set", "value": "make setup"}
    assert got["ledger"]["state"] == "absent" and got["ledger"]["path"] == "notes/debt.md"
    assert got["ledger"]["why"] == "no ledger at notes/debt.md"


@pytest.mark.unit
def test_a_ledger_that_is_newer_or_unreadable_says_why(tmp_path):
    root = make(tmp_path, ledger="# Technical debt\n\nLedgerboard: 2\n\n" + LEDGER.split("\n\n", 1)[1])
    got = seams.ledger(root)
    assert got["state"] == "newer" and got["major"] == 2 and got["entries"] is None
    assert "Ledgerboard: 2, newer than this ledgerboard.py reads (1)" in got["why"]
    (root / "docs" / "technical_debt.md").write_bytes(b"\xff\xfe not text")
    got = seams.ledger(root)
    assert got["state"] == "unreadable" and got["why"].startswith("docs/technical_debt.md")
    assert seams.ledger(make(tmp_path, "bare", None))["state"] == "absent"
    for outside in ("/etc/hostname", "../r/docs/technical_debt.md"):
        (root / ".shiftlead.yml").write_text(f"ledger: {outside}\n")
        got = seams.ledger(root)
        assert got["state"] == "unreadable" and got["why"] == f"ledger: {outside} is not a path inside the repo"


@pytest.mark.unit
def test_the_repo_reading_carries_the_seams_read_on_its_own_cadence(tmp_path):
    from sessionorc.agent_tick import TickMixin

    root = make(tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    r = str(root)
    first = TickMixin._read_repos([r], {}, set())
    assert first[r]["seams"]["board"]["state"] == "absent"
    (root / ".shiftlead.yml").write_text("board: notes/board.md\n")
    # a pass that is not the repo reading's own keeps the last seams; the five-minute one reads them again
    assert TickMixin._read_repos([r], first, set())[r]["seams"]["board"]["state"] == "absent"
    assert TickMixin._read_repos([r], first, {r})[r]["seams"]["board"] == {"state": "set", "value": "notes/board.md"}


@pytest.mark.unit
def test_a_repo_read_that_fails_keeps_the_last_seams(tmp_path, monkeypatch):
    from sessionorc.agent_tick import TickMixin

    root = make(tmp_path)
    r = str(root)
    first = TickMixin._read_repos([r], {}, set())

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(TickMixin, "_read_repo", staticmethod(boom))
    got = TickMixin._read_repos([r], first, {r})[r]
    assert got["seams"] == first[r]["seams"] and "error" in got["ledger"]


def served(tmp_path: Path, name: str = "r") -> Path:
    """A repo holding all three: dev-cadence's lock, the gate and a ledger."""
    root = make(tmp_path, name)
    (root / "scripts").mkdir()
    (root / cadence.SCRIPT).write_text("")
    (root / "docs" / "cadence-sync.lock").write_text("source: x\ncommit: abc\nfiles_commit: abc123\n")
    return root


@pytest.mark.unit
def test_a_repo_lacking_each_of_the_three_is_unserved_in_its_words(tmp_path):
    """TD-1011, §5 *The seams*: dev-cadence's tree, the gate and the ledger, each lack in its fixed words
    with its cure; with all three the repo is served."""
    root = served(tmp_path)
    assert seams.reading(root)["serve"] == {"ok": True, "lacks": []}
    cure = f"`<dev-cadence>/sync.sh {root}`, then a PR"
    (root / "docs" / "cadence-sync.lock").unlink()
    assert seams.reading(root)["serve"] == {
        "ok": False,
        "lacks": [{"key": "cadence", "words": f"unserved: no dev-cadence (no docs/cadence-sync.lock) — {cure}"}],
    }
    (root / "docs" / "cadence-sync.lock").write_text("source: x\n")
    words = seams.reading(root)["serve"]["lacks"][0]["words"]
    assert words == f"unserved: dev-cadence's lock does not parse — it has no files_commit line — {cure}"
    (root / "docs" / "cadence-sync.lock").write_bytes(b"\xff\xfe")
    assert seams.reading(root)["serve"]["lacks"][0]["words"].startswith(
        "unserved: dev-cadence's lock does not parse — "
    )
    (root / "docs" / "cadence-sync.lock").write_text("files_commit: abc123\n")
    (root / cadence.SCRIPT).unlink()
    assert seams.reading(root)["serve"]["lacks"] == [
        {"key": "gate", "words": f"unserved: no gate (no scripts/check_cadence.py) — {cure}"}
    ]
    (root / cadence.SCRIPT).write_text("")
    (root / "docs" / "technical_debt.md").unlink()
    assert seams.reading(root)["serve"]["lacks"] == [
        {"key": "ledger", "words": f"unserved: no ledger at docs/technical_debt.md — {cure}"}
    ]
    (root / "docs" / "technical_debt.md").write_bytes(b"\xff\xfe")
    (lack,) = seams.reading(root)["serve"]["lacks"]
    assert lack["key"] == "ledger" and lack["words"].startswith(
        "unserved: the ledger at docs/technical_debt.md does not parse — "
    )
    assert "sync.sh" not in lack["words"], "no adoption cures a ledger that does not parse"


@pytest.mark.unit
def test_dev_cadences_source_is_served_with_no_lock_and_its_gate_under_files(tmp_path):
    root = make(tmp_path, "dev-cadence")
    (root / "sync.sh").write_text("#!/bin/sh\n")
    (root / "files" / "scripts").mkdir(parents=True)
    got = seams.reading(root)
    assert got["source"] is True
    words = f"unserved: no gate (no files/scripts/check_cadence.py) — `<dev-cadence>/sync.sh {root}`, then a PR"
    assert got["serve"]["lacks"] == [{"key": "gate", "words": words}]
    (root / "files" / cadence.SCRIPT).write_text("")
    assert seams.reading(root)["serve"] == {"ok": True, "lacks": []}
    assert cadence.gate(root) == "python3 files/scripts/check_cadence.py --pr {pr} --json"
    assert seams.reading(served(tmp_path, "plain"))["source"] is False


@pytest.mark.unit
def test_the_three_warnings_and_the_session_start_commands_are_read(tmp_path):
    root = served(tmp_path)
    assert seams.reading(root)["warnings"] == ["no board at docs/user_attention.md", "no worktree setup"]
    (root / ".shiftlead.yml").write_text("board: notes/board.md\n")
    assert seams.reading(root)["warnings"][0] == "no board at notes/board.md", "a board set but not there"
    (root / ".shiftlead.yml").unlink()
    (root / workorders.BOARD).write_text("# Board\n")
    hydrate = root / gitinfo.HYDRATE
    hydrate.write_text("#!/bin/sh\n")
    hydrate.chmod(0o755)
    assert seams.reading(root)["warnings"] == [], "no .git directory: the shim is not read"
    (root / ".git" / "hooks").mkdir(parents=True)
    shim = f"dev-cadence's per-clone setup not run in this checkout — `<dev-cadence>/sync.sh {root}`"
    assert seams.reading(root)["warnings"] == [shim]
    (root / ".git" / "hooks" / "pre-push").write_text(f"#!/bin/sh\n# {seams.SHIM_MARKER} — written by x\n")
    assert seams.reading(root)["warnings"] == []
    assert seams.reading(root)["session_start"] == []
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "run me"}]}]}})
    )
    assert seams.reading(root)["session_start"] == ["run me"]
    (root / ".claude" / "settings.json").write_text("{not json")
    assert seams.reading(root)["session_start"] == []
