# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1468 slice 1 (design §4.5 screen 6 *Every item that needs the person draws on a card*, screen 12 *Recently
completed* and *In progress*): an item that needs the person — an open ask or steer to them, an undecided Decide or
Do line — whose entry no open card holds draws on the completed card that holds it, **kept**, else on a **loose
card** `loose:<ref>`; an item that needs nobody stays in the Inbox."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from test_ui_queue import NOW, at, client, fake, mail, queue

from sessionorc import notify
from sessionorc.queue import KEPT, context_pr, holder_claims, kept_or_loose, mail_card, pr_refs
from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import (
    apply_picks,
    asked_entries,
    attach,
    card_index,
    covered_by,
    design_link,
    item_home,
    items_n,
    line_names,
    queue_picks,
    queue_view,
    split_later,
)

pytestmark = pytest.mark.unit


def drawn(e, sec):
    return f'<div class="mailrow" data-msg="{e.get("id")}">{e.get("subject") or e.get("text")}</div>'


def view(entries=(), boards=(), picks=None, teams=None):
    q = queue()
    secs = inbox_sections(list(entries), now=NOW, boards=list(boards), cards=card_index(q))
    v = queue_view(q, NOW, attach(secs, drawn))
    return secs, (apply_picks(v, queue_picks(picks or {}), teams or {}) if picks is not None else v)


def test_the_index_keys_a_completed_cards_entries_kept():
    idx = card_index(queue())
    assert idx[KEPT + "s#TD-003"] == ("s#TD-3", "s#TD-3") and idx[KEPT + "s#TD-002"] == ("s#TD-1", "s#TD-2")
    assert idx[KEPT + "TD-003"] == ("s#TD-3", "s#TD-3")  # one repo's completed cards alone hold it: bare too
    assert "s#TD-003" not in idx and "TD-003" not in idx  # no open card's lookup meets it
    # the Inbox's read omits the entries, keeping the ids
    q = queue()
    for c in q["completed"]:
        c.pop("entries"), c.pop("titles")
    assert card_index(q)[KEPT + "s#TD-002"] == ("s#TD-1", "s#TD-2")


def test_an_open_ask_about_an_archived_entry_draws_on_its_kept_card_and_a_note_stays():
    ask = mail("m1", "merge #13?", about="TD-3")
    note = mail("m2", "TD-3 shipped", kind="note")
    secs, v = view([ask, note])
    (a,) = [e for e in secs["needs"] if e["id"] == "m1"]
    assert (a["home"], a["on_card"], a["on_row"]) == ("queue", "s#TD-3", "s#TD-3")
    assert a["tied"] == {"by": "about", "ref": "s#TD-003"}
    assert secs["queue_n"] == 1 and secs["count"] == 1  # the Queue tab's; both tabs add up to what waits
    (n,) = [e for e in secs["fyi"] if e["id"] == "m2"]
    assert n["home"] == "inbox"
    # drawn as a card at the head of Recently completed, outside its window (30 h ago) and its count, *needs you*
    (k,) = v["kept"]
    assert k["id"] == "s#TD-3" and k["status"] == "needs you" and k["wants"]["n"]["decide"] == 1
    assert k["top"]["archived"] and k["top"]["show"] == "TD-3"
    assert "TD-3" not in [ln["show"] for ln in v["completed"]["lines"]]
    assert v["completed"]["counts"]["week"] == 3  # TD-9's row and TD-1's two: TD-3 is out of the count
    assert v["n"]["needs_you"] == 2  # TD-30's own and the kept card
    # once the ask closes, it is its line again
    _, v = view([{**ask, "closed_reason": "answered"}])
    assert v["kept"] == [] and "TD-3" in [ln["show"] for ln in v["completed"]["lines"]]


