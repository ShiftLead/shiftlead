"""TD-710 slice 1, design §4.4 *A new entry settles before it is pickable* (TD-707): the home's clock,
`ledger_seen.json`, records each id a fresh reading holds, and the reading's entries carry `settling:
{until}` (or `held: {at}`) while their Kind's window runs; a marked entry matches no lane."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import ledger, modes, paths, settle
from sessionorc.agent_common import RpcError
from sessionorc.agent_tick import TickMixin
from sessionorc.client import AgentError, LocalClient

T0 = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
SPANS = settle.durations(None, None)  # the built-in: design-first 5m, the rest 0
GRINDER = ["free-pick", "owner:grinder"]
DESIGNER = ["design-first"]


def _entry(n: int, kind: str = "design-first", body: str = "") -> str:
    return f"## TD-{n:03d}: entry {n}\n\n**Priority:** Medium\n**Owner:** grinder\n**Kind:** {kind}\n\n{body}\n"


def _ledger(*parts: str) -> list[dict]:
    return ledger.entries("# Ledger\n\n" + "\n".join(parts))


@pytest.fixture(autouse=True)
def _fresh_clock(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _by_id(entries: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in entries}


def test_durations_layer_key_by_key_and_a_bad_value_falls_through():
    assert settle.durations(None, None) == {"design-first": 300}
    assert settle.durations({"design-first": "1h", "build": "2m"}, {"design-first": "10m"}) == {
        "design-first": 600,
        "build": 120,
    }
    assert settle.durations({"design-first": "soon"}, None) == {"design-first": 300}  # a typo keeps the layer below
    assert settle.durations(None, {"design-first": 0}) == {"design-first": 0}
    assert settle.parse_duration("90") == 90 and settle.parse_duration("2d") == 172800
    with pytest.raises(ValueError):
        settle.parse_duration(True)


def test_a_repos_first_reading_settles_every_id_it_holds():
    got = settle.observe(_ledger(_entry(1), _entry(2, "build")), "o/r", SPANS, T0)
    assert all("settling" not in e and "held" not in e for e in got)
    seen = json.loads(paths.ledger_seen_file().read_text())["o/r"]
    assert seen["TD-001"]["at"] == settle.EPOCH and seen["TD-001"]["sig"] == got[0]["sig"]


def test_a_new_design_first_entry_is_withheld_for_its_window_and_a_build_goes_at_once():
    settle.observe(_ledger(_entry(1)), "o/r", SPANS, T0)  # the first reading
    later = T0 + timedelta(minutes=1)
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(2), _entry(3, "build"), _entry(4, "")), "o/r", SPANS, later))
    assert got["TD-002"]["settling"] == {"until": (later + timedelta(minutes=5)).isoformat()}
    assert "settling" not in got["TD-003"] and "settling" not in got["TD-004"]  # no Kind reads as build
    assert not ledger.lane_matches(DESIGNER, got["TD-002"]) and ledger.lane_matches(GRINDER, got["TD-003"])
    # a carried reading is marked again from the record: the window ends when its time does
    after = T0 + timedelta(minutes=7)
    marked = _by_id(settle.mark(list(got.values()), "o/r", SPANS, after))
    assert "settling" not in marked["TD-002"] and ledger.lane_matches(DESIGNER, marked["TD-002"])


def test_an_edit_inside_the_window_restarts_it_and_one_after_settling_does_not():
    settle.observe(_ledger(), "o/r", SPANS, T0)
    t1 = T0 + timedelta(minutes=1)
    settle.observe(_ledger(_entry(2)), "o/r", SPANS, t1)
    t2 = T0 + timedelta(minutes=4)
    got = _by_id(settle.observe(_ledger(_entry(2, body="a second thought")), "o/r", SPANS, t2))
    assert got["TD-002"]["settling"] == {"until": (t2 + timedelta(minutes=5)).isoformat()}
    t3 = t2 + timedelta(minutes=6)
    got = _by_id(settle.observe(_ledger(_entry(2, body="a third, after it settled")), "o/r", SPANS, t3))
    assert "settling" not in got["TD-002"]
    seen = json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]
    assert seen["at"] == t2.isoformat() and seen["sig"] == got["TD-002"]["sig"]


def test_a_held_entry_is_withheld_past_its_window_until_an_edit_ends_the_hold():
    settle.observe(_ledger(), "o/r", SPANS, T0)
    settle.observe(_ledger(_entry(2)), "o/r", SPANS, T0)
    store = json.loads(paths.ledger_seen_file().read_text())
    store["o/r"]["TD-002"]["held"] = {"at": T0.isoformat(), "by": "person"}  # slice 2's td_hold writes this
    paths.ledger_seen_file().write_text(json.dumps(store))
    much_later = T0 + timedelta(days=2)
    got = _by_id(settle.observe(_ledger(_entry(2)), "o/r", SPANS, much_later))
    assert got["TD-002"]["held"] == {"at": T0.isoformat()} and "settling" not in got["TD-002"]
    assert not ledger.lane_matches(DESIGNER, got["TD-002"])
    got = _by_id(settle.observe(_ledger(_entry(2, body="the person's edit landed")), "o/r", SPANS, much_later))
    assert (
        "held" not in got["TD-002"]
        and got["TD-002"]["settling"]["until"] == (much_later + timedelta(minutes=5)).isoformat()
    )


def test_in_lanes_counts_a_settling_entry_in_no_lane_and_not_in_the_rest():
    settle.observe(_ledger(), "o/r", SPANS, T0)
    got = settle.observe(_ledger(_entry(2, "build"), _entry(3, "build")), "o/r", {"build": 600}, T0)
    lanes = ledger.in_lanes(
        [{**e, "for_page": "pickable"} for e in got], [{"id": "g", "name": "g", "lane": GRINDER, "state": "idle"}]
    )
    assert lanes["pickable"] == [] and lanes["rest"] == []


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_the_repo_reading_is_marked_with_the_repos_settle_over_the_installs(tmp_path):
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    (root / ".shiftlead.yml").write_text("settle: {design-first: 10m}\n")
    (paths.home() / "settings.yml").write_text("settle: {design-first: 1m, build: 1m}\n")
    led = root / "docs" / "technical_debt.md"
    led.write_text("# Ledger\n\n" + _entry(1))
    _git(root, "init", "-q")
    # no origin known yet: the clock records nothing, so a later first reading is not under another key
    assert "settling" not in TickMixin._read_repos([str(root)], {}, set())[str(root)]["ledger"]["entries"][0]
    assert not paths.ledger_seen_file().exists()
    _git(root, "remote", "add", "origin", "https://github.com/o/r.git")
    first = TickMixin._read_repos([str(root)], {}, {str(root)})
    assert "settling" not in first[str(root)]["ledger"]["entries"][0]  # the first reading: settled
    led.write_text("# Ledger\n\n" + _entry(1) + "\n" + _entry(2) + "\n" + _entry(3, "build"))
    got = _by_id(TickMixin._read_repos([str(root)], first, {str(root)})[str(root)]["ledger"]["entries"])
    until = datetime.fromisoformat(got["TD-002"]["settling"]["until"])
    assert timedelta(minutes=9) < until - datetime.now(UTC) <= timedelta(minutes=10)  # the repo's 10m
    assert datetime.fromisoformat(got["TD-003"]["settling"]["until"]) - datetime.now(UTC) <= timedelta(minutes=1)


def test_a_clock_that_cannot_be_written_marks_no_settling_says_so_and_still_marks_waits(tmp_path, caplog):
    paths.ledger_seen_file().mkdir(parents=True)  # a directory in its place: the write raises OSError
    root = tmp_path / "r"
    root.mkdir()
    got = _ledger(
        _entry(1),
        _entry(2).replace("**Kind:** design-first\n", "**Kind:** design-first\n**Waits:** event — the next sync PR\n"),
    )
    with caplog.at_level("WARNING", logger="shiftlead.agent"):
        TickMixin._settle(str(root), "https://github.com/o/r.git", got, T0, fresh=True)  # does not raise (TD-719)
    assert all("settling" not in e and "held" not in e for e in got)  # entries go at once
    assert _by_id(got)["TD-002"]["waiting"] == {"on": "event", "until": ""}  # a wait needs no clock
    assert "the settle clock of" in caplog.text and "could not be kept" in caplog.text


def test_a_checkout_with_no_origin_is_marked_from_the_record_under_its_path(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    got = _ledger(_entry(1), _entry(2))
    now = datetime.now(UTC)
    rec = {
        "TD-001": {"at": settle.EPOCH, "sig": got[0]["sig"]},
        "TD-002": {"at": now.isoformat(), "sig": got[1]["sig"]},
    }
    paths.ledger_seen_file().write_text(json.dumps({str(root): rec}))
    TickMixin._settle(str(root), "", got, now, fresh=True)  # no origin: marked, never recorded (TD-719)
    assert "settling" not in got[0]
    assert got[1]["settling"] == {"until": (now + timedelta(minutes=5)).isoformat()}
    assert json.loads(paths.ledger_seen_file().read_text()) == {str(root): rec}


def test_a_partial_reading_keeps_the_records_it_does_not_hold():
    settle.observe(_ledger(), "o/r", SPANS, T0)
    settle.observe(_ledger(_entry(2)), "o/r", SPANS, T0)
    store = json.loads(paths.ledger_seen_file().read_text())
    store["o/r"]["TD-002"]["held"] = {"at": T0.isoformat(), "by": "person"}
    paths.ledger_seen_file().write_text(json.dumps(store))
    settle.observe(_ledger(_entry(3, "build")), "o/r", SPANS, T0 + timedelta(minutes=1))  # TD-002 missing
    got = _by_id(settle.observe(_ledger(_entry(2)), "o/r", SPANS, T0 + timedelta(days=1)))
    assert got["TD-002"]["held"] == {"at": T0.isoformat()}, "the hold survived the reading that lacked it"


# -- slice 2: Hold and the claim (§4.4 *Hold*, §4.8 *A claim is a lease*) ------------------------------------


def _settling_two(t: datetime = T0) -> dict[str, dict]:
    """A first reading, then TD-002 (design-first, settling) and TD-003 (build, settled at once)."""
    settle.observe(_ledger(), "o/r", SPANS, t)
    return _by_id(settle.observe(_ledger(_entry(2), _entry(3, "build")), "o/r", SPANS, t))


def test_a_hold_withholds_past_the_window_and_a_release_makes_it_pickable_at_once():
    got = _settling_two()
    rec = settle.hold("o/r", got["TD-002"], SPANS, T0 + timedelta(minutes=1), by="person")
    assert rec["held"] == {"at": (T0 + timedelta(minutes=1)).isoformat(), "by": "person"}
    assert settle.hold("o/r", got["TD-002"], SPANS, T0 + timedelta(minutes=2), by="person") == rec, "held already"
    later = _by_id(settle.mark(list(got.values()), "o/r", SPANS, T0 + timedelta(days=1)))
    assert "held" in later["TD-002"] and not ledger.lane_matches(DESIGNER, later["TD-002"])
    settle.hold("o/r", got["TD-002"], SPANS, T0 + timedelta(days=1), by="person", release=True)
    now = _by_id(settle.mark(list(got.values()), "o/r", SPANS, T0 + timedelta(days=1)))
    assert "held" not in now["TD-002"] and "settling" not in now["TD-002"]
    # a release inside what was the window frees it at once too, and an edit after it changes nothing
    got = _by_id(settle.observe(_ledger(_entry(4)), "o/r", SPANS, T0))
    settle.hold("o/r", got["TD-004"], SPANS, T0, by="person")
    settle.hold("o/r", got["TD-004"], SPANS, T0, by="person", release=True)
    edited = _by_id(settle.observe(_ledger(_entry(4, body="an edit")), "o/r", SPANS, T0 + timedelta(seconds=30)))
    assert "settling" not in edited["TD-004"] and ledger.lane_matches(DESIGNER, edited["TD-004"])


def test_a_settled_entry_cannot_be_held_and_an_unheld_one_cannot_be_released():
    got = _settling_two()
    with pytest.raises(settle.Refused, match="TD-003 has settled, and a hold is a settling entry's"):
        settle.hold("o/r", got["TD-003"], SPANS, T0, by="person")  # a build: settled at once
    with pytest.raises(settle.Refused, match="TD-002 has settled"):
        settle.hold("o/r", got["TD-002"], SPANS, T0 + timedelta(minutes=6), by="person")
    with pytest.raises(settle.Refused, match="TD-002 is not held"):
        settle.hold("o/r", got["TD-002"], SPANS, T0, by="person", release=True)
    with pytest.raises(settle.Refused, match="TD-009 is not in the home's clock"):
        settle.hold("o/r", {"id": "TD-009"}, SPANS, T0, by="person")
    assert "held" not in json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]


def test_the_claim_refusal_names_the_window_or_the_hold():
    got = _settling_two()
    words = settle.claim_refusal(got["TD-002"], T0)
    until = (T0 + timedelta(minutes=5)).astimezone()
    assert words.startswith(f"TD-002 settles until {until:%H:%M}: ") and "--force does not pass it" in words
    assert settle.claim_refusal(got["TD-002"], T0 + timedelta(minutes=5)) is None, "a stale mark past its until"
    assert settle.claim_refusal(got["TD-003"], T0) is None and settle.claim_refusal(None, T0) is None
    words = settle.claim_refusal({"id": "TD-002", "held": {"at": T0.isoformat()}}, T0)
    assert words.startswith(f"TD-002 is held by the person since {T0.astimezone():%H:%M}: no lane takes it")


async def _home_with(agent, tmp_path, *, now: datetime) -> tuple[str, list[dict]]:
    """The agent reading a repo whose TD-002 settles, as the tick would leave it."""
    root = str(tmp_path / "r")
    got = _settling_two(now)
    agent._repos[root] = {"name": "r", "root": root, "remote": "https://github.com/o/r.git",
                          "ledger": {"entries": list(got.values())}}  # fmt: skip
    return root, agent._repos[root]["ledger"]["entries"]


async def test_td_hold_is_the_persons_and_marks_the_reading_at_once(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    with pytest.raises(RpcError, match="ao-w cannot hold a ledger entry: a person's own act"):
        await agent.rpc_td_hold(repo=root, id="TD-002", caller="ao-w")
    got = await agent.rpc_td_hold(repo="r", id="td-002")
    assert got["repo"] == "r" and got["id"] == "TD-002" and got["held"]["at"] and got["settling"] is None
    assert "held" in _by_id(entries)["TD-002"], "the reading is marked now, not at the next pass"
    got = await agent.rpc_td_hold(repo=root, id="TD-002", release=True)
    assert got["held"] is None and got["settling"] is None and "held" not in _by_id(entries)["TD-002"]
    with pytest.raises(RpcError, match="TD-003 has settled"):
        await agent.rpc_td_hold(repo=root, id="TD-003")
    with pytest.raises(RpcError, match="TD-404 is not an open entry of r's ledger"):
        await agent.rpc_td_hold(repo=root, id="TD-404")
    with pytest.raises(RpcError, match="elsewhere is not a repo this home reads"):
        await agent.rpc_td_hold(repo="elsewhere", id="TD-002")
    assert modes.offline_refusal("td_hold", None, {}, host="laptop", home="kmaster")


async def test_a_claim_on_a_settling_or_held_entry_is_refused_with_force_too(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        for force in (False, True):
            with pytest.raises(AgentError, match="TD-002 settles until .*--force does not pass it"):
                await person.call("progress", id=g, ref="TD-002", status="claimed", force=force)
        await agent.rpc_td_hold(repo=root, id="TD-002")
        with pytest.raises(AgentError, match="TD-002 is held by the person since"):
            await person.call("progress", id=g, ref="TD-002", status="claimed", force=True)
        await person.call("progress", id=g, ref="TD-003", status="claimed")  # a build: settled at once
        await agent.rpc_td_hold(repo=root, id="TD-002", release=True)
        await person.call("progress", id=g, ref="TD-002", status="claimed")
        assert {e.ref for e in agent.sessions[g].progress} >= {"TD-002", "TD-003"}


async def test_the_claimer_of_an_entry_the_person_then_holds_still_reports_on_it(agent, tmp_path):
    """The settle refusal is a claim's (design §4.8 *A claim is a lease*, TD-726): a session that took
    TD-002 before the home read its repo, whose entry the person then holds, reports `done` on it as on
    any claim — refused, it could not say what became of its work."""
    await park_ticks(agent)
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = str(tmp_path / "r")
        await person.call("progress", id=g, ref="TD-002", status="claimed")  # the repo not read yet: no refusal
        root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
        await agent.rpc_td_hold(repo=root, id="TD-002")
        with pytest.raises(AgentError, match="TD-002 is held by the person since"):
            await person.call("progress", id=g, ref="TD-002", status="claimed")  # a claim is still refused
        await person.call("progress", id=g, ref="TD-002", status="done", why="built")
        assert next(e for e in agent.sessions[g].progress if e.ref == "TD-002").status == "done"
