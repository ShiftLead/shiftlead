"""A team's switch to another flow (design §4.9d *The flow pick and a switch*, TD-2062): the pick, the preview's line
for each record and the reconcile's case agreeing, the at-once numbers kept, the copy pushed before the key, a refused
push refusing the switch, and a restart finishing a switch it cut off."""

from __future__ import annotations

import asyncio
import copy
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from sessionorc import link
from sessionorc import settings as settings_mod
from sessionorc import teamstore as ts
from sessionorc.agent_common import RpcError
from sessionorc.agent_settings import SettingsMixin
from sessionorc.agent_stage import stage_teams
from shiftlead import org as orgmod
from shiftlead import stage_fetch, team_show
from shiftlead.stage_acts import Reading, choose, switch_case
from shiftlead.stage_read import flow_on
from shiftlead.stagerecord import StateRefused

OLD = {
    "format": 3,
    "name": "build",
    "stages": [
        {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": "Check"},
        {"name": "Check", "does": "review", "model": "opus", "ship": "merge", "changes-wanted": "Build"},
        {"name": "Docs", "does": "build", "model": "opus", "work-pushed": "Check"},
    ],
}
NEW = {
    "format": 3,
    "name": "lean",
    "stages": [
        {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": "Docs"},
        {"name": "Docs", "does": "review", "model": "opus", "ship": "merge", "changes-wanted": "Build"},
    ],
}
FABLE = {**NEW, "name": "pricey", "stages": [{**NEW["stages"][0], "model": "fable"}, NEW["stages"][1]]}
ROWS = {"claude:a": {"state": "signed_in", "account": "acct", "models": ["opus"]}}


def _doc(**team):
    entry = {"repo": "shiftlead", "host": "home", "flow": "build", "logins": ["claude:a"], **team}
    return {"cut_over": "2026-12-01", "teams": {"t": entry}}


def _rec(tid, stage, *, moves=1, waits=None, holder=None, team="t", pr=None):
    return {"id": tid, "team": team, "flow": "build", "stage": stage, "moves": moves, "waits": waits,
            "holder": holder, "pr": pr, "closed_at": None}  # fmt: skip


def _listing(*docs, problems=None):
    rows = [{"name": d["name"], "place": "own", "doc": d, "text": f"name: {d['name']}\n", "problems": []} for d in docs]
    if problems:
        rows.append({"name": "broken", "place": "own", "doc": {"name": "broken"}, "text": "", "problems": problems})
    rows.append({"name": "first", "place": "own", "doc": None, "text": "", "problems": []})
    rows.append({"name": "theirs", "place": "repo", "repo": "other", "doc": NEW, "text": "", "problems": []})
    return lambda _roots: {"flows": rows}


# -- one function: the preview's case is the reconcile's ------------------------------------------------------------

RECORDS = [
    _rec("TD-1", "build", holder="ao-t-1"),  # Build is in both flows as a build: stays
    _rec("TD-2", "check", holder="ao-t-2"),  # Check is gone, with moves made: to the person
    _rec("TD-3", "check", moves=0, holder="ao-t-3"),  # gone, no move yet: re-enters
    _rec("TD-4", "docs", holder="ao-t-4"),  # Docs is kept as a key, but a review now, not a build: gone
    _rec("TD-5", "check", waits="person"),  # waits on the person: left until the answer
    _rec("TD-6", "check", waits="merging"),  # merging: not touched
]
WANT = {"TD-1": "stays", "TD-2": "to-person", "TD-3": "re-enters", "TD-4": "to-person", "TD-5": "waits",
        "TD-6": "merging"}  # fmt: skip
RECONCILE = {"stays": "rewrite-flow", "to-person": "stage-gone", "re-enters": "re-enter"}


@pytest.mark.parametrize("record", RECORDS, ids=[r["id"] for r in RECORDS])
def test_each_records_line_and_the_reconciles_case_agree(record):
    lines = team_show.switch_lines([record], "t", NEW, OLD, live=[record["holder"] or "-"])
    assert lines[0]["case"] == WANT[record["id"]]
    known = flow_on(record, NEW, OLD)  # the tick reads the record against the new copy, with its old flow
    act = choose(record, Reading(stage_known=known.stage_known, flow_current=known.flow_current, gate=True))
    case = lines[0]["case"]
    if case in RECONCILE:
        assert act is not None and act.name == "reconcile" and act.case == RECONCILE[case]
    elif case == "waits":
        assert act is None, "a question to the person is left until its answer"
    else:
        assert act is not None and act.case == "merging", "the merge gate takes it, as before the switch"


def test_a_line_says_a_session_is_ended_only_where_it_is_live():
    lines = team_show.switch_lines(RECORDS, "t", NEW, OLD, live=["ao-t-2"])
    by_id = {x["id"]: x for x in lines}
    assert by_id["TD-2"]["ends"] and "not pushed is lost" in by_id["TD-2"]["line"]
    assert not by_id["TD-3"]["ends"] and "lost" not in by_id["TD-3"]["line"]
    assert not by_id["TD-1"]["ends"], "a record that stays keeps its session"
    assert by_id["TD-6"]["line"] == "merging, not touched"


def test_another_teams_and_closed_records_are_not_in_the_preview():
    held = [_rec("TD-1", "build"), _rec("TD-2", "build", team="u"), {**_rec("TD-3", "check"), "closed_at": "x"}]
    assert [x["id"] for x in team_show.switch_lines(held, "t", NEW, OLD, ())] == ["TD-1"]


def test_without_the_old_flow_a_kept_key_reads_as_known():
    assert switch_case(_rec("TD-4", "docs"), flow_on(_rec("TD-4", "docs"), NEW, None).stage_known) == "stays"


def test_the_tick_reads_a_switched_record_against_the_flow_it_names():
    """After the switch the copy is the new flow's, so the tick's `was` is gone: it reads the record's old flow by name,
    and the kept key with another kind is still a gone stage."""
    asked = []
    repo = SimpleNamespace(was=None, doc=NEW, named=lambda n: asked.append(n) or OLD)
    assert stage_fetch._written_under(repo, "build") is OLD and asked == ["build"]
    assert stage_fetch._written_under(repo, "lean") is None, "a record on the flow that runs needs no other"
    replaced = SimpleNamespace(was=OLD, doc=NEW, named=None)
    assert stage_fetch._written_under(replaced, "build") is OLD


# -- the pick -------------------------------------------------------------------------------------------------------


def test_the_pick_lists_every_flow_the_team_could_be_given_with_why_not(monkeypatch):
    monkeypatch.setattr(team_show.flow_save, "listing", _listing(OLD, NEW, FABLE, problems=["no stage takes work"]))
    got = {c["name"]: c for c in team_show.choices("t", _doc(), ROWS, "home", ["/x/shiftlead"])}
    assert set(got) == {"build", "lean", "pricey", "broken"}, "a first-shape flow and another repo's are not offered"
    assert got["build"]["current"] and got["lean"]["cannot_run"] is None
    assert got["pricey"]["cannot_run"] == "cannot run here: t cannot run pricey: no login in its list offers fable"
    assert got["broken"]["cannot_run"] == "cannot run here: no stage takes work"


def test_a_team_on_a_node_is_offered_no_org_flow(monkeypatch):
    monkeypatch.setattr(team_show.flow_save, "listing", _listing(NEW))
    got = {c["name"]: c for c in team_show.choices("t", _doc(host="far"), {}, "home", ["/x/shiftlead"])}
    assert got["lean"]["cannot_run"].startswith("not followable: an org flow, and t runs on far")


def _with_repo_flows(*names):
    rows = [{"name": "lean", "place": "own", "doc": NEW, "text": "", "problems": []}]
    rows += [{"name": n, "place": "repo", "repo": "shiftlead", "doc": NEW, "text": "", "problems": []} for n in names]
    return lambda _roots: {"flows": rows}


def test_a_node_teams_repo_flow_is_judged_by_what_the_nodes_checkout_holds(monkeypatch):
    """§4.9c *An org flow or role is not usable by a team on a node*, §4.9d (TD-2062 slice 3): a repo flow the node's
    checkout does not hold yet is not followable, by name; a node that did not answer reads unknown, never offered."""
    monkeypatch.setattr(team_show.flow_save, "listing", _with_repo_flows("merged", "branch"))
    doc = _doc(host="far")
    assert team_show.node_flow_paths("t", doc, "home", ["/x/shiftlead"]) == {
        "merged": ".shiftlead/flows/merged/flow.yml",
        "branch": ".shiftlead/flows/branch/flow.yml",
    }
    assert team_show.node_flow_paths("t", _doc(), "home", ["/x/shiftlead"]) == {}, "a team here asks no node"

    def pick(on_node):
        return {c["name"]: c["cannot_run"] for c in team_show.choices("t", doc, {}, "home", ["/x"], on_node)}

    held = pick({"merged": True, "branch": False})
    assert (
        held["merged"] is None and held["branch"] == "not followable: branch is not in far's checkout of shiftlead yet"
    )
    assert held["lean"].startswith("not followable: an org flow"), "an org flow is never a node team's"
    assert pick("far did not answer: link down")["merged"] == "unknown: far did not answer: link down"
    assert pick(None)["merged"] == team_show.NODE_REPO_FLOW, "not asked: not read, as the switch-over check says"


def _on_node_agent(agent, monkeypatch, repos, org=None):
    """An agent whose node `far` answers its registry with `repos` (a list, or an error to raise) and its files with
    `m.yml` held and `b.yml` not; the checkout found by the start's own helper, on `org` (the org file)."""
    monkeypatch.setattr(team_show.orgmod, "load", lambda: org or orgmod.Org())
    a = agent(SimpleNamespace())
    asked = []

    async def registry(host):
        if isinstance(repos, Exception):
            raise repos
        return {"host": host, "repos": list(repos)}

    class Mux:
        async def request(self, method, **kw):
            asked.append((method, kw["dir"], kw["paths"]))
            return {"dir": kw["dir"], "files": {"m.yml": "name: merged\n", "b.yml": None}}

    a.rpc_host_repos, a._node_mux = registry, lambda _host: Mux()
    return a, asked


def _node_body(paths=None):
    paths = paths or {"merged": "m.yml", "branch": "b.yml"}
    return SimpleNamespace(node_flow_paths=lambda *_a: paths, node_checkout=team_show.node_checkout)


def _ask(a, body=None):
    return asyncio.run(a._on_node(body or _node_body(), "t", _doc(host="far"), "home", []))


def test_the_host_agent_asks_the_node_which_repo_flows_its_checkout_holds(agent, monkeypatch):
    a, asked = _on_node_agent(agent, monkeypatch, ["/srv/other", "/srv/shiftlead"])
    assert _ask(a) == {"merged": True, "branch": False} and asked == [("files", "/srv/shiftlead", ["m.yml", "b.yml"])]
    many = {f"f{i}": f"f{i}.yml" for i in range(17)}  # past the 16 files a node reads in one request
    asked.clear()
    assert _ask(a, _node_body(many)) == dict.fromkeys(many, False) and [len(p) for _m, _d, p in asked] == [16, 1]
    assert asyncio.run(a._on_node(SimpleNamespace(node_flow_paths=HERE), "t", _doc(), "home", [])) is None


def test_the_nodes_checkout_is_found_as_a_start_finds_it(agent, monkeypatch):
    """The org file's path for the node first, with nothing asked of the registry; else the registry's one entry,
    two of them refused as a start refuses them (`org.host_checkout`, the helper `_land` takes)."""
    org = orgmod.Org(checkouts={"shiftlead": {"far": Path("/org/shiftlead")}})
    a, asked = _on_node_agent(agent, monkeypatch, OSError("the registry is not asked"), org)
    assert _ask(a) == {"merged": True, "branch": False} and asked[0][1] == "/org/shiftlead"
    a, asked = _on_node_agent(agent, monkeypatch, ["/srv/shiftlead", "/home/x/shiftlead"])
    assert (
        _ask(a)
        == (
            "far's registry holds shiftlead 2 times (/srv/shiftlead, /home/x/shiftlead) — register the one checkout of"
            " shiftlead on far (design §5 *Repos*)"
        )
        and not asked
    )
    a, asked = _on_node_agent(agent, monkeypatch, ["/srv/other"])
    assert _ask(a).startswith("far's registry holds no checkout named shiftlead — register") and not asked


def test_a_node_that_cannot_be_read_says_why(agent, monkeypatch):
    a, _ = _on_node_agent(agent, monkeypatch, RpcError("far did not answer: the link dropped"))
    assert _ask(a) == "far's registry could not be read (far did not answer: the link dropped)"
    a, _ = _on_node_agent(agent, monkeypatch, ["/srv/shiftlead"])

    class Refusing:
        async def request(self, method, **kw):
            raise link.LinkError("path outside the checkout")

    a._node_mux = lambda _host: Refusing()
    assert _ask(a) == "far: path outside the checkout", "a node's refusal in host_files' words, not *did not answer*"


# -- the preview and the push ---------------------------------------------------------------------------------------


class _Store:
    def __init__(self, records, copy_text="old"):
        self.records = {r["id"]: r for r in records}
        self.copy = copy_text
        self.puts = []
        self.lock = threading.RLock()

    def entries(self):
        return self.records

    def flow(self, _team):
        return self.copy

    def put_flow(self, team, text):
        self.puts.append((team, text))
        self.copy = text

    def locked(self):
        return self.lock


@pytest.fixture
def on_store(monkeypatch, tmp_path):
    (tmp_path / "shiftlead").mkdir()
    store = _Store(RECORDS)
    monkeypatch.setattr(team_show, "StageStore", lambda _root: store)
    monkeypatch.setattr(team_show, "_flow_doc", lambda *_a: OLD)
    monkeypatch.setattr(team_show.flow_save, "listing", _listing(OLD, NEW, FABLE))
    return store, [tmp_path / "shiftlead"]


def test_the_preview_draws_each_record_and_the_numbers_dropped(on_store):
    _store, roots = on_store
    doc = _doc(at_once={"build": 2, "check": 3})
    got = team_show.switch_preview(team="t", flow="lean", doc=doc, rows=ROWS, here="home", roots=roots)
    assert got["refused"] is None and got["from"] == "build" and got["drops"] == ["check"]
    assert {x["id"]: x["case"] for x in got["records"]} == WANT and got["none_ended"]


def test_the_preview_of_a_flow_the_team_cannot_run_is_refused(on_store):
    _store, roots = on_store
    got = team_show.switch_preview(team="t", flow="pricey", doc=_doc(), rows=ROWS, here="home", roots=roots)
    assert "no login in its list offers fable" in got["refused"] and got["records"] == []


def test_the_push_writes_the_copy_once_and_answers_the_new_keys(on_store):
    store, roots = on_store
    args = {"team": "t", "flow": "lean", "doc": _doc(), "rows": ROWS, "here": "home", "roots": roots}
    assert team_show.switch_push(**args) == ["build"], "docs is kept as a key but changes kind"
    assert store.puts == [("t", "name: lean\n")]
    team_show.switch_push(**args)
    assert len(store.puts) == 1, "a copy that already is the new flow's is not pushed again"
    with pytest.raises(ValueError, match="no login in its list offers fable"):
        team_show.switch_push(**{**args, "flow": "pricey"})
    assert team_show.switch_push(**{**args, "flow": "pricey", "check": False}) == ["build"]


# -- the settings write ---------------------------------------------------------------------------------------------


def test_the_switch_writes_the_flow_and_keeps_only_the_new_flows_numbers():
    doc = _doc(at_once={"build": 2, "check": 3})
    assert ts.switch(doc, "t", "lean", ts.version(doc, "t"), ["build", "docs"]) == "t switched to lean"
    assert doc["teams"]["t"]["flow"] == "lean" and doc["teams"]["t"]["at_once"] == {"build": 2}
    ts.switch(doc, "t", "build", ts.version(doc, "t"), ["docs"])
    assert "at_once" not in doc["teams"]["t"]


def test_the_switch_is_refused_before_the_marker_over_a_newer_version_and_to_the_same_flow():
    doc = _doc()
    with pytest.raises(ts.TeamError, match="already runs build"):
        ts.switch(doc, "t", "build", ts.version(doc, "t"), [])
    with pytest.raises(ts.TeamError, match="reload"):
        ts.switch(doc, "t", "lean", "stale", [])
    del doc["cut_over"]
    with pytest.raises(ts.TeamError, match=ts.BEFORE):
        ts.switch(doc, "t", "lean", ts.version(doc, "t"), [])


# -- the host agent's call ------------------------------------------------------------------------------------------


class _Agent(SettingsMixin):
    def __init__(self, body, live=()):
        self._bg = set()
        self.body = body
        self._host_rec = {}
        self.saves = []
        self.host_store = SimpleNamespace(save=lambda rec: self.saves.append(copy.deepcopy(rec)))
        self.live = list(live)

    def _graph(self):
        return {r.id: r for r in self.live}

    async def _push_settings(self):
        pass

    async def _commit_defs(self, message, files):
        pass

    async def _push_changes(self):
        pass

    async def rpc_tools(self):
        return {"tools": []}

    async def rpc_gate(self):
        return {"accounts": {}}

    def _projected(self, accounts, doc, now):
        return accounts


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    settings_mod.save(_doc(at_once={"build": 2, "check": 3}))
    monkeypatch.setattr(
        "sessionorc.agent_settings.hosts.local_host",
        lambda: SimpleNamespace(name="home", repos=lambda: ["/x/shiftlead"]),
    )

    def make(body, live=()):
        monkeypatch.setattr("sessionorc.agent_settings.home_call", lambda _name: body)
        return _Agent(body, live)

    return make


def HERE(*_a):  # a team here: no node is asked for its repo flows
    return {}


def _body(pushes, *, refuse=None, seen=None):
    def push(**kw):
        if seen is not None:
            seen.append(copy.deepcopy(kw))
        if refuse:
            raise refuse
        pushes.append(kw["flow"])
        return ["build", "docs"]

    return SimpleNamespace(switch_push=push, node_flow_paths=HERE)


def test_switch_now_marks_pushes_writes_the_key_and_clears_the_mark(agent):
    pushes = []
    a = agent(_body(pushes))
    marks = []
    a.host_store = SimpleNamespace(save=lambda rec: marks.append(copy.deepcopy(rec.get("teams"))))
    v = ts.version(settings_mod.load(), "t")
    got = asyncio.run(a.rpc_team_switch(team="t", flow="lean", version=v))
    entry = settings_mod.load()["teams"]["t"]
    assert pushes == ["lean"] and entry["flow"] == "lean" and entry["at_once"] == {"build": 2}
    assert marks[0] == {"t": {"switching": "lean"}} and marks[-1] == {}, "recorded before it is made, then cleared"
    assert got["change"] == "t switched to lean" and got["version"] == ts.version(settings_mod.load(), "t")


def test_a_refused_push_refuses_the_switch_and_changes_nothing(agent):
    a = agent(_body([], refuse=StateRefused("protected branch")))
    before = settings_mod.load()
    with pytest.raises(RpcError, match="not switched to lean: origin refused the push"):
        asyncio.run(a.rpc_team_switch(team="t", flow="lean", version=ts.version(before, "t")))
    assert settings_mod.load() == before and a._host_rec.get("teams") == {}


def test_a_switch_is_refused_while_another_is_under_way_and_over_a_newer_version(agent):
    a = agent(_body([]))
    a._host_rec = {"teams": {"t": {"switching": "other"}}}
    with pytest.raises(RpcError, match="already switching to other"):
        asyncio.run(a.rpc_team_switch(team="t", flow="lean", version=ts.version(settings_mod.load(), "t")))
    with pytest.raises(RpcError, match="stale|reload"):
        asyncio.run(a.rpc_team_switch(team="t", flow="lean", version="stale"))


def test_a_switch_waits_out_a_stage_pass_already_running(agent):
    order = []
    a = agent(SimpleNamespace(switch_push=lambda **_kw: order.append("push") or ["build"], node_flow_paths=HERE))

    async def go():
        async def pass_():
            await asyncio.sleep(0.05)
            order.append("pass ended")

        a._stage_task = asyncio.create_task(pass_())
        await a.rpc_team_switch(team="t", flow="lean", version=ts.version(settings_mod.load(), "t"))

    asyncio.run(go())
    assert order == ["pass ended", "push"]


def test_a_restart_finishes_a_recorded_switch_and_clears_a_spent_mark(agent):
    seen = []
    a = agent(_body([], seen=seen))
    a._host_rec = {"teams": {"t": {"switching": "lean", "started": {"since": "x"}}}}
    asyncio.run(a._finish_switches())
    assert settings_mod.load()["teams"]["t"]["flow"] == "lean" and seen[0]["check"] is False
    assert a._host_rec["teams"]["t"] == {"started": {"since": "x"}}, "the team's other marks stand"
    a._host_rec["teams"]["t"]["switching"] = "lean"  # the key was written before the restart: only the mark is left
    asyncio.run(a._finish_switches())
    assert len(seen) == 1 and "switching" not in a._host_rec["teams"]["t"]


def test_a_switch_a_restart_cannot_finish_is_cleared(agent):
    a = agent(_body([], refuse=StateRefused("protected branch")))
    a._host_rec = {"teams": {"t": {"switching": "lean"}, "gone": {"switching": "lean"}}}
    asyncio.run(a._finish_switches())
    assert a._host_rec["teams"] == {} and settings_mod.load()["teams"]["t"]["flow"] == "build"


def test_the_stage_pass_leaves_a_switching_team_alone():
    doc = {"teams": {"t": {"repo": "shiftlead"}, "u": {"repo": "shiftlead"}}}
    assert set(stage_teams(doc, {"t": {"switching": "lean"}})["shiftlead"]) == {"u"}


def test_the_preview_rpc_answers_the_pick_and_says_an_unread_branch(agent):
    def preview(**kw):
        raise OSError("origin away")

    a = agent(SimpleNamespace(choices=lambda *a: [{"name": "lean"}], switch_preview=preview, node_flow_paths=HERE))
    got = asyncio.run(a.rpc_team_switch_preview(team="t"))
    assert got["choices"] == [{"name": "lean"}] and got["version"] == ts.version(settings_mod.load(), "t")
    with pytest.raises(RpcError, match="no preview of t's switch: origin away"):
        asyncio.run(a.rpc_team_switch_preview(team="t", flow="lean"))


def test_a_live_session_of_the_team_is_named_in_every_form_a_holder_takes(agent):
    live = [SimpleNamespace(id="ao-t-1", team="t", state="working"), SimpleNamespace(id="x", team="u", state="working")]
    a = agent(SimpleNamespace(), live)
    assert set(a._team_live("t")) == {"ao-t-1", "ao-t-1@home"}


def test_a_mark_the_disk_refuses_is_not_kept_in_memory(agent):
    a = agent(_body([]))
    a._host_rec = {"teams": {"t": {"started": {"since": "x"}}}}

    def full(_rec):
        raise OSError("disk full")

    a.host_store = SimpleNamespace(save=full)
    with pytest.raises(RpcError, match="record could not be written"):
        asyncio.run(a.rpc_team_switch(team="t", flow="lean", version=ts.version(settings_mod.load(), "t")))
    assert a._host_rec["teams"] == {"t": {"started": {"since": "x"}}}, "the team is not left skipped by the pass"


def test_two_presses_at_once_make_one_switch(agent):
    pushes = []
    a = agent(_body(pushes))

    async def go():
        v = ts.version(settings_mod.load(), "t")
        return await asyncio.gather(
            a.rpc_team_switch(team="t", flow="lean", version=v),
            a.rpc_team_switch(team="t", flow="lean", version=v),
            return_exceptions=True,
        )

    got = asyncio.run(go())
    assert pushes == ["lean"] and sum(isinstance(g, RpcError) for g in got) == 1


def test_a_number_is_kept_only_for_a_stage_of_the_same_key_and_kind():
    assert team_show._keys(NEW, OLD) == ["build"], "docs is a review now, not a build: its number goes"
    assert team_show._keys(NEW, None) == ["build", "docs"]


def test_a_stopped_team_is_switched_and_no_session_is_ended(agent, on_store):
    """§4.9d: a stopped team may be switched; with no session of it live the preview says none is ended, every line
    says so, and the switch ends nothing — the records named holders whose sessions are gone."""
    _store, roots = on_store
    got = team_show.switch_preview(team="t", flow="lean", doc=_doc(), rows=ROWS, here="home", roots=roots, live=())
    assert got["none_ended"] and not any(x["ends"] or "lost" in x["line"] for x in got["records"])
    gone = [SimpleNamespace(id="ao-t-2", team="t", state="exited")]
    pushes, closed = [], []
    a = agent(_body(pushes), gone)
    a.rpc_close = lambda **kw: closed.append(kw)
    assert a._team_live("t") == [], "an exited session of the team is not live"
    asyncio.run(a.rpc_team_switch(team="t", flow="lean", version=ts.version(settings_mod.load(), "t")))
    assert pushes == ["lean"] and settings_mod.load()["teams"]["t"]["flow"] == "lean" and not closed
