"""TD-591 slice 2 (design §4.7 `ao doctor` **repos** and `ao repo init`, §4.5a *Repo page: missing
seams*, §5 *The seams*): the client's lines over the repo facts' `seams` — `ao doctor`'s one line per
repo and the Repo page's lines under its title, each drawn from the reading and reading nothing
itself — and `ao repo init`'s empty ledger, which the host agent's seam reading then reads as *ok*."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import ledgerboard, seams
from shiftlead import cli, doctor, repoinit
from shiftlead.adapters.claude_code import CADENCE_HOOK_LINE
from shiftlead.ui.repo import missing_seams

pytestmark = pytest.mark.unit


CURE = "`<dev-cadence>/sync.sh /r/notes`, then a PR"


def seam_reading(ledger=None, lacks=(), warnings=(), **over) -> dict:
    """dev-cadence's shape: a parsing ledger of 412 entries, every seam defaulted, served, nothing warned,
    and the adapter's SessionStart line in the checkout's settings."""
    r = {
        "ledger": ledger or {"path": "docs/technical_debt.md", "state": "ok", "major": 1, "entries": 412, "why": None},
        "board": {"state": "defaulted", "value": "docs/user_attention.md"},
        "worktree_setup": {"state": "defaulted", "value": "scripts/hydrate_worktree.sh"},
        "serve": {"ok": not lacks, "lacks": [{"key": k, "words": w} for k, w in lacks]},
        "warnings": list(warnings),
        "session_start": [CADENCE_HOOK_LINE],
        "source": False,
    }
    r.update(over)
    return r


def repo(name: str, s: dict | None) -> dict:
    return {"name": name, "root": f"/r/{name}", **({"seams": s} if s is not None else {})}


def lines(rows):
    return [(r["verdict"], r["text"]) for r in rows]


def test_a_served_repo_is_ok_a_warning_warns_and_each_lack_unserves_it():
    """TD-1011, §4.7 **repos**: each lack in §5's words is a lack, naming its cure; a warning a warning."""
    newer = {"path": "docs/technical_debt.md", "state": "newer", "major": 2, "entries": None, "why": "Ledgerboard: 2"}
    gate = f"unserved: no gate (no scripts/check_cadence.py) — {CURE}"
    got = doctor.repos(
        {
            "/r/shiftlead": repo("shiftlead", seam_reading()),
            "/r/samscrape": repo("samscrape", seam_reading(warnings=["no worktree setup"])),
            "/r/notes": repo(
                "notes", seam_reading(lacks=[("gate", gate)], warnings=["no board at docs/user_attention.md"])
            ),
            "/r/later": repo("later", {k: v for k, v in seam_reading(newer).items() if k != "serve"}),
            "/r/old": repo("old", None),
        }
    )
    assert lines(got) == [
        ("lacking", f"repo later — ledger is Ledgerboard 2, this build reads {ledgerboard.FORMAT_MAJOR} (sync)"),
        ("lacking", f"repo notes — {gate} · no board at docs/user_attention.md"),
        ("warning", "repo old — seams not read yet"),
        ("warning", "repo samscrape — no worktree setup"),
        ("ok", "repo shiftlead — ledger 412 entries · board · gate check_cadence.py · worktree setup"),
    ]
    assert got[-1]["seams"]["ledger"]["entries"] == 412  # the raw reading rides beside the text (--json)
    assert lines(doctor.repos({})) == [("ok", "repos — none registered")]


def test_a_checkout_without_the_adapters_session_start_line_is_warned():
    """§5 *The seams*: the reading carries the commands as text, the client compares them with the
    adapter's `cadence_hook_line` — under `files/` in dev-cadence's source."""
    words = "no SessionStart line: a session started outside ShiftLead misses the cadence's nudge"
    assert doctor.missing_seams(seam_reading(session_start=["something else"])) == [words]
    assert doctor.missing_seams(seam_reading(session_start=[])) == [words]
    assert doctor.missing_seams(seam_reading()) == []
    source_line = CADENCE_HOOK_LINE.replace("/scripts/cadence_hooks.sh", "/files/scripts/cadence_hooks.sh")
    assert doctor.missing_seams(seam_reading(source=True, session_start=[source_line])) == []
    assert doctor.missing_seams(seam_reading(source=True)) == [words]
    older = {k: v for k, v in seam_reading().items() if k != "session_start"}
    assert doctor.missing_seams(older) == [], "a reading of an older host agent says nothing of it"


