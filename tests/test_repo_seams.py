"""TD-591 slice 2 (design §4.7 `ao doctor` **repos** and `ao repo init`, §4.5a *Repo page: missing
seams*, §5 *The seams*): the client's lines over the repo facts' `seams` — `ao doctor`'s one line per
repo and the Repo page's lines under its title, each drawn from the reading and reading nothing
itself — and `ao repo init`'s empty ledger, which the host agent's seam reading then reads as *ok*."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import cadence, ledgerboard, seams
from shiftlead import cli, doctor, repoinit
from shiftlead.ui.repo import missing_seams

pytestmark = pytest.mark.unit

ABSENT = {"state": "absent", "value": None}


def seam_reading(ledger=None, **over) -> dict:
    """dev-cadence's shape: a parsing ledger of 412 entries and every seam defaulted."""
    r = {
        "ledger": ledger or {"path": "docs/technical_debt.md", "state": "ok", "major": 1, "entries": 412, "why": None},
        "board": {"state": "defaulted", "value": "docs/user_attention.md"},
        "gate": {"state": "defaulted", "value": cadence.DEFAULT_GATE},
        "worktree_setup": {"state": "defaulted", "value": "scripts/hydrate_worktree.sh"},
    }
    r.update(over)
    return r


def repo(name: str, s: dict | None) -> dict:
    return {"name": name, "root": f"/r/{name}", **({"seams": s} if s is not None else {})}


def lines(rows):
    return [(r["verdict"], r["text"]) for r in rows]


def test_every_seam_there_is_ok_an_unset_one_warns_and_a_missing_ledger_lacks():
    absent = {"path": "docs/technical_debt.md", "state": "absent", "major": None, "entries": None, "why": "no ledger"}
    newer = {**absent, "state": "newer", "major": 2, "why": "this file declares Ledgerboard: 2, …"}
    got = doctor.repos(
        {
            "/r/shiftlead": repo("shiftlead", seam_reading()),
            "/r/samscrape": repo("samscrape", seam_reading(gate=ABSENT, worktree_setup=ABSENT)),
            "/r/notes": repo("notes", seam_reading(absent, board=ABSENT, gate=ABSENT, worktree_setup=ABSENT)),
            "/r/later": repo("later", seam_reading(newer)),
            "/r/old": repo("old", None),
        }
    )
    assert lines(got) == [
        ("lacking", f"repo later — ledger is Ledgerboard 2, this build reads {ledgerboard.FORMAT_MAJOR} (sync)"),
        (
            "lacking",
            "repo notes — no ledger at docs/technical_debt.md (`ao repo init`) · no gate: a person merges · "
            "no board: the Inbox is the person's channel · no worktree setup",
        ),
        ("warning", "repo old — seams not read yet (the host agent's first pass, or a build before TD-591)"),
        ("warning", "repo samscrape — no gate: a person merges · no worktree setup"),
        ("ok", "repo shiftlead — ledger 412 entries · board · gate check_cadence.py · worktree setup"),
    ]
    assert got[-1]["seams"]["ledger"]["entries"] == 412  # the raw reading rides beside the text (--json)
    assert lines(doctor.repos({})) == [("ok", "repos — none registered")]


def test_a_configured_gate_is_named_by_its_script_or_its_first_word():
    assert doctor._gate_word("python3 scripts/check_cadence.py --pr {pr} --json") == "check_cadence.py"
    assert doctor._gate_word("make gate PR={pr}") == "make"


