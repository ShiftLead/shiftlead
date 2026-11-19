"""An account's gauges in the `tools` read (design §4.2b *The gauge*, *The read*; TD-1975): `usage.gauges`, the one
builder, and the host agent filling each account's on every read from its gate entry and its last reading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sessionorc import spend as spend_mod
from sessionorc import usage

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def test_a_subscription_account_has_a_window_per_window_read_the_week_first_with_its_reserve_as_a_bay():
    reading = {"fetched": _iso(NOW - timedelta(minutes=5)), "windows": [
        {"label": "5h", "pct": 41, "resets": _iso(NOW + timedelta(hours=2))},
        {"label": "week", "pct": 6, "resets": _iso(NOW + timedelta(days=2))}]}  # fmt: skip
    entry = {"billing": "subscription", "reserves": {"week": 15, "5h": {"per_day": 10}},
             "windows": [{"label": "week", "line": 85}]}  # fmt: skip
    g = usage.gauges(entry, reading, 3600, NOW)
    assert [w["label"] for w in g["windows"]] == ["week", "5h"]
    week, five = g["windows"]
    assert (week["pct"], week["reserve"], week["keep"], week["room"], week["line"]) == (6.0, 15, 15, 79, 85)
    assert week["resets"] == _iso(NOW + timedelta(days=2))
    assert (five["reserve"], five["keep"], five["room"]) == ({"per_day": 10}, None, 59)  # a per-day draws no bay
    assert not g["unread"] and not g["stale"] and g["gone"] == [] and g["read_at"]


def test_no_reading_draws_a_window_per_reserve_or_the_week_and_an_old_reading_is_stale():
    g = usage.gauges({"billing": "subscription", "reserves": {"5h": 20}}, None, 3600, NOW)
    assert g["unread"] and [(w["label"], w["pct"], w["reserve"]) for w in g["windows"]] == [("5h", None, 20)]
    g = usage.gauges(None, None, 3600, NOW)  # an account no gate entry names yet
    assert g["unread"] and [(w["label"], w["pct"]) for w in g["windows"]] == [("week", None)]
    old = {"fetched": _iso(NOW - timedelta(hours=3)), "windows": [{"label": "week", "pct": 50}]}
    assert usage.gauges(None, old, 3600, NOW)["stale"]
    assert not usage.gauges(None, old, None, NOW)["stale"]  # `usage.max_age: off`


def test_a_metered_account_sums_each_window_against_its_amount_and_a_mixed_one_has_none():
    reading = {"windows": [{"label": "day", "pct": 64, "resets": _iso(NOW + timedelta(hours=10)),
                            "spent": {"total": 9, "cost": 3.2}}]}  # fmt: skip
    entry = {"billing": "metered", "amounts": {"day": "$5"}}
    g = usage.gauges(entry, reading, 3600, NOW, metered_labels=spend_mod.LABELS)
    assert [w["label"] for w in g["windows"]] == ["week", "day", "month"]
    day = g["windows"][1]
    assert (day["pct"], day["reserve"], day["keep"], day["room"], day["spent"]["cost"]) == (64.0, "$5", None, None, 3.2)
    assert g["windows"][0]["pct"] is None  # no amount on the week: nothing to fill against
    cold = usage.gauges(None, None, 3600, NOW, billing="metered", metered_labels=spend_mod.LABELS)
    assert cold["billing"] == "metered" and len(cold["windows"]) == 3
    mixed = usage.gauges({"billing": "mixed"}, reading, 3600, NOW)
    assert mixed["billing"] == "mixed" and mixed["windows"] == [] and mixed["gone"] == []


def test_a_reserve_on_a_label_the_reading_no_longer_reports_is_gone():
    reading = {"windows": [{"label": "week", "pct": 6}]}
    g = usage.gauges({"billing": "subscription", "reserves": {"week (opus)": 20}}, reading, 3600, NOW)
    assert [(w["label"], w["reserve"]) for w in g["windows"]] == [("week", None)]
    assert g["gone"] == [{"label": "week (opus)", "reserve": 20}]


async def test_the_tools_read_fills_each_accounts_gauges_afresh_and_never_writes_the_kept_read(agent):
    from conftest import park_ticks

    from sessionorc import settings as settings_mod

    await park_ticks(agent)
    settings_mod.save({"usage_gate": {"claude-code:paul": {"week": 15}}})
    agent._usage_acct["claude-code:paul"] = {
        "fetched": _iso(datetime.now(UTC)), "windows": [{"label": "week", "pct": 6}]}  # fmt: skip
    kept = {"switched": True, "tools": [{"adapter": "claude-code", "logins": [], "accounts": [
        {"key": "claude-code:paul", "billing": "subscription", "gauges": None},
        {"key": "gemini:key", "billing": "metered", "gauges": None}]}]}  # fmt: skip
    agent._tools_kept = kept
    got = await agent.rpc_tools()
    paul, key = got["tools"][0]["accounts"]
    assert [(w["label"], w["pct"], w["reserve"], w["room"]) for w in paul["gauges"]["windows"]] == [
        ("week", 6.0, 15, 79)]  # fmt: skip
    assert key["gauges"]["billing"] == "metered" and [w["label"] for w in key["gauges"]["windows"]] == [
        "week", "day", "month"]  # fmt: skip
    assert kept["tools"][0]["accounts"][0]["gauges"] is None  # filled on a copy
    agent._usage_acct["claude-code:paul"]["windows"] = [{"label": "week", "pct": 30}]
    assert (await agent.rpc_tools())["tools"][0]["accounts"][0]["gauges"]["windows"][0]["pct"] == 30.0  # afresh
    agent._tools_kept = {"switched": False, "tools": [{"accounts": []}]}
    assert await agent.rpc_tools() == agent._tools_kept  # not switched: nothing to fill


async def test_a_login_signed_in_whose_account_is_at_a_cap_is_limited_till_its_reset_and_a_metered_one_never(agent):
    from conftest import park_ticks

    await park_ticks(agent)
    reset = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)
    agent._usage_acct["claude-code:paul"] = {"fetched": _iso(datetime.now(UTC)), "windows": [
        {"label": "week", "pct": 30}, {"label": "5h", "pct": 100, "resets": _iso(reset)}]}  # fmt: skip
    agent._usage_acct["claude-code:k"] = {"fetched": _iso(datetime.now(UTC)), "windows": [{"label": "5h", "pct": 100}]}

    def login(name, account, state="signed_in", billing=None):
        return {"name": name, "account": account, "state": state, "till": None, "settings": {"billing": billing}}

    agent._tools_kept = {"switched": True, "tools": [{"adapter": "claude-code", "accounts": [
        {"key": "claude-code:paul", "billing": "subscription", "gauges": None},
        {"key": "claude-code:k", "billing": "mixed", "gauges": None}], "logins": [
        login("work", "claude-code:paul"), login("again", "claude-code:paul", "sign_in_again"),
        login("unknown", "claude-code:k"), login("key", "claude-code:k", billing="metered")]}]}  # fmt: skip
    got = {lg["name"]: (lg["state"], lg["till"]) for lg in (await agent.rpc_tools())["tools"][0]["logins"]}
    assert got == {"work": ("limited", _iso(reset)), "again": ("sign_in_again", None),
                   "unknown": ("limited", None), "key": ("signed_in", None)}  # fmt: skip
    assert agent._tools_kept["tools"][0]["logins"][0]["state"] == "signed_in"  # on a copy
    agent._usage_acct["claude-code:paul"]["windows"][1]["pct"] = 40  # the cap lifts at the next read
    assert (await agent.rpc_tools())["tools"][0]["logins"][0]["state"] == "signed_in"
