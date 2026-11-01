"""TD-710 slice 3, design §4.5a *Repo page: settles in 7m on an entry* and *Settings page: settle*, §4.4
*A new entry settles before it is pickable*: the Repo page's row draws the settle clock's mark, *settles in
7m*, with no press (TD-1297: no Hold or Release); the Settings page's **settle** field writes the install's
`settle:` through `set_settings`, and each Repos card shows the repo's own."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks
from test_ui_repo_page import client, fake, reading

from sessionorc import settings as settings_mod
from sessionorc import settle
from sessionorc.agent_common import RpcError
from shiftlead import teamrun
from shiftlead.ui import settings_page as setmod
from shiftlead.ui.repo import ledger_lists

T0 = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


def _marked(root: str) -> dict:
    """The fixture reading with TD-301 settling for seven minutes more, and TD-310 carrying an old clock's
    `held` mark, read as nothing since TD-1297."""
    r = reading(root)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-301"]["settling"] = {"until": (T0 + timedelta(minutes=7)).isoformat()}
    by["TD-310"]["held"] = {"at": (T0 - timedelta(hours=2)).isoformat(), "by": "person"}
    return r


@pytest.mark.unit
def test_the_marks_words_and_the_settle_field_parse():
    assert settle.words({"settling": {"until": (T0 + timedelta(minutes=7)).isoformat()}}, T0) == "settles in 7m"
    assert settle.words({"settling": {"until": T0.isoformat()}}, T0) == "", "a mark past its until says nothing"
    assert settle.words({"held": {"at": (T0 - timedelta(hours=2)).isoformat()}}, T0) == "", "TD-1297"
    assert settle.words({}, T0) == ""
    assert settle.parse_text("design-first 10m, live-check 0") == {"design-first": "10m", "live-check": "0"}
    assert settle.parse_text("  ") == {} and settle.parse_text("Design-First 1h\nbuild 2m") == {
        "design-first": "1h",
        "build": "2m",
    }
    for bad, says in (("design-first", "not a Kind and a duration"), ("design-first soon", "a settle duration")):
        with pytest.raises(ValueError, match=says):
            settle.parse_text(bad)
    with pytest.raises(ValueError, match="is not a Kind"):
        settle.parse({"no such": "5m"})
    assert settle.text_of({"design-first": "10m", "build": "0"}) == "design-first 10m, build 0"
    assert settle.text_of(None) == ""


@pytest.mark.unit
def test_a_marked_row_carries_its_words_and_no_press(tmp_path):
    rows = {e["id"]: e for x in ledger_lists(_marked(str(tmp_path)), [], None, T0) for e in x["rows"]}
    assert (rows["TD-301"]["settle"], rows["TD-310"]["settle"], rows["TD-311"]["settle"]) == ("settles in 7m", "", "")
    assert all("settle_mark" not in e for e in rows.values()), "no Hold or Release to give (TD-1297)"
    # the claim's *held by* keeps its key
    assert rows["TD-310"]["held"] == ""
    lists = ledger_lists(_marked(str(tmp_path)), [], None, T0 + timedelta(minutes=8))
    late = {e["id"]: e for x in lists for e in x["rows"]}
    assert late["TD-301"]["settle"] == "", "a window that ran out says nothing"


@pytest.mark.unit
def test_a_withheld_entry_is_not_counted_pickable_and_its_page_kind_stays(tmp_path):
    r = _marked(str(tmp_path))
    assert teamrun.lane_kinds(r)["pickable"] == 6 - 1 and teamrun.lane_kinds(r)["for-you"] == 1  # settling only
    assert teamrun.lane_kinds(reading(str(tmp_path)))["pickable"] == 6


@pytest.mark.unit
def test_the_repo_page_draws_settles_with_no_press_and_has_no_hold_route(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    r = _marked(root)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    now = datetime.now(UTC)
    by["TD-301"]["settling"] = {"until": (now + timedelta(minutes=7, seconds=30)).isoformat()}
    by["TD-310"]["held"] = {"at": (now - timedelta(hours=2, minutes=1)).isoformat(), "by": "person"}
    calls: list[str] = []
    Base = fake({root: r}, [])

    class Fake(Base):
        async def call(self, method, **kw):
            calls.append(method)
            return await super().call(method, **kw)

    c = client(monkeypatch, tmp_path, Fake)
    html = c.get("/repo/samscrape?open=pickable").text  # every row: past the fold too (TD-882)
    row = html[html.index('id="TD-301"') : html.index("</div>", html.index('id="TD-301"'))]
    assert "· settles in 7m</span>" in row and "<button" not in row
    assert "data-tdhold" not in html and "held 2h" not in html and "ledger_release" not in html
    assert ">Hold</button>" not in html and ">Release</button>" not in html
    assert c.post("/api/ledger/hold", json={"repo": "samscrape", "id": "TD-301"}).status_code in (404, 405)
    assert "td_hold" not in calls


async def test_set_settings_writes_the_installs_settle_and_an_empty_map_removes_it(agent):
    await park_ticks(agent)
    got = await agent.rpc_set_settings(settle={"Design-First": "10m", "build": 0})
    assert got["settle"] == {"design-first": "10m", "build": "0"}
    assert settings_mod.load()["settle"] == {"design-first": "10m", "build": "0"}
    assert (await agent.rpc_settings())["settle"] == {"design-first": "10m", "build": "0"}
    with pytest.raises(RpcError, match="a settle duration is like 5m"):
        await agent.rpc_set_settings(settle={"design-first": "soon"})
    with pytest.raises(RpcError, match="ao-w cannot change the settings"):
        await agent.rpc_set_settings(settle={}, caller="ao-w")
    await agent.rpc_set_settings(settle={})
    assert "settle" not in settings_mod.load() and (await agent.rpc_settings())["settle"] == {}


@pytest.mark.unit
def test_a_repos_card_shows_its_settle_read_only(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / ".shiftlead.yml").write_text("settle: {design-first: 10m}\n")
    (tmp_path / "b").mkdir()
    cards = {c["name"]: c for c in setmod.repo_cards([str(tmp_path / "a"), str(tmp_path / "b")], {})}
    a = {r["key"]: r for r in cards["a"]["rows"]}["settle"]
    b = {r["key"]: r for r in cards["b"]["rows"]}["settle"]
    assert (a["value"], a["default"]) == ("design-first 10m", False) and (b["value"], b["default"]) == ("none", True)


def test_the_settle_field_writes_through_set_settings(subprocess_agent):
    from fastapi.testclient import TestClient

    from sessionorc.client import call_sync
    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        page = c.get("/settings").text
        assert 'id="setsettle"' in page and 'name="settle" value=""' in page and "the built-in: design-first 5m" in page
        assert c.post("/api/settings/settle", json={"settle": "design-first 10m"}).json()["ok"]
        assert call_sync("settings")["settle"] == {"design-first": "10m"}
        assert 'name="settle" value="design-first 10m"' in c.get("/settings").text
        bad = c.post("/api/settings/settle", json={"settle": "design-first"})
        assert bad.status_code == 400 and "not a Kind and a duration" in bad.json()["detail"]
        assert c.post("/api/settings/settle", json={"settle": ""}).json()["ok"]
        assert call_sync("settings")["settle"] == {}


@pytest.mark.unit
def test_shiftleads_own_file_settles_a_design_first_entry_ten_minutes_and_a_bad_settle_is_refused(tmp_path):
    from pathlib import Path

    from shiftlead import repoconfig

    here = Path(__file__).resolve().parents[1]
    assert repoconfig.load(here).settle == {"design-first": "10m"}
    assert settle.spans(here)["design-first"] == 600
    (tmp_path / ".shiftlead.yml").write_text("settle: {design-first: soon}\n")
    with pytest.raises(ValueError, match="`settle`: a settle duration is like 5m"):
        repoconfig.load(tmp_path)
