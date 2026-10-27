"""TD-685 slice 1, design §6 *Sync: a mechanical sync PR is merged at the home*: `sync.check` — step 1
(the lock and the bytes are dev-cadence's) and step 2 (the replay, with `post_sync`, gives the PR's
head) — against a fixture dev-cadence and a fixture repo, each a bare origin and a checkout."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest

from sessionorc import sync

pytestmark = pytest.mark.unit

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
DOC = "docs/cadence.md"


def g(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=ENV
    ).stdout.strip()


def write(root: Path, files: dict[str, str | None]) -> None:
    for path, text in files.items():
        f = root / path
        if text is None:
            f.unlink()
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


def commit(root: Path, files: dict[str, str | None], msg: str = "c") -> str:
    write(root, files)
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", msg)
    return g(root, "rev-parse", "HEAD")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def lock(source: str, fc: str, files: dict[str, str], mode: str = "644") -> str:
    lines = ["# Written by dev-cadence sync.sh", f"source: {source}", f"commit: {fc[:7]}", f"files_commit: {fc}"]
    return "\n".join(lines + [f"file: {p} {sha(t)} {mode}" for p, t in files.items()]) + "\n"


class World:
    """A dev-cadence (`dc`, its origin `dc.git`) and a repo (`repo`, its origin `repo.git`) whose main
    holds a lock of `DOC` at dev-cadence's first commit, and `post_sync` when given."""

    def __init__(self, tmp: Path, post_sync: str | None = None):
        self.tmp = tmp
        for name in ("dc", "repo"):
            g(tmp, "init", "-q", "--bare", "-b", "main", f"{name}.git")
            g(tmp, "clone", "-q", f"{tmp}/{name}.git", name)
            g(tmp / name, "checkout", "-q", "-b", "main")
        self.dc, self.repo, self.source = tmp / "dc", tmp / "repo", f"{tmp}/dc.git"
        self.fc0 = self.dc_commit({DOC: "one\n"})
        toml = f'post_sync = "{post_sync}"\n' if post_sync else "# nothing\n"
        commit(self.repo, {DOC: "one\n", sync.LOCK: lock(self.source, self.fc0, {DOC: "one\n"}), sync.TOML: toml})
        g(self.repo, "push", "-q", "origin", "main")
        g(self.repo, "remote", "set-head", "origin", "main")
        g(self.dc, "remote", "set-head", "origin", "main")

    def dc_commit(self, files: dict[str, str], push: bool = True) -> str:
        c = commit(self.dc, {f"files/{p}": t for p, t in files.items()})
        if push:
            g(self.dc, "push", "-q", "origin", "HEAD:main")
        return c

    def pr(self, files: dict[str, str | None], branch: str = "cadence-sync-1") -> str:
        g(self.repo, "checkout", "-q", "-B", branch, "origin/main")
        head = commit(self.repo, files)
        g(self.repo, "push", "-q", "-f", "origin", branch)
        g(self.repo, "checkout", "-q", "main")
        return head

    def check(self, head: str, branch: str = "cadence-sync-1", **kw) -> dict:
        return sync.check(self.repo, 7, head, branch, clones=[self.dc], **kw)

    def honest(self, text: str = "two\n", extra: dict | None = None) -> str:
        """A sync of `DOC` to `text` as dev-cadence wrote it, plus `extra` paths."""
        fc = self.dc_commit({DOC: text})
        return self.pr({DOC: text, sync.LOCK: lock(self.source, fc, {DOC: text}), **(extra or {})})


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    return World(tmp_path)


def test_a_clean_sync_is_mechanical(world):
    head = world.honest()
    got = world.check(head)
    assert (got["verdict"], got["why"], got["head"]) == ("mechanical", "", head)
    assert got["files"] == [DOC] and got["post_sync"] is False and got["commit"] == g(world.dc, "rev-parse", "HEAD")[:7]
    assert sync.tree_dir(world.repo) == world.tmp / "home" / "sync" / "repo" / "tree"
    assert sync.tree_dir(world.repo).is_dir()


def test_a_file_the_lock_does_not_list_is_refused(world):
    assert world.check(world.honest(extra={"src/x.py": "x\n"}))["why"] == "src/x.py is not in the lock"


