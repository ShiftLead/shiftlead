"""TD-1765 slice 3 (TD-704's design, §4.9c *A claim's chip is its stage*): a *TDs in motion* row's chip is the claim's
stage in the team's flow — rules 1–5, first that applies, after the stage-name gate — named and coloured by the flow."""

from __future__ import annotations

from shiftlead.flowdefs import Stage
from shiftlead.ui import app as ui
from shiftlead.ui import cards
from shiftlead.ui.org import motion_phases

TD = [
    Stage("design", "designer", ["design-first", "owner:designer"]),
    Stage("build", "grinder", ["free-pick", "owner:grinder"]),
    Stage("review", "techlead"),
]
TL = "ao-s-techlead-ao-1"


def reading(reads: dict | None = None, recent: list | None = None) -> dict:
    return {
        "name": "s",
        "root": "/r/s",
        "remote": "git@github.com:eye/s.git",
        "ledger": {"entries": [{"id": "TD-1", "title": "one", "priority": "medium"}]},
        "prs": {"open": [{"number": 9, "branch": "td1-x"}], "recent": recent or []},
        "pr_orders": {"reads": reads or {}},
    }


def g(sid: str = "g1", role: str = "grinder", ref: str = "TD-1", pr: int | None = 9, **kw) -> dict:
    return {
        "id": sid,
        "name": sid,
        "role": role,
        "team": "td",
        "repo": "/r/s",
        "unattended": True,
        "progress": [{"ref": ref, "status": "claimed", "pr": pr}],
        **kw,
    }


SEAT = {"id": TL, "name": "techlead-ao-1", "role": "techlead", "team": "td", "seat": "on-call"}


def ask(to: str, state: str, at: str, again: bool = False, verdict: str = "") -> dict:
    return {"id": f"m-{to}-{at}", "to": to, "at": at, "state": state, "verdict": verdict, "again": again}


def chips(members: list[dict], r: dict, stages=TD, fleet=(SEAT,), whats=None) -> list[tuple[str, str, str]]:
    rows = ui.motion_rows(members, r, {"/r/s": r}, stages, fleet, whats or {})
    return [(x["ref"], x["stage"], x["color"]) for x in rows]


def test_rule_3_a_seat_with_an_open_ask_reads_its_review_stage_and_rule_4_after_any_answer():
    assert chips([g()], reading()) == [("TD-1", "build", "blue")]  # rule 4: a PR nobody asked is its author's
    assert chips([g()], reading({"9": [ask(TL, "open", "1")]})) == [("TD-1", "review", "amber")]
    for done in ("answered", "closed", "expired"):  # any answer, whatever its verdict, or an unanswered close
        assert chips([g()], reading({"9": [ask(TL, done, "1", verdict="findings")]})) == [("TD-1", "build", "blue")]
    # a seat that holds no stage reads its role in grey; one whose record is gone, *reader*
    other = {**SEAT, "id": "ao-s-director-ao-1", "role": "director"}
    r = reading({"9": [ask("ao-s-director-ao-1", "open", "1")]})
    assert chips([g()], r, fleet=(SEAT, other)) == [("TD-1", "director", "")]
    assert chips([g()], reading({"9": [ask("ao-gone", "open", "1")]})) == [("TD-1", "reader", "")]
    # two open: the later stage in the flow's order; a staged seat before one that holds none
    fc = Stage("fact-check", "checker")
    seat2 = {**SEAT, "id": "ao-s-checker", "role": "checker"}
    flow = [*TD[:2], fc, TD[2]]
    r = reading({"9": [ask(TL, "open", "1"), ask("ao-s-checker", "open", "2")]})
    assert chips([g()], r, flow, (SEAT, seat2)) == [("TD-1", "review", "amber")]
    r = reading({"9": [ask("ao-s-director-ao-1", "open", "1"), ask("ao-s-checker", "open", "2")]})
    assert chips([g()], r, flow, (seat2, other)) == [("TD-1", "fact-check", "pink")]  # the first palette name free


def test_rule_2_the_person_has_the_pr_or_the_work():
    you = [("TD-1", "you", "")]
    assert chips([g()], reading({"9": [ask("person", "open", "1")]})) == you
    # answered without *again* while no other addressee's entry is newer: still the person's
    assert chips([g()], reading({"9": [ask(TL, "closed", "1"), ask("person", "answered", "2")]})) == you
    # *Ask the reader again* hands it back to the author; a newer ask to a seat reads that seat
    assert chips([g()], reading({"9": [ask("person", "answered", "2", again=True)]})) == [("TD-1", "build", "blue")]
    newer = reading({"9": [ask("person", "answered", "2"), ask(TL, "open", "3")]})
    assert chips([g()], newer) == [("TD-1", "review", "amber")]
    # the work: an open ask or steer of the holder's to the person about the reference, or about its PR
    assert chips([g(waits_on=["TD-1"])], reading()) == you
    assert chips([g(waits_on=["#9"])], reading()) == you
    assert chips([g(waits_on=["TD-2"])], reading()) == [("TD-1", "build", "blue")]
    # *you* reads the same with no flow at all
    assert chips([g(waits_on=["TD-1"])], reading(), stages=None) == you


def test_rule_1_a_closed_pr_reads_its_holders_stage_marked_never_you_or_a_reader():
    r = reading({"7": [ask("person", "open", "1"), ask(TL, "open", "2")]}, recent=[{"number": 7, "state": "merged"}])
    rows = ui.motion_rows([g(pr=7, waits_on=["#7"])], r, {"/r/s": r}, TD, (SEAT,), {})
    assert [(x["stage"], x["pr_state"]) for x in rows] == [("build", "merged")]


