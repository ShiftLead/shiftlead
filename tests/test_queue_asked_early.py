"""TD-2184 slice 2, design §4.4 *A question whose entry only waits is asked early* (TD-2172): a `decision (paul)`
member whose counted work is all waits — a blocker, a gated blocker that itself waits, its own `until` or `event`
gate — and no open part reads *asked early*, marked `early` with its `early_line`; it keeps its need, marked, so no
test of need reads it, and its question is pressed as any. The fact — an open part, or a gated `Owner: paul` entry
with any counted work — keeps *waiting, then yours*, and the home's stale refusal reads it alone."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_queue import NOW, _entry, _repo
from test_queue_board_hold import HELD, _read, _row

from sessionorc import queue, settle
from sessionorc.agent_inbox import InboxMixin
from shiftlead.ui.app import ledger_for_you
from shiftlead.ui.queue import _seg, branch

GATED = {"Priority": "High"}
LATER = "2026-12-01"  # after NOW's day


def _gated(n: int, title: str, *blockers: str, **fields: str) -> str:
    return _entry(n, title, **GATED, Blocked_by=", ".join([*blockers, "decision (paul)"]), **fields)


def _one(tmp_path, *entries) -> tuple[str, dict]:
    root, r = _repo(tmp_path, "r", list(entries))
    settle.mark_waits(r["ledger"]["entries"], NOW)  # the gates marked as the home marks them
    return root, r


def _card(q: dict, ref: str) -> dict:
    return next(c for c in q["cards"] if ref in [c["top"]["qid"], *(r["qid"] for r in c["rows"])])


@pytest.mark.unit
def test_a_chain_of_gated_blockers_that_ends_in_a_wait_is_asked_early_and_counted_nowhere(tmp_path):
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-002", "TD-003"),
        _gated(2, "a gated blocker with no work"),
        _gated(3, "a gated blocker that waits", "TD-004"),
        _entry(4, "dated", Priority="High", Blocked_by=f"until {LATER}"),
    )
    q = _read({root: r})
    row, c = _row(q, "r#TD-001"), _card(q, "r#TD-001")
    assert row["state"] == "asked early" and row["needs"] == "decision" and row["early"]
    assert row["early_line"] == "once TD-003 closes" and not row["then_yours"] and row["open_work"] == []
    # TD-002, a gated blocker with no work, is asked as any on the same card, so the card needs the person by it alone
    assert c["status"] == "needs you" and c["top"]["qid"] == "r#TD-002" and not _row(q, "r#TD-002")["early"]
    root2, r2 = _one(
        tmp_path / "b",
        _gated(1, "the question", "TD-003"),
        _gated(3, "a gated blocker that waits", "TD-004"),
        _entry(4, "dated", Priority="High", Blocked_by=f"until {LATER}"),
    )
    assert _card(_read({root2: r2}), "r#TD-001")["status"] == "waiting", "with no need beside it, the card waits"
    assert branch(row) == "waiting" and _seg({**row, "show": "TD-001"})["title"] == "TD-001: asked early"
    # the Inbox's *Later* row: the same mark, counted nowhere
    later = ledger_for_you({root: r}, [], {}, now=NOW)
    got = next(x for g in later["groups"] for x in g["rows"] if x["id"] == "TD-001")
    assert got["early"] and got["early_line"] == "once TD-003 closes" and not got["then_yours"]
    assert all(g["n"] == sum(1 for x in g["rows"] if x["id"] == "TD-002") for g in later["groups"])
    # its press is no stale one: the home's refusal reads the fact alone
    home = SimpleNamespace(_repos={root: r})
    home._open_work = lambda: InboxMixin._open_work(home)
    InboxMixin._refuse_waiting(home, ["r#TD-001"])


@pytest.mark.unit
def test_a_gated_blocker_with_no_work_leaves_the_question_asked_as_any(tmp_path):
    root, r = _one(tmp_path, _gated(1, "the question", "TD-002"), _gated(2, "a gated blocker with no work"))
    q = _read({root: r})
    row = _row(q, "r#TD-001")
    assert row["state"] == "" and not row["early"] and not row["then_yours"]
    assert _card(q, "r#TD-001")["status"] == "needs you"


@pytest.mark.unit
def test_its_own_date_is_its_line_and_alone_its_card_waits(tmp_path):
    root, r = _one(tmp_path, _entry(1, "the question", **GATED, Blocked_by=f"until {LATER}, decision (paul)"))
    q = _read({root: r})
    row = _row(q, "r#TD-001")
    assert row["state"] == "asked early" and row["early_line"] == f"once {LATER}"
    assert _card(q, "r#TD-001")["status"] == "waiting"
    assert not queue._own(r["ledger"]["entries"][0] | {"early": row["early_line"]})


@pytest.mark.unit
def test_a_gated_blocker_whose_only_wait_is_its_date_is_named_as_that_date(tmp_path):
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-002"),
        _entry(2, "gated and dated", **GATED, Blocked_by=f"until {LATER}, decision (paul)"),
    )
    assert _row(_read({root: r}), "r#TD-001")["early_line"] == f"once {LATER}"


@pytest.mark.unit
def test_its_own_date_and_an_open_blocker_read_and_one_more(tmp_path):
    root, r = _one(
        tmp_path,
        _entry(1, "the question", **GATED, Blocked_by=f"TD-002, until {LATER}, decision (paul)"),
        _entry(2, "in progress", Priority="High"),
    )
    assert _row(_read({root: r}), "r#TD-001")["early_line"] == "once TD-002 and 1 more close"


@pytest.mark.unit
def test_the_first_wait_is_the_lowest_key_even_where_a_gated_blocker_is_added_after_the_open_ones(tmp_path):
    """TD-2237: `counted_work` adds a gated blocker that itself waits after `open_work`'s ids, then sorts each
    member's ids by key, so a gated TD-002 is named before an open TD-003."""
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-002", "TD-003"),
        _gated(2, "a gated blocker that waits", "TD-004"),
        _entry(3, "in progress", Priority="High"),
        _entry(4, "dated", Priority="High", Blocked_by=f"until {LATER}"),
    )
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "asked early" and row["early_line"] == "once TD-002 and 1 more close"


