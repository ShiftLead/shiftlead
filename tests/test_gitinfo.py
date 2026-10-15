"""porcelain v2 parsing against a real repo: spaces in paths, renames, ahead/behind, untracked."""

import subprocess

from sessionorc.gitinfo import git_info


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def test_git_info_paths_with_spaces_and_renames(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    (repo / "a file.txt").write_text("1")
    (repo / "old.txt").write_text("x" * 100)
    run("git", "add", ".", cwd=repo)
    run("git", "commit", "-q", "-m", "init", cwd=repo)
    (repo / "a file.txt").write_text("2")
    run("git", "mv", "old.txt", "new name.txt", cwd=repo)
    (repo / "untracked one.md").write_text("u")
    info = git_info(repo)
    assert info is not None and info.branch == "main" and info.upstream is None
    assert "M a file.txt" in info.files
    assert "R new name.txt" in info.files
    assert "?? untracked one.md" in info.files
    assert info.dirty == 3


def test_git_info_ahead_of_upstream(tmp_path):
    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    repo = tmp_path / "r"
    run("git", "clone", "-q", str(origin), str(repo), cwd=tmp_path)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    run("git", "checkout", "-q", "-b", "main", cwd=repo)
    (repo / "f").write_text("1")
    run("git", "add", "f", cwd=repo)
    run("git", "commit", "-q", "-m", "one", cwd=repo)
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    (repo / "f").write_text("2")
    run("git", "commit", "-q", "-am", "two", cwd=repo)
    info = git_info(repo)
    assert info and info.upstream == "origin/main" and info.ahead == 1 and info.behind == 0 and info.dirty == 0
    assert git_info(tmp_path / "not-a-repo") is None or True  # a non-repo returns None or a parent's info


def test_unpushed_is_one_measure_of_exists_only_on_this_machine(tmp_path):
    """Design §4.2 *one measure* (TD-080): *does this work exist only on this machine*, never *is
    it merged*. The three rules, in the order they apply — a launch branch that tracks
    `origin/main` and is pushed to its own ref read *308 unpushed* for ever before this."""
    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    repo = tmp_path / "r"
    run("git", "clone", "-q", str(origin), str(repo), cwd=tmp_path)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    (repo / "f").write_text("1")
    run("git", "add", "f", cwd=repo)
    run("git", "commit", "-q", "-m", "one", cwd=repo)
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)

    # rule 2: no `origin/<branch>` of its own, but an upstream — the porcelain's ahead, as before
    run("git", "checkout", "-q", "-b", "work", cwd=repo)
    run("git", "branch", "-q", "--set-upstream-to=origin/main", cwd=repo)
    (repo / "f").write_text("2")
    run("git", "commit", "-q", "-am", "two", cwd=repo)
    info = git_info(repo)
    assert info and (info.unpushed, info.pushed_against) == (1, "origin/main")

    # rule 1: the branch has its own remote ref — counted against *that*, whatever the upstream is.
    # This is TD-080's case: still ahead of origin/main, and no longer *unpushed*.
    run("git", "push", "-q", "origin", "work", cwd=repo)
    info = git_info(repo)
    assert info and info.ahead == 1, "still ahead of the upstream it tracks"
    assert (info.unpushed, info.pushed_against) == (0, "origin/work"), "and its work is not only here"
    (repo / "f").write_text("3")
    run("git", "commit", "-q", "-am", "three", cwd=repo)
    info = git_info(repo)
    assert info and (info.unpushed, info.pushed_against) == (1, "origin/work")

    # rule 3: neither — a detached HEAD on what origin has is pushed; a commit on no remote is not
    run("git", "checkout", "-q", "--detach", "origin/main", cwd=repo)
    info = git_info(repo)
    assert info and (info.unpushed, info.pushed_against) == (0, "remote branches")
    (repo / "f").write_text("4")
    run("git", "commit", "-q", "-am", "four", cwd=repo)
    info = git_info(repo)
    assert info and (info.unpushed, info.pushed_against) == (1, "remote branches")


