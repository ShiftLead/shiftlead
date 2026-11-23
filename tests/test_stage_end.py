"""`ao stage end` (design §4.9c, §4.7, TD-2050): each outcome refused when its fact does not hold and taken when it
does, one holder, a repeat answered with where the entry went, and limits and the cap going to the person."""

from __future__ import annotations

import asyncio
import importlib
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from sessionorc import agent_stage, modes
from sessionorc.agent_common import RpcError
from shiftlead import stage_end
from shiftlead.stage_end import PullRequest, Refused, end, names_entry
from shiftlead.stagerecord import new_record

ME = "ao-repo-build-td-7"
HEAD = "a" * 40
FLOW = {
    "format": 3,
    "name": "t",
    "max-moves": 25,
    "stages": [
        {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": "review"},
        {
            "name": "Review",
            "does": "review",
            "model": "sonnet",
            "ship": {"to": "merge", "refused": {"to": "build", "limit": 3}},
            "changes-wanted": {"to": "build", "limit": 3},
        },
    ],
}


class Store:
    """The record in memory: the git store is `test_stagerecord`'s."""

    def __init__(self, record):
        self.record = record
        self.intent = None
        self.writes = 0

    def locked(self):
        import threading

        return threading.RLock()

    def entry(self, _tid):
        import copy

        return copy.deepcopy(self.record)

    def put_entry(self, record, _why):
        self.record = record
        self.writes += 1

    def record_intent(self, tid, person, ask, context, answers, *, blocked=None, base=None):
        base["intent"] = {"person": person, "ask": ask, "context": context, "answers": dict(answers)}
        base["blocked"] = blocked
        self.put_entry(base, "intent")
        self.intent = base["intent"]
        return base


@dataclass
class Fake:
    pr: PullRequest | None = None
    local: str = HEAD
    fetched: str = HEAD
    on: str = "td7-thing"
    posted: list = field(default_factory=list)

    def branch(self):
        return self.on

    def worktree_head(self):
        return self.local

    def fetched_head(self, _branch):
        return self.fetched

    def pull_request(self, _branch, _number):
        return self.pr

    def post_review(self, number, body):
        self.posted.append((number, body))


def _pr(**kw) -> PullRequest:
    base = {
        "number": 9,
        "head": HEAD,
        "branch": "td7-thing",
        "state": "OPEN",
        "fork": False,
        "precheck": True,
        "files": ("src/x.py", "docs/ledger/archive/TD-7.md"),
    }
    return PullRequest(**{**base, **kw})


def _store(stage="build", **kw) -> Store:
    return Store({**new_record("TD-7", "t", stage, holder=ME), **kw})


def _end(store, outcome, reason="", facts=None, doc=FLOW, caller=ME):
    return end(store, "TD-7", caller, outcome, reason, doc, facts or Fake(_pr()), "paul")


def test_work_pushed_is_taken_and_writes_the_branch_and_pull_request():
    store = _store()
    got = _end(store, "work-pushed")
    assert got == {"entry": "TD-7", "outcome": "work-pushed", "went": "review", "repeat": False}
    r = store.record
    assert (r["stage"], r["holder"], r["branch"], r["pr"], r["moves"]) == ("review", None, "td7-thing", 9, 1)
    assert r["counts"] == {"build:work-pushed": 1} and r["history"][-1]["by"] == ME


@pytest.mark.parametrize(
    ("facts", "words"),
    [
        (Fake(None), "no open pull request"),
        (Fake(_pr(), local="b" * 40), "push your work"),
        (Fake(_pr(precheck=False)), "precheck"),
        (Fake(_pr(files=("src/x.py",))), "does not archive"),
        (Fake(_pr(state="CLOSED")), "not open"),
        (Fake(_pr(fork=True)), "not open"),
        (Fake(_pr(), on="some-branch"), "does not name"),
    ],
)
def test_work_pushed_is_refused_when_its_fact_does_not_hold(facts, words):
    store = _store()
    with pytest.raises(Refused, match=words):
        _end(store, "work-pushed", facts=facts)
    assert store.writes == 0 and store.record["holder"] == ME


def test_a_build_whose_next_is_a_build_may_end_red_and_unarchived():
    doc = {
        **FLOW,
        "stages": [
            {"name": "Tests", "does": "build", "model": "opus", "takes": "any", "work-pushed": "build"},
            {"name": "Build", "does": "build", "model": "opus", "work-pushed": "person"},
        ],
    }
    store = _store("tests")
    assert _end(store, "work-pushed", facts=Fake(_pr(precheck=False, files=())), doc=doc)["went"] == "build"


def test_ship_records_the_verdict_posts_the_comment_and_marks_merging():
    store = _store("review", branch="td7-thing", pr=9)
    facts = Fake(_pr())
    assert _end(store, "ship", facts=facts)["went"] == "merge"
    r = store.record
    assert r["waits"] == "merging" and r["merging"] == {"head": HEAD, "stage": "review", "outcome": "ship"}
    assert r["verdicts"]["review"] == {"head": HEAD, "stage": "review", "outcome": "ship"}
    assert facts.posted[0][1].startswith("cadence-review: SHIP · sonnet · code · 0 findings")


def test_ship_is_refused_when_the_head_moved_since_it_was_read():
    store = _store("review", branch="td7-thing", pr=9)
    facts = Fake(_pr(), fetched="c" * 40)
    with pytest.raises(Refused, match="read again"):
        _end(store, "ship", facts=facts)
    assert not facts.posted and store.writes == 0


def test_changes_wanted_needs_a_reason_and_posts_a_block():
    store = _store("review", branch="td7-thing", pr=9)
    with pytest.raises(Refused, match="needs --reason"):
        _end(store, "changes-wanted")
    facts = Fake(_pr())
    assert _end(store, "changes-wanted", "the test is wrong", facts=facts)["went"] == "build"
    assert facts.posted[0][1].startswith("cadence-review: BLOCK · sonnet · code · 1 findings")
    assert "the test is wrong" in facts.posted[0][1]


@pytest.mark.parametrize("outcome", ["not-needed", "design-needs-changing", "other"])
def test_a_reasoned_outcome_needs_its_reason(outcome):
    with pytest.raises(Refused, match="needs --reason"):
        _end(_store(), outcome)


def test_an_outcome_of_another_kind_is_refused():
    with pytest.raises(Refused, match="not an outcome of a build stage"):
        _end(_store(), "ship")
    with pytest.raises(Refused, match="not an outcome"):
        _end(_store(), "nothing-found", "x")


def test_a_call_from_a_session_that_is_not_the_holder_is_refused():
    store = _store()
    with pytest.raises(Refused, match="this entry is not yours"):
        _end(store, "work-pushed", caller="someone-else")
    assert store.writes == 0


def test_a_repeated_call_is_answered_with_where_the_entry_went():
    store = _store()
    _end(store, "work-pushed")
    writes = store.writes
    got = _end(store, "work-pushed")
    assert got["repeat"] is True and got["went"] == "review" and store.writes == writes


def test_a_limits_fourth_move_goes_to_the_person_with_carry_on():
    store = _store("review", branch="td7-thing", pr=9, counts={"review:changes-wanted": 3}, moves=6)
    got = _end(store, "changes-wanted", "still wrong", facts=Fake(_pr()))
    assert got["went"] == "person"
    r = store.record
    assert r["stage"] == "review" and r["moves"] == 6
    assert r["blocked"] == {"to": "build", "count": "review:changes-wanted"}
    assert store.intent["answers"][stage_end.CARRY_ON] == {"blocked": True}


def test_the_26th_move_at_a_cap_of_25_goes_to_the_person():
    store = _store(moves=25)
    assert _end(store, "work-pushed")["went"] == "person"
    assert store.record["blocked"]["cap"] is True and store.record["moves"] == 25
    store = _store(moves=24)
    assert _end(store, "work-pushed")["went"] == "review" and store.record["moves"] == 25


def test_not_needed_offers_archive_and_build_it_anyway():
    store = _store()
    assert _end(store, "not-needed", "already done")["went"] == "person"
    answers = store.intent["answers"]
    assert answers[stage_end.ARCHIVE] == {"archive": True} and answers[stage_end.BUILD_ANYWAY] == "build"
    assert store.intent["context"] == "already done"


@pytest.mark.parametrize(
    ("branch", "held"),
    [("td7-thing", True), ("TD-7-x", True), ("td-007", True), ("td70-x", False), ("td7-td8", False), ("x", False)],
)
def test_a_branch_names_its_entry_alone(branch, held):
    assert names_entry(branch, "TD-7") is held


# -- the host agent's layer ------------------------------------------------------------------------------------------


class _Session:
    id = ME
    host = "here"
    repo = "/repo"
    dir = "/repo/wt"
    team = "t"
    lane: ClassVar[list[str]] = ["TD-7"]
    progress: ClassVar[list] = []


class _Agent(agent_stage.StageMixin):
    host = "here"

    def __init__(self, s=None):
        self.s = s or _Session()

    def _find(self, _sid):
        return self.s

    def _is_self(self, s, caller):
        return caller == s.id


def test_only_the_session_itself_ends_its_stage(monkeypatch):
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: pytest.fail("the body was reached"))
    with pytest.raises(RpcError, match="not yours"):
        asyncio.run(_Agent().rpc_stage_end(ME, "work-pushed", caller="someone-else"))


