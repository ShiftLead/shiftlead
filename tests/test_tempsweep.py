"""TD-2123, design §4.6 *The disk sweep*, *tool temp*: build leftovers in `/tmp` and what a tool leaves under its temp
root are aged and removed, and nothing live is. Every root is a fixture; the real `/tmp` is never read.

A change time cannot be set back, so "old" here is a clock four days ahead of the files, and "written recently" a
modification time set just before that clock."""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sessionorc import adapters, cachesweep, diskbook, scratch, tempsweep
from sessionorc.adapters import ExternalSession
from sessionorc.agent import HostAgent
from shiftlead.adapters.claude_code import ClaudeCodeAdapter, munge

pytestmark = pytest.mark.unit

DAY = 86_400
NOW = time.time() + 4 * DAY
TOOL = "claude-code"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(d, *args) -> None:
    subprocess.run(["git", "-C", str(d), *args], env=ENV, check=True, capture_output=True)


@pytest.fixture
def roots(tmp_path):
    tmp, root = tmp_path / "tmp", tmp_path / "tmp" / "claude-1000"
    root.mkdir(parents=True)
    return tmp, root


def ext(cwd="/w/out", tool_id="outside", started: float | None = NOW - 10) -> ExternalSession:
    return ExternalSession(TOOL, str(cwd), "out", tool_id, "idle", started)


def run(tmp, root, *, items=(), blind=(), ours=(), cwds=(), idle=None, transcripts=(), **kw) -> diskbook.Tally:
    tally = diskbook.Tally()
    tempsweep.sweep(
        tmp,
        [(TOOL, root)],
        [Path(t) for t in transcripts],
        tally,
        now=kw.pop("now", NOW),
        idle=idle or (lambda _p: None),
        externals=lambda: {"items": list(items), "blind": list(blind)},
        tool_ids=lambda: set(ours),
        live_cwds=lambda: list(cwds),
        namers=kw.pop("namers", [munge]),
        **kw,
    )
    return tally


def entry(root: Path, name: str = "-w-project") -> Path:
    d = root / name
    d.mkdir()
    (d / "f").write_text("x")
    return d


def written_recently(path: Path) -> None:
    at = NOW - 60
    os.utime(path, (at, at))


def test_what_nothing_holds_goes_and_counts_as_removed_and_adds_nothing_to_held(roots):
    tmp, root = roots
    project, loose = entry(root), root / "loose.txt"
    loose.write_text("xy")
    build, wheel = tmp / "pdm-build-env-1", tmp / "pdm-wheel-cache-2"
    build.mkdir()
    wheel.mkdir()
    (build / "b").write_text("abc")
    other = tmp / "other-dir"  # not a build leftover: outside the temp root, never read
    other.mkdir()
    tally = run(tmp, root)
    assert not project.exists() and not loose.exists() and not build.exists() and not wheel.exists()
    assert other.exists() and root.exists()
    assert tally.removed > 0 and tally.held_gone == 0 and not tally.listed and not tally.unlisted


def test_a_clean_clone_goes_and_one_with_unpushed_work_is_kept(roots, tmp_path):
    tmp, root = roots
    bare = tmp_path / "o.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    git(seed, "checkout", "-q", "-b", "main")
    (seed / "a").write_text("a")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "c")
    git(seed, "push", "-q", "origin", "main")
    clean, worked = root / "clean", root / "worked"
    git(tmp_path, "clone", "-q", str(bare), str(clean))
    git(tmp_path, "clone", "-q", str(bare), str(worked))
    (worked / "b").write_text("b")
    git(worked, "add", "-A")
    git(worked, "commit", "-qm", "only here")
    tally = run(tmp, root)
    assert not clean.exists() and worked.exists()
    assert (str(worked), scratch.GIT_WORK) in tally.kept


def test_a_git_walk_cut_short_keeps_the_clone(roots, monkeypatch):
    tmp, root = roots
    d = entry(root)
    real = scratch._git_dirs

    def cut(path, weigh_tests=True, limit=None):
        return real(path, weigh_tests, time.monotonic() - 1)

    monkeypatch.setattr(scratch, "_git_dirs", cut)
    tally = run(tmp, root)
    assert d.exists() and (str(d), scratch.GIT_WORK) in tally.kept