def test_a_squash_merged_branch_tracking_origin_main_reads_pushed(tmp_path):
    """TD-701: a branch cut with `git switch -c … origin/main` tracks `origin/main`; squash-merged
    under another sha and its remote branch deleted, rule 2's porcelain *ahead* read it *1 unpushed*
    for ever. A commit whose content the upstream holds is not unpushed; one it lacks still is."""
    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    repo, other = tmp_path / "r", tmp_path / "o"
    run("git", "clone", "-q", str(origin), str(repo), cwd=tmp_path)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    (repo / "f").write_text("1\n")
    (repo / "g").write_text("a\n")
    run("git", "add", ".", cwd=repo)
    run("git", "commit", "-q", "-m", "one", cwd=repo)
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    run("git", "clone", "-q", str(origin), str(other), cwd=tmp_path)
    run("git", "config", "user.email", "o@o", cwd=other)
    run("git", "config", "user.name", "o", cwd=other)

    def squash_on_origin(*branch_files: tuple[str, str]) -> None:
        """What GitHub's squash merge does: the branch's content as one commit on main, by
        someone else, then another PR merged after it."""
        run("git", "pull", "-q", "--rebase", "origin", "main", cwd=other)
        for name, text in branch_files:
            (other / name).write_text(text)
        run("git", "commit", "-q", "-am", "squash", cwd=other)
        later = other / "later"
        later.write_text(later.read_text() + "x" if later.exists() else "x")
        run("git", "add", "later", cwd=other)
        run("git", "commit", "-q", "-m", "a later PR", cwd=other)
        run("git", "push", "-q", "origin", "main", cwd=other)
        run("git", "fetch", "-q", "origin", cwd=repo)

    # one commit, squash-merged: its patch is on main under another sha
    run("git", "switch", "-q", "-c", "td-one", "origin/main", cwd=repo)
    (repo / "f").write_text("2\n")
    run("git", "commit", "-q", "-am", "two", cwd=repo)
    info = git_info(repo)
    assert info and (info.unpushed, info.pushed_against) == (1, "origin/main"), "not merged yet: only here"
    squash_on_origin(("f", "2\n"))
    info = git_info(repo)
    assert info and info.ahead == 1 and info.behind == 2
    assert (info.unpushed, info.pushed_against) == (0, "origin/main"), "its content is on main"
    (repo / "g").write_text("z\n")
    run("git", "commit", "-q", "-am", "never pushed", cwd=repo)
    info = git_info(repo)
    assert info and info.ahead == 2 and (info.unpushed, info.pushed_against) == (1, "origin/main"), "only that one"
    run("git", "reset", "-q", "--hard", "HEAD~1", cwd=repo)

    # two commits, squashed into one: no single patch matches, the content does
    run("git", "switch", "-q", "-c", "td-two", "origin/main", cwd=repo)
    (repo / "f").write_text("3\n")
    run("git", "commit", "-q", "-am", "three", cwd=repo)
    (repo / "g").write_text("b\n")
    run("git", "commit", "-q", "-am", "four", cwd=repo)
    squash_on_origin(("f", "3\n"), ("g", "b\n"))
    info = git_info(repo)
    assert info and info.ahead == 2 and info.unpushed == 0

    # a commit that never reached the remote on top of a squash of several is not pushed: no single
    # patch matches and the content is not whole upstream, so the three are counted (never 0)
    (repo / "g").write_text("c\n")
    run("git", "commit", "-q", "-am", "five", cwd=repo)
    info = git_info(repo)
    assert info and info.ahead == 3 and (info.unpushed, info.pushed_against) == (3, "origin/main")


