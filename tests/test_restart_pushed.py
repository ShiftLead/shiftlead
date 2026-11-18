"""TD-1923, design §4.9a *A pushed commit is new work*, *A run past its context bound is not early*, *What counts
toward the ceiling* (TD-1900): a restart whose run pushed a commit of its own branch since its record began is not
early, not the *three runs running* repeat and not counted toward `RESTART_CEILING`, but counts toward
`RESTART_PUSHED_CEILING`; one declared over the record's context bound with nothing new is not early; a repeat of
the same `done` stays early whatever the reading."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import park_ticks, wait_for

from sessionorc.agent_common import (
    RESTART_CEILING,
    RESTART_PUSHED_CEILING,
    _counted,
    _restart_reading,
    pushed_ceiling_words,
    restart_waits,
)
from sessionorc.agent_tick import TickMixin
from sessionorc.client import LocalClient
from sessionorc.gitinfo import pushed_since
from sessionorc.models import ProgressEntry, Session
from shiftlead.ui.cards import restarted_view
from shiftlead.ui.inbox import restart_mark

NOW = datetime(2026, 11, 15, 23, 11, tzinfo=UTC)
SHA = "0123456789abcdef0123456789abcdef01234567"
OVER = {"context": {"tokens": 231_000}, "context_bound": 200_000}
UNDER = {"context": {"tokens": 199_000}, "context_bound": 200_000}


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rec(age=timedelta(minutes=17), progress=(), restarts=(), **kw) -> Session:
    made = [ProgressEntry(at=_iso(NOW - timedelta(minutes=1)), **p) for p in progress]
    return Session(
        id="ao-t-w", name="w", kind="interactive", adapter="shell", dir="/tmp/x", state="idle",
        created=_iso(NOW - age), progress=made, restarts=list(restarts), **kw,
    )  # fmt: skip


def _entry(minutes_ago: int, why="wanted", done=(), left=(), **more) -> dict:
    at = _iso(NOW - timedelta(minutes=minutes_ago))
    return {"at": at, "why": why, "done": [dict(d) for d in done], "left": list(left), **more}


# -- the reading (§4.9a *Early is decided from the record*) -------------------------------------------------


@pytest.mark.unit
def test_a_run_over_its_bound_with_nothing_new_is_not_early_and_one_under_it_is():
    got = _restart_reading(_rec(**OVER), NOW)
    assert got == {"early": False, "repeat": None, "words": "not early: context over its bound"}
    assert _restart_reading(_rec(**UNDER), NOW)["early"] is True
    assert _restart_reading(_rec(), NOW)["early"] is True  # no reading at all reads under
    # the same `done` again is a repeat whatever the reading
    before = _entry(40, done=[{"ref": "TD-1", "pr": 812}])
    again = _rec(progress=[{"ref": "TD-1", "status": "done", "pr": 812}], restarts=[before], **OVER)
    got = _restart_reading(again, NOW)
    assert (got["early"], got["repeat"]) == (True, {"ref": "TD-1"})


@pytest.mark.unit
def test_a_pushed_commit_is_new_work_and_never_the_three_runs_repeat():
    """The 2026-11-15 sequence: two prior entries each leaving TD-1895, the third run pushed its round."""
    two = [_entry(80, left=["TD-1895"]), _entry(40, left=["TD-1895"])]
    rec = _rec(progress=[{"ref": "TD-1895"}], restarts=two)
    got = _restart_reading(rec, NOW, pushed=SHA)
    assert got == {"early": False, "repeat": None, "words": "not early: pushed 0123456 this run", "pushed": SHA}
    # nothing pushed: the third run on it is a repeat, as before
    got = _restart_reading(rec, NOW)
    assert (got["early"], got["repeat"]) == (True, {"ref": "TD-1895"})
    # a push does not excuse the same `done` reported again
    before = _entry(40, done=[{"ref": "TD-1", "pr": 812}])
    again = _rec(progress=[{"ref": "TD-1", "status": "done", "pr": 812}], restarts=[before])
    assert _restart_reading(again, NOW, pushed=SHA)["repeat"] == {"ref": "TD-1"}


# -- the two ceilings' counts (§4.9a *What counts toward the ceiling*) ----------------------------------------


@pytest.mark.unit
def test_a_pushed_restart_is_left_out_of_the_ceiling_and_counted_toward_its_own():
    pushed = _entry(30, pushed=SHA)
    worked = _entry(20, done=[{"ref": "TD-2", "pr": 820}], pushed=SHA)  # a new `done`: neither
    bare = _entry(10)
    failed = _entry(5, pushed=SHA, error="create: boom")  # a failed replay counts, as `_counted` counts it
    assert _counted([pushed, worked, bare, failed], NOW) == [bare, failed]
    assert _counted([pushed, worked, bare, failed], NOW, pushed=True) == [pushed, bare, failed]


@pytest.mark.unit
def test_four_context_bound_restarts_with_nothing_pushed_reach_the_ceiling():
    three = [_entry(m) for m in (90, 60, 30)]
    assert len(_counted(three, NOW)) == RESTART_CEILING and TickMixin._window_full(_rec(restarts=three), NOW)


@pytest.mark.unit
def test_a_grinder_that_merges_and_pushes_each_run_reaches_neither_ceiling():
    seven = [_entry(105 - 15 * i, done=[{"ref": f"TD-{i}", "pr": 900 + i}], pushed=SHA) for i in range(7)]
    assert _counted(seven, NOW) == [] and _counted(seven, NOW, pushed=True) == []


@pytest.mark.unit
def test_a_pushed_mark_is_held_by_the_pushed_count():
    six = [_entry(100 - 15 * i, pushed=SHA) for i in range(RESTART_PUSHED_CEILING)]
    rec = _rec(restarts=six, restart_ceiling={"at": _iso(NOW), "count": 6, "why": "pushed"})
    assert TickMixin._window_full(rec, NOW)
    assert not TickMixin._window_full(rec, NOW + timedelta(minutes=30))  # the oldest left the window
    assert restart_waits(None, rec.restart_ceiling, None, None, "idle")["word"] == "restarts exhausted"


# -- the tick (§6 rule 2) ---------------------------------------------------------------------------------

CLEAN = {"branch": "w", "dirty": 0, "unpushed": 0, "upstream": "origin/w"}


async def _member(agent, person, tmp_path, name="w") -> str:
    (tmp_path / name).mkdir()
    params = {
        "name": name, "dir": str(tmp_path / name), "adapter": "composer0", "unattended": True,
        "supervised": True, "prompt": "the brief",
    }  # fmt: skip
    sid = (await person.call("create", **params))["id"]

    async def painted() -> bool:
        return any(t.startswith(">>") for t in await agent.rpc_tail(sid, 3))

    assert await wait_for(painted, timeout=5), "the composer child never painted its prompt"
    return sid


async def _idle(agent, sid: str, now: datetime) -> None:
    await agent.rpc_hook(sid, state="idle")
    agent.sessions[sid].since = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")


@pytest.mark.integration
async def test_a_run_sent_away_at_its_bound_is_replayed_by_the_next_tick(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        first = agent.sessions[sid]
        first.created = _iso(now - timedelta(minutes=17))
        first.context, first.context_bound = {"tokens": 231_000}, 200_000
        async with LocalClient(caller=sid) as w:
            got = await w.call("progress", id=sid, status="restart", why="context bound")
        assert "early" not in got["restart_wanted"] and got["decided"] == "not early: context over its bound"
        await _idle(agent, sid, now)
        first.git = dict(CLEAN)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not first and new.restarts[-1]["why"] == "wanted"
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_pushed_declaration_is_marked_and_its_entry_carries_the_sha(
    agent, composerstubs, tmp_path, monkeypatch
):
    await park_ticks(agent)
    now = datetime.now(UTC)
    monkeypatch.setattr("sessionorc.agent.pushed_since", lambda d, since, timeout=5.0: SHA)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        first = agent.sessions[sid]
        first.created = _iso(now - timedelta(minutes=17))
        async with LocalClient(caller=sid) as w:
            got = await w.call("progress", id=sid, status="restart", why="round pushed")
        assert got["restart_wanted"]["pushed"] == SHA and "early" not in got["restart_wanted"]
        assert got["decided"] == "not early: pushed 0123456 this run"
        await _idle(agent, sid, now)
        first.git = dict(CLEAN)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not first and new.restarts[-1]["pushed"] == SHA
        assert _counted(new.restarts, now) == []
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_nodes_member_reads_no_push(agent, composerstubs, tmp_path, monkeypatch):
    """§4.9a *A pushed commit is new work*: a node's member's worktree is not on the home, so its restart is
    read with no push, and the git read is never run (TD-1941)."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    calls: list[str] = []

    def read(d, since, timeout=5.0):
        calls.append(d)
        return SHA

    monkeypatch.setattr("sessionorc.agent.pushed_since", read)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        first = agent.sessions[sid]
        first.created = _iso(now - timedelta(minutes=17))
        first.host = f"{agent.host}-node"
        # a node's member calls the home over its link as `id@<node>`; the local socket drops a caller's
        # `@host` (identity is the channel's), so the call is let through as its own here
        monkeypatch.setattr(agent, "_is_self", lambda s, caller: s is first)
        async with LocalClient(caller=sid) as w:
            got = await w.call("progress", id=sid, status="restart", why="round pushed")
        assert calls == [], "a node's member's push is never read on the home"
        assert "pushed" not in got["restart_wanted"] and got["restart_wanted"].get("early") is True
        first.host = agent.host
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_the_seventh_pushed_restart_is_the_persons_and_three_counted_trip_first(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        rec = agent.sessions[sid]
        await _idle(agent, sid, now)
        rec.git = dict(CLEAN)
        rec.restart_wanted = {"at": _iso(now), "why": "context bound", "pushed": SHA}
        rec.restarts = [
            {"at": _iso(now - timedelta(minutes=100 - 15 * i)), "why": "wanted", "done": [], "left": [], "pushed": SHA}
            for i in range(RESTART_PUSHED_CEILING)
        ]
        await agent._keep_running(now)
        assert agent.sessions[sid] is rec
        assert rec.restart_ceiling["why"] == "pushed" and rec.restart_ceiling["count"] == RESTART_PUSHED_CEILING
        await agent._keep_running(now + timedelta(minutes=1))
        assert agent.sessions[sid] is rec, "the mark holds while six remain"
        # three counted restarts trip `RESTART_CEILING` first, with no `why`
        rec.restart_ceiling = None
        rec.restarts = [{"at": _iso(now - timedelta(minutes=m)), "why": "crash"} for m in (50, 30, 10)] + rec.restarts
        await agent._keep_running(now)
        assert rec.restart_ceiling == {"at": rec.restart_ceiling["at"], "count": RESTART_CEILING}
        await person.call("kill", id=sid)


# -- the git read (§4.9a, `gitinfo.pushed_since`) ----------------------------------------------------------


def _git(cwd: Path, *args: str, when: str | None = None) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True)
    return out.stdout.strip()


