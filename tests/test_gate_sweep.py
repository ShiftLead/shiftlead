"""TD-1376, design §4.4 *An entry says what it waits for*: the event runner. Once a UTC day the home's tick
sweeps each registered repo that pins agent-cadence and keeps a split ledger: each event gate's check through
the pinned `event_checks.py`, ledgerboard's `sweep()` on the vendored module, and its writes as PRs the home
opens and never merges — a lift through `ledger.py lift` on `lift/TD-n/<gate>`, the board items on
`sweep/<date>`."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from conftest import fake_gh_bin, park_ticks, with_origin

from sessionorc import cadence, gatesweep
from sessionorc import ledgerboard as lb

EVENT = """## TD-7: Waits on a PR

**Priority:** Low
**Added:** 2026-11-01
**Status:** Open
**Blocked by:** event (x-merged)

**Why:** w.

**Event (x-merged):** the PR merges.
check: pr-merged o/r#5

**Fix:** f.
"""
PERSON = """## TD-8: Waits on the person

**Priority:** Low
**Added:** 2026-11-01
**Status:** Open
**Blocked by:** decision (paul)

**Why:** w.

**Ask:** Should it go?

**Fix:** f.
"""
BOARD = "# Needs\n\nPeople: paul\n\n## Needs the user\n\n"
COVER = "- [ ] decide 2026-11-04 (session n/a) — Should it go? Context: TD-8 decision (paul). Due: 2026-11-09.\n"
UTC, LOCAL = date(2026, 11, 5), date(2026, 11, 5)
PASSED = {"id": "TD-7", "name": "x-merged", "outcome": "passed", "evidence": "o/r#5", "why": None}


def _sweep(results: dict, board: str = BOARD) -> dict:
    return lb.sweep(
        [EVENT + "\n" + PERSON], [("git@github.com:o/r.git", "r", board, "")], results, UTC, LOCAL, repo="o/r"
    )


# ── what sweep() decides, on the vendored module ──────────────────────────────────────────────


def test_an_event_whose_check_passed_is_lifted_with_its_evidence():
    got = _sweep({("TD-7", "x-merged"): ("passed", "o/r#5")})
    assert got["lifts"] == [{"id": "TD-7", "gate": "event (x-merged)", "kind": "event", "evidence": "o/r#5"}]
    for results in ({("TD-7", "x-merged"): ("not yet", None)}, {("TD-7", "x-merged"): ("error", None)}, {}):
        assert _sweep(results)["lifts"] == [], results


def test_a_gate_nothing_covers_gets_its_board_item():
    [item] = _sweep({})["to_file"]["github.com/o/r"]
    assert (item["kind"], item["context"], item["text"]) == ("decide", "TD-8 decision (paul)", "Should it go?")
    assert "TD-8 decision (paul)" not in json.dumps(_sweep({}, BOARD + COVER)["to_file"]), "covered: nothing filed"


def test_the_pure_parts():
    assert gatesweep.due(None, UTC) and gatesweep.due(date(2026, 11, 4), UTC) and not gatesweep.due(UTC, UTC)
    assert gatesweep.lift_branch("TD-7", "event (x-merged)") == "lift/TD-7/x-merged"
    assert gatesweep.lift_branch("TD-7", "until 2026-11-05") == "lift/TD-7/until"
    got = {
        "checks": [PASSED],
        "lifts": [{"id": "TD-7", "gate": "event (x-merged)"}],
        "to_file": {"b": [{}]},
        "to_close": {},
        "applied": ["lift TD-7 event (x-merged): opened u"],
    }
    assert gatesweep.summary(got) == (
        "1 event check(s); lifts: TD-7 event (x-merged); 1 item(s) to file, 0 to close\n"
        "  → lift TD-7 event (x-merged): opened u"
    )


@pytest.fixture
def real(monkeypatch):
    """The real functions, which conftest's guard replaces."""
    monkeypatch.setattr(gatesweep, "eligible", gatesweep.ELIGIBLE)
    monkeypatch.setattr(gatesweep, "sweep", gatesweep.SWEEP)


