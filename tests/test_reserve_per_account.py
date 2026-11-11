"""One usage reserve per account (design §6 *Usage gate*: *A reserve is the account's*, *The migration*;
TD-1581, TD-1609 slices 2 and 3): `usage_gate:` is keyed by the account's usage key, every reader reads by
account, and the home's tick moves a key holding no `:` — a profile's — to its account."""

from __future__ import annotations

import subprocess
import time

import pytest
import yaml
from conftest import park_ticks

from sessionorc import defs, paths
from sessionorc import settings as settings_mod
from sessionorc.client import AgentError, LocalClient
from shiftlead import doctor

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
def test_a_metered_account_keeps_money_before_tokens_whatever_the_number():
    """§6 *The migration* (TD-1630): no reading converts tokens to money, so a dollar amount is kept over a token
    one even where the token count is the smaller number."""
    metered = {"claude-code:key": {"metered"}}
    got, said = _move(
        {"api": {"day": "$9"}, "api2": {"day": "3 tok"}}, dict.fromkeys(("api", "api2"), "claude-code:key"), metered
    )
    assert got == {"claude-code:key": {"day": "$9"}}
    assert said == ["claude-code:key takes day $9 (from api; api2 had 3 tok)"]


@pytest.mark.unit
def test_a_tie_between_the_accounts_own_entry_and_a_profiles_stays_the_accounts():
    """A profile's reserve equal to the account's own entry's (TD-1630): the account's own is kept, and named."""
    got, said = _move({"claude-code:paul": {"week": 5}, "grind": {"week": 5}}, {"grind": "claude-code:paul"})
    assert got == {"claude-code:paul": {"week": 5}}
    assert said == ["claude-code:paul takes week 5 (from its own entry; grind had 5)"]


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
        # the gate's reply is by account (TD-1610): both profiles are on the one entry
        gate = (await person.call("gate"))["accounts"]
    assert gate["hookstub:paul"]["reserves"] == {"5h": 10} and {"pa", "pb"} <= set(gate["hookstub:paul"]["profiles"])


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


@pytest.mark.unit
def test_a_key_written_since_the_resolution_waits_and_an_empty_one_is_named():
    got, said = _move(
        {"grind": {"week": 5}, "new": {"week": 9}, "bare": {}},
        {"grind": "claude-code:paul", "bare": "claude-code:paul"},
    )
    assert got == {"claude-code:paul": {"week": 5}, "new": {"week": 9}}, "a key not resolved is the next tick's"
    assert said == ["bare had no reserve: its key is removed", "claude-code:paul takes week 5 (from grind)"]
    assert _move({"new": {"week": 9}}, {})[1] is None


@pytest.mark.integration
async def test_a_set_by_account_moves_every_profile_on_it_and_names_them(agent, hookstub):
    await park_ticks(agent)
    hookstub.accounts = {"pa": "paul", "pb": "paul", "pc": "other"}
    async with LocalClient() as person:
        got = await person.call("set_settings", account="hookstub:paul", reserves={"5h": 30})
        assert (got["account"], got["profiles"], got["unchecked"]) == ("hookstub:paul", ["pa", "pb"], True)
        whole = settings_mod.load()
        assert agent._gate_reserves(whole, "pa") == agent._gate_reserves(whole, "pb") == {"5h": 30}
        assert agent._gate_reserves(whole, "pc") is None
        got = await person.call("set_settings", profile="pb", reserves={"5h": 10})
        assert (got["account"], got["profiles"]) == ("hookstub:paul", ["pa", "pb"])
        with pytest.raises(AgentError, match="a profile or an account"):
            await person.call("set_settings", profile="pa", account="hookstub:paul", reserves={"5h": 1})
        with pytest.raises(AgentError, match="is not a usage key"):
            await person.call("set_settings", account="paul", reserves={"5h": 1})
    assert settings_mod.load()["usage_gate"] == {"hookstub:paul": {"5h": 10}}


@pytest.mark.integration
async def test_an_account_this_home_has_not_seen_is_refused_and_a_nodes_is_checked(agent, hookstub):
    await park_ticks(agent)
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="hookstub:nodeacct is one this home has not seen"):
            await person.call("set_settings", account="hookstub:nodeacct", reserves={"5h": 30})
        # a node has reported under it: its reading's labels check the set
        agent._usage_acct["hookstub:nodeacct"] = {"windows": [{"label": "5h", "pct": 10}]}
        with pytest.raises(AgentError, match="reports no window week"):
            await person.call("set_settings", account="hookstub:nodeacct", reserves={"week": 30})
        got = await person.call("set_settings", account="hookstub:nodeacct", reserves={"5h": 30})
    assert (got["profiles"], got["unchecked"]) == ([], False)
    assert settings_mod.reserves(settings_mod.load()) == {"hookstub:nodeacct": {"5h": 30}}


