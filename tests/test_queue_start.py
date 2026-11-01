"""TD-912, design §4.4 *One owner* (`start`); §4.5 screen 12 *Three verbs: Start session*; §4.5a *Queue
card: Start session / Open session*, *Inbox row: ledger entry: Start session*: once per card, the person's own
session on the card's `start` entry — its one `Owner: paul` entry, else its first `decision (paul)` entry, else its
top entry, by key alone — told the card's entries; **Open session** while the person's own session holds any of
them, refused while another holds `start`."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import scratch_dir
from test_queue import NOW, _by_id, _cards, _entry, _repo
from test_ui_inbox_ledger import MANAGER, _start_world
from test_ui_queue import card, client, fake, queue, row

from sessionorc.queue import card_entries
from shiftlead import repoconfig
from shiftlead.ui.queue import attach, card_session, item_ref, item_start, queue_view, waits_on_me


def _read(tmp: Path, entries: list[str], **marks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    root, r = _repo(tmp, "r", entries)
    for e in r["ledger"]["entries"]:
        e.update(marks.get(e["id"].replace("-", "_"), {}))
    return _by_id(_cards({root: r}))


# -- the reading's `start` and the card's ids ---------------------------------------------------------------


def test_start_is_the_one_owned_entry_else_the_first_decision_else_the_top_by_key_alone(tmp_path):
    cards = _read(tmp_path, [
        # one `Owner: paul` entry beside a decision: the owned one
        _entry(1, "top", Priority="High"),
        _entry(2, "a decision", Priority="High", Blocked_by="TD-001, decision (paul)"),
        _entry(3, "mine", Priority="Medium", Owner="paul", Blocked_by="TD-001"),
        # two `Owner: paul` entries: the first decision by key
        _entry(10, "top", Priority="High"),
        _entry(11, "mine", Priority="High", Owner="paul", Blocked_by="TD-010"),
        _entry(12, "mine too", Priority="High", Owner="paul", Blocked_by="TD-010"),
        _entry(13, "a later decision", Priority="Low", Blocked_by="TD-010, decision (paul)"),
        _entry(14, "the first decision", Priority="Medium", Blocked_by="TD-010, decision (paul)"),
        # two owned and no decision: the top entry
        _entry(20, "top", Priority="High"),
        _entry(21, "mine", Priority="High", Owner="paul", Blocked_by="TD-020"),
        _entry(22, "mine too", Priority="High", Owner="paul", Blocked_by="TD-020"),
        # nothing of the person's: the top entry
        _entry(30, "top", Priority="High"),
        _entry(31, "a build", Priority="High", Blocked_by="TD-030"),
        # an old clock's `held` mark is read as nothing (TD-1297): the decision is chosen as any is
        _entry(40, "top", Priority="High"),
        _entry(41, "a decision", Priority="High", Blocked_by="TD-040, decision (paul)"),
    ], TD_041={"held": {"at": NOW.isoformat()}})  # fmt: skip
    start = {k: c["start"] for k, c in cards.items()}
    assert start == {
        "r#TD-001": "r#TD-003",
        "r#TD-010": "r#TD-014",
        "r#TD-020": "r#TD-020",
        "r#TD-030": "r#TD-030",
        "r#TD-040": "r#TD-041",
    }
    # two readings, one entry: the choice reads nothing a press changes
    assert {k: c["start"] for k, c in _read(tmp_path / "again", [
        _entry(1, "top", Priority="High"),
        _entry(2, "a decision", Priority="High", Blocked_by="TD-001, decision (paul)"),
        _entry(3, "mine", Priority="Medium", Owner="paul", Blocked_by="TD-001"),
    ]).items()} == {"r#TD-001": "r#TD-003"}  # fmt: skip


def test_the_cards_ids_are_its_decide_and_do_entries_then_the_rest_in_key_order(tmp_path):
    cards = _read(tmp_path, [
        _entry(10, "top", Priority="High"),
        _entry(11, "a low decision", Priority="Low", Blocked_by="TD-010, decision (paul)"),
        _entry(12, "mine", Priority="High", Owner="paul", Blocked_by="TD-010"),
        _entry(13, "mine, an old clock mark", Priority="High", Owner="paul", Blocked_by="TD-010"),
        _entry(14, "a build", Priority="Medium", Blocked_by="TD-010"),
    ], TD_013={"held": {"at": NOW.isoformat()}})  # fmt: skip
    mine, rest = card_entries(cards["r#TD-010"])
    assert mine == ["r#TD-012", "r#TD-013", "r#TD-011"], "a `held` mark is no state since TD-1297: TD-013 is a want"
    assert rest == ["r#TD-010", "r#TD-014"]


# -- who a card's press meets -------------------------------------------------------------------------------


def _rec(rid: str, repo: str, *refs: str, unattended: bool = True, state: str = "working", name: str = "") -> dict:
    claims = [{"ref": r, "status": "claimed"} for r in refs]
    return {"id": rid, "name": name or rid, "repo": repo, "state": state, "unattended": unattended, "progress": claims}


def _card() -> dict:
    return {**card(row("s", "TD-020", "top"), [row("s", "TD-009", "mine", needs="owner", depth=1, parent="s#TD-020")]),
            "start": "s#TD-009"}  # fmt: skip


def test_card_session_opens_the_persons_own_and_names_another_holder_of_start():
    c = _card()
    assert card_session(c, []) == {"start": "s#TD-009", "own": "", "other": ""}
    # the person's own session on any entry of the card, the one holding `start` first
    own = [_rec("p2", "/x/s", "TD-20", unattended=False), _rec("p1", "/x/s", "TD-9", unattended=False)]
    assert card_session(c, own)["own"] == "p1"
    assert card_session(c, own[:1])["own"] == "p2"
    # before the tick derives its claim, a session named `td-<n>` in the entry's repo holds it
    assert card_session(c, [_rec("ao-s-td-9", "/x/s", unattended=False, name="td-9")])["own"] == "ao-s-td-9"
    # a worker on `start`, none of the person's: no button, the press refused
    assert card_session(c, [_rec("g1", "/x/s", "TD-009", name="grinder-1")]) == {
        "start": "s#TD-009",
        "own": "",
        "other": "grinder-1",
    }
    # a worker on another entry, an ended session, another repo's: nothing met
    others = [_rec("g1", "/x/s", "TD-020"), _rec("p", "/x/s", "TD-9", unattended=False, state="closed")]
    assert card_session(c, [*others, _rec("q", "/x/other", "TD-9", unattended=False)])["own"] == ""
    assert card_session(c, others)["other"] == ""


def test_the_card_draws_start_session_open_session_or_nothing(tmp_path, monkeypatch):
    q = queue()
    for c in q["cards"]:
        c["start"] = c["id"]
    held = q["cards"][0]  # s#TD-10, held by grinder-1 (`g1`)

    def page(fleet: list[dict]) -> str:
        class Fake(fake(q)):
            async def call(self, method, **kw):
                return fleet if method == "list" else await super().call(method, **kw)

        return client(monkeypatch, tmp_path, Fake).get("/queue").text

    def head(html: str, cid: str) -> str:
        i = html.index(f'data-card="{cid}"')
        return html[i : html.index('<span class="qgap">', i)]

    html = page([_rec("g1", "/x/s", "TD-10", name="grinder-1")])
    assert ">Start session<" not in head(html, held["id"]), "another holds `start`: no button"
    up = head(html, "s#TD-20")
    assert ">Start session<" in up and 'data-card="s#TD-20"' in up and 'data-ref="TD-20"' in up
    assert 'data-repo="s"' in up and 'data-act="ledger_start"' in up
    html = page([_rec("mine", "/x/s", "TD-21", unattended=False)])
    assert ">Open session<" in head(html, "s#TD-20") and ">Start session<" not in head(html, "s#TD-20")
    # the view carries what the button reads
    v = queue_view(q, NOW, fleet=[_rec("mine", "/x/s", "TD-21", unattended=False)])
    assert v["up_next"][0]["session"] == {"start": "s#TD-20", "own": "mine", "other": ""}


# -- the road, widened (`/api/ledger/start` with `card`) ----------------------------------------------------


def _q(start: str = "samscrape#TD-009") -> dict:
    """One card around TD-20 (pickable): TD-9 the person's own, TD-12 their decision."""
    top = row("samscrape", "TD-020", "top", key="2|1|000020")
    rows = [
        row("samscrape", "TD-009", "mine", needs="owner", key="2|1|000009", depth=1, parent="samscrape#TD-020"),
        row("samscrape", "TD-012", "decide", needs="decision", key="1|1|000012", depth=1, parent="samscrape#TD-020"),
    ]
    return {"cards": [{**card(top, rows), "start": start}]}