def test_a_steer_and_a_decide_line_about_an_archived_entry_are_kept_a_watch_line_is_not():
    steer = mail("m3", "TD-2 next?", kind="steer", bound="2026-10-17T00:00:00+00:00", default="go")
    line = {"row": "board", "id": "b1", "kind": "decide", "repo_name": "s", "due": "2026-10-16",
            "text": "Ship it? Context: TD-2. Due: 2026-10-16"}  # fmt: skip
    watch = {**line, "id": "b2", "kind": "watch"}
    decided = {**line, "id": "b3", "answered": True, "stale": True}
    secs, v = view([steer], [line, watch, decided])
    homes = {e["id"]: e["on_card"] for k in ("needs", "steering", "waiting") for e in secs[k]}
    assert homes == {"m3": "s#TD-1", "b1": "s#TD-1", "b2": "", "b3": ""}
    (k,) = v["kept"]
    assert k["id"] == "s#TD-1" and k["wants"]["n"]["decide"] == 2 and k["of"] == 2


def test_an_ask_naming_an_entry_no_card_holds_draws_on_its_loose_card():
    ask = mail("m4", "is other#TD-9 done?")
    again = mail("m5", "and now?", about="other#TD-9")
    bare = mail("m6", "TD-99, again?")  # found nowhere: keyed by its sender's repo
    secs, v = view([ask, again, bare])
    homes = {e["id"]: (e["on_card"], e["on_row"], e["tied"]) for e in secs["needs"]}
    assert homes["m4"] == ("loose:other#TD-009", "other#TD-009", {"by": "words", "ref": "other#TD-009"})
    assert homes["m5"][0] == "loose:other#TD-009"  # two items about one entry share one card
    assert homes["m6"][0] == "loose:s#TD-099"
    assert secs["queue_n"] == 3 and secs["count"] == 3
    # with no repo found, a bare ref matches no key and makes no loose card: the Inbox (TD-1541)
    secs, v = view([mail("m6", "TD-99, again?", repo=None), mail("m9", "or other#TD-9?", repo=None)])
    homes = {e["id"]: e["on_card"] or e["home"] for e in secs["needs"]}
    assert homes == {"m6": "inbox", "m9": "loose:other#TD-009"}, "its qualified ref still draws"
    secs, v = view([ask, again, bare])
    loose = {c["id"]: c for c in v["loose"]}
    assert set(loose) == {"loose:other#TD-009", "loose:s#TD-099"}
    one = loose["loose:other#TD-009"]
    assert one["status"] == "needs you" and one["wants"]["n"]["decide"] == 2 and one["top"]["id"] == ""
    assert one["top"]["title"] == "is other#TD-9 done?" and one["repos"] == ["other"] and one["ids"] == []
    assert v["n"]["in_progress"] == 3 and v["n"]["needs_you"] == 3  # TD-10's card and two loose; TD-30 and two
    # mail about no entry, and a note naming one, stay in the Inbox
    secs, v = view([mail("m7", "no id here"), mail("m8", "other#TD-9 went in", kind="note")])
    assert all(e["home"] == "inbox" for k in ("needs", "fyi") for e in secs[k]) and v["loose"] == []


def test_the_needs_you_switch_keeps_kept_and_loose_cards_and_a_chip_keeps_a_loose_one_for_its_repo():
    entries = [mail("m1", "merge?", about="TD-3"), mail("m4", "is other#TD-9 done?"), mail("m6", "TD-99?")]
    _, v = view(entries, picks={"filter": "needs-you"})
    on = lambda cs: [c["id"] for c in cs if not c["off"]]  # noqa: E731
    assert on(v["kept"]) == ["s#TD-3"] and sorted(on(v["loose"])) == ["loose:other#TD-009", "loose:s#TD-099"]
    assert all(ln["off"] for ln in v["completed"]["lines"]) and all(o["off"] for o in v["other"])
    assert v["summary"]["needs"] == 4  # TD-30, the kept card and the two loose
    _, v = view(entries, picks={"team": "ot"}, teams={"ot": "other"})
    assert on(v["loose"]) == ["loose:other#TD-009"] and on(v["kept"]) == []  # the bare one: no chip's
    _, v = view(entries, picks={"find": "TD-99"})
    assert on(v["loose"]) == ["loose:s#TD-099"]  # a loose card answers the find


