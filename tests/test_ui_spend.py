"""TD-832 slice 1, design §4.5 screen 13 *Spend* and §4.5a *Spend page*, *Sessions top bar: usage chip*: the page
draws the home's `seats` reading — the head and its picks carried in the URL, the Over time chart by team or
by role with the picked bar outlined and the bars before the ledger began dashed, By team and Top sessions on
All, a team's line, By seat with its role subtotals and Finished entries on one team — and the usage chip
opens it. The readings are `sessionorc.seats.reading` over a hand-written ledger, so the page is tested
against the shape the home serves."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from sessionorc import seats
from sessionorc.client import AgentError
from shiftlead.ui.spend import money, period_label, spend_picks, spend_query, spend_view

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)  # a Saturday
TODAY = NOW.date()
W = seats.WEIGHTS


def _row(figure, turns=1, name="w", team="ao-grind", role="grinder", repo="shiftlead", refs=None, **m):
    return {
        "name": name, "team": team, "role": role, "repo": repo, "metered": False, "refs": refs or {},
        "models": {"m": {"input": 1000, "output": 0, "cache_read": 0, "cache_write": 0, "turns": turns,
                         "figure": figure, "past_200k": 0.0, "past_300k": 0.0} | m},
    }  # fmt: skip


def ledger():
    """Two teams and an interactive session over two days, two grinders, an entry finished today."""
    today = {
        "g1": _row(52.3, 611, "grinder-ao-1", past_200k=6.3, refs={"TD-813": {"figure": 24.7, "turns": 301}}),
        "g2": _row(47.9, 540, "grinder-ao-2", refs={"between": {"figure": 6.1, "turns": 20}}),
        "d1": _row(38.2, 412, "designer-ao-1", role="designer"),
        "c1": _row(10.0, 50, "dc-grinder", team="dc-grind"),
        "p1": _row(9.45, 147, "ao-paul", team="", role=""),
        "outside": {**_row(1.9, 21), "name": "outside", "team": "", "role": ""},
    }
    yesterday = {"g1": _row(20.0, 100, "grinder-ao-1"), "c1": _row(40.0, 100, "dc-grinder", team="dc-grind")}
    return {
        "began": "2026-10-16T00:00:00Z",
        "days": {"2026-10-17": today, "2026-10-16": yesterday},
        "refs": {"shiftlead TD-813": {"first_claimed": "2026-10-17T06:00:00Z", "done_at": "2026-10-17T11:40:00Z"}},
    }


def reading(**kw):
    return seats.reading(ledger(), kw.pop("window", "day"), NOW, weights=W, **kw) | {"unknown": {}}


FLEET = [
    {"id": "g1", "name": "grinder-ao-1", "state": "idle", "created": "2026-10-17T00:00:00Z"},
    {"id": "d1", "name": "designer-ao-1", "state": "exited", "created": "2026-10-16"},
]


def fake(calls: list | None = None, down: bool = False, no_seats: bool = False):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "seats":
                if calls is not None:
                    calls.append(kw)
                if no_seats:
                    raise AgentError("unknown method: seats")
                try:
                    return reading(**kw)
                except ValueError as e:  # as `rpc_seats` refuses it
                    raise AgentError(str(e)) from None
            if method == "queue":
                top = {"qid": "shiftlead#TD-813", "title": "The page's send lands once"}
                return {"cards": [{"id": "c", "top": top}]}
            return {"list": [], "usage": {}, "host": {"name": "kmaster"}}.get(method, {})

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(ui, "datetime", Frozen)
    return TestClient(ui.create_app())


def test_the_picks_are_read_from_the_url_and_written_back_short():
    assert spend_picks({}) == {"view": "spend", "window": "day", "at": "", "team": "", "top": False}
    assert spend_picks({"window": "year", "team": "interactive", "top": "all"}) == {
        "view": "spend",
        "window": "day",
        "at": "",
        "team": "",
        "top": True,
    }  # fmt: skip — a bad window reads as day, and `team=interactive` (which `ao spend` reads) opens All
    p = spend_picks({"window": "week", "at": "2026-10-05", "team": "ao-grind"})
    assert spend_query(p) == "/spend?team=ao-grind&window=week&at=2026-10-05"
    assert spend_query(p, window="day", at="") == "/spend?team=ao-grind"
    assert spend_query(spend_picks({}), top=True) == "/spend?top=all"


def test_a_period_and_a_figure_are_named_as_the_design_says():
    assert period_label("day", date(2026, 10, 16), TODAY) == "Fri 16 Oct"
    assert period_label("week", date(2026, 10, 12), TODAY) == "week of 12 Oct"
    assert period_label("month", date(2026, 10, 1), TODAY) == "October"
    assert period_label("month", date(2025, 10, 1), TODAY) == "October 2025"
    assert (money(1498.2), money(92.4), money(0), money(3.5, "$")) == ("≈$1,498", "≈$92.40", "≈$0.00", "$3.50")


def test_all_draws_by_team_with_its_change_and_spent_most_and_top_sessions():
    v = spend_view(reading(), spend_picks({}), fleet=FLEET, today=TODAY)
    names = [r["name"] for r in v["by_team"]]
    assert names == ["ao-grind", "dc-grind", "interactive sessions", "outside shiftlead"]  # most first, outside last
    grind, dc, interactive, outside = v["by_team"]
    assert grind["href"] == "/spend?team=ao-grind" and not interactive["href"] and not outside["href"]
    assert grind["figure"] == "≈$138" and grind["most"] == "grinder-ao-1 · 38%"
    assert grind["change"] == "" and dc["change"] == ""  # the current day: the previous to date is not drawn
    assert grind["week"] == "≈$158" and grind["month"] == "≈$158"
    top = v["top"]
    assert [s["name"] for s in top][:3] == ["grinder-ao-1", "grinder-ao-2", "designer-ao-1"]
    assert top[0]["href"] == "/focus/g1"  # a live record's Focus
    assert top[2]["href"] == "/transcript/d1"  # an ended one's Transcript
    assert any(s["name"] == "ao-paul · shiftlead" and s["team"] == "interactive" for s in top)
    assert v["top_n"] == 5 and v["period"] == "Sat 17 Oct" and not v["metered"]


def test_a_past_week_reads_its_change_to_date_and_the_arrows_stop_at_the_ledger_and_now():
    v = spend_view(reading(window="week"), spend_picks({"window": "week"}), today=TODAY)
    assert v["back"] == "" and v["forward"] == ""  # the ledger began this week; the current one is the last
    day = spend_view(reading(), spend_picks({}), today=TODAY)
    assert day["back"] == "/spend?at=2026-10-16" and day["forward"] == ""
    past = spend_view(reading(at="2026-10-16"), spend_picks({"at": "2026-10-16"}), today=TODAY)
    assert past["back"] == "" and past["forward"] == "/spend"  # back to the current day, its `at` dropped
    (dc,) = [r for r in past["by_team"] if r["name"] == "dc-grind"]
    assert dc["change"] == "—"  # nothing the day before: no ratio


def test_the_chart_stacks_by_team_outlines_the_picked_bar_and_dashes_the_bars_before_the_ledger():
    v = spend_view(reading(), spend_picks({}), today=TODAY)
    bars = v["chart"]["bars"]
    assert len(bars) == 30 and bars[-1]["picked"] and not bars[-2]["picked"]
    assert all(b["before"] for b in bars[:-2]) and not bars[-2]["before"]  # the ledger began on the 16th
    assert bars[-2]["href"] == "/spend?at=2026-10-16" and bars[-1]["href"] == "/spend"
    legend = [g["word"] for g in v["chart"]["legend"]]
    assert legend == ["ao-grind", "dc-grind", "interactive sessions", "outside shiftlead"]
    assert "ao-grind: ≈$138" in bars[-1]["title"]
    week = spend_view(reading(window="week"), spend_picks({"window": "week"}), today=TODAY)["chart"]["bars"]
    assert len(week) == 12 and "partial: the ledger begins 2026-10-16" in week[-1]["title"]


def test_a_team_draws_its_line_by_seat_with_a_role_subtotal_and_its_finished_entries():
    picks = spend_picks({"team": "ao-grind"})
    titles = {"TD-813": "The page's send lands once"}
    v = spend_view(reading(team="ao-grind"), picks, fleet=FLEET, all_teams=["ao-grind", "dc-grind"], titles=titles,
                   today=TODAY)  # fmt: skip
    assert v["line"] == "≈$138 · 3k tokens today (so far) · yesterday ≈$20.00 · this week ≈$158 · October ≈$158"
    assert [c[1] for c in v["chips"]] == ["All", "ao-grind", "dc-grind"]
    rows = [(s["name"], bool(s.get("subtotal"))) for s in v["seats"]]
    assert rows == [("grinder-ao-1", False), ("grinder-ao-2", False), ("grinders", True), ("designer-ao-1", False)]
    g1, g2, sub, d1 = v["seats"]
    assert sub["figure"] == "≈$100" and sub["pct"] == "72%" and sub["per"] == "1 · median ≈$24.70"
    # each seat's own: grinder-ao-1 spent on TD-813, grinder-ao-2 on nothing finished
    assert (g1["per"], g1["per_title"]) == ("1 · median ≈$24.70", "TD-813")
    assert (g2["per"], g2["per_title"], d1["per"]) == ("—", "", "—")
    assert g1["title"].splitlines()[0] == "input 1k · output 0 · cache read 0 · cache write 0"  # kinds_line, no *tok*
    assert g2["between"] == "≈$6.10" and g1["past_200k"] == "12%"
    assert [g["word"] for g in v["chart"]["legend"]] == ["grinder", "designer"]  # by role
    (e,) = v["entries"]
    assert (e["ref"], e["title"], e["href"], e["figure"], e["held"]) == (
        "TD-813", "The page's send lands once", "/queue#TD-813", "≈$24.70", "5h40m",
    )  # fmt: skip
    assert e["roles"] == ["grinder ≈$24.70"]


def test_the_three_tables_draw_a_tokens_cell_and_the_totals_and_bars_carry_tokens(tmp_path, monkeypatch):
    """§4.5 screen 13 *Tokens*, §4.5a *Spend page* (TD-930): a **tokens** cell beside the figure in By team, Top
    sessions and By seat (a role's subtotal too), the short shape without *tok*, the four kinds on its hover; a
    wholly unweighed row reads *unweighed* in its figure cell and its count in the tokens cell; a row with no
    turns *0*; a row whose reading has no `tokens` an empty cell; the totals and each bar's hover carry tokens."""
    led = ledger()
    led["days"]["2026-10-17"]["g1"]["models"]["m"] |= {"output": 310_000, "cache_read": 88_000_000}
    led["days"]["2026-10-17"]["c1"] = _row(0.0, 50, "dc-grinder", team="dc-grind", unweighed=50)
    got = seats.reading(led, "day", NOW, weights=W) | {"unknown": {}}
    v = spend_view(got, spend_picks({}), fleet=FLEET, today=TODAY)
    by = {r["name"]: r for r in v["by_team"]}
    assert (by["ao-grind"]["tok"], by["ao-grind"]["figure"]) == ("88.3M", "≈$138")
    assert by["ao-grind"]["tok_title"] == "input 3k · output 310k · cache read 88M · cache write 0"
    assert (by["dc-grind"]["figure"], by["dc-grind"]["tok"]) == ("unweighed", "1k")  # the count once, in its cell
    assert v["whole"] == "≈$150 + 1k tok unweighed · 88.3M tokens"
    top = {s["name"]: s for s in v["top"]}
    assert (top["grinder-ao-1"]["tok"], top["dc-grinder"]["figure"], top["dc-grinder"]["tok"]) == (
        "88.3M", "unweighed", "1k",
    )  # fmt: skip
    bar = [b for b in v["chart"]["bars"] if b["picked"]][0]
    assert bar["title"].splitlines()[:2] == [
        "Sat 17 Oct: ≈$150 + 1k tok unweighed · 88.3M tok",
        "ao-grind: ≈$138 · 88.3M tok",
    ]
    assert bar["total"] == "≈$150 + 1k tok unweighed"  # the total above a bar stays money alone

    mine = seats.reading(led, "day", NOW, team="ao-grind", weights=W) | {"unknown": {}}
    t = spend_view(mine, spend_picks({"team": "ao-grind"}), fleet=FLEET, today=TODAY)
    g1, g2, sub, d1 = t["seats"]
    assert (g1["tok"], g2["tok"], sub["tok"], d1["tok"]) == ("88.3M", "1k", "88.3M", "1k")
    assert sub["tok_title"] == "input 2k · output 310k · cache read 88M · cache write 0"
    assert t["total"] == "≈$138 · 88.3M tokens"
    assert t["line"].startswith("≈$138 · 88.3M tokens today (so far)")

    old = {**mine, "seats": [{k: v for k, v in s.items() if k != "tokens"} for s in mine["seats"]]}
    assert {s["tok"] for s in spend_view(old, spend_picks({"team": "ao-grind"}), today=TODAY)["seats"]} == {""}
    led["days"]["2026-10-16"]["x1"] = _row(5.0, 10, "old", team="old-grind")  # spent yesterday, not today
    quiet = spend_view(seats.reading(led, "day", NOW, weights=W) | {"unknown": {}}, spend_picks({}), today=TODAY)
    assert {r["name"]: r["tok"] for r in quiet["by_team"]}["old-grind"] == "0"

    c = client(monkeypatch, tmp_path, fake())
    whole = spend_view(reading(), spend_picks({}), today=TODAY)
    team = spend_view(reading(team="ao-grind"), spend_picks({"team": "ao-grind"}), today=TODAY)
    tables = _tables(c.get("/spend").text) | _tables(c.get("/spend?team=ao-grind").text)
    for name, rows in (("By team", whole["by_team"]), ("Top sessions", whole["top"]), ("By seat", team["seats"])):
        head, body = tables[name]
        assert body and all(len(cells) == len(head) for cells in body), name  # no cell lost, none shifted left
        at = head.index("tokens")
        assert sorted(cells[at] for cells in body) == sorted(r["tok"] for r in rows), name
        titles = tables[name + " titles"]
        assert titles and all(re.fullmatch(r"input .+ · cache write .+", t) for t in titles), name


def _tables(html: str) -> dict[str, object]:
    """Each Spend table by its heading: its header cells and its body rows' cells as text, and the tokens
    cells' hover titles under `<heading> titles` — so a cell gone from one table is seen in that table."""
    out: dict[str, object] = {}
    for m in re.finditer(
        r'<span class="h2">([^<]+)</span>(?:(?!<span class="h2">).)*?<table>(.*?)</table>', html, re.S
    ):
        head = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", m[2], re.S)]
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m[2].split("</thead>", 1)[-1], re.S)
        rows = [r for r in rows if "colspan" not in r]  # an empty table's one note row
        out[m[1]] = (
            head,
            [[re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)] for r in rows],
        )
        out[m[1] + " titles"] = re.findall(r'<td class="spfold mono" title="([^"]+)">', m[2])
    return out