TAIL = (
    "Read the entry, check the code and the design for what is already built or decided, and tell me in a few lines "
    "what it asks of me and what you would do first. Then wait for me: I drive this one."
)


def test_a_card_press_starts_on_its_start_with_the_queue_prompt_and_the_cards_ids(tmp_path, monkeypatch):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q())
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "id": "ao-samscrape-td-9", "name": "td-9"}, "the ledger's own spelling"
    (kw,) = created
    assert kw["worktree"] == "td-9" and kw["lane"] == ["TD-9"] and kw["unattended"] is False
    assert kw["prompt"] == (
        "I opened this session from the Queue to work TD-9 of samscrape's ledger (docs/technical_debt.md) myself: "
        "it waits on me (its owner is me). Its entries are: waits on me — samscrape#TD-012, samscrape#TD-009; "
        f"the rest — samscrape#TD-020. {TAIL}"
    )


def test_a_card_press_names_the_cards_mail_item_among_waits_on_me(tmp_path, monkeypatch):
    """The road's own `card_mail` read (TD-1256): an ask about TD-12 is a Decide item of the card, so the prompt's
    *waits on me* names its id after the card's ledger entries — not the ledger entries alone."""
    from test_ui_inbox import entry

    ask = entry("m-41", "ask", from_="ao-samscrape-manager-sam", about="samscrape#TD-012", text="which name?")
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q(), inbox=[ask])
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert (
        "Its entries are: waits on me — samscrape#TD-012, samscrape#TD-009, m-41; the rest — samscrape#TD-020."
        in kw["prompt"]
    )