def test_the_repo_page_says_each_unset_seam_and_a_ledger_that_is_not_there():
    assert missing_seams(repo("shiftlead", seam_reading())) == {"lines": [], "ledger": None}
    assert missing_seams(repo("old", None)) == {"lines": [], "ledger": None}  # not read yet: nothing said
    led = {"path": "notes/ledger.md", "state": "absent", "major": None, "entries": None, "why": "no ledger"}
    got = missing_seams(repo("notes", seam_reading(led, board=ABSENT, gate=ABSENT, worktree_setup=ABSENT)))
    assert got == {
        "lines": ["no gate: a person merges", "no board: the Inbox is the person's channel", "no worktree setup"],
        "ledger": "no ledger at notes/ledger.md — `ao repo init`",
    }
    bad = {**led, "state": "unreadable", "why": "notes/ledger.md does not parse: boom"}
    assert missing_seams(repo("n", seam_reading(bad)))["ledger"] == (
        "the ledger at notes/ledger.md does not parse — notes/ledger.md does not parse: boom"
    )


def git_repo(tmp_path: Path, name: str = "bare") -> Path:
    root = tmp_path / name
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_repo_init_writes_a_ledger_the_seam_reading_reads_and_refuses_a_second_time(tmp_path, monkeypatch, capsys):
    root = git_repo(tmp_path)
    (root / "sub").mkdir()
    monkeypatch.chdir(root / "sub")  # the checkout this directory is in, from anywhere inside it
    assert cli.main(["--json", "repo", "init"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["wrote"] == ["docs/technical_debt.md", "docs/technical_debt_archive.md"]
    text = (root / "docs/technical_debt.md").read_text()
    assert ledgerboard.entries(text) == [] and "| ID | Title | Priority | Status |" in text
    assert ledgerboard.declared(text) == (
        {
            "owner": ("anchor", "designer", "grinder", "paul"),
            "kind": ("build", "design-first", "live-check", "evaluation", "decision"),
        },
        [],
    )
    assert seams.reading(root)["ledger"]["state"] == "ok"  # a ledger ShiftLead reads
    assert "technical_debt.md" in (root / "docs/technical_debt_archive.md").read_text()
    assert subprocess.run(["git", "-C", str(root), "log"], capture_output=True).returncode != 0  # nothing committed
    assert cli.main(["repo", "init"]) == 1
    assert "a ledger is there: docs/technical_debt.md" in capsys.readouterr().err


def test_repo_init_follows_ledger_and_refuses_an_archive_alone_and_a_path_outside(tmp_path):
    root = git_repo(tmp_path)
    (root / ".shiftlead.yml").write_text("ledger: work/ledger.md\n")
    assert repoinit.init(root) == ["work/ledger.md", "work/ledger_archive.md"]
    assert seams.reading(root)["ledger"] == {
        "path": "work/ledger.md",
        "state": "ok",
        "major": 1,
        "entries": 0,
        "why": None,
    }
    other = git_repo(tmp_path, "other")
    (other / "docs").mkdir()
    (other / "docs/technical_debt_archive.md").write_text("# old\n")
    with pytest.raises(ValueError, match="an archive is there: docs/technical_debt_archive.md"):
        repoinit.init(other)
    assert not (other / "docs/technical_debt.md").exists()
    (other / ".shiftlead.yml").write_text("ledger: ../elsewhere.md\n")
    with pytest.raises(ValueError, match="not a path inside the repo"):
        repoinit.init(other)


def test_repo_init_names_a_registered_repo_and_refuses_outside_a_git_repo(tmp_path, monkeypatch, capsys):
    root = git_repo(tmp_path, "named")

    class Host:
        def repos(self):
            return [str(root)]

    monkeypatch.setattr(cli.hosts, "local_host", lambda: Host())
    monkeypatch.chdir(tmp_path)
    assert cli.main(["repo", "init", "--repo", "named"]) == 0
    assert (root / "docs/technical_debt.md").is_file()
    assert cli.main(["repo", "init", "--repo", "nope"]) == 1
    assert "no registered repo is named 'nope'" in capsys.readouterr().err
    assert cli.main(["repo", "init"]) == 1
    assert "not in a git repo" in capsys.readouterr().err
    assert cli.main(["repo", "--repo", "named"]) == 1
    assert "--repo is `ao repo init`'s" in capsys.readouterr().err
