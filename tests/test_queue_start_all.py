"""TD-1340, design §4.5 screen 12 *Started from the header on a card with items* (TD-1338), §4.5a *Queue card:
Start session / Open session*: the header draws its Start session beside the items' wherever two or more of the
card's items count (`items_n`), with its own title (`card-start-all`), and its press — counted afresh at the road —
opens on the walk sentence (`WORK_ALL`); with one item the header draws none, and with fewer at the press the
`why_key` sentence stands, whatever the page drew."""

from __future__ import annotations

from test_queue import NOW
from test_queue_start import TAIL, _q, _rec
from test_ui_inbox import entry
from test_ui_inbox_ledger import MANAGER, _start_world

from shiftlead import repoconfig
from shiftlead.ui.queue import card_wants, items_n, queue_view, walk_mine

CID = "samscrape#TD-020"
ALL = "Starts one session for every item on this card"  # `card-start-all`'s title
ONE = "Starts your own session on this card"  # `card-start`'s
ITEM = {"section": "needs", "id": "m-1", "item": "m-1", "html": "", "kind": "decide", "want": "decide",
        "red": False, "running": False, "on_row": CID}  # fmt: skip


def _item(mid: str, **kw) -> dict:
    return {**ITEM, "id": mid, "item": mid, **kw}


RED = _item("red_pr:s:12", item="samscrape#12", want="do", kind="do", red=True)
FORK = _item("red_pr:s:13", item="samscrape#13", want="do", kind="do", fork=True)


def _head(got: dict | None, fleet: list[dict] | None = None) -> tuple[dict, str]:
    """The one card's view and its header's markup, as the Queue page draws it."""
    from shiftlead.ui.app import templates

    (c,) = queue_view(_q(), NOW, {"cards": {CID: got}} if got else None, fleet=fleet)["up_next"]
    html = templates.env.from_string('{% from "queue_card.html" import card %}{{ card(c) }}').render(c=c)
    return c, html[: html.index('<span class="qgap">')]


def test_the_count_is_every_decide_and_do_item_but_a_red_or_fork_pr_and_every_with_you_item():
    assert items_n(card_wants({}, "", False)) == 0
    assert items_n(card_wants({"needs": [_item("m-1"), _item("m-2", want="do", kind="do")]}, "", False)) == 2
    assert items_n(card_wants({"needs": [_item("m-1"), RED, FORK]}, "", False)) == 1
    answered = _item("samscrape#TD-012", want="answered", kind="")
    assert items_n(card_wants({"needs": [_item("m-1"), answered]}, "", False)) == 1, "an answered item is outside"
    assert items_n({"decide": [ITEM], "do": [], "with_you": [{"item": "samscrape#TD-9"}]}) == 2, "with you counts"


def test_a_card_with_two_items_draws_the_headers_start_session_beside_theirs_with_its_own_title():
    c, head = _head({"needs": [_item("m-1"), _item("m-2")]})
    assert c["items_n"] == 2 and c["items_start"] is True
    assert ">Start session<" in head and f'data-card="{CID}"' in head and 'data-item="' not in head
    assert ALL in head and ONE not in head


def test_one_item_or_one_beside_a_red_pr_draws_none_in_the_header():
    assert ">Start session<" not in _head({"needs": [_item("m-1")]})[1], "the item's button does the same"
    c, head = _head({"needs": [_item("m-1"), RED]})
    assert c["items_n"] == 1 and ">Start session<" not in head and ">Open session<" not in head


def test_two_answered_items_alone_draw_the_plain_headers_start_session():
    answered = [_item(f"samscrape#TD-0{n}", want="answered", kind="") for n in (12, 9)]
    c, head = _head({"needs": answered})
    assert c["items_n"] == 0 and ">Start session<" in head
    assert ONE in head and ALL not in head


def test_two_items_follow_the_holder_rule_on_start():
    """Two whose entries another session holds still count; where it holds `start` the header draws nothing
    (the row says *held by <name>*), and where the person's own session is on the card it is Open session."""
    got = {"needs": [_item("samscrape#TD-012", kind="decide"), _item("samscrape#TD-009", kind="decide")]}
    c, head = _head(got, fleet=[_rec("g1", "/x/samscrape", "TD-009", name="grinder-1")])
    assert c["items_n"] == 2 and c["session"]["other"] == "grinder-1"
    assert ">Start session<" not in head and ">Open session<" not in head
    c, head = _head(got, fleet=[_rec("mine", "/x/samscrape", "TD-020", unattended=False)])
    assert ">Open session<" in head and ">Start session<" not in head


def test_the_walk_sentence_and_waits_on_me_without_an_answered_entry():
    text = repoconfig.work_text("TD-9", "samscrape", "docs/technical_debt.md", "yours", "Queue", ["m-1"], [], walk=True)
    assert text.startswith(
        "I opened this session from the Queue to work through every item that waits on me on the card around TD-9 "
        "of samscrape's ledger (docs/technical_debt.md), one at a time: for each, read it, tell me its goal and what "
        "each answer leads to, and wait for my answer before the next. Its entries are: waits on me — m-1;"
    )
    item = repoconfig.work_text("TD-9", "s", "l", "yours", "Queue", item="m-1", walk=True)
    assert item.startswith("I opened this session from the Queue about m-1"), "an item's press keeps its own"
    wants = {"answered": [{"item": "samscrape#TD-012"}]}
    assert walk_mine(["samscrape#TD-012", "samscrape#TD-009", "m-1"], wants) == ["samscrape#TD-009", "m-1"]