def test_a_card_with_nothing_of_the_persons_starts_on_its_top_entry_with_the_card_key(tmp_path, monkeypatch):
    q = {"cards": [{**card(row("samscrape", "TD-020", "top")), "start": "samscrape#TD-020"}]}
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=q)
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-020", "card": "samscrape#TD-020"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["name"] == "td-20", "a pickable entry: not *for you*, started all the same from its card"
    assert kw["prompt"] == repoconfig.work_text("TD-20", "samscrape", "docs/technical_debt.md", "card", "Queue",
                                                rest=["samscrape#TD-020"])  # fmt: skip
    assert kw["prompt"].startswith(
        "I opened this session from the Queue to work the card around TD-20 of samscrape's ledger "
        "(docs/technical_debt.md). Its entries are: waits on me — none; the rest — samscrape#TD-020. "
    )


def test_a_stale_card_press_is_refused_and_starts_nothing(tmp_path, monkeypatch):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q())
    # the card's `start` moved on: TD-12 is not it
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-012", "card": "samscrape#TD-020"})
    assert r.status_code == 409 and "no longer the entry this card starts on" in r.text
    # the card is gone
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-099"})
    assert r.status_code == 409 and "no longer open" in r.text
    assert created == []


def test_a_card_press_goes_to_the_persons_session_and_refuses_another_holder_of_start(tmp_path, monkeypatch):
    def press(name: str, holder: dict) -> Any:
        repo, c, created = _start_world(tmp_path / name, monkeypatch, fleet=[MANAGER, holder], queue=_q())
        holder["repo"] = str(repo.resolve())  # the fake serves this very dict: its repo is the world's
        r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020"})
        assert created == [], "nothing is started"
        return r

    # the person's own session on another of the card's entries: its Focus, a stale page's press included
    r = press("own", _rec("ao-samscrape-mine", "", "TD-12", unattended=False))
    assert r.status_code == 200 and r.json() == {"ok": True, "focus": "ao-samscrape-mine"}, r.text
    # a worker holding `start`: refused in words
    r = press("worker", _rec("ao-samscrape-g1", "", "TD-9", name="grinder-1"))
    assert r.status_code == 409 and "held by grinder-1" in r.text


def test_an_inbox_press_names_its_entrys_card(tmp_path, monkeypatch):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q())
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-12"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["prompt"] == (
        "I opened this session from the Inbox to work TD-12 of samscrape's ledger (docs/technical_debt.md) myself: "
        "it waits on me (it is blocked by a decision of mine). Its entries are: waits on me — samscrape#TD-012, "
        f"samscrape#TD-009; the rest — samscrape#TD-020. {TAIL}"
    )


