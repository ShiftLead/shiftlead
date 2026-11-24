"""TD-2137, design §4.6 *Told what finished sessions left running*, *The process reading*, §4.5a *Inbox row:
processes left behind*, §4.7 `ao disk`: the five rules judged by run over a stubbed `/proc`, the spell raised by two
`LEFT_EVERY` walks and cleared under the lower line, `ended_runs` written at a forget and a replace in place, and one
row and one message per spell. Nothing on this machine is read or signalled."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sessionorc import diskbook, memory, notify, scratch
from sessionorc.models import Session
from sessionorc.store import HostStore
from shiftlead import cli
from shiftlead.ui import inbox as inbox_ui

MIB = 1024**2
TICK = os.sysconf("SC_CLK_TCK")
NOW = 2_000_000.0
BTIME = 1_000_000


def _z(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _proc(root: Path, pid: int, ppid: int, name: str, start: float, *, env=None, mib=10, cwd: str | None = None):
    """A process under the stub `/proc`, started at `start` (seconds since the epoch), holding `mib` of `Pss`."""
    d = root / str(pid)
    d.mkdir(parents=True)
    rest = ["S", str(ppid)] + ["0"] * 17 + [str(int((start - BTIME) * TICK))] + ["0"] * 10
    (d / "stat").write_text(f"{pid} ({name}) {' '.join(rest)}\n")
    (d / "comm").write_text(name + "\n")
    (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in (env or {}).items()) + b"\0")
    (d / "smaps_rollup").write_text(f"Pss:  {mib * 1024} kB\nSwapPss: 0 kB\n")
    if cwd is not None:
        os.symlink(cwd, d / "cwd")


@pytest.fixture
def world(tmp_path):
    """Every case of TD-2137's Done when, under one stub `/proc`: the named and the never named."""
    proc, home, other = tmp_path / "proc", tmp_path / "home", tmp_path / "other-home"
    home.mkdir()
    other.mkdir()
    proc.mkdir()
    (proc / "stat").write_text(f"cpu 1 2 3\nbtime {BTIME}\n")
    gone = str(tmp_path / "gone-scratch-home")
    old, young = NOW - 2 * 3600, NOW - 600
    live_created = NOW - 3 * 3600
    ours = {"SHIFTLEAD_HOME": str(home)}
    # named: a test child whose scratch home is gone, with a child and a live run's process beneath it
    _proc(proc, 100, 1, "pytest", old, env={"SHIFTLEAD_HOME": gone}, mib=300)
    _proc(proc, 101, 100, "python", old, mib=50)
    _proc(proc, 102, 100, "claude", NOW - 2.5 * 3600, env={**ours, "SHIFTLEAD_SESSION": "ao-live"}, mib=900)
    _proc(proc, 103, 102, "node", old, mib=70)
    # named: an ended unattended run's process
    _proc(proc, 110, 1, "node", old, env={**ours, "SHIFTLEAD_SESSION": "ao-ended"}, mib=40)
    # named: an earlier run of a seat whose id is live again, its start time in an `ended_runs` span
    _proc(proc, 120, 1, "uv", NOW - 10 * 3600, env={**ours, "SHIFTLEAD_SESSION": "ao-live"}, mib=20)
    # named: another home that exists, its working directory deleted
    _proc(proc, 130, 1, "pdm", old, env={"SHIFTLEAD_HOME": str(other)}, cwd="/tmp/x (deleted)")
    # never named
    _proc(proc, 200, 1, "nohup-job", old)  # a person's detached job: no variable
    _proc(proc, 210, 1, "systemd", NOW - 50 * 3600)  # this user's manager
    _proc(proc, 211, 210, "pipewire", old)  # a desktop service
    _proc(proc, 212, 210, "shiftlead-agent", old, env=ours)  # the live host agent: this home, no session
    _proc(proc, 213, 210, "uvicorn", old)  # the UI on a default install: no variable
    _proc(proc, 220, 1, "uvicorn", old, env={"SHIFTLEAD_HOME": str(other)}, cwd=str(other))  # a precheck's server
    _proc(proc, 230, 1, "claude", NOW - 2.5 * 3600, env={**ours, "SHIFTLEAD_SESSION": "ao-live"})  # a live run
    _proc(proc, 240, 1, "bash", old, env={**ours, "SHIFTLEAD_SESSION": "ao-mine"})  # interactive: in no span
    _proc(proc, 250, 1, "node", old, env={"SHIFTLEAD_HOME": str(other), "SHIFTLEAD_SESSION": "ao-ended"})
    _proc(proc, 260, 1, "pytest", young, env={"SHIFTLEAD_HOME": gone})  # under an hour old
    _proc(proc, 270, 1, "node", old, env={**ours, "SHIFTLEAD_SESSION": "ao-span"})  # started after its span's `to`
    _proc(proc, 280, 0, "pytest", old, env={"SHIFTLEAD_HOME": gone})  # a `docker exec`'s parent is not such a one
    runs = memory.Runs(
        live={"ao-live": ("worker", live_created)},
        ended={"ao-ended": NOW - 4 * 3600},
        spans={"ao-live": [(NOW - 11 * 3600, NOW - 9 * 3600)], "ao-span": [(NOW - 20 * 3600, NOW - 19 * 3600)]},
    )
    return proc, home, runs


