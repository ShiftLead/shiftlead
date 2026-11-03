"""A look's shots are the pushed commit's (design §4.10 *A look*, TD-1303; TD-1307 slice 2): a reader
draws the first of the look's commit (while an origin ref contains it), `origin/<shots_ref>` and
`origin/<default>` that holds the file, and a presence read's miss on the commit fetches that one
branch in the background, at most once a `SHOT_TTL`, answering a miss until a fetch has ended since
the commit was first read. Real repos: a bare origin, the sender's clone and the reader's."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sessionorc import shots

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n"
SHOT = "docs/mockups/reviews/a.png"


def git(cwd: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return cp.stdout.strip()


class Repos:
    def __init__(self, tmp_path: Path):
        self.origin, self.sender, self.reader = tmp_path / "origin.git", tmp_path / "sender", tmp_path / "proj"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(tmp_path, "clone", "-q", str(self.origin), str(self.sender))
        git(self.sender, "checkout", "-q", "-b", "main")
        (self.sender / "README").write_text("x\n")
        git(self.sender, "add", "-A")
        git(self.sender, "commit", "-q", "-m", "first")
        git(self.sender, "push", "-q", "origin", "main")
        git(tmp_path, "clone", "-q", str(self.origin), str(self.reader))
        self.reader = self.reader.resolve()

    def commit_shot(self, body: bytes, branch: str = "feat", push: bool = True, force: bool = False) -> str:
        p = self.sender / SHOT
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(PNG + body)
        git(self.sender, "add", "-A")
        git(self.sender, "commit", "-q", "-m", f"shot {body!r}")
        if push:
            git(self.sender, "push", "-q", *(["-f"] if force else []), "origin", f"HEAD:refs/heads/{branch}")
        return git(self.sender, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    shots._forget()
    fetches: list[str] = []
    real = shots._fetch_branch

    def counted(root, ref):
        fetches.append(ref)
        real(root, ref)

    monkeypatch.setattr(shots, "_fetch_branch", counted)
    r = Repos(tmp_path)
    r.fetches = fetches
    yield r
    shots._forget()


def presence(r: Repos, at: str, ref: str) -> tuple[str, str]:
    return shots.locate(r.reader, "a.png", at, ref, fetch=True)


def test_a_look_from_a_pushed_unmerged_branch_draws_its_commits_file(repos):
    at = repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    assert presence(repos, at, "feat")[1] == "commit"
    assert shots.read_from(repos.reader, "a.png", at, "feat") == (PNG + b"v1", "commit")
    assert repos.fetches == [], "a contained commit fetches nothing"
    # no shots_at: origin/<default> alone, which does not hold it; a lone ref is ignored
    assert shots.locate(repos.reader, "a.png") == ("", "")
    assert shots.locate(repos.reader, "a.png", "", "feat", fetch=True) == ("", "")
    assert shots.locate(repos.reader, "a.png", "not-a-sha", "feat", fetch=True) == ("", "")
    assert repos.fetches == []


def test_a_look_pushed_after_the_reader_last_fetched_draws_after_its_one_branch_fetch(repos):
    at = repos.commit_shot(b"v1")  # the reader has not fetched: it lacks the object
    assert presence(repos, at, "feat") == ("", ""), "a miss at once: the render never waits on the fetch"
    shots.wait_fetches()
    assert repos.fetches == ["feat"]
    assert presence(repos, at, "feat")[1] == "commit"
    assert shots.fetch_gen(repos.reader, "feat") == 1


def test_a_rebased_look_draws_the_branchs_file_once_the_branch_is_fetched_again(repos):
    old = repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    git(repos.sender, "commit", "-q", "--amend", "-m", "rebased")
    (repos.sender / SHOT).write_bytes(PNG + b"v2")
    git(repos.sender, "commit", "-q", "-a", "--amend", "-m", "rebased")
    git(repos.sender, "push", "-q", "-f", "origin", "HEAD:refs/heads/feat")
    git(repos.reader, "fetch", "-q", "origin")  # the old commit is held by no origin ref now
    assert presence(repos, old, "feat") == ("", ""), "fetched unset: the name alone, never a stale file"
    shots.wait_fetches()
    assert presence(repos, old, "feat")[1] == "ref"
    assert shots.read_from(repos.reader, "a.png", old, "feat") == (PNG + b"v2", "ref")
    for _ in range(3):  # read again and again within SHOT_TTL: no fetch is repeated, no blink
        assert presence(repos, old, "feat")[1] == "ref"
    shots.wait_fetches()
    assert repos.fetches == ["feat"]


def test_a_re_sent_look_draws_its_new_file_though_the_readers_branch_ref_is_stale(repos):
    repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    new = repos.commit_shot(b"v2")  # same name, a new commit the reader's origin/feat has not seen
    assert presence(repos, new, "feat") == ("", ""), "never origin/feat's older file of the same name"
    shots.wait_fetches()
    assert presence(repos, new, "feat")[1] == "commit"
    assert shots.read(repos.reader, "a.png", new, "feat") == PNG + b"v2"


def test_a_failed_fetch_falls_to_the_branchs_kept_ref_then_the_default(repos, monkeypatch):
    old = repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    git(repos.sender, "commit", "-q", "--amend", "-m", "elsewhere")
    git(repos.sender, "push", "-q", "-f", "origin", "HEAD:refs/heads/feat")
    git(repos.reader, "fetch", "-q", "origin")  # origin/feat holds v1 under a commit that is not `old`
    git(repos.sender, "push", "-q", "origin", ":refs/heads/feat")  # the forge deletes it
    assert presence(repos, old, "feat") == ("", "")
    shots.wait_fetches()
    assert repos.fetches == ["feat"]
    assert presence(repos, old, "feat")[1] == "ref", "the failed fetch's --no-prune kept origin/feat"
    # pruned, and the squash merged on main: the default branch's file, the merged change's
    git(repos.sender, "checkout", "-q", "main")
    (repos.sender / SHOT).parent.mkdir(parents=True, exist_ok=True)
    (repos.sender / SHOT).write_bytes(PNG + b"merged")
    git(repos.sender, "add", "-A")
    git(repos.sender, "commit", "-q", "-m", "squash")
    git(repos.sender, "push", "-q", "origin", "main")
    git(repos.reader, "fetch", "-q", "--prune", "origin")
    shots._contained.clear()
    assert presence(repos, old, "feat")[1] == "default"
    assert shots.read(repos.reader, "a.png", old, "feat") == PNG + b"merged"


def test_a_branch_is_fetched_at_most_once_a_shot_ttl(repos, monkeypatch):
    git(repos.sender, "push", "-q", "origin", "HEAD:refs/heads/gone")
    at = "0" * 40  # a commit nobody holds: every presence read misses the first step
    for _ in range(5):
        presence(repos, at, "gone")
    shots.wait_fetches()
    for _ in range(5):
        presence(repos, at, "gone")
    shots.wait_fetches()
    assert repos.fetches == ["gone"], "the fetch ended under SHOT_TTL ago bars another"
    monkeypatch.setattr(shots, "SHOT_TTL", -1.0)  # its minute is past: the re-fetch runs in the background
    presence(repos, at, "gone")
    shots.wait_fetches()
    assert repos.fetches == ["gone", "gone"]


def test_the_image_read_never_fetches(repos):
    at = repos.commit_shot(b"v1")
    assert shots.read_from(repos.reader, "a.png", at, "feat") == (None, "")
    shots.wait_fetches()
    assert repos.fetches == []


def test_a_node_reading_echoes_the_requests_at_and_names_its_source(repos, monkeypatch):
    at = repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    monkeypatch.setattr(shots, "root_of", lambda repo: repos.reader if repo == "proj" else None)
    head = shots.reading("proj", "a.png", at, "feat", head=True)
    assert head == {"at": at, "from": "commit", "exists": True, "png": ""}
    got = shots.reading("proj", "a.png", at, "feat")
    assert (got["at"], got["from"], got["exists"]) == (at, "commit", True) and got["png"]
    assert shots.reading("other", "a.png", at, "feat")["at"] == at, "echoed whichever source, none too"
    assert shots.reading("proj", "a.png")["at"] == ""


def _rebase(repos: Repos, body: bytes) -> None:
    (repos.sender / SHOT).write_bytes(PNG + body)
    git(repos.sender, "commit", "-q", "-a", "--amend", "-m", "rebased")
    git(repos.sender, "push", "-q", "-f", "origin", "HEAD:refs/heads/feat")


def test_a_look_read_as_a_hit_then_rebased_draws_its_branch_without_blinking(repos):
    """Every presence read records its commit, hit or miss: a look first read while contained is in
    the set of the branch's next fetch (here one another look on the branch caused), so once its
    branch is rebased it reads the branch's file at once, never its name."""
    old = repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    assert presence(repos, old, "feat")[1] == "commit"
    assert presence(repos, "0" * 40, "feat") == ("", "")  # another look on the branch: its fetch
    shots.wait_fetches()
    _rebase(repos, b"v2")
    git(repos.reader, "fetch", "-q", "origin")
    shots._contained.clear()
    assert presence(repos, old, "feat")[1] == "ref"
    assert repos.fetches == ["feat"]


