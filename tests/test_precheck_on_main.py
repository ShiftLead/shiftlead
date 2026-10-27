"""TD-1038, design §6 *The precheck on main*: where a repo with `promote:` sets `precheck`, the home runs
`precheck.py --commit <sha>` on main's head itself — when it starts and when it does not, one at a time
with the sync pass's run, a restarted home that finds one going, a `pid: null` file, the end with no
status, the bound's group kill and the prune, a failed status, and the Inbox row's words. `precheck.py
--commit` is faked: a shell line that records its arguments and sleeps or exits."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_promote import _commit, _git, _merge, checkout  # noqa: F401 — the fixture, shared

from sessionorc import promote
from shiftlead.ui import inbox

SHA = "a" * 40
OTHER = "b" * 40


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """`cadence.precheck_script` answering a shell line that appends `$2` (the sha after `--commit`) to
    `ran`, prints a line, then runs `then` (`sleep 30` by default): `{ran, then, pids}`. Every process it
    starts is killed at teardown, by the pid this test holds."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    state = {"ran": tmp_path / "ran", "then": "sleep 30"}

    def script(root):
        line = f'echo "$2" >> {state["ran"]}; echo "precheck: running on $2"; {state["then"]}'
        return (["sh", "-c", line, "sh"], None), None

    monkeypatch.setattr(promote.cadence, "precheck_script", script)
    yield state
    for pid in list(promote._procs):
        with suppress(OSError):
            os.killpg(pid, signal.SIGKILL)
        with suppress(Exception):
            promote._procs.pop(pid).wait(timeout=5)


def _reading(**kw) -> dict:
    return {"main": SHA, "live": OTHER, "tree": None, "precheck": "absent", "checks": "unknown", **kw}


def _ran(fake) -> list[str]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not fake["ran"].exists():
        time.sleep(0.05)
    return fake["ran"].read_text().split() if fake["ran"].exists() else []


def _gone(f: dict) -> None:
    deadline = time.monotonic() + 10
    while promote.alive(f["pid"], f["started"]) and time.monotonic() < deadline:
        time.sleep(0.05)


NOW = datetime.now(UTC)


def test_absent_on_main_with_one_and_three_met_starts_one_run_with_its_file_written(fake, tmp_path):
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    f = promote.precheck_run("r")
    assert f["sha"] == SHA and isinstance(f["pid"], int) and f["log"].endswith(f"precheck-{SHA[:7]}.log")
    assert (r["checks"], r["checks_why"], r["prechecking"]) == ("pending", f"prechecking {SHA[:7]}", SHA)
    assert _ran(fake) == [SHA]
    # the next pass finds it going: pending still, never a second
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert (r["checks"], r["prechecking"]) == ("pending", SHA)
    assert promote.precheck_run("r")["pid"] == f["pid"] and _ran(fake) == [SHA]


@pytest.mark.parametrize(
    "why",
    [
        {"precheck": None},  # the repo sets no `precheck`
        {"precheck": "success"},  # a status already there
        {"precheck": "pending"},
        {"precheck": "unread"},  # the status read failed: nothing starts
        {"live": SHA},  # live is main's head
        {"tree": "the checkout has 1 uncommitted change"},  # (1)
        {"inflight": {"sha": OTHER}},  # (3)
        {"failed": {"sha": OTHER}},
        {"held": {"sha": OTHER}},
        {"main": None},
    ],
)
def test_it_starts_nothing_unless_every_condition_holds(fake, tmp_path, why):
    r = _reading(**why)
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert promote.precheck_run("r") is None and r.get("prechecking") is None
    assert r["checks"] == "unknown"


def test_one_at_a_time_per_repo_with_main_moved_and_with_the_sync_passs_run(fake, tmp_path):
    promote.precheck_on_main(tmp_path, "r", _reading(main=OTHER, live=SHA), NOW)  # a run on the old head
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert (r["checks"], r["prechecking"]) == ("unknown", None) and promote.precheck_run("r")["sha"] == OTHER
    # the sync pass's run going on a PR keeps main's waiting too (§6 *Sync* step 4)
    f = promote.precheck_run("r")
    promote._write(promote.repo_dir("r") / "precheck-pr.json", {**f, "pr": 7})
    promote.clear("r", "precheck")
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert promote.precheck_run("r") is None and r["checks"] == "unknown"


def test_a_restarted_home_finds_the_run_going_and_starts_no_second(fake, tmp_path):
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        f = {"sha": SHA, "at": NOW.isoformat(), "pid": p.pid, "started": promote.proc_start(p.pid), "log": None}
        promote._write(promote.repo_dir("r") / "precheck.json", f)
        r = _reading()
        promote.precheck_on_main(tmp_path, "r", r, NOW)
        assert (r["checks"], r["prechecking"]) == ("pending", SHA) and _ran(fake) == []
    finally:
        p.kill()
        p.wait()


