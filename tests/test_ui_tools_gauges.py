"""The Tools page's gauges (design §4.2b *The gauge*, §4.5a *Tools page: an account* **keep back**, TD-1975): drawn
from the `tools` read's `gauges`, and the Settings page's Usage card leaving a switched home's accounts to it."""

from datetime import UTC, datetime, timedelta

from fixture_tools_tree import read

from shiftlead.ui import app as app_mod
from shiftlead.ui import settings_page as setmod

NOW = datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def test_the_view_gives_each_window_its_words_and_an_older_agents_read_draws_unread():
    g = {"billing": "subscription", "read_at": _iso(NOW - timedelta(minutes=5)), "stale": False, "unread": False,
         "windows": [{"label": "week", "pct": 6.0, "reserve": 15, "keep": 15, "room": 79, "line": 85,
                      "resets": _iso(NOW + timedelta(days=2))},
                     {"label": "5h", "pct": 41.0, "reserve": {"per_day": 10}, "keep": None, "room": 59, "line": None,
                      "resets": None}],
         "gone": [{"label": "week (opus)", "reserve": 20}]}  # fmt: skip
    v = setmod.gauge_view(g)
    week, five = v["gauges"]
    assert (week["value"], week["used"], week["keep"], week["room"], week["line"]) == ("15", 6.0, 15, 79, "→ line 85%")
    assert week["resets"] and five["value"] == "10/day" and v["age"].startswith("read ")
    assert v["gone"] == [{"label": "week (opus)", "value": "20", "line": "not reported: its reading reports week, 5h"}]
    old = setmod.gauge_view([])  # an older agent: `gauges: []`, never filled
    assert old["unread"] and [w["label"] for w in old["gauges"]] == ["week"]
    assert [w["label"] for w in setmod.gauge_view(None, "metered")["gauges"]] == ["week", "day", "month"]
    metered = setmod.gauge_view({"billing": "metered", "windows": [
        {"label": "day", "pct": 64.0, "reserve": "$5", "spent": {"total": 9, "cost": 3.2}}]})  # fmt: skip
    assert metered["metered"] and "spent $3.20 · 64%" in metered["gauges"][0]["line"]
    assert setmod.gauge_view({"billing": "mixed", "windows": []})["mixed"]


def test_the_tools_page_draws_the_reads_gauges_and_keep_back_writes_through_the_settings_card(monkeypatch):
    from fastapi.testclient import TestClient

    calls = []
    got = read()
    got["tools"][0]["accounts"][0]["gauges"] = {
        "billing": "subscription", "read_at": _iso(NOW), "stale": True, "unread": False, "gone": [],
        "windows": [{"label": "week", "pct": 6.0, "reserve": 15, "keep": 15, "room": 79, "line": 85}]}  # fmt: skip

    async def call(m, **p):
        calls.append((m, p))
        return got if m == "tools" else {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        r = c.get("/tools")
        assert r.status_code == 200
        assert 'class="toolgauges" data-account="claude-code:paul"' in r.text
        assert "room for unattended work: 79%" in r.text and 'name="week" value="15"' in r.text
        assert ">stale<" in r.text
        assert 'data-account="gemini:paul-google" data-metered="1"' in r.text  # unfilled: the home's windows
        r = c.post("/api/settings/usage", json={"account": "claude-code:paul", "reserves": {"week": "20"}})
    assert ("set_settings", {"reserves": {"week": 20}, "account": "claude-code:paul"}) in calls
    assert not any(m in ("usage", "gate") for m, _ in calls[:2])  # the page reads no usage of its own


def test_a_switched_home_leaves_only_the_accounts_the_tools_page_draws():
    assert setmod.tools_accounts(None) is None and setmod.tools_accounts({"switched": False, "tools": []}) is None
    assert setmod.tools_accounts(read()) == {"claude-code:paul", "gemini:paul-google"}


def test_a_limited_login_draws_limited_till_its_reset_in_local_time_or_limited_with_none():
    card = read()["tools"][0]
    till = NOW + timedelta(hours=2)
    card["logins"][0].update(state="limited", till=_iso(till))
    card["logins"][1].update(state="limited", till=None)
    tree = app_mod.login_tree(card, "/home/x")
    said = {lg["name"]: lg["said"] for lg in card["logins"]}
    today = till.astimezone().date() == datetime.now().astimezone().date()  # +2h may cross local midnight
    assert said[card["logins"][0]["name"]] == f"limited till {till.astimezone():{'%H:%M' if today else '%a %H:%M'}}"
    assert said[card["logins"][1]["name"]] == "limited"
    assert tree["accounts"]
    week = NOW + timedelta(days=3)  # a reset not today has its weekday in front
    card["logins"][0].update(state="limited", till=_iso(week))
    app_mod.login_tree(card, "/home/x")
    assert card["logins"][0]["said"] == f"limited till {week.astimezone():%a %H:%M}"