OLD, START, NEW = "2026-11-15T20:00:00Z", "2026-11-15T22:54:00Z", "2026-11-15T23:05:00Z"


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    (seed / "a").write_text("a")
    _git(seed, "add", "a")
    _git(seed, "commit", "-qm", "a", when=OLD)
    _git(tmp_path, "clone", "-q", "--bare", str(seed), "origin.git")
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), "wt")
    wt = tmp_path / "wt"
    _git(wt, "switch", "-q", "-c", "td1-x", "--track", "origin/main")  # a fresh worktree's branch
    return wt


def _commit(wt: Path, name: str, when: str) -> str:
    (wt / name).write_text(name)
    _git(wt, "add", name)
    _git(wt, "commit", "-qm", name, when=when)
    return _git(wt, "rev-parse", "HEAD")


@pytest.mark.unit
def test_pushed_since_reads_the_branchs_own_remote_ref(clone: Path):
    _commit(clone, "b", NEW)
    assert pushed_since(clone, START) is None, "tracking origin/main, no ref of its own"
    _git(clone, "push", "-q", "-u", "origin", "td1-x")
    assert pushed_since(clone, START) == _git(clone, "rev-parse", "HEAD")
    assert pushed_since(clone, "2026-11-16T00:00:00Z") is None  # authored before the record began
    _git(clone, "switch", "-q", "--detach")
    assert pushed_since(clone, START) is None, "a detached HEAD"
    assert pushed_since(clone.parent / "nowhere", START) is None