# -- started from an item (TD-1246; §4.5 screen 12 *Started from an item*) ---------------------------------


def test_an_items_id_is_its_board_key_mail_id_entry_or_pr_and_waits_on_me_names_every_item():
    assert item_ref({"row": "board", "key": "board:91aa0c3e", "id": "board:/r:3"}) == "board:91aa0c3e"
    assert item_ref({"id": "m-1524a3b5b9cc", "kind": "ask"}) == "m-1524a3b5b9cc"
    assert item_ref({"row": "ledger", "name": "s", "id": "TD-9"}) == "s#TD-009"
    assert item_ref({"row": "red_pr", "repo": "s", "pr": 12, "id": "red_pr:s:12"}) == "s#12"
    assert item_ref({"row": "alarm", "id": "m-x"}) == "", "a state row is no item to start from"
    wants = {
        "decide": [{"item": "s#TD-012"}, {"item": "m-aa"}, {"item": ""}],
        "do": [{"item": "board:bb"}, {"item": "s#12"}, {"item": "m-aa"}],
    }
    # the ledger entries as `card_entries` orders them, then every other item once, in the card's order
    assert waits_on_me(["s#TD-012", "s#TD-009"], wants) == ["s#TD-012", "s#TD-009", "m-aa", "board:bb", "s#12"]


def test_card_session_reads_the_entry_an_item_starts_on():
    c = _card()  # start s#TD-009; TD-020 its top
    worker = _rec("g1", "/x/s", "TD-009", name="grinder-1")
    assert card_session(c, [worker], on="s#TD-020") == {"start": "s#TD-009", "own": "", "other": ""}
    assert card_session(c, [_rec("g2", "/x/s", "TD-20", name="grinder-2")], on="s#TD-020")["other"] == "grinder-2"
    # the person's own session anywhere on the card still opens, whichever entry the item reads
    own = _rec("p", "/x/s", "TD-9", unattended=False)
    assert card_session(c, [own], on="s#TD-020")["own"] == "p"


def test_a_board_items_press_starts_on_the_cards_start_and_names_the_item_first(tmp_path, monkeypatch):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q())
    r = c.post(
        "/api/ledger/start",
        json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020", "item": "board:91aa0c3e"},
    )
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["worktree"] == "td-9", "a board line is no entry: the card's `start`"
    assert kw["prompt"] == (
        "I opened this session from the Queue about board:91aa0c3e, on the card around TD-9 of samscrape's ledger "
        "(docs/technical_debt.md). Read it first with `ao board show board:91aa0c3e`, and walk me through its goal "
        "and what each answer leads to. Its entries are: waits on me — samscrape#TD-012, samscrape#TD-009, "
        f"board:91aa0c3e; the rest — samscrape#TD-020. {TAIL}"
    )
    # an item that is no entry starts on `start` alone
    r = c.post(
        "/api/ledger/start", json={"repo": "samscrape", "id": "TD-012", "card": "samscrape#TD-020", "item": "m-1"}
    )
    assert r.status_code == 409 and "no longer the entry this card starts on" in r.text


def test_a_mail_and_a_ledger_items_first_sentence():
    m = repoconfig.work_text("TD-9", "s", "L", "card", "Queue", item="m-1524a3b5b9cc")
    assert m.startswith(
        "I opened this session from the Queue about m-1524a3b5b9cc, on the card around TD-9 of s's ledger (L). "
        "Read it first with `ao inbox --thread m-1524a3b5b9cc`, and walk me through"
    )
    e = repoconfig.work_text("TD-12", "s", "L", "decision", "Queue", item="s#TD-012")
    assert e.startswith("I opened this session from the Queue about s#TD-012, on the card around TD-12 of s's ")
    assert "Read it first, in the ledger, and walk me through" in e
    pr = repoconfig.work_text("TD-9", "s", "L", "card", "Queue", item="s#12")
    assert "about s#12, on the card around TD-9 of s's ledger (L). Read it first, and walk me through" in pr