def test_an_unweighed_figure_is_named_beside_never_in_it():
    from shiftlead.ui.spend import figure

    assert figure({"figure": 0.0, "unweighed_tokens": 4_100_000}) == "unweighed · 4.1M tok"
    assert figure({"figure": 2.0, "unweighed_tokens": 812_000, "unit": "$"}) == "$2.00 + 812k tok unweighed"


def test_a_figure_told_its_tokens_follow_writes_its_count_once_in_the_word_asked():
    """§4.4 *Tokens beside every figure* (TD-929): `count` appends the row's every kind summed, in the chip's
    short shape; a wholly unweighed row its count once; `False` (a table cell) none; a row with no `tokens` in
    its reading falls back to the bare composition, so its unweighed count is never lost."""
    from shiftlead.ui.spend import figure, tokens

    kinds = {"input": 1_200_000, "output": 300_000, "cache_read": 93_000_000, "cache_write": 700_000}
    row = {"figure": 426.0, "tokens": kinds}
    assert figure(row, count="tok") == "≈$426 · 95.2M tok"
    assert figure(row, count="tokens") == "≈$426 · 95.2M tokens"
    assert figure(row, count=False) == figure(row) == "≈$426"
    part = {"figure": 38.2, "unweighed_tokens": 4_100_000, "tokens": {"input": 8_400_000}}
    assert figure(part, count="tok") == "≈$38.20 + 4.1M tok unweighed · 8.4M tok"
    assert figure(part, count=False) == "≈$38.20 + 4.1M tok unweighed"
    wholly = {"figure": 0.0, "unweighed_tokens": 4_100_000, "tokens": {"input": 4_100_000}}
    assert figure(wholly, count="tok") == "unweighed · 4.1M tok"
    assert figure(wholly, count=False) == "unweighed"
    old = {"figure": 0.0, "unweighed_tokens": 4_100_000}  # a reading from before `tokens`
    assert figure(old, count="tok") == figure(old, count=False) == figure(old) == "unweighed · 4.1M tok"
    assert tokens(22_000_000) == "22M tok" and tokens(2_100_000_000) == "2.1B tok"


