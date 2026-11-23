"""A suite run releases its temporary files when it passes, and its test repos are small (TD-2098, design §4.6)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_git_template

HERE = Path(__file__).parent
PASSES = "def test_ok(tmp_path):\n    (tmp_path / 'f').write_text('x')\n"
FAILS = "def test_no(tmp_path):\n    (tmp_path / 'f').write_text('x')\n    assert False\n"


def _run(tmp_path: Path, body: str, *args: str) -> subprocess.CompletedProcess:
    """A real pytest run of `body` with this suite's conftest as a plugin, outside any worker of this run."""
    work = tmp_path / "w"
    work.mkdir(exist_ok=True)
    (work / "test_inner.py").write_text(body)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "GIT_TEMPLATE"))}
    env["PYTHONPATH"] = os.pathsep.join([str(HERE), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "conftest", "-c", os.devnull, "--rootdir", str(work), *args]
        + [str(work / "test_inner.py")],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


@pytest.mark.parametrize("xdist", [(), ("-n", "2")], ids=["alone", "xdist"])
def test_a_passing_run_leaves_no_base_temp_and_a_concurrent_runs_tree_stands(tmp_path, xdist):
    base = tmp_path / "b"
    other = tmp_path / "pytest-other"
    other.mkdir()
    (other / ".lock").write_text(str(os.getpid()))
    r = _run(tmp_path, PASSES, f"--basetemp={base}", *xdist)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not base.exists()
    assert (other / ".lock").exists()


@pytest.mark.parametrize("xdist", [(), ("-n", "2")], ids=["alone", "xdist"])
def test_a_failed_run_keeps_its_tree(tmp_path, xdist):
    base = tmp_path / "b"
    r = _run(tmp_path, FAILS, f"--basetemp={base}", *xdist)
    assert r.returncode == 1, r.stdout + r.stderr
    assert list(base.rglob("f"))


def test_a_numbered_run_is_released_and_its_current_link_with_it(tmp_path, monkeypatch):
    root = tmp_path / "t"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    r = _run(tmp_path, PASSES)
    assert r.returncode == 0, r.stdout + r.stderr
    parents = list(root.glob("pytest-of-*"))
    assert parents
    assert not [p.name for p in parents[0].iterdir() if p.name.startswith("pytest-")]


def test_a_repo_from_the_template_has_no_sample_hooks_and_keeps_what_tests_write_to(tmp_path):
    template = make_git_template(tmp_path / "base")
    repo = tmp_path / "r"
    env = {**os.environ, "GIT_TEMPLATE_DIR": str(template)}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    assert not list((repo / ".git").rglob("*.sample"))
    assert (repo / ".git" / "hooks").is_dir()
    assert (repo / ".git" / "info" / "exclude").is_file()


def test_this_runs_git_init_uses_the_small_template(tmp_path):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert not list((repo / ".git").rglob("*.sample"))
