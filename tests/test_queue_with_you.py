"""TD-1284 (TD-1281's build), design §4.4 *A row's state*, *The card's status*; §4.5 screen 12 *Three wants*, *Three
verbs: Start session*: an `Owner: paul` or `decision (paul)` entry that the person's own session (`unattended:
false`) claims reads *with you in <name>* and is no want — the card falls to the ledger's next word, its item is
drawn grey after Decide and Do with its Open session and counted nowhere — while the id lists still name it the
person's, so a press on it reaches the start road."""

from __future__ import annotations

from datetime import timedelta

from markupsafe import Markup
from test_queue import NOW, _by_id, _cards, _entry, _rec, _repo

from sessionorc import queue
from sessionorc.models import Session
from shiftlead.ui.queue import _seg, apply_picks, attach, branch, card_edge, item_start, qid, queue_view


def _mine(rid: str, repo: str, *refs: str, state: str = "idle") -> Session:
    """The person's own session: interactive, claiming `refs`."""
    s = _rec(rid, repo, *refs, state=state)
    s.unattended = False
    return s


def _one(tmp_path, **fields: str):
    root, r = _repo(tmp_path, "r", [_entry(1, "the person's", Priority="High", **fields)])
    return root, r


def test_the_persons_own_session_on_their_decision_reads_with_you_and_the_card_ready(tmp_path):
    for fields, need in (({"Blocked_by": "decision (paul)"}, "decision"), ({"Owner": "paul"}, "owner")):
        sub = tmp_path / need
        sub.mkdir()
        root, r = _one(sub, **fields)
        c = _by_id(_cards({root: r}, [_mine("p", root, "TD-001")]))["r#TD-001"]
        t = c["top"]
        assert t["state"] == "with you in p" and t["with_you"] == "p" and t["needs"] == need, "it keeps its need"
        assert t["holder"] == {"id": "p", "name": "p", "state": "idle"}
        # In progress by the claim, *ready* where nothing else waits; an idle interactive holder is never *stalled*
        assert c["group"] == "in_progress" and c["status"] == "ready"
        # the id lists still name it the person's: *waits on me*, which the start road checks
        assert queue.card_entries(c) == (["r#TD-001"], [])
        # no claim: Decide or Do again, as before; the record exited, its claim is gone with it
        for recs in ([], [_mine("p", root, "TD-001", state="exited")]):
            c = _by_id(_cards({root: r}, recs))["r#TD-001"]
            assert c["status"] == "needs you" and c["top"]["state"] == "" and c["top"]["with_you"] is None


def test_an_unattended_claim_keeps_needs_you_and_the_interactive_one_is_the_holder(tmp_path):
    root, r = _one(tmp_path, Blocked_by="decision (paul)")
    worker = _rec("a-worker", root, "TD-001")  # unattended, first by id and by claim
    c = _by_id(_cards({root: r}, [worker]))["r#TD-001"]
    assert c["status"] == "needs you" and c["top"]["with_you"] is None and c["top"]["holder"]["id"] == "a-worker"
    two = [worker, _mine("z-mine", root, "TD-001"), _mine("y-mine", root, "TD-001")]
    t = _by_id(_cards({root: r}, two))["r#TD-001"]["top"]
    assert t["state"] == "with you in y-mine" and t["holder"]["id"] == "y-mine", "the first of the person's by id"


def test_a_held_entry_the_persons_session_claims_reads_held(tmp_path):
    root, r = _one(tmp_path, Owner="paul")
    r["ledger"]["entries"][0]["held"] = {"at": NOW.isoformat(), "why": "after Friday"}
    t = _by_id(_cards({root: r}, [_mine("p", root, "TD-001")]))["r#TD-001"]["top"]
    assert t["state"] == "held (person)" and t["with_you"] is None


def test_a_non_top_row_with_you_is_grey_on_its_spine_and_in_its_parents_meter(tmp_path):
    root, r = _repo(tmp_path, "r", [
        _entry(1, "the parent", Priority="High", Owner="paul"),
        _entry(2, "a part", Priority="High", Part_of="TD-001", Blocked_by="decision (paul)"),
    ])  # fmt: skip
    q = _cards({root: r}, [_mine("p", root, "TD-002")])
    (c,) = q["cards"]
    assert c["top"]["id"] == "TD-001" and c["status"] == "needs you", "the parent still waits on the person"
    (part,) = c["rows"]
    assert part["state"] == "with you in p" and part["with_you"] == "p"
    assert branch(part) == "open" and _seg({**part, "show": "TD-2"}) == {"b": "open", "title": "TD-2: with you in p"}
    assert branch({**part, "with_you": None}) == "needs", "the same row of an unattended claim is amber"

    from shiftlead.ui.app import templates

    v = queue_view(q, NOW, {"cards": {}, "mentioned": {}})
    (shaped,) = v["in_progress"]
    assert shaped["top"]["meter"]["segs"] == [{"b": "open", "title": "TD-002: with you in p"}]
    html = templates.env.get_template("queue_row.html").module.row(shaped["rows"][0])
    assert '<span class="qstate s-with">with you in p</span>' in html
    assert "needsyou" not in html and "qpill" not in html, "no amber, and no holder pill beside the word"


def test_an_idle_interactive_holder_with_a_red_pr_is_not_stalled(tmp_path):
    root, r = _one(tmp_path, Owner="paul")
    pr = {"number": 7, "branch": "td1-x", "checks": "red", "red_since": (NOW - timedelta(days=3)).isoformat()}
    r["prs"]["open"] = [pr]
    c = _by_id(_cards({root: r}, [_mine("p", root, "TD-001")]))["r#TD-001"]
    assert c["top"]["state"] == "with you in p" and c["top"]["pr"] == 7 and c["status"] == "ready"