def test_which_roots_are_swept(real, monkeypatch, tmp_path):
    pinned, tree = {"on": False}, {"at": None, "why": "fetch failed"}
    monkeypatch.setattr(cadence, "pinned", lambda root: pinned["on"])
    monkeypatch.setattr(cadence, "tree", lambda root: (tree["at"], tree["why"]))
    assert gatesweep.eligible(tmp_path) == (False, "not pinned")
    pinned["on"] = True
    assert gatesweep.eligible(tmp_path) == (False, "no docs/ledger/README.md")
    (tmp_path / "docs" / "ledger").mkdir(parents=True)
    (tmp_path / "docs" / "ledger" / "README.md").write_text("Ledgerboard: 2\n")
    assert gatesweep.eligible(tmp_path) == (False, "pinned, no tree: fetch failed")
    payload = tmp_path / "payload"
    (payload / "scripts").mkdir(parents=True)
    tree.update(at=payload, why=None)
    assert gatesweep.eligible(tmp_path) == (False, "no scripts/event_checks.py in the pinned tree")
    (payload / "scripts" / "event_checks.py").write_text("")
    (payload / "scripts" / "ledger.py").write_text("")
    assert gatesweep.eligible(tmp_path) == (True, None)


# ── a sweep end to end: a repo with a bare origin, the fake forge, the vendored ledger writer ──


def _git(*a: str) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(real, monkeypatch, tmp_path):
    """A repo whose origin holds TD-7 (an event gate) and TD-8 (the person's gate, uncovered); `cadence.command`
    runs `event_checks.py` as a stub printing `checks.json`'s rows, and `ledger.py` as the vendored
    ledgerboard's writer, which the pinned agent-cadence's wraps; `gh` is the fake forge."""
    root = tmp_path / "r"
    (root / "docs" / "ledger").mkdir(parents=True)
    (root / "docs" / "ledger" / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n")
    (root / "docs" / "ledger" / "TD-7.md").write_text(EVENT)
    (root / "docs" / "ledger" / "TD-8.md").write_text(PERSON)
    (root / "docs" / "user_attention.md").write_text(BOARD)
    _git("init", "-q", "-b", "main", str(root))
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed")
    with_origin(root)
    monkeypatch.setenv("PATH", f"{fake_gh_bin(tmp_path / 'bin')}:{Path(sys.executable).parent}:/usr/bin:/bin")
    rows = tmp_path / "checks.json"
    rows.write_text(json.dumps({"checks": [PASSED]}))
    stub = tmp_path / "event_checks_stub.py"
    stub.write_text(f"print(open({str(rows)!r}).read())\n")
    ran: list[tuple[str, ...]] = []

    def command(where, word, script, *args):
        ran.append((script, *args))
        if script == "event_checks.py":
            return [sys.executable, str(stub)], None
        return [sys.executable, "-m", "sessionorc.ledgerboard.ledger", *args], None

    monkeypatch.setattr(cadence, "command", command)
    return root, ran


def _branch(root: Path, branch: str, path: str) -> str:
    bare = root.parent / f"{root.name}-origin.git"
    return _git("--git-dir", str(bare), "show", f"{branch}:{path}")


def test_a_sweep_opens_a_lift_pr_and_a_board_pr_and_merges_neither(repo):
    root, ran = repo
    got, why = gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert why is None, why
    assert got["applied"] == [
        "lift TD-7 event (x-merged): opened https://github.com/o/r/pull/1",
        "board: opened https://github.com/o/r/pull/2",
    ]
    lifted = _branch(root, "lift/TD-7/x-merged", "docs/ledger/TD-7.md")
    assert "event (x-merged)" not in lifted.split("**Why:**")[0], "the gate is gone from its Blocked by"
    assert "gate lifted: event (x-merged)" in lifted and "o/r#5" in lifted, "logged, with the check's evidence"
    assert ("ledger.py", "lift", "TD-7", "--gate", "event (x-merged)", "--by", "kmaster") == ran[1][:7]
    board = _branch(root, f"sweep/{UTC.isoformat()}", "docs/user_attention.md")
    assert "Context: TD-8 decision (paul)" in board and "Should it go?" in board
    state = json.loads((root.parent / "r-origin.git" / "fake-gh.json").read_text())
    assert [p["state"] for p in state["prs"].values()] == ["open", "open"], "the home opens them, never merges"
    assert _git("-C", str(root), "show", "main:docs/ledger/TD-7.md") == EVENT, "main is untouched"
    assert _git("-C", str(root), "branch", "--list", "lift/*", "sweep/*") == "", "no local branch is left"
    assert len(_git("-C", str(root), "worktree", "list").splitlines()) == 1, "no worktree is left"


def test_a_second_sweep_writes_nothing_twice(repo):
    root, _ = repo
    gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    got, _ = gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert got["applied"] == [
        "lift TD-7 event (x-merged): PR #1 is open — nothing to do",
        "board: an earlier sweep PR #2 is open — 1 to file, 0 to close wait for it",
    ]


def test_a_lift_whose_pr_was_closed_is_never_reopened_and_asked_about(repo, tmp_path):
    root, _ = repo
    gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    state_file = root.parent / "r-origin.git" / "fake-gh.json"
    state = json.loads(state_file.read_text())
    state["prs"]["1"]["state"], state["prs"]["2"]["state"] = "closed", "closed"
    state_file.write_text(json.dumps(state))
    _git("--git-dir", str(root.parent / "r-origin.git"), "branch", "-D", f"sweep/{UTC.isoformat()}")
    got, _ = gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert got["applied"][0] == (
        "lift TD-7 event (x-merged): its PR #1 was closed unmerged — not reopened; an act item asks why"
    )
    board = _branch(root, f"sweep/{UTC.isoformat()}", "docs/user_attention.md")
    assert "Lift of event (x-merged) on TD-7 was closed" in board and "Context: TD-7 event (x-merged) lift" in board


def test_a_check_with_no_answer_is_left_out_and_a_failed_check_run_is_no_reading(repo, tmp_path):
    root, _ = repo
    (tmp_path / "checks.json").write_text(json.dumps({"checks": [{**PASSED, "outcome": None}]}))
    got, _ = gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert got["lifts"] == [] and got["applied"] == ["board: opened https://github.com/o/r/pull/1"]
    (tmp_path / "checks.json").write_text("not json")
    assert gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster") == (
        None,
        "event_checks.py: exit 0, output is not its --json",
    )