def test_a_run_that_ended_with_no_status_reads_unknown_and_is_not_run_again(fake, tmp_path):
    fake["then"] = "exit 3"
    promote.precheck_on_main(tmp_path, "r", _reading(), NOW)
    f = promote.precheck_run("r")
    _gone(f)
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    want = f"precheck on {SHA[:7]} ended and recorded nothing (exit 3: precheck: running on {SHA})"
    assert (r["checks"], r["checks_why"]) == ("unknown", want)
    kept = promote.precheck_run("r")
    assert (kept["exit"], kept["pid"]) == (3, f["pid"])
    # read again (the exit is the file's now), and never started again on that commit
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert r["checks_why"] == want and _ran(fake) == [SHA]
    # a restarted home saw no exit: it says only that
    promote._write(promote.repo_dir("r") / "precheck.json", {**f, "exit": None, "last": ""})
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert r["checks_why"] == f"precheck on {SHA[:7]} ended and recorded nothing"
    # main moved: the next head runs afresh
    r = _reading(main=OTHER, live=SHA)
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert r["prechecking"] == OTHER


def test_a_pid_null_file_starts_again_on_mains_head_and_is_dropped_off_it(fake, tmp_path):
    promote._write(promote.repo_dir("r") / "precheck.json", {"sha": SHA, "at": NOW.isoformat(), "pid": None})
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert r["prechecking"] == SHA and isinstance(promote.precheck_run("r")["pid"], int)
    for pid in list(promote._procs):
        os.killpg(pid, signal.SIGKILL)
    promote._write(promote.repo_dir("r") / "precheck.json", {"sha": OTHER, "at": NOW.isoformat(), "pid": None})
    r = _reading(tree="the checkout has 1 uncommitted change")  # nothing starts in its place
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert promote.precheck_run("r") is None


