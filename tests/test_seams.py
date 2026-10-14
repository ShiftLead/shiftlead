"""§4.4 *Repo facts* **The seams** (§5 *The seams*; TD-584, built by TD-591 slice 1): the host agent's
reading of what a repo has — its ledger parsing through ledgerboard and its major, and `board:`,
`gate:` and `worktree_setup:` each set, defaulted or absent — on the repo reading as `seams`."""

from __future__ import annotations

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
    for key in ("board", "gate", "worktree_setup"):
        assert got[key] == {"state": "absent", "value": None}, key


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
    assert got["gate"] == {"state": "defaulted", "value": cadence.DEFAULT_GATE}
    assert got["worktree_setup"] == {"state": "defaulted", "value": gitinfo.HYDRATE}
    (root / ".shiftlead.yml").write_text(
        "ledger: notes/debt.md\nboard: notes/board.md\ngate: make gate PR={pr}\nworktree_setup: make setup\n"
    )
    got = seams.reading(root)
    assert got["board"] == {"state": "set", "value": "notes/board.md"}
    assert got["gate"] == {"state": "set", "value": "make gate PR={pr}"}
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
