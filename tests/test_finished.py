"""TD-241 slice 1, design §6 rule 9 (*Finished is the home's reading*): `work.finished` reads a live
team as finished from the records carrying its badge and nothing else — who is a seat, who the
manager and who a person's all come off the records — and the page's *concluded* is that reading."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from sessionorc import work
from sessionorc.models import Session
from shiftlead import teamrun

pytestmark = pytest.mark.unit

OUT = {"at": "2026-09-29T06:00:00Z", "why": "nothing pickable"}
LATER = {"at": "2026-09-29T07:00:00Z", "why": "nothing pickable"}
WANTS = {"at": "2026-09-29T08:00:00Z", "why": "context bound"}
LEAD = "ao-t-manager"


def _rec(name: str, state: str = "idle", **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state=state,
        team="g", unattended=True, controllers=[LEAD],
    )  # fmt: skip
    return Session(**{**base, **kw})


def _manager(state: str = "idle", **kw) -> Session:
    return _rec("manager", state, controllers=[], capabilities=["control"], **kw)


def _seat(state: str = "idle") -> Session:
    return _rec("techlead", state, seat={"role": "techlead"})


def test_two_members_declared_and_a_manager_idle_without_declaring_is_finished():
    team = [_manager(), _rec("g1", out_of_work=OUT), _rec("g2", out_of_work=LATER), _seat()]
    got = work.finished(team)
    assert got == {"at": LATER["at"], "restart": False, "names": ["g1", "g2", "manager", "techlead"], "why": []}
    # the page's concluded is the same reading, from the views a client holds, and names what Start closes
    views = [asdict(r) for r in team]
    assert work.finished(views) == got
    assert teamrun.concluded(views) == {k: got[k] for k in ("at", "restart", "names")}
    # the manager's own word changes nothing: it is not asked for
    assert work.finished([_manager(out_of_work=OUT), *team[1:]])["why"] == []


def test_the_why_clauses_name_the_sessions_that_keep_it_from_holding():
    team = [_manager("working"), _rec("g1", "working", out_of_work=OUT), _rec("g2"), _seat("needs-you")]
    got = work.finished(team)
    assert got["why"] == ["manager working", "g1 working", "g2 idle, not declared", "techlead needs-you"]
    assert got["at"] is None and teamrun.concluded([asdict(r) for r in team]) is None


def test_a_working_seat_blocks_it_and_an_idle_or_gone_one_does_not():
    members = [_manager(), _rec("g1", out_of_work=OUT)]
    assert work.finished([*members, _seat("working")])["why"] == ["techlead working"]
    assert work.finished([*members, _seat("closed")])["why"] == []
    # a seat by the definition's name, for a record with no `seat` field (the card's `seats`)
    assert work.finished([*members, _rec("techlead", "working")], {"techlead"})["why"] == ["techlead working"]
    assert work.finished([*members, _rec("techlead")], {"techlead"})["why"] == []


def test_an_interactive_member_counts_for_nothing():
    paul = _rec("paul", "working", unattended=False)
    got = work.finished([_manager(), _rec("g1", out_of_work=OUT), paul])
    assert got["why"] == [] and "paul" not in got["names"]
    # and a team whose only live session is a person's has nothing live to read
    assert work.finished([paul, _rec("g1", "closed", out_of_work=OUT)]) is None


def test_a_member_that_wants_a_restart_reads_restart_and_a_dead_one_blocks():
    got = work.finished([_manager(), _rec("g1", restart_wanted=WANTS), _rec("g2", out_of_work=OUT)])
    assert got["why"] == [] and got["restart"] is True and got["at"] == WANTS["at"]
    # exited or closed with the word: rule 2 has it, and a team about to have a member back is not finished
    for state in ("exited", "closed"):
        got = work.finished([_manager(), _rec("g1", state, restart_wanted=WANTS), _rec("g2", out_of_work=OUT)])
        assert got["why"] == [f"g1 {state}, restart wanted"]
    # once rule 2 has acted the old record is superseded, and passed over
    old = _rec("g1", "closed", restart_wanted=WANTS, superseded_by="ao-t-g1b")
    assert work.finished([_manager(), old, _rec("g1b", out_of_work=OUT)])["why"] == []


def test_the_dead_are_counted_blocking_or_passed_over():
    lead, g2 = _manager(), _rec("g2", out_of_work=OUT)
    # dead and declared: counted, its instant with the rest
    assert work.finished([lead, _rec("g1", "closed", out_of_work=LATER, pane=False), g2])["at"] == LATER["at"]
    # exited with its pane and no word: rule 1's crash blocks until that rule has acted
    assert work.finished([lead, _rec("g1", "exited", pane=True), g2])["why"] == ["g1 crashed"]
    # killed or closed with no word: passed over, as concluded passed it over
    for state, pane in (("exited", False), ("closed", False)):
        assert work.finished([lead, _rec("g1", state, pane=pane), g2])["why"] == []
    # nothing live at all: `wound_down`'s to describe
    assert work.finished([_rec("g1", "closed", out_of_work=OUT), _manager("exited")]) is None


def test_only_seats_and_the_manager_left_is_finished_with_no_instant():
    got = work.finished([_manager(), _seat(), _rec("g1", "closed", pane=False)])
    assert got == {"at": None, "restart": False, "names": ["manager", "techlead"], "why": []}
    assert work.finished([_manager("working"), _seat()])["why"] == ["manager working"]


def test_the_manager_is_read_from_the_records():
    lead, g1 = _manager(), _rec("g1", out_of_work=OUT)
    assert work.manager_of([lead, g1]) is lead
    # a person leads the team: nobody holds control, so every record is a member and must declare
    assert work.manager_of([g1, _rec("g2")]) is None
    assert work.finished([_rec("g1", out_of_work=OUT, controllers=[]), _rec("g2", controllers=[])])["why"] == [
        "g2 idle, not declared"
    ]
    # holding `control` with nobody listing it, or listed without the grant, is a member
    assert work.manager_of([_rec("x", capabilities=["control"], controllers=[]), _rec("y", controllers=[])]) is None
    assert work.manager_of([_rec("manager", controllers=[]), g1]) is None
    # manager → lead → worker: the lead holds control and is listed, and is a member under the manager
    sub = _rec("lead", capabilities=["control"])
    w = _rec("w", controllers=[sub.id], out_of_work=OUT)
    assert work.manager_of([sub, w, lead]) is lead
    assert work.finished([lead, sub, w])["why"] == ["lead idle, not declared"]


def test_a_dead_manager_is_passed_over_and_its_members_still_read():
    """A manager that exited is still the manager — never a member that crashed or must declare."""
    gone = _manager("exited", pane=True)
    assert work.manager_of([gone, _rec("g1")]) is gone
    assert work.finished([gone, _rec("g1", out_of_work=OUT)])["why"] == []
    assert work.finished([gone, _rec("g1")])["why"] == ["g1 idle, not declared"]


def test_a_start_replaces_a_dead_record_in_place_so_only_a_stray_one_blocks():
    """A member started again takes its old record's id (`_take_name`), so a dead `restart_wanted`
    blocks only while rule 2 has not acted — or on a record nothing will start again, which is a
    person's to Forget, and the clause names it."""
    stray = _rec("old-name", "closed", restart_wanted=WANTS, pane=False)
    got = work.finished([_manager(), _rec("g1", out_of_work=OUT), stray])
    assert got["why"] == ["old-name closed, restart wanted"]