def test_no_script_starts_nothing_and_says_why(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(promote.cadence, "precheck_script", lambda root: (None, "no precheck.py here"))
    r = _reading()
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert (r["checks"], r["checks_why"]) == ("unknown", "no precheck.py here")
    assert promote.precheck_run("r") is None


def test_a_failed_status_on_mains_head_is_told_with_the_logs_last_lines(fake, tmp_path):
    fake["then"] = "echo 'FAILED tests/test_x.py::test_y'; exit 1"
    promote.precheck_on_main(tmp_path, "r", _reading(), NOW)
    f = promote.precheck_run("r")
    _gone(f)
    r = _reading(precheck="failure", checks="failed")
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert r["precheck_failed"]["sha"] == SHA and r["precheck_failed"]["tail"][-1] == "FAILED tests/test_x.py::test_y"
    assert r["checks"] == "failed" and _ran(fake) == [SHA]
    # a failed status read with no file of this home's (another home ran it): told, no lines
    promote.clear("r", "precheck")
    r = _reading(precheck="failure", checks="failed")
    promote.precheck_on_main(tmp_path, "r", r, NOW)
    assert r["precheck_failed"] == {"sha": SHA, "log": None, "tail": []}


def test_a_run_past_the_bound_is_killed_by_group_and_its_worktree_removed(checkout, fake, tmp_path, monkeypatch):  # noqa: F811
    root = checkout
    sha = _git(root, "rev-parse", "HEAD")
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(promote.tempfile, "gettempdir", lambda: str(tmp))
    run = tmp / f"precheck-{sha[:7]}-abc"
    run.mkdir()
    _git(root, "worktree", "add", "-q", "--detach", str(run / "head"), sha)
    (tmp / f"precheck-{sha[:7]}-empty").mkdir()  # a kill between mkdtemp and the worktree add
    other = tmp / f"precheck-{sha[:7]}-session"
    (other / "head").mkdir(parents=True)  # a non-empty one the list does not name at the sha: a session's own
    # the leader obeys the TERM, a child deaf to it (the suite) is left: the group's KILL ends it
    fake["then"] = f"(trap '' TERM; echo $$ > {tmp_path / 'child'}; exec sleep 30) & wait"
    monkeypatch.setattr(promote, "PRECHECK_GRACE", 0.5)
    promote.precheck_on_main(root, "r", _reading(main=sha), NOW)
    f = promote.precheck_run("r")
    assert _ran(fake) == [sha]
    started = time.monotonic() + 5  # the child has said its pid before the bound's pass kills (TD-1052: a race)
    while not (tmp_path / "child").is_file() and time.monotonic() < started:
        time.sleep(0.02)
    later = datetime.now(UTC) + timedelta(seconds=promote.PRECHECK_BOUND + 1)
    r = _reading(main=sha)
    promote.precheck_on_main(root, "r", r, later)
    assert not promote.alive(f["pid"], f["started"])
    child = int((tmp_path / "child").read_text().split()[0])
    deadline = time.monotonic() + 5
    while Path(f"/proc/{child}").exists() and time.monotonic() < deadline:
        state = (
            Path(f"/proc/{child}/stat").read_text().split(")")[-1].split()[0]
            if Path(f"/proc/{child}").exists()
            else "Z"
        )
        if state == "Z":
            break
        time.sleep(0.05)
    assert (
        not Path(f"/proc/{child}").exists() or Path(f"/proc/{child}/stat").read_text().split(")")[-1].split()[0] == "Z"
    )
    assert not run.exists() and not (tmp / f"precheck-{sha[:7]}-empty").exists() and other.exists()
    assert str(run / "head") not in _git(root, "worktree", "list", "--porcelain")
    assert r["checks"] == "unknown" and "ended and recorded nothing" in r["checks_why"]


def test_the_pass_starts_it_with_auto_off_and_the_auto_row_says_prechecking(checkout, fake, monkeypatch):  # noqa: F811
    root = checkout
    sha = _merge(root, "b")
    monkeypatch.setattr(
        promote,
        "read_checks",
        lambda root, s, keep=True: ("unknown", f"no cadence/precheck on {s[:7]}", None, "absent"),
    )
    readings, _, _ = promote.survey([str(root)], {}, True, {}, datetime.now(UTC))
    r = readings[root.name]
    assert (r["checks"], r["prechecking"], promote.precheck_run(root.name)["sha"]) == ("pending", sha, sha)
    assert _ran(fake) == [sha]
    readings, _, _ = promote.survey([str(root)], readings, True, {root.name: True}, datetime.now(UTC))
    r = readings[root.name]
    assert r["acts"] == {"prechecking": sha[:7]} and _ran(fake) == [sha]
    assert promote.acts_words(r["acts"]) == f"prechecking {sha[:7]} — promotes when green"
    (row,) = inbox.promote_rows(readings)
    assert row["auto_row"] and row["fyi"] and f"auto on · prechecking {sha[:7]} — promotes when green" in row["text"]


def test_a_failed_precheck_on_mains_head_is_a_needs_you_row_whatever_auto_says():
    log = ["E   assert 1 == 2", "FAILED tests/test_x.py::test_y"]
    base = {"live": OTHER, "main": SHA, "ahead": 2, "checks": "failed", "acts": None}
    for auto in (False, True):
        r = {**base, "auto": auto, "precheck_failed": {"sha": SHA, "log": "/l", "tail": log}}
        (row,) = inbox.promote_rows({"shiftlead": r})
        assert not row["fyi"] and not row["auto_row"]
        assert row["text"].endswith(f"checks failed on {SHA[:7]}") or f"checks failed on {SHA[:7]} ·" in row["text"]
        assert row["precheck_failed"]["tail"] == log
    # a promote in flight beside it (a press going through): still Needs you
    r = {**base, "auto": False, "inflight": {"sha": SHA, "at": "x"}, "precheck_failed": {"sha": SHA, "tail": log}}
    (row,) = inbox.promote_rows({"shiftlead": r})
    assert not row["fyi"]
    # main moved: the failure was another head's, and the row is what it was
    r = {**base, "checks": "pending", "auto": True, "precheck_failed": {"sha": OTHER, "tail": log}}
    (row,) = inbox.promote_rows({"shiftlead": r})
    assert row["auto_row"] and row["precheck_failed"] is None and "checks failed on" not in row["text"]


def test_the_failed_rows_template_draws_the_logs_last_lines():
    from shiftlead.ui import app

    r = {"live": OTHER, "main": SHA, "ahead": 2, "checks": "failed", "auto": True, "acts": None}
    r["precheck_failed"] = {"sha": SHA, "log": "/l", "tail": ["FAILED tests/test_x.py::test_y"]}
    (row,) = inbox.promote_rows({"shiftlead": r})
    html = app.templates.env.get_template("inbox_row.html").module.promote_row(row, "needs")
    assert f"checks failed on {SHA[:7]}" in html and "FAILED tests/test_x.py::test_y" in html
    assert "Dismiss" not in html  # nothing stands to clear: main's next head is checked afresh


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))


def test_a_pass_that_read_no_checks_keeps_prechecking_and_runs_no_precheck(checkout, fake, monkeypatch):  # noqa: F811
    """TD-1074: a pass neither full nor the repo's first carries the last reading and reads no checks, so
    `precheck_on_main` is not run on it — run there, it would reset `prechecking` and act on a carried
    `absent`, dropping the *prechecking* row between full passes and starting a run on a stale reading."""
    root = checkout
    sha = _merge(root, "b")
    monkeypatch.setattr(
        promote,
        "read_checks",
        lambda root, s, keep=True: ("unknown", f"no cadence/precheck on {s[:7]}", None, "absent"),
    )
    readings, _, _ = promote.survey([str(root)], {}, True, {}, datetime.now(UTC))
    assert readings[root.name]["prechecking"] == sha and _ran(fake) == [sha]

    def never(*a, **kw):
        raise AssertionError("precheck_on_main ran on a pass that read no checks")

    monkeypatch.setattr(promote, "precheck_on_main", never)
    monkeypatch.setattr(promote, "precheck_pr_bound", never)
    readings, _, _ = promote.survey([str(root)], readings, False, {root.name: True}, datetime.now(UTC))
    r = readings[root.name]
    assert r["prechecking"] == sha and r["precheck"] == "absent" and _ran(fake) == [sha]
