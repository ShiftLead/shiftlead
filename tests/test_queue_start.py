"""TD-912, design §4.4 *One owner* (`start`), *Hold*; §4.5 screen 12 *Three verbs: Start session*; §4.5a *Queue
card: Start session / Open session*, *Inbox row: ledger entry: Start session*: once per card, the person's own
session on the card's `start` entry — its one `Owner: paul` entry, else its first `decision (paul)` entry, else its
top entry, by key alone — told the card's entries; **Open session** while the person's own session holds any of
them, refused while another holds `start`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_queue import NOW, _by_id, _cards, _entry, _repo
from test_ui_inbox_ledger import MANAGER, _start_world
from test_ui_queue import card, client, fake, queue, row

from sessionorc.queue import card_entries
from shiftlead import repoconfig
from shiftlead.ui.queue import card_session, item_ref, queue_view, waits_on_me


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
        # a held decision is chosen all the same: a hold withholds from lanes only (§4.4 *Hold*)
        _entry(40, "top", Priority="High"),
        _entry(41, "a held decision", Priority="High", Blocked_by="TD-040, decision (paul)"),
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
        _entry(13, "held, mine", Priority="High", Owner="paul", Blocked_by="TD-010"),
        _entry(14, "a build", Priority="Medium", Blocked_by="TD-010"),
    ], TD_013={"held": {"at": NOW.isoformat()}})  # fmt: skip
    mine, rest = card_entries(cards["r#TD-010"])
    assert mine == ["r#TD-012", "r#TD-011"], "a held entry is no want: it is among the rest"
    assert rest == ["r#TD-010", "r#TD-013", "r#TD-014"]


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
