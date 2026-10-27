"""A close's reap of the worktree it made (design §4.1 *A close reaps the worktree it made*, TD-979): the
worktree's tests, the remove and the branches, on a scratch repo with a bare origin."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import time
from pathlib import Path

import pytest
from conftest import pinned_script

from sessionorc import gitinfo
from sessionorc.gitinfo import ensure_worktree, reap_worktree, weigh_branches


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def ok(cwd, *args) -> bool:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True).returncode == 0


def commit(cwd, name="f", text="x", msg="c") -> str:
    (Path(cwd) / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> Path:
    """A main checkout cloned from a bare origin with one commit on `main` and `origin/HEAD` set."""
    seed, origin, r = tmp_path / "seed", tmp_path / "origin.git", tmp_path / "r"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    for cwd in (seed,):
        git(cwd, "config", "user.email", "t@t")
        git(cwd, "config", "user.name", "t")
    ignored = ("__pycache__/", ".pytest_cache/", ".ruff_cache/", ".venv/", "*.egg-info/", "scratch/", ".claude/")
    (seed / ".gitignore").write_text("".join(f"{x}\n" for x in ignored))
    git(seed, "add", ".gitignore")
    commit(seed, msg="one")
    git(seed, "push", "-q", str(origin), "main")
    git(tmp_path, "clone", "-q", str(origin), str(r))
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    return r


def branches(r) -> set[str]:
    return set(git(r, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())


def reap(wt, launch, **kw):
    return reap_worktree(wt, launch, **kw)


# -- reaped ---------------------------------------------------------------------------------------------


def test_a_clean_worktree_with_its_branch_pushed_goes_with_its_branch_and_origin_is_untouched(repo, tmp_path):
    wt, _ = ensure_worktree(repo, "ao-w")
    commit(wt, "g", msg="work")
    git(wt, "push", "-q", "-u", "origin", "ao-w")
    before = git(tmp_path / "origin.git", "for-each-ref")
    got = reap(wt, "ao-w")
    assert got == {"reaped": True, "branches_deleted": ["ao-w"], "branch_kept": {}}
    assert not wt.exists() and "ao-w" not in branches(repo)
    assert git(tmp_path / "origin.git", "for-each-ref") == before


def test_an_unpushed_commit_keeps_the_branch_never_the_worktree(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    commit(wt, "g", msg="pushed")
    git(wt, "push", "-q", "-u", "origin", "ao-w")
    commit(wt, "h", msg="after the last push")
    got = reap(wt, "ao-w")
    assert got["reaped"] and not wt.exists()
    assert got["branch_kept"] == {"ao-w": "1 commit never on origin"} and "ao-w" in branches(repo)


def test_a_detached_head_weighs_only_the_launch_branch(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    git(repo, "branch", "other", "origin/main")
    commit(repo, "local", msg="a local commit on main, so the next branch is ahead")
    git(repo, "branch", "other-ahead")
    git(wt, "checkout", "-q", "--detach")
    got = reap(wt, "ao-w")
    assert got == {"reaped": True, "branches_deleted": ["ao-w"], "branch_kept": {}}
    assert {"other", "other-ahead", "main"} <= branches(repo)


def test_a_worktree_that_ran_pytest_and_ruff_is_reaped_its_caches_being_disposable(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    for d in ("__pycache__", ".pytest_cache/v", ".ruff_cache/0.1", "pkg/__pycache__", "src/x.egg-info", ".venv/lib"):
        (wt / d).mkdir(parents=True)
        (wt / d / "blob").write_text("derived")
    assert reap(wt, "ao-w")["reaped"] and not wt.exists()


# -- kept -----------------------------------------------------------------------------------------------


def test_a_dirty_tree_is_kept_and_said(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    (wt / "f").write_text("changed")
    (wt / "new.txt").write_text("u")
    assert reap(wt, "ao-w") == {"kept": "2 uncommitted"}
    assert wt.is_dir() and "ao-w" in branches(repo)


def test_an_ignored_scratch_file_keeps_the_worktree(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    (wt / "scratch").mkdir()
    (wt / "scratch" / "notes.txt").write_text("mine")
    (wt / "scratch" / "more.txt").write_text("mine")
    assert reap(wt, "ao-w") == {"kept": "ignored: scratch/more.txt and 1 more"}
    assert wt.is_dir()


def test_a_symlink_is_no_blocker_and_a_nested_clone_always_is(repo, tmp_path):
    wt, _ = ensure_worktree(repo, "ao-w")
    (wt / ".claude").mkdir()
    (wt / ".claude" / "link").symlink_to(tmp_path)  # ignored, as hydrate's links are
    git(tmp_path, "init", "-q", str(tmp_path / "linked"))
    (wt / ".claude" / "repo-link").symlink_to(tmp_path / "linked")  # a link to a repo is still a link
    nested = wt / ".venv" / "clone"  # under a disposable directory, and still a blocker
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(nested))
    assert reap(wt, "ao-w") == {"kept": "ignored: .venv/clone/"}
    subprocess.run(["rm", "-rf", str(nested)], check=True)
    assert reap(wt, "ao-w")["reaped"] and tmp_path.is_dir()


def test_a_locked_worktree_is_kept_before_anything_is_touched(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    git(repo, "worktree", "lock", str(wt))
    stamped = []
    assert reap(wt, "ao-w", on_reaping=stamped.append) == {"kept": "locked"}
    assert stamped == [] and wt.is_dir()


def test_the_callers_idle_test_keeps_the_worktree_with_its_why(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    assert reap(wt, "ao-w", idle=lambda: "in use by ao-repo-shell") == {"kept": "in use by ao-repo-shell"}
    assert reap(wt, "ao-w", idle=lambda: None)["reaped"]


def test_no_step_starts_past_the_deadline(repo, monkeypatch):
    wt, _ = ensure_worktree(repo, "ao-w")
    calls = []
    real = gitinfo._run
    monkeypatch.setattr(
        gitinfo, "_run", lambda argv, timeout, cwd=None, env=None: calls.append(argv) or real(argv, timeout, cwd, env)
    )
    assert reap(wt, "ao-w", deadline=time.monotonic() - 1) == {"kept": "timed out"}
    assert wt.is_dir() and calls == []
    # the tests pass inside the deadline, and it runs out before the remove: nothing removed, nothing stamped
    now = [0.0]
    monkeypatch.setattr(gitinfo.time, "monotonic", lambda: now[0])

    def holds_then_late(*a, **kw):
        now[0] = 60.5
        return None

    monkeypatch.setattr(gitinfo, "worktree_holds", holds_then_late)
    stamped = []
    assert reap(wt, "ao-w", deadline=60.0, on_reaping=stamped.append) == {"kept": "timed out"}
    assert wt.is_dir() and stamped == []


def _hydrate(repo, body: str) -> None:
    """A stand-in `scripts/hydrate_worktree.sh` in the main checkout, logging each call."""
    script = repo / "scripts" / "hydrate_worktree.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text(f'#!/bin/sh\necho "$@" >> "{repo}/hydrate.log"\n{body}\n')
    script.chmod(0o755)


def _calls(repo) -> list[str]:
    p = repo / "hydrate.log"
    return p.read_text().splitlines() if p.exists() else []


def test_a_settings_file_the_hydrate_script_will_not_call_disposable_keeps_the_worktree(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    (wt / ".claude").mkdir()
    (wt / ".claude" / "settings.local.json").write_text('{"permissions": {"allow": ["Bash(new)"]}}')
    _hydrate(repo, 'case "$1" in --settings-disposable) exit 1;; esac; exit 0')
    assert reap(wt, "ao-w") == {"kept": "ignored: .claude/settings.local.json"}
    _hydrate(repo, "exit 0")
    got = reap(wt, "ao-w")
    assert got["reaped"] and any(c.startswith("--dehydrate") for c in _calls(repo))


def test_nested_work_the_hydrate_check_refuses_keeps_the_worktree_and_a_failed_remove_hydrates_again(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    _hydrate(repo, 'case "$1" in --check) exit 1;; esac; exit 0')
    assert reap(wt, "ao-w") == {"kept": "nested work unsaved"}
    assert not any(c.startswith("--dehydrate") for c in _calls(repo))
    # the dehydrate passes, then the tree changes under it: git's own refusal, and the tree hydrated again
    _hydrate(repo, f'case "$1" in --dehydrate) echo late > "{wt}/late.txt";; esac; exit 0')
    stamped = []
    got = reap(wt, "ao-w", on_reaping=stamped.append)
    assert "contains modified or untracked files" in got["kept"] and wt.is_dir() and stamped == ["ao-w"]
    assert _calls(repo)[-2:] == [f"--dehydrate --quiet {wt}", f"--quiet {wt}"]


def test_a_pinned_repos_reap_runs_the_pinned_trees_hydrate(repo, monkeypatch):
    """TD-1044: in a pinned repo (no `scripts/hydrate_worktree.sh`), the reaper's `--check` and `--dehydrate`
    are the pinned tree's, through the resolver."""
    from sessionorc import cadence

    wt, _ = ensure_worktree(repo, "ao-w")
    (repo / "docs").mkdir()
    (repo / "docs" / "cadence.toml").write_text(f'[dev-cadence]\nsource = "/nowhere"\nref = "{"a" * 40}"\n')
    stub = repo.parent / "launcher.sh"
    stub.write_text(f'#!/bin/sh\nshift 2\necho "$@" >> "{repo}/hydrate.log"\n')
    stub.chmod(0o755)
    monkeypatch.setattr(cadence, "command", lambda r, word, *a: ([str(stub), word, *a], dict(os.environ)))
    assert reap(wt, "ao-w")["reaped"] and not wt.exists()
    assert _calls(repo) == [f"--check --quiet {wt}", f"--dehydrate --quiet {wt}"]