@pytest.mark.integration
async def test_an_account_whose_profiles_disagree_on_billing_takes_no_reserve(agent, hookstub):
    await park_ticks(agent)
    hookstub.accounts = {"pa": "paul", "api": "paul"}
    hookstub.billing = {"api": {"billing": "metered", "prices": {"m": 1.0}}}
    async with LocalClient() as person:
        for where in ({"profile": "pa"}, {"profile": "api"}, {"account": "hookstub:paul"}):
            with pytest.raises(AgentError, match=r"profiles disagree on billing \(api metered, pa subscription\)"):
                await person.call("set_settings", reserves={"5h": 30}, **where)
    assert not settings_mod.load().get("usage_gate")


@pytest.mark.integration
async def test_a_metered_account_takes_an_amount_and_refuses_a_percent(agent, hookstub):
    await park_ticks(agent)
    hookstub.accounts = {"api": "key", "api2": "key"}
    hookstub.billing = {p: {"billing": "metered", "prices": {"m": 1.0}} for p in ("api", "api2")}
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="account hookstub:key is metered, so its reserve is an amount"):
            await person.call("set_settings", account="hookstub:key", reserves={"day": 30})
        got = await person.call("set_settings", account="hookstub:key", reserves={"day": "$5"})
    assert (got["metered"], got["profiles"], got["reserves"]) == (True, ["api", "api2"], {"day": "$5"})
    assert settings_mod.amounts(settings_mod.load())["hookstub:key"]["day"]["unit"] == "$"


@pytest.mark.integration
async def test_an_account_part_holding_a_colon_is_refused_and_a_dotted_one_works(agent, hookstub):
    await park_ticks(agent)
    hookstub.accounts = {"pa": "a:b", "pe": "paul@example.com"}
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="profile pa: the account part of hookstub:a:b holds a ':'"):
            await person.call("set_settings", profile="pa", reserves={"5h": 30})
        with pytest.raises(AgentError, match="holds a ':'"):
            await person.call("set_settings", account="hookstub:a:b", reserves={"5h": 30})
        got = await person.call("set_settings", profile="pe", reserves={"5h": 30})
    assert got["account"] == "hookstub:paul@example.com"
    assert settings_mod.load()["usage_gate"] == {"hookstub:paul@example.com": {"5h": 30}}


@pytest.mark.unit
def test_doctors_profiles_check_names_a_colon_account_and_a_split_billing():
    rows = [
        {"adapter": "claude-code", "profile": "grind", "account": "paul", "credentials": True},
        {"adapter": "claude-code", "profile": "api", "account": "paul", "metered": True, "key": True},
        {"adapter": "claude-code", "profile": "odd", "account": "a:b", "credentials": True},
        {"adapter": "claude-code", "profile": "mail", "account": "paul@example.com", "credentials": True},
        {"adapter": "gemini", "profile": "g", "account": "paul", "metered": True, "key": True},
    ]
    named = [r["text"] for r in doctor.profiles(rows) if r["verdict"] == doctor.WARNING]
    assert named == [
        "profile odd — its account a:b holds a ':', so its usage key does not split and its reserve is refused: "
        "rename it in profiles.yml (a '.' is allowed)",
        "account claude-code:paul — its profiles disagree on billing (api metered, grind subscription): an account "
        "has one billing, so its reserve is refused until profiles.yml agrees",
    ]


@pytest.mark.integration
async def test_the_gate_reply_lists_each_account_its_profiles_an_orphan_and_a_nodes(agent, hookstub):
    """The `gate` reply's `accounts` (§6 *The readers*, TD-1610): an account per `usage_gate:` key, per account
    the adapters' profiles name, and per account a node reported under; an orphan key carries `profiles: []`, an
    account with no reading `windows: []`, and one whose profiles disagree on billing says `mixed`."""
    await park_ticks(agent)
    hookstub.accounts = {"pa": "paul", "pb": "paul", "api": "split", "pc": "split"}
    hookstub.billing = {"api": {"billing": "metered", "prices": {"m": 1.0}}}
    async with LocalClient() as person:
        await person.call("set_settings", account="hookstub:paul", reserves={"5h": 30})
        whole = settings_mod.load()
        whole["usage_gate"]["hookstub:gone"] = {"week": 5}
        whole["usage_gate"]["hookstub:spent"] = {"day": "$5"}
        settings_mod.save(whole)
        agent._usage_acct["hookstub:nodeacct"] = {"windows": [{"label": "5h", "pct": 10}]}
        agent._usage_remote_keys[("node1", "np")] = "hookstub:nodeacct"
        got = (await person.call("gate"))["accounts"]
    paul = got["hookstub:paul"]
    assert (paul["profiles"], paul["billing"], paul["reserves"]) == (["pa", "pb"], "subscription", {"5h": 30})
    assert paul["windows"] == [], "no reading: no rows, the card still takes a reserve"
    gone = got["hookstub:gone"]
    assert (gone["profiles"], gone["reserves"]) == ([], {"week": 5}), "an orphan key is listed so it can be cleared"
    spent = got["hookstub:spent"]
    assert spent["billing"] == "metered" and "day" in spent["amounts"], "an orphan of amounts reads as metered"
    node = got["hookstub:nodeacct"]
    assert node["profiles"] == ["np"] and node["labels"] == ["5h"]
    split = got["hookstub:split"]
    assert split["billing"] == "mixed" and split["billings"] == {"api": "metered", "pc": "subscription"}
    assert {"day", "week", "month"} <= set(split["labels"]), "a mixed account keeps its spend labels"


