"""TD-591 slice 2, TD-1011 (design §4.7 `ao doctor` **repos**, §4.5a *Repo page: missing seams*, §5 *The
seams*): the client's lines over the repo facts' `seams` — `ao doctor`'s one line per repo and the Repo
page's lines under its title, each drawn from the reading and reading nothing itself."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sessionorc import cadence, ledgerboard, seams
from shiftlead import cli, doctor
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


def test_init_is_read_as_a_repo_name(monkeypatch, capsys):
    """TD-1011, design §4.7: `ao repo` has no `init` word — a repo's ledger comes from dev-cadence's seeds —
    so `init` is a repo's name like any word but `add`, and `--repo` is no option of `ao repo`."""
    got = {"/r/init": {"name": "init", "root": "/r/init", "prs": {}, "ledger": {}}}
    monkeypatch.setattr(cli, "call_sync", lambda method, **kw: got if method == "repos" else [])
    assert cli.main(["--json", "repo", "init"]) == 0
    out = capsys.readouterr().out
    assert '"name": "init"' in out, out
    with pytest.raises(SystemExit):
        cli.main(["repo", "--repo", "x"])


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


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def _dev_cadence(tmp_path: Path) -> tuple[Path, list[str]]:
    """dev-cadence's source (a root holding `sync.sh` and `files/`) with three commits, oldest first."""
    src = tmp_path / "dev-cadence"
    (src / "files").mkdir(parents=True)
    (src / "sync.sh").write_text("#!/bin/sh\n")
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    shas = []
    for n in range(3):
        (src / "files" / "n").write_text(f"{n}\n")
        _git(src, "add", "-A")
        _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"c{n}")
        shas.append(_git(src, "rev-parse", "HEAD"))
    return src, shas


def _consumer(tmp_path: Path, files_commit: str) -> Path:
    root = tmp_path / "notes"
    (root / "docs").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "check_cadence.py").write_text("x = 1\n")
    (root / "docs" / "technical_debt.md").write_text("# Technical debt\n")
    lock = (
        f"source: https://github.com/ShiftLead/dev-cadence\ncommit: {files_commit[:7]}\nfiles_commit: {files_commit}\n"
    )
    (root / "docs" / "cadence-sync.lock").write_text(lock)
    return root


def test_a_lock_older_than_the_builds_oldest_is_unserved_by_name(tmp_path, monkeypatch):
    """TD-1012, §5 *Which dev-cadence*: a lock at the middle of three commits is served with `OLDEST` at
    the first, and unserved in the fixed words with it at the third; ancestry read in the roster's
    dev-cadence checkout."""
    src, (first, middle, third) = _dev_cadence(tmp_path)
    root = _consumer(tmp_path, middle)
    roster = [root, src]
    monkeypatch.setattr(cadence, "OLDEST", first)
    got = seams.reading(root, roster)
    assert got["serve"] == {"ok": True, "lacks": []}
    assert got["cadence_age"] == {"commit": middle, "oldest": first, "descends": True, "why": None}
    assert not [w for w in got["warnings"] if "age" in w]
    monkeypatch.setattr(cadence, "OLDEST", third)
    got = seams.reading(root, roster)
    words = f"unserved: dev-cadence at {middle[:7]} is older than this build reads ({third[:7]}) — sync it"
    assert got["serve"] == {"ok": False, "lacks": [{"key": "age", "words": words}]}
    assert seams.unserved({"seams": got}) == [words]
    assert missing_seams(repo("notes", got))["unserved"] == [[(words, False)]]
    assert seams.reading(src, roster)["cadence_age"] is None, "dev-cadence's source carries no lock to age"
    # a commit the checkout does not hold is a warning, never a lack
    (root / "docs" / "cadence-sync.lock").write_text("files_commit: " + "f" * 40 + "\n")
    got = seams.reading(root, roster)
    assert got["serve"]["ok"] is True
    assert f"dev-cadence's age not read: fffffff is not a commit of {src}" in got["warnings"]


def test_with_no_dev_cadence_checkout_the_forge_compares_and_a_failure_is_a_warning(tmp_path, monkeypatch):
    """TD-1012: no dev-cadence checkout in the roster reads the forge's compare on the lock's source; a
    `gh` that fails is *dev-cadence's age not read: <why>*, never a lack; a read age is carried."""
    root = _consumer(tmp_path, "a" * 40)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gh = bin_ / "gh"
    gh.write_text('#!/bin/sh\necho "$@" >> "$0.calls"\necho "gh: HTTP 503: unavailable" >&2\nexit 1\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    got = seams.reading(root, [root])
    assert got["serve"] == {"ok": True, "lacks": []}
    assert "dev-cadence's age not read: gh: HTTP 503: unavailable" in got["warnings"]
    calls = (bin_ / "gh.calls").read_text()
    assert f"api repos/shiftlead/dev-cadence/compare/{cadence.OLDEST}...{'a' * 40}" in calls
    gh.write_text('#!/bin/sh\necho "$@" >> "$0.calls"\necho \'{"status": "behind"}\'\n')
    got = seams.reading(root, [root], got)
    assert got["serve"]["ok"] is False and got["cadence_age"]["descends"] is False
    gh.write_text("#!/bin/sh\nexit 1\n")
    again = seams.reading(root, [root], got)
    assert again["cadence_age"] == got["cadence_age"], "the age of two commits is read once"
    assert again["serve"] == got["serve"]
