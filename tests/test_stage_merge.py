"""The home's merge of a record marked `merging` (design §4.9c *The merge gate under a flow*, TD-2051), on a real
`shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import pinned_script

from shiftlead import stage_merge
from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_end import TRY_AGAIN
from shiftlead.stage_make import make
from shiftlead.stage_merge import MERGING, NO_READING_FOR, gate_and_land, run
from shiftlead.stagerecord import StageStore, new_record

TID = "TD-7"
HEAD = "a" * 40
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
FLOW: dict[str, Any] = {
    "format": 3,
    "name": "f",
    "stages": [
        {"name": "build", "does": "build", "model": "m", "takes": "any", "work-pushed": "review"},
        {
            "name": "review",
            "does": "review",
            "model": "m",
            "ship": {"to": "merge", "refused": {"to": "build", "limit": 1}},
        },
        {"name": "plain", "does": "review", "model": "m", "ship": "merge"},
    ],
}
READ = Reading(pr_state="open", head=HEAD)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)


@pytest.fixture
def store(tmp_path: Path) -> StageStore:
    origin, root = tmp_path / "o.git", tmp_path / "r"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "commit", "-q", "--allow-empty", "-m", "init")
    git(root, "push", "-q", "origin", "main")
    s = StageStore(root)
    s.ensure_branch()
    return s


def put(store: StageStore, stage: str = "review", **over: Any) -> None:
    merging = {"head": HEAD, "stage": stage, "outcome": "ship"}
    store.put_entry({**new_record(TID, "f", stage), "pr": 4, "waits": "merging", "merging": merging, **over}, "test")


def go(store: StageStore, got: Any, s: Reading = READ, land: Any = None, now: datetime = NOW) -> Any:
    landed: list[tuple[int, str]] = []

    def default(pr: int, head: str) -> None:
        landed.append((pr, head))

    made = run(store, TID, MERGING, s, FLOW, "paul", lambda _p, _h: got, land or default, now)
    return made, landed


def test_a_passing_gate_merges_that_head_and_leaves_the_close_to_reconcile(store):
    put(store)
    made, landed = go(store, {"verdict": "pass", "failed": []})
    assert made.made and landed == [(4, HEAD)]
    assert store.entry(TID)["waits"] == "merging"
    assert choose(store.entry(TID), Reading(entry="archived", pr_state="merged")) == Act("reconcile", "close")


def test_a_row_a_session_can_cure_takes_the_refused_move_and_counts_it(store):
    put(store)
    made, landed = go(store, {"verdict": "fail", "failed": ["ci"]})
    r = store.entry(TID)
    assert made.made and not landed
    assert (r["stage"], r["waits"], r["merging"]) == ("build", None, None)
    assert r["counts"]["review:refused"] == 1 and r["history"][-1]["by"] == "home"


def test_a_refused_live_check_goes_back_to_its_stage_on_its_one_refused_count_and_keeps_its_mark(store):
    merging = {"head": HEAD, "stage": "build", "outcome": "check-waits"}
    put(store, stage="build", merging=merging, check_waits=4, counts={"build:refused": 2})
    made, landed = go(store, {"verdict": "fail", "failed": ["ci"]})
    r = store.entry(TID)
    assert made.made and not landed
    assert (r["stage"], r["waits"], r["counts"]["build:refused"], r["check_waits"]) == ("build", None, 3, 4)
    put(store, stage="build", merging=merging, check_waits=4, counts={"build:refused": 3})  # the fourth: the person
    made, _ = go(store, {"verdict": "fail", "failed": ["ci"]})
    r = store.entry(TID)
    assert made.made and r["intent"] and r["blocked"]["count"] == "build:refused" and r["check_waits"] == 4


def test_the_refused_move_names_the_failing_row_in_its_reason(store):
    put(store)
    go(store, {"verdict": "fail", "failed": ["ci", "board"]})
    step = store.entry(TID)["history"][-1]
    assert (step["outcome"], step["to"], step["reason"]) == ("refused", "build", "the merge gate failed on ci, board")


@pytest.mark.parametrize("failed", [["ci", "a-row-a-later-pin-adds"], []])
def test_a_failed_row_no_list_sorts_goes_to_the_person_and_spends_no_limit(store, failed):
    put(store)
    made, landed = go(store, {"verdict": "fail", "failed": failed})
    r = store.entry(TID)
    assert made.made and not landed and r["intent"]["answers"][TRY_AGAIN] == {"merge": True}
    assert not r.get("counts") and r["stage"] == "review"


def test_every_row_the_pinned_gate_writes_is_sorted_once():
    rows = set(re.findall(r'\brow\(\s*"([a-z_-]+)"', pinned_script("check_cadence.py").read_text(encoding="utf-8")))
    assert rows, "the pinned gate's rows were not found"
    assert not stage_merge.PERSON_ROWS & stage_merge.SESSION_ROWS
    assert rows <= stage_merge.PERSON_ROWS | stage_merge.SESSION_ROWS, rows - stage_merge.SESSION_ROWS


def test_a_refused_move_past_its_limit_goes_to_the_person(store):
    put(store, counts={"review:refused": 1})
    made, _ = go(store, {"verdict": "fail", "failed": ["review"]})
    r = store.entry(TID)
    assert made.made and r["intent"] and r["blocked"]["count"] == "review:refused" and r["stage"] == "review"


def test_a_refused_move_unwritten_goes_to_the_person(store):
    put(store, stage="plain")
    made, _ = go(store, {"verdict": "fail", "failed": ["ci"]})
    assert made.made and "refused" in store.entry(TID)["intent"]["ask"]


# -- after a switch (§4.9d *A record marked `merging` is not touched*, TD-2062) ---------------------------------------

SWITCHED: dict[str, Any] = {
    **FLOW,
    "name": "g",
    "stages": [
        {"name": "build", "does": "build", "model": "m", "takes": "any", "work-pushed": "review"},
        {"name": "fix", "does": "build", "model": "m", "work-pushed": "review"},
        {"name": "review", "does": "review", "model": "m", "ship": {"to": "merge", "refused": "fix"}},
    ],
}


def _after_switch(store: StageStore, got: Any, doc: dict[str, Any], s: Reading = READ) -> Any:
    return run(store, TID, MERGING, s, doc, "paul", lambda _p, _h: got, lambda _p, _h: None, NOW)


def test_a_merge_under_way_is_taken_by_the_merge_gate_after_a_switch(store):
    put(store)  # written under f; the team now runs g, which keeps review as a review
    before = store.entry(TID)
    s = Reading(pr_state="open", head=HEAD, flow_current=False)  # the record still names f
    assert choose(before, s) == MERGING, "not rewritten to the new flow while it merges"
    made = _after_switch(store, {"verdict": "pass", "failed": []}, SWITCHED, s)
    assert made.made and store.entry(TID) == before, "the merge finishes as it would have"


def test_a_merge_refused_after_a_switch_takes_the_new_flows_refused_move(store):
    put(store)
    s = Reading(pr_state="open", head=HEAD, flow_current=False)
    made = _after_switch(store, {"verdict": "fail", "failed": ["ci"]}, SWITCHED, s)
    r = store.entry(TID)
    assert made.made and (r["stage"], r["waits"]) == ("fix", None), "g's refused move, not f's back to build"


@pytest.mark.parametrize(
    "doc, known",
    [({**SWITCHED, "stages": SWITCHED["stages"][:2]}, True), (SWITCHED, False)],
    ids=["no-such-key", "another-kind"],
)
def test_a_merge_refused_after_a_switch_that_lost_its_stage_goes_to_the_person(store, doc, known):
    put(store)
    s = Reading(pr_state="open", head=HEAD, flow_current=False, stage_known=known)
    made = _after_switch(store, {"verdict": "fail", "failed": ["ci"]}, doc, s)
    r = store.entry(TID)
    assert made.made and r["stage"] == "review" and "refused" in r["intent"]["context"] and not r.get("counts")


def test_a_moved_head_is_refused_without_running_the_gate(store):
    put(store)
    ran: list[int] = []
    s = Reading(pr_state="open", head="b" * 40)
    made = run(store, TID, MERGING, s, FLOW, "paul", lambda p, _h: ran.append(p), lambda _p, _h: None, NOW)
    assert made.made and not ran and store.entry(TID)["stage"] == "build"


@pytest.mark.parametrize("row", ["reach", "person"])
def test_a_row_only_a_person_can_cure_asks_with_try_again_and_spends_no_limit(store, row):
    put(store)
    made, landed = go(store, {"verdict": "fail", "failed": ["ci", row]})
    r = store.entry(TID)
    assert made.made and not landed and r["intent"]["answers"][TRY_AGAIN] == {"merge": True}
    assert not r.get("counts") and r["stage"] == "review" and r["merging"]["head"] == HEAD


def test_try_the_merge_again_marks_the_record_merging_at_its_head(store):
    put(store, waits="person", answers={TRY_AGAIN: {"merge": True}})
    r = store.entry(TID)
    r["merging"]["unread_since"] = "2026-11-23T10:00:00Z"
    store.put_entry(r, "test")
    s = Reading(gate=False, lifted=TRY_AGAIN, pr_state="open", head=HEAD)
    assert make(store, TID, Act("answer"), s, FLOW, "paul").made
    got = store.entry(TID)
    assert got["waits"] == "merging" and got["merging"] == {"head": HEAD, "stage": "review", "outcome": "ship"}


@pytest.mark.parametrize("got", [None, {"verdict": "unknown", "failed": []}])
def test_no_reading_stays_merging_and_goes_to_the_person_after_an_hour(store, got):
    put(store)
    made, _ = go(store, got)
    r = store.entry(TID)
    assert not made.made and r["waits"] == "merging" and r["merging"]["unread_since"] == "2026-11-23T12:00:00Z"
    made, _ = go(store, got, now=NOW + NO_READING_FOR - timedelta(seconds=1))
    assert not made.made and not store.entry(TID).get("intent")
    made, _ = go(store, got, now=NOW + NO_READING_FOR)
    r = store.entry(TID)
    assert made.made and r["intent"]["answers"][TRY_AGAIN] == {"merge": True} and not r.get("counts")


def test_a_gate_that_raises_is_no_reading(store):
    put(store)

    def boom(_p: int, _h: str) -> None:
        raise OSError("no gh")

    made = run(store, TID, MERGING, READ, FLOW, "paul", boom, lambda _p, _h: None, NOW)
    assert not made.made and "no gh" in made.why and store.entry(TID)["waits"] == "merging"


def test_a_merge_that_fails_stays_merging(store):
    put(store)
    made, _ = go(store, {"verdict": "pass", "failed": []}, land=lambda _p, _h: "conflict")
    assert not made.made and made.why == "conflict" and store.entry(TID)["merging"]["unread_since"]


def test_a_record_that_moved_during_the_gate_is_neither_merged_nor_written(store):
    put(store)
    landed: list[int] = []

    def gate(_p: int, _h: str) -> dict[str, Any]:
        r = store.entry(TID)
        r.update(waits=None, merging=None, stage="build")
        store.put_entry(r, "moved")
        return {"verdict": "pass", "failed": []}

    made = run(store, TID, MERGING, READ, FLOW, "paul", gate, lambda p, _h: landed.append(p), NOW)
    assert not made.made and not landed and store.entry(TID)["stage"] == "build"


def test_another_act_is_not_made(store):
    put(store)
    made, landed = None, []
    made = run(store, TID, Act("offer"), READ, FLOW, "paul", lambda _p, _h: None, lambda p, _h: landed.append(p), NOW)
    assert not made.made and not landed


# -- the real gate and merge -------------------------------------------------------------------------------


class Forge:
    """`cadence` and `sync` as `gate_and_land` calls them, recording the merge."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, composes: bool | None = True, sha: str = HEAD) -> None:
        self.verdict: dict[str, Any] | None = {"verdict": "pass", "failed": []}
        self.trailers: str | None = "Review: x\n"
        self.signed: list[str] = []
        self.merges: list[tuple[int, str, str | None, str | None]] = []
        self.sha = sha
        self.compose_why: str | None = None
        monkeypatch.setattr(
            stage_merge.cadence, "composes", lambda _root: (composes, None if composes is not None else "no tree")
        )
        monkeypatch.setattr(stage_merge.cadence, "check", self.check)
        monkeypatch.setattr(stage_merge.sync, "compose", self.compose)
        monkeypatch.setattr(stage_merge.sync, "merge", self.merge)

    def check(self, _root: Any, _pr: int, _timeout: float, trailers: Path | None = None) -> dict[str, Any] | None:
        if trailers is not None and self.trailers is not None:
            Path(trailers).write_text(self.trailers, encoding="utf-8")
        return self.verdict

    def compose(self, _root: Any, _pr: int, out: Path, *, merged_by: str) -> str | None:
        self.signed.append(merged_by)
        assert (out / "gate").read_text(encoding="utf-8") == self.trailers
        if self.compose_why:
            return self.compose_why
        for name, text in (("sha", self.sha + "\n"), ("subject", "the subject"), ("body", "the body")):
            (out / name).write_text(text, encoding="utf-8")
        return None

    def merge(
        self, _root: Any, pr: int, head: str, subject: str | None = None, body_file: Path | None = None
    ) -> str | None:
        body = Path(body_file).read_text(encoding="utf-8") if body_file is not None else None
        self.merges.append((pr, head, subject, body))
        return None