def test_a_ledger_items_press_starts_on_its_own_entry_by_the_holder_rules_of_that_entry(tmp_path, monkeypatch):
    def press(name: str, ref: str, holders: list[dict]) -> tuple[Any, list[dict]]:
        repo, c, created = _start_world(tmp_path / name, monkeypatch, fleet=[MANAGER, *holders], queue=_q())
        for h in holders:
            h["repo"] = str(repo.resolve())
        body = {"repo": "samscrape", "id": ref, "card": "samscrape#TD-020", "item": f"samscrape#{ref}"}
        return c.post("/api/ledger/start", json=body), created

    # TD-12, the card's decision, is free though a worker holds `start` (TD-9): it starts on TD-12
    r, created = press("free", "TD-12", [_rec("ao-samscrape-g1", "", "TD-9", name="grinder-1")])
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["worktree"] == "td-12" and kw["lane"] == ["TD-12"]
    assert kw["prompt"].startswith("I opened this session from the Queue about samscrape#TD-12, on the card around")
    # an unattended worker holds TD-12: refused in words, never its Focus
    r, created = press("held", "TD-12", [_rec("ao-samscrape-g2", "", "TD-12", name="grinder-2")])
    assert r.status_code == 409 and "held by grinder-2" in r.text and created == []
    # the item names another repo's TD-12: not this card's item
    repo, c, created = _start_world(tmp_path / "other", monkeypatch, fleet=[MANAGER], queue=_q())
    body = {"repo": "samscrape", "id": "TD-12", "card": "samscrape#TD-020", "item": "otherrepo#TD-12"}
    r = c.post("/api/ledger/start", json=body)
    assert r.status_code == 409 and "not an item of this card" in r.text and created == []
    # TD-20 is the card's top, no Decide or Do item and not `start`
    r, created = press("not", "TD-20", [])
    assert r.status_code == 409 and "not an item of this card" in r.text and created == []


def test_the_roads_record_is_the_persons_own_end_with_the_manager_its_controller(tmp_path, monkeypatch):
    """What `thread` reads on a Queue-started session (§4.8 *thread passes an own end*): the road creates it as
    the person, interactive, not supervised, no seat — so the create writes `by_person` (`test_person_only`'s
    controlled `by_person=True` record, which passes `thread` alone) — with the live manager its controller."""
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q())
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["unattended"] is False and kw["controllers"] == [MANAGER["id"]]
    assert not kw.get("supervised") and not kw.get("seat") and "by_person" not in kw


# -- the page: Start session on every Decide and Do item (TD-1246 slice 3) --------------------------------


def test_an_items_start_reads_the_entry_it_starts_on():
    c = _card()  # start s#TD-009 (the person's Do); TD-020 its top, no need
    go = {"repo": "s", "card": "s#TD-020", "own": ""}
    # a board line or a mail item starts on the card's `start`; a ledger item on its own Decide or Do entry
    assert item_start(c, "board:bb", []) == {"item": "board:bb", "ref": "TD-009", **go}
    assert item_start(c, "m-1", []) == {"item": "m-1", "ref": "TD-009", **go}
    assert item_start(c, "s#TD-009", []) == {"item": "s#TD-009", "ref": "TD-009", **go}
    # a ledger entry that is no Decide or Do of the card, a red PR, a card with no `start`: no button
    assert item_start(c, "s#TD-020", []) == {}
    assert item_start(c, "s#12", []) == {}
    assert item_start({**c, "start": ""}, "board:bb", []) == {}
    # another session on the entry it starts on, none of the person's: no button (the road refuses 409)
    assert item_start(c, "board:bb", [_rec("g1", "/x/s", "TD-9", name="grinder-1")]) == {}
    # the person's own session on the card: Open session, to that one
    assert item_start(c, "board:bb", [_rec("p", "/x/s", "TD-20", unattended=False)])["own"] == "p"


def test_an_item_on_a_free_entry_starts_though_a_worker_holds_start():
    top = row("s", "TD-020", "top", key="2|1|000020")
    rows = [
        row("s", "TD-009", "mine", needs="owner", key="2|1|000009", depth=1, parent="s#TD-020"),
        row("s", "TD-012", "decide", needs="decision", key="1|1|000012", depth=1, parent="s#TD-020"),
    ]
    c = {**card(top, rows), "start": "s#TD-009"}
    worker = [_rec("g1", "/x/s", "TD-9", name="grinder-1")]
    assert item_start(c, "s#TD-012", worker)["ref"] == "TD-012"
    assert item_start(c, "s#TD-009", worker) == {} and item_start(c, "m-1", worker) == {}


