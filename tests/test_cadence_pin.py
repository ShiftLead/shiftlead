"""TD-1014 (design §5 *How the readers find dev-cadence*): a repo that pins dev-cadence (`docs/cadence.toml`'s
`[dev-cadence]`, dev-cadence TD-129) carries no copy, so its readers ask one resolver, `cadence.command`,
which runs the launcher this build vendors under the host agent's own Python. A pinned repo (no lock)
reads served, its gate runs through the resolver, its age is its pin's `ref` against `OLDEST`, and its
ledgerboard release is the pinned tree's; a pin the launcher refuses or cannot resolve is a lack by name."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sessionorc import cadence, conventions, seams
from sessionorc import ledgerboard as lb
from shiftlead import doctor

pytestmark = pytest.mark.unit

LEDGER = "# Technical debt\n\n## TD-001: One thing\n\n**Priority:** Low\n**Status:** Open.\n\n---\n"
# the stub launcher: `-C <dir> path` prints the payload (STUB_PAYLOAD) or refuses as the launcher does
# (STUB_REFUSE); `-C <dir> run check_cadence.py --pr N --json` prints a verdict; each call is logged
STUB = r"""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "root": os.environ.get("CADENCE_REPO_ROOT")}) + "\n")
refuse = os.path.join(here, "refuse")
if os.path.exists(refuse):
    print("dev-cadence: " + open(refuse).read(), file=sys.stderr)
    sys.exit(2)
args = sys.argv[3:]
if args == ["path"]:
    print(open(os.path.join(here, "payload")).read())
elif args[:2] == ["run", "check_cadence.py"]:
    pr = int(args[3])
    print(json.dumps({"prs": [{"pr": pr, "verdict": "fail", "rows": [{"rule": "review", "status": "fail"}]}]}))
elif args == ["run", "cadence_changes.py", "--json"]:
    entry = {"heading": "### 2026-10-26 — pinned", "date": "2026-10-26", "title": "pinned", "landed": None}
    print(json.dumps({"ref": "origin/main", "entries": [entry]}))
else:
    sys.exit(2)
"""


@pytest.fixture(autouse=True)
def _fresh_trees():
    cadence._trees.clear()
    yield
    cadence._trees.clear()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def _dev_cadence(tmp_path: Path) -> tuple[Path, list[str]]:
    """dev-cadence's source (a root holding `sync.sh` and `files/`) with two commits, oldest first."""
    src = tmp_path / "dev-cadence"
    (src / "files").mkdir(parents=True)
    (src / "sync.sh").write_text("#!/bin/sh\n")
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    shas = []
    for n in range(2):
        (src / "files" / "n").write_text(f"{n}\n")
        _git(src, "add", "-A")
        _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"c{n}")
        shas.append(_git(src, "rev-parse", "HEAD"))
    return src, shas


def _stub(tmp_path: Path, monkeypatch, payload: Path) -> Path:
    stub = tmp_path / "launcher"
    stub.mkdir()
    (stub / "dev_cadence.py").write_text(STUB)
    (stub / "payload").write_text(str(payload))
    monkeypatch.setattr(cadence, "LAUNCHER", stub / "dev_cadence.py")
    return stub


def _calls(stub: Path) -> list[dict]:
    path = stub / "calls.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _payload(tmp_path: Path) -> Path:
    """A pinned tree's `files/`: the gate and the wheel's own ledgerboard."""
    payload = tmp_path / "tree" / "files"
    (payload / "scripts").mkdir(parents=True)
    (payload / "scripts" / "check_cadence.py").write_text("x = 1\n")
    shutil.copy(lb.__file__, payload / "scripts" / "ledgerboard.py")
    return payload


def _pinned(tmp_path: Path, ref: str, source: str = "https://github.com/ShiftLead/dev-cadence") -> Path:
    root = tmp_path / "notes"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text(LEDGER)
    (root / "docs" / "cadence.toml").write_text(f'[dev-cadence]\nsource = "{source}"\nref = "{ref}"\n')
    return root


def test_the_resolver_runs_the_vendored_launcher_under_this_python():
    argv, env = cadence.command("/r/notes", "run", "check_cadence.py", "--pr", "3")
    assert argv == [sys.executable, str(cadence.LAUNCHER), "-C", "/r/notes", "run", "check_cadence.py", "--pr", "3"]
    assert env["CADENCE_REPO_ROOT"] == "/r/notes"
    assert cadence.LAUNCHER.is_file() and cadence.LAUNCHER.parent == Path(cadence.__file__).parent
    cp = subprocess.run(argv[:2] + ["--interface"], capture_output=True, text=True, check=True)
    assert cp.stdout.strip() == "1", "the vendored launcher's interface"


