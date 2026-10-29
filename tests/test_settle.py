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
from sessionorc.models import PERSON, MailEntry, ProgressEntry, Session

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


def test_a_held_entry_is_withheld_past_its_window_and_an_edit_keeps_the_hold():
    settle.observe(_ledger(), "o/r", SPANS, T0)
    settle.observe(_ledger(_entry(2)), "o/r", SPANS, T0)
    store = json.loads(paths.ledger_seen_file().read_text())
    store["o/r"]["TD-002"]["held"] = {"at": T0.isoformat(), "by": "person"}  # slice 2's td_hold writes this
    paths.ledger_seen_file().write_text(json.dumps(store))
    much_later = T0 + timedelta(days=2)
    got = _by_id(settle.observe(_ledger(_entry(2)), "o/r", SPANS, much_later))
    assert got["TD-002"]["held"] == {"at": T0.isoformat(), "by": "person"} and "settling" not in got["TD-002"]
    assert not ledger.lane_matches(DESIGNER, got["TD-002"])
    got = _by_id(settle.observe(_ledger(_entry(2, body="the person's edit landed")), "o/r", SPANS, much_later))
    assert got["TD-002"]["held"] == {"at": T0.isoformat(), "by": "person"} and "settling" not in got["TD-002"], "TD-731"
    rec = json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]
    assert rec["sig"] == got["TD-002"]["sig"] and rec["held"]["at"] == T0.isoformat(), "the new sig, the hold kept"


def test_in_lanes_counts_a_settling_entry_in_no_lane_and_not_in_the_rest():
    settle.observe(_ledger(), "o/r", SPANS, T0)
    got = settle.observe(_ledger(_entry(2, "build"), _entry(3, "build")), "o/r", {"build": 600}, T0)
    lanes = ledger.in_lanes(
        [{**e, "for_page": "pickable"} for e in got], [{"id": "g", "name": "g", "lane": GRINDER, "state": "idle"}]
    )
    assert lanes["pickable"] == [] and lanes["rest"] == []


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _served(root) -> None:
    """agent-cadence's tree and its gate in `root`, which with a ledger serve it (§5 *The seams*, TD-1011)."""
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "docs" / "cadence-sync.lock").write_text("source: agent-cadence\ncommit: abc1234\nfiles_commit: abc1234\n")
    (root / "scripts" / "check_cadence.py").write_text("x = 1\n")


def test_the_repo_reading_is_marked_with_the_repos_settle_over_the_installs(tmp_path):
    root = tmp_path / "r"
    _served(root)
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


def test_an_unserved_repo_has_no_settle(tmp_path):
    """TD-1011, design §5 *The seams*: an unserved repo's reading records nothing on the settle clock and
    marks nothing settling; served, the same reading does."""
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    (root / ".shiftlead.yml").write_text("settle: {build: 10m}\n")
    led = root / "docs" / "technical_debt.md"
    led.write_text("# Ledger\n\n" + _entry(1, "build"))
    _git(root, "init", "-q")
    _git(root, "remote", "add", "origin", "https://github.com/o/r.git")
    first = TickMixin._read_repos([str(root)], {}, {str(root)})
    assert first[str(root)]["seams"]["serve"]["ok"] is False and not paths.ledger_seen_file().exists()
    led.write_text("# Ledger\n\n" + _entry(1, "build") + "\n" + _entry(2, "build"))
    got = _by_id(TickMixin._read_repos([str(root)], first, {str(root)})[str(root)]["ledger"]["entries"])
    assert "settling" not in got["TD-002"] and not paths.ledger_seen_file().exists()
    _served(root)
    TickMixin._read_repos([str(root)], {}, {str(root)})
    assert paths.ledger_seen_file().exists()


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
    assert got["TD-002"]["held"] == {"at": T0.isoformat(), "by": "person"}, (
        "the hold survived the reading that lacked it"
    )


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


