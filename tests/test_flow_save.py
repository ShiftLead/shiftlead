"""Saving a flow from the Flows page (design §4.9c *The Flows page*, *A switch or a rename re-keys the records*,
TD-2054): the check, the versions, the built-ins, and what a save does to entries already in the flow."""

from __future__ import annotations

import pytest

from sessionorc import briefs
from shiftlead import flow3, flow_save
from shiftlead.flow_save import FlowError
from shiftlead.stagerecord import new_record


def _flow(name="mine", build="Build", review="Review", does="review"):
    key = flow3.key_of(build)
    outcomes = f"ship: {{to: merge, refused: {{to: {key}, limit: 3}}}}\n    changes-wanted: {{to: {key}, limit: 3}}"
    if does != "review":
        outcomes = "work-pushed: person"
    return f"""format: 3
name: {name}
stages:
  - name: {build}
    does: build
    model: opus
    takes: any
    work-pushed: {flow3.key_of(review)}
  - name: {review}
    does: {does}
    model: sonnet
    {outcomes}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(flow3, "model_families", lambda: ("opus", "sonnet"))
    return tmp_path / "home"


class _Store:
    """One repo's records in memory."""

    repos: dict = {}

    def __init__(self, root):
        self.root = root
        self.rows = self.repos.setdefault(str(root), {})

    def entries(self):
        return {k: dict(v) for k, v in self.rows.items()}

    def locked(self):
        import threading

        return threading.RLock()

    @staticmethod
    def _entry_path(tid):
        return tid

    def write(self, changes, _message):
        import json

        for tid, text in changes.items():
            self.rows[tid] = json.loads(text)


@pytest.fixture
def records(monkeypatch):
    _Store.repos = {}
    monkeypatch.setattr(flow_save, "StageStore", _Store)
    return _Store.repos


def test_a_new_flow_is_saved_and_passes_the_check(home):
    got = flow_save.save("mine", _flow())
    path = home / "flows" / "mine" / "flow.yml"
    assert got == {"name": "mine", "version": briefs.version_of(path.read_text()), "moved": 0}
    assert flow3.check_file(path).usable


def test_a_flow_that_fails_the_check_is_not_written(home):
    with pytest.raises(FlowError, match="takes|stage"):
        flow_save.save("mine", _flow().replace("    takes: any\n", ""))
    assert not (home / "flows" / "mine").exists()


@pytest.mark.parametrize("name", ["build", "design-wise", "build-review"])
def test_a_built_ins_name_is_refused(home, name):
    with pytest.raises(FlowError, match="built-in"):
        flow_save.save(name, _flow(name=name))


def test_the_name_inside_the_file_is_the_directory(home):
    with pytest.raises(FlowError, match="must be mine"):
        flow_save.save("mine", _flow(name="other"))


def test_a_stale_version_and_a_second_new_flow_are_refused(home):
    flow_save.save("mine", _flow())
    with pytest.raises(FlowError, match="already exists"):
        flow_save.save("mine", _flow())
    with pytest.raises(FlowError, match="reload"):
        flow_save.save("mine", _flow(), version="0" * 16)


def test_a_first_shape_flow_is_never_overwritten(home):
    path = home / "flows" / "mine" / "flow.yml"
    path.parent.mkdir(parents=True)
    path.write_text("name: mine\nstages: []\n")
    with pytest.raises(FlowError, match="first-shape"):
        flow_save.save("mine", _flow(), version=briefs.version_of(path.read_text()))
    assert path.read_text() == "name: mine\nstages: []\n"


