"""Who closed it (design §4.4 *What closed, and by which PR* — **Who closed it**, TD-1899, built by TD-1932): the
ledger history's log carries each commit's trailers after the subject and a `\\x1d`, and every `recent` and
`completed` entry carries `by`, read from its closing commit's trailers alone; the Queue's completed-card members
and archived rows carry it beside `sha`."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_queue import NOW as QNOW
from test_queue import TODAY, _cards, _repo
from test_queue import _entry as _qentry

from sessionorc import ledger
from sessionorc import ledgerboard as lb

FULL = """\
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Co-Authored-By: grinder-ao-1 <grinder-ao-1@shiftlead.placeholder>
Co-authored-by: designer-ao-1 <designer-ao-1@shiftlead.placeholder>
Co-Authored-By: grinder-ao-1 <grinder-ao-1@shiftlead.placeholder>
Co-Authored-By: Paul <7411522+paul@users.noreply.github.com>
Agent-Model: claude-code/claude-opus-5-5
Review: sonnet (BLOCK)
Review: claude-sonnet (sonnet?) (FIXED)
Review: (sonnet, independent) at 2026-11-17T00:00:00Z (SHIP)
Review: (fact-check, doc-only) at 2026-11-17T00:00:00Z (SHIP)
Precheck: 0123456789abcdef0123456789abcdef01234567
Merged-by: grinder-ao-1 (claude-code/claude-opus-5-5)"""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _commit(root: Path, subject: str, trailers: str = "") -> None:
    _git(root, "add", "-A")
    msg = f"{subject}\n\nbody\n\n{trailers}\n" if trailers else f"{subject}\n"
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", msg)


def _file(n: int, title: str) -> str:
    return f"## TD-{n:03d}: {title}\n\n**Priority:** Low\n**Status:** Open.\n"


def _repo_v2(tmp_path: Path, precheck: str | None = 'precheck = "pdm run test"\n') -> Path:
    root = tmp_path / "r"
    (root / "docs" / "ledger" / "archive").mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(root))
    (root / "docs" / "ledger" / lb.LEDGER_README).write_text("# Ledger\n\nLedgerboard: 2\n", encoding="utf-8")
    if precheck is not None:
        (root / "docs" / "cadence.toml").write_text(precheck, encoding="utf-8")
    for n in (1, 2, 3, 4, 5):
        (root / "docs" / "ledger" / f"TD-{n:03d}.md").write_text(_file(n, f"entry {n}"), encoding="utf-8")
    _commit(root, "open them (#1)")
    return root


def _archive(root: Path, n: int, subject: str, trailers: str = "") -> None:
    _git(root, "mv", f"docs/ledger/TD-{n:03d}.md", f"docs/ledger/archive/TD-{n:03d}.md")
    _commit(root, subject, trailers)


def _life(root: Path) -> dict[str, ledger.Change]:
    text = lb.load("docs/ledger", *ledger.fs_io(root))[0]
    life = ledger.history(root, "docs/ledger", text)
    assert life is not None
    return life


def test_the_commit_line_splits_at_its_first_group_separator():
    sha, at, pr, trailers = ledger._commit_line(
        "\x00C abc 2026-11-17T00:00:00+00:00 TD-1 done (#12)\x1dMerged-by: x (m)\x1fReview: a: b (SHIP)"
    )
    assert (sha, pr, at) == ("abc", 12, datetime(2026, 11, 17, tzinfo=UTC))
    assert trailers == [("merged-by", "x (m)"), ("review", "a: b (SHIP)")]  # split at the first `: `
    assert ledger._commit_line("\x00C abc 2026-11-17T00:00:00+00:00 TD-1 done (#12)\x1d")[2:] == (12, [])


def test_every_trailer_reads_into_by():
    trailers = [(k.lower(), v) for k, _, v in (t.partition(": ") for t in FULL.splitlines())]
    by = ledger.closed_by(trailers, 7)
    assert by == {
        "pr": 7,
        "built": ["grinder-ao-1", "designer-ao-1"],  # session co-authors only, in order, each once
        "reviews": [
            {"model": "sonnet", "verdict": "BLOCK"},
            {"model": "claude-sonnet", "verdict": "FIXED"},
            {"model": "sonnet", "verdict": "SHIP"},
            {"model": "fact-check", "verdict": "SHIP"},
        ],
        "precheck": True,
        "merged": "grinder-ao-1",
        "override": False,
    }
    assert ledger.closed_by([("review", "sonnet (SHIP)")], 7) is None  # no Merged-by: no `by`


@pytest.mark.parametrize(
    "value, model, verdict",
    [
        ("unknown (SHIP)", None, "SHIP"),
        ("Unknown (SHIP)", None, "SHIP"),
        ("0 findings (SHIP)", None, "SHIP"),
        ("3 findings (1 fixed) (SHIP)", None, "SHIP"),
        ("independent review by claude-sonnet (subagent) at 2026-11-17 (SHIP)", None, "SHIP"),
        ("(sonnet fact-check, independent) at 2026-11-17 (SHIP)", None, "SHIP"),
        ("(Sonnet, independent, at 2026-11-17 (SHIP)", None, "SHIP"),
        ("- sonnet (SHIP)", None, "SHIP"),
        ("claude-sonnet (subagent) (SHIP)", "claude-sonnet", "SHIP"),
        ("claude-sonnet-5-5 (BLOCK)", "claude-sonnet-5-5", "BLOCK"),
        ("sonnet (ship)", "sonnet", "SHIP"),
        ("sonnet read it", None, None),
    ],
)
def test_a_review_value_reads_its_model_only_in_the_cadences_shapes(value, model, verdict):
    assert ledger.review_of(value) == {"model": model, "verdict": verdict}


def test_a_closed_entry_carries_by_from_its_closing_commit(tmp_path):
    root = _repo_v2(tmp_path, precheck='precheck = "pdm run test"\n')
    _archive(root, 1, "TD-001 done (#9)", FULL)
    _archive(root, 2, "TD-002 done (#10)", "Merged-by: Paul")  # no Review:, no Precheck:
    _archive(root, 3, "TD-003 done (#11)", "Merged-by: grinder-ao-2 (claude-code/x)\nMerge-override: red precheck")
    _archive(root, 4, "TD-004 done (#12)")  # no trailers
    _archive(root, 5, "TD-005 pushed by hand", "Merged-by: Paul")  # no `(#n)`
    life = _life(root)
    assert life["TD-001"].by and life["TD-001"].by["pr"] == 9 and life["TD-001"].pr == 9
    assert life["TD-001"].by["built"] == ["grinder-ao-1", "designer-ao-1"] and life["TD-001"].by["precheck"] is True
    assert life["TD-002"].by == {"pr": 10, "built": [], "reviews": [], "precheck": False, "merged": "Paul",
                                 "override": False}  # fmt: skip
    assert life["TD-003"].by and life["TD-003"].by["override"] is True and life["TD-003"].by["merged"] == "grinder-ao-2"
    assert life["TD-004"].closed is not None and life["TD-004"].pr == 12 and life["TD-004"].by is None
    assert life["TD-005"].by and life["TD-005"].by["pr"] is None and life["TD-005"].pr is None
    got = ledger.reading(root, datetime.now(UTC))
    rec = {e["id"]: e for e in got["recent"]}
    assert rec["TD-001"]["by"] == life["TD-001"].by and rec["TD-004"]["by"] is None
    done = {c["id"]: c for c in ledger.completed(got["recent"], [])}
    assert done["TD-001"]["by"]["reviews"][0] == {"model": "sonnet", "verdict": "BLOCK"}


def test_an_open_entry_reads_no_by(tmp_path):
    root = _repo_v2(tmp_path)
    got = ledger.reading(root, datetime.now(UTC))
    assert {e["id"]: e["by"] for e in got["recent"]}["TD-001"] is None


@pytest.mark.parametrize("cadence", [None, 'pin = "x"\n', "precheck = [unclosed\n"])
def test_precheck_reads_none_where_the_repo_sets_none_or_it_does_not_parse(tmp_path, cadence):
    root = _repo_v2(tmp_path, precheck=cadence)
    _archive(root, 1, "TD-001 done (#9)", FULL)
    by = _life(root)["TD-001"].by
    assert by is not None and by["precheck"] is None and by["merged"] == "grinder-ao-1"


def test_a_reopened_entry_carries_its_last_closes_by(tmp_path):
    root = _repo_v2(tmp_path)
    _archive(root, 1, "TD-001 done (#9)", "Merged-by: first")
    _git(root, "mv", "docs/ledger/archive/TD-001.md", "docs/ledger/TD-001.md")
    _commit(root, "TD-001 reopened (#10)", "Merged-by: reopener")
    assert _life(root)["TD-001"].by is None  # cleared with its close
    _archive(root, 1, "TD-001 done again (#11)", "Merged-by: second")
    by = _life(root)["TD-001"].by
    assert by and by["merged"] == "second" and by["pr"] == 11


def test_by_pr_is_the_archiving_commits_not_the_resolved_lines(tmp_path):
    root = _repo_v2(tmp_path)
    p = root / "docs" / "ledger" / "TD-001.md"
    p.write_text(p.read_text(encoding="utf-8") + "**Resolved:** 2026-11-17 — built (PR #3).\n", encoding="utf-8")
    _commit(root, "TD-001 built (#3)")
    _archive(root, 1, "TD-001 archived with its live check (#20)", "Merged-by: grinder-ao-1")
    assert _life(root)["TD-001"].by["pr"] == 20


def test_the_old_files_history_reads_trailers_too(tmp_path):
    root = tmp_path / "v1"
    (root / "docs").mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(root))
    led = root / "docs" / "technical_debt.md"
    led.write_text("# Technical debt\n\n" + _file(1, "one") + "\n---\n", encoding="utf-8")
    (root / "docs" / "technical_debt_archive.md").write_text("# Archive\n\n", encoding="utf-8")
    (root / "docs" / "cadence.toml").write_text('precheck = "pdm run test"\n', encoding="utf-8")
    _commit(root, "open (#1)")
    led.write_text("# Technical debt\n\n", encoding="utf-8")
    _commit(root, "TD-001 done (#2)", FULL)
    life = ledger.history(root, "docs/technical_debt.md", led.read_text(encoding="utf-8"))
    assert life and life["TD-001"].by and life["TD-001"].by["pr"] == 2 and life["TD-001"].by["precheck"] is True


def test_completed_carries_by_and_none_where_an_entry_has_none():
    recent = [{"id": "TD-1", "title": "t", "closed": "2026-11-17T00:00:00+00:00", "pr": None}]  # no sha, no by
    assert ledger.completed(recent, [])[0]["by"] is None and ledger.completed(recent, [])[0]["sha"] is None


def test_the_queues_completed_members_and_archived_rows_carry_by(tmp_path):
    by = {"pr": 22, "built": ["g"], "reviews": [], "precheck": True, "merged": "g", "override": False}
    root, r = _repo(tmp_path, "r", [_qentry(5, "open", Priority="Medium", Blocked_by="TD-003")],
                    archive=[_qentry(1, "a design", Resolved=f"{TODAY} — designed (PR #21)."),
                             _qentry(2, "its build", Blocked_by="TD-001", Resolved=f"{TODAY} — built (PR #22)."),
                             _qentry(3, "a row", Resolved=f"{TODAY} — (PR #23).")])  # fmt: skip
    r["completed"] = [
        {"id": i, "closed": QNOW.isoformat(), "pr": 22, "sha": "s", "by": by} for i in ("TD-002", "TD-003")
    ]
    q = _cards({root: r})
    members = {e["id"]: e for c in q["completed"] for e in c["entries"]}
    assert members["TD-002"]["by"] == by and members["TD-001"]["by"] is None
    rows = {x["id"]: x for c in q["cards"] for x in c["rows"]}
    assert rows["TD-003"]["archived"] and rows["TD-003"]["by"] == by