def test_a_settled_entry_is_held_and_released_and_an_unheld_one_cannot_be_released():
    """TD-731 (design §4.4 *Hold*): any open entry the clock holds is held, settling or settled."""
    got = _settling_two()
    with pytest.raises(settle.Refused, match="TD-002 is not held"):
        settle.hold("o/r", got["TD-002"], SPANS, T0, by="person", release=True)
    with pytest.raises(settle.Refused, match="TD-009 is not in the home's clock"):
        settle.hold("o/r", {"id": "TD-009"}, SPANS, T0, by="person")
    assert "held" not in json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]
    rec = settle.hold("o/r", got["TD-003"], SPANS, T0, by="person")  # a build: settled at once
    assert rec["held"] == {"at": T0.isoformat(), "by": "person"}
    later = T0 + timedelta(minutes=6)
    settle.hold("o/r", got["TD-002"], SPANS, later, by="person")  # past its window
    marked = _by_id(settle.mark(list(got.values()), "o/r", SPANS, later))
    assert "held" in marked["TD-002"] and "held" in marked["TD-003"]
    assert not ledger.lane_matches(GRINDER, marked["TD-003"]) and not ledger.lane_matches(DESIGNER, marked["TD-002"])
    settle.hold("o/r", got["TD-003"], SPANS, later, by="person", release=True)
    assert ledger.lane_matches(GRINDER, _by_id(settle.mark(list(got.values()), "o/r", SPANS, later))["TD-003"])


def test_a_landed_held_id_is_held_at_its_first_reading_and_never_settles():
    """TD-731 (design §4.4 *An entry can land held*): `prehold` records `{held}` before any reading holds
    the id; its first reading records its `sig` and keeps the hold, and no window ever runs."""
    settle.observe(_ledger(_entry(1)), "o/r", SPANS, T0)
    settle.prehold("o/r", ["TD-002"], "ao-i", T0)
    rec = json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]
    assert rec == {"held": {"at": T0.isoformat(), "by": "ao-i"}}
    t1 = T0 + timedelta(minutes=1)
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(2, "build")), "o/r", SPANS, t1))
    assert got["TD-002"]["held"] == {"at": T0.isoformat(), "by": "ao-i"} and "settling" not in got["TD-002"]
    assert not ledger.lane_matches(GRINDER, got["TD-002"])
    rec = json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]
    assert rec["sig"] == got["TD-002"]["sig"] and rec["at"] == t1.isoformat()
    much_later = T0 + timedelta(days=3)
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(2, "build", "amended")), "o/r", SPANS, much_later))
    assert "held" in got["TD-002"] and "settling" not in got["TD-002"], "amended, still held"
    settle.hold("o/r", got["TD-002"], SPANS, much_later, by="person", release=True)
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(2, "build", "amended")), "o/r", SPANS, much_later))
    assert "held" not in got["TD-002"] and ledger.lane_matches(GRINDER, got["TD-002"])


def test_pre_holding_an_id_leaves_a_repos_first_reading_recording_every_other_id_settled():
    settle.prehold("o/r", ["TD-009"], "person", T0)
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(2), _entry(9)), "o/r", SPANS, T0 + timedelta(minutes=1)))
    seen = json.loads(paths.ledger_seen_file().read_text())["o/r"]
    assert seen["TD-001"]["at"] == settle.EPOCH and seen["TD-002"]["at"] == settle.EPOCH, "still a first reading"
    assert "settling" not in got["TD-001"] and "settling" not in got["TD-002"]
    assert got["TD-009"]["held"] == {"at": T0.isoformat(), "by": "person"}
    # the next reading is not a first: a new id settles from now
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(3)), "o/r", SPANS, T0 + timedelta(minutes=2)))
    assert "settling" in got["TD-003"]