def test_attach_hands_each_decide_and_do_item_its_start_but_a_red_pr():
    seen: list[dict] = []
    es = [
        {"id": "m-1", "kind": "ask", "home": "queue", "on_card": "s#TD-020", "on_row": "s#TD-020"},
        {"id": "red_pr:s:12", "row": "red_pr", "repo": "s", "pr": 12, "home": "queue", "on_card": "s#TD-020",
         "on_row": "s#TD-020"},
        {"id": "m-2", "kind": "note", "home": "queue", "on_card": "s#TD-020", "on_row": "s#TD-020"},
    ]  # fmt: skip
    asked: list[tuple[str, str]] = []

    def start(cid: str, item: str) -> dict:
        asked.append((cid, item))
        return {"item": item}

    attach({"needs": es[:2], "fyi": es[2:]}, lambda e, sec: seen.append(e) or "", (), start)
    assert asked == [("s#TD-020", "m-1")], "a red PR and a Read item ask nothing"
    assert [e["start"] for e in seen] == [{"item": "m-1"}, {}, {}]
    seen.clear()
    attach({"needs": es[:1]}, lambda e, sec: seen.append(e) or "")
    assert seen[0]["start"] == {}, "with no `start` reader no item draws one"


def test_each_item_draws_its_start_session_after_its_answers_and_before_its_dots(tmp_path, monkeypatch):
    from test_ui_board import host, item, report
    from test_ui_inbox import entry

    from shiftlead.ui.app import board_rows, templates

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"]}
    (line,) = board_rows(
        report(root, item(9, "pick a name. Due: 2026-09-20.", "2026-09-20", "2d overdue")),
        {str(root.resolve()): of},
    )
    ask = entry("m-1", "ask", text="merge PR 9?", subject="merge PR 9?", answers=["merge it", "hold it"])
    one = templates.get_template("queue_mail.html")
    go = {"repo": "samscrape", "ref": "TD-009", "card": "samscrape#TD-020", "own": ""}
    for e, want, ref in ((ask, "decide", "m-1"), (line, "do", line["key"])):
        html = one.render(e={**e, "want": want, "start": {**go, "item": ref}}, section="needs")
        btn = html[html.index('class="btn sm qstart qistart"') :]
        assert btn.index(">Start session<") < btn.index('class="more qdots"'), "before its ⋯"
        assert f'data-item="{ref}"' in btn and 'data-card="samscrape#TD-020"' in btn and 'data-ref="TD-009"' in btn
        assert html.index(">Start session<") > html.index(">Answer…<"), "after its answers"
        row = html[html.index('class="row gap wrap sugg qanswers"') :]
        assert row.index(">Start session<") < row.index("</div>"), "the last of its answer row"
        own = one.render(e={**e, "want": want, "start": {**go, "item": ref, "own": "p"}}, section="needs")
        assert ">Open session<" in own and ">Start session<" not in own and f"with {ref} on the clipboard" in own
        assert "qistart" not in one.render(e={**e, "want": want, "start": {}}, section="needs")
        # the Inbox draws none: the card's alone
        inbox = templates.get_template("inbox_rows.html").render(rows=[{**e, "start": {**go, "item": ref}}])
        assert "qistart" not in inbox


def test_the_header_draws_start_session_only_where_no_item_does():
    from shiftlead.ui.app import templates

    q = _q()
    cid = "samscrape#TD-020"
    head = templates.env.from_string('{% from "queue_card.html" import card %}{{ card(c) }}')

    def drawn(got: dict) -> str:
        (c,) = queue_view(q, NOW, {"cards": {cid: got}} if got else None)["up_next"]
        html = head.render(c=c)
        return html[: html.index('<span class="qgap">')]

    item = {"section": "needs", "id": "m-1", "item": "m-1", "html": "", "kind": "decide", "want": "decide",
            "red": False, "running": False, "on_row": cid}  # fmt: skip
    red = {**item, "id": "red_pr:s:12", "item": "samscrape#12", "want": "do", "kind": "do", "red": True}
    assert ">Start session<" in drawn({}), "no item: the header's"
    assert ">Start session<" in drawn({"needs": [red]}), "a red PR draws none of its own"
    assert ">Start session<" not in drawn({"needs": [item]}), "an item draws its own: none in the header"
    assert ">Open session<" not in drawn({"needs": [item, red]})


