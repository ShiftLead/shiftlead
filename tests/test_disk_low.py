"""TD-2083, design §4.6 *Told before the pool is full*, §4.5a *Inbox row: temporary space low*: a pool held under 15%
after a reclaim (or, for `shared` beside `seats`, on the reading alone) raises one row and one message naming its three
largest holders; 15% to 35% neither ends nor repeats it, nor does a restart; over 35% ends it; a node that stops
answering neither raises nor clears it. The free-space reading is stubbed: this machine allows no unprivileged mount."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sessionorc import diskbook, notify, scratch
from sessionorc import settings as settings_mod
from sessionorc.agent_common import RpcError
from sessionorc.store import HostStore
from shiftlead import cli

HOLDERS = [{"name": "ao-big", "inodes": 1200, "cut": True}, {"name": "pip", "inodes": 1, "cut": False}]


def _z(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _step(state, share, *, reclaimed=None, reclaims=True, name="seats"):
    walked: list[str] = []

    def walk(path):
        walked.append(path)
        return HOLDERS

    got = scratch.step_low(state, [(name, "/pool", reclaims, share)], {name}, reclaimed, walk, "T")
    return got, walked


@pytest.mark.unit
def test_a_reclaimed_pool_turns_low_only_after_a_reclaim_and_walks_once():
    got, walked = _step({}, 0.10)
    assert got == {} and walked == [], "no reclaim has run since it was last over the clear line"
    got, walked = _step({}, 0.20, reclaimed="seats")
    assert got == {"seats": {"reclaimed": True}} and walked == [], "reclaimed, but not under 15%"
    got, walked = _step(got, 0.10)
    assert got["seats"]["low"] is True and got["seats"]["since"] == "T" and walked == ["/pool"]
    again, walked = _step(got, 0.05)
    assert again == got and walked == [], "still low: no second walk, nothing repeated"


@pytest.mark.unit
@pytest.mark.parametrize("share", [0.15, 0.25, 0.3499])
def test_between_the_lines_a_low_pool_stays_low(share):
    low, _ = _step({}, 0.10, reclaimed="seats")
    got, walked = _step(low, share)
    assert got == low and walked == []


@pytest.mark.unit
def test_over_the_clear_line_ends_it_and_a_later_fall_needs_a_new_reclaim():
    low, _ = _step({}, 0.10, reclaimed="seats")
    got, _ = _step(low, 0.35)
    assert got == {}
    got, walked = _step(got, 0.10)
    assert got == {} and walked == []
    got, walked = _step(got, 0.10, reclaimed="seats")
    assert got["seats"]["low"] is True and walked == ["/pool"]


@pytest.mark.unit
def test_shared_beside_seats_is_low_on_the_reading_alone():
    got, walked = _step({}, 0.10, reclaims=False, name="shared")
    assert got["shared"]["low"] is True and walked == ["/pool"]


@pytest.mark.unit
def test_no_reading_changes_nothing_and_a_gone_pool_is_forgotten():
    low, _ = _step({}, 0.10, reclaimed="seats")
    got, _ = _step(low, None)
    assert got == low
    assert scratch.step_low(low, [], {"shared"}, None, lambda _p: [], "T") == {}


@pytest.mark.unit
def test_a_reclaim_is_credited_even_where_its_reading_failed():
    got, _ = _step({}, None, reclaimed="seats")
    assert got == {"seats": {"reclaimed": True}}


@pytest.mark.unit
def test_odd_holders_cost_their_names_and_never_raise():
    odd = {"host": "h", "pool": "seats", "share_free": 0.1, "holders": [{"name": "x", "inodes": "many"}, 3]}
    assert notify.disk_low_text(odd) == "h temporary space low (seats): 10% free"
    assert notify.disk_low_text({**odd, "holders": "x"}) == "h temporary space low (seats): 10% free"


@pytest.mark.unit
def test_a_flat_directory_is_cut_at_the_bound(tmp_path, monkeypatch):
    flat = tmp_path / "flat"
    flat.mkdir()
    for i in range(4100):
        (flat / str(i)).touch()
    ticks = iter([0.0])
    monkeypatch.setattr(scratch.time, "monotonic", lambda: next(ticks, 100.0))
    n, cut = scratch._inodes(str(flat), 50.0)
    assert cut is True and n == 4096


@pytest.mark.unit
def test_the_state_survives_a_sweeps_write_and_a_pressure_line(tmp_path):
    now = datetime.now(UTC)
    diskbook.set_low(tmp_path, "h", {"seats": {"low": True, "since": "T", "holders": HOLDERS}})
    diskbook.write(tmp_path, "h", {}, {"path": "/p"}, "S", now)
    diskbook.note_pressure(tmp_path, "h", 10, False, now)
    assert diskbook.low_state(tmp_path)["seats"]["since"] == "T"
    diskbook.set_low(tmp_path, "h", {})
    got = json.loads((tmp_path / diskbook.FILE).read_text())
    assert "low" not in got and got["passes"], "clearing the state leaves the rest of the file"


@pytest.mark.unit
def test_holders_are_the_three_largest_named_by_their_record(tmp_path):
    root = tmp_path / "pool"
    ours = scratch.parent(root)
    for token, rid, n in (("aaaaaaaa", "ao-small", 1), ("bbbbbbbb", "ao-big", 30)):
        d = ours / token
        d.mkdir(parents=True)
        scratch.write_owner(d, rid, tmp_path)
        for i in range(n):
            (d / f"f{i}").write_text("")
    other = root / "pip-cache"
    other.mkdir()
    for i in range(10):
        (other / f"f{i}").write_text("")
    (root / "loose").write_text("")
    (root / "link").symlink_to(other)
    got = scratch.holders(root)
    assert [h["name"] for h in got] == ["ao-big", "pip-cache", "ao-small"]
    assert got[0]["inodes"] == 32 and got[1]["inodes"] == 11 and not any(h["cut"] for h in got)


@pytest.mark.unit
def test_a_walk_past_its_bound_says_at_least(tmp_path):
    (tmp_path / "d" / "e").mkdir(parents=True)
    (got,) = scratch.holders(tmp_path, walk_s=-1)
    assert got["name"] == "d" and got["cut"] is True


@pytest.mark.unit
def test_the_homes_spells_begin_hold_and_end():
    answer = {"pressure": {"seats": {"since": "x", "share_free": 0.12, "holders": HOLDERS}}}
    got = diskbook.low_spells({}, {"h": answer, "n": {"kinds": {}}}, "T0")
    assert list(got) == ["h:seats"] and got["h:seats"]["since"] == "T0" and got["h:seats"]["share_free"] == 0.12
    later = {"pressure": {"seats": {"since": "x", "share_free": 0.2, "holders": HOLDERS[:1]}}}
    held = diskbook.low_spells(got, {"h": later}, "T1")
    assert held["h:seats"]["since"] == "T0" and held["h:seats"]["share_free"] == 0.2
    assert len(held["h:seats"]["holders"]) == 1
    assert diskbook.low_spells(held, {"h": {"kinds": {}}}, "T2") == {}


@pytest.mark.unit
def test_a_node_that_stops_answering_neither_raises_nor_clears():
    answer = {"pressure": {"seats": {"share_free": 0.12, "holders": HOLDERS}}}
    got = diskbook.low_spells({}, {"n": answer}, "T0")
    assert diskbook.low_spells(got, {"n": {"error": "unreachable"}}, "T1") == got
    assert diskbook.low_spells({}, {"n": {"error": "unreachable"}}, "T1") == {}
    assert diskbook.low_spells(got, {"h": {"kinds": {}}}, "T1") == {}, "a host no longer asked has no spell"


@pytest.mark.unit
def test_the_host_record_keeps_the_spells(tmp_path):
    store = HostStore(tmp_path / "host.json")
    store.save({"teams": {}, "disk_low": {"h:seats": {"host": "h", "since": "T"}, "bad": 1}})
    assert store.load()["disk_low"] == {"h:seats": {"host": "h", "since": "T"}}


@pytest.mark.unit
def test_the_words_name_the_host_pool_share_and_holders():
    spell = {"host": "kmaster", "pool": "seats", "share_free": 0.129, "holders": HOLDERS}
    want = "kmaster temporary space low (seats): 12% free. Largest: ao-big (at least 1,200 files), pip (1 file)"
    assert notify.disk_low_text(spell) == want
    assert notify.disk_low_line(spell) == f"shiftlead · {want}"
    assert notify.disk_low_text({"host": "h", "pool": "shared"}) == "h temporary space low (shared)"


@pytest.mark.unit
def test_ao_disk_prints_a_low_pool():
    entry = {"at": None, "kinds": {}, "free": {}}
    entry["pressure"] = {"seats": {"since": "T", "share_free": 0.1, "holders": HOLDERS[:1]}}
    lines = cli.disk_lines({"h": entry})
    assert "  ⚠ h temporary space low (seats): 10% free. Largest: ao-big (at least 1,200 files) (since T)" in lines


# -- the host and the home, end to end ------------------------------------------------------------------------------


@pytest.fixture
def pool(agent, tmp_path, monkeypatch):
    """A pool the agent reads, its share free stubbed through `level`."""
    root = tmp_path / "p"
    root.mkdir()
    level = {"share": 0.5}
    monkeypatch.setattr(type(agent), "_scratch_root", staticmethod(lambda: str(root)))
    monkeypatch.setattr(type(agent), "_seat_root", staticmethod(lambda: ""))
    monkeypatch.setattr(diskbook, "share_free", lambda _p, *_a: level["share"])
    return level


async def _read(agent, share, level) -> None:
    level["share"] = share
    agent._pressure_backoff = scratch.Backoff()  # a reclaim at every low reading, whatever the last one freed
    await agent._pressure_pass(datetime.now(UTC))
    await agent._disk_low_pass()


@pytest.mark.integration
async def test_a_held_low_pool_is_one_spell_from_reclaim_to_clear(agent, pool):
    await _read(agent, 0.2, pool)
    assert "disk_low" not in agent._host_rec, "reclaimed, not under 15%"
    await _read(agent, 0.1, pool)
    key = f"{agent.host}:shared"
    since = agent._host_rec["disk_low"][key]["since"]
    await _read(agent, 0.3, pool)
    assert agent._host_rec["disk_low"][key]["since"] == since and agent._host_rec["disk_low"][key]["share_free"] == 0.3
    assert (await agent.rpc_host())["disk_low"][key]["since"] == since
    await _read(agent, 0.4, pool)
    assert "disk_low" not in agent._host_rec and (await agent.rpc_host())["disk_low"] == {}


@pytest.mark.integration
async def test_a_restart_neither_ends_nor_repeats_a_low_state(agent, pool, monkeypatch):
    await _read(agent, 0.1, pool)
    first = diskbook.low_state(os.environ["SHIFTLEAD_HOME"])["shared"]
    monkeypatch.setattr(scratch, "holders", lambda *_a: pytest.fail("a restart walks the pool again"))
    agent._pressure_backoff = scratch.Backoff()
    pool["share"] = 0.2  # a new run, between the lines, with no reclaim of its own
    await asyncio.to_thread(agent._low_step, False)
    assert diskbook.low_state(os.environ["SHIFTLEAD_HOME"])["shared"] == first


@pytest.mark.integration
async def test_a_second_file_system_is_shared_and_told_on_the_reading_alone(agent, tmp_path, monkeypatch):
    seat, root = tmp_path / "seat", tmp_path / "root"
    scratch.parent(seat).mkdir(parents=True)
    root.mkdir()
    monkeypatch.setattr(type(agent), "_scratch_root", staticmethod(lambda: str(root)))
    monkeypatch.setattr(type(agent), "_seat_root", staticmethod(lambda: str(seat)))
    monkeypatch.setattr(scratch, "same_fs", lambda _a, _b: False)
    assert [p[:1] + p[2:] for p in agent._low_pools()[0]] == [("seats", True), ("shared", False)]
    monkeypatch.setattr(diskbook, "share_free", lambda p, *_a: 0.1 if p == str(root) else 0.5)
    await asyncio.to_thread(agent._low_step, False)
    assert list(diskbook.low_state(os.environ["SHIFTLEAD_HOME"])) == ["shared"]
    monkeypatch.setattr(scratch, "same_fs", lambda _a, _b: True)
    assert [p[0] for p in agent._low_pools()[0]] == ["seats"]


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


def _spell(agent, since: datetime) -> None:
    agent._host_rec["disk_low"] = {
        "kmaster:seats": {
            "host": "kmaster",
            "pool": "seats",
            "since": _z(since),
            "share_free": 0.1,
            "holders": HOLDERS[:1],
        }
    }


@pytest.mark.integration
async def test_a_spell_is_told_once(agent, sent):
    t0 = datetime.now(UTC)
    _spell(agent, t0)
    await _tell(agent, t0 + timedelta(seconds=61))
    await _tell(agent, t0 + timedelta(seconds=120))
    assert sent == [
        (
            "samscrape/prd",
            "shiftlead · kmaster temporary space low (seats): 10% free. Largest: ao-big (at least 1,200 files)\n"
            "http://kmaster:8765/inbox?row=disk_low%3Akmaster%3Aseats",
        )
    ]


@pytest.mark.integration
async def test_a_snoozed_row_is_not_told_and_the_home_accepts_the_snooze(agent, sent):
    t0 = datetime.now(UTC)
    _spell(agent, t0)
    until = _z(t0 + timedelta(minutes=2))
    got = await agent.rpc_attention_snooze("disk_low:kmaster:seats", "disk_low", until)
    assert got["row"] == "disk_low:kmaster:seats|disk_low"
    await _tell(agent, t0 + timedelta(seconds=61))
    await _tell(agent, t0 + timedelta(minutes=3))
    assert sent == []
    with pytest.raises(RpcError, match="cannot snooze"):
        await agent.rpc_attention_snooze("disk_low:kmaster:seats", "disk_low", until, caller="ao-x-w")


# -- the row --------------------------------------------------------------------------------------------------------


def _spells() -> dict:
    since = _z(datetime.now(UTC) - timedelta(hours=1))
    return {
        "kmaster:seats": {"host": "kmaster", "pool": "seats", "since": since, "share_free": 0.1, "holders": HOLDERS},
    }


@pytest.mark.unit
def test_the_row_is_counted_under_needs_you_and_snoozed_by_its_key():
    from shiftlead.ui.app import disk_low_rows, inbox_sections

    rows = disk_low_rows(_spells())
    assert rows[0]["subject"] == "Temporary space" and rows[0]["sid"] == "disk_low:kmaster:seats"
    s = inbox_sections([], states=rows)
    assert [e["row"] for e in s["needs"]] == ["disk_low"] and s["count"] == 1
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    s = inbox_sections([], states=rows, attention_snoozed={"disk_low:kmaster:seats|disk_low": until})
    assert s["needs"] == [] and [e["row"] for e in s["snoozed"]] == ["disk_low"]
    assert disk_low_rows(None) == [] and disk_low_rows({"bad": "x"}) == [] and disk_low_rows("x") == []


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
            host = {"name": "kmaster", "disk_low": _spells()}
            return {"repos": {}, "doing_log": {}, "list": [], "usage": {}, "host": host}.get(method, {})

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    html = c.get("/inbox").text
    assert "kmaster temporary space low (seats): 10% free. Largest: ao-big (at least 1,200 files), pip (1 file)" in html
    assert 'data-sid="disk_low:kmaster:seats" data-row="disk_low" data-when="1w"' in html
    assert 'data-msg="disk_low:kmaster:seats"' in html  # the message's `?row=` lands on it
    assert c.get("/api/person/inbox").json()["needs"] == 1