def test_a_declaration_in_any_other_shape_is_none_and_never_a_raise():
    for junk in ("x", ["y"], 7, {"why": "no at"}):
        for key in ("out_of_work", "restart_wanted"):
            view = {"id": "ao-t-g1", "name": "g1", "team": "g", "state": "idle", key: junk}
            assert work.finished([view])["why"] == ["g1 idle, not declared"]


# ── TD-274 slice 1, design §4.9a *Waiting is read, never declared* ────────────────────────────


def _q(sender: str, about: str | None, kind: str = "steer", bound: str | None = "2026-10-02T09:57:00Z", **kw):
    return {"id": f"m-{sender}-{about}", "from": sender, "kind": kind, "about": about, "bound": bound, **kw}


def test_a_member_with_an_open_question_about_a_reference_is_waiting_whatever_it_declared():
    team = [_manager(), _rec("g1", out_of_work=OUT), _rec("g2", out_of_work=LATER)]
    assert work.finished(team)["why"] == []
    waiting = work.waiting_of([_q("ao-t-g2", "td-222")])
    assert waiting == {"ao-t-g2": [{"id": "m-ao-t-g2-td-222", "ref": "TD-222", "bound": "2026-10-02T09:57:00Z"}]}
    (clause,) = work.finished(team, waiting=waiting)["why"]
    assert clause.startswith("g2 waiting on the person: TD-222, until ")
    # an ask has no bound; two questions name the sooner bound and how many more
    asks = work.waiting_of([_q("ao-t-g2", "#895", kind="ask", bound=None), _q("ao-t-g2", "TD-222")])
    assert [q["ref"] for q in asks["ao-t-g2"]] == ["TD-222", "#895"]
    assert work.finished(team, waiting=asks)["why"][0].endswith(" and 1 more")
    only_ask = work.waiting_of([_q("ao-t-g2", "#895", kind="ask", bound=None)])
    assert work.finished(team, waiting=only_ask)["why"] == ["g2 waiting on the person: #895"]


