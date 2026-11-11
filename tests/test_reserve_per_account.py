"""One usage reserve per account (design §6 *Usage gate*: *A reserve is the account's*, *The migration*;
TD-1581, TD-1609 slice 2): `usage_gate:` is keyed by the account's usage key, every reader reads by
account, and the home's tick moves a key holding no `:` — a profile's — to its account."""

from __future__ import annotations

import subprocess
import time

import pytest
import yaml
from conftest import park_ticks

from sessionorc import defs, paths
from sessionorc import settings as settings_mod
from sessionorc.client import LocalClient

SUB = {"claude-code:paul": {"subscription"}}


def _move(gate: dict, accounts: dict, billing: dict | None = None) -> tuple[dict, list[str] | None]:
    doc = {"usage_gate": gate}
    said = settings_mod.migrate_reserves(doc, accounts, billing if billing is not None else SUB)
    return doc["usage_gate"], said


@pytest.mark.unit
def test_kmasters_four_profiles_on_one_account_keep_the_lowest_line():
    gate = {"grind": {"week": 1}, "grind-fable": {"week": 3}, "grind-ask": {"week": 5}, "grind-sonnet": {"week": 5}}
    got, said = _move(gate, dict.fromkeys(gate, "claude-code:paul"))
    assert got == {"claude-code:paul": {"week": 5}}  # the profile keys gone
    assert said == [
        "claude-code:paul takes week 5 (from grind-ask; grind had 1, grind-fable had 3, grind-sonnet had 5)"
    ]


@pytest.mark.unit
def test_a_flat_reserve_kept_over_a_per_day_one_names_the_profile_whose_line_may_rise():
    got, said = _move(
        {"a": {"week": 30}, "b": {"week": {"per_day": 5}}}, {"a": "claude-code:paul", "b": "claude-code:paul"}
    )
    assert got == {"claude-code:paul": {"week": 30}}  # line 70 against 95 on the last day
    assert said[0] == "claude-code:paul takes week 30 (from a; b had 5/day)"
    assert said[1].startswith("the week line of b may rise")
    # a flat 5 and a per-day 5: the same line on the last day, and the per-day one is kept
    got, said = _move(
        {"a": {"week": 5}, "b": {"week": {"per_day": 5}}}, {"a": "claude-code:paul", "b": "claude-code:paul"}
    )
    assert got == {"claude-code:paul": {"week": {"per_day": 5}}} and len(said) == 1


@pytest.mark.unit
def test_an_entry_already_under_the_account_counts_and_a_label_of_its_own_stays():
    gate = {"claude-code:paul": {"week": 10, "5h": 20}, "grind": {"week": 4}}
    got, said = _move(gate, {"grind": "claude-code:paul"})
    assert got == {"claude-code:paul": {"week": 10, "5h": 20}}
    assert said == ["claude-code:paul takes week 10 (from its own entry; grind had 4)"]


@pytest.mark.unit
def test_a_metered_account_keeps_the_smallest_amount_and_names_a_percent():
    metered = {"claude-code:key": {"metered"}}
    got, said = _move(
        {"api": {"day": "$10"}, "api2": {"day": " $5 ", "week": 30}},
        dict.fromkeys(("api", "api2"), "claude-code:key"),
        metered,
    )
    assert got == {"claude-code:key": {"day": "$5"}}
    assert "api2's week 30 does not fit its billing, so it is removed" in said
    assert "claude-code:key takes day $5 (from api2; api had $10)" in said


@pytest.mark.unit
def test_nothing_without_a_profile_key_and_the_default_profiles_key_moves():
    gate = {"claude-code:paul": {"week": 5}, "claude-code:nodeacct": {"week": 9}}
    assert _move(dict(gate), {})[1] is None
    assert settings_mod.reserves({"usage_gate": gate})["claude-code:nodeacct"] == {"week": 9}  # read as an account's
    got, said = _move({"": {"5h": 30}}, {"": "claude-code:paul"})
    assert got == {"claude-code:paul": {"5h": 30}} and said == [
        "claude-code:paul takes 5h 30 (from the default profile)"
    ]


