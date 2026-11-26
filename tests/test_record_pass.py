"""TD-2225, design §4.4 *The same pass records a design's Go* (TD-2222): the home's daily pass writes the Go of
every lifted design on its review record, in one PR on `record/<UTC date>` that it opens and never merges, and
`reports.sweep_of` makes that PR a work order in words of its own."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import fake_gh_bin, with_origin

from sessionorc import gatesweep, reports, workorders

UTC = date(2026, 11, 26)
LIFT = '- 2026-11-24: gate lifted: decision (paul) — by paul; answer "Go"'


def design(n: int, *log: str, kind: str = "design-first") -> str:
    lines = "\n".join(log)
    return (
        f"## TD-{n}: A design\n\n**Priority:** Low\n**Added:** 2026-11-01\n**Kind:** {kind}\n**Status:** Open\n\n"
        f"**Why:** w.\n\n**Fix:** f.\n\n**Log:**\n- 2026-11-20: gate added: decision (paul)\n{lines}\n"
    )


def record(n: int, *head: str) -> str:
    return f"# Review record: TD-{n}\n\n**Design:** d\n" + "".join(f"{h}\n" for h in head) + "\n| review |\n|---|\n"


def _git(*a: str) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout


def _commit_push(root: Path) -> None:
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "c")
    _git("-C", str(root), "push", "-q", "origin", "main")
    _git("-C", str(root), "fetch", "-q", "origin")


@pytest.fixture
def repo(monkeypatch, tmp_path):
    """A repo with a bare origin, its ledger and reviews; `gh` is the fake forge. `put` writes files and pushes."""
    root = tmp_path / "r"
    (root / "docs" / "ledger" / "archive").mkdir(parents=True)
    (root / "docs" / "reviews").mkdir(parents=True)
    (root / "docs" / "ledger" / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n")
    _git("init", "-q", "-b", "main", str(root))
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed")
    with_origin(root)
    monkeypatch.setenv("PATH", f"{fake_gh_bin(tmp_path / 'bin')}:{Path(sys.executable).parent}:/usr/bin:/bin")

    def put(files: dict[str, str]) -> None:
        for rel, text in files.items():
            (root / rel).write_text(text)
        _commit_push(root)

    return root, put


def _forge(root: Path) -> dict:
    f = root.parent / f"{root.name}-origin.git" / "fake-gh.json"
    return json.loads(f.read_text()) if f.exists() else {"prs": {}}


def _set_pr(root: Path, n: int, **kw) -> None:
    f = root.parent / f"{root.name}-origin.git" / "fake-gh.json"
    state = _forge(root)
    state["prs"][str(n)].update(kw)
    f.write_text(json.dumps(state))


def _at(root: Path, branch: str, path: str) -> str:
    return _git("--git-dir", str(root.parent / f"{root.name}-origin.git"), "show", f"{branch}:{path}")


def _owed(root: Path) -> dict[str, dict]:
    return {o["id"]: o for o in gatesweep.record_owed(root, "origin/main")}


def test_a_lifted_designs_pending_record_gets_one_pr_changing_its_two_lines(repo):
    root, put = repo
    rec = record(5, "**Decided:** pending", "**Source:** s", "**Go by:** pending")
    put({"docs/ledger/TD-5.md": design(5, LIFT), "docs/reviews/TD-005.md": rec})
    said = gatesweep.record_pass(root, "origin/main", UTC)
    assert said == ["record: opened https://github.com/o/r/pull/1 — 1 records"], said
    got = _at(root, "record/2026-11-26", "docs/reviews/TD-005.md")
    assert got == rec.replace("**Decided:** pending", "**Decided:** 2026-11-24").replace(
        "**Go by:** pending", "**Go by:** paul"
    ), "the two header lines change, nothing else"
    (pr,) = _forge(root)["prs"].values()
    assert pr["title"] == "reviews: record pass 2026-11-26 — 1 records"
    assert not re.search(r"TD-\d", pr["title"]), "the title names no entry id"
    assert f"- record: TD-5 — {LIFT[14:]}" in pr["body"]
    assert pr["state"] == "open", "the home opens it and never merges"
    assert _git("-C", str(root), "show", "main:docs/reviews/TD-005.md") == rec, "main is untouched"
    assert _git("-C", str(root), "branch", "--list", "record/*") == "", "no local branch is left"


def test_a_missing_go_by_is_added_after_source_else_verdict_else_decided():
    w = gatesweep.write_record
    assert w("**Decided:** pending\n**Source:** s\n**Class:** c\n", "paul", "2026-11-24") == (
        "**Decided:** 2026-11-24\n**Source:** s\n**Go by:** paul\n**Class:** c\n"
    )
    assert w("**Verdict:** READY\n**Decided:** pending\n", "paul", "2026-11-24") == (
        "**Verdict:** READY\n**Go by:** paul\n**Decided:** 2026-11-24\n"
    )
    assert w("**Decided:**\n**Class:** c\n", "paul", "2026-11-24") == (
        "**Decided:** 2026-11-24\n**Go by:** paul\n**Class:** c\n"
    ), "an empty Decided becomes the date alone"


def test_decided_keeps_what_it_held_after_the_date():
    w = gatesweep.write_record
    cases = {
        "pending": "2026-11-24",
        "pending, 2026-11-14 (the Hold revision …)": "2026-11-24 — 2026-11-14 (the Hold revision …)",
        "pending (the bought round 5 ended …)": "2026-11-24 — (the bought round 5 ended …)",
        "pending — the rounds run": "2026-11-24 — the rounds run",
        "One more round (Paul, 2026-11-12, …)": "2026-11-24 — One more round (Paul, 2026-11-12, …)",
    }
    for was, now in cases.items():
        assert w(f"**Decided:** {was}\n**Go by:** paul\n", "paul", "2026-11-24") == (
            f"**Decided:** {now}\n**Go by:** paul\n"
        ), was


def test_a_record_naming_a_judge_or_already_dated_is_left(repo):
    root, put = repo
    put(
        {
            "docs/ledger/TD-5.md": design(5, LIFT),
            "docs/reviews/TD-005.md": record(5, "**Decided:** 2026-11-24", "**Go by:** judge"),
            "docs/ledger/TD-6.md": design(6, LIFT),
            "docs/reviews/TD-006.md": record(6, "**Decided:** pending", "**Go by:** judge"),
        }
    )
    owed = _owed(root)
    assert "TD-5" not in owed, "a judge's Go and a date: nothing owed"
    assert gatesweep.write_record(record(6, "**Decided:** pending", "**Go by:** judge"), "paul", "2026-11-24") == (
        record(6, "**Decided:** 2026-11-24", "**Go by:** judge")
    ), "a Go by naming someone else is left; only the date is written"
    assert "TD-6" in owed


@pytest.mark.parametrize(
    "line, person",
    [
        ('- 2026-11-24: gate lifted: decision (paul) — by eyecantell for paul (design); answer "Go"', "paul"),
        ('- 2026-11-24: gate lifted: decision (paul) — by paul; answer "Go"; board shiftlead', "paul"),
        ('- 2026-11-24: gate lifted: decision (paul) — by paul; answer "go ahead"', "paul"),
        ('- 2026-11-24: gate lifted: decision (paul) — by paul; answer "Yes"', "paul"),
        ('- 2026-11-24: gate lifted: decision (paul) — by paul; answer "Go (default)"', "paul"),
    ],
)
def test_a_go_by_any_of_its_roads_is_owed_a_record_naming_the_person(repo, line, person):
    root, put = repo
    put({"docs/ledger/TD-5.md": design(5, line), "docs/reviews/TD-005.md": record(5, "**Decided:** pending")})
    o = _owed(root)["TD-5"]
    assert (o["person"], o["date"], o["line"]) == (person, "2026-11-24", line[14:])


@pytest.mark.parametrize(
    "log",
    [
        [LIFT, "- 2026-11-25: gate added: decision (paul)"],  # set again for a Hold
        [LIFT, '- 2026-11-25: kept waiting: decision (paul) — by paul; answer "One more round"'],
        ['- 2026-11-24: gate lifted: decision (paul) — by paul; answer "Per account, no override"'],
        ['- 2026-11-24: gate lifted: decision (paul) — by paul; answer "Approve"'],
        ["- 2026-11-24: gate lifted: decision (paul) — by grinder; override: the person said so"],
        [LIFT.replace("11-24", "11-20"), "- 2026-11-20: gate added: decision (paul)"],  # one day, the Log's order
    ],
)
def test_a_newer_gate_line_another_answer_or_an_override_owes_nothing(repo, log):
    root, put = repo
    put({"docs/ledger/TD-5.md": design(5, *log), "docs/reviews/TD-005.md": record(5, "**Decided:** pending")})
    assert _owed(root) == {}


def test_an_archived_design_is_read_and_a_build_or_one_with_no_record_is_not(repo):
    root, put = repo
    put(
        {
            "docs/ledger/archive/TD-5.md": design(5, LIFT),
            "docs/reviews/TD-005.md": record(5, "**Decided:** pending"),
            "docs/ledger/TD-6.md": design(6, LIFT, kind="build"),
            "docs/reviews/TD-006.md": record(6, "**Decided:** pending"),
            "docs/ledger/TD-7.md": design(7, LIFT),
        }
    )
    assert set(_owed(root)) == {"TD-5"}


def test_a_record_with_no_decided_line_is_skipped_and_named(repo):
    root, put = repo
    put({"docs/ledger/TD-5.md": design(5, LIFT), "docs/reviews/TD-005.md": record(5, "**Go by:** pending")})
    assert gatesweep.record_pass(root, "origin/main", UTC) == [
        "record TD-5: skipped — its record has no **Decided:** line"
    ]
    assert _forge(root)["prs"] == {}


def test_a_second_pass_on_the_day_or_while_one_is_open_writes_nothing(repo):
    root, put = repo
    put({"docs/ledger/TD-5.md": design(5, LIFT), "docs/reviews/TD-005.md": record(5, "**Decided:** pending")})
    gatesweep.record_pass(root, "origin/main", UTC)
    assert gatesweep.record_pass(root, "origin/main", UTC) == [
        "record: an earlier record PR #1 is open — 1 wait for it"
    ]
    _set_pr(root, 1, state="merged")
    assert gatesweep.record_pass(root, "origin/main", UTC) == [
        "record: record/2026-11-26 was written today already — 1 wait for tomorrow"
    ], "merged but not yet fetched: the day's branch still holds the write"
    assert len(_forge(root)["prs"]) == 1, "running the pass again gives no second PR"


def test_a_record_pr_closed_unmerged_holds_its_records_for_the_window(repo):
    root, put = repo
    put(
        {
            "docs/ledger/TD-5.md": design(5, LIFT),
            "docs/reviews/TD-005.md": record(5, "**Decided:** pending"),
            "docs/ledger/TD-6.md": design(6, LIFT),
            "docs/reviews/TD-006.md": record(6, "**Decided:** pending"),
        }
    )
    gatesweep.record_pass(root, "origin/main", date(2026, 11, 25))
    (pr,) = _forge(root)["prs"].values()
    body = pr["body"].replace("- record: TD-6 —", "(taken out)")  # a taker took TD-6 out before closing it
    _set_pr(root, 1, state="closed", closed_at="2026-11-25T12:00:00Z", body=body)
    said = gatesweep.record_pass(root, "origin/main", UTC)
    assert said == [
        "record TD-5: held — record PR #1 was closed unmerged",
        "record: opened https://github.com/o/r/pull/2 — 1 records",
    ], "the closed PR's body names only what it still held"
    assert "TD-6" in _forge(root)["prs"]["2"]["body"] and "TD-5" not in _forge(root)["prs"]["2"]["body"]
    later = date(2026, 11, 25) + timedelta(days=gatesweep.lb.SWEEP_REASK_DAYS + 1)
    _set_pr(root, 2, state="closed", closed_at=f"{later.isoformat()}T00:00:00Z")
    assert gatesweep.record_pass(root, "origin/main", later) == [
        "record TD-6: held — record PR #2 was closed unmerged",
        "record: opened https://github.com/o/r/pull/3 — 1 records",
    ], "past the window PR #1's hold on TD-5 is gone"
    assert "- record: TD-5 —" in _forge(root)["prs"]["3"]["body"]


def test_the_sweep_runs_the_record_pass_after_its_own_writes(monkeypatch):
    plan = {"base": "origin/main", "to_file": {}, "to_close": {}, "lifts": []}
    monkeypatch.setattr(gatesweep, "plan", lambda *a, **k: plan)
    monkeypatch.setattr(gatesweep, "apply", lambda *a, **k: ["lift: one"])
    monkeypatch.setattr(gatesweep, "record_pass", lambda root, base, day: [f"record: {base} {day}"])
    got, why = gatesweep.SWEEP("r", [], today_utc=UTC, today_local=UTC, by="k")
    assert why is None and got["applied"] == ["lift: one", "record: origin/main 2026-11-26"]


def test_a_record_pass_that_raises_keeps_the_sweeps_own_writes(monkeypatch):
    plan = {"base": "origin/main", "to_file": {}, "to_close": {}, "lifts": []}
    monkeypatch.setattr(gatesweep, "plan", lambda *a, **k: plan)
    monkeypatch.setattr(gatesweep, "apply", lambda *a, **k: ["lift: one"])

    def boom(*a):
        raise KeyError("person")

    monkeypatch.setattr(gatesweep, "record_owed", boom)
    got, why = gatesweep.SWEEP("r", [], today_utc=UTC, today_local=UTC, by="k")
    assert why is None and got["applied"] == ["lift: one", "record: not done — KeyError('person')"]


def test_an_unreadable_decision_line_newest_owes_nothing(repo):
    root, put = repo
    log = [LIFT, '- 2026-11-25: gate lifted: decision (paul) — by paul; answer "Go" and more']
    put({"docs/ledger/TD-5.md": design(5, *log), "docs/reviews/TD-005.md": record(5, "**Decided:** pending")})
    assert _owed(root) == {}


def test_only_a_leading_pending_drops_the_comma_or_dash_after_it():
    assert gatesweep.write_record("**Decided:** — x\n**Go by:** p\n", "p", "2026-11-24") == (
        "**Decided:** 2026-11-24 — — x\n**Go by:** p\n"
    )


def test_a_record_head_is_a_sweep_order_in_words_of_its_own():
    assert reports.sweep_of("record/2026-11-25") == "record"
    assert reports.sweep_of("record/x") is None and reports.sweep_of("record/2026-02-30") is None
    assert reports.gate_head("record/2026-11-25"), "never a red or filing order"
    pr = {"number": 9, "branch": "record/2026-11-25", "sweep": "record", "sweep_since": "2026-11-25T01:00:00Z"}
    pr["url"] = "https://github.com/o/r/pull/9"
    assert workorders.is_sweep_order(pr)
    order = workorders.pr_order(pr)
    assert order["sweep"] == "record" and order["priority"] == "Medium"
    assert order["context"] == f"{pr['url']} · {workorders.RECORD_CONTEXT}"
    assert workorders.pr_note(pr) == (
        f"record PR #9 has been open since 2026-11-25T01:00:00Z: {workorders.RECORD_CONTEXT} — take it or say why"
    )
    sweep = {**pr, "branch": "sweep/2026-11-25", "sweep": "sweep"}
    assert workorders.pr_order(sweep)["context"].endswith(workorders.SWEEP_CONTEXT)
    assert workorders.pr_note(sweep).startswith("sweep PR #9")
