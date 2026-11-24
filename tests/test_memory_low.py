"""TD-2136, design §4.6 *Told when memory runs short*, *The process reading*, §4.5a *Inbox row: memory low*: two
readings under 10% raise one row and one message naming the three largest holders, one reading does not, a restart
neither repeats nor ends it, and the first reading over 20% clears it. `/proc/meminfo`, the cgroup files and
`/proc/<pid>` are stubbed under a temporary directory; nothing on this machine is read or signalled."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sessionorc import diskbook, memory, notify, scratch
from sessionorc import settings as settings_mod
from sessionorc.store import HostStore
from shiftlead import cli

GIB = 1024**3
MIB = 1024**2


def _z(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


# -- the reading ----------------------------------------------------------------------------------------------------


def _meminfo(root: Path, total=8 * GIB, avail=4 * GIB, swap_total=2 * GIB, swap_free=GIB) -> None:
    root.mkdir(parents=True, exist_ok=True)
    kb = lambda n: f"{n // 1024} kB"  # noqa: E731
    lines = [f"MemTotal:       {kb(total)}", f"MemFree:        {kb(avail // 2)}", f"MemAvailable:   {kb(avail)}"]
    lines += [f"SwapTotal:      {kb(swap_total)}", f"SwapFree:       {kb(swap_free)}"]
    (root / "meminfo").write_text("\n".join(lines) + "\n")


def _cgroup(proc: Path, cg: Path, rel: str, files: dict[str, dict[str, str]]) -> None:
    (proc / "self").mkdir(parents=True, exist_ok=True)
    (proc / "self" / "cgroup").write_text(f"0::{rel}\n")
    for where, got in files.items():
        d = cg / where.lstrip("/")
        d.mkdir(parents=True, exist_ok=True)
        for name, text in got.items():
            (d / name).write_text(text)


@pytest.mark.unit
def test_the_machine_reads_both_halves_and_no_swap_reads_ram_alone(tmp_path):
    proc, cg = tmp_path / "proc", tmp_path / "cg"
    _meminfo(proc, total=8 * GIB, avail=2 * GIB, swap_total=2 * GIB, swap_free=GIB // 2)
    assert memory.read_halves(proc, cg) == {"ram": 0.25, "swap": 0.25}
    _meminfo(proc, swap_total=0, swap_free=0)
    assert memory.read_halves(proc, cg) == {"ram": 0.5}, "a host with no swap reads RAM alone"
    assert memory.read_halves(tmp_path / "none", cg) is None, "no readable /proc/meminfo is no reading"


@pytest.mark.unit
def test_a_limit_on_the_cgroup_or_a_parent_is_the_total_and_swap_is_left_out(tmp_path):
    proc, cg = tmp_path / "proc", tmp_path / "cg"
    _meminfo(proc, total=8 * GIB, avail=6 * GIB)
    stat = f"anon 1\ninactive_file {GIB // 4}\n"
    _cgroup(
        proc,
        cg,
        "/a/b",
        {
            "/a/b": {"memory.max": "max"},
            "/a": {"memory.max": str(GIB), "memory.current": str(GIB), "memory.stat": stat},
        },
    )
    assert memory.read_halves(proc, cg) == {"ram": 0.25}, "the parent's limit: 1 GiB less 1 GiB used plus 0.25 inactive"
    _cgroup(proc, cg, "/a/b", {"/a/b": {"memory.max": str(2 * GIB), "memory.current": str(GIB), "memory.stat": ""}})
    assert memory.read_halves(proc, cg) == {"ram": 0.25}, "the lowest limit on the path is the total"


@pytest.mark.unit
def test_a_limit_at_or_over_memtotal_or_cgroup_v1_reads_the_machine(tmp_path):
    proc, cg = tmp_path / "proc", tmp_path / "cg"
    _meminfo(proc, total=8 * GIB, avail=4 * GIB, swap_total=2 * GIB, swap_free=GIB)
    _cgroup(proc, cg, "/a", {"/a": {"memory.max": str(8 * GIB), "memory.current": str(7 * GIB)}})
    assert memory.read_halves(proc, cg) == {"ram": 0.5, "swap": 0.5}
    (proc / "self" / "cgroup").write_text("4:memory:/a\n")
    assert memory.read_halves(proc, cg) == {"ram": 0.5, "swap": 0.5}, "a cgroup v1 node reads as the machine"


# -- each half's state ----------------------------------------------------------------------------------------------


def _held(watch, state, halves, walk="idle", now="T"):
    return watch.step(state, halves, now, walk)


HOLD = {"ram": [{"name": "python", "bytes": 3 * GIB}], "swap": [{"name": "node", "bytes": GIB}], "cut": False}


@pytest.mark.unit
def test_two_readings_under_the_line_turn_a_half_and_its_walk_writes_it_low():
    w = memory.Watch()
    state, start = _held(w, {}, {"ram": 0.05})
    assert state == {} and not start, "one reading does not"
    state, start = _held(w, state, {"ram": 0.05})
    assert state == {} and start and w.turning == {"ram": 0.05}, "turning, and no row before its walk returns"
    state = w.walked(state, HOLD, {"ram"}, "T1")
    assert state == {"ram": {"low": True, "since": "T1", "share_free": 0.05, "holders": HOLD["ram"], "cut": False}}
    again, start = _held(w, state, {"ram": 0.04})
    assert again == state and not start, "still low: nothing repeated, no second walk"


@pytest.mark.unit
@pytest.mark.parametrize("share", [0.10, 0.15, 0.20])
def test_between_the_lines_a_low_half_stays_and_a_run_of_two_breaks(share):
    w = memory.Watch()
    low = {"ram": {"low": True, "since": "T", "share_free": 0.05, "holders": [], "cut": False}}
    assert _held(w, low, {"ram": share})[0] == low
    _held(w, {}, {"ram": 0.05})
    _held(w, {}, {"ram": share})
    state, start = _held(w, {}, {"ram": 0.05})
    assert state == {} and not start and not w.turning, "a reading between the lines broke the run"


@pytest.mark.unit
def test_the_first_reading_over_twenty_percent_ends_it_turning_or_low():
    w = memory.Watch()
    low = {"ram": {"low": True, "since": "T"}}
    assert _held(w, low, {"ram": 0.21})[0] == {}
    _held(w, {}, {"swap": 0.0})
    _held(w, {}, {"swap": 0.0})
    assert w.turning
    _held(w, {}, {"swap": 0.5})
    assert not w.turning
    assert w.walked({}, HOLD, {"swap"}, "T") == {}, "recovery before the walk returns writes no low"


@pytest.mark.unit
def test_a_restart_forgets_an_unfinished_count_but_keeps_a_low_half():
    w = memory.Watch()
    _held(w, {}, {"ram": 0.05})
    w = memory.Watch()  # a restart
    state, start = _held(w, {}, {"ram": 0.05})
    assert not start, "two new readings start again"
    low = {"ram": {"low": True, "since": "T"}}
    assert _held(memory.Watch(), low, {"ram": 0.05}) == (low, False), "a low half is neither ended nor repeated"


@pytest.mark.unit
def test_a_half_the_reading_lacks_is_ended_and_no_reading_changes_nothing():
    w = memory.Watch()
    low = {"ram": {"low": True}, "swap": {"low": True}}
    assert _held(w, low, None)[0] == low
    assert _held(w, low, {"ram": 0.05})[0] == {"ram": {"low": True}}, "swap turned off, or a limit set"


@pytest.mark.unit
def test_a_half_turning_during_a_walk_waits_for_the_next():
    w = memory.Watch()
    _held(w, {}, {"ram": 0.05}, walk="running")
    state, start = _held(w, {}, {"ram": 0.05}, walk="running")
    assert w.turning and not start, "one walk at a time"
    state = w.walked(state, HOLD, set(), "T")
    assert state == {} and w.turning == {"ram": 0.05}, "that walk did not start for it: the next does"
    assert w.walked(state, HOLD, {"ram"}, "T2")["ram"]["low"] is True


@pytest.mark.unit
def test_a_failed_walk_is_cut_with_no_holders_and_a_stuck_one_writes_a_turning_half_low():
    w = memory.Watch()
    _held(w, {}, {"swap": 0.05})
    _held(w, {}, {"swap": 0.05})
    got = w.walked({}, None, {"swap"}, "T")
    assert got == {"swap": {"low": True, "since": "T", "share_free": 0.05, "holders": [], "cut": True}}
    w = memory.Watch()
    _held(w, {}, {"ram": 0.05}, walk="stuck")
    state, start = _held(w, {}, {"ram": 0.05}, walk="stuck")
    assert state == {"ram": {"low": True, "since": "T", "share_free": 0.05, "holders": [], "cut": True}}
    assert not start and not w.turning


@pytest.mark.unit
def test_a_walk_refreshes_the_holders_of_a_half_already_low():
    w = memory.Watch()
    low = {"swap": {"low": True, "since": "T", "share_free": 0.0, "holders": [], "cut": True}}
    got = w.walked(low, HOLD, set(), "T9")
    assert got["swap"] == {"low": True, "since": "T", "share_free": 0.0, "holders": HOLD["swap"], "cut": False}
    assert w.walked(low, None, set(), "T9") == low, "a walk that raised changes no figures"


@pytest.mark.unit
def test_a_full_swap_with_free_ram_turns_swap_alone():
    w = memory.Watch()
    for _ in range(2):
        state, start = _held(w, {}, {"ram": 0.6, "swap": 0.0})
    assert list(w.turning) == ["swap"]
    state = w.walked(state, HOLD, {"swap"}, "T")
    assert list(state) == ["swap"]
    for _ in range(2):
        state, start = _held(w, state, {"ram": 0.05, "swap": 0.0})
    assert list(w.turning) == ["ram"] and start, "RAM turning under a standing swap row is its own"


# -- the process reading --------------------------------------------------------------------------------------------


def _proc(
    root: Path, pid: int, ppid: int, name: str, start_ticks: int, *, env=None, pss=None, swap=0, rss=None, vswap=0
):
    d = root / str(pid)
    d.mkdir(parents=True)
    rest = ["S", str(ppid)] + ["0"] * 17 + [str(start_ticks)] + ["0"] * 10
    (d / "stat").write_text(f"{pid} ({name}) {' '.join(rest)}\n")
    (d / "comm").write_text(name + "\n")
    (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in (env or {}).items()) + b"\0")
    if pss is not None:
        (d / "smaps_rollup").write_text(f"Rss: 1 kB\nPss:  {pss // 1024} kB\nSwapPss: {swap // 1024} kB\n")
    (d / "status").write_text(f"Name: {name}\nVmRSS: {(rss or 0) // 1024} kB\nVmSwap: {vswap // 1024} kB\n")
    return d


def _boot(root: Path, btime: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "stat").write_text(f"cpu 1 2 3\nbtime {btime}\n")


@pytest.mark.unit
def test_holders_sum_by_name_group_a_live_run_and_fall_back_to_status(tmp_path):
    proc, home = tmp_path / "proc", tmp_path / "home"
    home.mkdir()
    tick = os.sysconf("SC_CLK_TCK")
    btime = 1_000_000
    created = btime + 1000
    live = {"ao-x-w": ("worker", float(created))}
    early = (1000 - 5) * tick  # five seconds before the record's `created`: still its run
    _boot(proc, btime)
    env = {"SHIFTLEAD_SESSION": "ao-x-w", "SHIFTLEAD_HOME": str(home), "SECRET": "never read"}
    _proc(proc, 10, 1, "claude", early, env=env, pss=GIB, swap=10 * MIB)
    _proc(proc, 11, 10, "pytest", early + 100, pss=GIB, swap=10 * MIB)  # a descendant, no variables of its own
    _proc(proc, 20, 1, "python", 5, pss=300 * MIB, swap=500 * MIB)
    _proc(proc, 21, 1, "python", 5, pss=300 * MIB, swap=500 * MIB)
    _proc(proc, 30, 1, "node", 5, rss=100 * MIB, vswap=2 * GIB)  # no smaps_rollup: `status`
    _proc(proc, 40, 1, "tiny", 5, pss=MIB)
    procs, cut = memory.walk(proc)
    assert not cut and sorted(p.pid for p in procs) == [10, 11, 20, 21, 30, 40]
    assert next(p for p in procs if p.pid == 10).session == "ao-x-w"
    got = memory.holders(procs, live, home)
    assert got["ram"] == [
        {"name": "worker", "bytes": 2 * GIB},
        {"name": "python", "bytes": 600 * MIB},
        {"name": "node", "bytes": 100 * MIB},
    ], "ram ranks by Pss, three at most"
    assert got["swap"] == [
        {"name": "node", "bytes": 2 * GIB},
        {"name": "python", "bytes": 1000 * MIB},
        {"name": "worker", "bytes": 20 * MIB},
    ], "swap ranks by SwapPss"
    other = memory.holders(procs, live, tmp_path / "elsewhere")
    assert "worker" not in [h["name"] for h in other["ram"]], "another home's session id is not this home's run"
    late = {"ao-x-w": ("worker", float(created + scratch.LEFT_SLACK + 60))}
    assert "worker" not in [h["name"] for h in memory.holders(procs, late, home)["ram"]], "started before the run"


@pytest.mark.unit
def test_a_reused_pid_another_users_process_and_a_cut_walk(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    _boot(proc, 1)
    d = _proc(proc, 7, 1, "reused", 50, pss=GIB)
    _proc(proc, 8, 1, "kept", 50, pss=GIB)
    reads = {"n": 0}
    real = memory._stat

    def moving(path):
        got = real(path)
        if path == d:
            reads["n"] += 1
            return got[0], got[1] + reads["n"]  # the start time changed between the two reads
        return got

    monkeypatch.setattr(memory, "_stat", moving)
    procs, cut = memory.walk(proc)
    assert [p.name for p in procs] == ["kept"] and not cut
    assert memory.walk(proc, uid=os.getuid() + 1) == ([], False), "only this user's processes"
    assert memory.walk(proc, limit_s=-1)[1] is True, "a walk cut at its bound is marked cut"


@pytest.mark.unit
def test_nothing_here_signals_a_process():
    src = Path(memory.__file__).read_text()
    assert "kill" not in src and "signal" not in src.replace("signals a process", "")


# -- the words ------------------------------------------------------------------------------------------------------

HOLDERS = [{"name": "worker", "bytes": 3 * GIB}, {"name": "python", "bytes": 512 * MIB}, {"name": "x", "bytes": 1}]


@pytest.mark.unit
def test_the_words_name_the_host_half_share_and_holders():
    spell = {"host": "kmaster", "half": "ram", "share_free": 0.079, "holders": HOLDERS}
    want = "kmaster memory low: 7% free. Your largest: worker (3.0 GB), python (512.0 MB), x (1 B)"
    assert notify.memory_low_text(spell) == want and notify.memory_low_line(spell) == f"shiftlead · {want}"
    cut = {"host": "n1", "half": "swap", "share_free": 0.0, "holders": HOLDERS[:1], "cut": True}
    assert notify.memory_low_text(cut) == "n1 swap low: 0% free. Your largest: worker (at least 3.0 GB)"
    assert notify.memory_low_text({"host": "h", "half": "swap", "holders": []}) == "h swap low", "no holder, no list"


@pytest.mark.unit
def test_ao_disk_prints_each_half_and_no_memory_reading():
    entry = {"at": None, "kinds": {}, "free": {}}
    entry["memory"] = {
        "ram": {"low": True, "share_free": 0.05, "since": "T", "holders": HOLDERS[:1], "cut": False},
        "swap": {"low": False, "share_free": 0.9},
    }
    lines = cli.disk_lines({"h": entry})
    assert "  memory: ram 5% free, swap 90% free" in lines
    assert "  ⚠ h memory low: 5% free. Your largest: worker (3.0 GB) (since T)" in lines
    assert "  no memory reading" in cli.disk_lines({"h": {"at": None, "kinds": {}, "free": {}, "no_memory": True}})


# -- the home's spells ----------------------------------------------------------------------------------------------


def _answer(**halves):
    return {"memory": {h: {"low": share < 0.1, "share_free": share, "holders": HOLDERS} for h, share in halves.items()}}


@pytest.mark.unit
def test_the_home_keeps_a_spell_per_host_and_half():
    got = diskbook.memory_spells({}, {"n": _answer(ram=0.05, swap=0.5)}, "T0")
    assert list(got) == ["n:ram"] and got["n:ram"]["since"] == "T0" and got["n:ram"]["half"] == "ram"
    assert diskbook.memory_spells(got, {"n": _answer(ram=0.04)}, "T1")["n:ram"]["since"] == "T0", "told once"
    assert diskbook.memory_spells(got, {"n": _answer(ram=0.5)}, "T1") == {}, "low false ends it"
    assert diskbook.memory_spells(got, {"n": {"memory": {}}}, "T1") == {}, "a memory field without the half ends it"
    assert diskbook.memory_spells(got, {"n": {"error": "down"}}, "T1") == got, "a node that does not answer keeps it"
    assert diskbook.memory_spells(got, {"n": {"kinds": {}}}, "T1") == got, "an answer lacking memory keeps it"
    assert diskbook.memory_spells(got, {"h": _answer(ram=0.5)}, "T1") == {}, "a host no longer asked has none"


@pytest.mark.unit
def test_the_host_record_and_disk_json_keep_the_state(tmp_path):
    store = HostStore(tmp_path / "host.json")
    store.save({"teams": {}, "memory_low": {"h:ram": {"host": "h", "since": "T"}, "bad": 1}})
    assert store.load()["memory_low"] == {"h:ram": {"host": "h", "since": "T"}}
    diskbook.set_memory(tmp_path, "h", {"ram": {"low": True, "since": "T"}})
    diskbook.write(tmp_path, "h", {}, {}, "S", datetime.now(UTC))
    assert diskbook.memory_state(tmp_path) == {"ram": {"low": True, "since": "T"}}, "the hourly rewrite carries it"


# -- the host and the home, end to end ------------------------------------------------------------------------------


@pytest.fixture
def mem(agent, monkeypatch):
    """The agent's reading stubbed through `level`, and its walk through `walks`."""
    level: dict = {"halves": {"ram": 0.5, "swap": 0.9}}
    walks: list = []

    def walk(live, home, *a, **k):
        walks.append(live)
        return {"ram": HOLDERS, "swap": HOLDERS[:1], "cut": False}

    monkeypatch.setattr(memory, "read_halves", lambda *a, **k: level["halves"])
    monkeypatch.setattr(memory, "read_holders", walk)
    return level, walks