def test_the_page_draws_the_reading_and_a_pick_re_reads_its_body(tmp_path, monkeypatch):
    calls: list = []
    c = client(monkeypatch, tmp_path, fake(calls))
    html = c.get("/spend").text
    assert calls[0] == {"window": "day"}
    assert "By team" in html and "Top sessions" in html and "Over time" in html
    assert "≈ API-equivalent at your weights" in html and 'id="usagechip" href="/spend"' in html
    assert re.search(r'<a href="/spend\?window=week" data-spend aria-pressed="false">Week</a>', html)
    assert 'class="spbar picked"' in html and 'class="spbar before"' in html
    calls.clear()
    part = c.get("/spend?team=ao-grind&window=week&part=1").text
    assert calls[0] == {"window": "week", "team": "ao-grind"} and calls[1] == {"window": "week"}  # the chips' teams
    assert "<html" not in part and "By seat" in part and "Finished entries" in part
    assert "The page&#39;s send lands once" in part
    assert c.get("/api/spend?window=month").json()["window"] == "month"


def test_an_older_home_and_a_period_the_ledger_does_not_hold_are_said(tmp_path, monkeypatch):
    html = client(monkeypatch, tmp_path, fake(no_seats=True)).get("/spend").text
    assert "the home did not serve the seat ledger: unknown method: seats" in html
    calls: list = []
    html = client(monkeypatch, tmp_path, fake(calls)).get("/spend?at=2026-09-01").text
    assert "before the seat ledger begins" in html and "the current period is drawn" in html
    assert calls[-1] == {"window": "day"} and "By team" in html