@pytest.mark.unit
def test_the_five_rules_name_what_finished_sessions_left_and_nothing_else(world):
    proc, home, runs = world
    procs, cut = memory.walk(proc, uid=os.getuid())
    trees, held = memory.left_behind(procs, runs, home, NOW)
    assert not cut
    assert [t["pid"] for t in trees] == [100, 110, 120, 130], "largest first"
    by = {t["pid"]: t for t in trees}
    assert by[100]["processes"] == 2 and by[100]["bytes"] == 350 * MIB, "a child counted, a live run's left out"
    assert by[100]["home"].endswith("gone-scratch-home") and "session" not in by[100]
    assert by[110]["session"] == "ao-ended" and by[120]["session"] == "ao-live"
    assert by[130]["cwd_deleted"] is True and by[130]["home"].endswith("other-home")
    assert held == {100, 101, 110, 120, 130}
    assert by[110]["start"] == _z(NOW - 2 * 3600)


@pytest.mark.unit
def test_the_walk_answers_the_figures_and_the_memory_row_holds_left_behind_as_one(world):
    proc, home, runs = world
    got = memory.read_holders(runs, home, proc, now=NOW)
    assert got["left"]["processes"] == 5 and got["left"]["bytes"] == (350 + 40 + 20 + 10) * MIB
    names = [h["name"] for h in got["ram"]]
    assert names[0] == "worker" and "left behind" in names, names
    assert next(h for h in got["ram"] if h["name"] == "left behind")["bytes"] == 420 * MIB


@pytest.mark.unit
def test_nothing_is_signalled():
    for mod in (memory, diskbook):
        src = Path(mod.__file__).read_text()
        assert "os.kill" not in src and "killpg" not in src and "send_signal" not in src


# -- the spell ------------------------------------------------------------------------------------------------------


def _got(n: int, mib: int, cut: bool = False) -> dict:
    return {"cut": cut, "left": {"processes": n, "bytes": mib * MIB, "trees": [{"pid": 1, "name": "x", "bytes": 1}]}}


@pytest.mark.unit
def test_two_every_walks_raise_the_spell_and_a_low_memory_walk_counts_toward_neither():
    w = memory.LeftWatch()
    s = w.walked({}, _got(30, 10), True, "T1")
    assert "since" not in s and s["processes"] == 30, "one walk over the line does not"
    between = w.walked(s, _got(1, 1), False, "T2")
    assert between == s, "a walk because a half turned low changes no figure and breaks no run"
    assert w.walked(between, None, True, "T3") == between, "a failed walk counts toward neither"
    s = w.walked(between, _got(2, 600), True, "T4")
    assert s["since"] == "T4" and s["bytes"] == 600 * MIB, "the second LEFT_EVERY walk at or over 512 MiB raises it"
    s = w.walked(s, _got(5, 300), True, "T5")
    assert s["since"] == "T4", "300 MiB and 5 processes does not clear it"
    s = w.walked(s, _got(1, 1, cut=True), True, "T6")
    assert s["since"] == "T4" and s["cut"] is True, "a cut walk never ends a spell"
    s = w.walked(s, _got(9, 255), True, "T7")
    assert "since" not in s, "the first complete walk under both 256 MiB and 10 processes ends it"