def test_a_passed_gate_lands_the_composed_squash_signed_by_the_home(monkeypatch, tmp_path):
    forge = Forge(monkeypatch)
    gate, land = gate_and_land(tmp_path)
    assert gate(5, HEAD) == forge.verdict
    assert land(5, HEAD) is None
    assert forge.signed == ["shiftlead-home"]
    assert forge.merges == [(5, HEAD, "the subject", "the body")]


def test_a_pin_that_composes_no_squash_merges_bare(monkeypatch, tmp_path):
    forge = Forge(monkeypatch, composes=False)
    gate, land = gate_and_land(tmp_path)
    gate(5, HEAD)
    assert land(5, HEAD) is None
    assert forge.signed == [] and forge.merges == [(5, HEAD, None, None)]


def test_an_unread_tree_raises_so_the_run_reads_no_reading(monkeypatch, tmp_path):
    Forge(monkeypatch, composes=None)
    gate, _ = gate_and_land(tmp_path)
    with pytest.raises(RuntimeError, match="no tree"):
        gate(5, HEAD)


@pytest.mark.parametrize("verdict", [None, {"verdict": "fail", "failed": ["review"]}])
def test_nothing_lands_unless_the_gate_passed(monkeypatch, tmp_path, verdict):
    forge = Forge(monkeypatch)
    forge.verdict = verdict
    gate, land = gate_and_land(tmp_path)
    assert gate(5, HEAD) == verdict
    assert land(5, HEAD) == "the gate has not passed this head"
    assert forge.merges == []