PRESS_PROBE = """
const fs = require("fs");
const js = fs.readFileSync(process.argv[2], "utf8");
const block = js.slice(js.indexOf('if (action === "ledger_start") {'), js.indexOf('if (action === "board_add")'));
const press = new Function("b", "row", "fetch", "navigator", "location", "AO", "pressed", "say",
  "return (async () => { const action = 'ledger_start'; " + block + " })();");
(async () => {
  const out = {}, posted = {};
  for (const [name, focus, item, refuse, card = "s#TD-20"] of [
    ["copied", "ao-p", "m-41", false], ["refused", "ao-p", "m-41", true], ["started", "", "m-41", false],
    ["entry", "ao-p", "", false], ["bare", "ao-p", "", false, ""],
  ]) {
    const seen = [], loc = { href: "/queue" };
    const clip = { writeText: async (t) => {
      seen.push(`clip ${t} at ${loc.href}`);
      if (refuse) throw new Error("no");
    } };
    const ao = { poppedId: "", unPend: () => seen.push("unpend"),
      toast: (t, bad, to) => seen.push(`toast ${t} → ${to}`) };
    const got = { ok: true, json: async () => (focus ? { ok: true, focus } : { ok: true, id: "ao-n", name: "td-9" }) };
    const b = { dataset: { repo: "s", ref: "TD-9", ...(card ? { card } : {}), ...(item ? { item } : {}) } };
    const post = async (url, opts) => { posted[name] = [url, JSON.parse(opts.body)]; return got; };
    await press(b, { isConnected: true }, post, { clipboard: clip }, loc, ao, () => {}, (t) => seen.push(`say ${t}`));
    out[name] = [...seen, `href ${loc.href}`];
  }
  console.log(JSON.stringify({ out, posted }));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.mark.unit
def test_an_items_open_session_copies_its_id_and_the_toast_shows_it_where_refused():
    """TD-1257: the `ledger_start` press, run as itself under node with a stub clipboard and `location` — an item's
    **Open session** copies its id before it leaves for the session; refused, the toast shows the id and the page
    stays; a start, or a press with no item, copies nothing. The request names the entry, and the card and the item
    where the button has them (TD-1274)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the press is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "open_session_probe.js"
    probe.write_text(PRESS_PROBE)
    js = Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js"
    out = subprocess.run([node, str(probe), str(js)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["out"] == {
        "copied": ["clip m-41 at /queue", "say m-41 copied — paste it into your session", "href /focus/ao-p"],
        "refused": [
            "clip m-41 at /queue",
            "unpend",
            "toast copy m-41 — the browser refused the clipboard → /focus/ao-p",
            "href /queue",
        ],
        "started": ["say started td-9 on m-41", "href /focus/ao-n"],
        "entry": ["href /focus/ao-p"],
        "bare": ["href /focus/ao-p"],
    }
    # the item's press names its item and card, so the prompt names the item and the road checks the card's start
    item = {"repo": "s", "id": "TD-9", "card": "s#TD-20", "item": "m-41"}
    assert got["posted"]["copied"] == got["posted"]["started"] == ["/api/ledger/start", item]
    assert got["posted"]["entry"] == ["/api/ledger/start", {"repo": "s", "id": "TD-9", "card": "s#TD-20"}]
    assert got["posted"]["bare"] == ["/api/ledger/start", {"repo": "s", "id": "TD-9"}]


def test_the_queue_page_draws_an_asks_start_session_on_its_card_and_none_in_the_header(tmp_path, monkeypatch):
    from test_ui_inbox import entry

    ask = entry("m-1", "ask", text="TD-20: merge PR 9?", subject="TD-20: merge PR 9?", answers=["merge it"])
    html = client(monkeypatch, tmp_path, fake(_q(), entries=[{**ask, "about": "samscrape#TD-020"}])).get("/queue").text
    i = html.index('data-card="samscrape#TD-020"')
    head = html[i : html.index('<span class="qgap">', i)]
    assert 'data-act="ledger_start"' not in head, "the item draws its own: none in the header"
    btn = html[html.index('class="btn sm qstart qistart"') :]
    assert btn.index('data-item="m-1"') < btn.index(">") and 'data-ref="TD-009"' in btn[: btn.index(">")]
