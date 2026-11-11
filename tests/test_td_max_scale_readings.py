"""Rule 14's readings of a worker extra (design §6 rule 14 *Scale with the work*, §4.4 *Team shape*; td-max,
TD-1546 slice 3): the shape samples a live extra as a member of its line's stage and never a held one; a live
extra that declared out of work while its PR waits on the reader reads *waiting on <reader>: #n*, the team neither
finished nor wound down; and a team whose kept members and live extras have declared, its extras held, winds down."""

from __future__ import annotations

from test_finished import OUT, _held, _manager
from test_finished import _rec as _member
from test_shape import NOW, _add, _entry, _team, _today

from sessionorc import work
from sessionorc.models import ProgressEntry

EXTRA = {"line": "g"}


async def test_the_shape_samples_a_live_extra_in_its_lines_stage_and_never_a_held_one(agent, tmp_path):
    from conftest import park_ticks
    from test_shape import _rec

    await park_ticks(agent)
    mgr, g1 = _team(agent, str(tmp_path / "repo"), [_entry("TD-1"), _entry("TD-2")])
    live = _rec("g1-4", lane=["free-pick"], repo=g1.repo, controllers=[mgr.id], scale={"line": "g1"})
    live.progress = [ProgressEntry(ref="TD-2")]
    held = _rec("g1-5", lane=["free-pick"], repo=g1.repo, controllers=[mgr.id], scale={"line": "g1"})
    held.state = "closed"
    _add(agent, live, held)
    assert agent._shape_pass(NOW) is True
    day = _today(agent)
    classes = {k: next(iter(v["minutes"])) for k, v in day["records"].items()}
    assert classes == {g1.id: "idle_with_work", live.id: "on_claim"}, (
        "the live extra is its line's; the held one no one's"
    )
    assert day["records"][live.id]["stage"] == day["records"][g1.id]["stage"]


def test_a_live_extra_out_of_work_with_its_pr_at_the_reader_reads_waiting_on_it():
    extra = _member("g-4", out_of_work=OUT, host="kmaster", scale=EXTRA)
    extra.progress = [ProgressEntry(ref="TD-9", review_pr=3389)]
    kept = _member("g-1", out_of_work=OUT, host="kmaster")
    team = [_manager(out_of_work=OUT), kept, extra, _held(extra, 3389)]
    got = work.finished(team, home="kmaster")
    assert got["why"] == ["g-4 waiting on techlead: #3389"] and got["at"] is None, "neither finished"
    assert work.team_wound_down(team) is None, "a live extra keeps the team from reading wound down"
    # the PR merged and the reply read: the extra is back to held, and the team reads wound down
    extra.progress[0].status, extra.state = "done", "closed"
    for r in team:
        if r.name != "g-4":
            r.state = "closed"
    assert work.held_extra(extra)
    assert work.team_wound_down(team) == OUT["at"]


def test_a_team_winds_down_when_its_kept_members_and_live_extras_have_declared():
    kept = _member("g-1", out_of_work=OUT)
    live = _member("g-4", out_of_work=OUT, scale=EXTRA)
    never = _member("g-5", "closed", scale=EXTRA)  # held, never filled: declared nothing
    got = work.finished([_manager(), kept, live, never])
    assert got is not None and got["why"] == [] and got["at"] == OUT["at"]
    undeclared = _member("g-6", scale=EXTRA)  # a live extra that has not declared keeps it running
    assert work.finished([_manager(), kept, live, never, undeclared])["why"] == ["g-6 idle, not declared"]
