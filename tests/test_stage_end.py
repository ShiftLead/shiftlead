"""`ao stage end` (design §4.9c, §4.7, TD-2050): each outcome refused when its fact does not hold and taken when it
does, one holder, a repeat answered with where the entry went, and limits and the cap going to the person."""

from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from sessionorc import agent_stage, identity, modes
from sessionorc.agent_common import RpcError
from shiftlead import stage_end
from shiftlead.stage_end import PullRequest, Refused, end
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


def test_a_design_stage_whose_next_is_a_build_still_needs_a_green_precheck():
    doc = {
        **FLOW,
        "stages": [
            {"name": "Design", "does": "design", "model": "opus", "takes": "any", "work-pushed": "build"},
            {"name": "Build", "does": "build", "model": "opus", "work-pushed": "person"},
        ],
    }
    with pytest.raises(Refused, match="precheck"):
        _end(_store("design"), "work-pushed", facts=Fake(_pr(precheck=False)), doc=doc)


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
    [("td7-thing", True), ("TD-7-x", True), ("td-007", False), ("td70-x", False), ("td7-td8", False), ("x", False)],
)
def test_a_branch_names_its_entry_alone_by_the_match_the_offer_uses(branch, held):
    store = _store()
    facts = Fake(pr=_pr(branch=branch), on=branch)
    if held:
        assert _end(store, "work-pushed", facts=facts)["went"] == "review"
    else:
        with pytest.raises(Refused, match="does not name"):
            _end(store, "work-pushed", facts=facts)


def _git(cwd, *args):
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(cwd), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def test_a_siblings_push_does_not_move_what_a_reviewers_worktree_fetched(tmp_path):
    origin, builder, reviewer = tmp_path / "origin.git", tmp_path / "builder", tmp_path / "reviewer"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(builder))
    _git(builder, "checkout", "-q", "-b", "td-7")
    _git(builder, "commit", "-q", "--allow-empty", "-m", "A")
    a = _git(builder, "rev-parse", "HEAD")
    _git(builder, "push", "-q", "origin", "td-7")
    _git(builder, "worktree", "add", "-q", "--detach", str(reviewer), a)
    facts = stage_end.ForgeFacts(reviewer)
    assert facts.fetched_head("td-7") is None  # this worktree has fetched nothing yet
    _git(reviewer, "fetch", "-q", "origin")  # a plain fetch: its FETCH_HEAD has a line per branch
    assert facts.fetched_head("td-7") == a
    assert facts.fetched_head("td") is None
    _git(builder, "commit", "-q", "--allow-empty", "-m", "B")
    b = _git(builder, "rev-parse", "HEAD")
    _git(builder, "push", "-q", "origin", "td-7")
    assert _git(reviewer, "rev-parse", "refs/remotes/origin/td-7") == b  # the shared ref moved
    assert facts.fetched_head("td-7") == a


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

    def _address(self, s):
        return s.id


def test_only_the_session_itself_ends_its_stage(monkeypatch):
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: pytest.fail("the body was reached"))
    with pytest.raises(RpcError, match="not yours"):
        asyncio.run(_Agent().rpc_stage_end(ME, "work-pushed", caller="someone-else"))


class _NodeAgent(_Agent):
    """The home, with a node whose worktree reads as `reading` and a registry holding `/home-checkout`."""

    def __init__(self, s, reading):
        super().__init__(s)
        self.reading = reading
        self.asked: list = []
        self.reported: list = []

    def _address(self, s):
        return f"{s.id}@{s.host}"

    def _is_self(self, s, caller):
        return caller == self._address(s)

    async def _ask_node(self, host, method, **params):
        self.asked.append((host, method, params))
        return self.reading

    async def _ids_repo(self, want, _by):
        if want != "o/r":
            raise RpcError(f"no registered checkout has the origin {want!r}")
        return "/home-checkout", want, "r"

    async def rpc_progress(self, id, **kw):
        self.reported.append((id, kw))
        return {}


def _node_session():
    s = _Session()
    s.host = "node"
    s.repo, s.dir = "/node/repo", "/node/repo/wt"
    s.progress = [SimpleNamespace(ref="TD-7", status="claimed")]
    return s


NODE_READING = {"branch": "td7-x", "head": "a" * 40, "fetched": {"td7-x": "b" * 40}, "origin": "git@github.com:o/r.git"}


def test_a_session_on_a_node_ends_its_stage_with_its_own_worktrees_facts(monkeypatch):
    got = {}
    body = SimpleNamespace(call=lambda **kw: got.update(kw) or {"entry": "TD-7", "went": "review"})
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: body)
    agent = _NodeAgent(_node_session(), NODE_READING)
    asyncio.run(agent.rpc_stage_end(ME, "work-pushed", caller=f"{ME}@node"))
    assert agent.asked == [("node", "stage_worktree", {"dir": "/node/repo/wt"})]
    assert got["root"] == "/home-checkout" and got["seen"] == NODE_READING and got["caller"] == f"{ME}@node"
    assert agent.reported == [(f"{ME}@node", {"ref": "TD-7", "status": "done", "caller": f"{ME}@node"})]


def test_node_facts_are_the_nodes_reading_and_the_forge_is_asked_from_the_homes_checkout():
    facts = stage_end.NodeFacts("/home-checkout", NODE_READING)
    assert facts.branch() == "td7-x" and facts.worktree_head() == "a" * 40
    assert facts.fetched_head("td7-x") == "b" * 40 and facts.fetched_head("other") is None
    assert facts.directory == "/home-checkout"