def test_git_work_past_its_limit_between_stores_is_held(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch, "_git_dirs", lambda *_a: [("clone", tmp_path)])
    monkeypatch.setattr(scratch, "_store_holds", lambda *_a: False)
    assert scratch.git_work(tmp_path, limit=time.monotonic() - 1) is True
    assert scratch.git_work(tmp_path) is False


def test_an_entry_written_within_the_age_is_kept_and_not_named(roots):
    tmp, root = roots
    d, f = entry(root), root / "loose"
    f.write_text("x")
    written_recently(d / "f")
    written_recently(f)
    leftover = tmp / "pdm-build-young"
    leftover.mkdir()
    written_recently(leftover)
    tally = run(tmp, root)
    assert d.exists() and f.exists() and leftover.exists() and not tally.kept


def test_an_old_modification_time_with_a_fresh_change_time_is_kept(roots):
    tmp, root = roots
    d, f = entry(root), root / "moved-in"
    f.write_text("x")
    old = time.time() - 30 * DAY
    for p in (d / "f", d, f):
        os.utime(p, (old, old))
    build = tmp / "pdm-build-copied"
    build.mkdir()
    os.utime(build, (old, old))
    run(tmp, root, now=time.time() + 3600)
    assert d.exists() and f.exists() and build.exists()


def test_an_outside_session_holds_what_was_written_since_it_started_and_no_more(roots):
    tmp, root = roots
    d = entry(root)
    run(tmp, root, items=[ext(started=NOW - 5 * DAY)])  # the entry, four days old, is since its start
    assert d.exists()
    run(tmp, root, items=[ext(started=NOW - 3.5 * DAY)])  # older than its start
    assert not d.exists()


def test_a_managed_session_s_old_start_does_not_extend_the_age(roots):
    tmp, root = roots
    d = entry(root)
    run(tmp, root, items=[ext(tool_id="ours", started=NOW - 9 * DAY)], ours={"ours"})
    assert not d.exists()


def test_an_outside_session_with_no_start_time_keeps_the_root_and_warns(roots, caplog):
    tmp, root = roots
    d, e = entry(root, "a"), entry(root, "b")
    with caplog.at_level(logging.WARNING, logger="sessionorc.tempsweep"):
        run(tmp, root, items=[ext(started=None)])
    assert d.exists() and e.exists()
    assert "no start time" in caplog.text


def test_a_session_working_inside_or_named_by_the_entry_keeps_it(roots):
    tmp, root = roots
    inside = entry(root, "inside")
    tally = run(tmp, root, idle=lambda p: "in use by x" if p == inside else None)
    assert inside.exists() and (str(inside), "in use by x") in tally.kept

    cwd = "/w/live.repo"
    named = entry(root, munge(cwd))
    tally = run(tmp, root, cwds=[cwd])
    assert named.exists() and (str(named), "live session") in tally.kept
    tally = run(tmp, root, items=[ext(cwd=cwd, tool_id="ours")], ours={"ours"})
    assert named.exists()
    run(tmp, root)
    assert not named.exists()


def test_a_cwd_is_named_as_written_and_resolved(roots, tmp_path):
    tmp, root = roots
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    as_written, resolved = entry(root, munge(link)), entry(root, munge(real))
    run(tmp, root, cwds=[str(link)])
    assert as_written.exists() and resolved.exists()


def test_a_name_that_cannot_be_read_keeps_every_entry(roots):
    tmp, root = roots
    d = entry(root)

    def broken(_cwd):
        raise RuntimeError("no")

    run(tmp, root, cwds=["/w/x"], namers=[broken])
    assert d.exists()


