"""The disk sweep's branch rule (design §4.6 *The disk sweep*, *branches*, TD-2112): on real repos with a stubbed `gh`,
a landed branch is deleted and logged with its commit, every other is kept with its why, and a run paces itself."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sessionorc import branchsweep, diskbook, gitinfo
from sessionorc.ledgerboard import COUNTER_BRANCH
from shiftlead.cli import disk_lines

DAY = 86400


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, name, msg="c") -> str:
    (Path(cwd) / name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> Path:
    seed, origin, r = tmp_path / "seed", tmp_path / "origin.git", tmp_path / "r"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    git(seed, "config", "user.email", "t@t")
    git(seed, "config", "user.name", "t")
    commit(seed, "one")
    git(seed, "push", "-q", str(origin), "main")
    git(tmp_path, "clone", "-q", str(origin), str(r))
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    return r


@pytest.fixture
def forge(tmp_path, monkeypatch) -> dict:
    """A stub `gh`: `forge[branch]` is its PR list, `forge["fail"]` makes it exit 1, each ask is logged."""
    bin_dir, data, asked = tmp_path / "bin", tmp_path / "forge.json", tmp_path / "asked"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        f"d = json.load(open({str(data)!r}))\nb = sys.argv[sys.argv.index('--head') + 1]\n"
        f"open({str(asked)!r}, 'a').write(b + '\\n')\n"
        "sys.exit(1) if d.get('fail') else print(json.dumps(d.get(b, [])))\n"
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    class Forge(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            data.write_text(json.dumps(self))

        def asked(self) -> list[str]:
            return asked.read_text().split() if asked.exists() else []

    f = Forge()
    data.write_text("{}")
    return f


def branch(repo, name, *files, base="origin/main") -> str:
    git(repo, "checkout", "-q", "--no-track", "-b", name, base)
    tip = git(repo, "rev-parse", "HEAD")
    for f in files:
        tip = commit(repo, f)
    git(repo, "checkout", "-q", "main")
    return tip


def land_squash(repo, name) -> str:
    """Squash `name` onto origin/main, as a PR's merge does; the merge commit's id."""
    git(repo, "merge", "-q", "--squash", name)
    git(repo, "commit", "-q", "-m", f"squash {name}")
    git(repo, "push", "-q", "origin", "main")
    return git(repo, "rev-parse", "HEAD")


def pr(n, head, merge, base="main") -> dict:
    return {"number": n, "headRefOid": head, "baseRefName": base, "mergeCommit": {"oid": merge}}


def run(repo, **kw) -> branchsweep.Pass:
    kw.setdefault("cursor", None)
    kw.setdefault("keep_days", 7)
    kw.setdefault("now", time.time() + 10 * DAY)  # every reflog entry reads as past the age
    kw.setdefault("hold", lambda main, name, path: lambda: None)
    return branchsweep.sweep([repo], **kw)


def kept(got) -> dict[str, str]:
    return {b: why for _r, b, why in got.kept}


def exists(repo, name) -> bool:
    return gitinfo._git_rc(repo, "show-ref", "--verify", "-q", f"refs/heads/{name}", timeout=5) == 0


def test_a_branch_on_the_default_and_a_merged_prs_head_are_deleted_and_logged(repo, forge, caplog):
    on = branch(repo, "on")
    head = branch(repo, "merged", "m")
    forge["merged"] = [pr(7, head, land_squash(repo, "merged"))]
    with caplog.at_level(logging.INFO, logger="sessionorc.branchsweep"):
        got = run(repo)
    assert {(b, c, p) for _r, b, c, p in got.deleted} == {("on", on, "on main"), ("merged", head, "PR #7")}
    assert not exists(repo, "on") and not exists(repo, "merged")
    assert head in caplog.text and "PR #7" in caplog.text and on in caplog.text


def test_a_landed_branch_whose_reflog_git_expired_is_deleted_where_logging_is_on(repo, forge):
    branch(repo, "old")
    git(repo, "reflog", "expire", "--expire=all", "refs/heads/old")
    assert [d[1] for d in run(repo).deleted] == ["old"]


def test_each_branch_that_has_not_landed_is_kept_with_its_why(repo, forge):
    branch(repo, "unlanded", "u")
    other = branch(repo, "other-base", "o")
    forge["other-base"] = [pr(8, other, git(repo, "rev-parse", "origin/main"), base="release")]
    pushed = branch(repo, "pushed", "p")
    git(repo, "push", "-q", "-u", "origin", "pushed")
    git(repo, "branch", "--no-track", "own-head", "origin/main")
    git(repo, "push", "-q", "-u", "origin", "own-head")
    git(repo, "branch", "local-up", "--track", "pushed")
    got = run(repo)
    assert kept(got) == {
        "unlanded": "not landed: 1 commit",
        "other-base": "not landed: 1 commit",
        "pushed": "tracks origin/pushed",
        "own-head": "tracks origin/own-head",
        "local-up": "tracks pushed",
    }
    assert not got.deleted and exists(repo, "pushed") and pushed


def test_a_squash_merged_head_with_a_commit_only_in_its_reflog_is_kept(repo, forge):
    git(repo, "checkout", "-q", "--no-track", "-b", "amended", "origin/main")
    commit(repo, "a")
    (repo / "a").write_text("changed")
    git(repo, "commit", "-q", "-a", "--amend", "-m", "amended")
    tip = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    forge["amended"] = [pr(9, tip, land_squash(repo, "amended"))]
    assert kept(run(repo)) == {"amended": "1 commit only in its reflog"}


def test_a_branch_checked_out_or_moved_within_the_age_is_kept(repo, forge):
    git(repo, "branch", "--no-track", "held", "origin/main")
    wt = repo.parent / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "held")
    git(repo, "branch", "--no-track", "young", "origin/main")
    got = run(repo, now=time.time())
    assert kept(got) == {"held": f"checked out in {wt.resolve()}", "young": "moved within 7 days"}


def test_logging_off_keeps_a_branch_with_no_reflog_and_a_failed_read_keeps_it(repo, forge, monkeypatch):
    branch(repo, "old")
    git(repo, "reflog", "expire", "--expire=all", "refs/heads/old")
    git(repo, "config", "core.logAllRefUpdates", "false")
    assert kept(run(repo)) == {"old": "no reflog"}
    git(repo, "config", "--unset", "core.logAllRefUpdates")
    monkeypatch.setattr(branchsweep, "_call", lambda *a, **k: None)
    assert kept(run(repo)) == {"old": gitinfo.NOT_WEIGHED}


def test_a_bare_repo_with_the_setting_unset_keeps_it_read_from_a_linked_worktree_too(repo, forge, tmp_path):
    bare = tmp_path / "b.git"
    git(tmp_path, "clone", "-q", "--bare", str(tmp_path / "origin.git"), str(bare))
    git(bare, "update-ref", "refs/remotes/origin/main", git(bare, "rev-parse", "main"))
    git(bare, "branch", "old", "main")
    linked = tmp_path / "linked"
    git(bare, "worktree", "add", "-q", "-b", "lw", str(linked), "main")
    assert kept(run(bare))["old"] == "no reflog"
    assert kept(run(linked))["old"] == "no reflog"


def test_a_busy_create_lock_or_a_tip_that_moves_before_the_delete_keeps_it(repo, forge):
    branch(repo, "busy")
    assert kept(run(repo, hold=lambda main, name, path: None)) == {"busy": "busy: a start is using it"}

    def move(main, name, path):
        git(repo, "update-ref", f"refs/heads/{name}", git(repo, "commit-tree", "HEAD^{tree}", "-m", "moved"))
        return lambda: None

    assert kept(run(repo, hold=move)) == {"busy": "moved"} and exists(repo, "busy")


def test_the_default_and_the_counter_branch_are_never_weighed(repo, forge):
    git(repo, "branch", "--no-track", COUNTER_BRANCH, "origin/main")
    got = run(repo)
    assert not got.deleted and not got.kept and exists(repo, COUNTER_BRANCH)


def test_with_gh_failing_only_the_first_proof_deletes_and_it_is_asked_once(repo, forge):
    branch(repo, "on")
    branch(repo, "u1", "x")
    branch(repo, "u2", "y")
    forge["fail"] = True
    got = run(repo)
    assert [d[1] for d in got.deleted] == ["on"]
    assert kept(got) == {"u1": "no forge answer", "u2": "no forge answer"}
    assert forge.asked() == ["u1"]


def test_a_name_with_a_slash_takes_no_create_lock(repo, forge):
    branch(repo, "feat/x")
    asked = []
    got = run(repo, hold=lambda main, name, path: asked.append(name))
    assert [d[1] for d in got.deleted] == ["feat/x"] and asked == []


def test_a_repo_with_no_origin_default_keeps_every_branch(tmp_path, forge):
    r = tmp_path / "plain"
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    commit(r, "a")
    git(r, "branch", "x")
    assert kept(run(r)) == {"x": gitinfo.NOT_WEIGHED}


def test_a_run_stopped_by_its_budget_carries_on_after_its_cursor_and_clears_it(repo, forge, monkeypatch):
    for n in ("a", "b", "c"):
        branch(repo, n, f"{n}.txt")
    ticks = iter([0.0, 0.0, 0.0, 99.0])
    real = time.monotonic
    monkeypatch.setattr(branchsweep.time, "monotonic", lambda: next(ticks, real()))
    first = run(repo, budget=10)
    monkeypatch.setattr(branchsweep.time, "monotonic", real)
    assert first.stopped and first.cursor == (str(repo), "b") and list(kept(first)) == ["a", "b"]
    second = run(repo, cursor=first.cursor)
    assert not second.stopped and second.cursor is None and list(kept(second)) == ["c"]


def test_two_roots_of_one_clone_weigh_its_branches_once(repo, forge):
    branch(repo, "on")
    linked = repo.parent / "linked"
    git(repo, "worktree", "add", "-q", "--detach", str(linked), "origin/main")
    got = branchsweep.sweep(
        [repo, linked], cursor=None, keep_days=7, now=time.time() + 10 * DAY, hold=lambda m, n, p: lambda: None
    )
    assert [d[1] for d in got.deleted] == ["on"] and not got.kept


def test_a_dry_run_deletes_nothing_takes_no_lock_and_says_what_it_would(repo, forge):
    branch(repo, "on")
    got = run(repo, dry=True, hold=None)
    assert [(d[1], d[3]) for d in got.deleted] == [("on", "on main")] and exists(repo, "on")


def test_the_reading_counts_deletes_and_caps_the_kept_rows(tmp_path):
    now = datetime(2026, 11, 23, tzinfo=UTC)
    kept_map = {("/r", f"b{i:03}"): "why" for i in range(203)}
    rows = diskbook.branch_rows(2, kept_map)
    assert len(rows["kept"]) == 200 and rows["kept_more"] == 3
    diskbook.write(tmp_path, "h", {}, {}, "s", now, branches=rows)
    diskbook.write(tmp_path, "h", {}, {}, "s", now, branches=diskbook.branch_rows(1, {("/r", "x"): "kept"}))
    got = diskbook.read(tmp_path, "h", "s", now, {})["branches"]
    assert (got["deleted"], got["deleted_30d"], got["kept_more"]) == (1, 3, 0)
    assert diskbook.branch_kept(tmp_path) == {("/r", "x"): "kept"}
    lines = disk_lines({"h": diskbook.read(tmp_path, "h", "s", now, {})})
    assert "  branches   deleted 1 last pass, 3 in 30 days" in lines and "    kept /r x — kept" in lines


def test_the_prose_names_the_rows_past_the_cap_and_a_dry_runs_lists():
    entry = {"at": "t", "kinds": {}, "branches": {"deleted": 0, "deleted_30d": 0, "kept": [], "kept_more": 3}}
    assert "    and 3 more kept" in disk_lines({"h": entry})
    dry = {
        "dry_run": True,
        "kinds": {},
        "branches": {
            "would_delete": [{"repo": "/r", "branch": "x", "proof": "PR #1"}],
            "kept": [{"repo": "/r", "branch": "y", "why": "moved"}],
            "partial": True,
        },
    }
    lines = disk_lines({"h": dry})
    assert "  branches   would delete 1 (partial)" in lines
    assert "    would delete /r x — PR #1" in lines and "    kept /r y — moved" in lines


@pytest.mark.integration
async def test_the_agent_runs_the_rule_once_a_day_and_holds_the_rows(agent, repo, forge):
    from conftest import park_ticks

    await park_ticks(agent)
    agent._worktree_scope = True
    agent._sweep_roots = [str(repo)]
    branch(repo, "unlanded", "u")
    git(repo, "branch", "--no-track", "young", "origin/main")
    out: dict = {"deleted": 0}
    agent._branch_kept = {("/gone", "x"): "old row"}
    agent._sweep_branches(datetime.now(UTC), out)
    assert set(agent._branch_kept) == {(str(repo), "unlanded"), (str(repo), "young")}
    assert agent._branch_cursor is None and agent._branch_ended is not None
    git(repo, "branch", "-D", "young")
    agent._sweep_branches(datetime.now(UTC), out)  # within the day: nothing weighed, the row stands
    assert (str(repo), "young") in agent._branch_kept
    dry: dict = {"would_delete": [], "kept": [], "partial": False}
    before = dict(agent._branch_kept)
    agent._branch_cursor, ended = (str(repo), "a"), agent._branch_ended
    agent._sweep_branches(datetime.now(UTC), dry, dry=True)
    assert [k["branch"] for k in dry["kept"]] == ["unlanded"] and agent._branch_kept == before
    assert agent._branch_cursor == (str(repo), "a") and agent._branch_ended == ended
