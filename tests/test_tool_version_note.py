"""TD-1727 (TD-1650's second build), design §4.3 *An upgraded seat tool asks for the smoke*: on the home's tick, at
most every `VERSION_EVERY`, the home compares per adapter, seat profile and host the newest seat record's
`tool_version` with the one `tool_versions.json` last noted; a first sight is written and says nothing, the changes
go to the person in one `system` note at most every `VERSION_NOTE_EVERY`, and nothing is run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import kill_private_server, private_socket_name

from sessionorc import adapters, agent_tick, mail
from sessionorc.agent import HostAgent
from sessionorc.models import Session
from sessionorc.tmux import Tmux

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
LEAD1 = "A seat tool changed version; the home knows of no smoke on it."


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    adapters.names()
    monkeypatch.setitem(adapters._REGISTRY, "fake", SimpleNamespace(name="fake", label="Fake Tool"))
    monkeypatch.setitem(adapters._REGISTRY, "other", SimpleNamespace(name="other", label="Other Tool"))
    return tmp_path / "home"


@pytest.fixture
def agents(home):
    made: list[HostAgent] = []

    def make() -> HostAgent:
        a = HostAgent(tmux=Tmux(socket_name=private_socket_name()))
        made.append(a)
        return a

    yield make
    for a in made:
        kill_private_server(a.tmux)


_n = iter(range(10_000))


def rec(a: HostAgent, version: str | None, *, adapter="fake", profile="seatp", host=None, created=None, seat=True):
    """A seat record on the agent (its own host's in `sessions`, a node's in `remote`)."""
    i = next(_n)
    host = host or a.host
    s = Session(
        id=f"ao-s{i}",
        name=f"s{i}",
        kind="interactive",
        adapter=adapter,
        dir="/tmp",
        profile=profile,
        created=created or f"2026-11-12T08:{i % 60:02d}:00Z",
        seat={"trigger": "asks"} if seat else None,
        tool_version=version,
        host=host,
    )
    if host == a.host:
        a.sessions[s.id] = s
    else:
        a.remote.setdefault(host, {})[s.id] = s
    return s


def notes(a: HostAgent) -> list[str]:
    return [e.text for e in a.person_inbox if e.from_ == "system" and "seat tool" in e.text]


def stored(home) -> dict:
    return json.loads((home / "tool_versions.json").read_text())


def compare(a: HostAgent, now: datetime = T0) -> None:
    a._compare_versions(now)


@pytest.mark.unit
def test_first_sight_writes_and_sends_nothing(home, agents):
    a = agents()
    rec(a, "1.0.0")
    compare(a)
    assert notes(a) == []
    got = stored(home)
    assert got["versions"]["fake"]["seatp"][a.host]["version"] == "1.0.0"
    assert "noted_at" not in got


@pytest.mark.unit
def test_a_change_sends_one_note_and_a_second_tick_none(home, agents):
    a = agents()
    rec(a, "1.0.0")
    compare(a)
    rec(a, "1.1.0")
    compare(a)
    (n,) = notes(a)
    assert n.startswith(LEAD1 + "\n")
    assert mail.subject_of(n) == LEAD1
    assert "Fake Tool on profile seatp moved from 1.0.0 to 1.1.0 on " + a.host in n
    assert "Run it: `pdm run conformance fake --profile seatp --smoke`" in n
    compare(a, T0 + timedelta(days=2))
    assert len(notes(a)) == 1
    got = stored(home)
    assert got["versions"]["fake"]["seatp"][a.host]["version"] == "1.1.0"
    assert got["noted_at"] == "2026-11-12T09:00:00Z"


@pytest.mark.unit
def test_a_move_back_is_a_change(home, agents):
    a = agents()
    rec(a, "1.1.0")
    compare(a)
    rec(a, "1.0.0")
    compare(a)
    assert "moved from 1.1.0 to 1.0.0" in notes(a)[0]


@pytest.mark.unit
def test_the_newest_record_is_by_created(home, agents):
    a = agents()
    rec(a, "1.0.0", created="2026-11-12T08:00:00Z")
    compare(a)
    rec(a, "2.0.0", created="2026-11-12T10:00:00Z")
    rec(a, "1.0.0", created="2026-11-12T09:00:00Z")  # stored after, created before
    compare(a)
    assert "moved from 1.0.0 to 2.0.0" in notes(a)[0]


@pytest.mark.unit
def test_two_hosts_are_two_entries_and_never_renote_each_other(home, agents):
    a = agents()
    rec(a, "1.0.0")
    rec(a, "2.0.0", host="nodeb")
    compare(a)
    compare(a, T0 + timedelta(days=2))
    assert notes(a) == []
    v = stored(home)["versions"]["fake"]["seatp"]
    assert v[a.host]["version"] == "1.0.0" and v["nodeb"]["version"] == "2.0.0"


@pytest.mark.unit
def test_two_adapters_on_the_default_profile_are_two_entries(home, agents):
    a = agents()
    rec(a, "1.0.0", profile="")
    rec(a, "9.0.0", adapter="other", profile="")
    compare(a)
    compare(a, T0 + timedelta(days=2))
    assert notes(a) == []
    got = stored(home)["versions"]
    assert got["fake"][""][a.host]["version"] == "1.0.0"
    assert got["other"][""][a.host]["version"] == "9.0.0"


@pytest.mark.unit
def test_two_changes_in_one_tick_are_one_note(home, agents):
    a = agents()
    rec(a, "1.0.0")
    rec(a, "9.0.0", adapter="other")
    compare(a)
    rec(a, "1.1.0")
    rec(a, "9.1.0", adapter="other")
    compare(a)
    (n,) = notes(a)
    lead = "2 seat tools changed version; the home knows of no smoke on them."
    assert n.split("\n")[0] == lead and mail.subject_of(n) == lead
    assert len(n.split("\n")) == 3


@pytest.mark.unit
def test_a_change_inside_the_day_waits_and_is_noted_from_the_last_noted_across_a_restart(home, agents):
    a = agents()
    rec(a, "1.0.0")
    compare(a)
    rec(a, "1.1.0")
    compare(a)  # noted at T0
    rec(a, "1.2.0")
    compare(a, T0 + timedelta(hours=2))
    assert len(notes(a)) == 1
    assert stored(home)["versions"]["fake"]["seatp"][a.host]["version"] == "1.1.0"
    b = agents()  # a restart: the day is read from the file
    rec(b, "1.3.0")
    compare(b, T0 + timedelta(hours=3))
    assert not [n for n in notes(b) if "1.3.0" in n]
    compare(b, T0 + timedelta(days=1, minutes=1))
    assert "moved from 1.1.0 to 1.3.0" in [n for n in notes(b) if "1.3.0" in n][0]


@pytest.mark.unit
def test_a_first_sight_inside_the_day_is_written(home, agents):
    a = agents()
    rec(a, "1.0.0")
    compare(a)
    rec(a, "1.1.0")
    compare(a)  # noted
    rec(a, "5.0.0", profile="newp")
    compare(a, T0 + timedelta(hours=1))
    assert stored(home)["versions"]["fake"]["newp"][a.host]["version"] == "5.0.0"


@pytest.mark.unit
def test_the_default_profile_line_reads_default_and_says_it_is_smoked_only_if_set_aside(home, agents):
    a = agents()
    rec(a, "1.0.0", profile="")
    compare(a)
    rec(a, "1.1.0", profile="")
    compare(a)
    (n,) = notes(a)
    assert "Fake Tool on the default profile moved from 1.0.0 to 1.1.0" in n
    assert "`pdm run conformance fake --profile <default> --smoke`" in n
    assert "only if it has a `config_dir` set aside, else it cannot be smoked" in n
    assert stored(home)["versions"]["fake"][""][a.host]["version"] == "1.1.0"


@pytest.mark.unit
def test_a_nodes_line_says_run_it_on_the_host(home, agents):
    a = agents()
    rec(a, "1.0.0", host="nodeb")
    compare(a)
    rec(a, "1.1.0", host="nodeb")
    compare(a)
    (n,) = notes(a)
    assert "on nodeb;" in n
    assert "Run it on nodeb, from a checkout there: `pdm run conformance fake --profile seatp --smoke`" in n
    assert "Run it:" not in n


@pytest.mark.unit
def test_non_seat_records_and_a_dropped_seat_are_not_read(home, agents):
    a = agents()
    rec(a, "1.0.0", seat=False)
    compare(a)
    assert not (home / "tool_versions.json").exists()
    s = rec(a, "1.0.0")
    compare(a)
    s.seat = None  # the seat dropped: no longer read
    rec(a, "2.0.0", seat=False)
    compare(a)
    assert notes(a) == []


@pytest.mark.unit
def test_a_pool_member_and_a_resumed_seat_are_read(home, agents):
    """A pool's member (a scaled seat's extra) and a resumed seat carry `seat` as any seat does (teams.py
    `seat_params`), so each is read."""
    a = agents()
    m = rec(a, "1.0.0", profile="poolp")
    m.scale = {"line": "techlead"}  # a scaled seat's extra: its line, and its seat
    compare(a)
    assert stored(home)["versions"]["fake"]["poolp"][a.host]["version"] == "1.0.0"
    r = rec(a, "1.1.0", profile="poolp")
    r.supersedes = [{"id": m.id, "mail": True, "at": r.created}]  # a resumed seat's record
    compare(a)
    assert "Fake Tool on profile poolp moved from 1.0.0 to 1.1.0" in notes(a)[0]


@pytest.mark.unit
def test_a_seat_made_in_place_carries_no_version_and_is_skipped(home, agents):
    a = agents()
    rec(a, None)
    compare(a)
    assert not (home / "tool_versions.json").exists()


@pytest.mark.unit
def test_no_record_carrying_a_version_leaves_the_file_alone(home, agents):
    (home / "tool_versions.json").write_text(json.dumps({"versions": {"fake": {"seatp": {"h": {"version": "1"}}}}}))
    before = (home / "tool_versions.json").read_text()
    a = agents()
    compare(a)
    assert (home / "tool_versions.json").read_text() == before
    assert notes(a) == []


@pytest.mark.unit
def test_an_unreadable_file_reads_as_empty(home, agents):
    (home / "tool_versions.json").write_text("{not json")
    a = agents()
    rec(a, "1.0.0")
    compare(a)
    assert notes(a) == []
    assert stored(home)["versions"]["fake"]["seatp"][a.host]["version"] == "1.0.0"


@pytest.mark.unit
def test_a_noted_at_in_the_future_reads_as_lapsed(home, agents):
    a = agents()
    rec(a, "1.0.0")
    compare(a)
    got = stored(home)
    got["noted_at"] = "2027-01-01T00:00:00Z"
    (home / "tool_versions.json").write_text(json.dumps(got))
    rec(a, "1.1.0")
    compare(a)
    assert len(notes(a)) == 1


@pytest.mark.unit
def test_an_unregistered_adapter_falls_back_to_its_name(home, agents):
    a = agents()
    rec(a, "1.0.0", adapter="nodes-own")
    compare(a)
    rec(a, "1.1.0", adapter="nodes-own")
    compare(a)
    (n,) = notes(a)
    assert "nodes-own on profile seatp moved" in n
    assert "`pdm run conformance nodes-own --profile seatp --smoke`" in n


async def test_a_nodes_tick_skips_the_pass_and_the_home_reads_hourly(home, agents, monkeypatch):
    a = agents()
    rec(a, "1.0.0")
    a.mode = "node"
    await a._version_notes()
    assert not (home / "tool_versions.json").exists()
    a.mode = "home"
    await a._version_notes()
    assert stored(home)["versions"]["fake"]["seatp"][a.host]["version"] == "1.0.0"
    rec(a, "1.1.0")
    await a._version_notes()  # inside VERSION_EVERY: not read again
    assert notes(a) == []
    monkeypatch.setattr(agent_tick, "VERSION_EVERY", 0.0)
    await a._version_notes()
    assert len(notes(a)) == 1


async def test_the_pass_never_raises(home, agents, monkeypatch):
    a = agents()

    def boom(now):
        raise RuntimeError("x")

    monkeypatch.setattr(a, "_compare_versions", boom)
    await a._version_notes()
