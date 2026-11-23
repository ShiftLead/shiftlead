"""The disk sweep's *home files* rule (design §4.6 *The disk sweep*, TD-2115): status-line, start-context and launch
files past `runs_keep_days` that no record names go, one a record names in any state stays, and a launch record is
never read."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import park_ticks

from sessionorc import agent as agent_mod
from sessionorc import diskbook, homesweep, hosts, paths
from sessionorc.models import NODE_OWNED, SAME_SESSION, Session

DAY = 86400


def rec(id: str = "x", adapter_id: str | None = None, context_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=id, adapter_id=adapter_id, context_id=context_id)


def put(home: Path, rel: str, days: float = 30, body: str = "x") -> Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    at = time.time() - days * DAY
    os.utime(p, (at, at))
    return p


def run(home: Path, records: list, keep: int = 14, dry: bool = False) -> diskbook.Tally:
    t = diskbook.Tally()
    homesweep.sweep(home, keep, time.time(), lambda: list(records), t, dry=dry)
    return t


FOUR = ("statusline/a.json", "statusline/context/c.json", "launch/c.context.md", "launch/a.sh")


@pytest.mark.unit
def test_each_kind_past_the_age_with_no_record_goes(tmp_path):
    files = [put(tmp_path, r) for r in FOUR]
    t = run(tmp_path, [])
    assert not any(f.exists() for f in files)
    assert set(t.gone_paths) == {str(f) for f in files}


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel, holder",
    [
        ("statusline/a.json", rec("a")),
        ("statusline/context/c.json", rec(adapter_id="c")),
        ("launch/c.context.md", rec(adapter_id="c")),
        ("launch/c.context.md", rec(adapter_id="new", context_id="c")),  # a cleared session's old file
        ("launch/a.sh", rec("a")),
    ],
)
def test_one_a_record_names_is_kept_and_says_why(tmp_path, rel, holder):
    f = put(tmp_path, rel)
    t = run(tmp_path, [holder])
    assert f.exists()
    assert t.kept == [(str(f), "live record")]


@pytest.mark.unit
def test_a_young_file_and_keep_days_zero_remove_nothing(tmp_path):
    young = put(tmp_path, "statusline/y.json", days=1)
    assert run(tmp_path, []).kept == [] and young.exists()
    old = [put(tmp_path, r) for r in FOUR]
    t = run(tmp_path, [], keep=0)
    assert all(f.exists() for f in old) and t.removed == 0
    assert str(old[0]) in t.listed  # still held in the book


@pytest.mark.unit
def test_a_dead_writer_s_tmp_goes_whatever_the_records_say(tmp_path):
    tmp = put(tmp_path, "statusline/a.123.tmp")
    ctx = put(tmp_path, "statusline/context/c.123.tmp")
    fresh = put(tmp_path, "statusline/b.456.tmp", days=1)
    run(tmp_path, [rec("a"), rec(adapter_id="c")])
    assert not tmp.exists() and not ctx.exists() and fresh.exists()


@pytest.mark.unit
def test_a_launch_record_and_any_other_name_is_never_read(tmp_path):
    kept = [put(tmp_path, "launch/a@node.json"), put(tmp_path, "launch/a.json"), put(tmp_path, "launch/other.txt")]
    t = run(tmp_path, [])
    assert all(f.exists() for f in kept)
    assert not t.listed


@pytest.mark.unit
def test_a_dry_run_removes_nothing_and_counts_what_it_would(tmp_path):
    files = [put(tmp_path, r, body="12345") for r in FOUR]
    t = run(tmp_path, [], dry=True)
    assert all(f.exists() for f in files)
    assert t.removed == 20 and set(t.gone_paths) == {str(f) for f in files}


@pytest.mark.unit
def test_a_record_made_or_a_file_rewritten_after_the_weigh_keeps_it(tmp_path):
    made = put(tmp_path, "statusline/a.json")
    records: list = []
    reads = 0

    def later() -> list:
        nonlocal reads
        reads += 1
        return [rec("a")] if reads > 1 else list(records)

    t = diskbook.Tally()
    homesweep.sweep(tmp_path, 14, time.time(), later, t)
    assert made.exists() and t.kept == [(str(made), "live record")]

    rewritten = put(tmp_path, "launch/b.sh")
    t = diskbook.Tally()
    t.measure(rewritten, 1)
    os.utime(rewritten)
    homesweep._remove(str(rewritten), time.time() - 14 * DAY, lambda: False, t, False)
    assert rewritten.exists()


@pytest.mark.unit
def test_a_symlink_is_removed_as_a_link_and_its_target_stays(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("keep")
    link = tmp_path / "statusline" / "gone.json"
    link.parent.mkdir()
    link.symlink_to(target)
    at = time.time() - 30 * DAY
    os.utime(link, (at, at), follow_symlinks=False)
    run(tmp_path, [])
    assert not link.is_symlink() and target.read_text() == "keep"


@pytest.mark.unit
def test_context_id_is_the_node_s_and_no_ground_for_refusing_a_copy():
    assert "context_id" in NODE_OWNED and "context_id" not in SAME_SESSION
    s = Session(id="a", name="a", kind="interactive", adapter="shell", dir="/d", adapter_id="n", context_id="o")
    assert Session.from_dict(s.to_dict()).context_id == "o"


@pytest.mark.unit
def test_a_resume_refreshes_a_kept_file_and_reads_a_missing_one_as_gone(tmp_path):
    f = put(tmp_path, "launch/c.context.md")
    before = f.stat().st_mtime
    assert agent_mod._keep_file(f) and f.stat().st_mtime > before
    assert not agent_mod._keep_file(tmp_path / "launch" / "none.context.md")


async def test_a_forget_keeps_a_file_a_cleared_session_still_names(agent):
    await park_ticks(agent)
    file = paths.context_file("old")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("brief")
    base = {"kind": "interactive", "adapter": "shell", "dir": "/d"}
    cleared = Session(id="cleared", name="cleared", adapter_id="new", context_id="old", **base)
    other = Session(id="other", name="other", adapter_id="old", **base)
    agent.sessions.update(cleared=cleared, other=other)
    agent._forget("other")
    assert file.exists()
    agent._forget("cleared")
    assert not file.exists()


async def test_the_pass_counts_the_home_kind_and_the_dry_run_names_it(agent):
    await park_ticks(agent)
    f = put(paths.home(), "statusline/nobody.json")
    dry = await agent.rpc_disk_dry_run()
    entry = dry if "kinds" in dry else dry[agent.host]
    assert [g["path"] for g in entry["kinds"]["home"]["would_remove"]] == [str(f)]
    assert f.exists()
    tallied = agent._prune_runs(datetime.now(UTC), set())
    assert not f.exists() and tallied["home"]["removed"] == 1
    assert hosts.local_host().runs_keep_days > 0