@pytest.mark.unit
def test_a_walk_under_the_raise_breaks_the_run_and_a_cut_one_can_start_a_spell():
    w = memory.LeftWatch()
    s = w.walked({}, _got(25, 0), True, "T1")
    s = w.walked(s, _got(3, 10), True, "T2")
    s = w.walked(s, _got(25, 0), True, "T3")
    assert "since" not in s, "a complete walk under the raise broke the run"
    s = w.walked(s, _got(25, 0, cut=True), True, "T4")
    assert s["since"] == "T4", "a cut walk at or over the line counts"


# -- `ended_runs` ---------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_ended_runs_keeps_twenty_runs_an_id_and_ninety_days():
    ended: dict = {}
    for i in range(25):
        ended = memory.end_run(ended, "ao-x", _z(NOW + i), _z(NOW + i + 1))
    assert len(ended["ao-x"]["runs"]) == scratch.LEFT_ENDED_RUNS and ended["ao-x"]["runs"][0]["from"] == _z(NOW + 5)
    ended = memory.end_run(ended, "ao-old", _z(NOW - 100 * 86400), _z(NOW - 91 * 86400))
    kept = memory.trim_runs({**ended, "odd": "x", "bad": {"runs": [{"from": "?", "to": "?"}]}}, NOW + 100)
    assert set(kept) == {"ao-x"}, "a run past 90 days, an odd entry and an id left with none go"
    assert memory.spans(kept)["ao-x"][0] == (NOW + 5, NOW + 6)


@pytest.mark.unit
def test_the_host_record_keeps_ended_runs_and_the_spells(tmp_path):
    store = HostStore(tmp_path / "host.json")
    rec = {"teams": {}, "ended_runs": {"ao-x": {"runs": [{"from": "a", "to": "b"}]}}, "left_behind": {"h": {"x": 1}}}
    store.save(rec)
    got = store.load()
    assert got["ended_runs"] == rec["ended_runs"] and got["left_behind"] == rec["left_behind"]


def _rec(sid: str, unattended: bool = True, state: str = "exited") -> Session:
    s = Session(id=sid, name=sid, dir="/x", adapter="shell", kind="agent", unattended=unattended)
    s.state = state
    s.created = _z(time.time() - 3600)
    return s


@pytest.mark.integration
async def test_a_forget_writes_an_unattended_runs_span_and_a_replace_in_place_too(agent, monkeypatch):
    agent.sessions["ao-u"] = forgotten = _rec("ao-u")
    agent.sessions["ao-i"] = _rec("ao-i", unattended=False)
    agent._forget("ao-u")
    agent._forget("ao-i")
    runs = agent._host_rec["ended_runs"]
    assert list(runs) == ["ao-u"] and runs["ao-u"]["runs"][0]["from"] == forgotten.created, "unattended alone"
    assert HostStore(agent.host_store.path).load()["ended_runs"] == runs, "saved at once"
    monkeypatch.setattr(agent.tmux, "kill_session", lambda *_a: None)
    held = _rec("ao-r", state="closed")
    agent.sessions["ao-r"] = held
    await agent._take_name(held)
    assert agent._host_rec["ended_runs"]["ao-r"]["runs"][0]["from"] == held.created, "a new run replaces it in place"
    agent.sessions.pop("ao-r", None)


@pytest.mark.unit
def test_ended_records_are_the_unattended_exited_or_closed_ones():
    recs = [_rec("a"), _rec("b", unattended=False), _rec("c", state="working"), _rec("d", state="closed")]
    assert set(memory.ended_records(recs)) == {"a", "d"}


