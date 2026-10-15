# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-687 slice 2, design §4.5a *Inbox row: CI not starting* (§4.4 *CI that never started is the
person's*): one row per spell the home keeps (`ci_spells` on `host`) — its PRs as links and its default
branches, the billing link for an org and for a user, **Re-run** to the home's `ci_rerun`, *re-run asked*
while its runs are pending, and **Snooze ▾** keyed `ci_not_run:<owner>`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat()


def spells() -> dict:
    """Two PRs in one org and a default branch, and one PR in a user's account."""
    return {
        "shiftlead": {
            "owner": "ShiftLead", "since": _iso(now() - timedelta(hours=2)), "clear": 0,
            "row": {"owner": "ShiftLead", "reason": "The job was not started because recent account payments have failed", "kind": "billing", "items": [
                {"repo": "samscrape", "root": "/r/samscrape", "runs": [11], "pr": 1097, "url": "https://github.com/ShiftLead/samscrape/pull/1097"},
                {"repo": "samscrape", "root": "/r/samscrape", "runs": [12], "pr": 1099, "url": "https://github.com/ShiftLead/samscrape/pull/1099"},
                {"repo": "samscrape", "root": "/r/samscrape", "runs": [13], "main": "abc123"},
            ]},
        },
        "eye": {
            "owner": "eye", "since": _iso(now() - timedelta(minutes=30)), "clear": 0,
            "row": {"owner": "eye", "reason": "The job was not started: something else", "kind": "other", "items": [
                {"repo": "tools", "root": "/r/tools", "runs": [21], "pr": 7, "url": "https://github.com/eye/tools/pull/7"},
            ]},
        },
    }  # fmt: skip


@pytest.fixture
def types(monkeypatch):
    """`gh api users/<owner>` stubbed: ShiftLead an org, eye a user; every read counted."""
    from shiftlead.ui import inbox

    asked: list[str] = []
    known = {"ShiftLead": "Organization", "eye": "User"}

    def read(owner: str) -> str:
        asked.append(owner)
        return known.get(owner, "")

    monkeypatch.setattr(inbox, "_gh_user_type", {})
    monkeypatch.setattr(inbox, "_gh_user_type_read", read)
    return asked


def test_one_row_per_account_its_reason_and_items():
    from shiftlead.ui.app import ci_not_run_rows

    org, user = sorted(ci_not_run_rows(spells(), now()), key=lambda r: r["owner"] != "ShiftLead")
    assert (org["row"], org["sid"], org["id"]) == ("ci_not_run", "ci_not_run:shiftlead", "ci_not_run:shiftlead")
    assert (
        org["text"]
        == "GitHub Actions does not start in ShiftLead: billing or spending limit · samscrape #1097, samscrape #1099, samscrape main"
    )
    assert org["subject"] == "CI not starting · ShiftLead"
    assert [i["url"] for i in org["parts"]] == [
        "https://github.com/ShiftLead/samscrape/pull/1097",
        "https://github.com/ShiftLead/samscrape/pull/1099",
        "",
    ]
    assert org["age"] == "2h 0m" and not org["rerun_pending"]
    # the reason GitHub's when it is not billing
    assert user["text"] == "GitHub Actions does not start in eye: The job was not started: something else · tools #7"
    # a spell clearing stands with no items
    clearing = {
        "x": {"owner": "X", "since": _iso(now()), "clear": 1, "row": {"owner": "X", "kind": "billing", "items": []}}
    }
    (row,) = ci_not_run_rows(clearing, now())
    assert row["text"] == "GitHub Actions does not start in X: billing or spending limit" and row["parts"] == []
    assert ci_not_run_rows(None) == [] and ci_not_run_rows({"bad": "x"}) == []