def test_a_bar_of_a_chart_shifted_back_keeps_its_period_and_only_the_current_drops_it():
    old = ledger()
    old["days"]["2026-09-01"] = {"g1": _row(5.0, 10, "grinder-ao-1")}
    got = seats.reading(old, "day", NOW, weights=W, at="2026-09-01") | {"unknown": {}}
    bars = spend_view(got, spend_picks({"at": "2026-09-01"}), today=TODAY)["chart"]["bars"]
    assert bars[0]["at"] == "2026-09-01" and bars[0]["picked"]  # the picked day is the first bar
    assert bars[-1]["at"] == "2026-09-30" and bars[-1]["href"] == "/spend?at=2026-09-30"  # not today's link
    assert spend_view({"window": "day"}, spend_picks({}), today=TODAY) == {"served": False}  # no `at`: not served


def test_a_team_card_carries_today_s_figure_linking_to_its_spend_page_and_none_while_it_spent_nothing():
    """§4.5a *team card: spend* (TD-832 slice 2): today's figure, the week's and the seat that spent most in
    its hover, the press the Spend page on the team; absent while the team spent nothing today."""
    import asyncio

    from shiftlead.ui.app import Readings, team_groups, templates
    from shiftlead.ui.spend import team_figure

    rows = {t["team"]: t for t in reading()["teams"]}
    fig = team_figure("ao-grind", rows["ao-grind"])
    assert fig["text"] == "≈$138 today" and fig["href"] == "/spend?team=ao-grind"
    assert fig["title"].startswith("≈$158 this week · grinder-ao-1 spent most today, 38%")
    assert team_figure("dc-grind", None) is None and team_figure("t", {"team": "t", "figure": 0.0, "turns": 0}) is None
    views = [{"id": "g1", "name": "grinder-ao-1", "team": "ao-grind", "state": "idle", "rank": 5, "controllers": []}]
    (g,) = team_groups(views, spend=rows)
    head = templates.get_template("group_head.html").render(g=g)
    assert '<a class="meta spendfig" href="/spend?team=ao-grind" title="≈$158 this week' in head
    assert "≈$138 today</a>" in head
    (quiet,) = team_groups(views)
    assert "spendfig" not in templates.get_template("group_head.html").render(g=quiet)

    calls: list = []

    async def call(method, **kw):
        calls.append((method, kw))
        if len(calls) > 1:
            raise AgentError("unknown method: seats")
        return reading(**kw)

    rd = Readings(call)
    assert set(asyncio.run(rd.team_spend())) == {"ao-grind", "dc-grind", "interactive", "outside"}
    asyncio.run(rd.team_spend())  # the cached reading: no second read inside SPEND_TTL
    assert calls == [("seats", {"window": "day"})]
    rd.spend_cache["at"] = -1e9
    assert asyncio.run(rd.team_spend()) == {}  # an older home: the figures are left off