def test_the_repo_page_says_each_warning_and_each_lack_with_its_cure_as_code():
    assert missing_seams(repo("shiftlead", seam_reading())) == {"lines": [], "unserved": []}
    assert missing_seams(repo("old", None)) == {"lines": [], "unserved": []}  # not read yet: nothing said
    led = f"unserved: no ledger at notes/ledger.md — {CURE}"
    got = missing_seams(repo("notes", seam_reading(lacks=[("ledger", led)], warnings=["no worktree setup"])))
    assert got == {
        "lines": [[("no worktree setup", False)]],
        "unserved": [
            [
                ("unserved: no ledger at notes/ledger.md — ", False),
                ("<dev-cadence>/sync.sh /r/notes", True),
                (", then a PR", False),
            ]
        ],
    }
    bad = "unserved: the ledger at notes/ledger.md does not parse — boom"
    assert missing_seams(repo("n", seam_reading(lacks=[("ledger", bad)])))["unserved"] == [[(bad, False)]]


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
            "owner": ("designer", "grinder", "paul"),
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


def test_on_a_node_the_repos_line_reads_the_nodes_own_checkouts(tmp_path, monkeypatch):
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    got = {str(mine): repo("mine", seam_reading()), str(theirs): repo("theirs", seam_reading())}
    monkeypatch.setattr(cli, "call_sync", lambda method, **kw: got)

    class Host:
        def repos(self):
            return [str(mine)]

    monkeypatch.setattr(cli.hosts, "local_host", lambda: Host())
    assert list(cli._doctor_repos(node=True)) == [str(mine)]
    assert list(cli._doctor_repos(node=False)) == [str(mine), str(theirs)]


def test_the_wheels_ledgerboard_names_its_release_and_a_vendored_copy_is_read_by_its_header(tmp_path):
    wheel = seams.wheel_release()
    first = Path(ledgerboard.__file__).read_text(encoding="utf-8").split("\n", 1)[0]
    assert wheel and first.startswith(f"# ledgerboard v{wheel} sha256:")
    assert seams.ledgerboard_release(first + "\nrest") == wheel
    assert seams.ledgerboard_release("# ledgerboard v1.2\n") is None  # no hash: not a release header
    older, bare, none, source = (tmp_path / n for n in ("older", "bare", "none", "source"))
    (older / "scripts").mkdir(parents=True)
    (older / "scripts/ledgerboard.py").write_text("# ledgerboard v1.2 sha256:" + "a" * 64 + "\nx = 1\n")
    (bare / "scripts").mkdir(parents=True)
    (bare / "scripts/ledgerboard.py").write_text("# SYNCED FILE\nx = 1\n")
    none.mkdir()
    (source / "files/scripts").mkdir(parents=True)  # dev-cadence's own source
    (source / "files/scripts/ledgerboard.py").write_text(first + "\n")
    assert seams.ledgerboard(older) == {"release": "1.2", "wheel": wheel}
    assert seams.ledgerboard(bare) == {"release": None, "wheel": wheel}
    assert seams.ledgerboard(none) == {"release": None, "wheel": wheel}
    assert seams.ledgerboard(source) == {"release": wheel, "wheel": wheel}
    assert seams.reading(older)["ledgerboard"] == {"release": "1.2", "wheel": wheel}


def test_a_ledgerboard_release_other_than_the_wheels_warns_on_the_repos_line_and_the_repo_page():
    same, older, bare = ({"release": r, "wheel": "1.3"} for r in ("1.3", "1.2", None))
    got = doctor.repos(
        {
            "/r/a": repo("a", seam_reading(ledgerboard=same)),
            "/r/b": repo("b", seam_reading(ledgerboard=older, warnings=["no worktree setup"])),
            "/r/c": repo("c", seam_reading(ledgerboard=bare)),
            "/r/d": repo("d", seam_reading()),  # an older host agent's reading carries no ledgerboard
        }
    )
    assert lines(got) == [
        ("ok", "repo a — ledger 412 entries · board · gate check_cadence.py · worktree setup"),
        ("warning", "repo b — no worktree setup · ledgerboard v1.2 here, v1.3 in this build"),
        ("warning", "repo c — ledgerboard has no release header"),
        ("ok", "repo d — ledger 412 entries · board · gate check_cadence.py · worktree setup"),
    ]
    assert missing_seams(repo("b", seam_reading(ledgerboard=older)))["lines"] == [
        [("ledgerboard v1.2 here, v1.3 in this build", False)]
    ]
    assert missing_seams(repo("a", seam_reading(ledgerboard=same))) == {"lines": [], "unserved": []}
    # a wheel whose header could not be read: every headed copy warns, the build's release unknown
    assert doctor.ledgerboard_warning({"release": "1.3", "wheel": None}) == "ledgerboard v1.3 here, v? in this build"