async def _read(agent, halves, level) -> None:
    level["halves"] = halves
    await agent._memory_pass()
    if agent._walk_task is not None:
        await agent._walk_task
    await agent._disk_low_pass()


@pytest.mark.integration
async def test_a_low_half_is_one_spell_from_its_second_reading_to_clear(agent, mem):
    level, walks = mem
    await _read(agent, {"ram": 0.05, "swap": 0.9}, level)
    assert "memory_low" not in agent._host_rec and walks == [], "one reading does not"
    await _read(agent, {"ram": 0.05, "swap": 0.9}, level)
    key = f"{agent.host}:ram"
    spell = agent._host_rec["memory_low"][key]
    assert spell["holders"] == HOLDERS and len(walks) == 1
    await _read(agent, {"ram": 0.15, "swap": 0.9}, level)
    assert agent._host_rec["memory_low"][key]["since"] == spell["since"] and len(walks) == 1
    assert (await agent.rpc_host())["memory_low"][key]["since"] == spell["since"]
    agent._memory_watch = memory.Watch()  # a restart
    await _read(agent, {"ram": 0.05, "swap": 0.9}, level)
    assert agent._host_rec["memory_low"][key]["since"] == spell["since"] and len(walks) == 1, "neither repeats nor ends"
    await _read(agent, {"ram": 0.25, "swap": 0.9}, level)
    assert "memory_low" not in agent._host_rec and (await agent.rpc_host())["memory_low"] == {}


