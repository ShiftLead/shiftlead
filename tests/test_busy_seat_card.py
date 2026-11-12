"""TD-1672 slice 2 (TD-1569's build), design §4.9a *A busy seat is left alone*, §4.5a *team groups* and *rollup:
press and menus*: where a team's start would leave a busy seat running (`teamrun.rows`' `startable`), the card
draws Start beside Wind down and Stop now whatever its *stopped* reading, Start's confirm, closes and leaves
built from `startable` and never from `concluded`, the *not concluded* line hidden; the rollup's ⋯ offers all
three; and a `startable` the card's own live count disagrees with is not copied."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_ui_teams import badged, client, org_doc, world, write_org  # noqa: F401 — fixtures

from shiftlead import teamrun
from shiftlead.ui import org as uiorg

pytestmark = pytest.mark.unit

OUT = {"at": "2026-11-12T08:00:00Z", "why": "nothing pickable"}
CLEAN = {"dirty": 0, "unpushed": 0, "upstream": "origin/x"}
STATIC = Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js"


def _seated(tmp_path) -> None:
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"]["techlead"] = {"name": "techlead-ao"}
    write_org(tmp_path, doc)


def _seat(state: str = "working") -> dict:
    return {**badged("techlead-ao", "ao-grind", state=state), "seat": {"trigger": "asks"}, "git": dict(CLEAN)}


def _head(client) -> str:  # noqa: F811
    html = client.get("/").text
    sec = html[html.index('<section class="tgroup" data-team="ao-grind"') :]
    return sec[: sec.index('<div class="grid">')]


def test_exited_members_and_a_working_seat_draw_start_beside_wind_down(world, client):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    fleet.sessions = [
        {**badged("orc-ao", "ao-grind", state="exited"), "tail": []},
        {**badged("grind-1", "ao-grind", state="exited"), "tail": []},
        {**_seat(), "tail": []},
    ]
    (row,) = [r for r in client.get("/api/teams").json()["teams"] if r["name"] == "ao-grind"]
    assert row["startable"] == {"closes": [], "leaves": [{"name": "techlead-ao", "state": "working"}]}
    head = _head(client)
    assert 'data-team-act="start"' in head and ">Wind down</button>" in head and ">Stop now</button>" in head
    assert 'data-confirm="Start ao-grind? It leaves techlead-ao running (working)."' in head
    assert 'data-leaves="It leaves techlead-ao running (working)."' in head and "data-closes" not in head
    assert head.index('data-team-act="start"') < head.index('data-team-act="stop"')
    assert "notconcluded" not in head


def test_a_concluded_crew_with_a_busy_seat_closes_the_rest_and_leaves_the_seat(world, client):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    fleet.sessions = [
        {**badged("orc-ao", "ao-grind", state="idle"), "tail": [], "out_of_work": OUT, "git": dict(CLEAN)},
        {**badged("grind-1", "ao-grind", state="idle"), "tail": [], "out_of_work": OUT, "git": dict(CLEAN)},
        {**_seat("needs-you"), "tail": []},
    ]
    head = _head(client)
    assert "It first closes grind-1, orc-ao — each idle and declared" in head
    assert "refuses the start instead; it leaves techlead-ao running (needs-you)." in head
    assert 'data-closes="grind-1, orc-ao"' in head and ">Wind down</button>" in head
    assert "notconcluded" not in head


def test_no_busy_seat_keeps_todays_controls(world, client):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    fleet.sessions = [
        {**badged("orc-ao", "ao-grind", state="working"), "tail": []},
        {**badged("grind-1", "ao-grind", state="working"), "tail": []},
    ]
    head = _head(client)
    assert 'data-team-act="start"' not in head and ">Wind down</button>" in head
    assert "not concluded: " in head


def test_startable_is_not_copied_where_the_live_counts_differ(world, client, monkeypatch):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    fleet.sessions = [
        {**badged("orc-ao", "ao-grind", state="exited"), "tail": []},
        {**_seat(), "tail": []},
    ]
    rows = teamrun.rows

    def off_by_one(*a, **kw):
        out = rows(*a, **kw)
        for r in out:
            if r["startable"]:
                r["live"] += 1  # the definitions' read and the card's disagree about what is live
        return out

    monkeypatch.setattr(teamrun, "rows", off_by_one)
    head = _head(client)
    assert 'data-team-act="start"' not in head and "data-leaves" not in head and ">Wind down</button>" in head


def _team_item(**kw) -> dict:
    return {"kind": "team", "key": "t:ao-grind", "team": "ao-grind", "repo": "", "members": [], "defined": True} | kw


@pytest.mark.parametrize(
    "item, acts",
    [
        (_team_item(), ["new-team", "wind-down", "stop-now"]),
        (_team_item(stopped=True), ["start", "new-team"]),
        (_team_item(startable={"closes": [], "leaves": []}), ["new-team", "start", "wind-down", "stop-now"]),
        (
            _team_item(stopped=True, startable={"closes": ["a"], "leaves": []}),
            ["start", "new-team", "wind-down", "stop-now"],
        ),
        (_team_item(defined=False, startable={"closes": [], "leaves": []}), ["new-team"]),
    ],
)
def test_the_rollups_menu_offers_start_beside_wind_down_where_startable(item, acts):
    (row,) = uiorg.rollup_rows([item], set())
    assert row["acts"] == acts


def test_the_page_says_what_a_start_left_running():
    js = STATIC.read_text()
    assert "b.dataset.leaves" in js  # the nothing-to-pick dialog's leave clause
    assert "o.left_running" in js and "left running: " in js  # the start's toast
