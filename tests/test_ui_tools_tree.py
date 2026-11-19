"""The Tools page's login tree on a switched host (design §4.2b *The page*, TD-1974): each account and its logins
under it, *Not signed in*, and the logins whose account is to be named; before the switch-over, none of it."""

from __future__ import annotations

import re

import pytest
from fixture_tools_tree import read

from shiftlead.ui import app as app_mod


def page(monkeypatch, got) -> str:
    from fastapi.testclient import TestClient

    async def call(method, **params):
        return got if method == "tools" else {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        r = c.get("/tools")
    assert r.status_code == 200
    return r.text


def section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end, text.index(start))]


def test_a_switched_host_draws_each_account_and_its_logins(monkeypatch):
    text = page(monkeypatch, read())
    claude = section(text, 'data-adapter="claude-code"', "</section>")
    acct = section(claude, 'data-account="claude-code:paul"', "Not signed in")
    assert ">paul<" in acct and "Ultra · subscription" in acct and "opus · sonnet · haiku" in acct
    # the label drawn, the name beside it; the folder from ~; the note in italics; the state's words
    assert re.search(r">work laptop</span><span class=\"mono note\">claude-paul<", acct)
    assert "~/.claude-paul" in acct and "<i>conformance walks record here</i>" in acct
    assert 'state-signed_in">signed in<' in acct and 'state-limited">limited<' in acct
    assert "claude-heather" not in acct and "claude-new" not in acct
    unsigned = section(claude, "Not signed in", "Signed in, account not named")
    assert "claude-heather" in unsigned and 'state-not_signed_in">not signed in<' in unsigned
    naming = claude[claude.index("Signed in, account not named") :]
    assert "claude-new" in naming and "name its account" in naming
    gemini = section(text, 'data-adapter="gemini"', "</section>")
    # a label drawn with its key's name beside it; no plan recorded; a pin, a mismatch and both warnings
    assert '>Paul&#39;s key</span> <span class="mono note">paul-google<' in gemini
    assert "plan not recorded by the tool · metered" in gemini and "<i>pinned: flash-lite</i>" in gemini
    assert 'state-sign_in_again">sign in again<' in gemini
    assert "these logins read different accounts" in gemini and "one key from the environment" in gemini
    assert "its billing is not what the tool records" in gemini
    assert "Not signed in" not in gemini and "found here, signed in" in gemini


def test_before_the_switch_over_no_account_or_login_is_drawn(monkeypatch):
    got = read()
    got["switched"] = False
    text = page(monkeypatch, got)
    assert 'data-adapter="claude-code"' in text
    assert "data-account=" not in text and "data-login=" not in text and "Not signed in" not in text


@pytest.mark.parametrize("folder,shown", [("/home/x", "~"), ("/home/x/.c", "~/.c"), ("/home/xy", "/home/xy")])
def test_a_folder_is_drawn_from_the_home(folder, shown):
    assert app_mod._shown_folder(folder, "/home/x") == shown


def test_each_login_draws_its_controls_by_its_state(monkeypatch):
    text = page(monkeypatch, read())
    rows = dict(re.findall(r'data-login="([\w:-]+)"(.*?)</details>', text, re.S))
    assert set(rows) == {"claude-code:claude-paul", "claude-code:claude-conformance", "claude-code:claude-heather",
                         "claude-code:claude-new", "gemini:gemini-paul"}  # fmt: skip
    for row in rows.values():  # ✎, and the ⋯ menu's three, on every login
        assert 'data-tool-act="label"' in row and "Open a shell here" in row and "Edit note" in row
        assert "Forget this login" in row and 'data-version="v"' in row
    assert ">Sign in<" in rows["claude-code:claude-heather"] and "Sign in again" in rows["gemini:gemini-paul"]
    assert ">Sign in<" not in rows["claude-code:claude-paul"] and "Sign in again" not in rows["claude-code:claude-paul"]
    named = [k for k, row in rows.items() if "Name its account" in row]
    assert sorted(named) == ["claude-code:claude-new", "gemini:gemini-paul"]  # to be named, and the mismatch
    # an account's ✎ carries its key and version
    assert re.search(
        r'data-account="claude-code:paul" data-version="a" data-label="">.*?data-tool-act="label"', text, re.S
    )


def test_before_the_switch_over_no_login_control_is_drawn(monkeypatch):
    got = read()
    got["switched"] = False
    text = page(monkeypatch, got)
    assert "Forget this login" not in text and "Name its account" not in text and "toolpen" not in text


@pytest.mark.parametrize(
    "path,body,method,params",
    [
        ("/api/tools/login/label", {"login": "claude-code:claude-paul", "label": "x", "version": "v"}, "login_label",
         {"login": "claude-code:claude-paul", "label": "x", "version": "v"}),
        ("/api/tools/login/label", {"login": "claude-code:claude-paul", "label": "", "version": "v"}, "login_label",
         {"login": "claude-code:claude-paul", "label": None, "version": "v"}),
        ("/api/tools/login/note", {"login": "gemini:g", "text": "a line", "version": "v"}, "login_note",
         {"login": "gemini:g", "text": "a line", "version": "v"}),
        ("/api/tools/login/account", {"login": "gemini:g", "account": "paul", "version": "v"}, "login_account",
         {"login": "gemini:g", "account": "paul", "version": "v"}),
        ("/api/tools/login/forget", {"login": "gemini:g", "version": "v"}, "login_forget",
         {"login": "gemini:g", "version": "v"}),
        ("/api/tools/login/shell", {"login": "gemini:g"}, "login_shell", {"login": "gemini:g"}),
        ("/api/tools/account/label", {"key": "gemini:paul", "label": "k", "version": "b"}, "account_label",
         {"key": "gemini:paul", "label": "k", "version": "b"}),
    ],
)  # fmt: skip
def test_each_control_calls_its_verb(monkeypatch, path, body, method, params):
    from fastapi.testclient import TestClient

    calls = []

    async def call(m, **p):
        calls.append((m, p))
        return {"ok": True}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        r = c.post(path, json=body)
    assert r.status_code == 200 and [x for x in calls if x[0] == method] == [(method, params)]


