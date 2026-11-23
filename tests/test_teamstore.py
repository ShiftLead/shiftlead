"""A team's store after the cut-over (design §4.9d, TD-2060): the marker, `team_set`'s edits, the re-key of a renamed
stage, and the one pick of a login for a model."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sessionorc import settings as settings_mod
from sessionorc import teamstore as ts
from sessionorc.agent_common import RpcError
from sessionorc.agent_settings import SettingsMixin


def _doc(**team):
    return {"cut_over": "2026-12-01", "teams": {"a": {"repo": "shiftlead", "host": "home", "flow": "build", **team}}}


def _set(doc, **change):
    return ts.apply(doc, "a", change, ts.version(doc, "a"))


def _row(account="acct", models=("opus",), state="signed_in", **more):
    return {"account": account, "models": list(models), "state": state, **more}


def test_every_write_is_refused_before_the_marker():
    doc = _doc()
    del doc["cut_over"]
    with pytest.raises(ts.TeamError, match="after the switch-over"):
        _set(doc, label="x")


def test_a_team_with_no_repo_in_settings_is_not_switched_and_takes_no_write():
    doc = {"cut_over": "2026-12-01", "teams": {"a": {"reserve": 5}}}
    assert not ts.switched(doc, "a")
    with pytest.raises(ts.TeamError, match="no switched team"):
        ts.apply(doc, "a", {"label": "x"}, ts.version(doc, "a"))


def test_a_write_over_a_newer_version_or_with_none_is_refused():
    doc = _doc()
    was = ts.version(doc, "a")
    _set(doc, most=3)
    for sent in (was, None):
        with pytest.raises(ts.TeamError, match="reload"):
            ts.apply(doc, "a", {"most": 4}, sent)


def test_a_running_setting_does_not_move_the_version():
    doc = _doc()
    was = ts.version(doc, "a")
    doc["teams"]["a"]["until"] = "2026-12-02T00:00:00Z"
    assert ts.version(doc, "a") == was


@pytest.mark.parametrize("change", [{}, {"repo": "x"}, {"label": "x", "most": 2}])
def test_a_write_takes_exactly_one_of_the_page_keys(change):
    doc = _doc()
    with pytest.raises(ts.TeamError, match="takes one of"):
        ts.apply(doc, "a", change, ts.version(doc, "a"))


def test_label_is_set_and_an_empty_one_clears_it():
    doc = _doc()
    _set(doc, label="  Builders ")
    assert doc["teams"]["a"]["label"] == "Builders"
    _set(doc, label="")
    assert "label" not in doc["teams"]["a"]


def test_the_list_reorders_adds_and_removes_and_may_be_emptied():
    doc = _doc(logins=["claude-code:a", "grok:b"])
    _set(doc, logins=["grok:b", "claude-code:a", "gemini:c"])
    assert doc["teams"]["a"]["logins"] == ["grok:b", "claude-code:a", "gemini:c"]
    _set(doc, logins=[])
    assert doc["teams"]["a"]["logins"] == []


@pytest.mark.parametrize("bad", ["x", ["nocolon"], ["t:bad name"], ["t:a", "t:a"], [1]])
def test_a_bad_list_is_refused(bad):
    with pytest.raises(ts.TeamError):
        _set(_doc(), logins=bad)


def test_at_once_merges_by_stage_and_null_removes_a_key():
    doc = _doc(at_once={"build": 2, "gone": 1})
    _set(doc, at_once={"review": 3, "gone": None})
    assert doc["teams"]["a"]["at_once"] == {"build": 2, "review": 3}
    _set(doc, at_once={"build": None})
    _set(doc, at_once={"review": None})
    assert "at_once" not in doc["teams"]["a"]


@pytest.mark.parametrize("n", [0, -1, True, "2", 1.5])
def test_numbers_are_whole_and_at_least_one(n):
    with pytest.raises(ts.TeamError, match="whole number"):
        _set(_doc(), most=n)
    with pytest.raises(ts.TeamError, match="whole number"):
        _set(_doc(), at_once={"build": n})


def test_null_clears_the_team_limit():
    doc = _doc(most=4)
    _set(doc, most=None)
    assert "most" not in doc["teams"]["a"]


def test_a_rename_rekeys_only_the_teams_on_that_flow_and_a_swap_holds():
    doc = _doc(at_once={"x": 1, "y": 2})
    doc["teams"]["other"] = {"repo": "r", "flow": "else", "at_once": {"x": 5}}
    doc["teams"]["first"] = {"flow": "build", "at_once": {"x": 7}}  # not switched: its flow is the first shape's key
    assert ts.rekey(doc, "build", {"x": "y", "y": "x"}) == ["a"]
    assert doc["teams"]["a"]["at_once"] == {"y": 1, "x": 2}
    assert doc["teams"]["other"]["at_once"] == {"x": 5}
    assert doc["teams"]["first"]["at_once"] == {"x": 7}


def test_a_renamed_stages_number_wins_over_a_stale_key_of_its_new_name():
    doc = _doc(at_once={"b": 9, "a": 2})
    ts.rekey(doc, "build", {"a": "b"})
    assert doc["teams"]["a"]["at_once"] == {"b": 2}


def test_pick_takes_the_first_usable_login_offering_the_model():
    rows = {"t:a": _row("one", ("sonnet",)), "t:b": _row("two"), "t:c": _row("three")}
    assert ts.pick(["t:a", "t:b", "t:c"], "opus", rows) == {"login": "t:b", "state": "usable", "why": None}


def test_a_pin_narrows_what_a_login_offers():
    rows = {"t:a": _row("one", ("opus", "sonnet"), pin="sonnet"), "t:b": _row("two")}
    assert ts.pick(["t:a", "t:b"], "opus", rows)["login"] == "t:b"


@pytest.mark.parametrize(
    "row",
    [_row(state="limited"), _row(state="not_signed_in"), _row(account=None), _row(at_reserve=True)],
)
def test_an_unusable_login_is_passed_over_and_alone_reads_as_a_wait(row):
    assert ts.pick(["t:a", "t:b"], "opus", {"t:a": row, "t:b": _row("two")})["login"] == "t:b"
    got = ts.pick(["t:a"], "opus", {"t:a": row})
    assert (got["login"], got["state"]) == (None, "waits")


def test_a_login_on_an_account_an_earlier_unusable_one_shares_is_passed_over():
    rows = {"t:a": _row("one", ("sonnet",), at_reserve=True), "t:b": _row("one"), "t:c": _row("two")}
    assert ts.pick(["t:a", "t:b", "t:c"], "opus", rows)["login"] == "t:c"
    assert ts.pick(["t:b", "t:a"], "opus", rows)["login"] == "t:b", "only an earlier login bars its account"


def test_no_login_offering_the_model_names_it():
    got = ts.pick(["t:a"], "fable", {"t:a": _row()})
    assert got == {"login": None, "state": "none", "why": "no login in its list offers fable"}


def test_cannot_run_names_the_model_and_a_mere_wait_is_not_it():
    rows = {"t:a": _row(models=("opus",), state="limited")}
    assert ts.cannot_run("g", "wise", ["opus"], ["t:a"], rows) is None
    assert (
        ts.cannot_run("g", "wise", ["opus", "fable"], ["t:a"], rows)
        == "g cannot run wise: no login in its list offers fable"
    )
    assert ts.cannot_run("g", "wise", ["opus"], [], rows) == "g cannot run wise: its login list is empty"


class _Agent(SettingsMixin):
    """The mixin's write, with its push, commit and caller graph stubbed."""

    def __init__(self):
        self._bg = set()
        self.pushed = 0

    def _graph(self):
        return {}

    async def _push_settings(self):
        self.pushed += 1

    async def _commit_defs(self, message, files):
        self.message = message


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    settings_mod.save(_doc())
    return _Agent()


