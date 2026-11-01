"""TD-710 slice 1, design §4.4 *A new entry settles before it is pickable* (TD-707): the home's clock,
`ledger_seen.json`, records each id a fresh reading holds, and the reading's entries carry `settling:
{until}` while their Kind's window runs; a marked entry matches no lane. The clock records settling only
(TD-1297): a record's `held`, written before, is ignored."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import ledger, paths, settle
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


def test_a_clock_record_carrying_held_loads_as_settled_and_withholds_nothing():
    """TD-1297: a record written while the clock kept holds — `held` beside a settled `at`, or the retired
    `--held`'s `{held}` with no `at` — marks no `held` and withholds nothing; the next write drops the key."""
    settle.observe(_ledger(), "o/r", SPANS, T0)
    settle.observe(_ledger(_entry(2), _entry(3, "build")), "o/r", SPANS, T0)
    store = json.loads(paths.ledger_seen_file().read_text())
    store["o/r"]["TD-002"]["held"] = {"at": T0.isoformat(), "by": "person", "why": "wait"}
    store["o/r"]["TD-009"] = {"held": {"at": T0.isoformat(), "by": "ao-i"}}  # an id pre-held and never filed
    paths.ledger_seen_file().write_text(json.dumps(store))
    much_later = T0 + timedelta(days=2)
    got = _by_id(settle.mark(_ledger(_entry(2), _entry(3, "build"), _entry(9, "build")), "o/r", SPANS, much_later))
    for tid in ("TD-002", "TD-003", "TD-009"):
        assert "held" not in got[tid] and "settling" not in got[tid], tid
    assert ledger.lane_matches(DESIGNER, got["TD-002"]) and ledger.lane_matches(GRINDER, got["TD-009"])
    assert settle.claim_refusal(got["TD-002"], much_later) is None and settle.words(got["TD-002"], much_later) == ""
    got = _by_id(settle.observe(_ledger(_entry(2), _entry(9, "build")), "o/r", SPANS, much_later))
    assert "held" not in got["TD-002"] and "settling" not in got["TD-009"], "a build settles at once"
    seen = json.loads(paths.ledger_seen_file().read_text())["o/r"]
    assert "held" not in seen["TD-002"] and seen["TD-002"]["at"] == T0.isoformat(), "the record keeps its `at`"
    assert seen["TD-009"] == {"at": much_later.isoformat(), "sig": got["TD-009"]["sig"]}, "read as first seen"


def test_an_old_records_with_no_at_leave_a_repos_first_reading_recording_every_id_settled():
    """A key holding only records with no `at` (the retired `--held`'s) has had no reading: its first still
    records every id at the epoch."""
    paths.ledger_seen_file().write_text(json.dumps({"o/r": {"TD-009": {"held": {"at": T0.isoformat()}}}}))
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(9)), "o/r", SPANS, T0 + timedelta(minutes=1)))
    seen = json.loads(paths.ledger_seen_file().read_text())["o/r"]
    assert seen["TD-001"]["at"] == settle.EPOCH and seen["TD-009"]["at"] == settle.EPOCH
    assert "settling" not in got["TD-001"] and "settling" not in got["TD-009"]
    got = _by_id(settle.observe(_ledger(_entry(1), _entry(3)), "o/r", SPANS, T0 + timedelta(minutes=2)))
    assert "settling" in got["TD-003"], "the next reading is not a first"


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
    settle.observe(_ledger(_entry(3, "build")), "o/r", SPANS, T0 + timedelta(minutes=1))  # TD-002 missing
    assert json.loads(paths.ledger_seen_file().read_text())["o/r"]["TD-002"]["at"] == T0.isoformat()
    got = _by_id(settle.observe(_ledger(_entry(2)), "o/r", SPANS, T0 + timedelta(days=1)))
    assert "settling" not in got["TD-002"], "settled, not back as new after the reading that lacked it"


# -- the claim (§4.8 *A claim is a lease*) -------------------------------------------------------------------


def _settling_two(t: datetime = T0) -> dict[str, dict]:
    """A first reading, then TD-002 (design-first, settling) and TD-003 (build, settled at once)."""
    settle.observe(_ledger(), "o/r", SPANS, t)
    return _by_id(settle.observe(_ledger(_entry(2), _entry(3, "build")), "o/r", SPANS, t))


def test_the_claim_refusal_names_the_window():
    got = _settling_two()
    words = settle.claim_refusal(got["TD-002"], T0)
    until = (T0 + timedelta(minutes=5)).astimezone()
    assert words.startswith(f"TD-002 settles until {until:%H:%M}: the person's window to change it (design")
    assert "--force does not pass it" in words and "hold" not in words
    assert settle.claim_refusal(got["TD-002"], T0 + timedelta(minutes=5)) is None, "a stale mark past its until"
    assert settle.claim_refusal(got["TD-003"], T0) is None and settle.claim_refusal(None, T0) is None
    assert settle.claim_refusal({"id": "TD-002", "held": {"at": T0.isoformat()}}, T0) is None, "TD-1297"


async def _home_with(agent, tmp_path, *, now: datetime) -> tuple[str, list[dict]]:
    """The agent reading a repo whose TD-002 settles, as the tick would leave it."""
    root = str(tmp_path / "r")
    got = _settling_two(now)
    agent._repos[root] = {"name": "r", "root": root, "remote": "https://github.com/o/r.git",
                          "ledger": {"entries": list(got.values())}}  # fmt: skip
    return root, agent._repos[root]["ledger"]["entries"]


