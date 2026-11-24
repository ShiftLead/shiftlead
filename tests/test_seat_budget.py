"""TD-2133, design §4.6 *A live seat's rebuildable copies*, *A seat is told instead*: the hourly pass counts each live
seat's inodes and puts every count on its dated `disk.json` line; a count over `SEAT_BUDGET` on two passes running
opens a spell, which the `disk` reading carries as `seats_over`, and the home tells the seat once in one `system` note,
wherever it runs. A single high reading tells nothing, nothing repeats within the spell, and a walk cut short can
start a spell and never end one. The budget is stubbed small, so a handful of files stands for a quarter million."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import park_ticks
from test_scratch_sweep import made

from sessionorc import diskbook, hosts, paths, scratch
from sessionorc.models import Session


def _files(root: Path, *names: str) -> None:
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


# -- the count --------------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_touch_walk_counts_every_entry_under_each_top_entry(tmp_path):
    _files(tmp_path, "big/a/1", "big/a/2", "big/b", "small")
    (tmp_path / "link").symlink_to(tmp_path / "big")
    inodes: dict[str, int] = {}
    assert scratch._touch(tmp_path, time.time_ns(), 1000, None, inodes) is False
    assert inodes == {"big": 5, "small": 1, "link": 1}, "a directory counts itself; a symlink is not walked through"
    got = scratch.seat_count(inodes, False)
    assert got["inodes"] == 7 and not got["cut"]
    want = [("big", 5), ("link", 1), ("small", 1)]
    assert got["largest"] == [{"name": n, "inodes": c} for n, c in want]


@pytest.mark.unit
def test_a_walk_cut_at_the_cap_counts_what_it_saw(tmp_path):
    _files(tmp_path, "a/1", "a/2", "b/1", "b/2")
    old = time.time() - 2 * 86400
    for p in tmp_path.rglob("*"):
        os.utime(p, (old, old))
    inodes: dict[str, int] = {}
    assert scratch._touch(tmp_path, time.time_ns(), 1, None, inodes) is True
    assert 0 < sum(inodes.values()) < 6, "a lower bound"


# -- the spell --------------------------------------------------------------------------------------------------------


def _seat(n: int, cut: bool = False) -> dict:
    return {"inodes": n, "largest": [{"name": "pytest-of-k", "inodes": n}], "cut": cut}


@pytest.mark.unit
def test_two_passes_over_the_budget_open_a_spell_and_one_does_not():
    over = scratch.SEAT_BUDGET + 1
    one = scratch.seat_step({}, {"ao-w": _seat(over)}, "T1")
    assert one == {"ao-w": {"passes": 1, "inodes": over, "largest": _seat(over)["largest"]}}
    assert scratch.seats_over(one) == [], "a single high reading tells nothing"
    two = scratch.seat_step(one, {"ao-w": _seat(over)}, "T2")
    assert two["ao-w"]["since"] == "T2"
    assert scratch.seats_over(two) == [
        {"record": "ao-w", "since": "T2", "inodes": over, "largest": _seat(over)["largest"]}
    ]
    three = scratch.seat_step(two, {"ao-w": _seat(over + 5)}, "T3")
    assert three["ao-w"]["since"] == "T2", "the spell keeps its start"


@pytest.mark.unit
def test_a_reading_under_the_budget_breaks_the_run():
    over = scratch.SEAT_BUDGET + 1
    one = scratch.seat_step({}, {"ao-w": _seat(over)}, "T1")
    assert scratch.seat_step(one, {"ao-w": _seat(scratch.SEAT_BUDGET)}, "T2") == {}


@pytest.mark.unit
def test_the_spell_holds_between_the_lines_and_ends_under_the_clear_line():
    over = scratch.SEAT_BUDGET + 1
    spell = scratch.seat_step(scratch.seat_step({}, {"ao-w": _seat(over)}, "T1"), {"ao-w": _seat(over)}, "T2")
    held = scratch.seat_step(spell, {"ao-w": _seat(scratch.SEAT_BUDGET_CLEAR)}, "T3")
    assert held["ao-w"]["since"] == "T2"
    assert scratch.seat_step(held, {"ao-w": _seat(scratch.SEAT_BUDGET_CLEAR - 1)}, "T4") == {}


@pytest.mark.unit
def test_a_cut_walk_can_start_a_spell_and_never_end_one():
    over = scratch.SEAT_BUDGET + 1
    one = scratch.seat_step({}, {"ao-w": _seat(over, cut=True)}, "T1")
    spell = scratch.seat_step(one, {"ao-w": _seat(over, cut=True)}, "T2")
    assert spell["ao-w"]["since"] == "T2", "a lower bound over the line is over it"
    assert scratch.seat_step(spell, {"ao-w": _seat(10, cut=True)}, "T3")["ao-w"]["since"] == "T2"
    # nor does a cut reading under the line break a run of passes over it
    assert scratch.seat_step(one, {"ao-w": _seat(10, cut=True)}, "T2") == one


@pytest.mark.unit
def test_a_live_seat_left_unwalked_keeps_its_run_and_its_spell():
    over = scratch.SEAT_BUDGET + 1
    one = scratch.seat_step({}, {"ao-w": _seat(over)}, "T1")
    assert scratch.seat_step(one, {"ao-w": {"skipped": True}}, "T2") == one
    spell = scratch.seat_step(one, {"ao-w": _seat(over)}, "T2")
    assert scratch.seat_step(spell, {"ao-w": {"skipped": True}}, "T3") == spell
    assert scratch.seat_step({}, {"ao-w": {"skipped": True}}, "T1") == {}


@pytest.mark.unit
def test_a_record_that_ends_ends_its_spell():
    over = scratch.SEAT_BUDGET + 1
    spell = scratch.seat_step(scratch.seat_step({}, {"ao-w": _seat(over)}, "T1"), {"ao-w": _seat(over)}, "T2")
    assert scratch.seat_step(spell, {}, "T3") == {}


@pytest.mark.unit
def test_the_note_names_the_count_the_largest_and_what_to_do():
    spell = {
        "record": "ao-w",
        "since": "T",
        "inodes": 260_000,
        "largest": [{"name": "pytest-of-k", "inodes": 180_000}, {"name": "review", "inodes": 50_000}],
    }
    got = scratch.seat_note(spell)
    assert got.startswith("Your scratch holds 260,000 files, over the 250,000 a seat may keep")
    assert "The largest entries in it: pytest-of-k (180,000), review (50,000)." in got
    assert "under $SHIFTLEAD_SCRATCH/copies/" in got and "test runs go by themselves within two hours" in got


# -- the hourly pass and the home, end to end -------------------------------------------------------------------------


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(scratch, "SEAT_BUDGET", 4)
    monkeypatch.setattr(scratch, "SEAT_BUDGET_CLEAR", 3)


def _notes(r: Session) -> list[str]:
    return [e.text for e in r.inbox if e.from_ == "system" and "Your scratch holds" in e.text]


@pytest.mark.integration
async def test_a_seat_over_its_budget_on_two_passes_is_told_once(agent, small):
    await park_ticks(agent)
    root = hosts.DEFAULT_SCRATCH_ROOT
    big, quiet = made(root, str(paths.home()), "ao-x-w"), made(root, str(paths.home()), "ao-x-q")
    _files(big, "pytest-of-k/a", "pytest-of-k/b", "review/c")
    r = Session(id="ao-x-w", name="w", kind="agent", adapter="agentshell", dir="/tmp/x", host=agent.host)
    agent.sessions[r.id] = r
    scratch_of = {"ao-x-w": str(big), "ao-x-q": str(quiet)}
    home = os.environ["SHIFTLEAD_HOME"]
    try:
        agent._prune_runs(datetime.now(UTC), set(), set(), scratch_of, {})
        line = json.loads((Path(home) / diskbook.FILE).read_text())["passes"][-1]
        assert line["seats"] == {"ao-x-q": 1, "ao-x-w": 6}, "every live seat's count, owner.json included"
        await agent._disk_low_pass()
        assert _notes(r) == [] and "seats_over" not in agent._disk_here(), "a single high reading tells nothing"

        agent._prune_runs(datetime.now(UTC), set(), set(), scratch_of, {})
        over = agent._disk_here()["seats_over"]
        assert [(o["record"], o["inodes"]) for o in over] == [("ao-x-w", 6)]
        assert over[0]["largest"][0] == {"name": "pytest-of-k", "inodes": 3}
        await agent._disk_low_pass()
        assert len(_notes(r)) == 1 and "pytest-of-k (3)" in _notes(r)[0]
        assert agent.host_store.load()["seats_told"] == {"ao-x-w": {"host": agent.host, "since": over[0]["since"]}}

        agent._prune_runs(datetime.now(UTC), set(), set(), scratch_of, {})
        await agent._disk_low_pass()
        assert len(_notes(r)) == 1, "nothing repeats within the spell"

        scratch.write_owner(big, "ao-other", home)  # a pass that skips the live seat: its spell stands
        agent._prune_runs(datetime.now(UTC), set(), set(), scratch_of, {})
        assert "ao-x-w" not in json.loads((Path(home) / diskbook.FILE).read_text())["passes"][-1]["seats"]
        assert [o["since"] for o in agent._disk_here()["seats_over"]] == [over[0]["since"]]
        scratch.write_owner(big, "ao-x-w", home)
        agent._prune_runs(datetime.now(UTC), set(), set(), scratch_of, {})
        assert [o["since"] for o in agent._disk_here()["seats_over"]] == [over[0]["since"]]
        await agent._disk_low_pass()
        assert len(_notes(r)) == 1, "a skipped pass neither ends the spell nor tells it again"

        scratch._remove(big / "pytest-of-k")
        scratch._remove(big / "review")  # one file left, under the clear line
        agent._prune_runs(datetime.now(UTC), set(), set(), scratch_of, {})
        assert "seats_over" not in agent._disk_here() and diskbook.seat_state(home) == {}
        await agent._disk_low_pass()
        assert "seats_told" not in agent._host_rec, "a spell the reading no longer carries is forgotten"
        agent._prune_runs(datetime.now(UTC), set(), set(), None, None)  # no walk of the seats: no spell moves
        assert "seats" not in json.loads((Path(home) / diskbook.FILE).read_text())["passes"][-1]
    finally:
        agent.sessions.pop(r.id, None)
        for d in (big, quiet):
            scratch._remove(d)


@pytest.mark.integration
async def test_a_node_seat_is_told_and_a_node_down_neither_repeats_nor_forgets(agent, monkeypatch):
    await park_ticks(agent)
    r = Session(id="ao-x-w", name="w", kind="agent", adapter="agentshell", dir="/tmp/x", host="laptop")
    agent.remote["laptop"] = {r.id: r}
    spell = {"record": "ao-x-w", "since": "2026-11-24T10:00:00Z", "inodes": 300_000, "largest": []}
    answers = {"laptop": {"seats_over": [spell]}}

    async def everywhere(_method, _here):
        return {agent.host: {}, **answers}

    monkeypatch.setattr(agent, "_disk_everywhere", everywhere)
    try:
        await agent._disk_low_pass()
        assert len(_notes(r)) == 1 and "300,000 files" in _notes(r)[0]
        told = {"ao-x-w@laptop": {"host": "laptop", "since": spell["since"]}}
        assert agent._host_rec["seats_told"] == told
        answers["laptop"] = {"error": "unreachable"}
        await agent._disk_low_pass()
        assert agent._host_rec["seats_told"] == told, "a node down keeps what it was told"
        answers["laptop"] = {"seats_over": [spell]}
        await agent._disk_low_pass()
        assert len(_notes(r)) == 1, "and its return repeats nothing"
        answers["laptop"] = {"seats_over": [{**spell, "since": "2026-11-24T12:00:00Z"}]}
        await agent._disk_low_pass()
        assert len(_notes(r)) == 2, "a new spell is told again"
    finally:
        agent.remote.pop("laptop", None)


@pytest.mark.unit
def test_a_root_that_cannot_be_made_moves_no_spell(tmp_path, monkeypatch):
    t = diskbook.Tally()
    t.seat = {}

    def refuse(_root):
        raise OSError("read-only")

    monkeypatch.setattr(scratch, "ensure_parent", refuse)
    assert scratch.keep_alive(tmp_path, {"ao-w": str(tmp_path / "x")}, tmp_path, time.time_ns(), t) == []
    assert t.seat is None


@pytest.mark.unit
def test_odd_counts_read_as_nothing_and_never_raise():
    old = {"ao-w": {"passes": "x", "since": "T", "inodes": "y", "largest": "z"}}
    assert scratch.seats_over(old) == [{"record": "ao-w", "since": "T", "inodes": 0, "largest": []}]
    got = scratch.seat_step(old, {"ao-w": {"inodes": "many"}, "ao-q": "bad"}, "T2")
    assert got == {}, "an odd count reads as 0, under the clear line, and a seat's odd reading is skipped"
    assert "files" in scratch.seat_note({"inodes": "x", "largest": [{"name": "a", "inodes": None}]})


@pytest.mark.integration
async def test_a_spell_outlives_other_writers_and_ends_when_no_seat_is_live(agent, small):
    await park_ticks(agent)
    home = os.environ["SHIFTLEAD_HOME"]
    spell = {"ao-x-w": {"passes": 2, "since": "T", "inodes": 9, "largest": []}}
    diskbook.write(home, agent.host, {}, {}, "s", datetime.now(UTC), seats={}, seat_spells=spell)
    diskbook.set_low(home, agent.host, {"seats": {"low": True}})
    diskbook.set_memory(home, agent.host, {})
    diskbook.write(home, agent.host, {}, {}, "s", datetime.now(UTC))  # a pass that walked no seat
    assert diskbook.seat_state(home) == spell
    agent._disk_dry_here(agent._sweep_snapshot(datetime.now(UTC)))  # a dry run writes no spell
    assert diskbook.seat_state(home) == spell
    agent._prune_runs(datetime.now(UTC), set(), set(), {}, {})  # the hourly pass, no seat live
    assert diskbook.seat_state(home) == {}


@pytest.mark.integration
async def test_odd_node_answers_tell_nothing(agent, monkeypatch):
    await park_ticks(agent)
    answers = {"laptop": {"seats_over": "x"}, "pi": {"seats_over": [{"record": "w", "since": 5}, "y", {}]}}

    async def everywhere(_method, _here):
        return {agent.host: {}, **answers}

    monkeypatch.setattr(agent, "_disk_everywhere", everywhere)
    await agent._disk_low_pass()
    assert "seats_told" not in agent._host_rec