def test_the_org_and_repo_pages_draw_the_team_cards_spend_figure(tmp_path, monkeypatch):
    """TD-873: each page hands `team_groups` the `seats` reading by team, so the card's **spend** figure
    is drawn on a page load, not only by `team_groups` called apart (§4.5a *team card: spend*, TD-832)."""
    import test_ui_repo_page as rp

    root = str(tmp_path / "samscrape")
    base = rp.fake({root: rp.reading(root)}, [rp.rec("grinder-ao-1", root, team="ao-grind")])

    class Fake(base):
        async def call(self, method, **kw):
            return reading(**kw) if method == "seats" else await super().call(method, **kw)

    c = rp.client(monkeypatch, tmp_path, Fake)
    for path in ("/", "/repo/samscrape"):
        html = c.get(path).text
        assert '<a class="meta spendfig" href="/spend?team=ao-grind"' in html, path
        assert "≈$138 today</a>" in html, path


def test_the_weights_card_draws_the_read_weights_and_saves_only_what_differs_from_the_default():
    """§4.5a *Settings page: Usage* **weights** (TD-832 slice 3): a row per model prefix with its four prices
    and the *as of* date; Save sends the rows that are not the design's own at its own prices."""
    from shiftlead.ui.settings_page import weights_body, weights_card

    card = weights_card({**W, "claude-opus": {"input": 6, "output": 30}, "my-model": {"input": 1.5}})
    rows = {r["model"]: r for r in card["rows"]}
    assert card["as_of"] == "2026-10-17" and list(rows)[0] == "claude-fable"
    assert rows["claude-fable"] == {"model": "claude-fable", "input": "10", "output": "50", "cache_read": "0.25",
                                         "cache_write": "20", "default": True, "shipped": True}  # fmt: skip
    assert not rows["claude-opus"]["default"] and rows["claude-opus"]["cache_read"] == ""
    assert not rows["my-model"]["shipped"] and weights_card(None)["rows"][0]["default"]
    assert weights_card({"x": {"input": 0.1234567, "output": 12345678}})["rows"][0]["input"] == "0.1234567"
    assert weights_card({"x": {"output": 12345678}})["rows"][0]["output"] == "12345678"
    same = [
        {k: r[k] for k in ("model", "input", "output", "cache_read", "cache_write")} for r in weights_card(W)["rows"]
    ]
    assert weights_body(same, "2026-10-17") == {}  # nothing differs: the default holds
    assert weights_body(same[1:], "2026-10-17") == {}  # a shipped row removed comes back at its default
    priced = [{**same[1], "input": "$5", "cache_read": ""}, {"model": " mine ", "input": "2", "output": "8"}]
    assert weights_body(priced, "2026-11-01") == {
        "weights": {"as_of": "2026-11-01", "claude-opus": {"input": 5.0, "output": 20.0, "cache_write": 8.0},
                    "mine": {"input": 2.0, "output": 8.0}}
    }  # fmt: skip
    for rows_, words in (
        ([{"model": "", "input": "1"}], "needs its model prefix"),
        ([{"model": "a", "input": "1"}, {"model": "a", "input": "2"}], "a is named twice"),
        ([{"model": "a", "input": "cheap"}], "a input: $ per million tokens, not 'cheap'"),
        ([{"model": "a", "output": "-1"}], "at or above 0"),
        ([{"model": "a", "input": "inf"}], "at or above 0, not inf"),  # `float()` parses both (TD-873)
        ([{"model": "a", "input": "1", "output": "nan"}], "a output: $ per million tokens, at or above 0, not nan"),
        ([{"model": "a"}], "a: give it at least its input price"),
        ([{"model": "a", "output": "1"}], "a: give it at least its input price"),
        (None, "send {rows"),
    ):
        with pytest.raises(ValueError, match=re.escape(words)):
            weights_body(rows_)
    with pytest.raises(ValueError, match="as of is a date"):
        weights_body([{"model": "a", "input": "1"}], "soon")


