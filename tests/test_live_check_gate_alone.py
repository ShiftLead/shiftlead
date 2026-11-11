"""TD-1452 (design §4.9b *The `Kind:` line names the build; it holds nothing*, §4.4 *An entry says what it
waits for*): a live check whose build is not live is held by its `event (live…)` gate alone. The `#<n>` on
its `Kind:` line and the home's `live` reading of it are words; nothing picks, matches a lane or withholds
by them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sessionorc import ledger, settle

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


def _ev(name: str) -> str:
    return f'**Event ({name}):** The build is live.\ncheck: file-contains r@promote/live docs/ledger/TD-n.md "x"\n\n'


def _check(n: int, blocked: str = "", events: tuple[str, ...] = (), kind: str = "live-check #5") -> str:
    head = f"## TD-{n:03d}: check {n}\n\n**Priority:** High\n**Owner:** grinder\n**Kind:** {kind}\n**Status:** Built\n"
    head += f"**Blocked by:** {blocked}\n" if blocked else ""
    return head + "\n" + "".join(_ev(e) for e in events)


def _read(text: str, live_prs: set[int]) -> dict[str, dict]:
    got = ledger.entries("# L\n\n" + text, live=lambda n: n in live_prs)
    settle.mark_waits(got, NOW)
    return {e["id"]: e for e in got}


@pytest.mark.parametrize("live_prs", [set(), {5}], ids=["not-live", "live"])
def test_a_standing_live_gate_holds_whatever_the_reading_says(live_prs):
    got = _read(
        _check(1, "event (live)", ("live",))
        + _check(2, "event (live-2)", ("live", "live-2")),  # `live` lifted, the review fix's `live-2` standing
        live_prs,
    )
    want = "yes" if live_prs else "no"
    for tid, name in (("TD-001", "live"), ("TD-002", "live-2")):
        e = got[tid]
        assert e["live"] == want, "the reading is still read, for its words"
        assert e["pickable"] == "no" and e["for_page"] == "live-check"
        assert e["waiting"]["on"] == "event" and e["waiting"]["name"] == name
        assert not ledger.lane_matches(["free-pick"], e) and not ledger.lane_matches(["free-pick", "owner:grinder"], e)


def test_a_lifted_gate_is_pickable_and_free_pick_even_where_the_reading_says_no():
    e = _read(_check(1), set())["TD-001"]  # every gate lifted; the build rolled back below #5
    assert e["live"] == "no" and e["pickable"] == "yes" and "waiting" not in e
    assert ledger.kind_of(e) == "live-check" and e["for_page"] == "live-check"
    assert ledger.lane_matches(["free-pick"], e) and ledger.lane_matches(["free-pick", "owner:grinder"], e)
    assert not ledger.lane_matches(["free-pick", "owner:anchor"], e), "the owner word narrows it as a build"
    assert not ledger.lane_matches(["design-first"], e)


def test_no_open_live_check_as_td1451_left_them_becomes_pickable_by_the_switch():
    """The shapes TD-1451 left the open live checks in: each whose build was not live carries its gate, beside
    whatever else held it — a person's decision, an open id, a `until` — and the old decision form, which
    TD-1584 moves. Read with the build live or not, none is pickable or in a lane."""
    text = (
        _check(1, "event (live)", ("live",))
        + _check(2, "decision (paul), event (live)", ("live",))
        + _check(3, "TD-009, event (live)", ("live",))
        + _check(4, "event (live), until 2099-01-01", ("live",))
        + _check(5, "event (live-td9)", ("live", "live-td9"))
        + _check(6, "decision (paul) — read the page once it is promoted")
        + _check(7, "decision (techlead)")
        + "## TD-009: an open build\n\n**Priority:** High\n**Kind:** build\n"
    )
    for live_prs in (set(), {5}):
        got = _read(text, live_prs)
        checks = [e for e in got.values() if e["kind"] == "live-check"]
        assert len(checks) == 7
        for e in checks:
            assert e["pickable"] == "no", e["id"]
            assert not ledger.lane_matches(["free-pick"], e), e["id"]
            assert not ledger.lane_matches(["free-pick", "owner:grinder"], e), e["id"]
