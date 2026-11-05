"""TD-1377, design §4.4 *What waits on the person*: the merge gate refuses a `decision (paul)` a PR adds with no
board item to answer it. The gate is the pinned agent-cadence's `check_cadence.py`, whose *gates* row runs
ledgerboard's `uncovered_decisions()` (its target design §1.2, §7.2 step 4; SPEC *The merge gate's verdicts*) —
ShiftLead carries no copy and writes no second check. This runs that row over a repo laid out as this one is (the
v2 ledger `docs/ledger/` with this checkout's own preamble, the board `docs/user_attention.md` with its `People:`
line), so a pin that drops the row, or a layout the row no longer reads as refusing, fails here rather than letting
a gate that asks nobody merge."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from conftest import pinned_script

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "docs/ledger/TD-001.md"
BOARD = "docs/user_attention.md"
HEAD = """## TD-001: A thing the person must decide

**Priority:** Medium
**Type:** debt
**Added:** 2026-11-05
**Owner:** grinder
**Kind:** build
**Status:** Open
{blocked}**Location:** `src/sessionorc/queue.py`

**Why:** a reason.
{ask}
**Fix:** a fix.
"""
ASK = "\n**Ask:** Go ahead with the fix?\n"
BOARD_HEAD = """# User Attention Board

People: paul

## Needs the user

"""
ITEM = (
    "- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Go ahead with the fix? "
    "Context: TD-001 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.\n"
)


def _gate():
    path = pinned_script("check_cadence.py")
    sys.path.insert(0, str(path.parent))  # its siblings (ledger.py, ledgerboard/), as it imports them itself
    try:
        spec = importlib.util.spec_from_file_location("ac_check_cadence_gates", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", msg)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> Path:
    """origin (bare) and a clone whose `origin/main` holds the base: the ledger's real preamble, one open entry
    with no gate, and a board that lists Paul on `People:` with no item."""
    origin, repo = tmp_path / "origin.git", tmp_path / "shiftlead"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "remote", "add", "origin", str(origin))
    readme = (ROOT / "docs/ledger/README.md").read_text()
    _commit(repo, {"docs/ledger/README.md": readme, ENTRY: HEAD.format(blocked="", ask=""), BOARD: BOARD_HEAD}, "base")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin")
    return repo


def _row(gate, repo: Path, files: dict[str, str]) -> dict:
    _git(repo, "checkout", "-q", "-B", "td001", "origin/main")
    sha = _commit(repo, files, "TD-001: hold on the person")
    pr = {"state": "open", "head_sha": sha, "files": sorted(files)}
    return gate.row_gates(pr, str(repo))


def test_a_decision_added_with_no_board_item_fails_the_gate_and_one_with_its_item_passes(tmp_path):
    gate = _gate()
    repo = _repo(tmp_path)
    held = HEAD.format(blocked="**Blocked by:** decision (paul)\n", ask=ASK)

    bare = _row(gate, repo, {ENTRY: held})
    assert bare["status"] == "fail", bare
    assert "TD-001 gains decision (paul)" in bare["detail"] and "no open decide item" in bare["detail"], bare

    asked = _row(gate, repo, {ENTRY: held, BOARD: BOARD_HEAD + ITEM})
    assert asked["status"] == "pass", asked


def test_a_new_gated_decide_item_none_of_whose_answers_lifts_fails_the_gate(tmp_path):
    """The row's other refusal, as §4.4 says: two answers or more and each that ends the wait in `Lifts:`, else
    only `Go` lifts and the gate refuses a decide item with no lifting answer."""
    gate = _gate()
    repo = _repo(tmp_path)
    held = HEAD.format(blocked="**Blocked by:** decision (paul)\n", ask=ASK)
    no_lift = ITEM.replace(" Lifts: Yes.", "")
    got = _row(gate, repo, {ENTRY: held, BOARD: BOARD_HEAD + no_lift})
    assert got["status"] == "fail", got
    assert "none of its answers lifts it" in got["detail"], got