def test_an_edited_sync_file_beside_an_honest_lock_is_refused(world):
    fc = world.dc_commit({DOC: "two\n"})
    head = world.pr({DOC: "two, edited\n", sync.LOCK: lock(world.source, fc, {DOC: "two\n"})})
    assert world.check(head) == {"head": head, "verdict": "refused", "why": f"{DOC} differs from its lock line"}


def test_a_sync_file_edited_with_its_line_left_alone_is_refused(world):
    head = world.pr({DOC: "edited\n"})
    assert world.check(head)["why"] == f"{DOC} differs from its lock line"


def test_a_lock_the_pr_wrote_for_itself_is_refused(world):
    """Its hashes are its own files', not dev-cadence's: the bytes match the lock, the lock not dc."""
    head = world.pr({DOC: "mine\n", sync.LOCK: lock(world.source, world.fc0, {DOC: "mine\n"})})
    assert world.check(head)["why"] == f"lock not dev-cadence's: {DOC}"


def test_a_changed_source_is_refused(world):
    fc = world.dc_commit({DOC: "two\n"})
    head = world.pr({DOC: "two\n", sync.LOCK: lock("https://github.com/evil/dc", fc, {DOC: "two\n"})})
    assert world.check(head)["why"] == "the lock's source changed"


def test_no_clone_of_the_source_is_refused(world):
    head = world.honest()
    got = sync.check(world.repo, 7, head, "cadence-sync-1", clones=[world.repo])
    assert got["why"] == "no dev-cadence clone to check the lock against"


def test_a_dirty_files_commit_is_refused(world):
    fc = world.dc_commit({DOC: "two\n"})
    head = world.pr({DOC: "two\n", sync.LOCK: lock(world.source, fc + "+dirty", {DOC: "two\n"})})
    assert world.check(head)["why"] == "files_commit is +dirty"


def test_a_files_commit_off_dev_cadences_default_is_refused(world):
    g(world.dc, "checkout", "-q", "-b", "side")
    fc = world.dc_commit({DOC: "two\n"}, push=False)
    g(world.dc, "push", "-q", "origin", "side")
    head = world.pr({DOC: "two\n", sync.LOCK: lock(world.source, fc, {DOC: "two\n"})})
    assert world.check(head)["why"] == f"files_commit {fc[:7]} is not on dev-cadence's main"


def test_a_deleted_file_still_in_the_lock_and_one_the_base_lock_never_listed(world):
    head = world.pr({DOC: None, sync.LOCK: lock(world.source, world.fc0, {DOC: "one\n"}) + "# again\n"})
    assert world.check(head)["why"] == f"{DOC} deleted but still in the lock"
    commit(world.repo, {"README": "r\n"})
    g(world.repo, "push", "-q", "origin", "main")
    head = world.honest(extra={"README": None})
    assert world.check(head)["why"] == "README deleted but not in the base lock"


def test_a_file_dev_cadence_retired_is_deleted_by_the_replay(world):
    fc = world.dc_commit({"docs/b.md": "b\n"})
    two = {DOC: "one\n", "docs/b.md": "b\n"}
    head = world.pr({"docs/b.md": "b\n", sync.LOCK: lock(world.source, fc, two)})
    g(world.repo, "fetch", "-q")
    g(world.repo, "merge", "-q", "--ff-only", "origin/cadence-sync-1")
    g(world.repo, "push", "-q", "origin", "main")
    g(world.dc, "rm", "-q", "files/docs/b.md")
    fc = world.dc_commit({})
    head = world.pr({"docs/b.md": None, sync.LOCK: lock(world.source, fc, {DOC: "one\n"})}, branch="cadence-sync-2")
    assert world.check(head, branch="cadence-sync-2")["verdict"] == "mechanical"


def test_a_held_path_is_refused(world):
    head = world.honest()
    assert world.check(head, held=["docs/**"])["why"] == f"{sync.LOCK} is a held path"
    assert world.check(head, held=[DOC])["why"] == f"{DOC} is a held path"
    assert world.check(head, held=["src/**"])["verdict"] == "mechanical"


def test_a_head_that_moved_is_not_checked(world):
    old = world.honest()
    world.honest("three\n")
    assert world.check(old)["verdict"] == "moved"


@pytest.fixture
def post(tmp_path, monkeypatch):
    def make(cmd: str) -> World:
        monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
        (d := tmp_path / f"w{len(list(tmp_path.glob('w*')))}").mkdir()
        return World(d, post_sync=cmd)

    return make