# -- the branches ---------------------------------------------------------------------------------------


def _wt_pushed(repo, name="ao-w"):
    wt, _ = ensure_worktree(repo, name)
    commit(wt, "g", msg="work")
    git(wt, "push", "-q", "-u", "origin", name)
    return wt


def _rebase_elsewhere(repo, tmp_path, name, conflict=False):
    """Another session rebases `name` on a moved main and force-pushes it, from a clone of its own."""
    other = tmp_path / f"other-{name}"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    git(other, "config", "user.email", "o@o")
    git(other, "config", "user.name", "o")
    commit(other, "g" if conflict else f"m-{name}", text="main's", msg="main moves")
    git(other, "push", "-q", "origin", "main")
    git(other, "checkout", "-q", name)
    if conflict:
        subprocess.run(["git", "-C", str(other), "rebase", "-q", "origin/main"], capture_output=True)
        (other / "g").write_text("resolved")
        git(other, "add", "g")
        subprocess.run(["git", "-C", str(other), "-c", "core.editor=true", "rebase", "--continue"], capture_output=True)
    else:
        git(other, "rebase", "-q", "origin/main")
    git(other, "push", "-q", "-f", "origin", name)
    git(repo, "fetch", "-q", "origin")


@pytest.mark.parametrize("conflict", [False, True])
def test_a_branch_another_session_rebased_before_the_close_is_deleted_and_the_gate_reads_na(repo, tmp_path, conflict):
    wt = _wt_pushed(repo)
    _rebase_elsewhere(repo, tmp_path, "ao-w", conflict)
    assert int(git(repo, "rev-list", "--count", "origin/ao-w..ao-w")) == 1  # the stale tip the gate failed on
    got = reap(wt, "ao-w")
    assert got["branches_deleted"] == ["ao-w"] and got["branch_kept"] == {}
    spec = importlib.util.spec_from_file_location("check_cadence", pinned_script("check_cadence.py"))
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    row = cc.row_pushed({"state": "open", "head": "ao-w"}, str(repo))
    assert "na" in str(row) and "not a local branch" in str(row)