# -- the host and the home ------------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_spell_is_one_row_and_one_message_and_clears(agent, monkeypatch):
    left = {"n": 30, "mib": 600}

    def walk(runs, home, *a, **k):
        return {"ram": [], "swap": [], "cut": False, "left": _got(left["n"], left["mib"])["left"]}

    monkeypatch.setattr(memory, "read_halves", lambda *a, **k: {"ram": 0.9})
    monkeypatch.setattr(memory, "read_holders", walk)

    async def every() -> None:
        agent._walk_at = time.monotonic() - 2 * scratch.LEFT_EVERY
        await agent._memory_pass()
        await agent._walk_task
        await agent._disk_low_pass()

    await every()
    assert "left_behind" not in agent._host_rec, "one walk does not"
    reading = await asyncio.to_thread(agent._disk_here)
    assert reading["left_behind"]["since"] is None and reading["left_behind"]["processes"] == 30, "always carried"
    await every()
    spell = agent._host_rec["left_behind"][agent.host]
    assert spell["processes"] == 30 and spell["bytes"] == 600 * MIB and spell["largest"][0]["name"] == "x"
    assert (await agent.rpc_host())["left_behind"][agent.host]["since"] == spell["since"]
    row = agent._notify_rows()[f"left_behind:{agent.host}"]
    assert row.snooze == f"left_behind:{agent.host}|left_behind" and "30 processes left behind" in row.line
    left.update(n=5, mib=300)
    await every()
    assert agent._host_rec["left_behind"][agent.host]["since"] == spell["since"], "300 MiB and 5 processes stands"
    left.update(n=2, mib=10)
    await every()
    assert "left_behind" not in agent._host_rec and (await agent.rpc_host())["left_behind"] == {}


@pytest.mark.unit
def test_the_home_keeps_a_spell_per_host_and_an_older_build_keeps_its_own():
    old = {"n1": {"host": "n1", "since": "S"}}
    answers = {
        "home": {"left_behind": {"since": "A", "at": "A", "processes": 3, "bytes": 5, "trees": []}},
        "n1": {"kinds": {}},  # an older build: no field
        "n2": {"left_behind": {"since": None, "processes": 99}},
    }
    got = diskbook.left_spells(old, answers, "NOW")
    assert set(got) == {"home", "n1"} and got["home"]["since"] == "NOW" and got["n1"] == old["n1"]
    assert diskbook.left_spells({}, {"n1": {"error": "unreachable"}}, "NOW") == {}


@pytest.mark.unit
def test_the_words_the_row_and_ao_disk():
    spell = {
        "host": "kmaster",
        "since": "2026-11-24T10:00:00Z",
        "processes": 128,
        "bytes": 3 * 1024 * MIB,
        "cut": False,
        "largest": [{"name": "node", "bytes": 900 * MIB}, {"name": "pytest", "bytes": 300 * MIB}],
    }
    want = (
        "kmaster: 128 processes left behind by finished sessions, holding 3.0 GB. Largest: node (900.0 MB), "
        "pytest (300.0 MB)"
    )
    assert notify.left_behind_text(spell) == want
    assert notify.left_behind_text({**spell, "cut": True}).startswith("kmaster: at least 128 processes")
    assert notify.left_behind_line(spell).endswith(want)
    rows = inbox_ui.left_behind_rows({"kmaster": spell})
    assert rows[0]["sid"] == "left_behind:kmaster" and rows[0]["row"] == "left_behind" and rows[0]["text"] == want
    tree = {"pid": 4242, "name": "node", "start": "2026-10-19T08:00:00Z", "bytes": 900 * MIB, "processes": 3}
    entry = {"kinds": {}, "left_behind": {**spell, "at": "2026-11-24T11:00:00Z", "trees": [{**tree, "session": "s"}]}}
    lines = "\n".join(cli.disk_lines({"kmaster": entry}))
    assert "pid 4242 node started 2026-10-19T08:00:00Z: 900.0 MB in 3 processes (session s)" in lines
    assert "read 2026-11-24T11:00:00Z" in lines and "⚠ kmaster: 128 processes left behind" in lines


@pytest.mark.unit
def test_the_snooze_key_and_help_are_the_designs():
    from shiftlead.ui import help as help_mod

    one = next(h for h in help_mod.HELP if h.key == "left-behind-snooze")
    design = (Path(__file__).parents[1] / "docs/design/4.5a-controls.md").read_text()
    assert " ".join(one.text.split()) in " ".join(design.split())