def test_a_post_sync_that_reproduces_the_pr_is_mechanical_and_one_that_does_not_is_refused(post):
    w = post("cat docs/cadence.md > gen.txt")
    head = w.honest(extra={"gen.txt": "two\n"})
    got = w.check(head)
    assert (got["verdict"], got["post_sync"]) == ("mechanical", True)
    head = w.honest("three\n", extra={"gen.txt": "not what post_sync writes\n"})
    assert w.check(head)["why"] == "post_sync left gen.txt unlike the PR"
    # a file post_sync never wrote is not in the lock, whatever the replay does
    head = w.honest("four\n", extra={"gen.txt": "four\n", "other.txt": "o\n"})
    assert w.check(head)["why"] == "other.txt is not in the lock"


def test_post_sync_sees_no_token_and_its_failures_are_reasons(post, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("SHIFTLEAD_SESSION", "x")
    w = post("echo ${GH_TOKEN:-none} ${SHIFTLEAD_SESSION:-none} > tok.txt")
    assert w.check(w.honest(extra={"tok.txt": "none none\n"}))["verdict"] == "mechanical"


def test_post_sync_exit_and_bound(post):
    w = post("exit 3")
    assert w.check(w.honest())["why"] == "post_sync exited 3"
    w2 = post("sleep 30")
    assert w2.check(w2.honest("five\n"), bound=0.5)["why"].startswith("post_sync did not end in ")


# the head of this repo's own last lock (dev-cadence 232f2ad), as sync.sh wrote it: the repo pins dev-cadence
# now (dev-cadence TD-129) and carries no lock, and a lock is still read while a served repo has one
LAST_OWN_LOCK = """# Written by ShiftLead/dev-cadence sync.sh — do not edit by hand.
source: https://github.com/ShiftLead/dev-cadence
commit: 232f2ad
files_commit: 232f2ad364384929f57011ff2e76b9ba324ab8d7
synced: 2026-10-23T01:54:48Z
file: docs/cadence.md e1f332cb617f8333fb148f401f19e21958ee6d1a6547cbc02791dc67ad63efcd 644
file: docs/cadence-rationale.md f06aecd78c767a0eac466bb0c5e4637b364fc3582cfd6da5d930c1a38498961d 644
"""


def test_parse_lock_reads_a_lock_as_sync_sh_writes_it():
    got = sync.parse_lock(LAST_OWN_LOCK)
    assert got["source"] == "https://github.com/ShiftLead/dev-cadence" and got["files"]["docs/cadence.md"][1] == "644"
    assert sync.parse_lock(None) is None


def test_origins_compare_as_one_repository():
    n = sync._norm_url
    assert n("git@github.com:ShiftLead/dev-cadence.git") == n("https://github.com/shiftlead/dev-cadence/")
    assert n("/tmp/x/dc.git") == n("/tmp/x/dc")


def test_a_lock_line_dropped_while_dev_cadence_still_has_the_file_is_refused(world):
    """A PR that drops a guard script's line and deletes it is not dev-cadence's retirement."""
    head = world.pr({DOC: None, sync.LOCK: lock(world.source, world.fc0, {})})
    assert world.check(head)["why"] == f"lock not dev-cadence's: {DOC}"


def test_a_mode_only_change_differs_from_its_lock_line(world):
    world.honest()
    g(world.repo, "checkout", "-q", "cadence-sync-1")
    (world.repo / DOC).chmod(0o755)
    g(world.repo, "commit", "-q", "-am", "x")
    g(world.repo, "push", "-q", "origin", "cadence-sync-1")
    head = g(world.repo, "rev-parse", "HEAD")
    g(world.repo, "checkout", "-q", "main")
    assert world.check(head)["why"] == f"{DOC} differs from its lock line"


def test_what_post_sync_leaves_running_is_killed(tmp_path):
    """Its leader exits 0 at once; the child it backgrounded is killed with its group, so nothing
    writes the tree after the read."""
    (tmp_path / "t").mkdir()
    assert sync.run_post_sync(tmp_path / "t", "(sleep 1; echo late > late.txt) & exit 0", bound=5) is None
    time.sleep(1.5)
    assert not (tmp_path / "t" / "late.txt").exists()
