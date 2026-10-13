"""The vendored ledgerboard (ADR 2026-10-12 *How ledgerboard is consumed*, design §8, TD-585): the
wheel's `src/sessionorc/ledgerboard.py` is an intact release — the one `tests/ledgerboard/MANIFEST`
names — byte-equal to the synced `scripts/ledgerboard.py` where both exist, every vendored file is as
`scripts/vendor_ledgerboard.sh` wrote it, and the release's own fixtures pass against it."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WHEEL = ROOT / "src" / "sessionorc" / "ledgerboard.py"
SYNCED = ROOT / "scripts" / "ledgerboard.py"
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


def test_the_wheels_copy_is_byte_equal_to_the_synced_one():
    """One release in the repo: a sync that brings a new `scripts/ledgerboard.py` runs
    `vendor_ledgerboard.sh` in the same PR, or this fails — never two versions."""
    if not SYNCED.is_file():
        pytest.skip("no synced scripts/ledgerboard.py (a repo without dev-cadence has the wheel's alone)")
    assert WHEEL.read_bytes() == SYNCED.read_bytes(), "run scripts/vendor_ledgerboard.sh <the synced header's tag>"


def test_the_release_header_is_intact_and_names_the_manifests_tag():
    got = _run("--check-header")
    assert got.returncode == 0, got.stdout + got.stderr
    tag, _ = _manifest()
    assert tag and WHEEL.read_text(encoding="utf-8").startswith(f"# ledgerboard {tag} sha256:")


def test_every_vendored_file_is_as_vendored():
    _, files = _manifest()
    assert "src/sessionorc/ledgerboard.py" in files and any(f.startswith("tests/ledgerboard/") for f in files)
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

    assert Path(ledgerboard.__file__).resolve() == WHEEL