def test_the_vendored_launcher_is_dev_cadences_at_the_named_commit():
    """The launcher is frozen: a change to it is a new vendoring, with `LAUNCHER_COMMIT` moved and this hash."""
    digest = hashlib.sha256(cadence.LAUNCHER.read_bytes()).hexdigest()
    assert digest == "495b4610731a0a8b0355b97d882b526439f3aa4d7c417d4b87b269a06940ed57"
    assert cadence.LAUNCHER_COMMIT == "8008a10e50e9b70cd571984bb2810d79d59c94c7"


def test_a_pinned_repo_with_no_lock_reads_served_and_its_gate_runs_through_the_resolver(tmp_path, monkeypatch):
    src, (first, second) = _dev_cadence(tmp_path)
    monkeypatch.setattr(cadence, "OLDEST", first)
    stub = _stub(tmp_path, monkeypatch, _payload(tmp_path))
    root = _pinned(tmp_path, second)
    assert cadence.pinned(root) and cadence.pin(root) == ("https://github.com/ShiftLead/dev-cadence", second)
    got = seams.reading(root, [root, src])
    assert got["serve"] == {"ok": True, "lacks": []}, got["serve"]
    assert got["cadence_age"] == {
        "commit": second,
        "oldest": first,
        "seed": cadence.SEED,
        "descends": True,
        "why": None,
    }
    assert got["ledgerboard"] == {"release": seams.wheel_release(), "wheel": seams.wheel_release(), "pinned": True}
    assert doctor.ledgerboard_warning(got["ledgerboard"]) is None
    assert cadence.gate(root) == cadence.PINNED_GATE
    assert cadence.check(root, 7) == {"verdict": "fail", "failed": ["review"]}
    run = [c for c in _calls(stub) if c["argv"][2:3] == ["run"]]
    assert run == [{"argv": ["-C", str(root), "run", "check_cadence.py", "--pr", "7", "--json"], "root": str(root)}]
    # one reading's readers ask the launcher for the tree once
    assert len([c for c in _calls(stub) if c["argv"][2:] == ["path"]]) == 1


def test_a_pin_older_than_oldest_reads_the_older_tree_lack(tmp_path, monkeypatch):
    src, (first, second) = _dev_cadence(tmp_path)
    monkeypatch.setattr(cadence, "OLDEST", second)
    _stub(tmp_path, monkeypatch, _payload(tmp_path))
    root = _pinned(tmp_path, first)
    got = seams.reading(root, [root, src])
    words = f"unserved: dev-cadence at {first[:7]} is older than this build reads ({second[:7]}) — bump the pin"
    assert got["serve"] == {"ok": False, "lacks": [{"key": "age", "words": words}]}


def test_a_pin_the_launcher_refuses_or_cannot_resolve_is_a_lack_by_name(tmp_path, monkeypatch):
    src, (first, second) = _dev_cadence(tmp_path)
    monkeypatch.setattr(cadence, "OLDEST", first)
    stub = _stub(tmp_path, monkeypatch, _payload(tmp_path))
    root = _pinned(tmp_path, second)
    (stub / "refuse").write_text("this pin needs launcher interface 2; this launcher is 1 — install a newer launcher")
    got = seams.reading(root, [root, src])
    words = (
        "unserved: dev-cadence's pin does not resolve — it needs launcher interface 2, this build carries 1"
        " — a newer ShiftLead"
    )
    assert got["serve"] == {"ok": False, "lacks": [{"key": "cadence", "words": words}]}, "no gate lack beside it"
    assert doctor.ledgerboard_warning(got["ledgerboard"]) is None, "a pin with no tree warns for no copy"
    assert cadence.check(root, 7) is None
    cadence._trees.clear()
    (stub / "refuse").write_text("git fetch: could not read from remote")
    lacks = seams.reading(root, [root, src])["serve"]["lacks"]
    assert lacks == [
        {
            "key": "cadence",
            "words": "unserved: dev-cadence's pin does not resolve — git fetch: could not read from remote",
        }
    ]
    # a ref the launcher would refuse never reaches it
    (stub / "refuse").unlink()
    (root / "docs" / "cadence.toml").write_text(
        '[dev-cadence]\nsource = "https://github.com/ShiftLead/dev-cadence"\nref = "main"\n'
    )
    lack = seams.reading(root, [root, src])["serve"]["lacks"][0]
    assert lack["key"] == "cadence" and lack["words"].startswith("unserved: dev-cadence's pin does not parse — ")
    assert "ref must be a full 40-hex commit" in lack["words"] and lack["words"].endswith(seams.cure(root))


