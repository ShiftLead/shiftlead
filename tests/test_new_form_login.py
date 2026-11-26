"""TD-2068, the + New form after the cut-over (design §4.5a New session **the form**, §4.9e *A session the person
starts*): the Profile pick is a **Login** pick over the home's own host's logins, the login last used first, with an
optional **Model**; another host takes a typed login; Start creates on the login as `ao new --login` does, and a
profile is refused. Before the cut-over the form is as it was."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sessionorc import teamstore
from sessionorc.client import AgentError
from shiftlead.ui import app as uiapp

pytestmark = pytest.mark.unit

READ = {
    "tools": [
        {
            "adapter": "claude-code",
            "accounts": [
                {"key": "acct-paul", "label": "Paul (Max)", "models": {"families": ["opus", "sonnet", "haiku"]}},
            ],
            "logins": [
                {"name": "main", "account": "acct-paul", "pin": None},
                {"name": "pinned", "account": "acct-paul", "pin": "sonnet"},
            ],
        },
        {
            "adapter": "grok",
            "accounts": [{"key": "acct-x", "label": None, "models": {"families": ["grok-4"]}}],
            "logins": [{"name": "main", "account": "acct-x", "pin": None}, {"name": "spare", "account": None}],
        },
    ]
}
# `last_login` answers newest line first: grok's was the person's last create on a login
LAST = {"grok": "grok:main", "claude-code": "claude-code:main"}


def test_the_login_choices_put_the_newest_line_first_and_draw_each_logins_account_and_models():
    opts = uiapp.login_options(READ, LAST)
    assert [o["key"] for o in opts] == ["grok:main", "claude-code:main", "claude-code:pinned", "grok:spare"]
    by = {o["key"]: o for o in opts}
    assert by["claude-code:main"]["account"] == "Paul (Max)" and by["grok:main"]["account"] == "acct-x"
    assert by["grok:spare"]["account"] == "no account" and by["grok:spare"]["models"] == []
    assert by["claude-code:pinned"]["models"] == ["sonnet"], "a pin narrows what the login offers"
    assert [o["key"] for o in uiapp.login_options(READ, {})][0] == "claude-code:main", "none stored: the read's order"
    assert uiapp.login_options(None, None) == []


def test_a_filled_in_form_picks_the_login_asked_for_else_the_records_profile_else_the_last_used():
    opts = uiapp.login_options(READ, LAST)
    assert uiapp.login_prefill(opts, "claude-code:pinned", "") == "claude-code:pinned"
    assert uiapp.login_prefill(opts, "", "pinned") == "claude-code:pinned", "a bare name one login has"
    assert uiapp.login_prefill(opts, "", "main") == "grok:main", "a bare name two logins share: the last used"
    assert uiapp.login_prefill(opts, "", "") == "grok:main"
    assert uiapp.login_prefill([], "", "") == ""
    assert uiapp.login_prefill(opts, "", "", "claude-code") == "claude-code:main", "never another tool's login"
    assert uiapp.login_prefill(opts, "", "", "gemini") == "grok:main", "no login of its tool: the last used"


def test_a_resumes_fallback_is_its_tools_own_last_login_not_its_first():
    """TD-2291: a tool that is not the one last used falls back to `last_login`'s line for that tool, not to the
    first of its logins the read lists; that tool's first only where its line names no choice (§4.9e *A session the
    person starts*: "else the newest of its tool's")."""
    last = {"grok": "grok:main", "claude-code": "claude-code:pinned"}
    opts = uiapp.login_options(READ, last)
    assert [o["key"] for o in opts].index("claude-code:main") < [o["key"] for o in opts].index("claude-code:pinned")
    assert uiapp.login_prefill(opts, "", "gone", "claude-code", last) == "claude-code:pinned"
    assert (
        uiapp.login_prefill(opts, "", "gone", "claude-code", {"claude-code": "claude-code:gone"}) == "claude-code:main"
    )
    assert uiapp.login_prefill(opts, "", "gone", "claude-code", {"claude-code": "grok:spare"}) == "claude-code:main"
    assert uiapp.login_prefill(opts, "", "gone", "claude-code") == "claude-code:main", "none stored: its tool's first"


def test_the_forms_launch_on_a_login_is_ao_news():
    assert uiapp.form_login("grok:main", "", "", True) == {"login": "grok:main", "adapter": "grok"}
    assert uiapp.form_login(" claude-code:main ", "opus", "", True) == {
        "login": "claude-code:main",
        "adapter": "claude-code",
        "seat_model": "opus",
    }
    assert uiapp.form_login("", "", "", False) == {} and uiapp.form_login("", "", "shell", True) == {}
    for args, words in [
        (("", "", "", True), "name a login"),
        (("main", "", "", True), "a login is <tool>:<name>"),
        (("grok:main", "", "", False), "for after the switch-over"),
        (("", "opus", "shell", True), "a shell takes no login and no model"),
    ]:
        with pytest.raises(HTTPException) as e:
            uiapp.form_login(*args)
        assert e.value.status_code == 400 and words in e.value.detail


@pytest.fixture
def page(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (home / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    calls: list[tuple[str, dict]] = []
    state = {"off": True, "refuse": set()}
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: state["off"])

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def call(self, method, **params):
            calls.append((method, params))
            if method in state["refuse"]:
                raise AgentError(f"unknown method {method}")
            if method == "create":
                return {"id": "ao-r-w", "name": "w", "state": "idle"}
            if method == "tools":
                return READ
            if method == "last_login":
                return LAST
            if method in ("list", "recent_dirs"):
                return []
            if method == "host":
                return {"name": "kmaster"}
            return {}

    monkeypatch.setattr(uiapp, "LocalClient", FakeClient)
    with TestClient(uiapp.create_app()) as c:
        yield c, calls, tmp_path, state


def test_after_the_cut_over_the_form_draws_a_login_pick_and_before_it_the_profile_pick(page):
    c, _calls, _tmp, state = page
    html = c.get("/new").text
    assert "<label>Login</label>" in html and "<label>Profile</label>" not in html
    assert '<option value="grok:main" data-here="1" data-models="grok-4" selected>grok:main · acct-x</option>' in html
    assert ">claude-code:pinned · Paul (Max)</option>" in html and "shell (no agent)" in html
    assert 'name="model"' in html and "the login's pin, else the tool's default" in html
    assert 'from <span class="mono">logins.yml</span>' in html and "profiles.yml" not in html
    # a record's profile is the login's name: Resume with changes… lands on that login
    assert (
        '<option value="claude-code:pinned" data-here="1" data-models="sonnet" selected>'
        in c.get("/new", params={"profile": "pinned"}).text
    )
    # a filled-in record of one tool never lands on another tool's login
    assert (
        '<option value="claude-code:main" data-here="1" data-models="opus,sonnet,haiku" selected>'
        in c.get("/new", params={"adapter": "claude-code", "prefilled": "1"}).text
    )
    state["off"] = False
    before = c.get("/new").text
    assert "<label>Profile</label>" in before and "<label>Login</label>" not in before and 'name="model"' not in before


def test_start_creates_on_the_picked_or_typed_login_and_refuses_a_profile(page):
    c, calls, tmp_path, state = page
    form = {"name": "w", "dir": str(tmp_path)}
    r = c.post("/new", data={**form, "login": "claude-code:main", "model": "opus"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    made = [p for m, p in calls if m == "create"][-1]
    assert (made["login"], made["adapter"], made["seat_model"], made["profile"]) == (
        "claude-code:main",
        "claude-code",
        "opus",
        "",
    )
    # another host's login is typed: the select's *a login typed below* posts an empty login
    r = c.post("/new", data={**form, "login": "", "login_typed": "grok:node-main"}, follow_redirects=False)
    made = [p for m, p in calls if m == "create"][-1]
    assert r.status_code == 303 and made["login"] == "grok:node-main" and "seat_model" not in made
    r = c.post("/new", data={**form, "login": ":shell"}, follow_redirects=False)
    made = [p for m, p in calls if m == "create"][-1]
    assert r.status_code == 303 and made["adapter"] == "shell" and "login" not in made
    n = len([m for m, _ in calls if m == "create"])
    for data, words in [
        ({**form, "profile": "work"}, "profiles went at the switch-over: name a login"),
        ({**form, "login": ""}, "name a login"),
    ]:
        r = c.post("/new", data=data, follow_redirects=False)
        assert r.status_code == 400 and words in r.text
    state["off"] = False
    r = c.post("/new", data={**form, "login": "grok:main"}, follow_redirects=False)
    assert r.status_code == 400 and "for after the switch-over" in r.text
    assert len([m for m, _ in calls if m == "create"]) == n, "a refusal creates nothing"


def test_a_host_agent_that_refuses_a_read_still_draws_the_form(page):
    """TD-2292: a refused `tools` leaves the form to a typed login, with the warning; a refused `last_login` keeps the
    Login pick in the read's order, with no warning. Neither is an error page."""
    c, _calls, _tmp, state = page
    state["refuse"] = {"tools"}
    r = c.get("/new")
    assert r.status_code == 200, r.text
    assert "⚠ the host agent did not serve its logins" in r.text and 'name="login_typed"' in r.text
    assert 'id="typedfield" hidden' not in r.text, "no pick to choose from: the typed field is shown"
    state["refuse"] = {"last_login"}
    r = c.get("/new")
    assert r.status_code == 200, r.text
    assert "<label>Login</label>" in r.text and "did not serve its logins" not in r.text
    assert '<option value="claude-code:main" data-here="1" data-models="opus,sonnet,haiku" selected>' in r.text


