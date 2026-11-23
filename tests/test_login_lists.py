"""Which teams and built-in sets list a login (design §4.2b *The page*, *⋯ on a login*, TD-2064)."""

from __future__ import annotations

import pytest
from fixture_tools_tree import read
from test_ui_tools_tree import page, section

from sessionorc import builtinstore, logins

LK = "claude-code:grind"


def doc() -> dict:
    return {
        "teams": {
            "zeta": {"repo": "r", "logins": [LK], "label": "Zeta team"},
            "alpha": {"repo": "r", "logins": [LK, "claude-code:other"]},
            "old": {"logins": [LK]},  # not switched: its key is not a login list yet
            "timed": {"repo": "r", "logins": [], "schedule": {"start": "reset", "window": "5h", "login": LK}},
        },
        "builtins": {"default": {"logins": [LK]}, "night": {"label": "Night", "logins": ["claude-code:other"]}},
    }


def test_a_login_names_each_team_and_set_that_lists_it():
    got = builtinstore.login_lists(doc())
    assert got[LK]["teams"] == [{"name": "alpha", "label": None}, {"name": "zeta", "label": "Zeta team"}]
    assert got[LK]["sets"] == [{"name": "default", "label": None}]
    assert got["claude-code:other"]["sets"] == [{"name": "night", "label": "Night"}]
    assert "claude-code:none" not in got


def test_what_holds_a_login_includes_a_schedule_and_nothing_for_one_in_no_list():
    assert builtinstore.login_holders(doc(), LK) == [
        "team alpha",
        "team zeta",
        "built-in set default",
        "team timed's schedule",
    ]
    assert builtinstore.login_holders(doc(), "claude-code:none") == []


@pytest.mark.parametrize("broken", [{"teams": "x"}, {"teams": {"a": {"repo": "r", "logins": "x"}}}, {"builtins": 3}])
def test_a_hand_edited_shape_reads_as_no_list(broken):
    assert builtinstore.login_holders(broken, LK) == []


def test_the_row_links_each_list_or_says_it_is_in_none(monkeypatch):
    got = read()
    rows = got["tools"][0]["logins"]
    rows[0]["lists"] = {
        "teams": [{"name": "ao grind", "label": None}, {"name": "sam", "label": "Samscrape"}],
        "sets": [{"name": "default", "label": None}],
    }
    rows[1]["lists"] = {"teams": [], "sets": []}
    text = page(monkeypatch, got)
    first = section(text, f'data-login="claude-code:{rows[0]["name"]}"', "</form>")
    assert '<a href="/teams/ao%20grind">ao grind</a>, <a href="/teams/sam">Samscrape</a>, ' in first
    assert 'built-in set <a href="/builtins/default">default</a>' in first
    second = section(text, f'data-login="claude-code:{rows[1]["name"]}"', "</form>")
    assert "in no team&#39;s list" in second or "in no team's list" in second
    third = section(text, f'data-login="claude-code:{rows[2]["name"]}"', "</form>")
    assert "toollists" not in third  # a read with no lists (a node's) draws no line


def _home(agent, settings: str) -> None:
    from sessionorc import paths

    d = logins.empty()
    d["logins"][LK] = {"folder": "/h/.claude-grind", "account": "claude-code:paul"}
    d["accounts"]["claude-code:paul"] = {}
    logins.save(d, "fixture", paths.home())
    (paths.home() / "settings.yml").write_text(settings)


async def test_forget_is_refused_naming_the_lists_and_goes_through_once_none_does(agent):
    from conftest import park_ticks

    from sessionorc import paths
    from sessionorc.client import AgentError, LocalClient

    await park_ticks(agent)
    _home(agent, f"teams: {{t: {{repo: r, logins: ['{LK}']}}}}\nbuiltins: {{default: {{logins: ['{LK}']}}}}\n")
    async with LocalClient() as c:
        with pytest.raises(AgentError, match=f"{LK} cannot be forgotten while built-in set default, team t use it"):
            await c.call("login_forget", login="grind")
        (paths.home() / "settings.yml").write_text("teams: [broken\n")
        with pytest.raises(AgentError, match="settings.yml cannot be read"):
            await c.call("login_forget", login="grind")
        (paths.home() / "settings.yml").unlink()
        assert (await c.call("login_forget", login="grind"))["change"] == f"{LK} forgotten"


async def test_a_node_is_not_refused_for_the_homes_lists(agent):
    from conftest import park_ticks

    from sessionorc.client import LocalClient

    await park_ticks(agent)
    _home(agent, f"builtins: {{default: {{logins: ['{LK}']}}}}\n")
    agent.mode = "node"
    try:
        async with LocalClient() as c:
            assert (await c.call("login_forget", login="grind"))["change"] == f"{LK} forgotten"
    finally:
        agent.mode = "home"


async def test_the_tools_read_carries_each_logins_lists_on_the_home_only(agent):
    from conftest import park_ticks

    await park_ticks(agent)
    _home(agent, f"builtins: {{default: {{logins: ['{LK}']}}}}\n")
    kept = {"switched": True, "tools": [{"adapter": "claude-code", "accounts": [], "logins": [{"name": "grind"}]}]}
    row = (await agent._tools_gauges(kept))["tools"][0]["logins"][0]
    assert row["lists"]["sets"] == [{"name": "default", "label": None}]
    assert "lists" not in kept["tools"][0]["logins"][0]  # the kept read is never written
    agent.mode = "node"
    try:
        assert "lists" not in (await agent._tools_gauges(kept))["tools"][0]["logins"][0]
    finally:
        agent.mode = "home"