def test_a_worktree_reading_holds_what_the_home_checks(tmp_path):
    work = tmp_path / "w"
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(work)]
    work.mkdir()
    for args in (["init", "-q", "-b", "td7-x"], ["commit", "-q", "--allow-empty", "-m", "c"]):
        subprocess.run([*git, *args], check=True)
    subprocess.run([*git, "remote", "add", "origin", "git@github.com:o/r.git"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    (work / ".git" / "FETCH_HEAD").write_text(f"{'c' * 40}\t\tbranch 'td7-x' of github.com:o/r\n", encoding="utf-8")
    assert stage_end.worktree_reading(str(work)) == {
        "branch": "td7-x",
        "head": head,
        "fetched": {"td7-x": "c" * 40},
        "origin": "git@github.com:o/r.git",
    }


@pytest.mark.parametrize(
    ("reading", "words"),
    [
        ({"refused": "the session's worktree could not be read: try again"}, "could not be read"),
        ({**NODE_READING, "origin": None}, "no origin"),
        ({**NODE_READING, "origin": "git@github.com:someone/else.git"}, "no registered checkout"),
        (None, "no reading"),
    ],
)
def test_a_node_session_the_home_cannot_place_is_refused_in_words(monkeypatch, reading, words):
    body = SimpleNamespace(call=lambda **_kw: pytest.fail("the body was reached"))
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: body)
    with pytest.raises(RpcError, match=words):
        asyncio.run(_NodeAgent(_node_session(), reading).rpc_stage_end(ME, "work-pushed", caller=f"{ME}@node"))


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
    assert agent_stage.FLOW in group
    for target in group.values():
        assert callable(importlib.import_module(target).call)
    assert callable(importlib.import_module(group[agent_stage.NAME]).show)


def test_stage_show_from_a_persons_shell_reads_the_named_entry_of_a_registered_repo(monkeypatch):
    seen = {}
    body = SimpleNamespace(show=lambda **kw: seen.update(kw) or {"id": kw["tid"]})
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: body)
    monkeypatch.setattr("sessionorc.agent._registered_checkout", lambda r: Path(r) if r == "/repo" else None)
    assert asyncio.run(_Agent().rpc_stage_show(entry="TD-7", repo="/repo")) == {"id": "TD-7"}
    assert seen == {"root": "/repo", "tid": "TD-7"}
    for kw in ({"entry": "TD-7", "repo": "/elsewhere"}, {"repo": "/repo"}):
        with pytest.raises(RpcError, match="registered repo"):
            asyncio.run(_Agent().rpc_stage_show(**kw))
    assert "stage_show" in identity.READS


def test_a_stage_end_is_refused_offline_and_its_show_too():
    for method in ("stage_end", "stage_show"):
        said = modes.offline_refusal(method, ME, {"id": ME}, host="node", home="home", records={})
        assert said and "unreachable" in said
    assert "stage_end" not in modes.PERSON_NODE_BOUND


def test_a_review_comment_is_skipped_only_when_it_is_the_latest(monkeypatch):
    facts = stage_end.ForgeFacts("/nowhere")
    calls: list[tuple] = []
    ship, block = "cadence-review: SHIP · a", "cadence-review: BLOCK · b"

    def gh(*args):
        calls.append(args)
        return json.dumps({"comments": [{"body": ship}, {"body": block}, {"body": "a remark"}]})

    monkeypatch.setattr(facts, "_gh", gh)
    facts.post_review(9, block)
    assert len(calls) == 1
    facts.post_review(9, ship)  # an earlier SHIP under a later BLOCK is posted again
    assert calls[-1][:3] == ("pr", "comment", "9")


def test_a_pull_request_of_a_hundred_files_is_read_from_its_diff(monkeypatch):
    facts = stage_end.ForgeFacts("/nowhere")
    monkeypatch.setattr(facts, "_gh", lambda *_a: "a.py\ndocs/ledger/archive/TD-7.md\n")
    row = {"number": 9, "files": [{"path": f"f{i}"} for i in range(stage_end.FILES_CAP)]}
    assert facts._files(row) == ("a.py", "docs/ledger/archive/TD-7.md")


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


@pytest.mark.parametrize("ref", ["board:1a2b3c4d", "pr:41", "audit:t/docs"])
def test_a_jobs_or_an_audits_session_ends_with_the_reference_it_holds_and_its_claim_released(monkeypatch, ref):
    got = {}
    body = SimpleNamespace(call=lambda **kw: got.update(kw) or {"entry": ref, "went": "done"})
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: body)
    s = _node_session()
    s.lane = [ref]
    s.progress = [SimpleNamespace(ref=ref, status="claimed")]
    agent = _NodeAgent(s, NODE_READING)
    asyncio.run(agent.rpc_stage_end(ME, "nothing-found", reason="looked", caller=f"{ME}@node"))
    assert got["tid"] == ref and got["outcome"] == "nothing-found" and got["reason"] == "looked"
    assert agent.reported == [(f"{ME}@node", {"ref": ref, "status": "done", "caller": f"{ME}@node"})]


@pytest.mark.parametrize("lane", [["board:xyz"], ["pr:0"], ["audit:t"], ["#41"], ["board:1a2b3c4d", "TD-7"], []])
def test_a_lane_holding_no_one_stage_job_or_audit_is_refused(monkeypatch, lane):
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: pytest.fail("the body was reached"))
    s = _Session()
    s.lane = lane
    with pytest.raises(RpcError, match="holds no stage"):
        asyncio.run(_Agent(s).rpc_stage_end(ME, "work-pushed", caller=ME))


def test_stage_show_reads_an_entrys_record_alone(monkeypatch):
    monkeypatch.setattr(agent_stage, "stage_calls", lambda: pytest.fail("the body was reached"))
    s = _Session()
    s.lane = ["audit:t/docs"]
    with pytest.raises(RpcError, match="holds no stage"):
        asyncio.run(_Agent(s).rpc_stage_show(ME))