def test_a_launcher_that_hangs_cannot_run_or_names_no_directory_is_a_lack_in_words(tmp_path, monkeypatch):
    """TD-1028: each way `_tree` answers `(None, why)` besides a refusal is said in words a lack prints — a
    launcher past its timeout, one that cannot run, one that names no tree or a path that is not a directory;
    a refusal on several stderr lines is said by its last, the reason."""
    root = _pinned(tmp_path, "a" * 40)
    argv = []
    monkeypatch.setattr(cadence, "command", lambda repo, word, *args: (argv, dict(os.environ)))

    def said(*cmd, timeout=cadence.TREE_TIMEOUT):
        argv[:] = cmd
        cadence._trees.clear()
        return cadence.tree(root, timeout)

    assert said(sys.executable, "-c", "import time; time.sleep(30)", timeout=2) == (
        None,
        "the launcher gave no answer in 2s",
    )
    missing = tmp_path / "no-such-launcher"
    assert said(str(missing)) == (None, "the launcher could not run: No such file or directory")
    a_file = tmp_path / "a-file"
    a_file.write_text("x\n")
    assert said(sys.executable, "-c", f"print({str(a_file)!r})") == (
        None,
        f"the launcher named {a_file}, which is not a directory here",
    )
    assert said(sys.executable, "-c", "print()") == (None, "the launcher named no tree, which is not a directory here")
    refusal = "import sys; print('fetching', file=sys.stderr); print('dev-cadence: no such ref', file=sys.stderr)"
    assert said(sys.executable, "-c", refusal + "; sys.exit(2)") == (None, "no such ref")
    assert said(sys.executable, "-c", f"print({str(tmp_path)!r})") == (tmp_path, None)


def test_a_pinned_tree_without_the_gate_is_unserved_and_a_lock_keeps_the_copy_read(tmp_path, monkeypatch):
    src, (first, second) = _dev_cadence(tmp_path)
    monkeypatch.setattr(cadence, "OLDEST", first)
    payload = _payload(tmp_path)
    (payload / "scripts" / "check_cadence.py").unlink()
    _stub(tmp_path, monkeypatch, payload)
    root = _pinned(tmp_path, second)
    words = "unserved: no gate (no check_cadence.py in the pinned tree) — bump the pin"
    assert seams.reading(root, [root, src])["serve"]["lacks"] == [{"key": "gate", "words": words}]
    # while a repo still has the lock, its copy is read: the pin is not
    (root / "docs" / "cadence-sync.lock").write_text(f"source: x\ncommit: {second[:7]}\nfiles_commit: {second}\n")
    assert not cadence.pinned(root) and cadence.gate(root) is None
    assert seams.reading(root, [root, src])["serve"]["lacks"][0]["key"] == "gate"
    (root / "scripts").mkdir()
    (root / cadence.SCRIPT).write_text("")
    assert cadence.gate(root) == cadence.DEFAULT_GATE


def test_a_repo_with_neither_pin_nor_lock_names_both(tmp_path):
    root = tmp_path / "bare"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text(LEDGER)
    (root / "docs" / "cadence.toml").write_text("[other]\nx = 1\n")  # a cadence.toml with no pin is no pin
    assert not cadence.pinned(root)
    lack = seams.reading(root)["serve"]["lacks"][0]
    assert lack == {
        "key": "cadence",
        "words": "unserved: no dev-cadence (no pin in docs/cadence.toml, no docs/cadence-sync.lock) — "
        + seams.cure(root),
    }


def test_a_pinned_repos_conventions_run_the_pinned_trees_script_through_the_resolver(tmp_path, monkeypatch):
    """Design §6 rule 12 (TD-1014 slice 3): a pinned repo has no `scripts/cadence_changes.py`; the relay
    runs the pinned tree's through the resolver, and a tree without it gives no reading."""
    payload = _payload(tmp_path)
    stub = _stub(tmp_path, monkeypatch, payload)
    root = _pinned(tmp_path, "a" * 40)
    assert not conventions.has_script(root) and conventions.read(root) == (None, "no script"), "the tree carries none"
    (payload / "scripts" / "cadence_changes.py").write_text("x = 1\n")
    cadence._trees.clear()
    assert conventions.has_script(root)
    got = conventions.read(root)
    assert got == (
        {
            "ref": "origin/main",
            "entries": [
                {
                    "heading": "### 2026-10-26 — pinned",
                    "date": "2026-10-26",
                    "title": "pinned",
                    "body": "",
                    "landed": None,
                }
            ],
        },
        None,
    )
    ran = [c for c in _calls(stub) if c["argv"][2:3] == ["run"]]
    assert ran == [{"argv": ["-C", str(root), "run", "cadence_changes.py", "--json"], "root": str(root)}]
    # a lock beside the pin keeps the copy's script, which this checkout lacks
    (root / "docs" / "cadence-sync.lock").write_text("files_commit=x\n")
    assert not conventions.has_script(root)


