"""The vendored ledgerboard (ADR 2026-10-12 *How ledgerboard is consumed*, design §8, TD-585, TD-1330): the
wheel's package `src/sessionorc/ledgerboard/` (the module as `__init__.py`, its board writer `board.py`) is an
intact release — the one `tests/ledgerboard/MANIFEST` names — each file byte-equal to `scripts/ledgerboard/` in
the agent-cadence tree this repo pins (dev-cadence TD-129), every vendored file is as
`scripts/vendor_ledgerboard.sh` wrote it, and the release's own fixtures pass against it."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from conftest import pinned_script

ROOT = Path(__file__).resolve().parent.parent
WHEEL = ROOT / "src" / "sessionorc" / "ledgerboard"
PACKAGE_FILES = ("__init__.py", "board.py")
FIXTURES = ROOT / "tests" / "ledgerboard"
MANIFEST = FIXTURES / "MANIFEST"


def _manifest() -> tuple[str, dict[str, str]]:
    tag, files = "", {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("tag: "):
            tag = line.removeprefix("tag: ").strip()
        elif line.startswith("file: "):
            path, digest = line.removeprefix("file: ").rsplit(" ", 1)
            files[path] = digest
    return tag, files


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FIXTURES / "run.py"), *args, "--module", str(WHEEL)],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_the_wheels_copy_is_byte_equal_to_the_pinned_one():
    """One release in the repo: an agent-cadence bump that brings a new `scripts/ledgerboard/` runs
    `vendor_ledgerboard.sh` in the same PR, or this fails — never two versions (TD-1014: a pinned repo's
    ledgerboard release is its pinned tree's)."""
    assert sorted(f.name for f in WHEEL.glob("*.py")) == sorted(PACKAGE_FILES)
    assert not (WHEEL.parent / "ledgerboard.py").exists(), "the single file goes with the package (TD-1330)"
    for name in PACKAGE_FILES:
        pinned = pinned_script(f"ledgerboard/{name}")
        got = (WHEEL / name).read_bytes() == pinned.read_bytes()
        assert got, f"{name}: run scripts/vendor_ledgerboard.sh <the pinned header's tag>"


def test_the_release_header_is_intact_and_names_the_manifests_tag():
    got = _run("--check-header")
    assert got.returncode == 0, got.stdout + got.stderr
    tag, _ = _manifest()
    for name in PACKAGE_FILES:
        assert tag and (WHEEL / name).read_text(encoding="utf-8").startswith(f"# ledgerboard {tag} sha256:")


def test_every_vendored_file_is_as_vendored():
    _, files = _manifest()
    assert {f"src/sessionorc/ledgerboard/{n}" for n in PACKAGE_FILES} <= set(files) and any(f.startswith("tests/ledgerboard/") for f in files)
    on_disk = {str(f.relative_to(ROOT)) for f in FIXTURES.rglob("*") if f.is_file() and f != MANIFEST}
    on_disk -= {f for f in on_disk if "__pycache__" in f}
    assert on_disk == {f for f in files if f.startswith("tests/ledgerboard/")}, "a fixture the MANIFEST does not list"
    drift = [f for f, h in files.items() if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h]
    assert not drift, f"edited since vendored (scripts/vendor_ledgerboard.sh owns them): {drift}"


def test_the_releases_fixtures_pass_against_the_wheels_copy():
    got = _run()
    assert got.returncode == 0, got.stdout + got.stderr


def test_the_wheels_copy_imports_as_sessionorc_ledgerboard():
    from sessionorc import ledgerboard

    from sessionorc.ledgerboard import board

    assert Path(ledgerboard.__file__).resolve() == WHEEL / "__init__.py"
    assert Path(board.__file__).resolve() == WHEEL / "board.py"
