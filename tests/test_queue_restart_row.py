"""TD-1863 (TD-1856's build), design §4.4 *A row's state* (*A holder waiting on a restart is not stalled*) and *The
card's status*, §4.5 screen 6 *One place for each thing that needs the person*, §4.5a *Queue card: holder's state row*
and *Inbox row: restart*: a live session whose restart waits on the person, holding an entry an open Queue card holds,
draws its restart row on that card as a Do item, and the entry's rows read the restart's words instead of *stalled*."""

from __future__ import annotations

import pytest
from test_queue import _by_id, _cards, _entry, _rec, _repo
from test_queue_holder_word import _card_html, _row_html, _shaped
from test_queue_kept_loose import hold, holder_view, state
from test_queue_with_you import _mine
from test_ui_queue import at

from sessionorc import agent_common, agent_notify, queue
from shiftlead.ui.inbox import _holder_rank, restart_mark, state_rows, stuck_onto_holders

pytestmark = pytest.mark.unit

EARLY = {"at": "2026-10-16T10:00:00+00:00", "why": "context bound", "early": True, "decided": "early: nothing done"}


def _one(tmp_path, **fields: str):
    return _repo(tmp_path, "r", [_entry(1, "a build", Priority="High", **fields)])


def _marked(rid, root, *refs, state="idle", **marks):
    s = _rec(rid, root, *refs, state=state)
    for k, v in marks.items():
        setattr(s, k, v)
    return s


# -- step 1: the one reader


def test_the_reader_words_each_mark_and_reads_an_early_one_only_idle_or_exited():
    w = agent_common.restart_waits
    assert w(EARLY, None, None, None, "idle") == {"at": EARLY["at"], "word": "restart wanted · early", "lapses": False}
    assert w(EARLY, None, None, None, "exited")["word"] == "restart wanted · early"
    assert w(EARLY, None, None, None, "working") is None, "an early mark on a working record is no row"
    assert w({**EARLY, "repeat": {"ref": "TD-9"}}, None, None, None, "idle")["word"] == "restart wanted · repeats TD-9"
    assert w({**EARLY, "early": False}, None, None, None, "idle") is None
    assert w(None, {"at": "a", "count": 3}, None, None, "working")["word"] == "restarts exhausted"
    assert w(None, {"at": "a", "why": "lost-brief"}, None, None, "idle")["word"] == "brief lost twice"
    fill = w(None, {"at": "a", "why": "fill", "count": 4}, None, None, "exited")
    assert fill == {"at": "a", "word": "fills exhausted", "lapses": True}, "a plain fill mark is listed, and lapses"
    assert w(None, {"at": "a", "why": "fill", "held": True}, None, None, "exited")["lapses"] is False
    assert w(None, None, {"at": "b", "dirty": 2}, None, "idle") == {"at": "b", "word": "restart held", "lapses": False}
    assert w(EARLY, {"at": "a"}, None, "ao-new", "idle") is None, "a superseded record has no row"


def test_the_inbox_row_and_the_told_row_read_the_one_reader():
    # the full words open with the short word
    v = {"id": "s", "state": "idle", "restart_wanted": {**EARLY, "repeat": {"ref": "TD-9"}, "decided": "repeats TD-9"}}
    assert restart_mark(v)[1].startswith("restart wanted · repeats TD-9")
    assert restart_mark({**v, "state": "working"}) is None
    assert restart_mark({"id": "s", "restart_blocked": {"at": "b", "dirty": 1, "unpushed": 0}})[1].startswith(
        "restart held"
    )
    # the told row: a plain fill mark is never told, whatever the record is
    s = _rec("s", "/r", state="exited")
    s.restart_ceiling = {"at": "a", "why": "fill", "count": 4}
    assert agent_notify._restart_at(s) == ""
    s.restart_ceiling = {"at": "a", "why": "fill", "count": 4, "held": True}
    assert agent_notify._restart_at(s) == "a"
    s.restart_ceiling, s.restart_wanted, s.state = None, EARLY, "idle"
    assert agent_notify._restart_at(s) == EARLY["at"]


# -- step 2: the row word and the status


def test_td1711s_case_an_early_restart_reads_its_word_and_the_card_needs_you(tmp_path):
    root, r = _one(tmp_path)
    c = _by_id(_cards({root: r}, [_marked("g1", root, "TD-001", restart_wanted=EARLY)]))["r#TD-001"]
    t = c["top"]
    assert t["state"] == "restart wanted · early" and t["restart_word"] and t["restart_home"]
    assert t["holder"]["id"] == "g1"
    assert c["status"] == "needs you" and c["restart_home"] and c["stalled_holder"] is None
    # the word opens the record's Focus, drawn amber whatever its first word
    html = _row_html({**t, "depth": 1})
    assert '<a class="qstate s-restart" href="/focus/g1" title="open g1">restart wanted · early</a>' in html
    # the header draws no word beside its pill: the pill counts the Do item
    (shaped,) = _shaped(_cards({root: r}, [_marked("g1", root, "TD-001", restart_wanted=EARLY)]))
    head = _card_html(shaped).split('<div class="qrows">')[0]
    assert "restart wanted" not in head and ">stalled<" not in head


