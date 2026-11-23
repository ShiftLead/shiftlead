"""After the switch-over's marker the first shape's verbs and controls are refused (design §4.9e *What decides which
shape runs*, TD-2076), and before it they are not."""

from __future__ import annotations

import argparse
import contextlib
import json

import pytest
import yaml
from fastapi.testclient import TestClient
from test_ui_new_host import NODE_FILES, form  # noqa: F401 — a fixture
from test_ui_repo_page import client as repo_client
from test_ui_repo_page import fake as repo_fake
from test_ui_repo_page import reading, rec

from sessionorc import paths, teamstore
from sessionorc.client import AgentError, LocalClient
from shiftlead import cli, teams
from shiftlead.ui import app as uiapp
from shiftlead.ui import common

VERBS = [
    ["team", "flow", "t"],
    ["team", "size", "t", "w", "2"],
    ["team", "max", "t", "w", "2"],
    ["team", "add", "t", "w"],
    ["team", "on-work", "t", "off"],
]


@pytest.fixture
def marked(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.delenv("SHIFTLEAD_SESSION", raising=False)
    (home / "settings.yml").write_text(yaml.safe_dump({"cut_over": "2026-12-01"}))
    return home


@pytest.mark.parametrize("argv", VERBS, ids=lambda a: a[1])
def test_a_first_shape_verb_is_refused_after_the_marker(marked, argv, capsys):
    assert cli.main(argv) == 1
    assert teamstore.GONE in capsys.readouterr().err


@pytest.mark.parametrize("argv", VERBS, ids=lambda a: a[1])
def test_before_the_marker_the_verb_is_not_refused_for_it(tmp_path, monkeypatch, argv, capsys):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.delenv("SHIFTLEAD_SESSION", raising=False)
    with contextlib.suppress(Exception, SystemExit):  # no team `t` here: any other refusal is the verb's own
        cli.main(argv)
    captured = capsys.readouterr()
    assert teamstore.GONE not in captured.err + captured.out


def test_pr_held_answers_that_none_is_held(marked, capsys):
    assert cli.main(["pr", "held", "12", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["held"] is False and got["text"] == teamstore.NO_PR_HELD


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", "/api/teams/t/flow/apply"),
        ("get", "/api/teams/t/members"),
        ("post", "/api/teams/t/members"),
    ],
)
def test_a_first_shape_control_is_refused_after_the_marker(marked, method, url):
    with TestClient(uiapp.create_app()) as c:
        got = c.post(url, json={}) if method == "post" else c.get(url)
    assert got.status_code == 409 and teamstore.GONE in got.json()["detail"]


@pytest.mark.parametrize("key", teamstore.FIRST_SHAPE_KEYS)
async def test_settings_refuse_a_first_shape_key_after_the_marker(agent, key):
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(yaml.safe_dump({"cut_over": "2026-12-01"}))
    value = {"on_work": "off", "flow": "build", "size": {"w": 2}, "max": {"w": 2}}[key]
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="switch-over"):
            await person.call("set_settings", teams={"t": {key: value}})


async def test_settings_still_take_a_stop_time_after_the_marker(agent):
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(yaml.safe_dump({"cut_over": "2026-12-01"}))
    async with LocalClient() as person:
        await person.call("set_settings", teams={"t": {"reserve": 5}})


def test_the_team_start_stays_after_the_marker(marked):
    """Design 4.7 and 4.9d keep `ao team start` and the page's Start: they set the started mark."""
    with TestClient(uiapp.create_app()) as c:
        got = c.post("/api/teams/t/start", json={})
    assert teamstore.GONE not in got.text


def test_a_new_session_gets_no_reader_after_the_marker(marked):
    args = argparse.Namespace(team="t", adapter="claude-code", dir=str(marked), repo=None, role=None)
    defaults = {"review": {"reader": "techlead", "held": ["**"], "bound": "2h"}}
    assert cli._team_defaults(args, defaults) == ""
    assert defaults["review"] is None


def test_the_new_session_form_names_no_reader_after_the_marker(marked):
    assert common.team_reader("t", str(marked)) == {"review": None, "line": teamstore.NO_PR_HELD}


@pytest.mark.parametrize("is_off", [True, False], ids=["after", "before"])
def test_the_repo_page_compares_the_ledger_with_the_right_teams(tmp_path, monkeypatch, is_off):
    root = str(tmp_path / "samscrape")
    records = [rec("lead", root, team="new", builtin="techlead")]
    c = repo_client(monkeypatch, tmp_path, repo_fake({root: reading(root)}, records))
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: is_off)
    monkeypatch.setattr(teams, "entry_teams", lambda *a, **k: [{"team": "old"}])
    seen = []
    real = uiapp.team_notes
    monkeypatch.setattr(uiapp, "team_notes", lambda r, defs, fleet: (seen.append(list(defs)), real(r, defs, fleet))[1])
    assert c.get("/repo/samscrape").status_code == 200
    assert seen == [["new"] if is_off else ["old"]]


@pytest.mark.parametrize("is_off", [True, False], ids=["after", "before"])
def test_the_form_drops_a_role_s_own_reader_after_the_marker(form, monkeypatch, is_off):  # noqa: F811
    c, calls = form
    role = "roles:\n  hunter:\n    review: {reader: techlead, held: ['src/**'], bound: 2h}\n"
    monkeypatch.setitem(NODE_FILES, ".shiftlead.yml", role)
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: is_off)
    data = {"name": "a1", "dir": "/srv/node/alpha", "role": "hunter", "host": "node1"}
    r = c.post("/new", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    made = next(p for m, p in calls if m == "create")
    assert (made.get("review") is None) is is_off