@pytest.mark.parametrize("kind", ["symlink", "other-uid"])
def test_a_symlink_or_another_uid_s_entry_is_not_a_candidate(roots, tmp_path, monkeypatch, kind):
    tmp, root = roots
    if kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        p = root / "link"
        p.symlink_to(target)
        leftover = tmp / "pdm-build-link"
        leftover.symlink_to(target)
        run(tmp, root)
        assert p.is_symlink() and leftover.is_symlink() and target.exists()
    else:
        d = entry(root)
        real = os.getuid()
        monkeypatch.setattr(tempsweep.os, "getuid", lambda: real + 1)  # the root is read as another's, too
        tally = run(tmp, root)
        assert d.exists() and tally.unlisted


def test_anything_overlapping_a_transcript_store_is_kept(roots):
    tmp, root = roots
    d = entry(root)
    leftover = tmp / "pdm-build-holds"
    (leftover / "projects").mkdir(parents=True)
    tally = run(tmp, root, transcripts=[d / "f", leftover / "projects"])
    assert d.exists() and leftover.exists()
    assert {(str(d), "transcripts"), (str(leftover), "transcripts")} <= set(tally.kept)


def test_a_session_going_live_between_the_reads_keeps_the_entry(roots):
    tmp, root = roots
    d = entry(root)
    calls = 0

    def idle(_p):
        nonlocal calls
        calls += 1
        return "in use by late" if calls == 2 else None

    run(tmp, root, idle=idle)
    assert d.exists() and calls == 2


def test_an_outside_session_of_no_start_time_appearing_between_the_reads_keeps_the_entry(roots):
    """TD-2149: the second read, just before a removal, finds an outside session with no start time, so the age
    bound is unknown and the entry stays, as the first read would have kept it."""
    tmp, root = roots
    d = entry(root)
    reads = 0

    def externals():
        nonlocal reads
        reads += 1
        return {"items": [ext(started=None)] if reads > 1 else [], "blind": []}

    tally = diskbook.Tally()
    tempsweep.sweep(
        tmp,
        [(TOOL, root)],
        [],
        tally,
        now=NOW,
        idle=lambda _p: None,
        externals=externals,
        tool_ids=set,
        live_cwds=list,
        namers=[munge],
    )
    assert d.exists() and reads == 2 and tally.removed == 0


def test_an_absent_root_removes_nothing_and_leaves_the_reading_whole(tmp_path):
    tally = run(tmp_path / "no-tmp", tmp_path / "no-root")
    assert not tally.unlisted and tally.removed == 0


def test_a_root_that_is_a_symlink_removes_nothing_and_reads_partial(roots, tmp_path):
    tmp, _root = roots
    aimed = tmp_path / "elsewhere"
    d = entry(aimed.parent, aimed.name)
    link = tmp / "claude-link"
    link.symlink_to(d)
    tally = run(tmp, link)
    assert (d / "f").exists() and tally.unlisted


def test_a_dry_run_removes_nothing_counts_it_and_reads_partial_past_its_deadline(roots):
    tmp, root = roots
    d = entry(root)
    tally = run(tmp, root, dry=True)
    assert d.exists() and tally.removed > 0 and str(d) in tally.gone_paths
    tally = run(tmp, root, dry=True, deadline=time.monotonic() - 1)
    assert d.exists() and tally.unlisted and tally.removed == 0


def test_a_real_pass_past_its_budget_stops_and_the_next_takes_the_rest(roots, monkeypatch):
    tmp, root = roots
    d = entry(root)
    monkeypatch.setattr(tempsweep, "TOOL_TEMP_BUDGET_S", -1.0)
    tally = run(tmp, root)
    assert d.exists() and not tally.unlisted
    monkeypatch.setattr(tempsweep, "TOOL_TEMP_BUDGET_S", 60.0)
    run(tmp, root)
    assert not d.exists()


def test_at_most_twenty_kept_paths_are_named(roots):
    tmp, root = roots
    for n in range(tempsweep.MAX_KEPT + 3):
        entry(root, f"e{n}")
    tally = run(tmp, root, idle=lambda _p: "in use")
    assert len(tally.kept) == tempsweep.MAX_KEPT