@pytest.mark.unit
def test_a_gated_blocker_with_its_own_date_and_open_work_is_named_by_its_id(tmp_path):
    """TD-2237: a gated blocker is named by its date only where that date is its only wait; with open work beside
    it, the line names the blocker itself."""
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-002"),
        _entry(2, "gated, dated and blocked", **GATED, Blocked_by=f"TD-003, until {LATER}, decision (paul)"),
        _entry(3, "in progress", Priority="High"),
    )
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "asked early" and row["early_line"] == "once TD-002 closes"


@pytest.mark.unit
def test_a_held_build_blocked_by_open_work_never_reads_asked_early(tmp_path):
    from test_queue_held_builds import PART, _ask
    from test_queue_lift_here import _setup

    root, r = _setup(
        tmp_path,
        [
            _entry(1, "the design", **HELD),
            _entry(2, "build a", **{**PART, "Blocked_by": "TD-004, decision (paul)"}),
            _entry(4, "the build's blocker", Priority="High"),
        ],
        _ask("TD-002"),
    )
    q = _read({root: r})
    build = _row(q, "r#TD-002")
    assert not build["early"] and build["state"] == "waits on TD-001's question"
    design = _row(q, "r#TD-001")
    assert not design["early"] and design["state"] == "" and design["go_builds"] == ["TD-002"]


def _held_build(tmp_path) -> tuple:
    """TD-001 a gated design whose open line names TD-002 in `Parts:`; TD-002 its held build, waiting on a dated
    TD-004 alone."""
    from test_queue_held_builds import PART, _ask
    from test_queue_lift_here import _setup

    root, r = _setup(
        tmp_path,
        [
            _entry(1, "the design", **HELD),
            _entry(2, "build a", **{**PART, "Blocked_by": "TD-004, decision (paul)"}),
            _entry(4, "dated", Priority="High", Blocked_by=f"until {LATER}"),
        ],
        _ask("TD-002"),
    )
    settle.mark_waits(r["ledger"]["entries"], NOW)
    return root, r


