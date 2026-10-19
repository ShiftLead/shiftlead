"""An entry says what it waits for — the words (design §4.4 *An entry says what it waits for*, §4.7
`ao repo`, §4.5a *team card: Repo facet*, *card: compact* and *Repo page: waits mark*; TD-715, built by
TD-716 slice 2): `ao repo` says what each row waits for and that a member's lane only waits, the
lanes line counts *n waiting*, the card draws *n waiting* in grey, the Repo page's row draws the mark,
and a waiting entry is not counted pickable."""

from __future__ import annotations

import json
import pathlib
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import ledger, settle
from shiftlead import teamrun
from shiftlead.ui import org
from shiftlead.ui import repo as repo_ui

NOW = datetime.now(UTC)
TOMORROW = (NOW.astimezone().date() + timedelta(days=1)).isoformat()
LATER = (NOW.astimezone().date() + timedelta(days=9)).isoformat()
GRINDER = ["free-pick", "owner:grinder"]


def _entry(n: int, waits: str = "") -> str:
    head = f"## TD-{n:03d}: entry {n}\n\n**Priority:** Medium\n**Owner:** grinder\n**Kind:** build\n"
    return head + (f"**Waits:** {waits}\n" if waits else "") + "**Status:** Open\n\n**Why:** a reason.\n"


def _read(*parts: str) -> list[dict]:
    return settle.mark_waits(ledger.entries("# Ledger\n\n" + "\n".join(parts)), NOW)


def _three() -> list[dict]:
    """TD-001 free; TD-002 until tomorrow; TD-003 on an event; TD-004 until a later day."""
    return _read(
        _entry(1),
        _entry(2, f"until {TOMORROW} — CI runs on or after then"),
        _entry(3, "event — the next cadence-sync PR, which nobody in the lane can open on its own"),
        _entry(4, f"until {LATER} — the window resets"),
    )


def test_the_words_of_a_wait():
    by = {e["id"]: e for e in _three()}
    assert teamrun.wait_words(by["TD-001"]) == ""
    assert teamrun.wait_words(by["TD-002"]) == f"waits until {TOMORROW}"
    assert teamrun.wait_words(by["TD-002"], short=True) == f"waits until {TOMORROW[5:]}"
    assert teamrun.wait_words(by["TD-003"]).startswith("waits: the next cadence-sync PR, which nobody")
    short = teamrun.wait_words(by["TD-003"], short=True)
    assert short.endswith("…") and len(short) <= len("waits: ") + teamrun.WAIT_CLAMP
    assert teamrun.wait_line(by["TD-002"]) == f"Waits: until {TOMORROW} — CI runs on or after then"
    assert teamrun.waits_tally(["TD-002", "TD-003", "TD-004"], by) == (
        f"2 until a date (the first {TOMORROW}), 1 on an event"
    )
    assert teamrun.waits_tally(["TD-003"], by) == "1 on an event"
    # an `until` that names no date waits with no end, and says its words
    nodate = _read(_entry(5, "until the next audit"))[0]
    assert teamrun.wait_words(nodate) == "waits: the next audit"
    # a wait whose day has begun says nothing: the words read the home's mark, not the line
    assert teamrun.wait_words(settle.mark_waits([by["TD-002"]], NOW + timedelta(days=1))[0]) == ""


def test_a_waiting_entry_is_not_counted_pickable():
    entries = _three()
    r = {"ledger": {"entries": entries, "by_kind": {"pickable": 4}}}
    assert teamrun.lane_kinds(r)["pickable"] == 1


def _lanes(entries, out_of_work=True):
    records = [
        {"id": "w1", "name": "grinder-1", "lane": GRINDER, "state": "idle", "pill_word": "idle"},
        {"id": "w2", "name": "grinder-2", "lane": GRINDER, "state": "idle", "pill_word": "idle"},
    ]
    if out_of_work:
        records[0]["out_of_work"] = {"at": "x"}
        records[1]["out_of_work"] = {"at": "x"}
    return records, ledger.in_lanes(entries, records, held={"TD-001"})


def test_the_lanes_line_counts_what_waits_and_names_a_lane_that_only_waits():
    entries = _three()
    records, got = _lanes(entries)
    by = {e["id"]: e for e in entries}
    line = org.lanes_line("ao-grind", got, {"pickable": 4}, by)
    assert line["waiting"] == 3
    assert line["text"].endswith(
        " · 3 waiting · grinder-1 out of work, its lane waiting · grinder-2 out of work, its lane waiting"
    )
    assert "out of work with" not in line["text"], "a lane that only waits is not work left"
    assert f"TD-002 waits until {TOMORROW}" in line["waiting_title"]
    assert "TD-003 waits: the next cadence-sync PR" in line["waiting_title"]
    assert line["out_of_work_waiting"][0]["title"] == (
        f"TD-002, TD-003, TD-004 — its lane waits: 2 until a date (the first {TOMORROW}), 1 on an event"
    )
    html = _render("lanes_line.html", ln=line, url="/repo/r")
    assert "· 3 waiting" in html and "out of work, its lane waiting" in html
    assert 'href="/focus/w1"' in html
    # nothing waits: nothing is said
    plain = org.lanes_line("ao-grind", ledger.in_lanes(entries[:1], records), {"pickable": 1}, by)
    assert plain["waiting"] == 0 and "waiting" not in plain["text"] and plain["out_of_work_waiting"] == []