# -- the card ------------------------------------------------------------------------------------------------------


def _world(tmp_path, monkeypatch, asks=()):
    """A card whose only member, `samscrape#TD-60` (`Owner: paul`), the person's session `p` claims, and its
    ledger item, the Inbox's own row, attached to it; the card view, what each item was drawn with, and the card."""
    from test_ui_queue_cards import _fold_world

    from shiftlead.ui.app import _with_you, ledger_for_you

    rs, _ = _fold_world(tmp_path, monkeypatch)
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    q = qid("samscrape", "TD-60")  # samscrape#TD-060, as the reading writes it
    holder = {"id": "p", "name": "p", "state": "idle"}
    top = {"qid": q, "id": "TD-60", "repo": "samscrape", "title": "yours", "priority": "Medium", "needs": "owner",
           "state": "with you in p", "with_you": "p", "holder": holder}  # fmt: skip
    card = {"id": q, "group": "in_progress", "status": "ready", "top": top, "rows": [], "order": [q], "start": q}
    reading = {"at": NOW.isoformat(), "cards": [card]}
    fleet = [{"id": "p", "name": "p", "repo": "/x/samscrape", "state": "idle", "unattended": False,
              "progress": [{"ref": "TD-60", "status": "claimed"}]}]  # fmt: skip
    item = {**row, "home": "queue", "on_card": q, "on_row": q}
    drawn: list[dict] = []
    got = attach(
        {"needs": [item, *asks]},
        lambda e, sec: drawn.append(e) or Markup(f'<div class="mailrow">{e.get("id")}</div>'),
        (),
        lambda c, i: item_start(card, i, fleet),
        lambda c, i: _with_you(card, i),
    )
    return queue_view(reading, NOW, got, fleet=fleet), drawn, card, fleet


def test_the_item_is_no_want_counted_nowhere_and_draws_open_session(tmp_path, monkeypatch):
    v, drawn, card, fleet = _world(tmp_path, monkeypatch)
    (c,) = v["in_progress"]
    assert c["wants"]["n"] == {"decide": 0, "do": 0, "read": 0} and len(c["wants"]["with_you"]) == 1
    assert c["status"] == "ready" and c["edge"] == "working"
    assert (v["n"]["decide"], v["n"]["do"], v["n"]["needs_you"]) == (0, 0, 0)
    assert c["items_start"] is True, "the item draws its Open session: the header none"
    (e,) = drawn
    assert e["want"] == "with_you" and e["with_you"] == "p" and c["wants"]["with_you"][0]["kind"] == ""
    assert e["start"]["own"] == "p" and e["start"]["item"] == "samscrape#TD-060", "Open session, to p"
    # the start road accepts a press on it: the entry is still under *waits on me*
    assert item_start(card, "samscrape#TD-060", fleet)["ref"] == "TD-060"
    assert card_edge("in_progress", "ready", c["wants"]) == "working"
    # out of the Needs you switch
    assert apply_picks(v, {"filter": "needs-you"}, {})["in_progress"][0]["off"]
    from shiftlead.ui.app import templates

    head = templates.env.get_template("queue_card.html").module.card(c).split('<div class="qrows">')[0]
    assert 'class="qsec qwith" data-sec="with_you"' in head and "qwant" not in head and "qwpill" not in head
    assert 'data-act="ledger_start"' not in head, "the item's own Open session: none in the header"
    assert "edge-working" in head and "edge-needs" not in head


def test_the_item_draws_with_you_in_its_line_and_foot_and_no_held_by(tmp_path, monkeypatch):
    from shiftlead.ui.app import templates

    _, drawn, _, _ = _world(tmp_path, monkeypatch)
    one = templates.get_template("queue_mail.html")
    e = {**drawn[0], "held": "p", "claimed": False}  # the Inbox row names the claim's holder
    html = one.render(e=e, section="needs")
    assert '<span class="st qneed">with you in p</span>' in html
    assert "with you in p — an answer here still writes the decided line on samscrape's board" in html
    assert "claimed by p" not in html and "held by p" not in html and "waits on you, with no date" not in html
    assert ">Open session<" in html and ">Done</button>" in html, "its answers and Open session unchanged"
    # the same row with no `with_you` want, as the Inbox's *Later* draws it, is unchanged
    plain = one.render(e={**e, "want": "do"}, section="needs")
    assert "with you in" not in plain and "held by p" in plain and "waits on you, with no date" in plain


def test_the_card_draws_the_item_grey_after_decide_and_do_and_its_header_keeps_the_holder(tmp_path, monkeypatch):
    from test_ui_inbox import entry

    from shiftlead.ui.app import templates

    ask = {**entry("m-1", "ask", text="which?"), "home": "queue", "on_card": "samscrape#TD-060",
           "on_row": "samscrape#TD-060"}  # fmt: skip
    v, _, _, _ = _world(tmp_path, monkeypatch, asks=[ask])
    (c,) = v["in_progress"]
    # an open `ask` about the entry is Decide, counted, and keeps the card *needs you*
    assert c["status"] == "needs you" and c["wants"]["n"]["decide"] == 1 and c["edge"] == "needs"
    html = templates.env.get_template("queue_card.html").module.card(c)
    head = html.split('<div class="qrows">')[0]
    assert head.index('data-sec="decide"') < head.index('class="qsec qwith" data-sec="with_you"')
    assert ">Decide 1</span>" in head, "the pill counts the ask alone"
    assert 'href="/focus/p" title="holds it: p"' in head, "the header keeps its holder pill"
    assert "qstate" not in head.split('data-sec="decide"')[0], "and draws no state word for the top entry"
