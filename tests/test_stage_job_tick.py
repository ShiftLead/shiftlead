"""The two built-in seats' passes as the tick takes them (design §4.9d *How each one runs*, TD-2053)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from shiftlead import stage_job, stage_job_make, stage_job_tick
from shiftlead.stage_fetch import SessionsRead
from shiftlead.stagerecord import StageStore

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
FLOW = {"stages": [{"name": "build", "takes": "other"}, {"name": "review", "takes": "none"}]}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def store(tmp_path: Path) -> StageStore:
    origin, root = tmp_path / "o.git", tmp_path / "r"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "commit", "-q", "--allow-empty", "-m", "init")
    git(root, "push", "-q", "origin", "main")
    s = StageStore(root)
    s.ensure_branch()
    return s


def reach(started: list[str]) -> stage_job_make.JobReach:
    def start(record, _came):
        started.append(record["id"])
        return f"s-{len(started)}"

    return stage_job_make.JobReach(start, lambda h, r: None, lambda r, why: "aaaa0001", lambda i: None, lambda h: None)


def a_run(store: StageStore, made: list[str], **over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "now": NOW,
        "orders": [{"id": "board:1a2b3c4d", "decided": {"date": "2026-11-24"}}],
        "pr_orders": [{"id": "pr:4", "pr": 4, "pr_order": True, "red_since": "2026-11-20"}],
        "boards": {"boards": []},
        "rows": [{"number": 4, "state": "open"}],
        "entries": [],
        "sessions": SessionsRead({}, frozenset(), frozenset()),
        "checkouts": {},
        "local": "h",
        "started": ["t"],
        "docs": {"t": FLOW},
        "may_start": True,
    }
    return stage_job_tick.run(store, reach(made), **{**args, **over})


def test_the_open_lines_are_read_by_their_eight_hex_digits_and_an_unread_board_is_none():
    boards = {"boards": [{"items": [{"key": "board:1a2b3c4d"}, {"key": "TD-9"}, "junk"]}]}
    assert stage_job_tick.lines_open(boards) == {"1a2b3c4d"}
    assert stage_job_tick.lines_open({"error": "x"}) is None and stage_job_tick.lines_open(None) is None


def test_the_homes_line_names_the_seat_the_work_order_and_the_reason():
    record = stage_job.new_job("unheld-pull-requests", 4, "t", "x")
    text = stage_job_tick.line_text(record, "two job sessions in a row were lost")
    assert "pull requests nobody holds" in text and "pr:4" in text and "were lost" in text and "\n" not in text


def test_each_seat_offers_its_oldest_object(store):
    started: list[str] = []
    got = a_run(store, started)
    assert started == ["board-1a2b3c4d", "pr-4"]
    assert store.job("pr-4")["holder"] == "s-2" and store.job("board-1a2b3c4d")["team"] == "t"
    assert set(got) == set(stage_job.SEATS)


def test_no_started_team_offers_nothing(store):
    started: list[str] = []
    a_run(store, started, started=[], may_start=False)
    assert started == [] and store.jobs() == {}


def test_a_node_not_read_with_a_checkout_offers_no_pull_request(store):
    started: list[str] = []
    a_run(store, started, checkouts={"node2": ["/r"]})
    assert started == ["board-1a2b3c4d"]


def test_a_pickable_entrys_pull_request_is_the_entrys(store, monkeypatch):
    monkeypatch.setattr(stage_job_tick, "pickable_on", lambda e, team: True)
    seen: list[Any] = []

    def work(pickable, records, rows, *, held):
        seen.append(list(pickable))
        return frozenset({4})

    monkeypatch.setattr(stage_job, "entries_work", work)
    started: list[str] = []
    a_run(store, started, entries=[{"id": "TD-7"}])
    assert seen == [["TD-7"]] and started == ["board-1a2b3c4d"]


def test_unread_records_run_neither_seat(store, monkeypatch):
    def boom():
        raise ValueError("bad")

    monkeypatch.setattr(store, "entries", boom)
    assert a_run(store, []) == dict.fromkeys(stage_job.SEATS)


def test_the_reach_writes_and_closes_the_homes_line(monkeypatch, tmp_path):
    calls: list[tuple] = []
    monkeypatch.setattr(
        stage_job_tick.board, "add", lambda root, text, due: calls.append(("add", due)) or {"key": "board:0000beef"}
    )
    monkeypatch.setattr(
        stage_job_tick.board, "write_back", lambda root, line, text, action, **kw: calls.append((action, kw["key"]))
    )
    r = stage_job_tick.reach_for(
        lambda *a, **k: None, lambda: None, tmp_path, "r", local="h", hosts={}, docs={}, today=lambda: "2026-11-25"
    )
    record = stage_job.new_job("board-answers", "1a2b3c4d", "t", "x")
    assert r.line(record, "why") == "0000beef"
    r.close_line("0000beef")
    assert calls == [("add", "2026-11-25"), ("done", "board:0000beef")]
    assert r.start(record, None) is None  # no org read: nothing starts


def test_the_reach_starts_a_review_stages_session_where_the_record_stands_at_one(monkeypatch, tmp_path):
    org = type("Org", (), {"teams": {"t": object()}})()
    seen: list[tuple] = []

    def review(read, team, doc, record, **kw):
        seen.append(("review", record["stage"], kw["came"], kw["place"], kw["flow_dir"]))
        return "review-launch"

    def job(read, team, doc, record, model, **kw):
        seen.append(("job", record["stage"], model, kw["on_set"]))
        return "job-launch"

    monkeypatch.setattr(stage_job_tick.stage_job_start, "review_launch", review)
    monkeypatch.setattr(stage_job_tick.stage_job_start, "launch", job)
    monkeypatch.setattr(stage_job_tick.stage_start, "start", lambda call, read, team, got: {"id": got})
    monkeypatch.setattr(stage_job_tick.stage_start, "holder_of", lambda got, made: made["id"])
    monkeypatch.setattr(stage_job_tick.builtinstore, "sets", lambda sdoc: {"s": {}})
    monkeypatch.setattr(stage_job_tick.builtinstore, "repo_set", lambda sdoc, repo: "s")
    monkeypatch.setattr(stage_job_tick.builtinstore, "model", lambda entry, seat: "haiku")
    r = stage_job_tick.reach_for(
        lambda *a, **k: None,
        lambda: org,
        tmp_path,
        "r",
        local="h",
        hosts={},
        docs={"t": FLOW},
        flows_at={"t": ("repo", tmp_path / "f")},
        settings=dict,
    )
    record = stage_job.new_job("unheld-pull-requests", 4, "t", "x")
    assert r.start({**record, "stage": "review"}, "pushed") == "review-launch"
    assert r.start({**record, "stage": "build"}, None) == "job-launch"
    assert r.start(record, None) == "job-launch"
    assert seen == [
        ("review", "review", "pushed", "repo", tmp_path / "f"),
        ("job", "build", "haiku", "s"),
        ("job", None, "haiku", "s"),
    ]


def test_a_job_starts_on_the_set_its_repo_picked(monkeypatch, tmp_path):
    """TD-2258, design §4.9d *A repo uses one set*: with the real `builtinstore`, a job of repo `r`, which names the
    set `night`, launches on that set's model with `on_set` naming it, and a job of a repo naming none on `default`'s."""
    org = type("Org", (), {"teams": {"t": object()}})()
    seen: list[tuple] = []

    def job(read, team, doc, record, model, **kw):
        seen.append((model, kw["on_set"]))
        return "job-launch"

    monkeypatch.setattr(stage_job_tick.stage_job_start, "launch", job)
    monkeypatch.setattr(stage_job_tick.stage_start, "start", lambda call, read, team, got: {"id": got})
    monkeypatch.setattr(stage_job_tick.stage_start, "holder_of", lambda got, made: made["id"])
    sdoc = {
        "builtins": {
            "default": {"models": {"unheld-pull-requests": "opus"}, "logins": []},
            "night": {"models": {"unheld-pull-requests": "haiku"}, "logins": []},
        },
        "repos": {"r": {"builtins": "night"}},
    }
    record = stage_job.new_job("unheld-pull-requests", 4, "t", "x")
    for repo in ("r", "q"):
        r = stage_job_tick.reach_for(
            lambda *a, **k: None,
            lambda: org,
            tmp_path,
            repo,
            local="h",
            hosts={},
            docs={"t": FLOW},
            settings=lambda: sdoc,
        )
        assert r.start(record, None) == "job-launch"
    assert seen == [("haiku", "night"), ("opus", "default")]


def test_a_job_waiting_merging_is_merged_after_the_seats_pass(store):
    record = {
        **stage_job.new_job("unheld-pull-requests", 4, "t", "2026-11-20T00:00:00Z"),
        "pr": 4,
        "stage": "build",
        "waits": "merging",
        "merging": {"head": "f" * 40, "stage": "build", "outcome": "work-pushed"},
    }
    store.put_job(record, "test: merging")
    landed: list[tuple[int, str]] = []
    gate_land = (lambda pr, head: {"verdict": "pass", "failed": []}, lambda pr, head: landed.append((pr, head)))
    made: list[str] = []
    rows = [{"number": 4, "state": "open", "head": "f" * 40}]
    got = a_run(store, made, rows=rows, gate_land=gate_land)
    assert landed == [(4, "f" * 40)] and "pr-4" not in made, "a job waiting on its merge is offered no session"
    assert got["unheld-pull-requests"][-1].act == stage_job_tick.MERGING
    assert a_run(store, [], rows=rows)["unheld-pull-requests"] is not None and len(landed) == 1, "no gate, no merge"


def a_merging_job(store: StageStore, team: str = "t") -> dict[str, Any]:
    record = {
        **stage_job.new_job("unheld-pull-requests", 4, team, "2026-11-20T00:00:00Z"),
        "pr": 4,
        "stage": "build",
        "waits": "merging",
        "merging": {"head": "f" * 40, "stage": "build", "outcome": "work-pushed"},
    }
    store.put_job(record, "test: merging")
    return record


def a_gate_land(gated: list[tuple[int, str]], landed: list[tuple[int, str]]) -> tuple[Any, Any]:
    def gate(pr: int, head: str) -> dict[str, Any]:
        gated.append((pr, head))
        return {"verdict": "pass", "failed": []}

    return gate, lambda pr, head: landed.append((pr, head))


@pytest.mark.parametrize("state", ["merged", "closed"])
def test_a_job_whose_pull_request_is_no_longer_open_is_merged_by_nothing(store, state):
    a_merging_job(store)
    gated: list[tuple[int, str]] = []
    landed: list[tuple[int, str]] = []
    rows = [{"number": 4, "state": state, "head": "f" * 40}]
    got = stage_job_tick.merges(store, rows, {"t": FLOW}, a_gate_land(gated, landed), reach([]))
    assert gated == [] and landed == [], f"a {state} pull request's head is not the job's to merge"
    assert [s.act for s in got["unheld-pull-requests"]] == [stage_job_tick.MERGING], "the job is read as unread"


def test_a_job_whose_teams_flow_is_not_read_is_left_unmerged(store):
    a_merging_job(store, team="t")
    gated: list[tuple[int, str]] = []
    landed: list[tuple[int, str]] = []
    rows = [{"number": 4, "state": "open", "head": "f" * 40}]
    got = a_run(store, [], rows=rows, docs={"other": FLOW}, gate_land=a_gate_land(gated, landed))
    assert gated == [] and landed == [], "a job whose team's flow is not read this pass is left as it is"
    assert stage_job_tick.MERGING not in [s.act for s in got["unheld-pull-requests"] or ()]
    assert store.job(stage_job.key_of("unheld-pull-requests", 4))["waits"] == "merging"


def test_a_seat_whose_pass_failed_gets_no_merge_steps(store, monkeypatch):
    from shiftlead import stage_job_pass

    a_merging_job(store)
    real = stage_job_pass.seat_pass

    def seat_pass(store_, seat, *a: Any, **k: Any) -> Any:
        if seat == "unheld-pull-requests":
            raise RuntimeError("this seat's pass failed")
        return real(store_, seat, *a, **k)

    monkeypatch.setattr(stage_job_pass, "seat_pass", seat_pass)
    gated: list[tuple[int, str]] = []
    landed: list[tuple[int, str]] = []
    rows = [{"number": 4, "state": "open", "head": "f" * 40}]
    got = a_run(store, [], rows=rows, gate_land=a_gate_land(gated, landed))
    assert landed == [(4, "f" * 40)], "the merge still runs"
    assert got["unheld-pull-requests"] is None, "a seat whose pass failed stays None, its merge steps not added"
    assert got["board-answers"] is not None
