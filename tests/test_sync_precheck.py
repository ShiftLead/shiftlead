"""TD-1039, design §6 *Sync* step 4: where a repo sets `precheck`, a sync PR reading *none* with no
`cadence/precheck` on its head is a candidate that waits rather than an order, and the pass starts
`precheck.py --pr <n>` before its gate — the skip when a status stands or `precheck` is unset, the
uncounted waits (the checkout, a run going), the pass going on, a run's end with a status and with none
(counted once), a `pid: null` file, the kill on a moved head or a closed PR, and the day's wait becoming
an order. `precheck.py` is faked by a shell line; the check, the gate and every `gh` call are stubbed as
`test_sync_pass.py` stubs them, and its fixtures are shared."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
from test_promote import _commit, _git  # noqa: F401
from test_sync_pass import HEAD, ROOT, _names, _orders, _pr, _reading, agent, gh  # noqa: F401 — fixtures, shared

from sessionorc import cadence, promote, sync
from sessionorc.models import now_iso

REPO = "samscrape"
OTHER = "b" * 40


@pytest.fixture
def pre(monkeypatch, tmp_path):
    """The repo sets `precheck`, the checkout reads clean on origin's head unless `checkout` says why
    not, and `precheck.py` is a shell line that appends its arguments to `ran` and runs `then` (`sleep
    30` by default). Every process it starts is killed at teardown, by the pid this test holds."""
    state = {"ran": tmp_path / "ran", "then": "sleep 30", "checkout": None, "command": "pdm run test"}

    def script(root):
        line = f'echo "$@" >> {state["ran"]}; {state["then"]}'
        return (["sh", "-c", line, "sh"], None), None

    monkeypatch.setattr(promote.cadence, "precheck_script", script)
    monkeypatch.setattr(cadence, "precheck_command", lambda root, rev: (state["command"], None))
    monkeypatch.setattr(sync, "checkout_why", lambda root: state["checkout"])
    monkeypatch.setattr(promote, "drop_precheck_tree", lambda *a, **k: None)  # no checkout at ROOT
    start = promote.start_precheck_pr
    monkeypatch.setattr(promote, "start_precheck_pr", lambda root, *a: start(tmp_path, *a))  # ROOT is no directory
    yield state
    for pid in list(promote._procs):
        with suppress(OSError):
            os.killpg(pid, signal.SIGKILL)
        with suppress(Exception):
            promote._procs.pop(pid).wait(timeout=5)


def _none(**over) -> dict:
    return _pr(**{"checks": "none", "prechecked": False, **over})


def _ran(pre) -> list[str]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not pre["ran"].exists():
        time.sleep(0.05)
    return pre["ran"].read_text().splitlines() if pre["ran"].exists() else []


def _gone(f: dict) -> None:
    deadline = time.monotonic() + 10
    while promote.alive(f["pid"], f["started"]) and time.monotonic() < deadline:
        time.sleep(0.05)


def _entry(home) -> dict:
    return home._repos[ROOT]["sync"]["1097"]


# -- pure ---------------------------------------------------------------------------------------------


def test_a_none_pr_is_a_candidate_only_where_the_repo_sets_precheck_and_no_status_stands():
    held = lambda pr: False  # noqa: E731
    assert sync.candidates([_none()], {}, held) == []
    assert [p["number"] for p in sync.candidates([_none()], {}, held, True)] == [1097]
    # a status on the head, whatever it reads, is no *none*: the gate's to read, never run again
    assert sync.candidates([_none(prechecked=True)], {}, held, True) == []
    assert sync.candidates([_pr(checks="pending", prechecked=True)], {}, held, True) == []


def test_a_pr_waiting_on_its_precheck_waits_as_a_green_one_and_is_no_order():
    e = {"head": HEAD, "verdict": "", "why": "prechecking aaaaaaa", "tries": 0, "waiting_since": now_iso()}
    (pr,) = sync.mark([_none()], {"1097": e}, True)
    assert pr.get("sync_home") is True
    (pr,) = sync.mark([_none()], {"1097": e}, False)  # a pass that no longer covers the repo: the team's
    assert "sync_home" not in pr
    (pr,) = sync.mark([_none()], {"1097": {**e, "head": OTHER}}, True)  # a new head waits for its own pass
    assert "sync_home" not in pr


def test_the_wait_is_uncounted_keeps_its_first_time_and_after_a_day_is_refused():
    t0 = datetime(2026, 10, 26, tzinfo=UTC)
    e = sync.wait_entry(None, HEAD, "a precheck of samscrape is running", t0.isoformat())
    assert (e["verdict"], e["tries"], e["waiting_since"]) == ("", 0, t0.isoformat())
    later = (t0 + timedelta(hours=23)).isoformat()
    e = sync.wait_entry(e, HEAD, "the checkout has 2 uncommitted changes", later)
    assert (e["verdict"], e["tries"], e["waiting_since"]) == ("", 0, t0.isoformat())
    e = sync.wait_entry(e, HEAD, "no precheck.py here", (t0 + timedelta(days=1)).isoformat())
    assert (e["verdict"], e["why"]) == ("refused", "precheck waited a day: no precheck.py here")
    assert sync.settled(e, HEAD)
    # a new head starts its own wait
    assert sync.wait_entry(e, OTHER, "x", later)["waiting_since"] == later


def test_checkout_why_reads_origins_head_and_a_clean_tree(tmp_path):
    origin, root = tmp_path / "origin.git", tmp_path / "repo"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", str(origin))
    _commit(root, "a")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    assert sync.checkout_why(root) is None
    (root / "a").write_text("edited")
    assert sync.checkout_why(root) == "the checkout has 1 uncommitted change"
    _commit(root, "b")
    assert "not origin/main's head" in sync.checkout_why(root)


# -- at the home --------------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_pass_runs_the_precheck_before_the_gate_and_the_pr_waits_then_its_status_is_gated(agent, gh, pre):  # noqa: F811
    _reading(agent, _none())
    await agent._sync_pass()
    assert _names(gh) == ["login", "check", "comment"], "steps 1 to 3, then the precheck in place of the gate"
    assert _ran(pre) == ["--pr 1097"]
    f = promote.precheck_pr_run(REPO)
    assert (f["pr"], f["sha"], f["pid"] is not None) == (1097, HEAD, True)
    e = _entry(agent)
    assert (e["verdict"], e["tries"], e["posted"], e["why"]) == ("", 0, True, f"prechecking {HEAD[:7]}")
    assert await _orders(agent) == [], "a PR waiting on its precheck is no order"
    # the run going: the next pass waits, uncounted, without the check
    gh["calls"] = []
    await agent._sync_pass()
    assert _names(gh) == [] and _entry(agent)["why"] == "a precheck of samscrape is running"
    assert _entry(agent)["tries"] == 0
    # it recorded a status and ended: the file is dropped and the PR is gated as any green one
    promote.kill(f["pid"], f["started"])
    _reading(agent, _pr(prechecked=True))
    agent._repos[ROOT]["sync"] = {"1097": e}
    gh["calls"] = []
    await agent._sync_pass()
    assert promote.precheck_pr_run(REPO) is None
    assert _names(gh) == ["check", "gate", "head", "merge"], "posted once per head: no second SHIP comment"
    assert _entry(agent)["verdict"] == "merged"


@pytest.mark.integration
async def test_precheck_unset_is_no_candidate_and_the_none_pr_is_the_teams(agent, gh, pre):  # noqa: F811
    pre["command"] = None
    _reading(agent, _none())
    await agent._sync_pass()
    assert _names(gh) == [] and promote.precheck_pr_run(REPO) is None
    assert [o["id"] for o in await _orders(agent)] == ["pr:1097"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "why", ["the checkout has 1 uncommitted change", "the checkout is at bbbbbbb, not origin/main's head"]
)
async def test_a_checkout_that_cannot_run_it_is_an_uncounted_wait_without_the_check(agent, gh, pre, why):  # noqa: F811
    pre["checkout"] = why
    _reading(agent, _none())
    await agent._sync_pass()
    await agent._sync_pass()
    assert _names(gh) == ["login"] and promote.precheck_pr_run(REPO) is None
    e = _entry(agent)
    assert (e["verdict"], e["tries"], e["why"]) == ("", 0, why) and e["waiting_since"]
    assert await _orders(agent) == []


@pytest.mark.integration
async def test_mains_run_going_is_an_uncounted_wait_and_the_pass_goes_on(agent, gh, pre):  # noqa: F811
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        f = {"sha": OTHER, "at": now_iso(), "pid": p.pid, "started": promote.proc_start(p.pid), "log": None}
        promote._write(promote.repo_dir(REPO) / "precheck.json", f)
        _reading(agent, _none(), _pr(1098))
        await agent._sync_pass()
        assert _entry(agent)["why"] == "a precheck of samscrape is running" and _entry(agent)["tries"] == 0
        assert promote.precheck_pr_run(REPO) is None
        # the green PR beside it is judged on the same pass, not held behind the wait
        assert agent._repos[ROOT]["sync"]["1098"]["verdict"] == "merged"
    finally:
        p.kill()
        p.wait()


@pytest.mark.integration
async def test_a_run_that_ended_with_no_status_is_counted_once_and_a_later_pass_starts_another(agent, gh, pre):  # noqa: F811
    pre["then"] = "exit 3"
    _reading(agent, _none())
    await agent._sync_pass()
    f = promote.precheck_pr_run(REPO)
    _gone(f)
    gh["calls"] = []
    await agent._sync_pass()
    e = _entry(agent)
    assert (e["verdict"], e["tries"]) == ("", 1) and "ended and recorded nothing" in e["why"]
    assert promote.precheck_pr_run(REPO)["counted"] is True and _names(gh) == [], "this pass starts nothing"
    await agent._sync_pass()  # counted already: not counted again, and a new run starts
    assert _entry(agent)["tries"] == 1 and _ran(pre) == ["--pr 1097", "--pr 1097"]
    assert "counted" not in promote.precheck_pr_run(REPO)


@pytest.mark.integration
async def test_a_pid_null_file_is_dropped_uncounted(agent, gh, pre):  # noqa: F811
    promote._write(promote.repo_dir(REPO) / "precheck-pr.json", {"pr": 1097, "sha": HEAD, "at": now_iso(), "pid": None})
    pre["checkout"] = "the checkout has 1 uncommitted change"  # so nothing new starts on the same pass
    _reading(agent, _none())
    await agent._sync_pass()
    assert promote.precheck_pr_run(REPO) is None and _entry(agent)["tries"] == 0


@pytest.mark.integration
@pytest.mark.parametrize("moved", [True, False], ids=["head-moved", "pr-closed"])
async def test_a_moved_head_or_a_closed_pr_kills_the_run_and_drops_the_file(agent, gh, pre, moved):  # noqa: F811
    _reading(agent, _none())
    await agent._sync_pass()
    f = promote.precheck_pr_run(REPO)
    assert promote.alive(f["pid"], f["started"])
    pre["checkout"] = "the checkout has 1 uncommitted change"
    _reading(agent, *([_none(head=OTHER)] if moved else []))
    await agent._sync_pass()
    _gone(f)
    assert not promote.alive(f["pid"], f["started"]) and promote.precheck_pr_run(REPO) is None


@pytest.mark.integration
async def test_the_bound_kills_the_run_and_the_sync_pass_counts_it(agent, gh, pre):  # noqa: F811
    _reading(agent, _none())
    await agent._sync_pass()
    f = promote.precheck_pr_run(REPO)
    old = (datetime.now(UTC) - timedelta(seconds=promote.PRECHECK_BOUND + 1)).isoformat()
    promote._write(promote.repo_dir(REPO) / "precheck-pr.json", {**f, "at": old})
    await agent._sync_pass()
    assert not promote.alive(f["pid"], f["started"])
    e = _entry(agent)
    assert e["tries"] == 1 and "killed at the 20-minute bound" in e["why"]


@pytest.mark.integration
async def test_a_day_waiting_at_one_head_is_refused_and_the_teams_order(agent, gh, pre):  # noqa: F811
    pre["checkout"] = "the checkout has 1 uncommitted change"
    _reading(agent, _none())
    day_ago = (datetime.now(UTC) - timedelta(seconds=sync.SYNC_PRECHECK_WAIT + 60)).isoformat()
    agent._repos[ROOT]["sync"] = {"1097": {"head": HEAD, "verdict": "", "why": "x", "tries": 0, "posted": False,
                                           "waiting_since": day_ago}}  # fmt: skip
    await agent._sync_pass()
    e = _entry(agent)
    assert (e["verdict"], e["why"]) == ("refused", "precheck waited a day: the checkout has 1 uncommitted change")
    (order,) = await _orders(agent)
    assert order["id"] == "pr:1097" and "precheck waited a day" in order["context"]