def test_rule_5_and_the_stage_name_gate():
    # a hunter outside the flow reads its role, grey, after the stages; *you* last
    ms = [g("h1", role="hunter", ref="TD-5", pr=None), g("g1", waits_on=["TD-1"]), g("g2", ref="TD-3", pr=None)]
    assert chips(ms, reading()) == [("TD-3", "build", "blue"), ("TD-5", "hunter", ""), ("TD-1", "you", "")]
    # a pending Apply that moves its lane, a rename, a sit-out: the stage name is not read, the role is
    old = dict(cards.FLOW_ACTS)
    try:
        cards.FLOW_ACTS.update({"g1": "relaunch"})
        assert chips([g()], reading(), whats={"g1": ["lane free-pick → design-first"]}) == [("TD-1", "grinder", "")]
        assert chips([g()], reading(), whats={"g1": ["stage build.md → b2.md", "profile a → b"]}) == [
            ("TD-1", "build", "blue")
        ]
        cards.FLOW_ACTS.update({"g1": "rename"})
        assert chips([g()], reading(), whats={}) == [("TD-1", "grinder", "")]
        # a member the flow has lost — left, or removed by a pending Apply — reads its role (TD-1779)
        for act in ("left", "removed"):
            cards.FLOW_ACTS.update({"g1": act})
            assert chips([g()], reading(), whats={}) == [("TD-1", "grinder", "")], act
        # …and a reader seat whose own stage name is not read reads its role
        cards.FLOW_ACTS.clear()
        cards.FLOW_ACTS.update({TL: "sit_out"})
        assert chips([g()], reading({"9": [ask(TL, "open", "1")]})) == [("TD-1", "techlead", "")]
    finally:
        cards.FLOW_ACTS.clear()
        cards.FLOW_ACTS.update(old)
    assert chips([g(sit_out=True)], reading()) == [("TD-1", "grinder", "")]
    assert chips([g(closed_for={"why": "sit_out"})], reading()) == [("TD-1", "grinder", "")]


def test_a_claims_pr_is_read_in_its_own_records_repo():
    # the team's repo has #9 merged; the member's own repo has #9 open with the techlead's ask: *review*, not closed
    team = {
        **reading(recent=[{"number": 9, "state": "merged"}]),
        "prs": {"open": [], "recent": [{"number": 9, "state": "merged"}]},
    }
    own = {**reading({"9": [ask(TL, "open", "1")]}), "root": "/r/b", "name": "b"}
    rows = ui.motion_rows([g(repo="/r/b")], team, {"/r/s": team, "/r/b": own}, TD, (SEAT,), {})
    assert [(x["stage"], x["pr_state"]) for x in rows] == [("review", "")]


def test_a_flows_written_color_and_the_heading_in_stage_order():
    flow = [TD[0], TD[1], Stage("fact-check", "checker", color="teal"), TD[2]]
    seat2 = {**SEAT, "id": "ao-s-checker", "role": "checker"}
    r = reading({"9": [ask("ao-s-checker", "open", "1")]})
    assert chips([g()], r, flow, (seat2,)) == [("TD-1", "fact-check", "teal")]
    ms = [g("g1"), g("d1", role="designer", ref="TD-2", pr=None), g("h", role="hunter", ref="TD-4", pr=None)]
    rows = ui.motion_rows(ms, reading(), {"/r/s": reading()}, TD, (SEAT,), {})
    assert motion_phases(rows) == [("design", 1), ("build", 1), ("hunter", 1)]
    s = {"motion": rows, "phases": motion_phases(rows), "n_refs": 3, "phase_w": 6, "ref_w": 4, "who_w": 2}
    html = ui.templates.get_template("team_summary.html").render(
        g={"team": "td", "summary": {**s, "drawn": ["motion"]}}
    )
    assert "TDs in motion (3)" in html and "1 design · 1 build · 1 hunter" in html
    assert '<span class="phase hue-indigo">design</span>' in html and '<span class="phase st-out">hunter</span>' in html
    assert "--phase-n: 6" in html


def test_a_reference_two_chips_hold_joins_on_the_repo_pages_held_by():
    from shiftlead.ui.repo import ledger_lists

    r = reading({"9": [ask(TL, "open", "1")]})
    r["ledger"]["entries"][0]["for_page"] = "pickable"
    ms = [g("g1"), g("g2", pr=None)]
    motion = ui.motion_rows(ms, r, {"/r/s": r}, TD, (SEAT,), {})
    assert sorted(x["stage"] for x in motion) == ["build", "review"]
    lists = ledger_lists(r, motion, {}, None, {})
    (row,) = [e for got in lists for e in got["rows"] if e.get("id") == "TD-1"]
    assert sorted(row["held"].split(", ")) == ["g1", "g2"]


def test_one_role_with_a_worker_and_a_review_stage_reads_each_by_its_kind():
    """TD-1780 (§4.9c rules 3 and 4): where one role holds both a worker stage and a review stage, a holder's
    PR nobody asked reads the worker stage and an open ask's seat the review stage — in either order of the flow."""
    lead = g("t1", role="techlead")
    fix, rev = Stage("fix", "techlead", ["free-pick", "owner:techlead"]), Stage("review", "techlead")
    for flow in ([TD[0], fix, rev], [TD[0], rev, fix]):
        names = [s.name for s in flow]
        assert [x[1] for x in chips([lead], reading(), flow)] == ["fix"], names
        assert [x[1] for x in chips([lead], reading({"9": [ask(TL, "open", "1")]}), flow)] == ["review"], names
