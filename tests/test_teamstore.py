"""A team's store after the cut-over (design §4.9d, TD-2060): the marker, `team_set`'s edits, the re-key of a renamed
stage, and the one pick of a login for a model."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
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
    agent._graph, agent._host_rec = (lambda: {}), {}
    agent._usage, agent._usage_acct = {}, {}
    monkeypatch.setattr("sessionorc.agent_settings.home_call", lambda name: SimpleNamespace(call=call))
    assert asyncio.run(agent.rpc_team_show(team="a")) == {"team": "a"}
    assert seen["rows"]["claude:x"]["at_reserve"] is True and seen["head"]["word"] == "stopped"
    assert seen["node_mark"] is None
    agent._host_rec = {"teams": {"a": {"node_cannot_run": {"model": "opus"}}}}
    asyncio.run(agent.rpc_team_show(team="a"))
    assert seen["node_mark"] == {"model": "opus"}, "the home's mark of a team on a node reaches the read"


def test_after_the_cut_over_a_switched_teams_head_reads_its_started_mark(agent):
    """§4.9d *The page*, *Start and Wind down* (TD-2065): running while started, else who stopped it, with the
    sessions still ending as `finishing`; before the cut-over the head is read off the records as it was."""
    from sessionorc.models import Session

    live = Session(id="ao-x-s", name="s", kind="agent", adapter="shell", dir="/tmp/x", team="a", state="idle")
    live.unattended = True
    mine = Session(id="ao-x-p", name="p", kind="agent", adapter="shell", dir="/tmp/x", team="a", state="idle")
    gone = Session(id="ao-x-g", name="g", kind="agent", adapter="shell", dir="/tmp/x", team="a", state="idle")
    gone.unattended, gone.superseded_by = True, "ao-x-s"
    lead = Session(id="ao-x-t", name="t", kind="agent", adapter="shell", dir="/tmp/x", team="a", state="idle")
    lead.unattended, lead.seat, lead.builtin = True, {"trigger": "asks", "tags": True}, "techlead"
    seat = Session(id="ao-x-q", name="q", kind="agent", adapter="shell", dir="/tmp/x", team="a", state="idle")
    seat.unattended, seat.seat = True, {"trigger": "asks"}
    # a person's own, a superseded one and a seat, built-in or not: none counted, live or finishing (§4.9d)
    agent._graph = lambda: {r.id: r for r in (live, mine, gone, lead, seat)}
    doc = settings_mod.load()
    cut = doc.pop("cut_over")
    agent._host_rec = {"teams": {"a": {"stopped": {"at": "t", "by": "person"}}}}
    assert agent._team_head("a", doc)["word"] == "running", "before the cut-over the mark is not read"
    doc["cut_over"] = cut
    agent._host_rec = {"teams": {"a": {"started": {"since": "t", "by": "person"}}}}
    assert agent._team_head("a", doc) == {"word": "running", "sessions": 1, "by": None}
    agent._host_rec = {"teams": {"a": {"stopped": {"at": "t", "by": "person"}}}}
    assert agent._team_head("a", doc) == {"word": "stopped", "sessions": 1, "by": "person", "finishing": 1}
    live.state = "exited"
    assert agent._team_head("a", doc) == {"word": "stopped", "sessions": 0, "by": "person"}, "a filled seat: none"
    agent._host_rec = {}
    assert agent._team_head("a", doc)["by"] is None, "never started: Stopped"


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
    a._host_rec = {}
    a.host_store = SimpleNamespace(save=lambda rec: a.__dict__.setdefault("host_saves", []).append(copy.deepcopy(rec)))

    async def pushed():
        a.__dict__["host_pushes"] = a.__dict__.get("host_pushes", 0) + 1

    a._push_changes = pushed
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


def test_a_settings_write_during_new_teams_check_is_kept(agent, monkeypatch):
    """The refusal runs in a thread: what another write saved meanwhile is not overwritten by the older copy."""

    def checked(**_kw):
        doc = settings_mod.load()
        doc["teams"]["a"]["logins"] = ["claude:meanwhile"]
        settings_mod.save(doc)

    a = _agent_on(monkeypatch, SimpleNamespace(new_refusal=checked))
    asyncio.run(a.rpc_team_new(name="db", repo="shiftlead", flow="build"))
    doc = settings_mod.load()
    assert "db" in doc["teams"] and doc["teams"]["a"]["logins"] == ["claude:meanwhile"]


def test_delete_removes_the_home_record_so_a_remade_name_starts_clean(agent, monkeypatch):
    body = SimpleNamespace(open_records=lambda *_: [], drop_copy=lambda *_: None, new_refusal=lambda **_: None)
    a = _agent_on(monkeypatch, body)
    a._host_rec = {"teams": {"a": {"schedule_fired": "x", "work_waiting": {"stopped": True}}, "b": {"keep": 1}}}
    repo = settings_mod.load()["teams"]["a"]["repo"]

    async def go():
        await a.rpc_team_delete(team="a", version=ts.version(settings_mod.load(), "a"))
        assert a._host_rec["teams"] == {"b": {"keep": 1}}, "another team's record stands"
        assert a.host_saves[-1]["teams"] == {"b": {"keep": 1}} and a.host_pushes == 1
        await a.rpc_team_new(name="a", repo=repo, flow="build")
        assert "a" not in a._host_rec["teams"]

    asyncio.run(go())


def test_a_state_branch_not_read_refuses_the_delete(agent, monkeypatch):
    def broken(*_):
        raise OSError("origin away")

    a = _agent_on(monkeypatch, SimpleNamespace(open_records=broken, drop_copy=broken))
    v = ts.version(settings_mod.load(), "a")
    with pytest.raises(RpcError, match="not deleted: origin away"):
        asyncio.run(a.rpc_team_delete(team="a", version=v))
    assert "a" in settings_mod.load()["teams"]


# the started mark (§4.9d *Started is a mark the home keeps*, TD-2065)


def test_a_start_sets_the_mark_and_deletes_stopped_and_a_second_start_writes_nothing():
    marks = {"a": {"stopped": {"at": "t0", "by": "person"}, "balance": {"keep": 1}}}
    assert not ts.started(marks, "a")
    assert ts.mark_started(marks, "a", "schedule", "t1")
    assert marks == {"a": {"started": {"since": "t1", "by": "schedule"}, "balance": {"keep": 1}}}
    assert ts.started(marks, "a") and not ts.started(marks, "b") and not ts.started(None, "a")
    assert not ts.mark_started(marks, "a", "person", "t2") and marks["a"]["started"]["since"] == "t1"
    with pytest.raises(ValueError):
        ts.mark_started(marks, "b", "tick", "t1")


def test_a_stop_clears_only_a_set_mark_so_a_stop_time_never_overwrites_the_persons():
    marks = {"a": {"started": {"since": "t1", "by": "person"}}}
    assert ts.mark_stopped(marks, "a", "person", "t2")
    assert marks == {"a": {"stopped": {"at": "t2", "by": "person"}}}
    assert not ts.mark_stopped(marks, "a", "until", "t3"), "a stop time on a stopped team is spent"
    assert marks["a"]["stopped"] == {"at": "t2", "by": "person"}
    assert not ts.mark_stopped(marks, "b", "until", "t3") and "b" not in marks
    with pytest.raises(ValueError):
        ts.mark_stopped(marks, "a", "schedule", "t3")


def test_a_stop_time_is_due_only_on_a_mark_set_before_its_instant_once_it_has_passed():
    now = datetime(2026, 12, 2, 12, tzinfo=UTC)
    marks = {"a": {"started": {"since": "2026-12-01T09:00:00+00:00", "by": "person"}}, "b": {"stopped": {}}}
    assert ts.stop_time_due(marks, "a", "2026-12-02T10:00:00Z", now)
    assert ts.stop_time_due(marks, "a", "2026-12-02T12:00:00+00:00", now), "at the instant itself"
    assert not ts.stop_time_due(marks, "a", "2026-12-02T13:00:00Z", now), "still ahead"
    assert not ts.stop_time_due(marks, "a", "2026-12-01T08:00:00Z", now), "spent: the Start came after it"
    assert not ts.stop_time_due(marks, "b", "2026-12-02T10:00:00Z", now), "not started: nothing to clear"
    assert not ts.stop_time_due(marks, "c", "2026-12-02T10:00:00Z", now) and not ts.stop_time_due(None, "a", "x", now)
    assert not ts.stop_time_due(marks, "a", "not a time", now)


def test_team_mark_starts_and_winds_down_a_switched_team_and_saves_the_record(agent, monkeypatch):
    a = _agent_on(monkeypatch, SimpleNamespace())

    async def go():
        got = await a.rpc_team_mark(team="a", started=True)
        assert got == {"team": "a", "started": True, "change": "a started"}
        assert a._host_rec["teams"]["a"]["started"]["by"] == "person"
        assert a.host_saves[-1]["teams"]["a"]["started"] and a.host_pushes == 1
        again = await a.rpc_team_mark(team="a", started=True)
        assert again["change"] == "a is already started" and a.host_pushes == 1
        got = await a.rpc_team_mark(team="a", started=False)
        assert got["change"] == "a wound down"
        assert set(a._host_rec["teams"]["a"]) == {"stopped"} and a._host_rec["teams"]["a"]["stopped"]["by"] == "person"
        assert (await a.rpc_team_mark(team="a", started=False))["change"] == "a is not started"
        assert a.host_pushes == 2

    asyncio.run(go())


def test_team_mark_is_refused_before_the_cut_over_for_an_unswitched_team_and_without_a_word(agent, monkeypatch):
    a = _agent_on(monkeypatch, SimpleNamespace())

    async def go():
        with pytest.raises(RpcError, match="no switched team 'zz'"):
            await a.rpc_team_mark(team="zz", started=True)
        with pytest.raises(RpcError, match="started: true"):
            await a.rpc_team_mark(team="a", started="yes")
        doc = settings_mod.load()
        del doc["cut_over"]
        settings_mod.save(doc)
        with pytest.raises(RpcError, match=ts.BEFORE):
            await a.rpc_team_mark(team="a", started=True)
        assert a._host_rec == {} and not a.__dict__.get("host_saves")

    asyncio.run(go())


def test_a_mark_that_cannot_be_saved_is_put_back(agent, monkeypatch):
    a = _agent_on(monkeypatch, SimpleNamespace())

    def broken(_rec):
        raise OSError("disk full")

    a.host_store = SimpleNamespace(save=broken)
    with pytest.raises(OSError):
        asyncio.run(a.rpc_team_mark(team="a", started=True))
    assert "a" not in a._host_rec.get("teams", {})


def test_delete_is_refused_while_the_team_is_started(agent, monkeypatch):
    body = SimpleNamespace(open_records=lambda *_: [], drop_copy=lambda *_: None)
    a = _agent_on(monkeypatch, body)
    a._host_rec = {"teams": {"a": {"started": {"since": "t1", "by": "person"}}}}
    v = ts.version(settings_mod.load(), "a")
    with pytest.raises(RpcError, match="a is started: wind it down first"):
        asyncio.run(a.rpc_team_delete(team="a", version=v))
    assert "a" in settings_mod.load()["teams"]


def test_delete_removes_the_teams_built_in_tech_lead_records_on_their_hosts(agent, monkeypatch):
    """§4.9d *How each one runs* (TD-2065): Delete removes the team's `builtin: techlead` records as Forget does, here
    and on a node, and no first-shape seat or another team's record."""
    body = SimpleNamespace(open_records=lambda *_: [], drop_copy=lambda *_: None)
    recs = {
        "ao-s-techlead-a": SimpleNamespace(id="ao-s-techlead-a", team="a", state="closed", builtin="techlead"),
        "ao-s-techlead-a@node": SimpleNamespace(id="ao-s-techlead-a", team="a", state="closed", builtin="techlead"),
        "ao-s-techlead-ao-1": SimpleNamespace(id="ao-s-techlead-ao-1", team="a", state="closed", builtin=None),
        "ao-s-techlead-b": SimpleNamespace(id="ao-s-techlead-b", team="b", state="closed", builtin="techlead"),
    }
    a = _agent_on(monkeypatch, body)
    a._graph = lambda: dict(recs)
    removed, routed = [], []

    async def remove(id, caller=None):
        removed.append(id)

    async def route(method, params, caller, host):
        routed.append((method, params["id"], host))

    a.rpc_remove, a._route_act = remove, route
    asyncio.run(a.rpc_team_delete(team="a", version=ts.version(settings_mod.load(), "a")))
    assert removed == ["ao-s-techlead-a"] and routed == [("remove", "ao-s-techlead-a@node", "node")]
    assert "a" not in (settings_mod.load().get("teams") or {})