def test_team_set_writes_the_file_and_answers_the_new_version(agent):
    async def run():
        was = ts.version(settings_mod.load(), "a")
        got = await agent.rpc_team_set(team="a", most=3, version=was)
        await asyncio.gather(*agent._bg)
        return got

    got = asyncio.run(run())
    doc = settings_mod.load()
    assert doc["teams"]["a"]["most"] == 3 and got["version"] == ts.version(doc, "a") and agent.pushed == 1


def test_team_set_passes_a_null_as_a_clear_and_no_key_as_a_refusal(agent):
    doc = settings_mod.load()
    doc["teams"]["a"].update(most=3, label="shown")
    settings_mod.save(doc)

    async def run():
        with pytest.raises(RpcError, match="takes one of"):
            await agent.rpc_team_set(team="a", version=ts.version(settings_mod.load(), "a"))
        for bad in ({"clear": "logins"}, {"clear": "label"}, {"clear": "most", "label": "x"}):
            with pytest.raises(RpcError, match="clears most alone"):
                await agent.rpc_team_set(team="a", version=ts.version(settings_mod.load(), "a"), **bad)
        await agent.rpc_team_set(team="a", clear="most", version=ts.version(settings_mod.load(), "a"))
        await agent.rpc_team_set(team="a", label="", version=ts.version(settings_mod.load(), "a"))
        await asyncio.gather(*agent._bg)

    asyncio.run(run())
    held = settings_mod.load()["teams"]["a"]
    assert "most" not in held and "label" not in held


