"""TD-2068, design §4.7 *ao new*, §4.9e *The launch on a login*: after the cut-over a session the person starts takes
`--login <tool>:<name>`, else the login last used on its host, and `--model`; `--profile` is refused. Before it,
`--login` and `--model` are refused and nothing changes."""

from __future__ import annotations

import argparse

import pytest

from sessionorc import teamstore
from sessionorc.client import AgentError
from shiftlead import cli

pytestmark = pytest.mark.unit

LAST = {"claude-code": "claude-code:main", "gemini": "gemini:g"}


def _args(**kw):
    base = {"adapter": "claude-code", "profile": None, "login": None, "model": None, "host": None}
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture
def after(monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    monkeypatch.setattr(cli.hosts, "local_host", lambda: argparse.Namespace(name="kmaster", repos=lambda: {}))
    monkeypatch.setattr(cli, "call_sync", lambda method, **kw: LAST if method == "last_login" else {})


def test_a_named_login_is_the_launch_with_its_tool_and_the_roles_profile_dropped(after):
    args, defaults = _args(login="gemini:pro", model="flash"), {"profile": "role-profile"}
    assert cli._new_login(args, defaults) == {"login": "gemini:pro", "seat_model": "flash"}
    assert args.adapter == "gemini" and "profile" not in defaults


def test_no_model_lets_the_logins_pin_or_the_tools_default_stand(after):
    assert cli._new_login(_args(login="claude-code:main"), {}) == {"login": "claude-code:main"}


def test_with_no_login_named_the_last_used_for_its_tool_on_its_host_is_taken(after):
    args = _args()
    assert cli._new_login(args, {}) == {"login": "claude-code:main"} and args.adapter == "claude-code"
    args = _args(adapter="gemini")
    assert cli._new_login(args, {}) == {"login": "gemini:g"} and args.adapter == "gemini", "keyed by tool"
    assert cli._new_login(_args(host="kmaster"), {}) == {"login": "claude-code:main"}, "the home named is the home"


def test_a_nodes_last_used_is_not_read_from_the_home_yet(after):
    with pytest.raises(AgentError, match="no claude-code login was used here yet"):
        cli._new_login(_args(host="node1"), {})


def test_ao_new_hands_the_login_and_model_to_its_create(after, monkeypatch):
    sent = {}

    def call(method, **kw):
        if method == "create":
            sent.update(kw)
            return {"id": "w", "name": "w", "adapter": kw["adapter"], "dir": kw["dir"], "state": "idle"}
        return LAST if method == "last_login" else {}

    monkeypatch.setattr(cli, "call_sync", call)
    args = cli.build_parser().parse_args(["new", "w", "--login", "gemini:g", "--model", "flash", "-d", "/tmp"])
    cli.cmd_new(args)
    assert (sent.get("login"), sent.get("seat_model"), sent.get("adapter")) == ("gemini:g", "flash", "gemini")


def test_a_profile_is_refused_after_the_cut_over(after):
    with pytest.raises(AgentError, match=cli.NO_PROFILE):
        cli._new_login(_args(profile="grind"), {})


@pytest.mark.parametrize("login", ["main", "claude-code:", ":main"])
def test_a_login_not_in_tool_name_form_is_refused(after, login):
    with pytest.raises(AgentError, match="<tool>:<name>"):
        cli._new_login(_args(login=login), {})


def test_no_login_named_and_none_used_there_is_refused(after, monkeypatch):
    monkeypatch.setattr(cli, "call_sync", lambda method, **kw: {})
    with pytest.raises(AgentError, match="no grok login was used here yet"):
        cli._new_login(_args(adapter="grok"), {})


def test_before_the_cut_over_login_and_model_are_refused_and_a_profile_stands(monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: False)
    defaults = {"profile": "grind"}
    assert cli._new_login(_args(profile="grind"), defaults) == {} and defaults == {"profile": "grind"}
    for kw in ({"login": "claude-code:main"}, {"model": "opus"}):
        with pytest.raises(AgentError, match="after the switch-over"):
            cli._new_login(_args(**kw), {})


def test_a_shell_takes_no_login(after):
    assert cli._new_login(_args(adapter="shell"), {}) == {}
    for kw in ({"login": "claude-code:main"}, {"model": "opus"}):
        with pytest.raises(AgentError, match="a shell takes no login"):
            cli._new_login(_args(adapter="shell", **kw), {})


def test_ao_new_parses_login_and_model():
    got = cli.build_parser().parse_args(["new", "w", "--login", "gemini:g", "--model", "flash"])
    assert (got.login, got.model) == ("gemini:g", "flash")