@pytest.mark.integration
async def test_a_nodes_spend_and_usage_calls_put_their_profiles_on_the_account(agent, hookstub):
    """`_account_on`'s node sources (§6 *The profiles on an account*, TD-1629): a profile a node's spend call named
    under the account is metered, one its usage call named is a subscription — each counts toward the account's
    one billing, so a disagreement with the home's profiles is refused."""
    await park_ticks(agent)
    hookstub.accounts = {"pa": "paul"}
    hookstub.billing = {"api": {"billing": "metered", "prices": {"m": 1.0}}}
    hookstub.accounts["api"] = "key"
    agent._spend_named["node1"] = {"hookstub:paul": {"napi"}}
    agent._usage_remote_keys[("node1", "np")] = "hookstub:key"
    async with LocalClient() as person:
        with pytest.raises(AgentError, match=r"profiles disagree on billing \(napi metered, pa subscription\)"):
            await person.call("set_settings", account="hookstub:paul", reserves={"5h": 30})
        with pytest.raises(AgentError, match=r"profiles disagree on billing \(api metered, np subscription\)"):
            await person.call("set_settings", account="hookstub:key", reserves={"day": "$5"})
    assert not settings_mod.load().get("usage_gate")


@pytest.mark.integration
async def test_a_profile_only_a_record_runs_under_is_on_its_account(agent, hookstub, tmp_path):
    """A profile no adapter lists but a record here runs under is on the account it resolves to (TD-1629): the
    account takes a reserve by its key, naming that profile, where it would be one this home has not seen."""
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await person.call("create", name="pr", dir=str(tmp_path), adapter="hookstub", profile="pr")
        got = await person.call("set_settings", account="hookstub:pr", reserves={"5h": 30})
        assert (got["account"], got["profiles"]) == ("hookstub:pr", ["pr"])
        await person.call("kill", id=s["id"])
        await person.call("remove", id=s["id"])


@pytest.mark.integration
async def test_a_profile_its_adapter_answers_for_but_does_not_list_takes_a_set(agent, hookstub, monkeypatch):
    """The default insertion (TD-1629): an adapter whose `profiles()` lists nothing still answers `account_for`, so a
    set by that profile's name puts it on its account rather than refusing the account as unseen."""
    await park_ticks(agent)
    hookstub.accounts = {"pa": "paul"}
    monkeypatch.setattr(hookstub, "profiles", lambda: [])
    async with LocalClient() as person:
        got = await person.call("set_settings", profile="pa", reserves={"5h": 30})
    assert (got["account"], got["profiles"]) == ("hookstub:paul", ["pa"])
    assert settings_mod.load()["usage_gate"] == {"hookstub:paul": {"5h": 30}}


@pytest.mark.integration
async def test_a_metered_accounts_prices_are_pooled_and_a_profiles_reading_checks_the_labels(agent, hookstub):
    """A metered account's prices are the first of its profiles' that has any (§6 *One billing*), so a set by the
    profile with none still takes money; and with no account reading, a profile's own reading checks a set's
    labels (TD-1629)."""
    await park_ticks(agent)
    hookstub.accounts = {"api": "key", "api2": "key", "pa": "paul", "pb": "paul"}
    hookstub.billing = {
        "api": {"billing": "metered", "prices": {}},
        "api2": {"billing": "metered", "prices": {"m": 1.0}},
    }
    async with LocalClient() as person:
        got = await person.call("set_settings", profile="api", reserves={"day": "$5"})
        assert got["reserves"] == {"day": "$5"}
        agent._usage["pb"] = {"windows": [{"label": "5h", "pct": 10}], "reason": "ok"}
        with pytest.raises(AgentError, match="reports no window week: its windows are 5h"):
            await person.call("set_settings", account="hookstub:paul", reserves={"week": 30})
