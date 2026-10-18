"""The Git card's pick (design §4.2 *The Git card's pick*, §4.5a *Focus side panel, Git card: the pick*,
TD-856): the `git_files` read — the newest ten commits on `HEAD`'s first-parent line, and the files of the
pick (Working tree, one of the ten, or Session) with their codes and `gone` — served on the record's host,
ungated, refusing a sha outside the ten and an unknown pick in words."""

from __future__ import annotations

import os
import subprocess

import pytest

from sessionorc import identity
from sessionorc.agent_common import NODE_READS
from sessionorc.client import AgentError, LocalClient
from sessionorc.gitinfo import GIT_PICK_SESSION, GIT_PICK_TREE, GitPickError, pick_files


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def commit(repo, message, when=1_700_000_000):
    env = {**os.environ, "GIT_COMMITTER_DATE": f"@{when} +0000", "GIT_AUTHOR_DATE": f"@{when} +0000"}
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True, env=env)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


def cloned(tmp_path):
    """A clone of a bare origin whose `main` holds `base.txt`, `old.txt` and `ren.txt` in one root commit,
    on a branch `work` cut from it."""
    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    repo = tmp_path / "r"
    run("git", "clone", "-q", str(origin), str(repo), cwd=tmp_path)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "Tess", cwd=repo)
    run("git", "checkout", "-q", "-b", "main", cwd=repo)
    (repo / "base.txt").write_text("b")
    (repo / "old.txt").write_text("o")
    (repo / "ren.txt").write_text("a line long enough that git calls the move a rename\n" * 4)
    run("git", "add", ".", cwd=repo)
    commit(repo, "base", 1_600_000_000)
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    run("git", "checkout", "-q", "-b", "work", cwd=repo)
    return repo


def test_commits_name_head_first_and_stop_at_ten(tmp_path):
    repo = cloned(tmp_path)
    for i in range(12):
        (repo / "n.txt").write_text(str(i))
        run("git", "add", ".", cwd=repo)
        commit(repo, f"c{i}", 1_700_000_000 + i)
    got = pick_files(repo, "origin/main", "tree")
    assert [c["ref"] for c in got["commits"]] == ["HEAD"] + [f"HEAD~{i}" for i in range(1, 10)]
    head = got["commits"][0]
    assert head["subject"] == "c11" and head["author"] == "Tess" and head["at"] == "2023-11-14T22:13:31Z"
    assert len(head["sha"]) == 40 and got["files"] == []


def test_a_commits_files_are_its_own_and_a_root_commits_are_against_the_empty_tree(tmp_path):
    repo = cloned(tmp_path)
    (repo / "new.txt").write_text("n")
    (repo / "base.txt").write_text("changed")
    run("git", "rm", "-q", "old.txt", cwd=repo)
    run("git", "mv", "ren.txt", "moved.txt", cwd=repo)
    run("git", "add", ".", cwd=repo)
    sha = commit(repo, "four kinds")
    (repo / "later.txt").write_text("l")
    run("git", "add", ".", cwd=repo)
    commit(repo, "later")
    got = pick_files(repo, "origin/main", sha)
    assert [c["sha"] for c in got["commits"]].index(sha) == 1  # HEAD~1
    assert sorted((f["code"], f["path"]) for f in got["files"]) == [
        ("A", "new.txt"),
        ("D", "old.txt"),
        ("M", "base.txt"),
        ("R", "moved.txt"),
    ]
    assert [f["path"] for f in got["files"] if f.get("gone")] == ["old.txt"]
    root = got["commits"][-1]["sha"]
    assert got["commits"][-1]["subject"] == "base"
    assert sorted((f["code"], f["path"]) for f in pick_files(repo, None, root)["files"]) == [
        ("A", "base.txt"),
        ("A", "old.txt"),
        ("A", "ren.txt"),
    ]


def test_the_commits_are_the_first_parent_line_without_a_merged_branchs_own(tmp_path):
    repo = cloned(tmp_path)
    run("git", "checkout", "-q", "-b", "side", cwd=repo)
    (repo / "side.txt").write_text("s")
    run("git", "add", ".", cwd=repo)
    side = commit(repo, "on the side", 1_700_000_100)
    run("git", "checkout", "-q", "work", cwd=repo)
    (repo / "w.txt").write_text("w")
    run("git", "add", ".", cwd=repo)
    commit(repo, "on work", 1_700_000_200)
    env = {**os.environ, "GIT_COMMITTER_DATE": "@1700000300 +0000", "GIT_AUTHOR_DATE": "@1700000300 +0000"}
    subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "merge side", "side"], cwd=repo, check=True, env=env)
    got = pick_files(repo, "origin/main", "tree")
    assert [c["subject"] for c in got["commits"]] == ["merge side", "on work", "base"]
    assert side not in [c["sha"] for c in got["commits"]]


def test_a_path_deleted_after_the_commit_is_gone(tmp_path):
    repo = cloned(tmp_path)
    (repo / "x.txt").write_text("x")
    run("git", "add", ".", cwd=repo)
    sha = commit(repo, "x")
    (repo / "x.txt").unlink()
    assert pick_files(repo, "origin/main", sha)["files"] == [{"code": "A", "path": "x.txt", "gone": True}]


