"""td-max's one-time migration (design §4.9 *On by default, with default ceilings*, §5; TD-1545 slice 4): at the
home's first start on the build, with no `scale.migrated` stamp, `max: off` for every team it knows — a key under
`teams:` or a record carrying `team` — and the stamp in the same write; the held extras of each team it writes
`off` dropped; with the stamp present, nothing written."""

from __future__ import annotations

import pytest
import yaml
from conftest import park_ticks
from test_anchor_retired import _shell

from sessionorc import settings as settings_mod
from sessionorc.client import LocalClient


@pytest.mark.unit
def test_every_known_team_is_written_off_with_the_stamp_once():
    doc = {"teams": {"a": {"size": {"g": 2}}, "b": None}, "scale": {"live": {"kmaster": 30}}}
    assert settings_mod.migrate_scale(doc, ["c", "", "a"], "2026-11-10") == ["a", "b", "c"]
    assert doc["teams"] == {"a": {"size": {"g": 2}, "max": "off"}, "b": {"max": "off"}, "c": {"max": "off"}}
    assert doc["scale"] == {"live": {"kmaster": 30}, "migrated": "2026-11-10"}  # beside `live`, kept
    assert settings_mod.scale(doc) == {"live": {"kmaster": 30}, "migrated": "2026-11-10"}
    assert settings_mod.teams(doc)["a"]["max"] == "off"
    before = yaml.safe_dump(doc)
    # the stamp present: a team first started later is on td-max, and nothing is written
    assert settings_mod.migrate_scale(doc, ["d"], "2026-11-11") is None
    assert yaml.safe_dump(doc) == before


@pytest.mark.unit
def test_a_home_with_no_team_writes_the_stamp_alone():
    doc: dict = {}
    assert settings_mod.migrate_scale(doc, [], "2026-11-10") == []
    assert doc == {"scale": {"migrated": "2026-11-10"}}


@pytest.mark.integration
async def test_the_home_writes_it_once_and_drops_the_held_extras_of_a_team_written_off(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        settings_mod.save({"teams": {"named": {"on_work": "ask"}}})
        member = (await person.call("create", **_shell(tmp_path, "g-1", team="started")))["id"]
        extra = (
            await person.call("create", **_shell(tmp_path, "g-4", team="started", held=True, scale={"line": "g"}))
        )["id"]
        await agent.rpc_kill(id=member)
        agent._migrate_scale()
        doc = settings_mod.load()
        assert doc["teams"]["named"] == {"on_work": "ask", "max": "off"}
        assert doc["teams"]["started"] == {"max": "off"}  # known by a record carrying it
        assert doc["scale"]["migrated"]
        assert extra not in agent.sessions, "a held extra of a team written off is dropped"
        assert member in agent.sessions, "a member's record is never the migration's"
        # a second start finds the stamp: a team written later stays on td-max
        settings_mod.save({**doc, "teams": {**doc["teams"], "later": {"on_work": "ask"}}})
        agent._migrate_scale()
        assert "max" not in settings_mod.load()["teams"]["later"]


@pytest.mark.integration
async def test_a_broken_settings_file_is_left_for_the_next_start(agent):
    await park_ticks(agent)
    settings_mod.settings_file().write_text("- not a mapping\n")
    agent._migrate_scale()
    assert settings_mod.settings_file().read_text() == "- not a mapping\n"


@pytest.mark.integration
async def test_the_write_is_committed_to_the_homes_definitions_history(agent):
    import subprocess

    from sessionorc import defs, paths

    await park_ticks(agent)
    home = paths.home()
    settings_mod.settings_file().unlink(missing_ok=True)  # the fixture's start stamped it before the tree
    defs.init(home)
    settings_mod.save({"teams": {"named": {"on_work": "ask"}}})
    defs.commit("by hand", home=home, files=("settings.yml",))
    await agent._migrate_scale_committed()
    log = subprocess.run(
        ["git", "-C", str(home), "log", "--format=%s", "--", "settings.yml"], capture_output=True, text=True
    ).stdout.splitlines()
    assert log[0].startswith("settings: ") and "teams.named.max none → 'off'" in log[0], log