def test_a_tech_lead_record_not_removed_refuses_the_delete_and_keeps_the_team(agent, monkeypatch):
    dropped = []
    body = SimpleNamespace(open_records=lambda *_: [], drop_copy=lambda *a: dropped.append(a))
    a = _agent_on(monkeypatch, body)
    rec = SimpleNamespace(id="ao-s-techlead-a", team="a", state="closed", builtin="techlead")
    a._graph = lambda: {"ao-s-techlead-a@node": rec}

    async def route(*_a):
        raise RpcError("node is unreachable")

    a._route_act = route
    with pytest.raises(RpcError, match="not deleted: its tech lead's record ao-s-techlead-a@node was not removed"):
        asyncio.run(a.rpc_team_delete(team="a", version=ts.version(settings_mod.load(), "a")))
    assert "a" in settings_mod.load()["teams"] and not dropped, "the state branch's copy is kept too"


def test_team_node_cannot_marks_a_team_on_its_host_record_and_is_the_homes_own(agent, monkeypatch):
    """§4.9d *A team on a node*, TD-2068: the stage pass's mark that the team's node found no login of its list offering
    a model, kept beside the started mark with the list and the flow it was read against; refused from a session, at
    a node, for a team not switched and without a model or a list."""
    a = _agent_on(monkeypatch, SimpleNamespace())
    a.mode, a.host, a.home = "home", "home", "home"

    async def go():
        await a.rpc_team_mark(team="a", started=True)
        got = await a.rpc_team_node_cannot(team="a", model="opus", logins=["claude-code:x"], flow="build")
        mark = a._host_rec["teams"]["a"]["node_cannot_run"]
        assert {k: mark[k] for k in ("model", "logins", "flow")} == {
            "model": "opus",
            "logins": ["claude-code:x"],
            "flow": "build",
        }
        assert got["team"] == "a" and a.host_saves[-1]["teams"]["a"]["node_cannot_run"] == mark
        assert a._host_rec["teams"]["a"]["started"], "the started mark stands beside it"
        for kw, words in (
            ({"caller": "s-1"}, "never a session's"),
            ({"team": "zz"}, "no switched team"),
            ({"model": " "}, "names the model"),
            ({"logins": "claude-code:x"}, "as login keys"),
        ):
            with pytest.raises(RpcError, match=words):
                await a.rpc_team_node_cannot(**{"team": "a", "model": "opus", "logins": [], "flow": "build", **kw})
        a.mode = "node"
        with pytest.raises(RpcError, match="is a node of"):
            await a.rpc_team_node_cannot(team="a", model="opus", logins=[], flow="build")

    asyncio.run(go())


