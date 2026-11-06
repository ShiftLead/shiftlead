"""TD-1376, design §4.4 *An entry says what it waits for*: the event runner. Once a UTC day the home's tick
sweeps each registered repo that pins agent-cadence and keeps a split ledger: each event gate's check through
the pinned `event_checks.py`, ledgerboard's `sweep()` on the vendored module, and its writes as PRs the home
opens and never merges — a lift through `ledger.py lift` on `lift/TD-n/<gate>`, the board items on
`sweep/<date>`."""

from __future__ import annotations

import json
import logging
import os
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
    assert ran[1][:7] == ("ledger.py", "lift", "TD-7", "--gate", "event (x-merged)", "--by", "kmaster")
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


@pytest.fixture
def other(repo, tmp_path):
    """`repo` with no `People:` on its own board, and a second registered repo `x` whose board names the person:
    sweep() files `r`'s uncovered person gate there (TD-229)."""
    root, _ = repo
    (root / "docs" / "user_attention.md").write_text("# Needs\n\n## Needs the user\n\n")
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "no people")
    _git("-C", str(root), "push", "-q", "origin", "main")
    x = tmp_path / "x"
    (x / "docs").mkdir(parents=True)
    (x / "docs" / "user_attention.md").write_text(BOARD)
    _git("init", "-q", "-b", "main", str(x))
    _git("-C", str(x), "add", "-A")
    _git("-C", str(x), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed")
    with_origin(x)
    return root, x


def _forge(root: Path) -> dict:
    return json.loads((root.parent / f"{root.name}-origin.git" / "fake-gh.json").read_text())


def _set_forge(root: Path, **kw) -> None:
    f = root.parent / f"{root.name}-origin.git" / "fake-gh.json"
    state = json.loads(f.read_text()) if f.exists() else {"prs": {}}
    f.write_text(json.dumps({**state, **kw}))


def test_another_repos_board_gets_one_notices_pr_there_with_qualified_ids(other):
    root, x = other
    got, why = gatesweep.sweep(root, [x], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert why is None, why
    (line,) = [a for a in got["applied"] if a.startswith("board ") and "x" in a.split(":")[0]]
    assert line.endswith("opened https://github.com/o/r/pull/1"), got["applied"]
    slug = got["repo"].replace("/", "-").strip("-")
    (pr,) = _forge(x)["prs"].values()
    assert pr["head"] == f"notices/{slug}-sweep-{UTC.isoformat()}"
    assert pr["state"] == "open", "opened there, merged by none"
    board = _branch(x, pr["head"], "docs/user_attention.md")
    assert f"Context: {got['repo']}#TD-8" in board, board
    assert _git("-C", str(x), "branch", "--list", "notices/*") == "", "no local branch is left in that clone"
    assert len(_git("-C", str(x), "worktree", "list").splitlines()) == 1, "no worktree is left there"


def test_a_second_sweep_files_nothing_there_while_the_first_notices_pr_is_open(other):
    root, x = other
    gatesweep.sweep(root, [x], today_utc=UTC, today_local=LOCAL, by="kmaster")
    got, _ = gatesweep.sweep(root, [x], today_utc=UTC, today_local=LOCAL, by="kmaster")
    (line,) = [a for a in got["applied"] if "from this repo is open there" in a]
    assert "#1" in line and len(_forge(x)["prs"]) == 1


def test_an_open_notices_pr_older_than_the_newest_300_still_holds_the_next(other):
    """The one-open rule reads open PRs alone: an open one past the newest 300 of every state still counts."""
    root, x = other
    gatesweep.sweep(root, [x], today_utc=UTC, today_local=LOCAL, by="kmaster")
    state = _forge(x)
    for n in range(2, 303):
        state["prs"][str(n)] = {"base": "main", "head": f"other-{n}", "title": "t", "body": "", "state": "merged"}
    _set_forge(x, prs=state["prs"])
    got, _ = gatesweep.sweep(root, [x], today_utc=date(2026, 11, 6), today_local=date(2026, 11, 6), by="kmaster")
    assert any("from this repo is open there" in a for a in got["applied"]), got["applied"]
    assert len(_forge(x)["prs"]) == 302


def test_a_closed_or_merged_notices_pr_and_another_repos_sweep_branch_hold_nothing(other):
    root, x = other
    gatesweep.sweep(root, [x], today_utc=UTC, today_local=LOCAL, by="kmaster")
    state = _forge(x)
    state["prs"]["1"]["state"] = "merged"
    state["prs"]["2"] = {"base": "main", "head": "notices/x-sweep-sweep-2026-11-05", "title": "t", "body": "",
                         "state": "open"}  # fmt: skip
    _set_forge(x, prs=state["prs"])
    got, _ = gatesweep.sweep(root, [x], today_utc=date(2026, 11, 6), today_local=date(2026, 11, 6), by="kmaster")
    assert any(a.endswith("pull/3") for a in got["applied"]), got["applied"]


def test_a_board_more_visible_than_this_repo_is_not_written(other):
    root, x = other
    _set_forge(x, visibility="PUBLIC")
    got, _ = gatesweep.sweep(root, [x], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert any("not written — it is public, more visible than this repo (private)" in a for a in got["applied"])
    assert _forge(x)["prs"] == {}


def test_a_board_with_no_registered_clone_is_said_not_done(repo):
    root, _ = repo
    p = {"own": "r", "repo": "o/r", "base": "origin/main", "lifts": [], "to_file": {"o/x": [{}]}, "to_close": {}}
    assert gatesweep.apply(root, p, today_utc=UTC, today_local=LOCAL, by="kmaster") == [
        "board o/x: not done — no registered clone of it (1 to file, 0 to close)"
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


def test_a_closed_lift_asked_about_in_a_sweep_pr_not_yet_fetched_is_not_asked_again(repo):
    """The act item went out in a sweep PR the forge merged and this clone has not fetched: the sweep PR's body
    names its Context, so no second item is filed (gate_sweep.py's `prs_naming` rule)."""
    root, _ = repo
    gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    state_file = root.parent / "r-origin.git" / "fake-gh.json"
    state = json.loads(state_file.read_text())
    state["prs"]["1"]["state"] = "closed"
    state["prs"]["2"].update(state="merged", body="- file: [act] … — Context: TD-7 event (x-merged) lift")
    state_file.write_text(json.dumps(state))
    got, _ = gatesweep.sweep(root, [], today_utc=UTC, today_local=LOCAL, by="kmaster")
    assert got["applied"][0] == (
        "lift TD-7 event (x-merged): its PR #1 was closed unmerged — not reopened; asked on the board already"
    )


# ── host-log: the home runs agent-cadence's reader per gate (§4.4 *The check*, TD-1388) ─────────

HOSTLOG = """## TD-9: Waits on a press

**Priority:** Low
**Added:** 2026-11-01
**Status:** Open
**Blocked by:** event (applied)

**Why:** w.

**Event (applied):** the person applies ao-grind.
check: host-log witnessed kind press "apply ao-grind"

**Fix:** f.

**Log:**
- 2026-11-04: gate added: event (applied)
"""
SOURCES = '[sources.witnessed]\nshape = "directory"\npath = "~/.shiftlead/witnessed"\n'
WITNESSED_TABLE = """[sources.witnessed]
shape = "directory"
path = "~/.shiftlead/witnessed"
match = ["*.jsonl"]
records = "jsonl"
fields = { at = "at", kind = "kind", text = "text", id = "id", repo = "repo" }
"""
HOST = {"repo": "o/r", "visibility": "public", "host_file": Path("/store/host-log.toml")}
GATE = {
    "id": "TD-9",
    "name": "applied",
    "check": lb.parse_check('host-log witnessed kind press "apply ao-grind"'),
    "since": "2026-11-04",
}


@pytest.fixture
def reader(monkeypatch, tmp_path):
    """`hostlog.py` as a stub: it records its argv and standard input, then prints `out` and exits `code`
    (`sleep` seconds first); `cadence.command` hands it out for `hostlog.py` and records the call."""
    rec = tmp_path / "reader.json"
    said = {"out": json.dumps({"outcome": "passed", "evidence": "witnessed/w-1"}), "code": 0, "sleep": 0}
    conf = tmp_path / "reader-conf.json"
    stub = tmp_path / "hostlog_stub.py"
    stub.write_text(
        "import json, sys, time\n"
        f"c = json.load(open({str(conf)!r}))\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}, open({str(rec)!r}, 'w'))\n"
        "time.sleep(c['sleep'])\n"
        "print(c['out'])\n"
        "sys.exit(c['code'])\n"
    )
    calls: list[tuple] = []
    prev = cadence.command  # the `repo` fixture's, where it ran first: every other script still goes there

    def command(where, word, *args):
        if args[:1] != ("hostlog.py",):
            return prev(where, word, *args)
        calls.append((str(where), word, *args))
        conf.write_text(json.dumps(said))
        return [sys.executable, str(stub), *args[1:]], dict(os.environ)

    monkeypatch.setattr(cadence, "command", command)
    monkeypatch.setattr(cadence, "pinned", lambda root: True)
    monkeypatch.setattr(cadence, "is_source", lambda root: False)
    monkeypatch.setattr(cadence, "tree", lambda root: (tmp_path, None))

    def ran() -> dict | None:
        return json.loads(rec.read_text()) if rec.exists() else None

    return said, calls, ran


def test_host_log_gates_are_the_open_entries_host_log_checks():
    assert gatesweep.host_log_gates(EVENT + "\n" + HOSTLOG + "\n" + PERSON) == [GATE]
    undated = HOSTLOG.split("**Log:**")[0]
    assert gatesweep.host_log_gates(undated)[0]["since"] is None
    assert gatesweep.host_log_gates(HOSTLOG.replace("**Status:** Open", "**Status:** Resolved 2026-11-05")) == []
    assert gatesweep.check_line(GATE["check"]) == 'host-log witnessed kind press "apply ao-grind"'
    many = lb.parse_check('host-log witnessed times 3 "x y"')
    assert gatesweep.check_line(many) == 'host-log witnessed times 3 "x y"'


def test_the_reader_is_run_with_the_homes_host_file_and_the_check_last(reader, tmp_path):
    said, calls, ran = reader
    got = gatesweep.host_log(tmp_path, GATE, conf=SOURCES, host=HOST)
    assert got == {"outcome": "passed", "evidence": "witnessed/w-1", "why": None}
    [call] = calls
    assert call[:4] == (str(tmp_path), "run", "hostlog.py", "check")
    assert ran()["argv"] == [
        "check", "--repo-config", "-", "--host-config", "/store/host-log.toml", "--repo", "o/r",
        "--visibility", "public", "--since", "2026-11-04", 'host-log witnessed kind press "apply ao-grind"',
    ]  # fmt: skip
    assert ran()["stdin"] == SOURCES, "the repo's log-sources.toml on standard input"
    gatesweep.host_log(tmp_path, {**GATE, "since": None}, conf="", host={**HOST, "visibility": "private"})
    assert "--since" not in ran()["argv"] and ran()["stdin"] == ""
    assert ran()["argv"][ran()["argv"].index("--visibility") + 1] == "private"
    gatesweep.host_log(tmp_path, GATE, conf="", host={**HOST, "visibility": "internal"})
    assert ran()["argv"][ran()["argv"].index("--visibility") + 1] == "public", "internal is passed as public"


def test_each_reader_answer_maps_to_its_outcome(reader, tmp_path, monkeypatch):
    said, _, _ = reader

    def answer(out: str, code: int = 0) -> dict:
        said.update(out=out, code=code)
        return gatesweep.host_log(tmp_path, GATE, conf="", host=HOST)

    assert answer(json.dumps({"outcome": "not yet", "count": 0})) == {
        "outcome": "not yet",
        "evidence": None,
        "why": "0 counted",
    }
    assert answer(json.dumps({"outcome": "error", "problem": "outside every root"}))["outcome"] == "error"
    assert answer(json.dumps({"outcome": "none", "problem": "no host file"})) == {
        "outcome": None,
        "evidence": None,
        "why": "no host file",
    }
    assert answer(json.dumps({"outcome": "passed", "evidence": "e"}), code=1)["outcome"] == "error", "non-zero"
    assert answer("not json")["outcome"] == "error"
    assert answer(json.dumps(["passed"]))["outcome"] == "error", "not one JSON object"
    assert answer(json.dumps({"outcome": "maybe"}))["outcome"] == "error"
    monkeypatch.setattr(gatesweep, "HOSTLOG_TIMEOUT", 0.5)
    said["sleep"] = 5
    got = answer(json.dumps({"outcome": "passed"}))
    assert got["outcome"] == "error" and "gave no answer in" in got["why"], "the hard timeout"


def test_a_repo_the_reader_cannot_run_for_is_error_without_a_run(reader, tmp_path, monkeypatch):
    _, calls, _ = reader
    assert "no <repo> id" in gatesweep.host_log(tmp_path, GATE, conf="", host={**HOST, "repo": None})["why"]
    monkeypatch.setattr(cadence, "tree", lambda root: (None, "fetch failed"))
    assert gatesweep.host_log(tmp_path, GATE, conf="", host=HOST) == {
        "outcome": "error",
        "evidence": None,
        "why": "agent-cadence's pinned tree could not be made: fetch failed",
    }
    monkeypatch.setattr(cadence, "pinned", lambda root: False)
    assert gatesweep.host_log(tmp_path, GATE, conf="", host=HOST)["outcome"] == "error"
    assert calls == [], "none of them ran the reader"
    monkeypatch.setattr(cadence, "tree", lambda root: (tmp_path, None))
    monkeypatch.setattr(cadence, "is_source", lambda root: True)
    assert gatesweep.host_log(tmp_path, GATE, conf="", host=HOST)["outcome"] == "passed", "agent-cadence's own source"
    assert len(calls) == 1


def test_a_source_checkout_is_what_cadence_is_source_reads(tmp_path):
    (tmp_path / "files").mkdir()
    (tmp_path / "launcher").mkdir()
    (tmp_path / "launcher" / "INTERFACE").write_text("1\n")
    assert cadence.is_source(tmp_path) and not cadence.pinned(tmp_path)


def test_the_homes_answers_replace_event_checks_rows_for_host_log_gates(reader, tmp_path, caplog):
    said, calls, ran = reader
    root = tmp_path / "h"
    (root / "docs" / "ledger").mkdir(parents=True)
    (root / gatesweep.LOG_SOURCES).write_text(SOURCES)
    _git("init", "-q", "-b", "main", str(root))
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed")
    (root / gatesweep.LOG_SOURCES).write_text("# a working-tree edit, not the base's\n")
    theirs = [PASSED, {"id": "TD-9", "name": "applied", "outcome": None, "evidence": None, "why": "no host file"}]
    said["out"] = json.dumps({"outcome": "error", "problem": "the source is private"})
    caplog.set_level(logging.INFO, logger="shiftlead.agent")
    got = gatesweep.host_log_rows(root, "main", EVENT + "\n" + HOSTLOG, theirs, HOST)
    assert got == [
        PASSED,
        {"id": "TD-9", "name": "applied", "outcome": "error", "evidence": None, "why": "the source is private"},
    ]
    assert ran()["stdin"] == SOURCES, "read from the base the ledger was read from"
    assert "TD-9 event (applied), host-log error — the source is private" in caplog.text, "the problem is logged"
    (root / gatesweep.LOG_SOURCES).unlink()
    _git("-C", str(root), "rm", "-q", "--cached", gatesweep.LOG_SOURCES)
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "drop")
    gatesweep.host_log_rows(root, "main", HOSTLOG, [], HOST)
    assert ran()["stdin"] == "", "no file: empty input"
    calls.clear()
    assert gatesweep.host_log_rows(root, "main", EVENT, [PASSED], HOST) == [PASSED] and calls == []


def test_a_passed_host_log_gate_is_lifted_with_the_readers_evidence_and_a_none_is_left_out(repo, reader):
    root, ran = repo
    said, _, _ = reader
    (root / "docs" / "ledger" / "TD-9.md").write_text(HOSTLOG)
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "td9")
    _git("-C", str(root), "push", "-q", "origin", "main")
    _git("-C", str(root), "fetch", "-q", "origin")
    said["out"] = json.dumps({"outcome": "none", "problem": "no host file"})
    p = gatesweep.plan(root, [], today_utc=UTC, today_local=LOCAL, host=HOST)
    assert {x["id"] for x in p["lifts"]} == {"TD-7"} and "TD-9" not in json.dumps(p["to_file"]), "none: left out"
    said["out"] = json.dumps({"outcome": "passed", "evidence": "witnessed/w-3"})
    p = gatesweep.plan(root, [], today_utc=UTC, today_local=LOCAL, host=HOST)
    assert {"id": "TD-9", "gate": "event (applied)", "kind": "event", "evidence": "witnessed/w-3"} in p["lifts"]


def test_forge_visibility_reads_gh_and_glab(monkeypatch, tmp_path):
    seen: list = []

    def gh(root, *args):
        seen.append(("gh", str(root), args))
        return subprocess.CompletedProcess(args, 0, "INTERNAL\n", "")

    monkeypatch.setattr(gatesweep, "_gh", gh)
    assert gatesweep.forge_visibility(tmp_path, "git@github.com:o/r.git") == "internal"
    assert seen[0][2] == ("repo", "view", "--json", "visibility", "--jq", ".visibility")
    monkeypatch.setattr(gatesweep, "_gh", lambda root, *a: subprocess.CompletedProcess(a, 1, "", "no"))
    assert gatesweep.forge_visibility(tmp_path, "git@github.com:o/r.git") is None

    def glab(directory, host, path, timeout):
        seen.append(("glab", host, path))
        return {"visibility": "private"}, None

    monkeypatch.setattr(gatesweep.reports, "_glab_api", glab)
    assert gatesweep.forge_visibility(tmp_path, "git@gitlab.com:g/sub/r.git") == "private"
    assert seen[-1] == ("glab", "gitlab.com", "projects/g%2Fsub%2Fr")
    assert gatesweep.forge_visibility(tmp_path, "git@example.org:o/r.git") is None, "no forge it can ask"


async def test_the_tick_hands_the_sweep_the_repo_id_visibility_and_host_file(agent, monkeypatch, tmp_path):
    from sessionorc import witness

    root = str(tmp_path / "s")
    reads: list[str] = []
    answers = iter([None, "private"])

    def vis(r, remote):
        reads.append(remote)
        return next(answers)

    hosts: list = []

    def sweep(root, others, **kw):
        hosts.append(kw["host"])
        return {"checks": [], "lifts": [], "to_file": {}, "to_close": {}, "applied": []}, None

    monkeypatch.setattr(gatesweep, "eligible", lambda r: (True, None))
    monkeypatch.setattr(gatesweep, "forge_visibility", vis)
    monkeypatch.setattr(gatesweep, "sweep", sweep)
    agent._repos[root] = {"remote": "git@github.com:o/r.git"}
    await agent._sweep_pass(UTC)
    assert hosts[-1] == {"repo": "o/r", "visibility": "public", "host_file": witness.host_file()}, "unread: public"
    await agent._sweep_pass(date(2026, 11, 6))
    assert hosts[-1]["visibility"] == "private", "a failed read is tried again at the next due reading"
    await agent._sweep_pass(date(2026, 11, 7))
    assert hosts[-1]["visibility"] == "private" and len(reads) == 2, "a read once made is kept for the agent's life"


async def test_a_root_whose_host_log_arguments_raise_is_still_swept_with_no_repo_id(agent, monkeypatch, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    hosts: dict[str, dict] = {}

    def sweep(root, others, **kw):
        hosts[root] = kw["host"]
        return {"checks": [], "lifts": [], "to_file": {}, "to_close": {}, "applied": []}, None

    async def args(root):
        if root == a:
            raise ValueError("a malformed remote")
        return {"repo": "o/b", "visibility": "public", "host_file": "h"}

    monkeypatch.setattr(gatesweep, "eligible", lambda r: (True, None))
    monkeypatch.setattr(gatesweep, "sweep", sweep)
    monkeypatch.setattr(agent, "_host_log_args", args)
    agent._repos[a] = {"remote": "x"}
    agent._repos[b] = {"remote": "git@github.com:o/b.git"}
    await agent._sweep_pass(date(2026, 11, 6))
    assert hosts[a]["repo"] is None, "its host-log gates answer error, as a root with no origin id"
    assert hosts[b]["repo"] == "o/b", "the pass goes on to the next root"


def test_against_the_real_reader_a_press_today_lifts_a_gate_added_yesterday_and_one_yesterday_does_not(tmp_path):
    """The pinned `hostlog.py` itself, through `cadence.command` for this checkout, on a test home whose
    `witnessed/start` predates yesterday and whose host file the home wrote, with this repo's committed
    `log-sources.toml` (the design's table) on standard input."""
    from datetime import UTC, datetime, timedelta

    from conftest import pinned_script

    from sessionorc import witness

    pinned_script("hostlog.py")  # skips where the pinned tree cannot be reached
    root = Path(__file__).resolve().parents[1]
    store = Path(os.path.realpath(tmp_path / "store"))
    log_dir = store / "witnessed"
    now = datetime.now(UTC)
    witness.ensure_start(now - timedelta(days=3), root=log_dir)
    assert witness.ensure_host_file(store)
    host = {"repo": "o/r", "visibility": "public", "host_file": witness.host_file(store)}
    committed = root / gatesweep.LOG_SOURCES  # #2996's; the design's table until it merges
    conf = committed.read_text(encoding="utf-8") if committed.is_file() else WITNESSED_TABLE
    gate = {**GATE, "since": (now - timedelta(days=1)).date().isoformat()}
    witness.append("press", "o/r", "apply ao-grind", at=now - timedelta(days=1), root=log_dir)
    witness.append("press", "elsewhere/r", "apply ao-grind", at=now, root=log_dir)  # another repo's
    got = gatesweep.host_log(root, gate, conf=conf, host=host)
    assert got["outcome"] == "not yet", got
    rec = witness.append("press", "o/r", "apply ao-grind", at=now, root=log_dir)
    got = gatesweep.host_log(root, gate, conf=conf, host=host)
    assert got["outcome"] == "passed" and got["evidence"] == f"witnessed/{rec['id']}", got
