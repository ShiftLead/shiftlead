"""The seat smoke's parts that need no tool (design §4.3 *The live smoke, unattended*, TD-1648): the seat's brief
as a team start composes it and the line it is picked from, the scratch clone and its origin, the ask, and the
reading that passes or fails the run."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("seat_run", ROOT / "scripts" / "seat_run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seat_run"] = mod
    spec.loader.exec_module(mod)
    return mod


sr = _load()

REPO_FILE = """\
teams:
  one:
    manager: {role: manager, name: lead}
    members: [{role: grinder, name: g}]
    seats:
      - {name: audit-a, role: auditor, brief: docs/briefs/audit-a.md, trigger: {prs: 10}}
      - {name: fc-first, role: fact-checker, profile: gemini-reader, brief: docs/briefs/fc-first.md, trigger: asks}
  two:
    manager: {role: manager, name: lead2}
    members: [{role: grinder, name: g2}]
    seats:
      - {name: fc-grok, role: fact-checker, profile: grok-reader, brief: docs/briefs/fc-grok.md, trigger: asks}
      - {name: fc-pool, role: fact-checker, pool: [pool-a, pool-b], brief: docs/briefs/fc-pool.md, trigger: asks}
"""


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "docs" / "briefs").mkdir(parents=True)
    (r / ".shiftlead.yml").write_text(REPO_FILE, encoding="utf-8")
    for n in ("audit-a", "fc-first", "fc-grok", "fc-pool"):
        (r / "docs" / "briefs" / f"{n}.md").write_text(f"REPO PART OF {n}\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", cwd=r)
    _git("add", "-A", cwd=r)
    _git("-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "fixture", cwd=r)
    return r


def test_the_line_on_the_profile_is_picked_across_the_teams_in_file_order(repo):
    got = sr.compose(repo, "fact-checker", "grok-reader")
    assert got.name == "fc-grok" and got.role == "fact-checker"
    assert "REPO PART OF fc-grok" in got.text and "{repo}" not in got.text and "{lane}" not in got.text
    assert "on profile grok-reader" in got.line
    # a pool's member matches by its profile (`seat_records()`)
    assert sr.compose(repo, "fact-checker", "pool-b").name == "fc-pool-p2"


def test_no_line_on_the_profile_borrows_the_roles_first_brief(repo):
    got = sr.compose(repo, "fact-checker", "new-profile")
    assert got.name == "fc-first" and "REPO PART OF fc-first" in got.text
    assert "the role's first line" in got.line


def test_seat_names_the_line_alone_and_refuses_another_roles(repo):
    got = sr.compose(repo, "fact-checker", "grok-reader", seat="fc-first")
    assert got.name == "fc-first" and "REPO PART OF fc-first" in got.text
    with pytest.raises(sr.SeatRefused, match="the auditor role's, not the fact-checker role's"):
        sr.compose(repo, "fact-checker", "grok-reader", seat="audit-a")
    with pytest.raises(sr.SeatRefused, match="no seat line 'nope'"):
        sr.compose(repo, "fact-checker", "grok-reader", seat="nope")


def test_a_role_with_no_seat_line_needs_a_brief_which_replaces_the_template(repo, tmp_path):
    with pytest.raises(sr.SeatRefused, match="no seat line"):
        sr.compose(repo, "sweeper", "p")
    old = tmp_path / "old.md"
    old.write_text("AN OLD TEMPLATE\n\n{repo}\n\nlane: {lane}; techlead: {techlead}\n", encoding="utf-8")
    got = sr.compose(repo, "sweeper", "p", brief_file=old)
    assert got.name == sr.DEFAULT_NAME and got.text.startswith("AN OLD TEMPLATE")
    assert "{repo}" not in got.text and "{techlead}" not in got.text
    # beside a line, `--brief` replaces the template and keeps the line's `brief:` in `{repo}`
    got = sr.compose(repo, "fact-checker", "gemini-reader", brief_file=old)
    assert got.name == "fc-first" and got.text.startswith("AN OLD TEMPLATE") and "REPO PART OF fc-first" in got.text
    assert str(old) in got.line


def test_the_brief_is_the_team_starts_for_the_same_line(repo):
    """The smoke's brief is `teams._brief`'s for the seat line, as a team start composes it: no lane, no flow."""
    from shiftlead import org as orgmod
    from shiftlead import repoconfig, teams

    cfg = repoconfig.load(repo)
    merged = orgmod.merge_repo_teams(orgmod.Org(), repo, dict(cfg.teams), repoconfig.role_names(cfg))
    line = next(s for s in merged.teams["one"].seat_records() if s.name == "fc-first")
    want, _ = teams._brief(repoconfig.resolve_role(cfg, "fact-checker", {}), line, [])
    assert sr.compose(repo, "fact-checker", "gemini-reader").text == want


def test_the_clone_is_heads_and_its_origin_holds_the_same_commits(repo, tmp_path):
    _git("checkout", "-q", "-b", "topic", cwd=repo)
    (repo / "f").write_text("x", encoding="utf-8")
    _git("add", "f", cwd=repo)
    _git("-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "topic", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    where = tmp_path / "scratch"
    where.mkdir()
    clone, bare = sr.scratch_clone(repo, where)
    assert _git("rev-parse", "HEAD", cwd=clone) == head
    assert _git("rev-parse", "main", cwd=bare) == head
    assert _git("remote", "get-url", "origin", cwd=clone) == str(bare)
    _git("fetch", "-q", "origin", cwd=clone)  # the brief's fetch reads
    assert _git("rev-parse", "origin/main", cwd=clone) == head


def test_uncommitted_names_changes_under_the_brief_paths_alone(repo):
    assert sr.uncommitted(repo) == []
    (repo / "docs" / "briefs" / "fc-grok.md").write_text("changed\n", encoding="utf-8")
    (repo / "elsewhere.txt").write_text("x", encoding="utf-8")
    got = sr.uncommitted(repo)
    assert len(got) == 1 and got[0].endswith("docs/briefs/fc-grok.md")
    assert sr.brief_paths(repo)[0] == ".shiftlead.yml" and sr.brief_paths(repo)[-1] == "src/shiftlead/briefs/"


def test_the_ask_names_the_token_and_the_reply_roads_options():
    nonce = sr.new_nonce()
    assert len(nonce) == 12 and int(nonce, 16) >= 0 and nonce != sr.new_nonce()
    text = sr.ask_text(nonce)
    assert nonce in text
    assert all(o in text for o in ("--reply-to", "--json", "--kind", "--about"))


def test_the_environments_drop_the_builders_model_and_the_persons_session():
    env = {"AGENT_MODEL": "m", "AGENT_MODEL_FILE": "f", "SHIFTLEAD_SESSION": "s", "TMUX": "t", "TMUX_PANE": "%1"}
    assert set(sr.agent_env(env)) == {"SHIFTLEAD_SESSION", "TMUX", "TMUX_PANE"}
    assert set(sr.person_env(env)) == {"AGENT_MODEL", "AGENT_MODEL_FILE"}


def test_the_create_carries_no_seat_team_or_worktree(tmp_path):
    seen = {}

    def call(method, **p):
        seen.update(method=method, **p)
        return {"id": "x"}

    sr.launch(call, sr.SeatBrief("fc", "fact-checker", "BRIEF", ""), "gemini", "gemini-reader", tmp_path)
    assert seen == {
        "method": "create",
        "name": "fc",
        "adapter": "gemini",
        "profile": "gemini-reader",
        "dir": str(tmp_path),
        "role": "fact-checker",
        "unattended": True,
        "prompt": "BRIEF",
    }


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def _watch(records, inboxes, timeout=600.0):
    recs, boxes, clock = iter(records), iter(inboxes), Clock()
    last = {"rec": {}, "box": []}

    def get():
        last["rec"] = next(recs, last["rec"])
        return last["rec"]

    def inbox():
        last["box"] = next(boxes, last["box"])
        return last["box"]

    return sr.watch(get, inbox, "m-ask", timeout=timeout, clock=clock, sleep=clock.sleep)


REPLY = {"kind": "reply", "id": "m-r", "thread": "m-ask", "text": "abc"}


def test_a_reply_on_the_thread_passes_whatever_its_text():
    got = _watch([{"state": "working"}, {"state": "working"}], [[], [{"kind": "reply", "thread": "m-other"}, REPLY]])
    assert got.ok and got.step == "reply" and got.said == "abc"
    # a reply naming the ask by `reply_to` counts too, and an exit after it is no failure
    got = _watch([{"state": "exited"}], [[{"kind": "reply", "reply_to": "m-ask", "text": "t"}]])
    assert got.ok


def test_needs_you_fails_at_once_naming_what_it_waits_on():
    pending = {"kind": "permission", "text": "Allow ao msg --reply-to?"}
    got = _watch([{"state": "working"}, {"state": "needs-you", "pending": pending}], [[], [REPLY]])
    assert not got.ok and got.step == "needs-you" and "Allow ao msg --reply-to?" in got.said


def test_an_exit_before_the_reply_fails_and_so_does_the_ten_minutes():
    got = _watch([{"state": "working"}, {"state": "exited"}], [[]])
    assert not got.ok and got.step == "exited"
    got = _watch([{"state": "working"}], [[]], timeout=10.0)
    assert not got.ok and got.step == "timeout" and "reads working" in got.said
