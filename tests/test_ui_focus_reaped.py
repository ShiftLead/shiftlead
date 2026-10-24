"""The Focus page after a close's reap (design §4.1 *Kept, and said*, §4.5a *Focus side panel*, TD-979): the
Session card's directory line says *kept — <why>* or *reaped*, and a reaped record draws no Git card."""

from __future__ import annotations

import subprocess

from test_ui import client  # noqa: F401 — the fixture, by name


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path):
    origin, r = tmp_path / "origin.git", tmp_path / "r"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(r))
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / ".gitignore").write_text(".claude/\n")
    git(r, "add", ".gitignore")
    git(r, "commit", "-q", "-m", "one")
    git(r, "push", "-q", "-u", "origin", "main")
    git(r, "remote", "set-head", "origin", "-a")
    return r


def _start(client, repo, name):  # noqa: F811
    form = {"name": name, "dir": str(repo), "where": "worktree", "worktree": name, "adapter": "hookstub"}
    r = client.post("/new", data=form, follow_redirects=False)
    return r.headers["location"].rsplit("/", 1)[-1]


def test_a_reaped_record_draws_no_git_card_and_a_kept_one_says_why(client, tmp_path):  # noqa: F811
    repo = _repo(tmp_path)
    reaped, kept, ahead = _start(client, repo, "rp"), _start(client, repo, "kp"), _start(client, repo, "ah")
    html = client.get(f"/focus/{reaped}").text
    assert 'id="gitcard"' in html  # live: the Git card
    assert 'data-confirm="Close rp? It is killed and its worktree reaped unless that would lose something."' in html
    (repo / ".claude" / "worktrees" / "kp" / "scratch").write_text("x")
    wt = repo / ".claude" / "worktrees" / "ah"
    (wt / "f").write_text("x")
    git(wt, "add", "f")
    git(wt, "commit", "-q", "-m", "unpushed")
    for sid in (reaped, kept, ahead):
        assert client.post(f"/api/sessions/{sid}/close").status_code == 200
    html = client.get(f"/focus/{reaped}").text
    assert 'id="gitcard"' not in html and 'id="fworktree"' in html and "· reaped</span>" in html
    html = client.get(f"/focus/{kept}").text
    assert 'id="gitcard"' in html and "· kept — 1 uncommitted</span>" in html
    # a branch kept for commits never on origin: the card adds that the repo's reaper takes a landed one
    html = client.get(f"/focus/{ahead}").text
    assert "· reaped — branch kept, 1 commit never on origin (the repo&#39;s reaper takes a landed one)</span>" in html
