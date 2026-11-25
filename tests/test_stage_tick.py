"""One repo's stage pass as the tick calls it (design §4.9c *The home acts only where no session will*, TD-2051): a
switched team's flow found and checked, its records read against it, and no session started for a team not started."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sessionorc import paths
from shiftlead import flow3, stage_end, stage_merge, stage_size, stage_tick
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
    assert store.entry("TD-7") is None, "no team is started, so nothing is offered"
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


@pytest.mark.unit
def test_each_teams_facts_read_its_own_started_mark(
    root: Path, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A team's facts may start a session only by the home's started mark in its `host` record (§4.9d *Started is a
    mark the home keeps*, TD-2065): a started team's yes, a team the person stopped and one with no record no."""
    given: dict[str, bool] = {}

    def facts(*_a: Any, **kw: Any) -> None:
        given[kw["team"]] = kw["started"]
        return None

    monkeypatch.setattr(stage_tick.stage_pass, "repo_facts", facts)
    three = {"t": TEAM, "u": TEAM, "v": TEAM}
    marks = {"t": {"started": {"since": "x", "by": "person"}}, "u": {"stopped": {"at": "x", "by": "person"}}}
    a_pass(root, Kept(), teams=three, host_teams=marks)
    assert given == {"t": True, "u": False, "v": False}


@pytest.mark.unit
def test_each_teams_facts_carry_its_own_numbers(root: Path, quiet: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A team's numbers reach its facts, so the pass counts each offer against them (§4.9d *Sessions at once*,
    TD-2065): one stage's number and the team limit, and a team that sets neither."""
    given: dict[str, Any] = {}

    def facts(*_a: Any, **kw: Any) -> None:
        given[kw["team"]] = kw["limits"]
        return None

    monkeypatch.setattr(stage_tick.stage_pass, "repo_facts", facts)
    a_pass(root, Kept(), teams={"t": {**TEAM, "at_once": {"build": 3}, "most": 4}, "u": TEAM})
    assert given == {"t": stage_size.Limits({"build": 3}, 4), "u": stage_size.Limits()}


@pytest.mark.unit
def test_a_team_launches_from_the_flow_the_pass_runs(
    root: Path, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TD-2051: the reach launches from the doc it is given (the last good copy while the flow fails its check), its
    briefs from the flow's directory as found now, and only from the standard briefs where no flow file is found."""
    given: list[Any] = []
    monkeypatch.setattr(stage_tick.stage_pass, "reach_for", lambda *a, **k: given.append((a[3], k)) or "reach")
    org = type("Org", (), {"teams": {"t": object()}})()
    copy = {"format": 3, "name": "kept", "stages": []}
    got = stage_tick._reach(never, root, {**TEAM, "flow": "nowhere"}, "h", Kept(), "t", lambda: org, copy)
    assert got == "reach" and given[0][0] == copy and given[0][1]["place"] == "package"
    assert given[0][1]["flow_dir"] is None
    d = root / flow3.REPO_DIR / "failing"
    d.mkdir(parents=True)
    (d / flow3.FILE).write_text("not: a flow\n", encoding="utf-8")
    stage_tick._reach(never, root, {**TEAM, "flow": "failing"}, "h", Kept(), "t", lambda: org, copy)
    assert given[1][0] == copy and given[1][1]["place"] == "repo" and given[1][1]["flow_dir"] == d
    alone = stage_tick._reach(never, root, TEAM, "h", Kept(), "u", lambda: org, copy)
    assert len(given) == 2 and alone.start("build", object()) is None, "a team the org lacks starts nothing"


# -- the built-in seats' jobs (TD-2053) -------------------------------------------------------------------------------


@pytest.mark.integration
def test_without_the_reading_of_orders_no_job_is_passed_over(root: Path, quiet: list[str]) -> None:
    assert a_pass(root, Kept()).jobs == {}


@pytest.mark.integration
def test_with_the_orders_both_seats_are_passed_over_and_nothing_starts(root: Path, quiet: list[str]) -> None:
    orders = [{"id": "board:1a2b3c4d", "decided": {"date": "2026-11-24"}}]
    prs = [{"id": "pr:4", "pr": 4, "pr_order": True, "red_since": "2026-11-24"}]
    got = a_pass(
        root,
        Kept(),
        orders=orders,
        pr_orders=prs,
        boards={"boards": []},
        prs={"open": [{"number": 4, "state": "open"}], "recent": []},
    )
    assert set(got.jobs) == {"board-answers", "unheld-pull-requests"}
    assert [s.key for s in got.jobs["board-answers"]] == ["board-1a2b3c4d"]
    assert all(s.act is None for steps in got.jobs.values() for s in steps), "no team is started"
    assert StageStore(root).jobs() == {}


@pytest.mark.integration
def test_a_job_whose_object_is_gone_is_closed_by_the_tick(root: Path, quiet: list[str]) -> None:
    from shiftlead import stage_job

    StageStore(root).put_job(stage_job.new_job("board-answers", "1a2b3c4d", "t", "2026-11-24"), "test")
    got = a_pass(root, Kept(), orders=[], pr_orders=[], boards={"boards": []})
    assert got.jobs["board-answers"][0].act.case == "object-gone"
    assert StageStore(root).job("board-1a2b3c4d")["closed_at"]


@pytest.mark.integration
def test_a_merging_job_is_landed_through_the_repos_gate_and_land(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from shiftlead import stage_job

    made: list[str] = []
    gated: list[tuple[int, str]] = []
    landed: list[tuple[int, str]] = []

    def gate(pr: int, head: str) -> dict[str, Any]:
        gated.append((pr, head))
        return {"verdict": "pass", "failed": []}

    def gate_and_land(where: Any) -> tuple[Any, Any]:
        made.append(str(where))
        return gate, lambda pr, head: landed.append((pr, head))

    monkeypatch.setattr(stage_end, "_person_of", lambda _root: "paul")
    monkeypatch.setattr(stage_merge, "gate_and_land", gate_and_land)
    record = {
        **stage_job.new_job("unheld-pull-requests", 4, "t", "2026-11-20T00:00:00Z"),
        "pr": 4,
        "stage": "build",
        "waits": "merging",
        "merging": {"head": "f" * 40, "stage": "build", "outcome": "work-pushed"},
    }
    StageStore(root).put_job(record, "test: merging")
    real = stage_tick.stage_pass.repo_pass  # the teams' pass over no team, so it makes no gate and land of its own
    monkeypatch.setattr(stage_tick.stage_pass, "repo_pass", lambda s, st, _flows, *a, **k: real(s, st, {}, *a, **k))
    kept = Kept()
    a_pass(
        root,
        kept,
        orders=[],
        pr_orders=[],
        boards={"boards": []},
        prs={"open": [{"number": 4, "state": "open", "head": "f" * 40}], "recent": []},
    )
    assert made == [str(root)] and kept.gate_land is not None, "the pass makes the repo's gate and land once"
    assert gated == [(4, "f" * 40)] and landed == [(4, "f" * 40)], "the job is landed through that gate and land"