@pytest.mark.unit
def test_pushed_since_skips_old_authors_merges_and_other_branches(clone: Path):
    _commit(clone, "b", OLD)
    _git(clone, "rebase", "-q", "--committer-date-is-author-date", "origin/main")
    _git(clone, "push", "-q", "-u", "origin", "td1-x")
    assert pushed_since(clone, START) is None, "a rebased branch's author dates are old"
    # a merge of main, made after the start, is not new work
    _git(clone, "switch", "-q", "main")
    _commit(clone, "c", OLD)
    _git(clone, "push", "-q", "origin", "main")
    _git(clone, "switch", "-q", "td1-x")
    _git(clone, "merge", "-q", "--no-ff", "-m", "merge main", "main", when=NEW)
    _git(clone, "push", "-q")
    assert pushed_since(clone, START) is None
    # a commit pushed only to another branch
    _commit(clone, "d", NEW)
    _git(clone, "push", "-q", "origin", "HEAD:refs/heads/elsewhere")
    assert pushed_since(clone, START) is None


# -- the chip and the Inbox row (§4.5a) -------------------------------------------------------------------


@pytest.mark.unit
def test_the_chip_and_the_row_name_the_pushed_count():
    six = [_entry(100 - 15 * i, pushed=SHA) for i in range(6)]
    view = restarted_view(six, NOW)
    assert view["hover"].splitlines()[-1] == "0 of 3 · 6 of 6 pushed in 2 h"
    plain = restarted_view([_entry(10)], NOW)
    assert plain["hover"].splitlines()[-1] == "1 of 3 in 2 h"
    mark = {"at": _iso(NOW), "count": 6, "why": "pushed"}
    assert restarted_view([], NOW, ceiling=mark) is None
    words = "restarts exhausted · 6 in 2 h — pushed restarts counted, it restarted six times in two hours"
    assert pushed_ceiling_words(6) == words
    assert restart_mark({"restart_ceiling": mark, "state": "idle"}) == (mark["at"], words)