async def test_a_claim_on_a_settling_entry_is_refused_with_force_too(agent, tmp_path):
    await park_ticks(agent)
    root, entries = await _home_with(agent, tmp_path, now=datetime.now(UTC))
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        for force in (False, True):
            with pytest.raises(AgentError, match="TD-002 settles until .*--force does not pass it"):
                await person.call("progress", id=g, ref="TD-002", status="claimed", force=force)
        await person.call("progress", id=g, ref="TD-003", status="claimed")  # a build: settled at once
        settle.mark(entries, "o/r", SPANS, datetime.now(UTC) + timedelta(minutes=6))  # the window ran out
        await person.call("progress", id=g, ref="TD-002", status="claimed")
        assert {e.ref for e in agent.sessions[g].progress} >= {"TD-002", "TD-003"}


# -- the tell (§4.4 *The tell*, TD-731, TD-905): `_ledger_road`'s first step, `_tell_holders` ----------------


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


async def test_the_tell_names_its_unattended_holder_and_its_prs_reader_each_press(agent, tmp_path):
    await park_ticks(agent)
    await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003", pr=1840)
    mine = _put(agent, "ao-gi", unattended=False, claim="TD-003")  # interactive: the person's own
    reader = _put(agent, "ao-tl", unattended=True)
    reader.inbox.append(MailEntry(id="m-a1", from_="ao-gw", to=["ao-tl"], at="t", kind="ask", text="read", pr=1840))
    other = _put(agent, "ao-tl2", unattended=True)
    other.inbox.append(MailEntry(id="m-a2", from_="ao-x", to=["ao-tl2"], at="t", kind="ask", text="read", pr=99))
    told, readers, untold = await agent._tell_holders("TD-003", "goes back to design — split it")
    assert told == ["ao-gw", "ao-tl"] and readers == ["ao-tl"] and untold == []
    assert _notes(worker, "TD-003") == [
        "TD-003 goes back to design — split it: stop at the step in hand, push, leave its PR open and unmerged, and "
        'drop the entry: `ao progress drop TD-003 --why "goes back to design — split it"`.'
    ]
    assert _notes(reader, "TD-003") == ["TD-003 goes back to design — split it: leave PR #1840 unmerged."]
    assert _notes(mine, "TD-003") == [] and _notes(other, "TD-003") == []
    assert next(p for p in worker.progress if p.ref == "TD-003").status == "claimed", "the claim stands"
    told, _, _ = await agent._tell_holders("TD-003", "is closed by the person — done")
    assert told == ["ao-gw", "ao-tl"], "each press tells"
    assert not paths.ledger_seen_file().exists() or "held" not in json.dumps(
        json.loads(paths.ledger_seen_file().read_text())
    ), "the clock records no hold"


async def test_a_note_that_cannot_be_sent_is_a_line_of_untold(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    await _home_with(agent, tmp_path, now=datetime.now(UTC))
    _put(agent, "ao-gw", unattended=True, claim="TD-003")

    async def refuse(*a, **kw):
        raise RpcError("ao-gw's inbox is full")

    monkeypatch.setattr(agent, "_msg", refuse)
    told, readers, untold = await agent._tell_holders("TD-003", "goes back to design")
    assert told == [] and readers == [] and untold == ["could not tell ao-gw: ao-gw's inbox is full"]


async def test_a_pr_is_read_only_from_a_declared_claim(agent, tmp_path):
    """TD-744: a PR is read from a declared lease's claim only — a derived `claimed` line on the same id
    carrying a PR names no reader."""
    await park_ticks(agent)
    await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    worker.progress.append(ProgressEntry(ref="TD-003", pr=1842, source="derived"))
    reader = _put(agent, "ao-tl", unattended=True)
    reader.inbox.append(MailEntry(id="m-a1", from_="ao-gw", to=["ao-tl"], at="t", kind="ask", text="read", pr=1842))
    told, readers, _ = await agent._tell_holders("TD-003", "goes back to design")
    assert told == ["ao-gw"] and readers == [] and _notes(reader, "TD-003") == []


async def test_a_reviewers_pr_and_a_live_seat_are_read_once_and_a_holder_is_not_told_twice(agent, tmp_path):
    """Review of #1861: a claim's `review_pr` names its PR as `pr` does; an exited seat is not told; a seat
    with two asks on the PR gets one note; a holder that is also a reader gets only the holder's."""
    await park_ticks(agent)
    await _home_with(agent, tmp_path, now=datetime.now(UTC))
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
    told, readers, untold = await agent._tell_holders("TD-003", "goes back to design")
    assert told == ["ao-gw", "ao-tl"] and readers == ["ao-tl"] and untold == []
    assert len(_notes(worker, "TD-003")) == 1 and "drop the entry" in _notes(worker, "TD-003")[0]
    assert _notes(reader, "TD-003") == ["TD-003 goes back to design: leave PR #1841 unmerged."]
    assert _notes(gone, "TD-003") == []


async def test_the_tells_words_cannot_break_or_run_inside_the_quoted_why(agent, tmp_path):
    await park_ticks(agent)
    await _home_with(agent, tmp_path, now=datetime.now(UTC))
    worker = _put(agent, "ao-gw", unattended=True, claim="TD-003")
    await agent._tell_holders("TD-003", 'is fixed "x" $(rm -rf ~) `id` \\n')
    note = _notes(worker, "TD-003")[0]
    assert note.startswith('TD-003 is fixed "x" $(rm -rf ~)'), "the words are the note's"
    assert note.endswith('`ao progress drop TD-003 --why "fixed x (rm -rf ~) id n"`.'), note