@pytest.mark.unit
def test_a_held_build_whose_work_is_all_waits_reads_its_designs_question_not_asked_early(tmp_path):
    """TD-2244: a held build whose counted work is all waits keeps *waits on TD-<design>'s question* and is never
    asked early (§4.4 *A design's question is asked once, on the design*, TD-2026)."""
    root, r = _held_build(tmp_path)
    build = _row(_read({root: r}), "r#TD-002")
    assert build["state"] == "waits on TD-001's question" and not build["early"] and not build["then_yours"]


@pytest.mark.unit
def test_a_held_builds_word_stands_over_an_early_mark(tmp_path, monkeypatch):
    """TD-2244: `asked` leaves a held build out of its early members; were one marked early anyway, the row's own
    precedence keeps the design's question as its word (`reading`'s `not held_word`)."""
    root, r = _held_build(tmp_path)
    real = queue.asked

    def marked(counted, entries, held):
        got = real(counted, entries, held)
        return got._replace(early={**got.early, "r#TD-002": "once TD-004 closes"})

    monkeypatch.setattr(queue, "asked", marked)
    build = _row(_read({root: r}), "r#TD-002")
    assert build["state"] == "waits on TD-001's question" and not build["early"]


@pytest.mark.unit
def test_the_persons_own_gated_entry_keeps_the_fact_or_is_a_need(tmp_path):
    root, r = _one(
        tmp_path,
        _entry(1, "theirs, blocked", **GATED, Owner="paul", Blocked_by="TD-002, decision (paul)"),
        _entry(2, "in progress", Priority="High"),
        _entry(3, "theirs, dated", **GATED, Owner="paul", Blocked_by=f"until {LATER}, decision (paul)"),
    )
    q = _read({root: r})
    blocked, dated = _row(q, "r#TD-001"), _row(q, "r#TD-003")
    assert blocked["state"] == "waiting, then yours" and blocked["then_yours"] == ["r#TD-002"]
    assert not dated["early"] and not dated["then_yours"] and dated["needs"] == "owner"


@pytest.mark.unit
def test_a_persons_step_among_its_blockers_is_a_wait(tmp_path):
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-002"),
        _entry(2, "the person's step", Priority="High", Owner="paul"),
    )
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "asked early" and row["early_line"] == "once TD-002 closes" and row["after"] == ["r#TD-002"]


@pytest.mark.unit
def test_a_cycle_of_gated_blockers_counts_for_nothing(tmp_path):
    root, r = _one(tmp_path, _gated(1, "one", "TD-002"), _gated(2, "two", "TD-001"))
    q = _read({root: r})
    for ref in ("r#TD-001", "r#TD-002"):
        row = _row(q, ref)
        assert row["state"] == "" and not row["early"] and not row["then_yours"]


@pytest.mark.unit
def test_early_line_names_an_event_and_another_repos_id():
    entries = {
        "r#TD-001": {"id": "TD-001", "key": "0|1"},
        "s#TD-005": {"id": "TD-005", "key": "0|5"},
    }
    c = queue.Counted({}, {"r#TD-001": ["s#TD-005"]}, {}, {"r#TD-001": ["event (live)"]})
    assert queue.early_line("r#TD-001", c, entries) == "once s#TD-005 and 1 more close"
    c = queue.Counted({}, {}, {}, {"r#TD-001": ["event (live)"]})
    assert queue.early_line("r#TD-001", c, entries) == "once its event lands"
    assert queue.early_line("r#TD-001", queue.Counted({}, {}, {}, {}), entries) == ""


def _early_row(tmp_path) -> dict:
    """`ledger_for_you`'s row for TD-001, gated and blocked by TD-002 in progress: asked early."""
    root, r = _one(tmp_path, _gated(1, "the question", "TD-002", Ask="Go ahead?"), _entry(2, "in progress", **GATED))
    row = next(
        x for g in ledger_for_you({root: r}, [], {}, now=NOW)["groups"] for x in g["rows"] if x["id"] == "TD-001"
    )
    assert row["early"] and row["early_line"] == "once TD-002 closes" and not row["then_yours"]
    return row


