"""TD-1984, built by TD-1999 — design §4.5 screen 12 *Three verbs: Start session* (*Beside another holder*), §4.5a
*Queue card: Start session / Open session* and *Inbox row: ledger entry: Start session / Open session*: a card whose
entry another session holds draws Start session all the same, and its press starts the person's own session
**beside** the holder — named the first free of `with-td-<n>`, `with-td-<n>-2` … `-9`, a shape that derives no claim,
given no `lane`, its prompt's holder sentence naming the holder — and the next press opens it by its name. No road
answers 409 *held by <name>*."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from test_queue import _cards, _entry, _repo
from test_queue import _rec as _qrec
from test_queue_kept_start import _ask, _kq, _press
from test_queue_start import TAIL, _q, _rec
from test_ui_inbox_ledger import MANAGER, _fleet, _render, _repos, _row, _start_world

from sessionorc import ledger
from sessionorc.models import Session
from sessionorc.reports import BRANCH_RE
from shiftlead import repoconfig
from shiftlead.ui.queue import BESIDE_RE, beside_td, card_session, item_start

CARD = {"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020"}


def _world(tmp_path, monkeypatch, holders: list[dict], **kw: Any):
    """`_start_world` with `holders` live in its repo, and a fleet that grows by each `create`, as the home's does:
    the record a press made is in the next `list`."""
    from shiftlead.ui import app as ui

    fleet = [MANAGER, *holders]
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=fleet, queue=kw.pop("queue", _q()), **kw)
    for h in holders:
        h["repo"] = str(repo.resolve())
    base = ui.LocalClient

    class Grow(base):  # type: ignore[misc, valid-type]
        async def call(self, method, **k):
            if method == "list":
                return list(fleet)
            got = await super().call(method, **k)
            if method == "create":
                await asyncio.sleep(0.05)  # a create takes a while: a racing press would read the old list
                fleet.append({"id": got["id"], "name": k["name"], "repo": k["repo"], "state": "starting",
                              "unattended": k["unattended"], "lane": k["lane"], "progress": []})  # fmt: skip
            return got

    monkeypatch.setattr(ui, "LocalClient", Grow)
    monkeypatch.setattr(ui, "_START_LOCKS", {})
    return repo, c, created, fleet


def _g1(ref: str = "TD-9", **claim: Any) -> dict:
    g = _rec("ao-samscrape-g1", "", name="grinder-1")
    g["progress"] = [{"ref": ref, "status": "claimed", **claim}]
    return g


# -- the name and the button ------------------------------------------------------------------------------------


def test_the_beside_name_is_anchored_and_derives_no_claim():
    assert (
        BESIDE_RE.fullmatch("with-td-9") and BESIDE_RE.fullmatch("with-td-9-2") and BESIDE_RE.fullmatch("with-td-9-9")
    )
    assert not BESIDE_RE.fullmatch("with-td-9-10") and not BESIDE_RE.fullmatch("with-td-9-1")
    assert not BESIDE_RE.fullmatch("xwith-td-9") and not BESIDE_RE.fullmatch("with-td-9x")
    assert beside_td("With-TD-012", "TD-12") and beside_td("with-td-9-3", "TD-009")
    assert not beside_td("with-td-1", "TD-12") and not beside_td("with-td-12", "TD-1")
    # `BRANCH_RE` (the tick's derivation, §4.8) does not read it: no claim comes of the branch
    for n in ("with-td-9", "with-td-9-2", "with-td-012"):
        assert BRANCH_RE.match(n) is None


def test_a_held_item_and_a_held_header_draw_the_button_and_the_with_td_session_opens_it():
    from test_queue_start import _card

    c = _card()  # start s#TD-009
    worker = _rec("g1", "/x/s", "TD-009", name="grinder-1")
    got = item_start(c, "m-1", [worker])
    assert got and got["held"] == "grinder-1" and got["own"] == ""
    assert card_session(c, [worker])["other"]["name"] == "grinder-1"
    # the person's own `with-td-9` session: Open session, on every item of the card (one session per card)
    mine = _rec("ao-s-with-td-9", "/x/s", unattended=False, name="with-td-9")
    assert item_start(c, "m-1", [worker, mine])["own"] == "ao-s-with-td-9"
    assert card_session(c, [worker, mine]) == {"start": "s#TD-009", "own": "ao-s-with-td-9", "other": {}}
    # an unattended `with-td-` session, or one of another number, marks nothing
    assert card_session(c, [worker, {**mine, "unattended": True}])["own"] == ""
    assert card_session(c, [worker, {**mine, "name": "with-td-90"}])["own"] == ""


def test_the_item_draws_start_session_beside_a_holder_in_its_answer_bar():
    from test_ui_inbox import entry

    from shiftlead.ui.app import templates

    ask = entry("m-1", "ask", text="merge PR 9?", subject="merge PR 9?", answers=["merge it"])
    go = {"repo": "samscrape", "ref": "TD-009", "card": "samscrape#TD-020", "own": "", "held": "grinder-1"}
    html = templates.get_template("queue_mail.html").render(e={**ask, "want": "decide", "start": go}, section="needs")
    assert ">Start session<" in html and ">Open session<" not in html
    btn = html[html.index('class="btn sm qstart qistart"') :]
    assert 'data-ref="TD-009"' in btn[: btn.index(">")] and btn.index(">Start session<") < btn.index("</button>")


# -- the press beside a holder ----------------------------------------------------------------------------------


def test_the_press_starts_with_td_n_with_no_lane_and_the_holder_sentence(tmp_path, monkeypatch):
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1(branch="td-9", pr=41)])
    r = c.post("/api/ledger/start", json=CARD)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": "ao-samscrape-with-td-9", "name": "with-td-9"}
    (kw,) = created
    assert (kw["name"], kw["worktree"], kw["lane"]) == ("with-td-9", "with-td-9", [])
    # role, review, team and controllers are any start's
    assert kw["role"] == "techlead" and kw["team"] == "sam-grind" and kw["controllers"] == [MANAGER["id"]]
    assert kw["unattended"] is False
    assert (
        "Its entries are: waits on me — samscrape#TD-012, samscrape#TD-009; the rest — samscrape#TD-020. "
        "TD-9 is held by grinder-1 on its branch td-9, in review #41, so while it holds it, it is that session's "
        "work. Read its branch and its PR, but never push to them, and open no PR of your own on TD-9. Where it "
        "should change course, tell me what you would write to it with `ao msg grinder-1`, and send it once I agree "
        "(where `ao msg` refuses, tell me instead). If it lets go (`ao repo` names who holds TD-9 now) and I ask you "
        "to take TD-9 over, declare a claim with `ao progress claim TD-9` first."
    ) in kw["prompt"]
    assert kw["prompt"].startswith("I opened this session from the Queue to work TD-9 of samscrape's ledger")


def test_the_cards_key_reads_look_into_beside_a_holder(tmp_path, monkeypatch):
    q = {"cards": [{**_q()["cards"][0], "start": "samscrape#TD-020"}]}
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1("TD-20")], queue=q)
    r = c.post("/api/ledger/start", json={**CARD, "id": "TD-020"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["name"] == "with-td-20"
    assert kw["prompt"].startswith(
        "I opened this session from the Queue to look into the card around TD-20 of samscrape's ledger "
        "(docs/technical_debt.md) with me. Its entries are:"
    )
    assert "to work the card" not in kw["prompt"]


def test_an_answered_entry_its_asker_holds_opens_to_work_it_myself_and_names_the_asker(tmp_path, monkeypatch):
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1("TD-12")], queue=_q("samscrape#TD-012"))
    r = c.post("/api/ledger/start", json={**CARD, "id": "TD-012"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["prompt"].startswith(
        "I opened this session from the Queue to work TD-12 of samscrape's ledger (docs/technical_debt.md) myself: "
        "it waits on me (it is blocked by a decision of mine)."
    )
    assert "TD-12 is held by grinder-1, so while it holds it" in kw["prompt"]


def test_the_next_press_opens_the_first_before_and_after_the_tick_lists_its_claim(tmp_path, monkeypatch):
    repo, c, created, fleet = _world(tmp_path, monkeypatch, [_g1()])
    first = c.post("/api/ledger/start", json=CARD).json()
    assert first["name"] == "with-td-9"
    # before the tick: the record by its name alone
    assert c.post("/api/ledger/start", json=CARD).json() == {"ok": True, "focus": first["id"]}
    # an item's press on the same card opens it too
    item = c.post("/api/ledger/start", json={**CARD, "item": "board:91aa0c3e"}).json()
    assert item == {"ok": True, "focus": first["id"]}
    # after the tick, the holder let go: the session still opens by its name, and holds nothing
    fleet[1]["progress"] = []
    fleet[1]["state"] = "closed"
    assert c.post("/api/ledger/start", json=CARD).json() == {"ok": True, "focus": first["id"]}
    assert len(created) == 1


def test_a_name_used_once_sends_the_next_press_to_the_next_name(tmp_path, monkeypatch):
    checks = {"with-td-9": {"verdict": "supersede"}}  # an exited `with-td-9` keeps the name until reaped
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1()], checks=checks)
    r = c.post("/api/ledger/start", json=CARD)
    assert r.status_code == 200 and r.json()["name"] == "with-td-9-2", r.text
    (kw,) = created
    assert kw["worktree"] == "with-td-9-2" and kw["lane"] == []


def test_with_all_nine_names_taken_the_form_names_the_first_and_carries_no_lane(tmp_path, monkeypatch):
    names = ["with-td-9", *(f"with-td-9-{k}" for k in range(2, 10))]
    checks = {n: {"verdict": "supersede"} for n in names}
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1()], checks=checks)
    r = c.post("/api/ledger/start", json=CARD)
    got = r.json()
    assert r.status_code == 200 and got["ok"] is False and created == [], r.text
    fields = {k: v[0] for k, v in parse_qs(urlsplit(got["form"]).query).items()}
    assert fields["name"] == fields["worktree"] == "with-td-9" and "lane" not in fields
    assert got["why"] == "with-td-9 names an exited session — pick another name"
    assert "TD-9 is held by grinder-1" in fields["prompt"], "the form road's prompt carries the holder sentence"
    # the form's submit keeps a `with-td-` name's empty lane empty, though its role's preset has one
    from shiftlead.ui import app as ui

    data = {"name": "with-td-9-9", "dir": str(repo), "where": "worktree", "worktree": "with-td-9-9", "role": "grinder"}
    assert c.post("/new", data=data, follow_redirects=False).status_code == 303
    assert created[-1]["lane"] == []
    other = {**data, "name": "mine-9", "worktree": "mine-9"}
    assert c.post("/new", data=other, follow_redirects=False).status_code == 303
    assert created[-1]["lane"] == list(ui.repoconfig.resolve_role(ui.repoconfig.discover(str(repo)), "grinder").lane)


def test_a_resume_of_a_with_td_record_keeps_its_lane_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import resume_create, resume_form_url

    (tmp_path / ".shiftlead.yml").write_text("roles: {techlead: {lane: [TD-9]}}\n")
    rec = {"id": "ao-w", "name": "with-td-9-2", "dir": str(tmp_path), "role": "techlead", "lane": [],
           "adapter_id": "u-1", "state": "exited"}  # fmt: skip
    assert resume_create(rec)["lane"] == []
    assert "lane=" not in resume_form_url(rec)
    assert resume_create({**rec, "name": "td-9"})["lane"] == ["TD-9"], "any other name takes the preset's"


def test_two_racing_presses_start_one_session(tmp_path, monkeypatch):
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1()])

    async def race() -> list[dict]:
        transport = httpx.ASGITransport(app=c.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            got = await asyncio.gather(*(ac.post("/api/ledger/start", json=CARD) for _ in range(2)))
        return [g.json() for g in got]

    a, b = asyncio.run(race())
    assert len(created) == 1 and created[0]["name"] == "with-td-9"
    started = a if "id" in a else b
    assert {"ok": True, "focus": started["id"]} in (a, b), (a, b)


def test_a_kept_cards_press_beside_a_holder_leaves_out_the_take_over_clause(tmp_path, monkeypatch):
    g = _rec("ao-samscrape-g1", "", "TD-31", name="grinder-1")
    repo, c, created, _ = _world(tmp_path, monkeypatch, [g], queue=_kq(), inbox=[_ask()])
    r = _press(c, id="TD-031", item="m-41")
    assert r.status_code == 200 and r.json()["name"] == "with-td-031", r.text
    (kw,) = created
    assert kw["lane"] == [] and "If it lets go" not in kw["prompt"]
    assert "the rest — none. TD-031 is held by grinder-1, so while it holds it" in kw["prompt"]


# -- the prompt's holder sentence -------------------------------------------------------------------------------


def test_the_holder_sentence_with_and_without_a_branch_and_a_pr():
    def held(**h: Any) -> str:
        text = repoconfig.work_text("TD-9", "s", "L", "card", "Queue", ["s#TD-009"], [], held={"name": "g", **h})
        return text.split("the rest — none. ", 1)[1].split(" Read its branch")[0]

    assert held() == "TD-9 is held by g, so while it holds it, it is that session's work."
    assert (
        held(branch="td-9") == "TD-9 is held by g on its branch td-9, so while it holds it, it is that session's work."
    )
    assert (
        held(git_branch="feat")
        == "TD-9 is held by g on its branch feat, so while it holds it, it is that session's work."
    )
    assert held(branch="td-9", git_branch="feat", pr=4) == (
        "TD-9 is held by g on its branch td-9, in review #4, so while it holds it, it is that session's work."
    )
    assert held(review_pr=7) == "TD-9 is held by g, in review #7, so while it holds it, it is that session's work."
    # no holder: no sentence, `{held}` empty, and `card` reads *to work*
    plain = repoconfig.work_text("TD-9", "s", "L", "card", "Queue", ["s#TD-009"], [], held={})
    assert plain == repoconfig.work_text("TD-9", "s", "L", "card", "Queue", ["s#TD-009"], [])
    assert "held by" not in plain and "{held}" not in plain and plain.endswith(TAIL)
    assert plain.startswith("I opened this session from the Queue to work the card around TD-9")


def test_the_holder_sentence_follows_the_entries_sentence_for_every_opening():
    h = {"name": "grinder-1"}
    for kw in ({"item": "m-1"}, {"item": "m-1", "kept": True}, {"walk": True}, {}):
        text = repoconfig.work_text("TD-9", "s", "L", "yours", "Queue", ["m-1"], ["s#TD-020"], held=h, **kw)
        entries = text.index("Its entries are: waits on me — m-1; the rest — s#TD-020. TD-9 is held by grinder-1")
        assert entries > 0 and text.index(TAIL) > entries, kw
        assert ("If it lets go" in text) is not kw.get("kept", False), kw
    # a card line that reads `{held}` is the card's, never a slot
    block = ["This is the card:", "a line with {held} in it", "— end of the card —"]
    text = repoconfig.work_text("TD-9", "s", "L", "card", "Queue", [], [], card=block, held=h)
    assert "a line with {held} in it" in text


# -- what the row, the lanes and the Inbox read ----------------------------------------------------------------


def test_the_row_and_the_lanes_keep_the_holders(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(4, "held", Priority="High")])
    mine = Session(id="p", name="with-td-4", kind="interactive", adapter="shell", dir=root, repo=root, state="working")  # type: ignore[arg-type]
    mine.unattended = False
    recs = [_qrec("w1", root, "TD-004"), mine]
    (c,) = _cards({root: r}, recs)["cards"]
    assert c["top"]["state"] == "held by w1", "the row keeps its holder's word"
    # once the holder lets go, the entry is back in its lane while the person's session runs
    entries = [{**e, "for_page": "pickable"} for e in r["ledger"]["entries"]]
    worker = {"id": "w1", "name": "w1", "lane": ["free-pick"], "state": "idle"}
    beside = {"id": "p", "name": "with-td-4", "lane": [], "state": "working"}
    assert ledger.in_lanes(entries, [worker, beside])["pickable"] == ledger.in_lanes(entries, [worker])["pickable"]
    assert "TD-004" in ledger.in_lanes(entries, [worker, beside])["pickable"]


def test_the_inbox_road_opens_the_persons_own_with_td_session_first_else_the_holder(tmp_path, monkeypatch):
    own = _rec("ao-samscrape-with-td-9", "", unattended=False, name="with-td-9")
    repo, c, created, _ = _world(tmp_path, monkeypatch, [_g1(), own])
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"})
    assert r.json() == {"ok": True, "focus": "ao-samscrape-with-td-9"}
    repo, c, created, _ = _world(tmp_path / "b", monkeypatch, [_g1("TD-009")])
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"})
    assert r.json() == {"ok": True, "focus": "ao-samscrape-g1"}, "TD-009 is TD-9: the claim compared by `same_td`"
    # own, though nothing holds it: Open session to it, never a start beside a holder
    repo, c, created, _ = _world(tmp_path / "c", monkeypatch, [_rec("ao-samscrape-x", "", unattended=False,
                                                                     name="with-td-9-3")])  # fmt: skip
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"})
    assert r.json() == {"ok": True, "focus": "ao-samscrape-x"} and created == []


def test_the_inbox_row_draws_open_session_while_the_persons_with_td_session_lives(tmp_path, monkeypatch):
    from shiftlead.ui.app import ledger_for_you

    fleet = [{**s, "unattended": True} for s in _fleet(tmp_path)]  # the workers' records
    a = str(tmp_path / "agentorc")
    fleet.append({"id": "p1", "name": "with-td-156", "repo": a, "state": "working", "unattended": False})
    lf = ledger_for_you(_repos(tmp_path), fleet, {})
    rows = {r["id"]: r for r in lf["groups"][0]["rows"]}
    assert rows["TD-156"]["own"] == "p1" and rows["TD-156"]["held"] == "", "the name marks the button alone"
    assert rows["TD-319"]["own"] == "" and rows["TD-319"]["held"] == "grinder-ao-1"
    html = _render(lf, tmp_path, monkeypatch)
    mine, held = _row(html, "ledger:agentorc:TD-156"), _row(html, "ledger:agentorc:TD-319")
    assert ">Open session</button>" in mine and ">Start session</button>" not in mine
    assert "your session on TD-156: go to its Focus — nothing is started" in mine
    assert "grinder-ao-1 holds TD-319: go to its Focus" in held


def test_no_road_answers_409_held_by(tmp_path, monkeypatch):
    from pathlib import Path

    src = (Path(__file__).parents[1] / "src/shiftlead/ui/app.py").read_text()
    assert 'f"held by {' not in src
    for body in (CARD, {**CARD, "item": "board:91aa0c3e"}, {**CARD, "item": "samscrape#TD-9"}):
        repo, c, created, _ = _world(tmp_path / str(len(body)) / body.get("item", "h").replace(":", "_"), monkeypatch,
                                     [_g1()])  # fmt: skip
        r = c.post("/api/ledger/start", json=body)
        assert r.status_code == 200 and "held by" not in r.text, (body, r.text)