def test_prose_a_closed_question_a_note_and_a_dead_asker_hold_nothing():
    team = [_manager(), _rec("g1", out_of_work=OUT), _rec("g2", "closed", out_of_work=LATER)]
    for entries in (
        [_q("ao-t-g1", "the menu question")],  # prose: dies with its asker
        [_q("ao-t-g1", "TD-222", closed_reason="replied")],
        [_q("ao-t-g1", "TD-222", kind="note")],
        [_q("ao-t-g2", "TD-222")],  # a closed member's question is orphaned, not a wait
    ):
        assert work.finished(team, waiting=work.waiting_of(entries))["why"] == []
    # the manager's or a seat's question is not a member's wait
    assert work.finished(team, waiting=work.waiting_of([_q(LEAD, "TD-222")]))["why"] == []


def _held(member: Session, pr: int, closed: bool = False):
    """The techlead seat holding `member`'s ask for `pr` (§4.9b *The reader*)."""
    from sessionorc.models import MailEntry

    seat = _seat()
    seat.host = "kmaster"
    ask = MailEntry(id=f"m-{pr}", from_=member.id, to=[seat.id], at=OUT["at"], kind="ask", text="read it", pr=pr)
    if closed:
        ask.closed_reason = "answered"
    seat.inbox.append(ask)
    return seat


def test_a_member_whose_claimed_pr_waits_on_a_seats_held_ask_is_unfinished_whatever_it_declared():
    """§6 rule 9 *Which members count* (TD-854, built by TD-863): a member declared `none` beside a PR
    its techlead holds is waiting on that reader; once the ask is answered, it reads finished."""
    from sessionorc.models import ProgressEntry

    g1 = _rec("g1", out_of_work=OUT, host="kmaster")
    g1.progress = [ProgressEntry(ref="TD-9", pr=2067), ProgressEntry(ref="TD-8", review_pr=2068)]
    team = [_manager(), g1, _held(g1, 2067)]
    got = work.finished(team, home="kmaster")
    assert got["why"] == ["g1 waiting on techlead: #2067"] and got["at"] is None
    # the view the page holds reads the same, its `prs_waiting` the reading `Session.view` gives
    views = [r.view() for r in team]
    assert work.finished(views, home="kmaster") == got and teamrun.concluded(views) is None
    two = _held(g1, 2067)
    two.inbox += _held(g1, 2068).inbox
    assert work.finished([_manager(), g1, two], home="kmaster")["why"] == ["g1 waiting on techlead: #2067 and 1 more"]
    # answered: gone from `prs_waiting`
    assert work.finished([_manager(), g1, _held(g1, 2067, closed=True)], home="kmaster")["why"] == []
    # a person-inbox question keeps its clause first
    waiting = {g1.id: [{"id": "m-q", "ref": "TD-9", "bound": None}]}
    assert work.finished(team, waiting=waiting, home="kmaster")["why"] == ["g1 waiting on the person: TD-9"]


def test_a_done_claim_or_a_held_ask_for_a_pr_the_member_does_not_claim_blocks_nothing():
    from sessionorc.models import ProgressEntry

    g1 = _rec("g1", out_of_work=OUT, host="kmaster")
    g1.progress = [ProgressEntry(ref="TD-9", status="done", pr=2067), ProgressEntry(ref="TD-7", pr=2000)]
    assert work.finished([_manager(), g1, _held(g1, 2067)], home="kmaster")["why"] == []
    other = _rec("g2", out_of_work=OUT)
    other.progress = [ProgressEntry(ref="TD-9", pr=2067)]
    assert work.finished([_manager(), g1, other, _held(g1, 2067)], home="kmaster")["why"] == []
    # an ask from a node's member names it `id@host`: not the home's record of the same id, but the
    # node's view of it, and a bare address is the home's own (`ao-t-g1@kmaster` is `ao-t-g1`)
    node = _held(g1, 2000)
    node.inbox[0].from_ = f"{g1.id}@laptop"
    assert work.held_asks([g1, node], home="kmaster") == {}
    assert list(work.held_asks([{**g1.view(), "id": f"{g1.id}@laptop"}, node], home="kmaster")) == [f"{g1.id}@laptop"]
    named = _held(g1, 2000)
    named.inbox[0].from_ = f"{g1.id}@kmaster"
    assert list(work.held_asks([g1, named], home="kmaster")) == [g1.id]
    assert work.held_asks([g1, _held(g1, 2000)], home="kmaster") == {g1.id: [{"seat": "techlead", "pr": 2000}]}