@pytest.mark.unit
def test_the_card_slot_names_a_pushed_ceiling(tmp_path, monkeypatch):
    """§4.5 row 5 (b): an exited member at the pushed restarts' ceiling reads the pushed words in the card's slot,
    not the plain ceiling's, and its hover names §4.9a (TD-1941)."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import view

    rec = {
        "id": "ao-w", "name": "w", "kind": "agent", "adapter": "claude-code", "dir": "/r/.claude/worktrees/w",
        "repo": "/r", "state": "exited", "exit_code": 1, "since": "2026-11-15T22:00:00Z", "confidence": "hook",
        "pane": True, "tail": ["done.", "❯ "], "seen_at": "2026-11-15T23:00:00Z", "unattended": True,
        "git": {"branch": "w", "dirty": 1},
    }  # fmt: skip
    pushed = view({**rec, "restart_ceiling": {"at": _iso(NOW), "count": 6, "why": "pushed"}})["slot"]
    assert pushed["text"] == pushed_ceiling_words(6) and pushed["kind"] == "bad"
    assert pushed["full"] == f"{pushed_ceiling_words(6)} (design §4.9a) — it is yours now: Resume it, or Forget it"
    plain = view({**rec, "restart_ceiling": {"at": _iso(NOW), "count": 3}})["slot"]
    assert plain["text"] == "restarts exhausted · 3 in 2 h"