def test_a_saved_rename_reaches_the_teams_numbers(agent):
    doc = settings_mod.load()
    doc["teams"]["a"]["at_once"] = {"old": 2}
    settings_mod.save(doc)

    async def run():
        await agent._rekey_teams("build", {"old": "new"})
        await asyncio.gather(*agent._bg)

    asyncio.run(run())
    assert settings_mod.load()["teams"]["a"]["at_once"] == {"new": 2}


def test_team_show_reads_this_hosts_logins_with_the_teams_reserve(agent, monkeypatch):
    doc = settings_mod.load()
    doc["teams"]["a"].update(logins=["claude:x"], reserve=10)
    settings_mod.save(doc)
    account = {"key": "acct", "models": {"families": ["opus"]}}
    login = {"name": "x", "account": "acct", "state": "signed_in"}
    window = {"label": "week", "pct": 75, "reserve": 20, "resets": "2099-01-01T00:00:00Z"}
    seen = {}

    async def tools():
        return {"tools": [{"adapter": "claude", "accounts": [account], "logins": [login]}]}

    async def gate():
        return {"accounts": {"acct": {"windows": [window]}}}

    def call(**kw):
        seen.update(kw)
        return {"team": kw["team"]}

    agent.rpc_tools, agent.rpc_gate = tools, gate
    agent._graph = lambda: {}
    agent._usage, agent._usage_acct = {}, {}
    monkeypatch.setattr("sessionorc.agent_settings.home_call", lambda name: SimpleNamespace(call=call))
    assert asyncio.run(agent.rpc_team_show(team="a")) == {"team": "a"}
    assert seen["rows"]["claude:x"]["at_reserve"] is True and seen["head"]["word"] == "stopped"


# -- New team and Delete (design §4.9d *New team*, *Delete*, TD-2063) ------------------------------------------------


def _cut(**teams):
    return {"cut_over": "2026-12-01", "teams": teams}


def test_a_new_team_is_stopped_with_an_empty_login_list():
    doc = _cut()
    assert ts.new(doc, "db", label=" Data ", repo="shiftlead", host="home", flow="build") == "db made"
    assert doc["teams"]["db"] == {"repo": "shiftlead", "host": "home", "flow": "build", "logins": [], "label": "Data"}
    assert ts.switched(doc, "db")


