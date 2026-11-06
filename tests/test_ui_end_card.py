"""The Focus's ending card (design §4.5 *The Focus screen's anatomy* item 3, §4.5a **ending card**; TD-964, built
by TD-1406): what an ended session cost, from one reading — the `seats` reading's `record` pick, which the page
reads as `/api/spend?record=<id>` — its total in the disconnect card's money-and-tokens rule, *since* its first
day, its tokens and turns and this run's length, then by entry, read once when the ending is drawn."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest
import test_ui_spend
from test_ui_drop_card import PROBE
from test_ui_spend import client, fake

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
APP = UI / "static" / "app.js"

END_PROBE = (
    PROBE.split("const AO = window.AO;")[0]
    + """
const AO = window.AO;
const tok = (i, o, r, w) => ({ input: i, output: o, cache_read: r, cache_write: w });
const reading = {
  record: "r1", first_day: "2026-10-19",
  whole: { figure: 41.8, turns: 312, between: 4.6, unweighed_tokens: 0, unit: "≈$",
           tokens: tok(900000, 300000, 10600000, 600000) },
  money: { "≈$": 41.8 },
  days: [{ day: "2026-10-19" }, { day: "2026-10-21" }],
  refs: [{ ref: "TD-156", figure: 18.2, turns: 100 }, { ref: "TD-942", figure: 14.9, turns: 90 },
         { ref: "TD-623", figure: 4.1, turns: 20 }, { ref: "TD-4", figure: 0.3, turns: 2 },
         { ref: "TD-5", figure: 0.2, turns: 2 }, { ref: "TD-6", figure: 0.1, turns: 1 }],
};
const v = { id: "r1", name: "dc-paul", state: "closed", created: "2026-10-21T16:28:00Z",
            closed_at: "2026-10-21T18:42:00Z" };
const at = Date.UTC(2026, 9, 21, 18, 43), now = at + 60000;
console.log(JSON.stringify({
  card: AO.endCard(reading, v, at, now),
  exited: AO.endCard(reading, { ...v, state: "exited", closed_at: null,
    ended: { at: "2026-10-21T17:00:00Z" } }, at, now).run,
  mixed: AO.endCard({ ...reading, money: { "≈$": 2, "$": 5 }, refs: [],
    whole: { ...reading.whole, between: 0 } }, v, at, now),
  empty: AO.endCard({ ...reading, days: [] }, v, at, now),
  never: AO.endCard(null, v, null, now),
  live: AO.endCard(reading, { ...v, state: "idle" }, at, now),
  shell: AO.endCard(reading, { ...v, agent: false }, at, now),
}));
"""
)


def probe(tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    f = tmp_path / "end_probe.js"
    f.write_text(END_PROBE)
    run = subprocess.run(
        [node, str(f), str(APP)], capture_output=True, text=True, timeout=30, env={**os.environ, "TZ": "UTC"}
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_card_says_the_total_since_its_first_day_tokens_turns_and_the_run(tmp_path):
    c = probe(tmp_path)["card"]
    assert (c["money"], c["since"], c["tok"], c["turns"]) == ("≈$41.80", "Oct 19", "12.4M tokens", "312 turns")
    assert c["kinds"] == "input 900,000 · output 300,000 · cache read 10,600,000 · cache write 600,000"
    assert c["run"] == "this run 16:28 to 18:42 (2h 14m)" and c["asof"] == "18:43"


def test_by_entry_is_the_five_largest_then_between_each_bar_scaled_to_the_largest(tmp_path):
    entries = probe(tmp_path)["card"]["entries"]
    assert [(e["ref"], e["figure"], e["pct"]) for e in entries] == [
        ("TD-156", "≈$18.20", 100),
        ("TD-942", "≈$14.90", 82),
        ("TD-623", "≈$4.10", 23),
        ("TD-4", "≈$0.30", 2),
        ("TD-5", "≈$0.20", 1),
        ("between entries", "≈$4.60", 25),
    ]
    assert entries[-1]["between"] is True


def test_an_exit_ends_the_run_at_its_own_time_and_units_stay_apart(tmp_path):
    got = probe(tmp_path)
    assert got["exited"] == "this run 16:28 to 17:00 (32m)"
    assert got["mixed"]["money"] == "≈$2.00 · $5.00" and got["mixed"]["entries"] == []


def test_no_row_or_no_read_is_no_reading_and_a_live_or_agentless_record_draws_none(tmp_path):
    got = probe(tmp_path)
    assert got["empty"] == {"none": True, "asof": "18:43"} and got["never"] == {"none": True, "asof": None}
    assert got["live"] is None and got["shell"] is None


def test_focus_reads_the_record_once_and_places_the_card_after_the_banner():
    js = APP.read_text(encoding="utf-8")
    assert "fetch(`/api/spend?record=${encodeURIComponent(id)}`)" in js
    assert "drawEnd(v);" in js and "if (on && endShown) on = false;" in js  # no disconnect card beside it
    html = (UI / "templates" / "focus.html").read_text(encoding="utf-8")
    banner, card, pane = (html.index(f'id="{x}"') for x in ("fexited", "fend", "termwrap"))
    assert banner < card < pane


def test_the_route_asks_the_home_for_one_records_reading(monkeypatch, tmp_path):
    calls: list = []
    c = client(monkeypatch, tmp_path, fake(calls))
    monkeypatch.setattr(
        test_ui_spend, "reading", lambda **kw: {"record": kw["record"].split("@")[0]}
    )  # the home's answer
    assert c.get("/api/spend?record=g1@kmaster").json() == {"record": "g1"}
    assert calls == [{"record": "g1@kmaster"}]  # the address as given: the home drops its host part
    calls.clear()
    c.get("/api/spend?record=g1&window=week&team=t")
    assert calls == [{"record": "g1", "window": "week", "team": "t"}]  # passed on, for the home to refuse
