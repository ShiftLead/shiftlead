"""TD-710 slice 1, design §4.4 *A new entry settles before it is pickable* (TD-707): the home's clock,
`ledger_seen.json`, records each id a fresh reading holds, and the reading's entries carry `settling:
{until}` (or `held: {at}`) while their Kind's window runs; a marked entry matches no lane."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import ledger, paths, settle
from sessionorc.agent_tick import TickMixin

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
    first = TickMixin._read_repos([str(root)], {}, set())
    assert "settling" not in first[str(root)]["ledger"]["entries"][0]  # the first reading: settled
    led.write_text("# Ledger\n\n" + _entry(1) + "\n" + _entry(2) + "\n" + _entry(3, "build"))
    got = _by_id(TickMixin._read_repos([str(root)], first, set())[str(root)]["ledger"]["entries"])
    until = datetime.fromisoformat(got["TD-002"]["settling"]["until"])
    assert timedelta(minutes=9) < until - datetime.now(UTC) <= timedelta(minutes=10)  # the repo's 10m
    assert datetime.fromisoformat(got["TD-003"]["settling"]["until"]) - datetime.now(UTC) <= timedelta(minutes=1)