@pytest.mark.unit
def test_a_profile_no_adapter_resolves_is_removed_and_named():
    got, said = _move({"lap": {"day": "$5"}, "grind": {"week": 5}}, {"lap": None, "grind": "claude-code:paul"})
    assert got == {"claude-code:paul": {"week": 5}}
    assert "lap had day $5: no adapter here resolves it, so it is removed" in said


@pytest.mark.unit
def test_an_account_whose_profiles_disagree_on_billing_keeps_no_moved_value():
    gate = {"claude-code:paul": {"week": 5}, "api": {"day": "$5"}, "grind": {"week": 3}}
    got, said = _move(
        gate,
        {"api": "claude-code:paul", "grind": "claude-code:paul"},
        {"claude-code:paul": {"metered", "subscription"}},
    )
    assert got == {"claude-code:paul": {"week": 5}}  # its own entry stays as it is
    assert said == [
        "claude-code:paul's profiles disagree on billing, so no reserve moved to it: api had day $5; grind had week 3; "
        "its own entry (week 5) stays as it is"
    ]


@pytest.mark.integration
async def test_two_profiles_on_one_account_read_one_line_and_a_set_moves_both(agent, hookstub, tmp_path):
    await park_ticks(agent)
    hookstub.accounts = {"pa": "paul", "pb": "paul"}
    async with LocalClient() as person:
        await person.call("create", name="a", dir=str(tmp_path), adapter="hookstub", profile="pa")
        got = await person.call("set_settings", profile="pa", reserves={"5h": 30})
        assert (got["account"], got["reserves"]) == ("hookstub:paul", {"5h": 30})
        assert settings_mod.load()["usage_gate"] == {"hookstub:paul": {"5h": 30}}
        whole = settings_mod.load()
        assert agent._gate_reserves(whole, "pa") == agent._gate_reserves(whole, "pb") == {"5h": 30}
        await person.call("set_settings", profile="pb", reserves={"5h": 10})
        whole = settings_mod.load()
        assert agent._gate_reserves(whole, "pa") == {"5h": 10}, "a change on one profile moves the account's line"
        # the gate's reply keeps its shape until TD-1610: each profile with its account's reserves
        gate = (await person.call("gate"))["profiles"]
    assert gate["pa"]["reserves"] == gate["pb"]["reserves"] == {"5h": 10} and gate["pb"]["account"] == "hookstub:paul"


def _git_log(home) -> list[str]:
    cp = subprocess.run(
        ["git", "-C", str(home), "log", "--format=%s", "--", "settings.yml"], capture_output=True, text=True
    )
    return cp.stdout.splitlines()


@pytest.mark.integration
async def test_the_home_commits_the_file_as_it_stood_then_moves_pushes_commits_and_notes(agent, hookstub, monkeypatch):
    await park_ticks(agent)
    hookstub.accounts = {"grind": "paul", "grind-ask": "paul"}
    home = paths.home()
    defs.init(home)
    settings_mod.save({**settings_mod.load(), "usage_gate": {"grind": {"week": 1}, "grind-ask": {"week": 5}}})
    notes: list[str] = []
    pushed: list[int] = []
    monkeypatch.setattr(agent, "_system_note", lambda to, text, **kw: notes.append(text))

    async def push(host=None):
        pushed.append(1)

    monkeypatch.setattr(agent, "_push_settings", push)
    await agent._migrate_reserves()
    assert settings_mod.load()["usage_gate"] == {"hookstub:paul": {"week": 5}}
    log = _git_log(home)
    assert log[1] == "settings.yml before TD-1581's migration" and log[0].startswith("settings: usage_gate.")
    before = subprocess.run(["git", "-C", str(home), "rev-parse", "HEAD~1"], capture_output=True, text=True).stdout
    assert pushed == [1] and len(notes) == 1
    assert notes[0].startswith(
        "Usage reserves are now per account: hookstub:paul takes week 5 (from grind-ask; grind had 1)"
    )
    assert f"restore from the home's commit {before.strip()[:12]}" in notes[0]
    # a tick with no profile key moves nothing, commits nothing and sends no note
    await agent._migrate_reserves()
    assert len(_git_log(home)) == len(log) and len(notes) == 1 and pushed == [1]
    # a profile key written by hand after it is moved on the next tick
    settings_mod.save({**settings_mod.load(), "usage_gate": {"hookstub:paul": {"week": 5}, "grind": {"week": 7}}})
    await agent._migrate_reserves()
    assert settings_mod.load()["usage_gate"] == {"hookstub:paul": {"week": 7}} and len(notes) == 2