def test_the_card_draws_n_waiting_in_grey_where_its_lane_takes_nothing_else():
    entries = _three()
    records, got = _lanes(entries)
    line = org.lanes_line("ao-grind", got, {"pickable": 4}, {e["id"]: e for e in entries})
    lc = org.lane_count(records[0], line)
    assert lc == {
        "text": "3 waiting",
        "title": f"3 entries in its lane wait: 2 until a date (the first {TOMORROW}), 1 on an event",
        "kind": "waiting",
        "solid": False,
    }, "never solid, though the member is out of work and idle"
    assert 'class="lanecount k-waiting"' in _render_macro(lc)
    # a lane with work it can take counts that, as before
    free = ledger.in_lanes(entries, records)
    lc2 = org.lane_count(records[0], org.lanes_line("ao-grind", free, {"pickable": 4}, {}))
    assert lc2["text"] == "1/2" and lc2["kind"] == "pickable" and lc2["solid"]
    # nothing waits and nothing to take: no count
    none = ledger.in_lanes(entries[:1], records, held={"TD-001"})
    assert org.lane_count(records[0], org.lanes_line("ao-grind", none, {"pickable": 1}, {})) is None


def test_the_repo_pages_row_draws_the_waits_mark():
    entries = _three()
    r = {"ledger": {"entries": entries}}
    rows = {e["id"]: e for lst in repo_ui.ledger_lists(r, [], None, NOW) for e in lst["rows"]}
    assert rows["TD-001"]["wait"] == "" and rows["TD-002"]["wait"] == f"waits until {TOMORROW[5:]}"
    assert rows["TD-002"]["wait_line"] == f"Waits: until {TOMORROW} — CI runs on or after then"
    assert rows["TD-003"]["wait"].startswith("waits: the next") and rows["TD-003"]["wait"].endswith("…")
    src = (pathlib.Path(repo_ui.__file__).parent / "templates" / "queue_row.html").read_text(encoding="utf-8")
    assert '<span class="meta waits" title="{{ e.wait_line }}">· {{ e.wait }}</span>' in src


@pytest.fixture
def git_repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    return root


def test_ao_repo_says_what_each_row_waits_for_and_that_a_lane_only_waits(git_repo, monkeypatch, capsys):
    from shiftlead import cli

    entries = _three()
    reading = {str(git_repo): {"name": "r", "root": str(git_repo), "prs": {"open": []},
                               "ledger": {"entries": entries, "by_kind": {"pickable": 4}}}}  # fmt: skip
    records, _ = _lanes(entries)
    fleet = [{**r, "repo": str(git_repo), "team": "ao-grind"} for r in records]
    fleet[1]["progress"] = [{"ref": "TD-001", "status": "claimed"}]
    del fleet[1]["out_of_work"]
    monkeypatch.setattr(
        cli,
        "call_sync",
        lambda rpc, **kw: {"repos": reading, "list": fleet, "doing_log": {}, "queue": {}, "inbox": {}}[rpc],
    )
    monkeypatch.chdir(git_repo)
    assert cli.main(["repo"]) == 0
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if " TD-002 " in line)
    assert f"grinder waits until {TOMORROW}" in row
    assert "grinder waits: the next cadence-sync PR" in next(line for line in out.splitlines() if " TD-003 " in line)
    assert (
        f"  grinder-1 is out of work; its lane waits: 2 until a date (the first {TOMORROW}), 1 on an event: "
        "TD-002, TD-003, TD-004"
    ) in out
    assert "grinder-1 is out of work with" not in out
    assert cli.main(["--json", "repo"]) == 0
    lanes = json.loads(capsys.readouterr().out)[0]["lanes"]["ao-grind"]
    assert lanes["waiting"] == {"until": ["TD-002", "TD-004"], "event": ["TD-003"]}


def _render(name: str, **ctx) -> str:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(repo_ui.__file__.rsplit("/", 1)[0] + "/templates"), autoescape=True)
    return env.get_template(name).render(**ctx)


def _render_macro(lc) -> str:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(repo_ui.__file__.rsplit("/", 1)[0] + "/templates"), autoescape=True)
    return str(env.get_template("lanecount.html").module.span(lc))