def test_the_dev_cadence_console_script_runs_the_vendored_launcher(tmp_path):
    """Design §4.4a, TD-1014: `pyproject.toml` declares `dev-cadence` over `dev_cadence_entry.main`, which runs
    the vendored launcher and says a refusal on stderr with exit 2, as the launcher's own `__main__` does."""
    import tomllib

    scripts = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["dev-cadence"] == "sessionorc.dev_cadence_entry:main"
    run = [sys.executable, "-c", "from sessionorc.dev_cadence_entry import main; main()"]
    cp = subprocess.run([*run, "--interface"], capture_output=True, text=True)
    assert (cp.returncode, cp.stdout.strip()) == (0, "1")
    _git(tmp_path, "init", "-q", str(tmp_path / "bare"))
    cp = subprocess.run([*run, "-C", str(tmp_path / "bare"), "words"], capture_output=True, text=True)
    assert cp.returncode == 2 and cp.stderr.startswith("dev-cadence: ") and "Traceback" not in cp.stderr


def test_precheck_is_read_from_the_toml_at_a_rev_with_no_script(tmp_path):
    """TD-1037 (design §6 *Where `precheck` is read*): `precheck_command` reads `docs/cadence.toml` at the rev
    named, never the working tree: set, unset, empty, not a string, and a file that does not parse."""
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    toml = root / cadence.PIN
    # no commit yet: the rev is not there, which is not known — never read as unset
    assert cadence.precheck_command(root, "HEAD") == (None, "docs/cadence.toml could not be read: no HEAD here")

    def commit(text: str) -> None:
        toml.write_text(text)
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c")

    commit("# nothing yet\n")
    toml.unlink()
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "no file")
    assert cadence.precheck_command(root, "HEAD") == (None, None)  # no file at the rev: unset
    commit('precheck = "  pdm run test  "\n')
    assert cadence.precheck_command(root, "HEAD") == ("pdm run test", None)
    toml.write_text("# the working tree is never read\n")
    assert cadence.precheck_command(root, "HEAD") == ("pdm run test", None)
    for text in ("# nothing set\n", 'precheck = "  "\n', "precheck = 3\n", '[x]\nprecheck = "y"\n'):
        commit(text)
        assert cadence.precheck_command(root, "HEAD") == (None, None), text
    commit("precheck = \n")
    assert cadence.precheck_command(root, "HEAD") == (None, "docs/cadence.toml does not parse")


def test_precheck_script_in_each_layout_and_absent(tmp_path, monkeypatch):
    """TD-1037 (design §6 *What runs*): the checkout's `scripts/`, dev-cadence's own `files/scripts/`, and the
    resolver's `dev-cadence run` with its env in a pinned repo; absent in each, *no precheck.py here*."""
    absent = (None, "no precheck.py here")
    plain = tmp_path / "plain"
    (plain / "scripts").mkdir(parents=True)
    assert cadence.precheck_script(plain) == absent
    (plain / "scripts" / "precheck.py").write_text("")
    assert cadence.precheck_script(plain) == ((["python3", "scripts/precheck.py"], None), None)
    src, (first, second) = _dev_cadence(tmp_path)
    assert cadence.precheck_script(src) == absent
    (src / "files" / "scripts").mkdir()
    (src / "files" / "scripts" / "precheck.py").write_text("")
    assert cadence.precheck_script(src) == ((["python3", "files/scripts/precheck.py"], None), None)
    payload = _payload(tmp_path)
    _stub(tmp_path, monkeypatch, payload)
    root = _pinned(tmp_path, second)
    assert cadence.precheck_script(root) == absent  # a pinned tree older than the script
    (payload / "scripts" / "precheck.py").write_text("")
    cadence._trees.clear()
    (argv, env), why = cadence.precheck_script(root)
    assert why is None and argv == cadence.command(root, "run", "precheck.py")[0]
    assert env is not None and env["CADENCE_REPO_ROOT"] == str(root)
    (tmp_path / "launcher" / "refuse").write_text("no such ref")
    cadence._trees.clear()
    assert cadence.precheck_script(root) == (None, "no such ref")