def test_each_mark_reads_its_word_working_at_its_ceiling_too(tmp_path):
    root, r = _one(tmp_path)
    for rec, word in (
        (
            _marked("g", root, "TD-001", restart_wanted={**EARLY, "repeat": {"ref": "TD-9"}}),
            "restart wanted · repeats TD-9",
        ),
        (_marked("g", root, "TD-001", restart_ceiling={"at": "a", "count": 3}), "restarts exhausted"),
        (_marked("g", root, "TD-001", restart_ceiling={"at": "a", "why": "lost-brief"}), "brief lost twice"),
        (_marked("g", root, "TD-001", restart_blocked={"at": "a", "dirty": 1}), "restart held"),
        (_marked("g", root, "TD-001", state="working", restart_ceiling={"at": "a", "count": 3}), "restarts exhausted"),
    ):
        c = _by_id(_cards({root: r}, [rec]))["r#TD-001"]
        assert (c["top"]["state"], c["status"]) == (word, "needs you"), word


def test_no_mark_still_reads_stalled_and_the_persons_own_claim_reads_with_you(tmp_path):
    root, r = _one(tmp_path)
    c = _by_id(_cards({root: r}, [_rec("g1", root, "TD-001", state="idle")]))["r#TD-001"]
    assert c["top"]["state"] == "stalled" and not c["top"]["restart_word"] and not c["restart_home"]
    both = [_marked("g1", root, "TD-001", restart_wanted=EARLY), _mine("p", root, "TD-001")]
    t = _by_id(_cards({root: r}, both))["r#TD-001"]["top"]
    assert t["state"] == "with you in p" and not t["restart_word"]
    assert t["restart_home"], "the restart row is homed there all the same"


def test_a_holder_on_two_cards_homes_its_row_on_the_newest_claim_and_the_other_card_is_never_stalled(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "one", Priority="High"), _entry(2, "two", Priority="High")])
    g = _marked("g1", root, "TD-001", "TD-002", restart_wanted=EARLY)  # one `at`: the later in `progress` wins
    cards = _by_id(_cards({root: r}, [g]))
    home, other = cards["r#TD-002"], cards["r#TD-001"]
    assert home["status"] == "needs you" and home["top"]["restart_home"]
    assert other["top"]["state"] == "restart wanted · early" and not other["top"]["restart_home"]
    assert other["status"] == "ready" and not other["restart_home"], "nothing else on it: never *stalled*"


def test_a_homed_child_row_makes_its_card_need_you_and_the_header_keeps_the_top_entrys_word(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "parent", Priority="High"), _entry(2, "part", Part_of="TD-001")])
    q = _cards({root: r}, [_marked("g1", root, "TD-002", restart_wanted=EARLY)])
    c = _by_id(q)["r#TD-001"]
    assert c["restart_home"] and c["status"] == "needs you" and not c["top"]["restart_home"]
    (child,) = c["rows"]
    assert child["restart_home"] and child["state"] == "restart wanted · early"
    (shaped,) = _shaped(q)
    head = _card_html(shaped).split('<div class="qrows">')[0]
    assert ">waiting<" in head, "the top entry's own word"


def test_a_press_mark_held_back_drops_the_word_and_the_card_still_needs_you(tmp_path):
    root, r = _one(tmp_path)
    q = _cards({root: r}, [_marked("g1", root, "TD-001", restart_wanted=EARLY)])
    marked = {**r, "ledger": {**r["ledger"], "entries": [{**r["ledger"]["entries"][0], "applying": {"answer": "Go"}}]}}
    (out,) = queue.lay_held(q, {root: marked})["cards"]
    assert out["top"]["state"].startswith("answered") or out["top"]["state"].startswith("applying")
    assert out["top"]["restart_word"] is False and out["top"]["restart_home"]
    assert out["status"] == "needs you"
    assert "s-restart" not in _row_html({**out["top"], "depth": 1})


# -- step 3: the row on the card


def _restart(sid, **kw):
    return state(sid, "restart", at=at(1), **kw)


