"""TDs in motion's **completed** face (design §4.5a *team card: TDs in motion*, **Completed**, TD-1189, built by
TD-1194 slice 2): what the ledger closed in the window that a record of the team names — by a claim's `ref` or
`pr`, or a `restarts` entry's `done`, never a `review_pr` alone — eight rows then *+n more*, the empty window's
words, the face the facet opens on, stored per team, and `drawn_facets` reading the closes."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import scratch_dir
from test_ui_keys import PROBE, UI
from test_ui_team_summary import NOW, _iso, claim, member, reading

from shiftlead.ui import app as ui
from shiftlead.ui.org import REF_WIDTH, drawn_facets

pytestmark = pytest.mark.unit


def close(tid: str, pr: int | None, hours: float, title: str = "") -> dict:
    return {"id": tid, "title": title or f"the {tid} fix", "pr": pr, "closed": _iso(NOW - timedelta(hours=hours))}


def summary(members: list[dict], completed: list[dict]) -> dict:
    repos = {"/r/samscrape": reading("/r/samscrape", completed=completed)}
    return ui.team_summary("grind", members, repos, {}, now=NOW)


def render(s: dict) -> str:
    return ui.templates.get_template("team_summary.html").render(g={"team": "grind", "summary": s})


def test_a_close_is_the_teams_by_a_claims_ref_its_pr_or_a_restarts_done_and_never_by_review_pr_alone():
    closes = [
        close("TD-1", 101, 1),  # a done claim's ref
        close("TD-2", 102, 2),  # a dropped claim's pr: the design archived in its build's PR
        close("TD-3", 103, 3),  # an ended run's restarts `done`
        close("TD-4", 104, 4),  # named only by a claim's review_pr: off the card
        close("TD-5", 105, 5),  # nobody's: the person's own PR
        close("TD-6", None, 6),  # a commit naming no PR, claimed by ref
    ]
    a = member(
        "a",
        progress=[
            claim("TD-1", status="done"),
            claim("TD-9", pr=102, status="dropped"),
            {"ref": "TD-8", "status": "claimed", "review_pr": 104},
            claim("TD-6", status="done"),
        ],
    )
    b = member("b", state="exited", restarts=[{"at": _iso(NOW), "why": "wanted", "done": [{"ref": "TD-3", "pr": 103}]}])
    s = summary([a, b], closes)
    day = s["completed"]["day"]
    assert [r["id"] for r in day["rows"]] == ["TD-1", "TD-2", "TD-3", "TD-6"] and day["n"] == 4 and not day["more"]
    assert day["rows"][0]["url"] == "https://github.com/eye/samscrape/pull/101" and day["rows"][3]["pr"] is None
    html = render(s)
    done = html[html.index('data-mv="completed"') :]
    assert "Completed (4)" in done and "TD-4" not in done and "TD-5" not in done
    assert '<span class="nopr">no PR</span>' in done and 'data-doing-at="' + closes[0]["closed"] + '"' in done
    assert s["done_pr_w"] == len("no PR")
    assert 'href="/repo/samscrape?win=day#completed" title="TD-1"' in done  # a closed entry lands on Merged


def test_eight_rows_then_more_linking_to_the_merged_column_and_the_empty_windows_words():
    closes = [close(f"TD-{i}", 200 + i, 30 + i) for i in range(11)]  # all past a day, within a week
    s = summary([member("a", progress=[claim(c["id"], status="done") for c in closes])], closes)
    week = s["completed"]["week"]
    assert week["n"] == 11 and week["more"] == 3 and len(week["rows"]) == 8
    assert s["completed"]["day"]["n"] == 0
    html = render(s)
    assert '<a class="meta more" href="/repo/samscrape?win=week#completed">+3 more</a>' in html
    assert "nothing completed today" in html and "+11" not in html


def test_each_row_shows_its_short_age_and_each_empty_window_says_its_own_word():
    closes = [close("TD-1", 101, 1), close("TD-2", 102, 26)]  # an hour ago; past a day, within the week
    s = summary([member("a", progress=[claim(c["id"], status="done") for c in closes])], closes)
    assert [r["age"] for r in s["completed"]["week"]["rows"]] == ["1h", "1d"]
    done = render(s)[render(s).index('data-mv="completed"') :]
    assert f'data-doing-at="{closes[0]["closed"]}" title="{closes[0]["closed"]}">1h</span>' in done
    assert f'title="{closes[1]["closed"]}">1d</span>' in done
    html = render(summary([member("a")], []))
    assert all(f"nothing completed {w}" in html for w in ("today", "this week", "this month"))
    old = [close("TD-3", 103, 24 * 10)]  # ten days ago: the month's alone
    html = render(summary([member("a", progress=[claim("TD-3", status="done")])], old))
    assert "nothing completed today" in html and "nothing completed this week" in html
    assert "nothing completed this month" not in html


def test_the_completed_reference_track_is_the_longest_id_shown_capped_at_ref_width():
    closes = [close("TD-1", 101, 1), close("TD-1234", 102, 2)]
    s = summary([member("a", progress=[claim(c["id"], status="done") for c in closes])], closes)
    assert s["done_ref_w"] == len("TD-1234")
    assert "--ref-n: 7; --who-n: 0;" in render(s)
    long = [close("TD-123456789", 103, 1)]  # 12 characters, past the column's cap
    s = summary([member("a", progress=[claim("TD-123456789", status="done")])], long)
    assert s["done_ref_w"] == REF_WIDTH == 10 and f"--ref-n: {REF_WIDTH}; --who-n: 0;" in render(s)


def test_the_face_opens_on_in_motion_with_a_claim_else_completed_and_the_toggle_is_drawn():
    closes = [close("TD-1", 101, 1)]
    held = summary([member("a", progress=[claim("TD-301"), claim("TD-1", status="done")])], closes)
    idle = summary([member("a", progress=[claim("TD-1", status="done")])], closes)
    assert held["motion_face"] == "motion" and idle["motion_face"] == "completed"
    html = render(idle)
    assert 'data-motion-default="completed"' in html
    assert '<div class="mv" data-mv="motion" hidden>' in html
    seg = '<span class="seg" data-pick="motion"><button type="button" data-v="motion">in motion</button>'
    assert html.count(seg) == 4  # the in-motion head and each window's completed head


def test_drawn_facets_draws_motion_for_a_stopped_team_with_closes_and_no_claim():
    assert drawn_facets({"completed": {"day": {"n": 0}, "week": {"n": 2}}}) == ["motion"]
    assert drawn_facets({"completed": {"day": {"n": 0}, "week": {"n": 0}}}) == []
    # `team_groups` reads the clock: a close thirty hours before it, inside the week
    closes = [close("TD-1", 101, 30) | {"closed": _iso(datetime.now(UTC) - timedelta(hours=30))}]
    m = member("a", state="exited", rank=1, slot={}, place="x", progress=[claim("TD-1", status="done")])
    repos = {"/r/samscrape": reading("/r/samscrape", completed=closes)}
    (g,) = [g for g in ui.team_groups([m], (), repos, {}) if g["team"] == "grind"]
    assert g["summary"]["drawn"] == ["repo", "motion"] and not g["summary"]["motion"]


FACE_PROBE = (
    PROBE[: PROBE.index("console.log(")]
    + """
const kept = { "motion:grind": "completed", "motion:stale": "gone" };
const get = (k, d) => (k in kept ? kept[k] : d);
console.log(JSON.stringify([
  AO.motionFace("grind", "motion", get),     // a stored pick wins over a claim
  AO.motionFace("other", "completed", get),  // no pick: the server's default
  AO.motionFace("other", "", get),           // no default: in motion
  AO.motionFace("stale", "completed", get),  // a stored value that is neither: the default
]));
"""
)


def test_the_pick_is_stored_per_team_and_wins_over_the_default():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the pick is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "motion_face_probe.js"
    probe.write_text(FACE_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["completed", "completed", "motion", "completed"]
    js = (UI / "static" / "app.js").read_text()
    assert 'else if (pick === "motion") store.set("motion:" + sum.dataset.team, v);' in js
    assert '$$(".mv", sum).forEach((el) => (el.hidden = el.dataset.mv !== st.motion));' in js