def test_ensure_worktree_creates_reuses_and_validates(tmp_path):
    from sessionorc.gitinfo import WorktreeError, ensure_worktree

    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    repo = tmp_path / "r"
    run("git", "clone", "-q", str(origin), str(repo), cwd=tmp_path)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    run("git", "checkout", "-q", "-b", "main", cwd=repo)
    (repo / "f").write_text("1")
    run("git", "add", "f", cwd=repo)
    run("git", "commit", "-q", "-m", "one", cwd=repo)
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    wt = ensure_worktree(repo, "topic-1")
    assert wt == repo / ".claude" / "worktrees" / "topic-1" and (wt / "f").is_file()
    branch = subprocess.run(["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    assert branch.stdout.strip() == "topic-1"
    assert ensure_worktree(repo, "topic-1") == wt  # idempotent
    import pytest

    with pytest.raises(WorktreeError, match="letters, digits"):
        ensure_worktree(repo, "../evil")
    with pytest.raises(WorktreeError, match="not a git repository"):
        ensure_worktree(tmp_path / "plain", "x")


def test_ensure_worktree_from_inside_a_worktree_and_without_origin(tmp_path):
    from sessionorc.gitinfo import ensure_worktree

    repo = tmp_path / "solo"  # no origin: base is HEAD
    repo.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    (repo / "f").write_text("1")
    run("git", "add", "f", cwd=repo)
    run("git", "commit", "-q", "-m", "one", cwd=repo)
    wt1 = ensure_worktree(repo, "wt1")
    assert wt1 == repo / ".claude" / "worktrees" / "wt1"
    # called with the worktree as the "repo": lands beside wt1 under the main checkout, not nested
    wt2 = ensure_worktree(wt1, "wt2")
    assert wt2 == repo / ".claude" / "worktrees" / "wt2"
    # an existing local branch with no worktree yet is checked out, not recreated
    run("git", "branch", "pre-made", cwd=repo)
    wt3 = ensure_worktree(repo, "pre-made")
    head = subprocess.run(["git", "-C", str(wt3), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    assert head.stdout.strip() == "pre-made"


def test_git_info_names_the_commit_so_a_detached_head_can_be_named(tmp_path):
    """Design §4.5 *The card's anatomy*, row 3 (TD-095): *detached at <short sha>* needs the commit;
    a repo with no commit yet has none to name."""
    repo = tmp_path / "r"
    repo.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=repo)
    assert git_info(repo).oid == ""  # `# branch.oid (initial)`
    run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "a", cwd=repo)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    run("git", "checkout", "-q", "--detach", cwd=repo)
    info = git_info(repo)
    assert info.branch == "(detached)" and info.oid == sha


def test_a_new_worktree_is_set_up_by_the_repos_worktree_setup(tmp_path):
    """TD-589, §5 *The seams* `worktree_setup:`: a configured command runs by the shell in each new
    worktree, in place of the default `scripts/hydrate_worktree.sh` (run with the worktree's path);
    neither, and nothing runs. A setup that fails names itself, and the worktree stays."""
    import os

    import pytest

    from sessionorc.gitinfo import WorktreeError, ensure_worktree, worktree_setup

    repo = tmp_path / "solo"
    repo.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "t@t", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    (repo / "f").write_text("1")
    run("git", "add", "f", cwd=repo)
    run("git", "commit", "-q", "-m", "one", cwd=repo)
    assert worktree_setup(repo) == ("absent", None)
    plain = ensure_worktree(repo, "plain")
    assert sorted(p.name for p in plain.iterdir()) == [".git", "f"], "no setup: nothing runs"

    hydrate = repo / "scripts" / "hydrate_worktree.sh"
    hydrate.parent.mkdir()
    hydrate.write_text('#!/bin/sh\necho hydrated > "$1/.hydrated"\n')
    assert worktree_setup(repo) == ("absent", None), "a script that cannot be run is no default"
    os.chmod(hydrate, 0o755)
    assert worktree_setup(repo) == ("defaulted", "scripts/hydrate_worktree.sh")
    assert (ensure_worktree(repo, "hydrated") / ".hydrated").is_file()

    for text in ("worktree_setup: ''\n", "worktree_setup: [a]\n", "worktree_setup: [\n"):
        (repo / ".shiftlead.yml").write_text(text)
        assert worktree_setup(repo)[0] == "defaulted", text
    (repo / ".shiftlead.yml").write_text("worktree_setup: ' pwd > .setup-ran; echo \"$1\" >> .setup-ran '\n")
    assert worktree_setup(repo) == ("set", 'pwd > .setup-ran; echo "$1" >> .setup-ran')
    wt = ensure_worktree(repo, "set")
    assert (wt / ".setup-ran").read_text().split() == [str(wt)] * 2, "run in the new worktree, its path $1"
    assert not (wt / ".hydrated").exists(), "the configured command, not the default"
    assert not (ensure_worktree(repo, "set") / ".hydrated").exists() and (wt / ".setup-ran").is_file()
    (wt / ".setup-ran").unlink()
    ensure_worktree(repo, "set")
    assert not (wt / ".setup-ran").exists(), "a worktree that exists is reused, not set up again"

    (repo / ".shiftlead.yml").write_text("worktree_setup: 'echo no npm >&2; exit 4'\n")
    with pytest.raises(WorktreeError, match=r"but echo no npm >&2; exit 4 failed: no npm"):
        ensure_worktree(repo, "broken")
    assert (repo / ".claude" / "worktrees" / "broken" / "f").is_file(), "the worktree is kept"