def test_kept_or_loose_and_mail_card_read_alike():
    idx = card_index(queue())
    assert kept_or_loose(["s#TD-003"], idx) == ("s#TD-3", "s#TD-3", "s#TD-003")
    assert kept_or_loose(["x#TD-001", "s#TD-002"], idx) == ("s#TD-1", "s#TD-2", "s#TD-002")  # the first kept
    assert kept_or_loose(["x#TD-001"], idx) == ("loose:x#TD-001", "x#TD-001", "x#TD-001")
    assert kept_or_loose([], idx) is None and kept_or_loose(["x#TD-001"], {}) is None
    assert mail_card("TD-3", "merge?", idx) is None  # needs nobody: the Inbox
    assert mail_card("TD-3", "merge?", idx, "s", needs=True) == ("s#TD-3", "s#TD-3")
    assert mail_card("TD-21", "which?", idx, "s", needs=True) == ("s#TD-20", "s#TD-21")  # an open card first
    assert mail_card("TD-3", "merge?", idx, needs=True) is None  # no repo: its bare ref matches no key (TD-1541)


def test_a_loose_cards_address_is_percent_encoded_with_no_row():
    path = notify.queue_path("loose:other#TD-9", "other#TD-9", "m-1")
    assert path == "/card/loose%3Aother%23TD-9?item=m-1"
    assert parse_qs(urlsplit(path).query) == {"item": ["m-1"]}  # the card is the path's, a page of its own (TD-1762)
    assert unquote(urlsplit(path).path) == "/card/loose:other#TD-9"
    assert notify.queue_path("s#TD-3", "s#TD-3", "m-1") == "/card/s%23TD-3?row=s%23TD-3&item=m-1"


def test_the_page_draws_a_kept_card_and_a_loose_card_and_the_inbox_neither(tmp_path, monkeypatch):
    entries = [mail("m1", "merge #13?", about="TD-3"), mail("m4", "is other#TD-9 done?")]
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    html = c.get("/queue").text
    done = html[html.index('id="qcompleted"') : html.index('id="qinprogress"')]
    assert 'class="qcards qkepts"' in done and 'data-card="s#TD-3"' in done and "merge #13?" in done
    assert done.index('data-card="s#TD-3"') < done.index('class="rlist qdone"')  # at the head of the group
    prog = html[html.index('id="qinprogress"') : html.index('id="qwaiting"')]
    assert 'data-card="loose:other#TD-009"' in prog and prog.index('data-other="1"') < prog.index("loose:other")
    assert 'data-status="needs you"' in prog[prog.index("loose:other") - 400 :]
    inbox = c.get("/inbox").text
    rows = inbox[inbox.index('id="rows-needs"') : inbox.index('id="sec-fyi"')]
    assert "merge #13?" not in rows and "is other#TD-9 done?" not in rows
    got = c.get("/api/person/inbox?counts=1").json()
    assert got["queue_n"] == 2 and got["needs"] == 2


def test_a_lone_kept_card_is_counted_shown_and_reads_one_card_needs_you():
    """The review of #3193: the summary counts a kept card among the cards shown, so a lone one reads *1 card needs
    you* with the switch on."""
    _, v = view([mail("m1", "merge #13?", about="TD-3")], picks={"filter": "needs-you"})
    assert v["shown"] == 2 and v["summary"]["needs"] == 2  # TD-30's card and the kept one
    q = queue()
    q["cards"] = []
    secs = inbox_sections([mail("m1", "merge #13?", about="TD-3")], now=NOW, cards=card_index(q))
    v = apply_picks(queue_view(q, NOW, attach(secs, drawn)), queue_picks({"filter": "needs-you"}), {})
    assert v["shown"] == 1 and v["summary"] == {"cards": 1, "needs": 1, "of": 1}


def test_a_running_steer_alone_leaves_its_kept_or_loose_card_steer():
    """The review of #3193: a steer whose clock runs is no *needs you*, as on an open card (`_mail_status`)."""
    steer = mail("m3", "other#TD-9 next?", kind="steer", bound="2026-10-17T00:00:00+00:00", default="go")
    _, v = view([steer])
    (c,) = v["loose"]
    assert c["status"] == "steer" and v["n"]["needs_you"] == 1  # TD-30's alone
    _, v = view([steer], picks={"filter": "needs-you"})
    assert v["loose"][0]["off"]


# -- slice 2: an item whose only anchor is a PR (§4.5 screen 6 *Every item that needs the person draws on a card*)


def pr_view(entries, pr_refs):
    q = {**queue(), "pr_refs": pr_refs}
    secs = inbox_sections(list(entries), now=NOW, cards=card_index(q))
    return secs, queue_view(q, NOW, attach(secs, drawn))