@pytest.mark.integration
async def test_the_walk_reads_a_snapshot_of_the_live_records(agent, mem):
    level, walks = mem
    agent.sessions["ao-x-w"] = SimpleNamespace(
        id="ao-x-w", name="worker", state="working", created=_z(datetime.now(UTC))
    )
    agent.sessions["ao-x-old"] = SimpleNamespace(
        id="ao-x-old", name="old", state="exited", created=_z(datetime.now(UTC))
    )
    try:
        await _read(agent, {"ram": 0.05}, level)
        await _read(agent, {"ram": 0.05}, level)
    finally:
        agent.sessions.pop("ao-x-w")
        agent.sessions.pop("ao-x-old")
    assert list(walks[0]) == ["ao-x-w"] and walks[0]["ao-x-w"][0] == "worker"


@pytest.mark.integration
async def test_a_hung_walk_is_cut_and_no_second_walk_overlaps_it(agent, monkeypatch):
    level = {"halves": {"ram": 0.05}}
    release = threading.Event()
    started: list[int] = []

    def hang(*_a, **_k):
        started.append(1)
        release.wait(10)
        return {"ram": HOLDERS, "swap": [], "cut": False}

    monkeypatch.setattr(memory, "read_halves", lambda *a, **k: level["halves"])
    monkeypatch.setattr(memory, "read_holders", hang)
    try:
        await agent._memory_pass()
        await agent._memory_pass()
        assert len(started) <= 1 and agent._walk_state() == "running"
        agent._walk_started = time.monotonic() - 3 * scratch.LEFT_WALK_S
        agent._walk_at = time.monotonic() - 2 * scratch.LEFT_EVERY  # a periodic walk is due too
        await agent._memory_pass()
        got = diskbook.memory_state(os.environ["SHIFTLEAD_HOME"])
        assert got["ram"]["holders"] == [] and got["ram"]["cut"] is True, "written low, cut, with no holders"
        assert len(started) == 1, "no other walk starts until its thread returns"
    finally:
        release.set()
        await agent._walk_task
    assert diskbook.memory_state(os.environ["SHIFTLEAD_HOME"])["ram"]["holders"] == [], "its late result is not applied"