def test_a_session_on_a_node_is_refused_until_the_home_can_read_its_worktree(monkeypatch):
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: pytest.fail("the body was reached"))
    s = _Session()
    s.host = "node"
    with pytest.raises(RpcError, match="runs on node"):
        asyncio.run(_Agent(s).rpc_stage_end(ME, "work-pushed", caller=ME))


def test_a_refusal_from_the_body_is_the_calls_error(monkeypatch):
    body = SimpleNamespace(call=lambda **_kw: {"refused": "the precheck is not green"})
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: body)
    with pytest.raises(RpcError, match="precheck"):
        asyncio.run(_Agent().rpc_stage_end(ME, "work-pushed", caller=ME))


def test_a_stage_module_that_will_not_load_refuses_the_call_and_nothing_more(monkeypatch):
    def broken():
        raise ImportError("no")

    ep = SimpleNamespace(name=agent_stage.NAME, load=broken)
    monkeypatch.setattr(agent_stage, "entry_points", lambda group: [ep] if group == agent_stage.GROUP else [])
    with pytest.raises(RpcError, match="could not be loaded"):
        agent_stage.stage_calls()
    monkeypatch.setattr(agent_stage, "entry_points", lambda group: [])
    with pytest.raises(RpcError, match="no shiftlead.home_calls"):
        agent_stage.stage_calls()