def test_builtins_node_cannot_marks_a_sets_seat_on_a_node_and_is_the_homes_own(agent, monkeypatch):
    """§4.9d *Where a seat's session launches*, TD-2068: the stage pass's mark that a node found no login of a built-in
    set's list offering a seat's model, per seat and node, on the host record's `builtins` entry with the list it was
    read against; refused from a session, at a node, for the home itself, and for an unknown set or seat."""
    a = _agent_on(monkeypatch, SimpleNamespace())
    a.mode, a.host, a.home = "home", "home", "home"
    ok = {"set": "default", "seat": "sweeper", "host": "n", "model": "haiku", "logins": ["claude-code:x"]}

    async def go():
        got = await a.rpc_builtins_node_cannot(**ok)
        await a.rpc_builtins_node_cannot(**{**ok, "host": "m", "model": "opus"})
        marks = a._host_rec["builtins"]["default"]["node_cannot_run"]["sweeper"]
        assert {k: marks["n"][k] for k in ("model", "logins")} == {"model": "haiku", "logins": ["claude-code:x"]}
        assert marks["m"]["model"] == "opus", "each node's mark is its own"
        assert got["host"] == "n" and a.host_saves[-1]["builtins"]["default"]["node_cannot_run"]["sweeper"] == marks
        for kw, words in (
            ({"caller": "s-1"}, "never a session's"),
            ({"set": "zz"}, "no built-in set"),
            ({"seat": "zz"}, "is not a built-in seat"),
            ({"host": ""}, "names the node"),
            ({"host": "home"}, "names the node"),
            ({"model": " "}, "names the model"),
            ({"logins": "claude-code:x"}, "as login keys"),
        ):
            with pytest.raises(RpcError, match=words):
                await a.rpc_builtins_node_cannot(**{**ok, **kw})
        a.mode = "node"
        with pytest.raises(RpcError, match="is a node of"):
            await a.rpc_builtins_node_cannot(**ok)

    asyncio.run(go())