def test_another_repos_board_is_left_for_the_second_slice(repo, tmp_path):
    root, _ = repo
    p = {"own": "r", "base": "origin/main", "lifts": [], "to_file": {"github.com/o/x": [{}]}, "to_close": {}}
    assert gatesweep.apply(root, p, today_utc=UTC, today_local=LOCAL, by="kmaster") == [
        "board github.com/o/x: not done — another repo's board is written by hand until TD-1376's second slice "
        "(1 to file, 0 to close)"
    ]


# ── the tick ───────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def agent(agent):
    """The tick parked: its own pass would race the test's."""
    await park_ticks(agent)
    return agent


async def test_the_tick_sweeps_each_sweepable_root_once_a_day(agent, monkeypatch, caplog, tmp_path):
    ran: list[tuple[str, list]] = []
    swept, plain = str(tmp_path / "swept"), str(tmp_path / "plain")
    (tmp_path / "plain").mkdir()
    ok = {swept: (True, None), plain: (False, "not pinned")}
    monkeypatch.setattr(gatesweep, "eligible", lambda root: ok[root])

    def sweep(root, others, **kw):
        ran.append((root, others))
        return {"checks": [PASSED], "lifts": [], "to_file": {}, "to_close": {}, "applied": []}, None

    monkeypatch.setattr(gatesweep, "sweep", sweep)
    agent._repos[swept], agent._repos[plain] = {}, {}
    caplog.set_level(logging.INFO, logger="shiftlead.agent")
    await agent._sweep_pass(UTC)
    assert ran == [(swept, [plain])], "a root the home cannot sweep is not run; every other root's board is read"
    assert "gate sweep — 1 event check(s); lifts: none" in caplog.text
    await agent._sweep_pass(UTC)
    assert len(ran) == 1, "once a UTC day"
    await agent._sweep_pass(date(2026, 11, 6))
    assert len(ran) == 2 and caplog.text.count("no gate sweep — not pinned") == 1, (
        "the next day it runs again, and a standing reason is logged once"
    )


async def test_a_failed_sweep_waits_for_the_next_day(agent, monkeypatch, caplog):
    ran: list[str] = []
    monkeypatch.setattr(gatesweep, "eligible", lambda root: (True, None))

    def sweep(root, others, **kw):
        ran.append(root)
        return None, "no origin/<default>"

    monkeypatch.setattr(gatesweep, "sweep", sweep)
    agent._repos["/r"] = {}
    caplog.set_level(logging.INFO, logger="shiftlead.agent")
    await agent._sweep_pass(UTC)
    await agent._sweep_pass(UTC)
    assert ran == ["/r"] and "the gate sweep gave no reading — no origin/<default>" in caplog.text