@pytest.mark.parametrize(
    ("doc", "name", "words"),
    [
        ({"teams": {}}, "db", ts.BEFORE),
        (_cut(), "no spaces", "not a team's name"),
        (_cut(DB={"repo": "r"}), "db", "already a team"),
    ],
)
def test_a_new_team_is_refused(doc, name, words):
    with pytest.raises(ts.TeamError, match=words):
        ts.new(doc, name, label=None, repo="r", host="h", flow="build")


def test_delete_takes_the_version_and_the_marker():
    doc = _cut(a={"repo": "r", "logins": []}, b={"repo": "r"})
    for bad, words in ((None, "changed since"), ("old", "changed since")):
        with pytest.raises(ts.TeamError, match=words):
            ts.delete(doc, "a", bad)
    before = {"teams": {"a": {"repo": "r"}}}
    with pytest.raises(ts.TeamError, match=ts.BEFORE):
        ts.delete(before, "a", ts.version(before, "a"))
    assert ts.delete(doc, "a", ts.version(doc, "a")) == "a deleted" and list(doc["teams"]) == ["b"]


def _agent_on(monkeypatch, body, live=()):
    monkeypatch.setattr("sessionorc.agent_settings.home_call", lambda name: body)
    monkeypatch.setattr(
        "sessionorc.agent_settings.hosts.local_host",
        lambda: SimpleNamespace(name="home", repos=lambda: ["/x/shiftlead"]),
    )
    a = _Agent()
    a._graph = lambda: {r.id: r for r in live}
    return a


def test_team_new_writes_the_team_and_refuses_an_unknown_repo(agent, monkeypatch):
    body = SimpleNamespace(new_refusal=lambda **kw: None if kw["repo"] == "shiftlead" else "not registered")
    a = _agent_on(monkeypatch, body)

    async def go():
        with pytest.raises(RpcError, match="not registered"):
            await a.rpc_team_new(name="db", repo="other", flow="build")
        assert "db" not in settings_mod.load()["teams"]
        with pytest.raises(RpcError, match="neither this home"):
            await a.rpc_team_new(name="db", repo="shiftlead", host="far", flow="build")
        got = await a.rpc_team_new(name="db", repo="shiftlead", flow="build")
        assert got["team"] == "db" and settings_mod.load()["teams"]["db"]["host"] == "home"

    asyncio.run(go())


def test_team_delete_names_what_refuses_it_and_keeps_the_team(agent, monkeypatch):
    dropped = []
    held = ["TD-2101 is in build", "TD-2084 waits on you"]
    body = SimpleNamespace(open_records=lambda *_: held, drop_copy=lambda *a: dropped.append(a))

    async def go():
        live = [SimpleNamespace(id="ao-a-1", team="a", state="working")]
        a = _agent_on(monkeypatch, body, live)
        v = ts.version(settings_mod.load(), "a")
        with pytest.raises(RpcError, match="live sessions: ao-a-1"):
            await a.rpc_team_delete(team="a", version=v)
        a = _agent_on(monkeypatch, body)
        with pytest.raises(RpcError, match="TD-2101 is in build; TD-2084 waits on you"):
            await a.rpc_team_delete(team="a", version=v)
        assert not dropped and "a" in settings_mod.load()["teams"]
        held.clear()
        await a.rpc_team_delete(team="a", version=v)
        assert dropped and "a" not in (settings_mod.load().get("teams") or {})

    asyncio.run(go())


def test_a_state_branch_not_read_refuses_the_delete(agent, monkeypatch):
    def broken(*_):
        raise OSError("origin away")

    a = _agent_on(monkeypatch, SimpleNamespace(open_records=broken, drop_copy=broken))
    v = ts.version(settings_mod.load(), "a")
    with pytest.raises(RpcError, match="not deleted: origin away"):
        asyncio.run(a.rpc_team_delete(team="a", version=v))
    assert "a" in settings_mod.load()["teams"]
