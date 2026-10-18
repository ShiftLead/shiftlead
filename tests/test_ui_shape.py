"""TD-835, design §4.5 screen 13 *Shape*, §4.5a *Spend page: Spend · Shape* and §4.7 `ao team shape`: the
Spend page's Shape view draws the home's `shape` reading — per team its suggestions (or *nothing to suggest*,
or *too little to read yet*), its members by role as a bar of hours by class with the percents under it and
its spend per finished entry, its queues per flow stage — with the pick carried in the URL, and `ao team
shape` prints the same lines. The readings are `sessionorc.shape.reading` over a hand-written sample file,
so the page is tested against the shape the home serves."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from sessionorc import shape as shape_mod
from sessionorc.client import AgentError
from shiftlead import cli
from shiftlead.ui.spend import hours, shape_view, spend_picks, spend_query, view_links

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday
MIN = shape_mod.SHAPE_MIN_HOURS


def _queue(role, kind, order, backed_up=0, unstaffed=0, past_bound=0, oldest_h=0, depth_max=3):
    return {
        "role": role, "kind": kind, "order": order, "minutes": 600, "depth_sum": 600, "depth_max": depth_max,
        "oldest_max": oldest_h * 3600, "nonempty": 600, "backed_up": backed_up, "unstaffed": unstaffed,
        "past_bound": past_bound,
    }  # fmt: skip


def doc(starved=300, too_little=False):
    """ao-grind over one day: two grinders starved while design was backed up, a designer, a techlead seat."""
    scale = 0.1 if too_little else 1
    recs = {
        "g1": {"name": "grinder-ao-1", "role": "grinder", "stage": "build",
               "minutes": {"working": round(300 * scale), "starved": round(starved * scale)}},
        "g2": {"name": "grinder-ao-2", "role": "grinder", "stage": "build",
               "minutes": {"on_claim": round(240 * scale), "starved": round(starved * scale), "limited": 60}},
        "d1": {"name": "designer-ao-1", "role": "designer", "stage": "design",
               "minutes": {"working": 400, "waiting:person": 200}},
        "t1": {"name": "techlead-ao-1", "role": "techlead", "stage": "review",
               "minutes": {"working": 420, "free": 180}},
    }  # fmt: skip
    if too_little:
        recs = {k: v for k, v in recs.items() if k.startswith("g")}
    queues = {
        "design": _queue("designer", "lane", 1, backed_up=480, oldest_h=14),
        "build": _queue("grinder", "lane", 2),
        "review": _queue("techlead", "review", 3, past_bound=30, oldest_h=1),
    }
    day = {"minutes": 600, "limited": 60, "records": recs, "queues": {} if too_little else queues}
    return {"days": {NOW.date().isoformat(): {"ao-grind": day}}, "first_seen": {}}


def reading(team="ao-grind", window="day", **kw):
    finished = {"grinder": {"entries": 5, "median": 13.4}}
    return shape_mod.reading(doc(**kw), team, window, NOW, finished) | {"unit": "≈$"}


def test_the_view_pick_is_carried_in_the_url_and_shape_reads_the_current_period():
    assert spend_picks({"view": "shape", "window": "month", "at": "2026-10-01", "top": "all", "team": "t"}) == {
        "view": "shape",
        "window": "week",
        "at": "",
        "team": "t",
        "top": False,
    }  # fmt: skip — on Shape `at` and `top` drop and a month reads as a week
    p = spend_picks({"window": "month", "at": "2026-09-01", "team": "ao-grind", "top": "all"})
    assert view_links(p) == [
        ("spend", "Spend", "/spend?team=ao-grind&window=month&at=2026-09-01&top=all"),
        ("shape", "Shape", "/spend?view=shape&team=ao-grind&window=week"),
    ]
    shape = spend_picks({"view": "shape", "window": "week"})
    assert spend_query(shape, team="dc-grind") == "/spend?view=shape&team=dc-grind&window=week"
    assert view_links(shape)[0] == ("spend", "Spend", "/spend?window=week")
    assert [hours(h) for h in (0, 0.4, 1.17, 3, 14.2)] == ["—", "24m", "1h10m", "3h", "14h"]


def test_a_team_draws_its_suggestions_its_roles_by_class_and_its_queues():
    v = shape_view([reading()], spend_picks({"view": "shape", "team": "ao-grind"}), ["ao-grind"], MIN)
    t = v["teams"][0]
    assert t["too_little"] == "" and t["suggestions"] == [
        "design backed up 80%, oldest 14h; grinders starved 50% while design was backed up 80%: one more designer",
        "designer waiting on you 33% — answers, not members",
    ]  # the home's two rules naming one more designer are one line
    grinder = t["roles"][1]
    assert (grinder["role"], grinder["seats"], grinder["hours"]) == ("grinder", "2 seats", "20.0 h")
    assert [s["word"] for s in grinder["segs"]] == ["working", "on its claim", "starved", "limited / paused"]
    assert grinder["segs"][-1]["colour"] == "hatch"
    assert grinder["words"] == "working 25% · on its claim 20% · starved 50% · limited / paused 5%"
    assert "grinder-ao-2: on its claim 4.0 h · starved 5.0 h · limited 1.0 h" in grinder["title"]
    assert grinder["finished"] == "5 · median ≈$13.40" and t["roles"][0]["finished"] == "—"
    assert t["queues"][0] == {
        "stage": "design (designer)", "mean": "1.0", "max": 3, "oldest": "14h", "nonempty": "100%",
        "backed_up": "80%", "unstaffed": "0%", "past_bound": "",
    }  # fmt: skip
    assert t["queues"][2]["past_bound"] == "5%" and t["queues"][2]["oldest"] == "1h"
    assert v["windows"] == [
        ("day", "Day", "/spend?view=shape&team=ao-grind"),
        ("week", "Week", "/spend?view=shape&team=ao-grind&window=week"),
    ]


def test_too_little_and_nothing_to_suggest_are_said():
    t = shape_view([reading(too_little=True)], spend_picks({"view": "shape"}), [], MIN)["teams"][0]
    assert (
        t["suggestions"] == [] and t["too_little"] == "too little to read yet: 2.9 live hours of the 8 a reading needs"
    )
    got = reading(starved=0) | {"suggestions": []}
    assert shape_view([got], spend_picks({"view": "shape"}), [], MIN)["teams"][0]["suggestions"] == []


def fake(calls: list, no_shape: bool = False):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            if method == "shape":
                if no_shape:
                    raise AgentError("unknown method: shape")
                return reading(kw["team"], kw["window"])
            if method == "seats":
                return {"teams": [{"team": "ao-grind"}, {"team": "interactive"}]}
            if method == "list":
                return [{"id": "c1", "team": "dc-grind"}, {"id": "p", "team": ""}]
            return {"usage": {}, "host": {"name": "kmaster"}}.get(method, {})

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def test_the_page_draws_a_block_per_team_on_all_and_the_picked_team_alone(tmp_path, monkeypatch):
    calls: list = []
    c = client(monkeypatch, tmp_path, fake(calls))
    html = c.get("/spend?view=shape").text
    assert [kw["team"] for m, kw in calls if m == "shape"] == ["ao-grind", "dc-grind"]  # the ledger's and the records'
    assert re.search(r'<a href="/spend\?view=shape" data-spend aria-pressed="true">Shape</a>', html)
    assert re.search(r'<a href="/spend" data-spend aria-pressed="false">Spend</a>', html)
    assert "Members by role" in html and "Queues" in html and "one more designer" in html
    assert ">Month</a>" not in html and "spnav" not in html  # Day · Week over the current period, no arrows
    calls.clear()
    part = c.get("/spend?view=shape&team=ao-grind&window=week&part=1").text
    assert [kw for m, kw in calls if m == "shape"] == [{"team": "ao-grind", "window": "week"}]
    assert "<html" not in part and part.count('class="shteam"') == 1
    assert 'title="grinder-ao-1: working 5.0 h · starved 5.0 h' in part and "past bound 5%" in part
    assert c.get("/api/shape?team=ao-grind&window=week").json()["window"] == "week"


def test_an_older_home_without_the_shape_reading_is_said(tmp_path, monkeypatch):
    html = client(monkeypatch, tmp_path, fake([], no_shape=True)).get("/spend?view=shape&team=ao-grind").text
    assert "the home did not serve the team&#39;s shape: unknown method: shape" in html


def test_ao_team_shape_prints_the_lines_and_json_the_reply(monkeypatch, capsys):
    got = reading()
    monkeypatch.setattr(cli, "call_sync", lambda method, **kw: got if method == "shape" else {})
    assert cli.cmd_team_shape(argparse.Namespace(name="ao-grind", window="day", json=False)) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "ao-grind · today"
    assert (
        out[1]
        == "  design backed up 80%, oldest 14h; grinders starved 50% while design was backed up 80%: one more designer"
    )
    assert "  grinder · 2 seats · 20.0 h · working 25% · on its claim 20% · starved 50% · limited 5%" in out
    assert "  designer · 1 seat · 10.0 h · working 67% · waiting you 33% · limited 0%" in out
    assert out[-1] == (
        "  review · mean 1.0 · max 3 · oldest 1h · non-empty 100% · backed up 0% · unstaffed 0% · past bound 5%"
    )
    assert cli.cmd_team_shape(argparse.Namespace(name="ao-grind", window="day", json=True)) == 0
    assert '"roles"' in capsys.readouterr().out
    lines = cli.shape_lines(reading(too_little=True), MIN)
    assert lines[0] == "too little to read yet: 2.9 live hours of the 8 a reading needs"
    assert cli.shape_lines(reading() | {"suggestions": []}, MIN)[0] == "nothing to suggest"
