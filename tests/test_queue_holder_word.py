"""TD-1724 (TD-1567's build), design §4.4 *A row's state* (*The person's own session is never stalled*), §4.5 screen
12 *A holder's word opens the holder*, §4.5a *Queue card: holder's word*: an entry the person's own idle session
claims reads *with you in <name>*, never *stalled*, though it needs nothing of the person; and each word that stands
for a session — *with you in*, *held by*, *stalled* — opens that session's Focus, the card's *stalled* its
`stalled_holder`."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_queue import NOW, _by_id, _cards, _entry, _rec, _repo
from test_queue_with_you import _mine

from sessionorc import queue
from shiftlead.ui.queue import queue_view

pytestmark = pytest.mark.unit


def _one(tmp_path, **fields: str):
    return _repo(tmp_path, "r", [_entry(1, "a build", Priority="High", **fields)])


def _red(r, number: int = 7, *, days: int = 3) -> None:
    since = (NOW - timedelta(days=days)).isoformat()
    r["prs"]["open"] = [{"number": number, "branch": "td1-x", "checks": "red", "red_since": since}]


def _templates():
    from shiftlead.ui.app import templates

    return templates.env


def _row_html(row) -> str:
    return str(_templates().get_template("queue_row.html").module.row(row))


def _card_html(c) -> str:
    return str(_templates().get_template("queue_card.html").module.card(c))


def _shaped(q):
    v = queue_view(q, NOW, {"cards": {}, "mentioned": {}})
    return [*v["in_progress"], *v.get("up_next", []), *v.get("waiting", [])]


def test_td1529s_case_an_idle_interactive_holder_reads_with_you_never_stalled(tmp_path):
    root, r = _one(tmp_path)
    c = _by_id(_cards({root: r}, [_mine("td-1529", root, "TD-001")]))["r#TD-001"]
    t = c["top"]
    assert t["state"] == "with you in td-1529" and t["needs"] is None and t["with_you"] is None
    assert t["holder"] == {"id": "td-1529", "name": "td-1529", "state": "idle"}
    assert c["status"] != "stalled" and c["stalled_holder"] is None
    # with an unattended idle co-holder too: the person's claim keeps the row from *stalled*, and its holder is theirs
    both = [_rec("a-idle", root, "TD-001", state="idle"), _mine("td-1529", root, "TD-001")]
    t = _by_id(_cards({root: r}, both))["r#TD-001"]["top"]
    assert t["state"] == "with you in td-1529" and t["holder"]["id"] == "td-1529"


def test_the_same_row_with_an_open_pr_reads_in_review_with_the_sessions_pill(tmp_path):
    root, r = _one(tmp_path)
    r["prs"]["open"] = [{"number": 9, "branch": "td1-x", "checks": "green"}]
    (c,) = _cards({root: r}, [_mine("p", root, "TD-001")])["cards"]
    assert c["top"]["state"] == "in review #9" and c["top"]["holder"]["id"] == "p" and c["top"]["with_you"] is None
    html = _row_html({**c["top"], "depth": 1})
    assert 'class="qpill mono" href="/focus/p"' in html, "the pill beside the PR words"


def test_an_unattended_idle_holder_still_reads_stalled_its_pill_the_stuck_record(tmp_path):
    root, r = _one(tmp_path)
    recs = [_rec("a-busy", root, "TD-001", state="working"), _rec("b-idle", root, "TD-001", state="idle")]
    c = _by_id(_cards({root: r}, recs))["r#TD-001"]
    t = c["top"]
    assert t["state"] == "stalled" and t["holder"]["id"] == "b-idle", "the record the word stands for, not claim[0]"
    assert c["status"] == "stalled" and c["stalled_holder"]["id"] == "b-idle"
    html = _row_html({**t, "depth": 1})
    assert '<a class="qstate s-stalled" href="/focus/b-idle" title="open b-idle">stalled</a>' in html
    assert 'class="qpill mono" href="/focus/b-idle"' in html


def test_held_by_opens_its_holder_and_hides_the_pill(tmp_path):
    root, r = _one(tmp_path)
    (c,) = _cards({root: r}, [_rec("w", root, "TD-001")])["cards"]
    html = _row_html({**c["top"], "depth": 1})
    assert '<a class="qstate s-held" href="/focus/w" title="open w">held by w</a>' in html and "qpill" not in html


def test_a_red_pr_nobody_holds_reads_a_plain_stalled(tmp_path):
    root, r = _one(tmp_path)
    _red(r)
    c = _by_id(_cards({root: r}, []))["r#TD-001"]
    assert c["top"]["state"] == "stalled" and c["top"]["holder"] is None and c["stalled_holder"] is None
    assert '<span class="qstate s-stalled">stalled</span>' in _row_html({**c["top"], "depth": 1})
    (shaped,) = _shaped(_cards({root: r}, []))
    html = _card_html(shaped)
    assert '<span class="qstatus s-stalled">stalled</span>' in html and 'href="/focus/' not in html


def test_a_red_pr_held_by_the_persons_idle_session_is_bare_and_being_fixed_with_a_working_co_holder(tmp_path):
    root, r = _one(tmp_path)
    _red(r)
    t = _by_id(_cards({root: r}, [_mine("p", root, "TD-001")]))["r#TD-001"]["top"]
    assert t["state"] == "#7 failing" and t["holder"]["id"] == "p", "an idle session is fixing nothing"
    recs = [_mine("p", root, "TD-001"), _rec("w", root, "TD-001", state="working")]
    t = _by_id(_cards({root: r}, recs))["r#TD-001"]["top"]
    assert t["state"] == "#7 failing · being fixed" and t["holder"]["id"] == "p"


def test_the_header_draws_with_you_once_as_a_link_and_one_stalled(tmp_path):
    root, r = _one(tmp_path)
    (shaped,) = _shaped(_cards({root: r}, [_mine("p", root, "TD-001")]))
    head = _card_html(shaped).split('<div class="qrows">')[0]
    assert head.count("with you in p") == 1 and 'href="/focus/p" title="open p">with you in p</a>' in head
    assert "qpill" not in head, "the word stands in the pill's place"
    # a top entry and a card both *stalled*: one *stalled* in the header, the status's, opening the stuck record
    (shaped,) = _shaped(_cards({root: r}, [_rec("b-idle", root, "TD-001", state="idle")]))
    head = _card_html(shaped).split('<div class="qrows">')[0]
    assert head.count(">stalled<") == 1
    assert '<a class="qstatus s-stalled" href="/focus/b-idle" title="open b-idle">stalled</a>' in head
    assert 'class="qpill mono" href="/focus/b-idle"' in head, "the top entry's pill stands"


def test_a_need_rows_with_you_still_opens_and_answered_stays_plain():
    holder = {"id": "p", "name": "p", "state": "idle"}
    row = {"qid": "r#TD-001", "id": "TD-001", "repo": "r", "title": "x", "priority": "High", "needs": "decision",
           "state": "with you in p", "with_you": "p", "holder": holder, "depth": 1}  # fmt: skip
    assert 'href="/focus/p" title="open p">with you in p</a>' in _row_html(row)
    asked = {**row, "with_you": None, "answered": {"asker": "d", "name": "d"}, "state": "answered — waiting on d"}
    assert '<span class="qstate s-with">answered — waiting on d</span>' in _row_html(asked)
    # a row with no holder (the Repo page's fallback rows) draws its word plain
    plain = {**row, "needs": None, "with_you": None, "state": "held by w", "holder": None}
    assert '<span class="qstate s-held">held by w</span>' in _row_html(plain)


def test_stalled_holder_reads_the_top_entry_first_then_the_rows_as_drawn():
    a, b = {"id": "a", "name": "a", "state": "idle"}, {"id": "b", "name": "b", "state": "idle"}
    rows = [{"state": "ready", "holder": a}, {"state": "stalled", "holder": None}, {"state": "stalled", "holder": b}]
    assert queue.stalled_holder(rows) == b
    assert queue.stalled_holder([{"state": "stalled", "holder": a}, *rows]) == a
    assert queue.stalled_holder([]) is None


def test_two_stuck_claims_stand_for_the_first_by_id(tmp_path):
    root, r = _one(tmp_path)
    recs = [_rec("z-idle", root, "TD-001", state="idle"), _rec("b-idle", root, "TD-001", state="idle")]
    c = _by_id(_cards({root: r}, recs))["r#TD-001"]
    assert c["top"]["holder"]["id"] == "b-idle" and c["stalled_holder"]["id"] == "b-idle"


def test_a_waiting_leaf_held_by_the_person_keeps_its_pill(tmp_path):
    root, r = _one(tmp_path)
    (shaped,) = _shaped(_cards({root: r}, [_mine("p", root, "TD-001")]))
    t = shaped["top"]
    waiting = {**shaped, "group": "waiting", "wait": {"id": t["qid"], "phrase": "waits until 2026-12-01"}}
    head = _card_html(waiting).split('<div class="qrows">')[0]
    assert 'class="qpill mono" href="/focus/p"' in head, "the wait phrase stands in the word's place: the pill names p"


def test_an_archived_row_is_no_stalled_holder():
    a = {"id": "a", "name": "a", "state": "idle"}
    assert queue.stalled_holder([{"state": "stalled", "holder": a, "archived": True}]) is None


def test_lay_held_reads_stalled_holder_again_over_marked_rows(tmp_path):
    root, r = _one(tmp_path)
    q = _cards({root: r}, [_rec("b-idle", root, "TD-001", state="idle")])
    (c,) = q["cards"]
    assert c["stalled_holder"]["id"] == "b-idle"
    marked = {**r, "ledger": {**r["ledger"], "entries": [{**r["ledger"]["entries"][0], "applying": {"answer": "Go"}}]}}
    (out,) = queue.lay_held(q, {root: marked})["cards"]
    assert out["top"]["state"] != "stalled" and out["stalled_holder"] is None
