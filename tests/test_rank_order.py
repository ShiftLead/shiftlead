"""TD-769 slice 1, design §4.4 *The Queue: cards, and the rank that orders them*: the pick order is
the rank. The home's ledger reading carries each entry's `key`, `lined`, `card_key` and `order` from
the vendored ledgerboard and the rank file beside the ledger, and `ao repo` lists in that order — the
order `scripts/ledger.py --pickable` prints from the same rank file."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sessionorc import ledger
from sessionorc import ledgerboard as lb
from shiftlead import cli

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ledger.py"

LEDGER = """# Technical Debt

## TD-010: a low debt

**Priority:** Low

## TD-011: a medium feature

**Priority:** Medium
**Type:** feature

## TD-012: a medium debt

**Priority:** Medium

## TD-013: a high debt

**Priority:** High

## TD-014: a high feature after TD-013

**Priority:** High
**Type:** feature
**Blocked by:** TD-013

## TD-015: another medium debt

**Priority:** Medium
"""


def _by_id(text: str, rank_text: str | None = None, repo: str = "") -> dict[str, dict]:
    return {e["id"]: e for e in ledger.entries(text, "", rank_text=rank_text, repo=repo)}


def _order(got: dict[str, dict]) -> list[str]:
    return [t for t, _ in sorted(got.items(), key=lambda kv: kv[1]["order"])]


def test_implicit_keys_sort_by_priority_then_type_then_id():
    got = _by_id(LEDGER, repo="shiftlead")
    assert got["TD-012"]["key"] == "2|0|000012|shiftlead" and not got["TD-012"]["lined"]
    assert got["TD-011"]["key"] == "2|1|000011|shiftlead"
    # TD-014 rides TD-013's card (its key the card's best), after the entry it is blocked by
    assert got["TD-014"]["card_key"] == got["TD-013"]["key"]
    assert _order(got) == ["TD-013", "TD-014", "TD-012", "TD-015", "TD-011", "TD-010"]
    assert _by_id(LEDGER)["TD-012"]["key"] == "2|0|000012"  # no repo, no last part (ledger.py's)


def test_a_rank_line_moves_its_card_and_reads_lined():
    # TD-010 dragged to the top: a key below every implicit one
    rank = lb.set_rank("", {"TD-010": lb.midpoint(None, "1|0|000013")})
    got = _by_id(LEDGER, rank, "shiftlead")
    assert got["TD-010"]["lined"] and got["TD-010"]["key"] == rank.splitlines()[-1].split(": ")[1]
    assert _order(got)[0] == "TD-010"


def test_a_lined_card_keeps_its_place_through_a_priority_edit():
    rank = lb.set_rank("", {"TD-015": lb.midpoint("1|0|000013", "1|1|000014")})
    before = _order(_by_id(LEDGER, rank))
    raised = LEDGER.replace("## TD-010: a low debt\n\n**Priority:** Low", "## TD-010: a low debt\n\n**Priority:** High")
    after = _order(_by_id(raised, rank))
    assert before.index("TD-015") == 2 and after.index("TD-015") == after.index("TD-013") + 2
    # the undragged one moved with its Priority; the lined one kept its key
    assert after.index("TD-010") < before.index("TD-010")
    assert _by_id(raised, rank)["TD-015"]["key"] == _by_id(LEDGER, rank)["TD-015"]["key"]


def test_the_reading_reads_the_rank_file_beside_the_ledger(tmp_path):
    root = tmp_path / "Shiftlead"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text(LEDGER, encoding="utf-8")
    key = lb.midpoint(None, "1|0|000013|shiftlead")
    (root / lb.rank_path("docs/technical_debt.md")).write_text(lb.set_rank("", {"TD-011": key}), encoding="utf-8")
    got = {e["id"]: e for e in ledger.reading(root, datetime.now(UTC), with_history=False)["entries"]}
    assert got["TD-011"] == {**got["TD-011"], "key": key, "lined": True, "order": 0}
    assert got["TD-012"]["key"].endswith("|shiftlead")  # the checkout's name, lower-cased


def test_ao_repos_order_is_ledger_py_pickables_from_the_rank_file_alone(tmp_path):
    """For single-repo cards the home's order is the script's: one rank file, one ledgerboard."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "technical_debt.md").write_text(LEDGER, encoding="utf-8")
    rank = lb.set_rank("", {"TD-010": lb.midpoint("1|0|000013", "2|0|000012"), "TD-011": lb.midpoint(None, "1")})
    (tmp_path / "docs" / "technical_debt_rank.yml").write_text(rank, encoding="utf-8")
    cp = subprocess.run(
        [sys.executable, str(SCRIPT), "--pickable", "--json"],
        cwd=tmp_path, env={"DEV_CADENCE_REG_DIR": str(tmp_path / "no-roster"), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    script = [e["id"] for e in json.loads(cp.stdout)["pickable"]]
    home = ledger.reading(tmp_path, datetime.now(UTC), with_history=False)["entries"]
    picked = sorted((e for e in home if e["pickable"] == "yes"), key=cli._pick_key)
    assert [e["id"] for e in picked] == script
    assert script[:2] == ["TD-011", "TD-013"] and script.index("TD-010") == script.index("TD-013") + 1


def test_ao_repo_falls_back_to_cadences_order_on_a_reading_with_no_order():
    old = [{"id": "TD-1", "priority": "low"}, {"id": "TD-2", "priority": "high", "type": "feature"},
           {"id": "TD-3", "priority": "high"}]  # fmt: skip
    assert [e["id"] for e in sorted(old, key=cli._pick_key)] == ["TD-3", "TD-2", "TD-1"]