@pytest.fixture
def sent(agent, monkeypatch):
    got: list[tuple[str, str]] = []

    async def record(secrets: str, text: str) -> str | None:
        got.append((secrets, text))
        return None

    monkeypatch.setattr(agent, "_notify_run", record)
    settings_mod.save({"notify": {"telegram": {"on": True, "secrets": "samscrape/prd", "link": "http://kmaster:8765"}}})
    return got


async def _tell(agent, now: datetime) -> None:
    agent._notify_pass(now)
    for _ in range(20):  # the send is a detached task
        if not agent._bg:
            break
        await asyncio.sleep(0.01)


def _spell(half: str, since: datetime) -> dict:
    share = 0.0 if half == "swap" else 0.05
    return {
        "host": "kmaster",
        "half": half,
        "since": _z(since),
        "share_free": share,
        "holders": HOLDERS[:1],
        "cut": False,
    }


@pytest.mark.integration
async def test_a_spell_is_told_once_and_ram_under_a_snoozed_swap_row_is_told(agent, sent):
    t0 = datetime.now(UTC)
    agent._host_rec["memory_low"] = {"kmaster:swap": _spell("swap", t0)}
    await agent.rpc_attention_snooze("memory_low:kmaster:swap", "memory_low", _z(t0 + timedelta(days=1)))
    await _tell(agent, t0 + timedelta(seconds=61))
    assert sent == [], "a snoozed row is not told"
    agent._host_rec["memory_low"]["kmaster:ram"] = _spell("ram", t0 + timedelta(seconds=62))
    await _tell(agent, t0 + timedelta(seconds=130))
    await _tell(agent, t0 + timedelta(seconds=200))
    assert sent == [
        (
            "samscrape/prd",
            "shiftlead · kmaster memory low: 5% free. Your largest: worker (3.0 GB)\n"
            "http://kmaster:8765/inbox?row=memory_low%3Akmaster%3Aram",
        )
    ]