def test_a_rerun_pending_reads_re_run_asked_with_its_age():
    from shiftlead.ui.app import ci_not_run_rows

    s = spells()
    s["eye"]["rerun"] = {
        "at": _iso(now() - timedelta(minutes=5)),
        "runs": [{"root": "/r/tools", "run": 21, "pending": True}],
        "asked": 1,
        "refused": 0,
    }
    s["shiftlead"]["rerun"] = {
        "at": _iso(now() - timedelta(hours=1)),
        "runs": [{"root": "/r/samscrape", "run": 11, "pending": False}],
        "asked": 1,
        "refused": 0,
    }
    rows = {r["owner"]: r for r in ci_not_run_rows(s, now())}
    assert rows["eye"]["rerun_pending"] and rows["eye"]["rerun_age"] == "5m"
    assert not rows["ShiftLead"]["rerun_pending"] and rows["ShiftLead"]["rerun_age"] == ""


def test_the_billing_link_for_an_org_and_a_user_read_once(types):
    from shiftlead.ui import inbox

    assert inbox.billing_url("ShiftLead") == "https://github.com/organizations/ShiftLead/settings/billing"
    assert inbox.billing_url("eye") == "https://github.com/settings/billing"
    assert inbox.billing_url("shiftlead") == "https://github.com/organizations/shiftlead/settings/billing"
    assert types == ["ShiftLead", "eye"]  # once per account, whatever its case
    # an account that cannot be read is the person's own page, and is not asked again on every poll
    assert inbox.billing_url("Gone") == "https://github.com/settings/billing"
    assert inbox.billing_url("Gone") == "https://github.com/settings/billing"
    assert types == ["ShiftLead", "eye", "Gone"]


def test_the_row_is_counted_under_needs_you_and_snoozed_by_its_key():
    from shiftlead.ui.app import ci_not_run_rows, inbox_sections

    rows = ci_not_run_rows(spells(), now())
    s = inbox_sections([], states=rows)
    assert [e["row"] for e in s["needs"]] == ["ci_not_run", "ci_not_run"] and s["count"] == 2
    until = (now() + timedelta(days=1)).isoformat()
    s = inbox_sections([], states=rows, attention_snoozed={"ci_not_run:shiftlead|ci_not_run": until})
    assert [e["owner"] for e in s["needs"]] == ["eye"] and [e["owner"] for e in s["snoozed"]] == ["ShiftLead"]


def fake(host: dict, calls: list):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            if method == "inbox":
                return {"id": "person", "entries": [], "threads": {}, "sends": [], "unread": 0}
            if method == "ci_rerun":
                return {"owner": "ShiftLead", "asked": 3, "refused": 1, "why": "billing"}
            return {"repos": {}, "doing_log": {}, "list": [], "usage": {}, "host": {"name": "kmaster", **host}}.get(
                method, {}
            )

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def test_the_inbox_draws_the_row_with_open_rerun_and_snooze(tmp_path, monkeypatch, types):
    calls: list = []
    c = client(monkeypatch, tmp_path, fake({"ci_spells": spells()}, calls))
    html = c.get("/inbox").text
    assert "GitHub Actions does not start in ShiftLead: billing or spending limit · " in html
    assert (
        '<a href="https://github.com/ShiftLead/samscrape/pull/1097" target="_blank" rel="noopener">samscrape #1097</a>, '
        in html
    )
    assert ", samscrape main</div>" in html
    assert 'href="https://github.com/organizations/ShiftLead/settings/billing" target="_blank" rel="noopener"' in html
    assert 'data-act="ci_rerun" data-id="person" data-owner="ShiftLead"' in html
    assert 'data-sid="ci_not_run:shiftlead" data-row="ci_not_run" data-when="1w"' in html
    assert 'data-msg="ci_not_run:shiftlead"' in html  # the Telegram line's `?row=` lands on it
    assert c.get("/api/person/inbox").json()["needs"] == 2


def test_rerun_is_the_homes_ci_rerun_with_the_account(tmp_path, monkeypatch, types):
    calls: list = []
    c = client(monkeypatch, tmp_path, fake({}, calls))
    r = c.post("/api/person/ci_rerun", json={"owner": "ShiftLead"})
    assert r.status_code == 200 and r.json() == {
        "ok": True,
        "owner": "ShiftLead",
        "asked": 3,
        "refused": 1,
        "why": "billing",
    }
    assert ("ci_rerun", {"owner": "ShiftLead"}) in calls
    assert c.post("/api/person/ci_rerun", json={}).status_code == 400
