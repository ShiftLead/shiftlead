"""The Tools page's gauges (design §4.2b *The gauge*, §4.5a *Tools page: an account* **keep back**, TD-1975): one per
window an account's reading reports, drawn from the same Usage card the Settings page reads."""

from datetime import UTC, datetime, timedelta

from fixture_tools_tree import read

from shiftlead import profiles as profiles_mod
from shiftlead.ui import app as app_mod
from shiftlead.ui import settings_page as setmod

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def _cards(usage, accounts, profiles=None):
    profiles = profiles or {
        "claude-paul": profiles_mod.Profile(name="claude-paul", account="paul"),
        "api": profiles_mod.Profile(name="api", account="key", billing="metered", prices={"input": 3}),
        "sa": profiles_mod.Profile(name="sa", account="split"),
        "sb": profiles_mod.Profile(name="sb", account="split", billing="metered"),
    }
    return {c["account"]: c for c in setmod.usage_cards(profiles, accounts, usage, NOW)}


def test_a_subscription_account_draws_a_gauge_per_window_the_week_first_with_its_reserve_as_a_bay():
    resets = (NOW + timedelta(days=2)).isoformat()
    usage = {"claude-paul": {"tool": "claude-code", "fetched": (NOW - timedelta(minutes=5)).isoformat(), "windows": [
        {"label": "5h", "pct": 41, "resets": (NOW + timedelta(hours=2)).isoformat()},
        {"label": "week", "pct": 6, "resets": resets}]}}  # fmt: skip
    accounts = {"claude-code:paul": {"profiles": ["claude-paul"], "billing": "subscription",
        "reserves": {"week": 15, "5h": {"per_day": 10}}, "windows": [
        {"label": "week", "line": 85, "reserve": 15, "resets": resets, "next": None}]}}  # fmt: skip
    g = setmod.account_gauges(_cards(usage, accounts)["claude-code:paul"], 3600, NOW)
    assert [w["label"] for w in g["gauges"]] == ["week", "5h"]  # the week's first
    week, five = g["gauges"]
    assert (week["used"], week["keep"], week["room"], week["value"]) == (6.0, 15, 79, "15")
    assert week["resets"]  # the reset's day and time, local
    assert (five["keep"], five["value"]) == (None, "10/day")  # a percent per day draws no fixed bay
    assert not g.get("unread") and not g.get("stale") and not g["metered"]


def test_an_account_with_no_reading_draws_an_empty_gauge_and_its_field_and_an_old_one_is_stale():
    accounts = {"claude-code:paul": {"profiles": ["claude-paul"], "billing": "subscription", "reserves": {},
        "windows": []}}  # fmt: skip
    g = setmod.account_gauges(_cards({}, accounts)["claude-code:paul"], 3600, NOW)
    assert g["unread"] and [(w["label"], w["used"]) for w in g["gauges"]] == [("week", None)]
    assert setmod.account_gauges(None, None, NOW)["unread"]  # an account the gate has not named yet
    cold = setmod.account_gauges(None, None, NOW, billing="metered")  # a metered one: the home's windows, unread
    assert cold["metered"] and [(w["label"], w["used"], w["line"]) for w in cold["gauges"]][0] == (
        "week", None, "no reading yet")
    old = {"claude-paul": {"tool": "claude-code", "fetched": (NOW - timedelta(hours=3)).isoformat(),
        "windows": [{"label": "week", "pct": 50}]}}  # fmt: skip
    assert setmod.account_gauges(_cards(old, accounts)["claude-code:paul"], 3600, NOW)["stale"]
    assert not setmod.account_gauges(_cards(old, accounts)["claude-code:paul"], None, NOW).get("stale")  # off


def test_a_metered_account_sums_each_window_against_its_amount_and_a_mixed_one_takes_none():
    resets = (NOW + timedelta(hours=10)).isoformat()
    usage = {"api": {"tool": "claude-code", "windows": [
        {"label": "day", "pct": 64, "resets": resets, "spent": {"total": 9, "cost": 3.2}}]}}  # fmt: skip
    accounts = {
        "claude-code:key": {"profiles": ["api"], "billing": "metered", "amounts": {"day": "$5"}, "windows": []},
        "claude-code:split": {"profiles": ["sa", "sb"], "billing": "mixed",
            "billings": {"sa": "subscription", "sb": "metered"}},
    }  # fmt: skip
    cards = _cards(usage, accounts)
    g = setmod.account_gauges(cards["claude-code:key"], 3600, NOW)
    assert g["metered"] and [w["label"] for w in g["gauges"]] == ["week", "day", "month"]  # the week's first
    day = next(w for w in g["gauges"] if w["label"] == "day")
    assert (day["used"], day["value"], day["keep"]) == (64.0, "$5", None) and "spent $3.20" in day["line"]
    week = next(w for w in g["gauges"] if w["label"] == "week")
    assert week["used"] is None  # no amount on it: nothing to fill against
    mixed = setmod.account_gauges(cards["claude-code:split"], 3600, NOW)
    assert mixed["mixed"] and mixed["gauges"] == []


def test_a_reserve_on_a_window_no_longer_reported_is_drawn_with_remove():
    usage = {"claude-paul": {"tool": "claude-code", "windows": [{"label": "week", "pct": 6}]}}
    accounts = {"claude-code:paul": {"profiles": ["claude-paul"], "billing": "subscription",
        "reserves": {"week (opus)": 20}, "windows": []}}  # fmt: skip
    g = setmod.account_gauges(_cards(usage, accounts)["claude-code:paul"], 3600, NOW)
    assert [(x["label"], x["value"]) for x in g["gauges"]] == [("week", "")]
    assert [(x["label"], x["value"]) for x in g["gone"]] == [("week (opus)", "20")]


def test_the_tools_page_draws_each_accounts_gauges_and_keep_back_writes_through_the_settings_card(monkeypatch):
    from fastapi.testclient import TestClient

    calls = []
    usage = {"claude-paul": {"tool": "claude-code", "windows": [{"label": "week", "pct": 6}]}}

    async def call(m, **p):
        calls.append((m, p))
        if m == "tools":
            return read()
        if m == "usage":
            return usage
        if m == "settings":
            return {"usage_accounts": {"claude-code:paul": {"profiles": ["claude-paul"], "billing": "subscription",
                "reserves": {"week": 15}, "windows": []}}}  # fmt: skip
        return {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    real = setmod.usage_cards  # the home's profiles.yml as the page reads it: the one profile on paul's account
    mine = {"claude-paul": profiles_mod.Profile(name="claude-paul", account="paul")}
    monkeypatch.setattr(setmod, "usage_cards", lambda _p, a, u, now=None: real(mine, a, u, now))
    with TestClient(app_mod.create_app()) as c:
        r = c.get("/tools")
        assert r.status_code == 200
        assert 'class="toolgauges" data-account="claude-code:paul"' in r.text
        assert "room for unattended work: 79%" in r.text and 'name="week" value="15"' in r.text
        assert 'data-account="gemini:paul-google" data-metered="1"' in r.text  # metered, with no card yet
        r = c.post("/api/settings/usage", json={"account": "claude-code:paul", "reserves": {"week": "20"}})
    assert ("set_settings", {"reserves": {"week": 20}, "account": "claude-code:paul"}) in calls