def test_a_later_failed_gate_takes_back_the_earlier_pass(monkeypatch, tmp_path):
    forge = Forge(monkeypatch)
    gate, land = gate_and_land(tmp_path)
    gate(5, HEAD)
    forge.verdict = {"verdict": "fail", "failed": ["ci"]}
    gate(5, HEAD)
    assert land(5, HEAD) == "the gate has not passed this head"
    assert forge.merges == []


def test_a_pass_is_for_its_own_head_and_lands_once(monkeypatch, tmp_path):
    forge = Forge(monkeypatch)
    gate, land = gate_and_land(tmp_path)
    gate(5, HEAD)
    assert land(5, "b" * 40) == "the gate has not passed this head"
    assert land(5, HEAD) == "the gate has not passed this head"  # the mismatch spent the pass
    assert forge.merges == []


def test_a_squash_composed_for_another_head_is_not_merged(monkeypatch, tmp_path):
    forge = Forge(monkeypatch, sha="b" * 40)
    gate, land = gate_and_land(tmp_path)
    gate(5, HEAD)
    assert "composed for bbbbbbbbbbbb" in (land(5, HEAD) or "")
    assert forge.merges == []


def test_a_refused_compose_is_the_reason_and_merges_nothing(monkeypatch, tmp_path):
    forge = Forge(monkeypatch)
    forge.compose_why = "squash-message said no"
    gate, land = gate_and_land(tmp_path)
    gate(5, HEAD)
    assert land(5, HEAD) == "squash-message said no"
    assert forge.merges == []