def test_the_weights_card_writes_spend_weights_through_set_settings(subprocess_agent):
    from sessionorc.client import call_sync
    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        page = c.get("/settings").text
        assert 'id="setweights"' in page and 'value="claude-opus-5-5"' in page and 'href="/spend"' in page
        assert "API-equivalent" in page and 'name="as_of" value="2026-10-17"' in page
        assert 'aria-label="put claude-opus back at its default price on Save"' in page
        rows = [{"model": "claude-opus", "input": "6", "output": "30", "cache_read": "", "cache_write": ""},
                {"model": "mine", "input": "1", "output": "", "cache_read": "", "cache_write": ""}]  # fmt: skip
        assert c.post("/api/settings/spend", json={"rows": rows, "as_of": "2026-10-17"}).json()["ok"]
        got = call_sync("settings")["spend"]["weights"]
        assert got["claude-opus"] == {"input": 6.0, "output": 30.0} and got["mine"] == {"input": 1.0}
        assert got["claude-fable"] == W["claude-fable"]  # the rows not sent keep the default
        assert 'value="mine"' in c.get("/settings").text
        bad = c.post("/api/settings/spend", json={"rows": [{"model": "x", "input": "free"}]})
        assert bad.status_code == 400 and "x input: $ per million tokens" in bad.json()["detail"]
        assert c.post("/api/settings/spend", json={"rows": [], "as_of": ""}).json()["ok"]
        assert call_sync("settings")["spend"]["weights"] == W  # nothing differs: the key is gone
