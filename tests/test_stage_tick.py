"""One repo's stage pass as the tick calls it (design §4.9c *The home acts only where no session will*, TD-2051): a
switched team's flow found and checked, its records read against it, and no session started before TD-2065."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sessionorc import paths
from shiftlead import flow3, stage_end, stage_merge, stage_tick
from shiftlead.stage_tick import Kept, flow_now, run
from shiftlead.stagerecord import StageStore

README = "# Ledger\n\nLedgerboard: 2\n"
ENTRY = "## TD-7: Entry 7\n\n**Priority:** Low\n**Owner:** grinder\n**Kind:** build\n**Status:** Open\n\n**Why:** x.\n"
TEAM = {"repo": "r", "host": "h", "flow": "build"}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def root(tmp_path: Path) -> Path:
    origin, root = tmp_path / "o.git", tmp_path / "r"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", str(origin))
    for rel, text in {"docs/ledger/README.md": README, "docs/ledger/TD-7.md": ENTRY}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "ledger")
    git(root, "push", "-q", "origin", "main")
    StageStore(root).ensure_branch()
    return root


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The person read as given, and a gate and land that record that they were made rather than run the cadence."""
    made: list[str] = []

    def gate_and_land(where: Any) -> tuple[Any, Any]:
        made.append(str(where))
        return (lambda _pr, _head: None), (lambda _pr, _head: None)

    monkeypatch.setattr(stage_end, "_person_of", lambda _root: "paul")
    monkeypatch.setattr(stage_merge, "gate_and_land", gate_and_land)
    return made


def never(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("the pass reached the host agent")


def a_pass(root: Path, kept: Kept, **over: Any) -> Any:
    args: dict[str, Any] = {
        "root": root,
        "teams": {"t": TEAM},
        "entries": [{"id": "TD-7", "kind": "build", "owner": "grinder", "pickable": "yes"}],
        "prs": {"open": [], "recent": []},
        "graph": {},
        "snapshotted": (),
        "checkouts": {},
        "host_teams": None,
        "local": "h",
        "call": never,
        "kept": kept,
    }
    return run(**{**args, **over})


@pytest.mark.unit
def test_a_builtin_flow_is_found_in_the_package_and_passes_its_check(root: Path) -> None:
    text, problems = flow_now(root, "build")
    assert flow3.is_format3(text) and problems == ()


@pytest.mark.unit
def test_a_repo_flow_runs_only_where_it_is_format_3(root: Path) -> None:
    d = root / flow3.REPO_DIR / "mine"
    d.mkdir(parents=True)
    (d / flow3.FILE).write_text("stages: []\n", encoding="utf-8")
    assert flow_now(root, "mine") == (None, (f"flow mine ({d}) is not a format-3 flow",))
    built = (flow3.PACKAGE_DIR / "build" / flow3.FILE).read_text(encoding="utf-8")
    (d / flow3.FILE).write_text(built, encoding="utf-8")
    assert flow_now(root, "mine")[0] == built
    assert flow_now(root, "") == (None, ("the team names no flow",))
    assert flow_now(root, "nowhere") == (None, ("flow nowhere is not found",))


@pytest.mark.unit
def test_the_orgs_flow_shadows_the_repos_and_a_name_never_leaves_the_flows(root: Path) -> None:
    built = (flow3.PACKAGE_DIR / "build" / flow3.FILE).read_text(encoding="utf-8")
    mine, org = root / flow3.REPO_DIR / "mine", paths.home() / "flows" / "mine"
    for d in (mine, org):
        d.mkdir(parents=True)
        (d / flow3.FILE).write_text(built, encoding="utf-8")
    assert stage_tick.flow_file(root, "mine") == (org / flow3.FILE, "org", None)
    (root / "x").mkdir()
    (root / "x" / flow3.FILE).write_text(built, encoding="utf-8")
    for name in ("../../x", "/abs", ".hidden"):
        assert stage_tick.flow_file(root, name) is None


@pytest.mark.integration
def test_a_pass_reads_a_switched_team_stores_its_flow_and_starts_nothing(root: Path, quiet: list[str]) -> None:
    kept = Kept()
    got = a_pass(root, kept)
    assert got is not None and got.unread == () and list(got.teams) == ["t"]
    store = StageStore(root)
    assert store.flow("t") == (flow3.PACKAGE_DIR / "build" / flow3.FILE).read_text(encoding="utf-8")
    assert store.entry("TD-7") is None, "no team is started before TD-2065, so nothing is offered"
    assert got.tell == {}
    a_pass(root, kept)
    assert len(quiet) == 1, "one gate and land per repo, kept between passes"


@pytest.mark.integration
def test_a_flow_not_found_is_told_once_and_its_team_has_no_reading(root: Path, quiet: list[str]) -> None:
    kept = Kept()
    gone = {"t": {**TEAM, "flow": "nowhere"}}
    first = a_pass(root, kept, teams=gone)
    assert first.unread == ("t",) and first.tell == {"t": ("flow nowhere is not found",)}
    assert a_pass(root, kept, teams=gone).tell == {}, "told once until it passes again"


@pytest.mark.unit
def test_an_unreadable_ledger_or_person_reads_no_record(
    root: Path, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stage_tick, "ledger_read", lambda *_a: None)
    assert a_pass(root, Kept()) is None
    monkeypatch.undo()

    def refuse(_root: Any) -> str:
        raise stage_end.Refused("the repo's board names no person to ask")

    monkeypatch.setattr(stage_end, "_person_of", refuse)
    assert a_pass(root, Kept()) is None


@pytest.mark.integration
def test_origins_branches_are_read_once_a_pass_and_only_for_a_carried_branch(
    root: Path, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A moved entry's carried branch counts as still pushed only by origin's reading (TD-2051): read once a pass,
    only where a closed record carries a branch, and a pass that cannot read it has no reading of the team."""
    reads: list[Path] = []
    given: list[Any] = []

    def pushed(at: Path) -> frozenset[str] | None:
        reads.append(at)
        return answer

    def facts(*_a: Any, **kw: Any) -> None:
        given.append(kw["branches"])
        return None

    monkeypatch.setattr(stage_tick, "pushed_branches", pushed)
    monkeypatch.setattr(stage_tick.stage_pass, "repo_facts", facts)
    two = {"t": TEAM, "u": {**TEAM, "flow": "build"}}
    answer: frozenset[str] | None = frozenset({"td7-x"})
    a_pass(root, Kept(), teams=two)
    assert reads == [] and given == [frozenset(), frozenset()], "no record carries a branch: origin is not asked"
    monkeypatch.setattr(stage_tick, "carries_branch", lambda _records: True)
    given.clear()
    a_pass(root, Kept(), teams=two)
    assert reads == [root] and given == [answer, answer], "asked once for the two teams"
    answer, given[:] = None, []
    got = a_pass(root, Kept(), teams=two)
    assert given == [] and got is not None and set(got.unread) == {"t", "u"}