def test_a_pass_with_no_trailer_file_raises(monkeypatch, tmp_path):
    forge = Forge(monkeypatch)
    forge.trailers = None
    gate, land = gate_and_land(tmp_path)
    with pytest.raises(OSError):
        gate(5, HEAD)
    assert land(5, HEAD) == "the gate has not passed this head"


def test_compose_signs_with_the_name_it_is_given():
    env = {"AGENT_NAME": "x", "AGENT_MODEL": "m", "AGENT_MODEL_FILE": "f", "PATH": "/bin"}
    assert stage_merge.sync.squash_env(env, "shiftlead-home") == {"AGENT_NAME": "shiftlead-home", "PATH": "/bin"}
    assert stage_merge.sync.squash_env(env)["AGENT_NAME"] == "shiftlead-sync"


# -- the merge gate's questions are rows (§4.9c *A question the home asks is a row*, TD-2158) ----------------------


def _unread(store: StageStore) -> Any:
    go(store, None)
    return go(store, None, now=NOW + NO_READING_FOR)[0]


@pytest.mark.parametrize(
    ("case", "stage", "ask"),
    [
        ("merge-person", "review", lambda st: go(st, {"verdict": "fail", "failed": ["ci", "person"]})[0]),
        ("merge-unread", "review", _unread),
        (
            "merge-stage-gone",
            "review",
            lambda st: _after_switch(
                st,
                {"verdict": "fail", "failed": ["ci"]},
                SWITCHED,
                Reading(pr_state="open", head=HEAD, flow_current=False, stage_known=False),
            ),
        ),
        ("merge-refused", "plain", lambda st: go(st, {"verdict": "fail", "failed": ["ci"]})[0]),
    ],
)
def test_each_merge_gate_question_writes_an_ask_row_with_no_run_in_its_intents_commit(store, case, stage, ask):
    put(store, stage=stage)
    assert ask(store).made
    r = store.entry(TID)
    *_, row = r["history"]
    assert r["intent"] and "run" not in row
    assert {k: row[k] for k in ("from", "to", "outcome", "by", "reason")} == {
        "from": stage,
        "to": "person",
        "outcome": "ask",
        "by": "home",
        "reason": case,
    }


def test_a_merge_gate_question_on_a_record_carrying_the_homes_gate_writes_no_row(store):
    put(store)
    s = Reading(pr_state="open", head=HEAD, gate=True)
    made, _ = go(store, {"verdict": "fail", "failed": ["ci", "person"]}, s)
    r = store.entry(TID)
    assert made.made and r["waits"] == "person" and not r.get("history")