@pytest.mark.parametrize("is_dir", [True, False])
def test_a_failed_removal_leaves_the_parent_s_mode_and_is_tried_again(roots, is_dir):
    tmp, root = roots
    if is_dir:
        p = entry(root)
    else:
        p = root / "loose"
        p.write_text("x")
    os.chmod(root, 0o500)
    try:
        tally = run(tmp, root)
        assert p.exists() and tally.removed == 0
        assert root.stat().st_mode & 0o777 == 0o500
    finally:
        os.chmod(root, 0o700)
    run(tmp, root)
    assert not p.exists()


def test_a_read_only_tree_is_removed_with_its_parent_left_alone(roots):
    tmp, root = roots
    d = entry(root)
    os.chmod(d, 0o500)
    before = root.stat().st_mode
    run(tmp, root)
    assert not d.exists() and root.stat().st_mode == before


def _agent(calls):
    return SimpleNamespace(sessions={}, host="here", _tool_ids=set, _reap_idle=lambda *_a: None, calls=calls)


def test_a_scratch_home_s_agent_runs_neither_part(monkeypatch):
    calls = []
    monkeypatch.setattr(cachesweep, "default_home", lambda: False)
    monkeypatch.setattr(tempsweep, "sweep", lambda *a, **k: calls.append(a))
    HostAgent._sweep_tool_temp(_agent(calls), diskbook.Tally())
    assert not calls


def test_an_adapter_that_cannot_name_its_stores_stops_the_rule(monkeypatch):
    calls = []
    monkeypatch.setattr(cachesweep, "default_home", lambda: True)
    monkeypatch.setattr(adapters, "transcript_roots", lambda: ([], ["broken"]))
    monkeypatch.setattr(tempsweep, "sweep", lambda *a, **k: calls.append(a))
    tally = diskbook.Tally()
    HostAgent._sweep_tool_temp(_agent(calls), tally)
    assert not calls and tally.unlisted


def test_the_default_home_s_agent_runs_it_on_the_real_tmp(monkeypatch):
    calls = []
    monkeypatch.setattr(cachesweep, "default_home", lambda: True)
    monkeypatch.setattr(adapters, "transcript_roots", lambda: ([], []))
    monkeypatch.setattr(tempsweep, "sweep", lambda *a, **k: calls.append((a, k)))
    HostAgent._sweep_tool_temp(_agent(calls), diskbook.Tally(), dry=True, deadline=5.0)
    ((args, kw),) = calls
    assert args[0] == Path("/tmp") and kw["dry"] is True and kw["deadline"] == 5.0


def test_claude_code_names_its_root_and_entry():
    ad = ClaudeCodeAdapter()
    assert ad.temp_roots() == [Path(f"/tmp/claude-{os.getuid()}")]
    assert ad.temp_entry(Path("/home/me/a.b")) == "-home-me-a-b"


def test_the_registry_s_start_is_read_in_seconds_and_none_where_absent(tmp_path, monkeypatch):
    """The entry's shape is copied from a real `sessions/<pid>.json`: `startedAt` in epoch milliseconds."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(f"profiles:\n  t: {{config_dir: {tmp_path}}}\n")
    (tmp_path / "sessions").mkdir()
    me = os.getpid()
    text = Path(f"/proc/{me}/stat").read_text()
    start = text[text.rindex(")") + 2 :].split()[19]
    base = {"pid": me, "procStart": start, "kind": "interactive", "entrypoint": "cli", "status": "idle"}
    for name, extra in (("a", {"startedAt": 1795452350537}), ("b", {}), ("c", {"startedAt": "soon"})):
        (tmp_path / "sessions" / f"{name}.json").write_text(
            json.dumps({**base, "sessionId": name, "cwd": f"/w/{name}", "name": name, **extra})
        )
    got = {e.tool_id: e.started for e in ClaudeCodeAdapter().external_sessions()}
    assert got == {"a": pytest.approx(1795452350.537), "b": None, "c": None}


def test_another_uid_s_entry_is_no_candidate():
    st = SimpleNamespace(st_uid=os.getuid() + 1, st_mode=stat.S_IFDIR | 0o700)
    assert tempsweep._candidate(SimpleNamespace(stat=lambda follow_symlinks: st)) is None