@pytest.mark.unit
def test_an_early_ledger_item_is_grey_counted_on_no_pill_and_counts_for_start_session(tmp_path):
    from test_queue_covers_once import ledger_row

    from shiftlead.ui.queue import answered_case, attach, card_wants, items_n

    assert answered_case({"row": "ledger", "early": True}) == "early"
    assert answered_case({"row": "ledger", "early": True, "then_yours": ["r#TD-9"]}) == "then_yours"
    marked = {**ledger_row(1), "early": True, "early_line": "once TD-002 closes"}
    got = attach({}, lambda e, sec: e.get("id"), [marked], lambda c, ref, on: {"repo": "r", "ref": ref})
    items = got["cards"]["r#TD-001"]["needs"]
    assert [(m["item"], m["want"]) for m in items] == [("r#TD-001", "answered")] and items[0]["starts"]
    w = card_wants({"needs": items}, "r#TD-001", True)
    assert not w["n"].get("decide") and items_n(w) == 1, "on no pill, counted for the header's Start session"


@pytest.mark.unit
def test_the_early_item_draws_its_whole_bar_under_its_press_line(tmp_path):
    from test_queue_item_shape import card

    row = {**_early_row(tmp_path), "home": "queue", "start": {"repo": "r", "ref": "TD-1", "card": "r#TD-001"}}
    html = card(row, "answered")
    assert (
        '<div class="qpress qp-idle qearly" role="status">Asked early: your answer acts once TD-002 closes.</div>'
        in html
    )
    for kept in ("Not clear", "Answer…"):
        assert kept in html, kept
    assert "Go ahead?" in html


@pytest.mark.unit
def test_the_later_row_draws_the_early_line_with_its_question_whole(tmp_path):
    from test_queue_item_shape import inbox

    html = inbox(_early_row(tmp_path), section="later")
    assert "Asked early: your answer acts once TD-002 closes" in html
    assert "Not clear" in html and "Reply" in html, "its question drawn whole"


@pytest.mark.unit
def test_a_covering_line_stands_in_an_early_entrys_place():
    from test_queue_covers_once import ENTRIES, index, ledger_row, line

    from shiftlead.ui.queue import attach, item_home

    idx = index(("r#TD-050", [50, 51, 52]))
    placed = {**line(), **item_home(line(), idx, entries=ENTRIES)}
    later = [ledger_row(n, "r#TD-050") for n in (50, 52)]
    later.append({**ledger_row(51, "r#TD-050"), "early": True, "early_line": "once TD-055 closes"})
    got = attach({"needs": [placed]}, lambda e, sec: e.get("key") or e.get("id"), later)["cards"]["r#TD-050"]["needs"]
    assert [m["html"] for m in got] == ["board:k1"], "the line alone, no early item beside it"


# TD-2235: an earlier word stands over *asked early* (§4.4 *A question whose entry only waits is asked early*: *with you
# in <name>*, a press's mark, an *answered — …* keep theirs), on the Queue row and on the *Later* row alike


def _waits(tmp_path) -> tuple[str, dict]:
    """TD-001, gated and blocked by TD-002 in progress: asked early where nothing else stands."""
    return _one(tmp_path, _gated(1, "the question", "TD-002", Ask="Go ahead?"), _entry(2, "in progress", **GATED))


def _later(repos, fleet=(), inbox=()) -> dict:
    got = ledger_for_you(repos, list(fleet), {}, NOW, list(inbox))
    return next(x for g in got["groups"] for x in g["rows"] if x["id"] == "TD-001")


@pytest.mark.unit
def test_the_persons_own_session_on_it_reads_with_you_not_asked_early(tmp_path):
    from test_queue import _rec

    root, r = _waits(tmp_path)
    assert _row(_read({root: r}), "r#TD-001")["early"], "asked early with nothing else standing"
    mine = _rec("p", root, "TD-001", state="idle")
    mine.unattended = False
    row = _row(_read({root: r}, [mine]), "r#TD-001")
    assert row["state"] == "with you in p" and not row.get("early")
    fleet = [{"id": "p", "name": "p", "state": "idle", "unattended": False, "repo": root, "dir": root,
              "progress": [{"ref": "TD-001", "status": "claimed", "at": NOW.isoformat()}]}]  # fmt: skip
    assert not _later({root: r}, fleet)["early"], "the Later row keeps its own word too"