def test_a_refusal_and_an_unknown_control(monkeypatch):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    async def call(m, **p):
        raise HTTPException(400, "claude-paul changed since this page read it — reload")

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        r = c.post("/api/tools/login/forget", json={"login": "claude-paul", "version": "v"})
        assert r.status_code == 400 and "changed since this page read it" in r.json()["detail"]
        assert c.post("/api/tools/login/explode", json={}).status_code == 404


def test_a_logins_settings_form_is_filled_from_the_read(monkeypatch):
    text = page(monkeypatch, read())
    row = section(text, 'data-login="claude-code:claude-paul"', "</form>")
    assert 'data-tool-act="settings"' in row and 'data-billing="subscription"' in row
    assert "<option selected>subscription</option>" in row
    assert 'name="extra_args" value="[&#34;--verbose&#34;]"' in row and 'name="permission_wait" value="30"' in row
    # the pin's choices are its account's families
    pins = r'name="pin".*?<option value="">none</option><option>opus</option><option>sonnet</option>'
    assert re.search(pins, row, re.S)
    gem = section(text, 'data-login="gemini:gemini-paul"', "</form>")
    assert "<option selected>flash-lite</option>" in gem  # the pin set


def test_add_login_on_each_card_and_add_on_a_found_row(monkeypatch):
    text = page(monkeypatch, read())
    assert text.count("+ Add login") == 2 and 'class="tooladdform row gap wrap" data-tool="gemini"' in text
    gemini = section(text, 'data-adapter="gemini"', "</section>")
    assert re.search(r'class="btn sm tooladdfound" type="button" data-tool="gemini" data-path="[^"]+"', gemini)
    got = read()
    got["switched"] = False
    text = page(monkeypatch, got)
    assert "+ Add login" not in text and "tooladdfound" not in text  # before the switch-over, neither


@pytest.mark.parametrize(
    "changes,billing,order",
    [
        ({"prices": '{"input": 3}', "billing": "metered"}, "subscription", ["billing", "prices"]),
        ({"prices": "", "billing": "subscription"}, "metered", ["prices", "billing"]),
        ({"prices": "", "billing": ""}, "metered", ["prices", "billing"]),
        ({"pin": "opus", "extra_args": '["--x"]', "permission_wait": "30"}, None,
         ["extra_args", "permission_wait", "pin"]),
    ],
)  # fmt: skip
def test_settings_are_written_in_an_order_no_write_refuses(changes, billing, order):
    got = app_mod.settings_writes(changes, billing)
    assert [k for k, _ in got] == order
    vals = dict(got)
    assert vals.get("prices") in (None, {"input": 3}) and vals.get("permission_wait", 30) == 30
    assert vals.get("extra_args", ["--x"]) == ["--x"]


def test_a_setting_that_is_not_one_or_not_a_value_is_refused():
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="not a login's setting"):
        app_mod.settings_writes({"colour": "red"}, None)
    with pytest.raises(HTTPException, match="does not read as a value"):
        app_mod.settings_writes({"prices": "{input: [1"}, None)


def test_settings_send_the_version_once_and_stop_at_the_first_refusal(monkeypatch):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    calls = []

    async def call(m, **p):
        if m == "login_set":
            calls.append(p)
            if p["key"] == "permission_wait":
                raise HTTPException(400, "permission_wait is a number of seconds, not 'x'")
        return {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    body = {"login": "claude-code:claude-paul", "version": "v", "billing": "subscription",
            "changes": {"extra_args": '["--a"]', "permission_wait": "x", "pin": "opus"}}  # fmt: skip
    with TestClient(app_mod.create_app()) as c:
        r = c.post("/api/tools/login/settings", json=body)
        assert r.status_code == 400 and r.json()["detail"].endswith("(extra_args saved)")
        assert [(p["key"], p["version"]) for p in calls] == [("extra_args", "v"), ("permission_wait", None)]
        calls.clear()
        body["changes"] = {"pin": "opus"}
        assert c.post("/api/tools/login/settings", json=body).json() == {"saved": ["pin"]}
        assert calls == [{"login": "claude-code:claude-paul", "key": "pin", "value": "opus", "version": "v"}]


def test_add_sends_its_fields_empty_ones_as_none(monkeypatch):
    from fastapi.testclient import TestClient

    calls = []

    async def call(m, **p):
        calls.append((m, p))
        return {"change": "added"}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        c.post("/api/tools/add", json={"tool": "gemini", "name": " work ", "path": "", "account": ""})
        c.post("/api/tools/add", json={"tool": "gemini", "path": "/home/x", "name": ""})
    adds = [p for m, p in calls if m == "login_add"]
    assert adds == [
        {"tool": "gemini", "name": "work", "path": None, "account": None},
        {"tool": "gemini", "name": None, "path": "/home/x", "account": None},
    ]


def test_no_tools_control_is_one_the_page_wide_handler_sends_as_a_sessions_action(monkeypatch):
    """The page-wide click handler sends every `[data-act]` press as a session's action: a Tools control carries
    `data-tool-act`, so a press is its own verb alone (TD-1974, found by slice 8's UI check)."""
    text = page(monkeypatch, read())
    assert "data-tool-act=" in text and "data-act=" not in section(
        text, 'id="toolspage"', "</main>" if "</main>" in text else "</body>"
    )