# -- the row --------------------------------------------------------------------------------------------------------


def _spells() -> dict:
    return {"kmaster:ram": _spell("ram", datetime.now(UTC) - timedelta(hours=1))}


@pytest.mark.unit
def test_the_row_is_counted_under_needs_you_and_snoozed_by_its_key():
    from shiftlead.ui.app import inbox_sections, memory_low_rows

    rows = memory_low_rows(_spells())
    assert rows[0]["subject"] == "Memory" and rows[0]["sid"] == "memory_low:kmaster:ram"
    s = inbox_sections([], states=rows)
    assert [e["row"] for e in s["needs"]] == ["memory_low"] and s["count"] == 1
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    s = inbox_sections([], states=rows, attention_snoozed={"memory_low:kmaster:ram|memory_low": until})
    assert s["needs"] == [] and [e["row"] for e in s["snoozed"]] == ["memory_low"]
    assert memory_low_rows(None) == [] and memory_low_rows({"bad": "x"}) == [] and memory_low_rows("x") == []


@pytest.mark.unit
def test_the_inbox_draws_the_row_and_its_snooze(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"id": "person", "entries": [], "threads": {}, "sends": [], "unread": 0}
            host = {"name": "kmaster", "memory_low": _spells()}
            return {"repos": {}, "doing_log": {}, "list": [], "usage": {}, "host": host}.get(method, {})

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    html = c.get("/inbox").text
    assert "kmaster memory low: 5% free. Your largest: worker (3.0 GB)" in html
    assert 'data-sid="memory_low:kmaster:ram" data-row="memory_low" data-when="1w"' in html
    assert 'data-msg="memory_low:kmaster:ram"' in html
    assert c.get("/api/person/inbox").json()["needs"] == 1


@pytest.mark.integration
async def test_a_walk_returning_past_its_bound_is_not_applied(agent, monkeypatch):
    level = {"halves": {"ram": 0.05}}

    def late(*_a, **_k):
        agent._walk_started = time.monotonic() - 3 * scratch.LEFT_WALK_S  # returned past twice its bound
        return {"ram": HOLDERS, "swap": [], "cut": False}

    monkeypatch.setattr(memory, "read_halves", lambda *a, **k: level["halves"])
    monkeypatch.setattr(memory, "read_holders", late)
    await agent._memory_pass()
    await agent._memory_pass()
    await agent._walk_task
    assert "ram" not in diskbook.memory_state(os.environ["SHIFTLEAD_HOME"]), "no low written from a late result"
    await agent._memory_pass()  # the next reading sees the half still turning and the walk done: a fresh walk
    await agent._walk_task