def _asks(*mids: str) -> list[dict]:
    return [
        entry(m, "ask", from_="ao-samscrape-manager-sam", about="samscrape#TD-012", text=f"which {m}?") for m in mids
    ]


def _press(tmp_path, monkeypatch, inbox: list[dict], **extra) -> tuple[int, str]:
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q(), inbox=inbox)
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", **extra})
    assert r.status_code == 200, r.text
    (kw,) = created
    return r.status_code, kw["prompt"]


def test_a_header_press_on_a_two_item_card_walks_them(tmp_path, monkeypatch):
    """The road counts afresh from the card's wants: this world's card carries TD-12 (Decide) and TD-9 (Do) as items
    once the person inbox is read, so the walk sentence, *waits on me* naming every item — whatever the page drew
    (the press carries no count)."""
    walk = (
        "I opened this session from the Queue to work through every item that waits on me on the card around TD-9 "
        "of samscrape's ledger (docs/technical_debt.md), one at a time: for each, read it, tell me its goal and what "
        "each answer leads to, and wait for my answer before the next. Its entries are: waits on me — "
    )
    _, prompt = _press(tmp_path / "a", monkeypatch, [], card=CID)
    assert prompt == f"{walk}samscrape#TD-012, samscrape#TD-009; the rest — samscrape#TD-020. {TAIL}"
    _, prompt = _press(tmp_path / "b", monkeypatch, _asks("m-41", "m-42"), card=CID)
    assert prompt == f"{walk}samscrape#TD-012, samscrape#TD-009, m-41, m-42; the rest — samscrape#TD-020. {TAIL}"


def test_a_header_press_leaves_an_answered_entry_out_of_waits_on_me(tmp_path, monkeypatch):
    """TD-1343: the road's own *waits on me* on the walk press leaves out an entry *answered — waiting on <asker>*
    (`walk_mine` at the press, not only alone): this world's TD-12, answered at the press, beside TD-9 and two
    asks, so three items still count and the press walks them, never naming TD-12 as one that waits on the person."""
    import shiftlead.ui.app as app

    wants = app.card_wants

    def answered(*a):
        w = wants(*a)
        out = [m for m in w.get("decide") or () if m.get("item") == "samscrape#TD-012"]
        assert out, "the world's card carries TD-12 as a Decide item"
        return {**w, "decide": [m for m in w["decide"] if m not in out], "answered": out}

    monkeypatch.setattr(app, "card_wants", answered)
    _, prompt = _press(tmp_path, monkeypatch, _asks("m-41", "m-42"), card=CID)
    assert prompt.startswith("I opened this session from the Queue to work through every item that waits on me")
    assert "Its entries are: waits on me — samscrape#TD-009, m-41, m-42; the rest — " in prompt
    assert "samscrape#TD-012" not in prompt.split("the rest — ")[0], "the answered entry waits on its asker"


def test_with_one_left_at_the_press_the_why_key_sentence_stands(tmp_path, monkeypatch):
    """A page drawn with two, pressed once one of them is settled (TD-9 no longer a Do item at the press): the road
    counts one, so the `why_key` sentence; with the inbox unread it cannot count, and the same."""
    import shiftlead.ui.app as app

    wants = app.card_wants
    monkeypatch.setattr(app, "card_wants", lambda *a: {**wants(*a), "do": []})
    _, prompt = _press(tmp_path / "a", monkeypatch, [], card=CID)
    mine = "I opened this session from the Queue to work TD-9 of samscrape's ledger (docs/technical_debt.md) myself"
    assert prompt.startswith(mine)
    monkeypatch.setattr(app, "card_wants", wants)
    repo, c, created = _start_world(tmp_path / "b", monkeypatch, fleet=[MANAGER], queue=_q())
    assert c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": CID}).status_code == 200
    assert created[0]["prompt"].startswith(mine), "the reading failed: the `why_key` sentence"


def test_an_items_press_and_an_inbox_press_keep_their_own_sentences(tmp_path, monkeypatch):
    _, prompt = _press(tmp_path / "a", monkeypatch, _asks("m-41", "m-42"), card=CID, item="m-41")
    assert prompt.startswith("I opened this session from the Queue about m-41, on the card around TD-9")
    _, prompt = _press(tmp_path / "b", monkeypatch, _asks("m-41", "m-42"))
    assert prompt.startswith("I opened this session from the Inbox to work TD-9")


def test_a_header_press_counts_a_question_about_the_origin_path(tmp_path, monkeypatch):
    """TD-1371: the press rebuilds the card index with the reading's `origins`, so a question about
    `<origin path>#TD-n` is counted among *waits on me* as one about `<repo>#TD-n` is."""
    asks = [entry("m-41", "ask", from_="ao-samscrape-manager-sam", about="O/Samscrape#TD-12", text="which?")]
    repo, c, created = _start_world(
        tmp_path, monkeypatch, fleet=[MANAGER], queue={**_q(), "origins": {"samscrape": "o/samscrape"}}, inbox=asks
    )
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": CID})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert "samscrape#TD-012, samscrape#TD-009, m-41; the rest" in kw["prompt"]
