"""TD-831, design §4.7 `ao spend` and `ao status -v`, §4.4 *Spend per seat*: the seat ledger's reading from a
terminal — By team, a block per team, the interactive sessions and *outside shiftlead*; one team's head line
and block; the finished entries — and each record's figure on `ao status -v`. The readings are
`sessionorc.seats.reading` over a hand-written ledger, so the lines are tested against the shape the home serves."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import pytest

from sessionorc import identity, seats
from shiftlead import cli

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)  # a Saturday
TODAY = NOW.date()


def _row(figure, turns=1, name="w", team="ao-grind", role="grinder", repo="shiftlead", refs=None, metered=False, **m):
    return {
        "name": name, "team": team, "role": role, "repo": repo, "metered": metered, "refs": refs or {},
        "models": {"m": {"input": 1000, "output": 0, "cache_read": 0, "cache_write": 0, "turns": turns,
                         "figure": figure, "past_200k": 0.0, "past_300k": 0.0} | m},
    }  # fmt: skip


def ledger():
    """Two teams and an interactive session over two days; two grinders and a designer; an entry finished today
    that two roles worked on (the designer the most), and one claimed before the ledger began."""
    today = {
        "g1": _row(52.3, 611, "grinder-ao-1", past_200k=6.3, refs={"TD-813": {"figure": 24.7, "turns": 301}}),
        "g2": _row(47.9, 540, "grinder-ao-2", refs={"between": {"figure": 6.1, "turns": 20}}),
        "d1": _row(38.2, 412, "designer-ao-1", role="designer", refs={"TD-813": {"figure": 30.0, "turns": 40}}),
        "c1": _row(10.0, 50, "dc-grinder", team="dc-grind", refs={"TD-9": {"figure": 4.0, "turns": 9}}),
        "p1": _row(9.45, 147, "ao-paul", team="", role=""),
        "outside": {**_row(1.9, 21), "name": "outside", "team": "", "role": ""},
    }
    yesterday = {"g1": _row(20.0, 100, "grinder-ao-1"), "c1": _row(40.0, 100, "dc-grinder", team="dc-grind")}
    return {
        "began": "2026-10-16T00:00:00Z",
        "days": {"2026-10-17": today, "2026-10-16": yesterday},
        "refs": {
            "shiftlead TD-813": {"first_claimed": "2026-10-17T06:00:00Z", "done_at": "2026-10-17T11:40:00Z"},
            "shiftlead TD-9": {"first_claimed": "2026-10-17T08:00:00Z", "done_at": "2026-10-17T08:50:00Z"},
        },
    }


def got(window="day", team=None, by=None, led=None):
    return seats.reading(led or ledger(), window, NOW, team, by, seats.WEIGHTS) | {"unknown": {}}


def test_by_team_then_each_teams_seats_then_interactive_then_outside():
    lines = cli.spend_lines(got(), None, TODAY)
    assert lines[0] == "By team · Sat 17 Oct · ≈$160"
    by_team = [ln for ln in lines if ln.startswith("  ao-grind ·")][0]
    # the head's figure, its share of the whole, its turns, the week's and month's so far, the seat that spent most
    assert by_team.startswith("  ao-grind · ≈$138 · 87% · 1,563 turns · week ≈$158 · month ≈$158 · most grinder-ao-1")
    assert "  interactive sessions · ≈$9.45 · 6% · 147 turns" in "\n".join(lines)
    heads = [ln for ln in lines if not ln.startswith(" ")]
    assert heads == ["By team · Sat 17 Oct · ≈$160", "ao-grind", "dc-grind", "interactive sessions"] + [
        "outside shiftlead · ≈$1.90 · 1% · 21 turns"
    ]
    grind = lines[lines.index("ao-grind") + 1 : lines.index("dc-grind")]
    assert (
        grind[0]
        == "  grinder-ao-1 · grinder · ≈$52.30 · 38% · 611 turns · between ≈$0.00 · past 200k 12% · past 300k 0%"
    )
    assert "  grinder-ao-2 · grinder · ≈$47.90 · 35% · 540 turns · between ≈$6.10" in grind[1]
    # a role of one seat carries its finished entries; a role of two does not split them
    assert grind[2].startswith("  designer-ao-1 · designer · ≈$38.20 · 28% · 412 turns · 1 done, median ≈$54.70 ·")
    assert " done" not in grind[0] + grind[1]
    # dc-grind's grinder is not the reading's one grinder, so the grinders' finished entry is on no seat's line
    assert " done" not in lines[lines.index("dc-grind") + 1]
    assert lines[lines.index("interactive sessions") + 1].startswith(
        "  ao-paul · shiftlead · ≈$9.45 · 100% · 147 turns"
    )


def test_a_teams_head_line_then_its_block_alone_and_interactive_the_same():
    lines = cli.spend_lines(got(team="ao-grind"), "ao-grind", TODAY)
    assert lines[0] == "ao-grind · ≈$138 today (so far) · yesterday ≈$20.00 · this week ≈$158 · October ≈$158"
    assert [ln.split(" · ")[0].strip() for ln in lines[1:]] == ["grinder-ao-1", "grinder-ao-2", "designer-ao-1"]
    mine = cli.spend_lines(got(team="interactive"), "interactive", TODAY)
    assert mine[0].startswith("interactive sessions · ≈$9.45 today (so far)")
    assert mine[1:] == [
        "  ao-paul · shiftlead · ≈$9.45 · 100% · 147 turns · between ≈$0.00 · past 200k 0% · past 300k 0%"
    ]


def test_a_metered_figure_reads_dollars_and_an_unweighed_one_its_tokens():
    led = ledger()
    led["days"]["2026-10-17"] = {
        "g1": _row(3.2, 10, "grinder-ao-1", metered=True),
        "g2": _row(0.0, 4, "grinder-ao-2", unweighed=4),
    }
    led["days"].pop("2026-10-16")
    lines = cli.spend_lines(got(team="ao-grind", led=led), "ao-grind", TODAY)
    assert lines[1].startswith("  grinder-ao-1 · grinder · $3.20 ·")
    assert lines[2].startswith("  grinder-ao-2 · grinder · unweighed · 1k tok ·")


def test_the_finished_entries_their_roles_and_the_partial_mark():
    reading = got()
    assert cli.entry_lines(reading) == [
        "TD-813 · designer ≈$30.00 + grinder ≈$24.70 = ≈$54.70 · 5h40m",
        "TD-9 · grinder ≈$4.00 · 50m",
    ]
    led = ledger()
    led["began"] = "2026-10-17T07:00:00Z"  # TD-813 was first claimed before it
    assert cli.entry_lines(got(led=led))[0].endswith("· 5h40m · partial")
    assert cli.entry_lines({"entries": []}) == ["no entry finished in the period"]


def test_an_empty_ledger_prints_nothing_spent_and_raises_nowhere():
    empty = {"began": None, "days": {}, "refs": {}}
    for window in ("day", "week", "month"):
        assert cli.spend_lines(got(window, led=empty), None, TODAY)[0].endswith(" · ≈$0.00")
        alone = cli.spend_lines(got(window, "ao-grind", led=empty), "ao-grind", TODAY)
        assert len(alone) == 1 and alone[0].startswith("ao-grind · ≈$0.00 ")  # the head line, and no seat
    assert cli.record_spend([{"id": "g1"}], lambda method, **kw: got(kw["window"], by="record", led=empty)) == {}
    assert cli.spend_lines({}, None, TODAY) == ["nothing read: the home served no period"]


def test_ao_spend_asks_the_seats_rpc_and_json_prints_its_reply(monkeypatch, capsys):
    asked = []

    def call(method, **kw):
        asked.append((method, kw))
        return got(kw["window"], kw["team"])

    monkeypatch.setattr(cli, "call_sync", call)
    args = argparse.Namespace(team=None, window="week", at="2026-10-12", entries=True, json=False)
    assert cli.cmd_spend(args) == 0
    assert asked == [("seats", {"window": "week", "team": None, "at": "2026-10-12"})]
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("By team · week of 12 Oct")
    assert "Finished entries" in out and "  TD-9 · grinder ≈$4.00 · 50m" in out
    assert cli.cmd_spend(argparse.Namespace(team="ao-grind", window="day", at=None, entries=False, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["teams"][0]["team"] == "ao-grind"
    # the parser takes every flag §4.7 names
    parsed = cli.build_parser().parse_args(
        ["spend", "--team", "t", "--window", "month", "--at", "2026-10-01", "--entries"]
    )
    assert (parsed.fn, parsed.team, parsed.window, parsed.at, parsed.entries) == (
        cli.cmd_spend,
        "t",
        "month",
        "2026-10-01",
        True,
    )


def test_a_session_may_read_the_seats_reading():
    """`ao spend` is open to a session as `ao status` is (design §4.7)."""
    assert "seats" in identity.READS


REC = {"state": "idle", "confidence": "hook", "since": "2026-10-17T11:00:00Z", "adapter": "claude-code"}


def test_status_v_prints_each_records_figure_and_none_where_it_spent_nothing(monkeypatch, capsys):
    led = ledger()
    sessions = [
        {"id": "g1", "name": "grinder-ao-1", "profile": "grind"} | REC,
        {"id": "x9", "name": "quiet", "profile": "grind"} | REC,
        {"id": "m1", "name": "metered", "profile": "api"} | REC,
    ]

    def call(method, **kw):
        if method == "list":
            return [dict(s) for s in sessions]
        if method == "seats":
            assert kw["by"] == "record"
            return got(kw["window"], by="record", led=led) | ({"unknown": {"api": "no key"}})
        raise RuntimeError(method)

    monkeypatch.setattr(cli, "call_sync", call)
    spend = cli.record_spend(sessions, call)
    assert spend["g1"] == {"day": 52.3, "week": 72.3, "past_200k": 0.1205, "past_300k": 0.0, "unit": "≈$"}
    assert "x9" not in spend and spend["m1"] == {"unknown": "no key"}
    assert cli.record_spend_line(spend["g1"]) == "spend ≈$52.30 today · ≈$72.30 week · past 200k 12%"
    assert cli.record_spend_line(spend["m1"]) == "spend unknown (no key)"
    assert cli.record_spend_line({"day": 3.2, "week": 9.8, "past_200k": 0.0, "past_300k": 0.0, "unit": "$"}) == (
        "spend $3.20 today · $9.80 week · past 200k 0%"
    )
    assert cli.record_spend_line(None) == ""

    monkeypatch.setattr(cli, "_identity_line", lambda: None)
    monkeypatch.setattr(cli, "_running_build", lambda: None)
    assert cli.cmd_status(argparse.Namespace(json=False, verbose=True)) == 0
    out = capsys.readouterr().out
    assert "spend ≈$52.30 today · ≈$72.30 week · past 200k 12%" in out and out.count("spend ≈$") == 1
    assert "spend unknown (no key)" in out
    assert cli.cmd_status(argparse.Namespace(json=True, verbose=True)) == 0
    records = {r["id"]: r for r in json.loads(capsys.readouterr().out)}
    assert records["g1"]["spend"]["week"] == 72.3 and "spend" not in records["x9"]
    assert records["m1"]["spend"] == {"unknown": "no key"}
    assert cli.cmd_status(argparse.Namespace(json=True, verbose=False)) == 0
    assert all("spend" not in r for r in json.loads(capsys.readouterr().out))  # without -v it is not asked


def test_status_v_without_the_seats_reading_prints_the_rest(monkeypatch, capsys):
    """A refused or failed `seats` (the home down, a node's link down) leaves `ao status -v` as it was; a node
    does not ask, the ledger being the home's."""
    asked = []

    def call(method, **kw):
        asked.append(method)
        if method == "list":
            return [{"id": "g1", "name": "grinder-ao-1", "profile": "grind"} | REC]
        raise RuntimeError("refused")

    monkeypatch.setattr(cli, "call_sync", call)
    monkeypatch.setattr(cli, "_identity_line", lambda: None)
    monkeypatch.setattr(cli, "_running_build", lambda: None)
    assert cli.cmd_status(argparse.Namespace(json=False, verbose=True)) == 0
    out = capsys.readouterr().out
    assert out.startswith("g1") and "spend" not in out and "seats" in asked
    assert cli.cmd_status(argparse.Namespace(json=True, verbose=True)) == 0
    assert "spend" not in json.loads(capsys.readouterr().out)[0]
    asked.clear()
    monkeypatch.setattr(cli.hosts, "is_node", lambda: True)
    monkeypatch.setattr(cli, "_node_status_line", lambda: "a node")
    assert cli.cmd_status(argparse.Namespace(json=True, verbose=True)) == 0
    assert "seats" not in asked