def test_pr_refs_reads_open_prs_by_branch_then_title_and_recent_by_title_then_branch():
    prs = {
        "open": [
            {"number": 160, "branch": "td20-split", "title": "TD-30: other words"},
            {"number": 161, "branch": "fix-x", "title": "TD-21: the build"},
            {"number": 162, "branch": "fix-y", "title": "no entry"},
            {"number": 163, "branch": "fix-z", "title": "other#TD-9 upstream"},
        ],
        "recent": [
            {"number": 160, "branch": "td40-x", "title": "TD-40"},  # open wins
            {"number": 164, "branch": "td9-x", "title": "TD-3: the archived one"},
            {"number": 165, "branch": "td9-x", "title": "no ref"},
            {"number": True, "title": "TD-1"},
            {"number": 162, "branch": "fix-y", "title": "TD-8: named in its month alone"},
            {"number": 166, "branch": 7, "title": None},  # an odd shape reads as no entry, never raises
        ],
    }
    assert pr_refs("s", prs) == {
        "s#160": "s#TD-020",
        "s#161": "s#TD-021",
        "s#162": "s#TD-008",
        "s#163": "other#TD-009",
        "s#164": "s#TD-003",
        "s#165": "s#TD-009",
    }
    assert pr_refs("s", None) == {} and pr_refs("s", {"error": "x"}) == {}


def test_a_merge_ask_carrying_only_a_pr_draws_on_the_card_of_the_entry_its_pr_names():
    ask = mail("m1", "merge it?", pr=164, repo="s")
    secs, v = pr_view([ask], {"s#164": "s#TD-021"})
    (a,) = secs["needs"]
    assert (a["home"], a["on_card"], a["on_row"]) == ("queue", "s#TD-20", "s#TD-21")
    assert a["tied"] == {"by": "pr", "ref": "s#TD-021"}
    assert not v["loose"]  # none on `loose:s#164`
    # with no repo (none stamped, no orphan stamp, no record) it has no repo to search: the Inbox
    secs, v = pr_view([mail("m2", "merge it?", pr=164, repo=None)], {"s#164": "s#TD-021"})
    assert secs["needs"][0]["home"] == "inbox" and not v["loose"]


def test_a_pr_only_item_whose_entry_is_on_a_completed_card_draws_on_that_kept_card():
    secs, v = pr_view([mail("m1", "merge it?", pr=164, repo="s")], {"s#164": "s#TD-003"})
    (a,) = secs["needs"]
    assert (a["on_card"], a["on_row"], a["tied"]) == ("s#TD-3", "s#TD-3", {"by": "pr", "ref": "s#TD-003"})
    assert [k["id"] for k in v["kept"]] == ["s#TD-3"]


def test_a_pr_only_item_naming_no_entry_draws_on_its_prs_loose_card_counted_on_the_queue_tab():
    steer = {**mail("m2", "which way?", kind="steer", about="#170", repo="s"), "paused_at": at(0)}
    secs, v = pr_view([mail("m1", "merge it?", pr=170, repo="s"), steer], {})
    homes = {e["id"]: (e["home"], e["on_card"], e["on_row"], e["tied"]) for e in secs["needs"]}
    assert homes["m1"] == ("queue", "loose:s#170", "s#170", {"by": "pr", "ref": "s#170"})
    assert homes["m2"] == homes["m1"]  # an `about` of `#n` is the same PR: one card
    assert secs["queue_n"] == 2 and secs["count"] == 2
    (c,) = v["loose"]
    assert c["id"] == "loose:s#170" and c["top"]["show"] == "#170" and c["status"] == "needs you"
    # an entry the PR names that no card holds: that entry's loose card, not the PR's
    secs, v = pr_view([mail("m1", "merge it?", pr=170, repo="s")], {"s#170": "other#TD-009"})
    assert secs["needs"][0]["on_card"] == "loose:other#TD-009"


def test_a_pr_only_note_stays_in_the_inbox_and_an_ask_naming_an_entry_ignores_its_pr():
    secs, _v = pr_view([mail("m1", "merged", kind="note", pr=164, repo="s")], {"s#164": "s#TD-021"})
    assert secs["fyi"][0]["home"] == "inbox"
    secs, _v = pr_view([mail("m2", "merge?", about="TD-20", pr=164, repo="s")], {"s#164": "s#TD-021"})
    assert secs["needs"][0]["on_row"] == "s#TD-20"


