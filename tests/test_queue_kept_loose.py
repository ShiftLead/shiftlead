# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1468 slice 1 (design §4.5 screen 6 *Every item that needs the person draws on a card*, screen 12 *Recently
completed* and *In progress*): an item that needs the person — an open ask or steer to them, an undecided Decide or
Do line — whose entry no open card holds draws on the completed card that holds it, **kept**, else on a **loose
card** `loose:<ref>`; an item that needs nobody stays in the Inbox."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from test_ui_queue import NOW, client, fake, mail, queue

from sessionorc import notify
from sessionorc.queue import KEPT, kept_or_loose, mail_card
from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import apply_picks, attach, card_index, queue_picks, queue_view

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
    assert a["tied"] == {"by": "about", "ref": "TD-003"}
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
    bare = mail("m6", "TD-99, again?")  # found nowhere, no repo for its sender: keyed bare
    secs, v = view([ask, again, bare])
    homes = {e["id"]: (e["on_card"], e["on_row"], e["tied"]) for e in secs["needs"]}
    assert homes["m4"] == ("loose:other#TD-009", "other#TD-009", {"by": "words", "ref": "other#TD-009"})
    assert homes["m5"][0] == "loose:other#TD-009"  # two items about one entry share one card
    assert homes["m6"][0] == "loose:TD-099"
    assert secs["queue_n"] == 3 and secs["count"] == 3
    loose = {c["id"]: c for c in v["loose"]}
    assert set(loose) == {"loose:other#TD-009", "loose:TD-099"}
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
    assert on(v["kept"]) == ["s#TD-3"] and on(v["loose"]) == ["loose:TD-099", "loose:other#TD-009"]
    assert all(ln["off"] for ln in v["completed"]["lines"]) and all(o["off"] for o in v["other"])
    assert v["summary"]["needs"] == 4  # TD-30, the kept card and the two loose
    _, v = view(entries, picks={"team": "ot"}, teams={"ot": "other"})
    assert on(v["loose"]) == ["loose:other#TD-009"] and on(v["kept"]) == []  # the bare one: no chip's
    _, v = view(entries, picks={"find": "TD-99"})
    assert on(v["loose"]) == ["loose:TD-099"]  # a loose card answers the find


def test_kept_or_loose_and_mail_card_read_alike():
    idx = card_index(queue())
    assert kept_or_loose(["s#TD-003"], idx) == ("s#TD-3", "s#TD-3", "s#TD-003")
    assert kept_or_loose(["x#TD-001", "s#TD-002"], idx) == ("s#TD-1", "s#TD-2", "s#TD-002")  # the first kept
    assert kept_or_loose(["x#TD-001"], idx) == ("loose:x#TD-001", "x#TD-001", "x#TD-001")
    assert kept_or_loose([], idx) is None and kept_or_loose(["x#TD-001"], {}) is None
    assert mail_card("TD-3", "merge?", idx) is None  # needs nobody: the Inbox
    assert mail_card("TD-3", "merge?", idx, needs=True) == ("s#TD-3", "s#TD-3")
    assert mail_card("TD-21", "which?", idx, needs=True) == ("s#TD-20", "s#TD-21")  # an open card first


def test_a_loose_cards_address_is_percent_encoded_with_no_row():
    path = notify.queue_path("loose:other#TD-9", "other#TD-9", "m-1")
    assert path == "/queue?card=loose%3Aother%23TD-9&item=m-1"
    assert parse_qs(urlsplit(path).query) == {"card": ["loose:other#TD-9"], "item": ["m-1"]}
    assert notify.queue_path("s#TD-3", "s#TD-3", "m-1") == "/queue?card=s%23TD-3&row=s%23TD-3&item=m-1"


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