def test_a_rename_moves_every_trace_of_the_stage_on_open_records_and_only_those(home, records):
    v = flow_save.save("mine", _flow())["version"]
    rec = new_record("TD-1", "mine", "review", holder="s")
    rec["counts"] = {"review:changes-wanted": 2, "build:work-pushed": 1}
    rec["verdicts"] = {"review": {"head": "a", "stage": "review", "outcome": "ship"}}
    rec["history"] = [{"from": "build", "to": "review", "outcome": "work-pushed"}]
    rec["blocked"] = {"to": "review", "count": "review:changes-wanted"}
    rec["intent"] = {"answers": {"Back — a session takes it back": "review"}}
    closed = {**new_record("TD-2", "mine", "review"), "closed_at": "2026-11-01T00:00:00Z"}
    other = new_record("TD-3", "another", "review")
    records["/r"] = {"TD-1": rec, "TD-2": closed, "TD-3": other}
    got = flow_save.save("mine", _flow(review="Check"), version=v, renames={"review": "check"}, roots=["/r"])
    assert got["moved"] == 1
    new = records["/r"]["TD-1"]
    assert new["stage"] == "check"
    assert new["counts"] == {"check:changes-wanted": 2, "build:work-pushed": 1}
    assert new["verdicts"] == {"check": {"head": "a", "stage": "check", "outcome": "ship"}}
    assert new["history"][0]["to"] == "check"
    assert new["blocked"] == {"to": "check", "count": "check:changes-wanted"}
    assert new["intent"]["answers"] == {"Back — a session takes it back": "check"}
    assert records["/r"]["TD-2"]["stage"] == "review"
    assert records["/r"]["TD-3"]["stage"] == "review"


def test_removing_a_stage_that_holds_entries_is_refused_naming_them(home, records):
    v = flow_save.save("mine", _flow())["version"]
    records["/r"] = {"TD-1": new_record("TD-1", "mine", "review")}
    before = (home / "flows" / "mine" / "flow.yml").read_text()
    with pytest.raises(FlowError, match="review still holds TD-1: it cannot be deleted"):
        flow_save.save("mine", _flow(review="Check"), version=v, roots=["/r"])
    assert (home / "flows" / "mine" / "flow.yml").read_text() == before


def test_changing_a_stages_kind_while_it_holds_entries_is_refused(home, records):
    v = flow_save.save("mine", _flow())["version"]
    records["/r"] = {"TD-1": new_record("TD-1", "mine", "review")}
    with pytest.raises(FlowError, match="its kind cannot change"):
        flow_save.save("mine", _flow(does="design"), version=v, roots=["/r"])


@pytest.mark.parametrize(
    "renames", [{"nope": "check"}, {"review": "nope"}, {"build": "check", "review": "check"}, "review"]
)
def test_a_rename_that_does_not_match_the_save_is_refused(home, records, renames):
    v = flow_save.save("mine", _flow())["version"]
    with pytest.raises(FlowError):
        flow_save.save("mine", _flow(review="Check"), version=v, renames=renames, roots=["/r"])


def test_delete_is_refused_while_a_team_runs_it_and_needs_the_version(home):
    v = flow_save.save("mine", _flow())["version"]
    with pytest.raises(FlowError, match="run by alpha"):
        flow_save.delete("mine", v, running=["alpha"])
    with pytest.raises(FlowError, match="reload"):
        flow_save.delete("mine", "0" * 16)
    assert flow_save.delete("mine", v) == {"name": "mine", "deleted": True}
    assert not (home / "flows" / "mine").exists()


def _call(**kw):
    return flow_save.call(
        **{"name": "mine", "text": "", "version": None, "renames": None, "delete": False, "roots": [], **kw}
    )


def test_the_rpc_body_answers_a_refusal_in_words_and_skips_a_repo_whose_checkout_is_gone(home, tmp_path):
    assert "format: 3" in _call(text="name: mine\n")["refused"]
    assert "format: 3" in _call(text="a: [unclosed")["refused"]
    got = _call(text=_flow(), roots=[tmp_path / "gone"])
    assert got["name"] == "mine" and got["moved"] == 0


def test_the_rpc_body_refuses_a_delete_while_a_team_runs_the_flow(home, monkeypatch):
    v = _call(text=_flow())["version"]
    monkeypatch.setattr(flow_save, "running", lambda name, roots: ["alpha"])
    assert "run by alpha" in _call(delete=True, version=v)["refused"]
    monkeypatch.setattr(flow_save, "running", lambda name, roots: [])
    assert _call(delete=True, version=v) == {"name": "mine", "deleted": True}


def test_a_delete_is_refused_when_the_org_cannot_be_read(home, monkeypatch):
    v = _call(text=_flow())["version"]

    def broken(name, roots):
        raise ValueError("org.yml: the top level must be a mapping")

    monkeypatch.setattr(flow_save, "running", broken)
    assert "org.yml" in _call(delete=True, version=v)["refused"]
    assert (home / "flows" / "mine").exists()