def test_telegrams_card_reads_a_pr_only_item_alike():
    idx = card_index({**queue(), "pr_refs": {"s#164": "s#TD-021"}})
    assert mail_card(None, "merge it?", idx, "s", True, 164) == ("s#TD-20", "s#TD-21")
    assert mail_card("#170", "which way?", idx, "s", True) == ("loose:s#170", "s#170")
    assert mail_card(None, "merge it?", idx, None, True, 164) is None
    assert mail_card(None, "merge it?", idx, "s", False, 164) is None


# -- slice 3: a stopped holder's state rows (§4.5 screen 6 *One place for each thing that needs the person*)


def hold(sid, qid, at=None, source="declared", n=0):
    return {"sid": sid, "qid": qid, "source": source, "at": at, "n": n}


def test_holder_claims_reads_declared_first_newest_then_the_later_in_progress():
    idx = card_index(queue())
    pick = lambda *hs: holder_claims(list(hs), idx)  # noqa: E731
    # the newest declared claim an open card holds
    assert pick(hold("a", "s#TD-20", at(3), n=0), hold("a", "s#TD-21", at(1), n=1)) == {"a": "s#TD-021"}
    # one with no readable `at` the oldest
    assert pick(hold("a", "s#TD-20", None, n=1), hold("a", "s#TD-21", at(5), n=0)) == {"a": "s#TD-021"}
    # a tie: the later in the record's `progress`
    assert pick(hold("a", "s#TD-20", at(1), n=1), hold("a", "s#TD-21", at(1), n=0)) == {"a": "s#TD-020"}
    # a derived claim, however new, never weighs against a declared one; alone it is read
    assert pick(hold("a", "s#TD-20", at(5)), hold("a", "s#TD-21", at(0), "derived", 1)) == {"a": "s#TD-020"}
    assert pick(hold("a", "s#TD-21", at(0), "derived")) == {"a": "s#TD-021"}
    # a claim on an entry no open card holds passes to the next; none left, no card
    assert pick(hold("a", "s#TD-3", at(0), n=1), hold("a", "s#TD-20", at(2), n=0)) == {"a": "s#TD-020"}
    assert pick(hold("a", "s#TD-3", at(0))) == {}
    # two seats on one entry: each its own
    assert pick(hold("a", "s#TD-20", at(1)), hold("b", "s#TD-20", at(1))) == {"a": "s#TD-020", "b": "s#TD-020"}


def state(sid, row, **kw):
    return {"row": row, "id": f"{sid}:{row}", "sid": sid, "name": sid, "subject": row, "text": "t", **kw}


def holder_view(states, holds, snoozed=None):
    q = {**queue(), "holds": holds}
    secs = inbox_sections([], now=NOW, states=states, cards=card_index(q), attention_snoozed=snoozed)
    return secs, queue_view(q, NOW, attach(secs, drawn, start=lambda c, i: {"item": i} if i else {}))


def test_a_stopped_holders_state_rows_draw_on_its_card_and_a_seat_holding_nothing_keeps_them_in_the_inbox():
    rows = [
        state("g1", "permission", call="t1", deadline="", left="2 min"),
        state("g2", "limited"),
        state("g3", "needs"),
        state("g4", "permission", call="t9"),  # holds nothing an open card holds
        state("g5", "unpushed"),  # not one of the five
    ]
    holds = [
        hold("g1", "s#TD-21", at(1)),
        hold("g2", "s#TD-20", at(1)),
        hold("g3", "s#TD-20", at(2)),
        hold("g4", "s#TD-3", at(1)),
        hold("g5", "s#TD-20", at(1)),
    ]
    secs, v = holder_view(rows, holds)
    homes = {e["sid"]: (e["home"], e["on_card"], e["on_row"], e["tied"]) for e in secs["needs"]}
    assert homes["g1"] == ("queue", "s#TD-20", "s#TD-21", {"by": "holder", "ref": "s#TD-021"})
    assert homes["g2"][:2] == ("queue", "s#TD-20") and homes["g3"][:2] == ("queue", "s#TD-20")
    assert homes["g4"][0] == "inbox"
    # the Queue tab counts the three, the Inbox tab the rest: together what waits on the person
    assert (
        secs["queue_n"] == 3 and secs["count"] - secs["queue_n"] == len([r for r in rows if state_kind_counts(r)]) - 3
    )
    (c,) = [c for c in v["in_progress"] + v["up_next"] + v["waiting"] if c["id"] == "s#TD-20"]
    do = c["wants"]["do"]
    assert [m["id"] for m in do if m.get("holder")] == ["g1:permission", "g2:limited", "g3:needs"]
    assert c["status"] == "needs you" and c["wants"]["n"]["do"] >= 3
    # no Start session of their own, and outside the header's count
    assert all(not m.get("holder") or "qistart" not in str(m["html"]) for m in do)
    assert items_n(c["wants"]) == sum(1 for m in do + c["wants"]["decide"] if not (m.get("holder") or m.get("red")))