@pytest.mark.unit
def test_a_mail_answer_reads_answered_not_asked_early(tmp_path):
    from test_queue_answered_hold import _asker, _q
    from test_ui_answered_hold import FLEET, _ask

    root, r = _waits(tmp_path)
    row = _row(_read({root: r}, [_asker()], [_q()]), "r#TD-001")
    assert row["state"] == "answered — waiting on designer" and not row.get("early")
    got = _later({root: r}, FLEET, [_ask("TD-001")])
    assert got["answered"] is not None and not got["early"]


@pytest.mark.unit
def test_a_press_landing_draws_its_mark_not_asked_early(tmp_path):
    root, r = _waits(tmp_path)
    marked = queue.lay_applying(r, {"ledger:r#TD-001": {"t": {"act": "decide", "at": "x"}}}, "r")
    row = _row(_read({root: marked}), "r#TD-001")
    assert row["state"] != "asked early" and not row.get("early")
    got = _later({root: marked})
    assert got["applying"] and not got["early"]


@pytest.mark.unit
def test_an_open_answered_board_line_reads_answered_not_asked_early(tmp_path):
    from test_queue_board_hold import _board, _open

    root, r = _waits(tmp_path)
    r["boards"] = _board(root, _open("TD-001"))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["answered"]["kind"] == "board" and row["state"].startswith("answered — ") and not row.get("early")


@pytest.mark.unit
def test_the_rails_later_count_leaves_an_early_row_out(tmp_path):
    from shiftlead.ui.inbox import rail_rows

    row = _early_row(tmp_path)
    assert not [x for x in rail_rows({}, [], [row]) if x.get("section") == "later"]
    plain = {**row, "early": False, "early_line": ""}
    assert [x for x in rail_rows({}, [], [plain]) if x.get("section") == "later"], "a row not early is counted"


@pytest.mark.unit
def test_its_own_event_gate_alone_is_its_line_and_its_card_waits(tmp_path):
    gated = _entry(1, "the question", **GATED, Blocked_by="event (live), decision (paul)")
    event = '**Event (live):** The build is live.\ncheck: file-contains r@promote/live docs/x.md "y"\n\n'
    root, r = _one(tmp_path, gated + event)
    q = _read({root: r})
    row = _row(q, "r#TD-001")
    assert row["state"] == "asked early" and row["early_line"] == "once its event lands"
    assert _card(q, "r#TD-001")["status"] == "waiting", "an early member's own event gate waits as its date does"


@pytest.mark.unit
def test_a_member_that_only_waits_keeps_lift_the_hold_under_an_open_decided_line(tmp_path):
    from test_queue_board_hold import _open, _setup

    entries = [_gated(1, "the question", "TD-002"), _entry(2, "in progress", **GATED)]
    root, r = _setup(tmp_path, entries, _open("TD-001"))
    settle.mark_waits(r["ledger"]["entries"], NOW)
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "answered — waiting on a pick" and not row["then_yours"]
    assert row["lift_here"] is True, "its counted work is all waits, so no fact takes its Lift (TD-1926, TD-2172)"


@pytest.mark.unit
def test_an_early_queue_row_draws_its_word_teal(tmp_path):
    from shiftlead.ui.app import templates
    from shiftlead.ui.queue import queue_view

    root, r = _one(tmp_path, _gated(1, "the question", "TD-002"), _entry(2, "in progress", **GATED))
    view = queue_view(_read({root: r}), NOW)
    c = next(c for g in ("in_progress", "waiting", "up_next") for c in view.get(g) or () if c["id"] == "r#TD-002")
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    row = html[html.index('data-qid="r#TD-001"') :]
    assert '<span class="qstate s-waiting">asked early</span>' in row, "teal: its need no test reads (TD-2184)"