def test_a_fetchs_end_drops_every_look_on_its_branch_at_once(repos):
    """Two looks on one branch, both pushed after the reader last fetched: the one fetch's end bumps
    the branch's count, so a presence answer kept under the old count is read again (the page's
    `_shot_seen`), and both draw their commits."""
    first = repos.commit_shot(b"one")
    second = repos.commit_shot(b"two")
    assert presence(repos, first, "feat") == ("", "") and presence(repos, second, "feat") == ("", "")
    assert shots.fetch_gen(repos.reader, "feat") == 0
    shots.wait_fetches()
    assert shots.fetch_gen(repos.reader, "feat") == 1
    assert presence(repos, first, "feat")[1] == "commit" and presence(repos, second, "feat")[1] == "commit"
    assert repos.fetches == ["feat"], "one fetch for both"


def test_a_commit_not_read_for_two_shot_ttls_leaves_the_fetched_set(repos, monkeypatch):
    old = repos.commit_shot(b"v1")
    git(repos.reader, "fetch", "-q", "origin")
    _rebase(repos, b"v2")
    git(repos.reader, "fetch", "-q", "origin")
    presence(repos, old, "feat")
    shots.wait_fetches()
    assert presence(repos, old, "feat")[1] == "ref"
    clock = [shots.time.monotonic()]
    monkeypatch.setattr(shots.time, "monotonic", lambda: clock[0])
    clock[0] += 2 * shots.SHOT_TTL + 1  # unread for two minutes: forgotten, as after a restart
    assert presence(repos, old, "feat") == ("", "")
    shots.wait_fetches()


def test_fetches_in_flight_are_capped(repos, monkeypatch):
    import threading

    gate = threading.Event()
    started: list[str] = []

    def slow(root, ref):
        started.append(ref)
        gate.wait(10)

    monkeypatch.setattr(shots, "_fetch_branch", slow)
    for i in range(shots.FETCHES_MAX + 2):
        presence(repos, "0" * 40, f"b{i}")
    assert len(started) <= shots.FETCHES_MAX
    with shots._lock:
        running = sum(1 for b in shots._branches.values() if b.running is not None)
    assert running == shots.FETCHES_MAX
    gate.set()
    shots.wait_fetches()