def test_every_home_call_in_pyproject_resolves():
    data = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    group = data["project"]["entry-points"][agent_stage.GROUP]
    assert agent_stage.NAME in group
    for target in group.values():
        module = importlib.import_module(target)
        assert callable(module.call) and callable(module.show)


def test_a_stage_end_is_refused_offline_and_its_show_too():
    for method in ("stage_end", "stage_show"):
        said = modes.offline_refusal(method, ME, {"id": ME}, host="node", home="home", records={})
        assert said and "unreachable" in said
    assert "stage_end" not in modes.PERSON_NODE_BOUND


def test_the_forge_facts_read_one_open_pull_request_of_this_repo(monkeypatch):
    row = {
        "number": 9,
        "headRefOid": HEAD,
        "headRefName": "td7-thing",
        "state": "OPEN",
        "isCrossRepository": False,
        "statusCheckRollup": [{"context": "cadence/precheck", "state": "SUCCESS"}],
        "files": [{"path": "docs/ledger/archive/TD-7.md"}],
    }
    fork = {**row, "number": 10, "isCrossRepository": True}
    facts = stage_end.ForgeFacts("/nowhere")
    monkeypatch.setattr(facts, "_gh", lambda *_a: json.dumps([row, fork]))
    pr = facts.pull_request("td7-thing", None)
    assert (pr.number, pr.precheck, pr.files) == (9, True, ("docs/ledger/archive/TD-7.md",))
    monkeypatch.setattr(facts, "_gh", lambda *_a: json.dumps([{**row, "statusCheckRollup": []}]))
    assert facts.pull_request("td7-thing", None).precheck is False
    monkeypatch.setattr(facts, "_gh", lambda *_a: "[]")
    assert facts.pull_request("td7-thing", None) is None