def test_the_restart_row_is_a_do_item_on_its_card_and_in_no_inbox_section():
    secs, v = holder_view([_restart("g1", record_restartable=True)], [hold("g1", "s#TD-20", at(1))])
    (e,) = secs["needs"]
    assert (e["home"], e["on_card"], e["tied"]) == ("queue", "s#TD-20", {"by": "holder", "ref": "s#TD-020"})
    assert secs["queue_n"] == 1
    (c,) = [c for c in v["in_progress"] + v["up_next"] + v["waiting"] if c["id"] == "s#TD-20"]
    (m,) = [m for m in c["wants"]["do"] if m.get("holder")]
    assert m["id"] == "g1:restart" and "qistart" not in str(m["html"])
    # an exited holder holding no entry an open card holds keeps its row in the Inbox
    secs, _v = holder_view([_restart("g2")], [hold("g2", "s#TD-3", at(1))])
    assert [e["home"] for e in secs["needs"]] == ["inbox"]


def test_a_dismissed_or_snoozed_restart_row_is_drawn_on_its_card_all_the_same():
    row = _restart("g1")
    for raw in (f"dismissed:{row['at']}", "2999-01-01T00:00:00Z"):
        secs, _v = holder_view([row], [hold("g1", "s#TD-20", at(1))], {"g1|restart": raw})
        assert [(e["home"], e["on_card"]) for e in secs["needs"]] == [("queue", "s#TD-20")], raw
        assert not secs["snoozed"], "not in the Inbox's *Snoozed (n)* fold"
    # in the Inbox, the dismissal stands
    secs, _v = holder_view([row], [hold("g1", "s#TD-3", at(1))], {"g1|restart": f"dismissed:{row['at']}"})
    assert not secs["needs"] and not secs["snoozed"]


def test_a_stuck_line_goes_under_the_pending_row_first_then_the_restart_row():
    ranks = [_holder_rank({"row": r}) for r in ("permission", "restart", "stalled", "limited")]
    assert ranks == [0, 1, 2, 2]


def test_a_stalled_row_listed_before_the_restart_row_leaves_the_stuck_line_to_the_restart_row():
    # TD-1916: the rank is held in its use — a first-wins pick would keep the line on the stalled row
    stalled = {"row": "stalled", "sid": "s", "home": "inbox"}
    restart = {"row": "restart", "sid": "s", "home": "inbox"}
    line = {"row": "stuck", "id": "ask:m-1", "home": "inbox", "at": "a", "reason_base": "r", "text": "stuck 1h",
            "actor": {"id": "s"}}  # fmt: skip
    out = {"needs": [stalled, restart, line], "steering": [], "waiting": [], "snoozed": []}
    stuck_onto_holders(out, lambda r: "")
    assert restart["stuck_lines"] == [{"id": "ask:m-1", "text": "stuck 1h"}]
    assert "stuck_lines" not in stalled and out["needs"] == [stalled, restart], "the stuck row is a line, no row"


def test_the_rows_record_restartable_is_the_records_own_flag_and_the_merged_one_is_unchanged():
    view = {"id": "s", "name": "s", "state": "exited", "restartable": False, "seat": "fact-check",
            "restart_ceiling": {"at": "a", "why": "fill", "count": 4}}  # fmt: skip
    (row,) = [r for r in state_rows([view]) if r["row"] == "restart"]
    assert row["restartable"] is True and row["record_restartable"] is False, "a fills-exhausted seat's own Restart"
    view = {"id": "w", "name": "w", "state": "idle", "restartable": True, "restart_wanted": EARLY}
    (row,) = [r for r in state_rows([view]) if r["row"] == "restart"]
    assert row["record_restartable"] is True


def _render(e, mode):
    from shiftlead.ui.app import templates

    if mode == "card":
        return templates.get_template("queue_mail.html").render(e=e, section="needs", origin="", board_choices={})
    return templates.get_template("inbox_rows.html").render(rows=[e], section="needs")


def test_the_card_draws_restart_where_the_record_can_and_open_with_no_resume_or_dismiss(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    e = _restart("g1", want="do", record_restartable=True, restartable=True, lapses=False)
    html = _render(e, "card")
    assert 'data-act="restart" data-id="g1"' in html and 'href="/focus/g1"' in html
    assert 'data-act="resume"' not in html and "Dismiss" not in html and "Snooze" not in html
    # a seat's, or an unsupervised record's, draws Open alone
    html = _render({**e, "record_restartable": False}, "card")
    assert 'data-act="restart"' not in html and 'href="/focus/g1"' in html


def test_the_inbox_restart_row_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    # a *fills exhausted* row still draws its mark-clearing Restart from the merged `restartable`, beside Resume and
    # its Dismiss
    e = _restart("g1", restartable=True, record_restartable=False, lapses=True)
    html = _render(e, "inbox")
    assert 'data-act="restart" data-id="g1"' in html and 'data-act="resume"' in html
    assert 'data-until="dismissed:' in html