def test_pre_holding_an_id_already_held_keeps_its_hold():
    """TD-744: `prehold` over an id the person holds already leaves that hold's `at` and `by` as they were."""
    settle.prehold("o/r", ["TD-002"], "person", T0)
    settle.prehold("o/r", ["TD-002"], "ao-i", T0 + timedelta(minutes=3))
    rec = json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]
    assert rec == {"held": {"at": T0.isoformat(), "by": "person"}}


def test_the_claim_refusal_names_the_window_or_the_hold():
    got = _settling_two()
    words = settle.claim_refusal(got["TD-002"], T0)
    until = (T0 + timedelta(minutes=5)).astimezone()
    assert words.startswith(f"TD-002 settles until {until:%H:%M}: ") and "--force does not pass it" in words
    assert settle.claim_refusal(got["TD-002"], T0 + timedelta(minutes=5)) is None, "a stale mark past its until"
    assert settle.claim_refusal(got["TD-003"], T0) is None and settle.claim_refusal(None, T0) is None
    words = settle.claim_refusal({"id": "TD-002", "held": {"at": T0.isoformat()}}, T0)
    assert words.startswith(
        f"TD-002 is held by the person since {T0.astimezone():%H:%M}: no lane takes it until they release it (design"
    ), "TD-731: an edit no longer ends a hold"


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
    got = await agent.rpc_td_hold(repo=root, id="TD-003")  # settled: held all the same (TD-731)
    assert got["held"]["at"] and got["told"] == [] and got["untold"] == []
    with pytest.raises(RpcError, match="TD-404 is not an open entry of r's ledger"):
        await agent.rpc_td_hold(repo=root, id="TD-404")
    with pytest.raises(RpcError, match="elsewhere is not a repo this home reads"):
        await agent.rpc_td_hold(repo="elsewhere", id="TD-002")
    assert modes.offline_refusal("td_hold", None, {}, host="laptop", home="kmaster")


async def test_td_hold_on_a_repo_whose_origin_is_not_read_yet_is_refused_and_writes_nothing(agent, tmp_path):
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    agent._repos[root]["remote"] = ""  # read before its origin was: the clock's key is not known (TD-727)
    before = paths.ledger_seen_file().read_text()
    with pytest.raises(RpcError, match="r's origin is not read yet: its clock is keyed by it, so ask again"):
        await agent.rpc_td_hold(repo=root, id="TD-002")
    assert paths.ledger_seen_file().read_text() == before


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


# -- TD-731: a claimed entry is held all the same (§4.4 *A claimed entry is held all the same*) -------------


def _put(agent, sid: str, *, unattended: bool, claim: str | None = None, pr: int | None = None) -> Session:
    s = Session(
        id=sid, name=sid.removeprefix("ao-"), kind="agent", adapter="claude-code", dir="", unattended=unattended
    )
    if claim:
        s.progress.append(ProgressEntry(ref=claim, pr=pr))
    agent.sessions[sid] = s
    return s


def _notes(s: Session, tid: str) -> list[str]:
    return [e.text for e in s.inbox if e.kind == "note" and e.from_ == PERSON and e.about == tid]


