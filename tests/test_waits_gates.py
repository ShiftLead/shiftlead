"""An entry that waits on an `until` or `event` gate reads as waiting, not blocked (design §4.4 *An entry says
what it waits for*, *What a wait does*; §4.5a *Repo page: waits mark*; §4.4 *Waiting*; TD-1392's design,
built by TD-1395): the `waiting` mark from the gates, the page kind read past them, the lanes counting it
under `waiting`, the claim refused with its word, the Queue card's leaf and the Repo page's row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks
from test_queue import NOW as QNOW
from test_queue import _by_id, _cards, _repo

from sessionorc import ledger, settle
from sessionorc.client import AgentError, LocalClient
from shiftlead import teamrun
from shiftlead.ui import repo as repo_ui

NOW = datetime.now(UTC)
TODAY = NOW.date()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
LATER = (TODAY + timedelta(days=9)).isoformat()
GRINDER = ["free-pick", "owner:grinder"]
EVENT = "**Event (flake-again):** the test fails again in a precheck\ncheck: pr-merged o/r#5\n"


def _entry(n: int, blocked: str = "", kind: str = "build", event: bool = False, owner: str = "grinder") -> str:
    head = f"## TD-{n:03d}: entry {n}\n\n**Priority:** Medium\n**Owner:** {owner}\n**Kind:** {kind}\n**Status:** Open\n"
    head += f"**Blocked by:** {blocked}\n" if blocked else ""
    return head + "\n**Why:** a reason.\n" + (f"\n{EVENT}" if event else "")


def _read(*parts: str, now: datetime = NOW, archive: str = "", live=None) -> dict[str, dict]:
    got = settle.mark_waits(ledger.entries("# Ledger\n\n" + "\n".join(parts), archive or None, live=live), now)
    return {e["id"]: e for e in got}


def test_an_until_and_an_event_gate_are_marked_waiting_and_sorted_by_their_kind():
    got = _read(
        _entry(1, f"until {TOMORROW}"),
        _entry(2, "event (flake-again)", event=True),
        _entry(3, f"until {LATER}", kind="design-first"),
    )
    assert got["TD-001"]["waiting"] == {"on": "until", "until": TOMORROW, "name": "", "why": ""}
    assert got["TD-002"]["waiting"] == {
        "on": "event",
        "until": "",
        "name": "flake-again",
        "why": "the test fails again in a precheck",
    }
    assert got["TD-001"]["pickable"] == "no", "ledgerboard keeps it from pickable; the mark says why"
    assert [got[i]["for_page"] for i in ("TD-001", "TD-002", "TD-003")] == ["pickable", "pickable", "design"]
    entries = list(got.values())
    assert not any(ledger.lane_matches(GRINDER, e) for e in entries)
    records = [{"id": "w1", "name": "w1", "lane": GRINDER, "state": "idle", "out_of_work": {"at": "x"}}]
    lanes = ledger.in_lanes(entries, records)
    assert lanes["waiting"] == {"until": ["TD-001"], "event": ["TD-002"]}
    assert lanes["out_of_work"] == [] and lanes["out_of_work_waiting"][0]["waiting"] == ["TD-001", "TD-002"]


def test_an_until_of_todays_utc_day_is_not_waiting():
    got = _read(_entry(1, f"until {TODAY.isoformat()}"))["TD-001"]
    assert "waiting" not in got and got["pickable"] == "yes" and ledger.lane_matches(GRINDER, got)


def test_a_carried_reading_stops_waiting_on_the_dates_utc_day():
    got = _read(_entry(1, f"until {TOMORROW}"))
    later = settle.mark_waits(list(got.values()), NOW + timedelta(days=1))[0]
    assert "waiting" not in later and later["pickable"] == "yes" and later["blocked_by"] == []
    assert ledger.lane_matches(GRINDER, later), "it enters free-pick on its day"


def test_an_until_still_standing_beside_an_event_is_on_until_then_on_the_event():
    got = _read(_entry(1, f"until {TOMORROW}, event (flake-again)", event=True))
    assert got["TD-001"]["waiting"]["on"] == "until" and got["TD-001"]["waiting"]["until"] == TOMORROW
    later = settle.mark_waits(list(got.values()), NOW + timedelta(days=1))[0]
    assert later["waiting"]["on"] == "event" and later["waiting"]["name"] == "flake-again"


def test_a_waiting_live_check_naming_a_live_build_is_counted_under_its_lanes_waiting():
    got = _read(_entry(1, f"until {TOMORROW}", kind="live-check #5"), live=lambda n: True)
    e = got["TD-001"]
    assert e["for_page"] == "live-check" and e["live"] == "yes" and e["waiting"]["on"] == "until"
    assert ledger.lane_matches(GRINDER, ledger._unwaited(e)) and not ledger.lane_matches(GRINDER, e)
    lanes = ledger.in_lanes([e], [{"id": "w1", "name": "w1", "lane": GRINDER, "state": "idle"}])
    assert lanes["waiting"]["until"] == ["TD-001"]


def test_a_recheck_build_with_a_future_until_is_in_no_lane_and_enters_free_pick_on_its_day():
    then = datetime.combine(TODAY + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=1)
    assert not ledger.lane_matches(GRINDER, _read(_entry(1, f"until {TOMORROW}"))["TD-001"])
    on_the_day = settle.mark_waits(ledger.entries("# Ledger\n\n" + _entry(1, f"until {TOMORROW}")), then)[0]
    assert "waiting" not in on_the_day and ledger.lane_matches(GRINDER, on_the_day)


def test_an_open_id_or_a_decision_beside_a_gate_is_not_waiting():
    got = _read(
        _entry(1),
        _entry(2, f"TD-001, until {TOMORROW}"),
        _entry(3, "decision (paul), event (flake-again)", event=True),
    )
    assert "waiting" not in got["TD-002"] and got["TD-002"]["for_page"] == "blocked"
    assert "waiting" not in got["TD-003"] and got["TD-003"]["for_page"] == "for-you"


def test_the_claim_refusals_words():
    got = _read(_entry(1, f"until {TOMORROW}"), _entry(2, "event (flake-again)", event=True))
    assert settle.wait_refusal(got["TD-001"]).startswith(f"TD-001 waits until {TOMORROW} (design §4.4")
    assert settle.wait_refusal(got["TD-002"]).startswith("TD-002 waits on event (flake-again) (design §4.4")


@pytest.mark.integration
async def test_a_claim_on_a_gated_entry_is_refused_and_force_passes_it(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "r")
    got = _read(_entry(1, f"until {TOMORROW}"), _entry(2, "event (flake-again)", event=True))
    agent._repos[root] = {"name": "r", "root": root, "ledger": {"entries": list(got.values())}}
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        with pytest.raises(AgentError, match=f"TD-001 waits until {TOMORROW}"):
            await person.call("progress", id=g, ref="TD-001", status="claimed")
        with pytest.raises(AgentError, match=r"TD-002 waits on event \(flake-again\)"):
            await person.call("progress", id=g, ref="TD-002", status="claimed")
        await person.call("progress", id=g, ref="TD-002", status="claimed", force=True)
        assert any(p.ref == "TD-002" for p in agent.sessions[g].progress)


def test_the_repo_pages_row_hovers_the_gate_and_omits_it_from_blocked_by():
    got = _read(
        _entry(1, f"until {TOMORROW}"),
        _entry(2, "event (flake-again)", event=True),
    )
    rows = {e["id"]: e for lst in repo_ui.ledger_lists({"ledger": {"entries": list(got.values())}}, [], None, NOW)
            for e in lst["rows"]}  # fmt: skip
    assert (
        rows["TD-001"]["wait"] == f"waits until {TOMORROW[5:]}" and rows["TD-001"]["wait_line"] == f"until {TOMORROW}"
    )
    assert rows["TD-002"]["wait"] == "waits: the test fails again in a precheck"
    assert rows["TD-002"]["wait_line"] == "event (flake-again) — the test fails again in a precheck"
    assert rows["TD-001"]["blocked_by"] == [] and rows["TD-002"]["blocked_by"] == []
    assert teamrun.wait_words(got["TD-002"]) == "waits: the test fails again in a precheck"


def test_a_queue_card_whose_member_waits_on_an_event_is_waiting_with_its_event_line(tmp_path):
    def entry(n: int, title: str, blocked: str, body: str = "") -> str:
        return f"## TD-{n:03d}: {title}\n\n**Priority:** High\n**Blocked by:** {blocked}\n\n{body}"

    root, r = _repo(tmp_path, "r", [
        entry(10, "the top", "TD-011"),
        entry(11, "waits on an event", "event (flake-again)", EVENT + "\n"),
        entry(20, "waits on a date", "until 2099-01-30"),
    ])  # fmt: skip
    settle.mark_waits(r["ledger"]["entries"], QNOW)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    assert by["TD-011"]["waiting"]["on"] == "event" and "unreachable" not in by["TD-011"]
    cards = _by_id(_cards({root: r}))
    one, two = cards["r#TD-011"], cards["r#TD-020"]  # a card is named by its root, the entry the rest wait on
    assert one["group"] == "waiting" and one["status"] == "waiting", "a gate gives no `unreachable`"
    assert one["wait"] == {"column": "event", "phrase": "waits on the test fails again in a precheck", "id": "r#TD-011"}
    assert two["group"] == "waiting" and two["wait"]["phrase"] == "waits until Jan 30"


HOSTLOG = '**Event (push-on):** the person turns push on\ncheck: host-log witnessed kind press "push-on"\n'


@pytest.mark.parametrize(
    ("blocked", "section", "on"),
    [
        ("event (push-on)", HOSTLOG, "event"),  # a home-witnessed event (TD-1295, TD-1388)
        ("event (flake-again)", EVENT, "event"),  # a typed check the forge answers
        (f"until {TOMORROW}", "", "until"),  # an occurrence nothing witnesses: the day of the next look
    ],
)
def test_a_live_checks_gate_keeps_it_out_of_the_lanes_until_it_lifts(blocked, section, on):
    """A live check whose build is live waits on its gate, not its `Kind:` line (§4.4 *An entry says what it
    waits for*, §4.9b; TD-1385): its gate marks it waiting, it stays a *live check*, and no lane takes it; the
    same entry with the gate lifted is the lane's."""
    head = "## TD-007: a live check\n\n**Priority:** Medium\n**Owner:** grinder\n"
    head += "**Kind:** live-check #5\n**Status:** Open\n"
    gated = head + f"**Blocked by:** {blocked}\n\n**Why:** a reason.\n" + (f"\n{section}" if section else "")
    got = _read(gated, live=lambda n: True)["TD-007"]
    assert got["live"] == "yes" and got["for_page"] == "live-check"
    assert got["waiting"]["on"] == on and not ledger.lane_matches(GRINDER, got), "its build is live, its gate holds"
    lifted = _read(head + "\n**Why:** a reason.\n" + (f"\n{section}" if section else ""), live=lambda n: True)
    lifted = lifted["TD-007"]
    assert "waiting" not in lifted and ledger.lane_matches(GRINDER, lifted), "lifted, it is the lane's"