def test_session_carries_the_porcelains_code_for_a_dirty_path_and_the_bases_letter_otherwise(tmp_path):
    repo = cloned(tmp_path)
    (repo / "committed.txt").write_text("c")
    run("git", "rm", "-q", "old.txt", cwd=repo)
    run("git", "add", ".", cwd=repo)
    commit(repo, "one")
    (repo / "base.txt").write_text("dirty")
    (repo / "fresh.txt").write_text("untracked")
    got = pick_files(repo, "origin/main", "session")
    codes = {f["path"]: f["code"] for f in got["files"]}
    assert codes == {"base.txt": "M", "fresh.txt": "??", "committed.txt": "A", "old.txt": "D"}
    assert [f["path"] for f in got["files"] if f.get("gone")] == ["old.txt"] and got["more"] == 0
    tree = pick_files(repo, "origin/main", "tree")["files"]
    assert {(f["code"], f["path"]) for f in tree} == {("M", "base.txt"), ("??", "fresh.txt")}


def test_a_path_git_would_quote_comes_whole(tmp_path):
    repo = cloned(tmp_path)
    (repo / "naïve file.txt").write_text("n")
    for pick in ("tree", "session"):
        assert pick_files(repo, "origin/main", pick)["files"] == [{"code": "??", "path": "naïve file.txt"}]


def test_a_staged_rename_is_one_entry_by_its_new_path(tmp_path):
    repo = cloned(tmp_path)
    run("git", "mv", "ren.txt", "moved.txt", cwd=repo)
    assert pick_files(repo, "origin/main", "tree")["files"] == [{"code": "R", "path": "moved.txt"}]
    assert [f["path"] for f in pick_files(repo, "origin/main", "session")["files"] if not f.get("gone")] == [
        "moved.txt"
    ]


def test_tree_caps_at_twenty(tmp_path):
    repo = cloned(tmp_path)
    for i in range(GIT_PICK_TREE + 5):
        (repo / f"f{i:03}.txt").write_text(str(i))
    assert len(pick_files(repo, "origin/main", "tree")["files"]) == GIT_PICK_TREE == 20


def test_session_caps_at_a_hundred_with_more(tmp_path):
    repo = cloned(tmp_path)
    for i in range(GIT_PICK_SESSION + 5):
        (repo / f"f{i:03}.txt").write_text(str(i))
    got = pick_files(repo, "origin/main", "session")
    assert len(got["files"]) == GIT_PICK_SESSION and got["more"] == 5


def test_an_old_sha_and_an_unknown_pick_are_refused_in_words(tmp_path):
    repo = cloned(tmp_path)
    old = pick_files(repo, None, "tree")["commits"][0]["sha"]
    for i in range(10):
        (repo / "n.txt").write_text(str(i))
        run("git", "add", ".", cwd=repo)
        commit(repo, f"c{i}")
    with pytest.raises(GitPickError, match="not among the last ten commits"):
        pick_files(repo, None, old)
    with pytest.raises(GitPickError, match="pick is tree, session or a sha"):
        pick_files(repo, None, "x")
    with pytest.raises(GitPickError, match="not a git directory"):
        pick_files(tmp_path / "origin.git" / "hooks", None, "tree")


def test_an_unborn_head_has_no_commits(tmp_path):
    run("git", "init", "-q", str(tmp_path / "u"), cwd=tmp_path)
    (tmp_path / "u" / "a.txt").write_text("a")
    got = pick_files(tmp_path / "u", None, "tree")
    assert got["commits"] == [] and got["files"] == [{"code": "??", "path": "a.txt"}]


def test_git_files_is_a_node_read_and_ungated():
    assert "git_files" in NODE_READS  # a node's record's pick goes through `read`, as `paths` does
    assert "git_files" in identity.READS


@pytest.mark.integration
async def test_the_read_answers_on_the_records_host_and_refuses_in_words(agent, tmp_path):
    repo = cloned(tmp_path)
    (repo / "a.txt").write_text("a")
    run("git", "add", ".", cwd=repo)
    sha = commit(repo, "a")
    async with LocalClient() as person:
        sid = (await person.call("create", name="sh", dir=str(repo), adapter="shell", argv=["bash", "--norc"]))["id"]
        got = await person.call("git_files", id=sid, pick=sha)
        assert got["commits"][0]["sha"] == sha and got["files"] == [{"code": "A", "path": "a.txt"}]
        with pytest.raises(AgentError, match="git_files: pick is tree, session or a sha"):
            await person.call("git_files", id=sid, pick="x")
        was = agent.mode, agent.home
        agent.mode, agent.home = "node", "kmaster"  # the home's `read` of a node's record reaches it
        via = await agent._from_home("read", {"rpc": "git_files", "params": {"id": sid, "pick": "session"}})
        assert via["files"] == [{"code": "A", "path": "a.txt"}] and via["more"] == 0
        agent.mode, agent.home = was
        await person.call("kill", id=sid)