def test_a_launch_branch_never_pushed_with_no_commit_of_its_own_is_deleted(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    assert not ok(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/ao-w")
    assert reap(wt, "ao-w")["branches_deleted"] == ["ao-w"]


def test_a_launch_branch_whose_commits_went_out_on_a_topic_branch_is_deleted_with_it(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    commit(wt, "g", msg="work")
    git(wt, "checkout", "-q", "-b", "td1-topic")
    commit(wt, "h", msg="more")
    git(wt, "push", "-q", "-u", "origin", "td1-topic")
    got = reap(wt, "ao-w")
    assert sorted(got["branches_deleted"]) == ["ao-w", "td1-topic"] and got["branch_kept"] == {}


def test_a_branch_merged_with_a_merge_commit_is_deleted(repo, tmp_path):
    wt, _ = ensure_worktree(repo, "ao-w")
    commit(wt, "g", msg="work")  # never pushed under its own name
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "ao-w")
    git(repo, "push", "-q", "origin", "main")
    assert reap(wt, "ao-w")["branches_deleted"] == ["ao-w"]


def test_a_branch_never_pushed_with_a_commit_of_its_own_is_kept_and_counted(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    commit(wt, "g", msg="one")
    commit(wt, "h", msg="two")
    assert reap(wt, "ao-w")["branch_kept"] == {"ao-w": "2 commits never on origin"}


def test_a_launch_branch_tracking_origin_heads_branch_is_weighed_against_origin_not_its_upstream(repo):
    git(repo, "branch", "--track", "ao-w", "origin/main")  # as `worktree add -b` from origin/HEAD leaves it
    wt, _ = ensure_worktree(repo, "ao-w")
    assert git(wt, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/main"
    commit(wt, "g", msg="own")
    assert reap(wt, "ao-w")["branch_kept"] == {"ao-w": "1 commit never on origin"}


def test_a_pruned_remote_ref_or_no_reflog_keeps_a_branch_with_a_commit_of_its_own(repo, tmp_path):
    wt = _wt_pushed(repo)
    _rebase_elsewhere(repo, tmp_path, "ao-w")
    git(repo, "update-ref", "-d", "refs/remotes/origin/ao-w")  # as a `fetch --prune` of a deleted branch: reflog gone
    assert reap(wt, "ao-w")["branch_kept"] == {"ao-w": "1 commit never on origin"}
    git(repo, "config", "core.logAllRefUpdates", "false")
    wt2, _ = ensure_worktree(repo, "ao-v")
    commit(wt2, "v", msg="v1")
    git(wt2, "push", "-q", "-u", "origin", "ao-v")
    _rebase_elsewhere(repo, tmp_path, "ao-v")
    assert not ok(repo, "reflog", "exists", "refs/remotes/origin/ao-v")
    assert reap(wt2, "ao-v")["branch_kept"] == {"ao-v": "1 commit never on origin"}


def test_a_branch_checked_out_in_another_worktree_is_kept_by_gits_own_refusal(repo):
    other, _ = ensure_worktree(repo, "ao-v")
    git(other, "checkout", "-q", "-b", "shared")  # held by origin/main, so only git's refusal keeps it
    git(repo, "branch", "spare", "origin/main")
    deleted, kept = weigh_branches(repo, ["shared", "spare"])
    assert deleted == ["spare"] and kept == {"shared": f"checked out in {other}"}


def test_the_default_branch_and_a_branch_deleted_by_hand_are_skipped_named_in_neither(repo):
    wt, _ = ensure_worktree(repo, "ao-w")
    git(repo, "checkout", "-q", "--detach")
    git(wt, "checkout", "-q", "main")  # the default branch checked out in the worktree
    git(repo, "branch", "-D", "ao-w")  # the launch branch deleted by hand
    got = reap(wt, "ao-w")
    assert got == {"reaped": True, "branches_deleted": [], "branch_kept": {}} and "main" in branches(repo)


def test_no_origin_and_no_origin_head_keep_every_branch_and_say_why(repo):
    git(repo, "branch", "spare", "origin/main")
    git(repo, "remote", "set-head", "origin", "-d")
    assert weigh_branches(repo, ["spare"]) == ([], {"spare": "no origin/HEAD"})
    git(repo, "remote", "set-head", "origin", "-a")
    assert weigh_branches(repo, ["spare"]) == (["spare"], {})
    git(repo, "branch", "spare", "origin/main")
    git(repo, "remote", "remove", "origin")
    assert weigh_branches(repo, ["spare"]) == ([], {"spare": "no origin"})


def test_a_failing_git_read_keeps_the_branch_as_could_not_be_weighed(repo, monkeypatch):
    git(repo, "branch", "spare", "origin/main")
    real = gitinfo._run

    def failing(argv, timeout, cwd=None, env=None):
        return None if "rev-list" in argv else real(argv, timeout, cwd, env)

    monkeypatch.setattr(gitinfo, "_run", failing)
    assert weigh_branches(repo, ["spare"]) == ([], {"spare": "could not be weighed"})
    assert "spare" in branches(repo)


def test_the_disposable_list_is_the_designs(repo):
    assert set(gitinfo.DISPOSABLE_IGNORED) == {
        "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".pdm-build", ".pdm-python", "*.egg-info",
        ".venv",
    }  # fmt: skip
    assert (gitinfo.REAP_WITHIN, gitinfo.REAP_STEP) == (60.0, 20.0)
    assert os.access(pinned_script("check_cadence.py"), os.R_OK)  # the gate the test above loads