async def test_a_hold_on_a_claimed_entry_tells_its_unattended_holder_and_its_prs_reader_once(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003", pr=1840)
    mine = _put(agent, "ao-gi", unattended=False, claim="TD-003")  # interactive: the person's own
    reader = _put(agent, "ao-tl", unattended=True)
    reader.inbox.append(MailEntry(id="m-a1", from_="ao-gw", to=["ao-tl"], at="t", kind="ask", text="read", pr=1840))
    other = _put(agent, "ao-tl2", unattended=True)
    other.inbox.append(MailEntry(id="m-a2", from_="ao-x", to=["ao-tl2"], at="t", kind="ask", text="read", pr=99))
    got = await agent.rpc_td_hold(repo=root, id="TD-003")
    assert got["untold"] == []
    assert got["held"]["at"] and got["told"] == ["ao-gw", "ao-tl"] and got["readers"] == ["ao-tl"]
    assert _notes(worker, "TD-003") == [
        "TD-003 is held by the person: stop at the step in hand, push, leave its PR open and unmerged, and drop "
        'the entry: `ao progress drop TD-003 --why "held by the person"`. A Release makes it pickable again.'
    ]
    assert _notes(reader, "TD-003") == ["TD-003 is held by the person: leave PR #1840 unmerged until they release it."]
    assert _notes(mine, "TD-003") == [] and _notes(other, "TD-003") == []
    assert next(p for p in worker.progress if p.ref == "TD-003").status == "claimed", "the claim stands"
    again = await agent.rpc_td_hold(repo=root, id="TD-003")  # held already: nobody is told again
    assert again["told"] == [] and len(_notes(worker, "TD-003")) == 1 and len(_notes(reader, "TD-003")) == 1
    released = await agent.rpc_td_hold(repo=root, id="TD-003", release=True)
    assert released["told"] == [] and len(_notes(worker, "TD-003")) == 1


async def test_a_note_that_cannot_be_sent_leaves_the_hold_written_and_names_the_holder(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    _put(agent, "ao-gw", unattended=True, claim="TD-003")

    async def refuse(*a, **kw):
        raise RpcError("ao-gw's inbox is full")

    monkeypatch.setattr(agent, "_msg", refuse)
    got = await agent.rpc_td_hold(repo=root, id="TD-003")
    assert got["held"]["at"] and got["told"] == [] and got["untold"] == ["could not tell ao-gw: ao-gw's inbox is full"]
    assert "held" in json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-003"]
    assert "held" in _by_id(entries)["TD-003"]


async def test_a_pr_is_read_only_from_a_declared_claim(agent, tmp_path):
    """TD-744 (`_hold_tell`): a PR is read from a declared lease's claim only — a derived `claimed` line on
    the same id carrying a PR names no reader."""
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    worker.progress.append(ProgressEntry(ref="TD-003", pr=1842, source="derived"))
    reader = _put(agent, "ao-tl", unattended=True)
    reader.inbox.append(MailEntry(id="m-a1", from_="ao-gw", to=["ao-tl"], at="t", kind="ask", text="read", pr=1842))
    got = await agent.rpc_td_hold(repo=root, id="TD-003")
    assert got["told"] == ["ao-gw"] and got["readers"] == [] and _notes(reader, "TD-003") == []


async def test_a_reviewers_pr_and_a_live_seat_are_read_once_and_a_holder_is_not_told_twice(agent, tmp_path):
    """Review of #1861: a claim's `review_pr` names its PR as `pr` does; an exited seat is not told; a seat
    with two asks on the PR gets one note; a holder that is also a reader gets only the holder's."""
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True)
    worker.progress.append(ProgressEntry(ref="TD-003", review_pr=1841))
    worker.inbox.append(MailEntry(id="m-a0", from_="ao-x", to=["ao-gw"], at="t", kind="ask", text="read", pr=1841))
    reader = _put(agent, "ao-tl", unattended=True)
    for n in (1, 2):
        reader.inbox.append(
            MailEntry(id=f"m-a{n}", from_="ao-gw", to=["ao-tl"], at="t", kind="ask", text="read", pr=1841)
        )
    gone = _put(agent, "ao-tl3", unattended=True)
    gone.state = "exited"
    gone.inbox.append(MailEntry(id="m-a3", from_="ao-gw", to=["ao-tl3"], at="t", kind="ask", text="read", pr=1841))
    got = await agent.rpc_td_hold(repo=root, id="TD-003")
    assert got["told"] == ["ao-gw", "ao-tl"] and got["readers"] == ["ao-tl"] and got["untold"] == []
    assert len(_notes(worker, "TD-003")) == 1 and "drop the entry" in _notes(worker, "TD-003")[0]
    assert _notes(reader, "TD-003") == ["TD-003 is held by the person: leave PR #1841 unmerged until they release it."]
    assert _notes(gone, "TD-003") == []


# -- TD-905: a hold's words, and the drop notice (§4.4 *Hold*) ---------------------------------------------


async def test_a_holds_words_are_on_the_record_the_reading_and_the_note_and_new_words_replace_them(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    got = await agent.rpc_td_hold(repo=root, id="TD-003", why="  wait for   the  vendor ")
    assert got["held"] == {"at": got["held"]["at"], "by": "person", "why": "wait for the vendor"}, (
        "one line, on the reading"
    )
    assert json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-003"]["held"]["why"] == "wait for the vendor"
    assert _notes(worker, "TD-003")[0].startswith("TD-003 is held by the person (“wait for the vendor”): stop")
    again = await agent.rpc_td_hold(repo=root, id="TD-003", why="after Friday")
    assert again["told"] == [] and len(_notes(worker, "TD-003")) == 1, "new words tell nobody again"
    assert _by_id(entries)["TD-003"]["held"]["why"] == "after Friday"
    rec = json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-003"]["held"]
    assert rec["why"] == "after Friday" and rec["at"] == got["held"]["at"], "the hold's start stands"
    same = await agent.rpc_td_hold(repo=root, id="TD-003")  # no words: the old ones stand
    assert same["held"]["why"] == "after Friday"
    with pytest.raises(RpcError, match="a release takes no words"):
        await agent.rpc_td_hold(repo=root, id="TD-003", release=True, why="x")
    released = await agent.rpc_td_hold(repo=root, id="TD-003", release=True)
    assert released["held"] is None and "held" not in _by_id(entries)["TD-003"]


async def test_a_drop_notice_tells_the_holder_and_the_reader_and_writes_no_hold(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003", pr=1840)
    reader = _put(agent, "ao-tl", unattended=True)
    reader.inbox.append(MailEntry(id="m-a1", from_="ao-gw", to=["ao-tl"], at="t", kind="ask", text="read", pr=1840))
    with pytest.raises(RpcError, match="writes no hold"):
        await agent.rpc_td_hold(repo=root, id="TD-003", tell="goes back to design", why="x")
    with pytest.raises(RpcError, match="writes no hold"):
        await agent.rpc_td_hold(repo=root, id="TD-003", tell="goes back to design", release=True)
    got = await agent.rpc_td_hold(repo=root, id="TD-003", tell="goes back to design — split it")
    assert got["held"] is None and got["told"] == ["ao-gw", "ao-tl"] and got["readers"] == ["ao-tl"]
    seen = json.loads(paths.ledger_seen_file().read_text()) if paths.ledger_seen_file().exists() else {}
    assert "held" not in _by_id(entries)["TD-003"] and "held" not in (seen.get("o/r") or {}).get("TD-003", {})
    assert _notes(worker, "TD-003") == [
        "TD-003 goes back to design — split it: stop at the step in hand, push, leave its PR open and unmerged, and "
        'drop the entry: `ao progress drop TD-003 --why "goes back to design — split it"`.'
    ]
    assert _notes(reader, "TD-003") == ["TD-003 goes back to design — split it: leave PR #1840 unmerged."]
    again = await agent.rpc_td_hold(repo=root, id="TD-003", tell="is closed by the person — done")
    assert again["told"] == ["ao-gw", "ao-tl"], "a notice is no hold: each press tells"
    with pytest.raises(RpcError, match="ao-w cannot hold a ledger entry"):
        await agent.rpc_td_hold(repo=root, id="TD-003", tell="x", caller="ao-w")


async def test_a_holds_words_and_a_drop_notice_are_cut_to_one_line_of_200(agent, tmp_path):
    """TD-908: `WHY_CHARS` cuts a hold's words on the record, the reading and the note, and a drop notice's."""
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    long = "w" * 300
    got = await agent.rpc_td_hold(repo=root, id="TD-003", why=long)
    assert got["held"]["why"] == long[:200]
    assert json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-003"]["held"]["why"] == long[:200]
    assert _by_id(entries)["TD-003"]["held"]["why"] == long[:200]
    assert _notes(worker, "TD-003")[0].startswith(f"TD-003 is held by the person (“{long[:200]}”): stop")
    await agent.rpc_td_hold(repo=root, id="TD-003", release=True)
    tell = "t" * 300
    await agent.rpc_td_hold(repo=root, id="TD-003", tell=tell)
    assert _notes(worker, "TD-003")[-1].startswith(f"TD-003 {tell[:200]}: stop")


# -- TD-1127: a person's session holds, releases and tells (§4.8 *A person's session passes two of them*) ----


def _stored(tid: str) -> dict:
    return json.loads(paths.ledger_seen_file().read_text())["o/r"][tid]


def _mine(agent, sid: str, **over) -> Session:
    """A session the person started by hand: interactive, no controller, no seat (`mail.person_session`)."""
    s = Session(**{"id": sid, "name": sid.removeprefix("ao-"), "kind": "interactive", "adapter": "claude-code",
                   "dir": "", **over})  # fmt: skip
    agent.sessions[sid] = s
    return s


async def test_a_persons_session_holds_tells_and_releases_its_own_hold_but_never_the_persons(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    _mine(agent, "ao-me")
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    got = await agent.rpc_td_hold(repo=root, id="TD-003", caller="ao-me")
    assert got["held"]["by"] == "ao-me" and got["told"] == ["ao-gw"]
    assert _stored("TD-003")["held"]["by"] == "ao-me"
    assert _notes(worker, "TD-003") == [
        "TD-003 is held by the person's session me: stop at the step in hand, push, leave its PR open and unmerged, "
        'and drop the entry: `ao progress drop TD-003 --why "held by the person\'s session me"`. A Release makes it '
        "pickable again."
    ], "the presser named once"
    got = await agent.rpc_td_hold(repo=root, id="TD-003", release=True, caller="ao-me")
    assert got["held"] is None and "held" not in _by_id(entries)["TD-003"]
    # the person's own hold: no release, no new words, no re-hold from a session
    await agent.rpc_td_hold(repo=root, id="TD-003", why="mine")
    for kw, act in (
        ({"release": True}, "release"),
        ({"why": "later"}, "reword"),
        ({}, "reword"),
        ({"why": "mine"}, "reword"),
    ):
        with pytest.raises(RpcError, match=f"TD-003's hold is the person's own: they {act} it on the Repo page"):
            await agent.rpc_td_hold(repo=root, id="TD-003", caller="ao-me", **kw)
    assert _stored("TD-003")["held"] == {"at": _stored("TD-003")["held"]["at"], "by": "person", "why": "mine"}
    # a hold written before `by` reads as the person's
    store = json.loads(paths.ledger_seen_file().read_text())
    store["o/r"]["TD-003"]["held"].pop("by")
    paths.ledger_seen_file().write_text(json.dumps(store))
    with pytest.raises(RpcError, match="the person's own: they release it"):
        await agent.rpc_td_hold(repo=root, id="TD-003", release=True, caller="ao-me")
    # the person's shell rewords and releases the person's hold as the person does, keeping it `person`
    agent.sessions["ao-sh"] = Session(id="ao-sh", name="sh", kind="interactive", adapter="shell", dir="")
    await agent.rpc_td_hold(repo=root, id="TD-003", why="still mine", caller="ao-sh")
    assert _stored("TD-003")["held"]["by"] == "person" and _stored("TD-003")["held"]["why"] == "still mine"
    await agent.rpc_td_hold(repo=root, id="TD-003", release=True, caller="ao-sh")
    assert "held" not in _stored("TD-003")


async def test_a_sessions_new_words_on_another_sessions_hold_make_it_the_presser(agent, tmp_path):
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    _mine(agent, "ao-a")
    _mine(agent, "ao-b")
    await agent.rpc_td_hold(repo=root, id="TD-003", why="a's", caller="ao-a")
    at = _stored("TD-003")["held"]["at"]
    await agent.rpc_td_hold(repo=root, id="TD-003", why="a's", caller="ao-b")  # the same words: nothing changes
    assert _stored("TD-003")["held"] == {"at": at, "by": "ao-a", "why": "a's"}
    await agent.rpc_td_hold(repo=root, id="TD-003", why="b's", caller="ao-b")
    assert _stored("TD-003")["held"] == {"at": at, "by": "ao-b", "why": "b's"}, "`at` kept"
    await agent.rpc_td_hold(repo=root, id="TD-003", release=True, caller="ao-a")  # a session's hold: liftable


async def test_a_persons_session_drop_notice_says_who_told_and_a_nodes_session_passes(agent, tmp_path):
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    agent.remote = {
        "laptop": {"ao-me": Session(id="ao-me", name="me", kind="interactive", adapter="claude-code", dir="")}
    }
    got = await agent.rpc_td_hold(repo=root, id="TD-003", tell="is superseded by TD-002", caller="ao-me@laptop")
    assert got["told"] == ["ao-gw"] and got["held"] is None
    assert _notes(worker, "TD-003")[0].startswith(
        "TD-003 is superseded by TD-002 (told by the person's session me): stop at the step in hand"
    )
    got = await agent.rpc_td_hold(repo=root, id="TD-003", caller="ao-me@laptop")
    assert got["held"]["by"] == "ao-me@laptop"
    agent.remote["laptop"]["ao-me"].controllers = ["ao-lead"]  # a lead's word ends it on the next call
    with pytest.raises(RpcError, match="ao-me@laptop cannot hold a ledger entry: .*started by hand"):
        await agent.rpc_td_hold(repo=root, id="TD-003", release=True, caller="ao-me@laptop")


async def test_the_claim_refusal_names_a_sessions_hold_by_its_presser(agent, tmp_path):
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    _mine(agent, "ao-me")
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        await agent.rpc_td_hold(repo=root, id="TD-003", caller="ao-me")
        with pytest.raises(AgentError, match="TD-003 is held by the person's session me since"):
            await person.call("progress", id=g, ref="TD-003", status="claimed", force=True)
        del agent.sessions["ao-me"]  # gone: its id stands for it
        with pytest.raises(AgentError, match="TD-003 is held by ao-me since"):
            await person.call("progress", id=g, ref="TD-003", status="claimed")


async def test_a_release_of_an_entry_not_held_is_refused_to_every_caller(agent, tmp_path):
    """Review of #2564: `td_hold --release` on an entry not held is refused to the person, their shell and a
    person's session alike; only a road's own clear finds nothing to do."""
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    _mine(agent, "ao-me")
    agent.sessions["ao-sh"] = Session(id="ao-sh", name="sh", kind="interactive", adapter="shell", dir="")
    for caller in (None, "ao-sh", "ao-me"):
        with pytest.raises(RpcError, match="TD-003 is not held: there is nothing to release"):
            await agent.rpc_td_hold(repo=root, id="TD-003", release=True, caller=caller)


async def test_a_drop_notices_words_cannot_break_or_run_inside_the_quoted_why(agent, tmp_path):
    await park_ticks(agent)
    root, _ = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    await agent.rpc_td_hold(repo=root, id="TD-003", tell='is fixed "x" $(rm -rf ~) `id` \\n')
    note = _notes(worker, "TD-003")[0]
    assert note.startswith('TD-003 is fixed "x" $(rm -rf ~)'), "the words are the note's"
    assert note.endswith('`ao progress drop TD-003 --why "fixed x (rm -rf ~) id n"`.'), note