@pytest.mark.integration
async def test_a_failed_pre_commit_moves_nothing_until_the_file_is_clean(agent, hookstub, monkeypatch, caplog):
    await park_ticks(agent)
    hookstub.accounts = {"grind": "paul"}
    home = paths.home()
    defs.init(home)
    settings_mod.save({**settings_mod.load(), "usage_gate": {"grind": {"week": 1}}})
    notes: list[str] = []
    monkeypatch.setattr(agent, "_system_note", lambda to, text, **kw: notes.append(text))
    lock = home / ".git" / "index.lock"
    lock.write_text("")  # another git holds the index: the pre-commit fails
    await agent._migrate_reserves()
    await agent._migrate_reserves()
    assert settings_mod.load()["usage_gate"] == {"grind": {"week": 1}}, "nothing moved while dirty"
    assert sum("not clean against HEAD" in r.message for r in caplog.records) == 1, "logged once"
    assert notes == []
    since, logged, told = agent._reserves_unclean
    agent._reserves_unclean = (since - 86401, logged, told)  # a day of such ticks
    await agent._migrate_reserves()
    await agent._migrate_reserves()
    assert len(notes) == 1 and "for a day the home could not commit settings.yml" in notes[0]
    lock.unlink()
    await agent._migrate_reserves()
    assert settings_mod.load()["usage_gate"] == {"hookstub:paul": {"week": 1}}
    assert agent._reserves_unclean is None, "a clean tick resets the day"


@pytest.mark.integration
async def test_a_home_that_is_no_tree_keeps_a_copy_never_overwritten(agent, hookstub, monkeypatch):
    await park_ticks(agent)
    hookstub.accounts = {"grind": "paul"}
    notes: list[str] = []
    monkeypatch.setattr(agent, "_system_note", lambda to, text, **kw: notes.append(text))
    settings_mod.save({**settings_mod.load(), "usage_gate": {"grind": {"week": 1}}})
    copy = paths.home() / "settings.yml.before-TD-1581"
    await agent._migrate_reserves()
    assert yaml.safe_load(copy.read_text())["usage_gate"] == {"grind": {"week": 1}}
    assert f"restore from {copy}" in notes[0]
    settings_mod.save({**settings_mod.load(), "usage_gate": {"grind": {"week": 2}}})
    await agent._migrate_reserves()
    assert yaml.safe_load(copy.read_text())["usage_gate"] == {"grind": {"week": 1}}, "never overwritten"
    assert "restore from this note's values" in notes[1]


@pytest.mark.integration
async def test_a_missing_or_unparseable_file_is_never_written(agent, hookstub):
    await park_ticks(agent)
    f = settings_mod.settings_file()
    f.unlink(missing_ok=True)
    await agent._migrate_reserves()
    assert not f.exists()
    f.write_text("usage_gate: {grind: [unclosed\n")
    await agent._migrate_reserves()
    assert f.read_text() == "usage_gate: {grind: [unclosed\n"


@pytest.mark.integration
async def test_the_tick_moves_a_profile_key_before_its_first_reserve_read(agent, monkeypatch):
    await park_ticks(agent)
    order: list[str] = []
    real = agent._gate_reserves

    async def migrate():
        order.append("migrate")

    def reads(whole, profile):
        order.append("read")
        return real(whole, profile)

    monkeypatch.setattr(agent, "_migrate_reserves", migrate)
    monkeypatch.setattr(agent, "_gate_reserves", reads)
    await agent.tick()
    assert order[:1] == ["migrate"]


@pytest.mark.unit
def test_the_unclean_day_is_counted_from_the_first_failed_tick():
    """`_reserves_not_clean`'s clock: the day runs from the first failed tick, not the latest."""

    class A:
        _reserves_unclean = None
        notes: list[str] = []

        def _system_note(self, to, text):
            self.notes.append(text)

    from sessionorc.agent_settings import SettingsMixin

    a = A()
    SettingsMixin._reserves_not_clean(a)
    first = a._reserves_unclean[0]
    assert abs(first - time.monotonic()) < 5
    SettingsMixin._reserves_not_clean(a)
    assert a._reserves_unclean[0] == first and a.notes == []