def state_kind_counts(r):
    return r["row"] in ("permission", "limited", "needs", "unpushed")


def test_a_snoozed_stalled_row_stays_in_the_snoozed_fold():
    rows = [state("g1", "stalled")]
    secs, _v = holder_view(rows, [hold("g1", "s#TD-20", at(1))], {"g1|stalled": "2999-01-01T00:00:00Z"})
    assert [e["home"] for e in secs["snoozed"]] == ["inbox"] and not secs["needs"]
    # its time passed: drawn on the card
    secs, _v = holder_view(rows, [hold("g1", "s#TD-20", at(1))], {"g1|stalled": "2000-01-01T00:00:00Z"})
    assert [(e["home"], e["on_card"]) for e in secs["needs"]] == [("queue", "s#TD-20")]


def test_a_holders_permission_row_on_its_card_draws_allow_deny_with_its_call_and_no_snooze(tmp_path, monkeypatch):
    """§4.5a *Queue card: holder's state row*: the controls of *Inbox row: state* but Snooze, built from the same row
    (its record id and `call`), so a permission pushed after the page was drawn is never answered unseen; the
    *routed around* line where the seat cannot answer."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    one = ui.templates.get_template("queue_mail.html")
    perm = state("g1", "permission", call="t1", deadline="", left="2 min", want="do")
    html = one.render(e=perm, section="needs", origin="", board_choices={})
    assert 'data-act="allow" data-id="g1" data-call="t1"' in html and 'data-act="deny" data-id="g1"' in html
    assert "Snooze" not in html and "qistart" not in html and "Answer" not in html
    stalled = state("g2", "stalled", want="do", routed_to="its questions go to the techlead", routed_why="limited")
    html = one.render(e=stalled, section="needs", origin="", board_choices={})
    assert "Snooze" not in html and 'href="/focus/g2"' in html
    assert 'class="meta routed"' in html and "its questions go to the techlead" in html


# -- TD-1552: a board line whose `Context:` names only a PR ties by that PR (§4.5 screen 6 *Every item that needs the
# person draws on a card*)


def pr_line(context="PR #164", lid="b1", kind="decide", **kw):
    return {"row": "board", "id": lid, "kind": kind, "repo_name": "s", "due": "2026-10-16",
            "text": f"Ship it? Context: {context}. Due: 2026-10-16", **kw}  # fmt: skip


def pr_idx(refs):
    return card_index({**queue(), "pr_refs": refs})


def home_of(line, refs, needs=True):
    h = item_home(line, pr_idx(refs), needs=needs)
    return h["home"], h["on_card"], h["on_row"], h["tied"]


def test_context_pr_reads_a_bare_hash_number_alone():
    assert [context_pr(t) for t in ("PR #3142", "#3142", "(#3142)", "TD-9 / PR #164 and #170")] == [
        3142,
        3142,
        3142,
        164,
    ]
    assert [context_pr(t) for t in ("agent-cadence#164", "owner/name#12", "a.b#3", "PR#164", "TD-12", "", None)] == [
        None
    ] * 7


def test_an_undecided_pr_only_decide_line_draws_on_the_open_card_of_its_prs_entry():
    want = ("queue", "s#TD-20", "s#TD-21", {"by": "pr", "ref": "s#TD-021"})
    for context in ("PR #164", "#164", "the review (#164)"):
        assert home_of(pr_line(context), {"s#164": "s#TD-021"}) == want
    # #164 found only in the month's merged PRs, by its title
    refs = pr_refs("s", {"open": [], "recent": [{"number": 164, "branch": "fix-x", "title": "TD-21: the build"}]})
    assert home_of(pr_line(), refs) == want


def test_a_pr_only_line_whose_entry_is_archived_draws_on_its_kept_card_else_its_loose_card():
    assert home_of(pr_line(), {"s#164": "s#TD-003"}) == ("queue", "s#TD-3", "s#TD-3", {"by": "pr", "ref": "s#TD-003"})
    assert home_of(pr_line(), {"s#164": "s#TD-077"}) == (
        "queue", "loose:s#TD-077", "s#TD-077", {"by": "pr", "ref": "s#TD-077"})  # fmt: skip


def test_a_pr_only_line_naming_no_entry_draws_on_its_prs_loose_card_counted_on_the_queue_tab():
    q = {**queue(), "pr_refs": {}}
    secs = inbox_sections([], now=NOW, boards=[pr_line()], cards=card_index(q))
    (b,) = [e for e in secs["needs"] if e["id"] == "b1"]
    assert (b["home"], b["on_card"], b["on_row"], b["tied"]) == (
        "queue",
        "loose:s#164",
        "s#164",
        {"by": "pr", "ref": "s#164"},
    )
    assert secs["queue_n"] == 1 and secs["count"] == 1  # the Queue tab's; both tabs add up to what waits
    v = queue_view(q, NOW, attach(secs, drawn))
    assert [c["id"] for c in v["loose"]] == ["loose:s#164"]


def test_a_line_that_names_no_pr_or_no_repo_stays_in_the_inbox():
    refs = {"s#164": "s#TD-021"}
    for context in ("PR#164", "agent-cadence#164"):
        assert home_of(pr_line(context), refs)[0] == "inbox"
    no_repo = {**pr_line(), "repo_name": ""}
    assert home_of(no_repo, refs)[0] == "inbox"


def test_a_context_naming_an_entry_ties_by_it_and_ignores_its_pr():
    assert home_of(pr_line("TD-20 / PR #164"), {"s#164": "s#TD-021"}) == (
        "queue", "s#TD-20", "s#TD-20", {"by": "context", "ref": "s#TD-020"})  # fmt: skip


def test_a_pr_only_line_needing_nobody_follows_its_prs_entry_to_an_open_card_alone():
    """A decided line, a `watch` or `fyi` line, and a line not yet due (`needs` false) draw on the open card of the
    PR's entry as lines naming that entry do, and stay in the Inbox where no open card holds it."""
    for line in (pr_line(), pr_line(kind="watch"), pr_line(kind="fyi"), pr_line(decided=True)):
        assert home_of(line, {"s#164": "s#TD-021"}, needs=False)[:3] == ("queue", "s#TD-20", "s#TD-21")
        assert home_of(line, {"s#164": "s#TD-003"}, needs=False)[0] == "inbox"
        assert home_of(line, {}, needs=False)[0] == "inbox"
    # not yet due: the card attachment's `coming` road
    _lf, rest, moved, _unshown = split_later({"n": 0, "groups": []}, [pr_line()], pr_idx({"s#164": "s#TD-021"}))
    assert [(e["id"], e["on_row"], e["tied"]["by"], e["later_section"]) for e in moved] == [
        ("b1", "s#TD-21", "pr", "coming")
    ]
    _lf, rest, moved, _unshown = split_later({"n": 0, "groups": []}, [pr_line()], pr_idx({"s#164": "s#TD-003"}))
    assert moved == [] and [e["id"] for e in rest] == ["b1"]


def test_a_pr_tied_line_covers_no_ledger_row_and_draws_no_design_link():
    assert line_names(pr_line()) == set()
    assert line_names({**pr_line(), "parts": ["TD-7"]}) == {"s#TD-007"}
    assert not covered_by({"name": "s", "id": "TD-21"}, asked_entries([pr_line()]))
    assert design_link(pr_line(), pr_idx({"s#164": "s#TD-021"})) == {}