def test_a_nodes_record_fills_the_typed_login_and_this_hosts_leaves_it_empty(page):
    """TD-2292: Resume with changes… on another host's record types its login, as its profile names it (§4.9e *A
    record's `profile`*): a bare name under the record's tool; the same record on this host fills the pick instead."""
    c, _calls, _tmp, _state = page
    params = {"profile": "grind", "adapter": "claude-code", "prefilled": "1"}
    away = c.get("/new", params={**params, "host": "node1"}).text
    assert 'id="logintyped" value="claude-code:grind"' in away
    assert (
        'id="logintyped" value="grok:x"' in c.get("/new", params={**params, "host": "node1", "profile": "grok:x"}).text
    )
    here = c.get("/new", params=params).text
    assert 'id="logintyped" value=""' in here


def test_a_start_on_a_login_under_a_role_naming_a_profile_sends_no_profile(page):
    """TD-2292: a role's `profile:` is dropped on a launch on a login (§4.9e *A session the person starts*): the
    `create` names the login alone, which the host agent would refuse beside a profile that is not its own."""
    c, calls, tmp_path, _state = page
    (tmp_path / ".shiftlead.yml").write_text("roles: {grinder: {profile: work}}\n")
    data = {"name": "w", "dir": str(tmp_path), "role": "grinder", "prompt": "go", "login": "claude-code:main"}
    r = c.post("/new", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    made = [p for m, p in calls if m == "create"][-1]
    assert (made["login"], made["profile"]) == ("claude-code:main", "")
