# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1618 (design §4.5 screen 12 *Three verbs: An item on a kept card*, §4.5a *Queue card: Start session / Open
session*, §4.4 *Completed cards*): a Decide or Do item drawn on a kept completed card draws Start session, starting
on the archived entry it is tied to, by `/api/ledger/start`'s kept path; the kept card's header draws none."""

from __future__ import annotations

from typing import Any

import pytest
from test_queue import TODAY, _cards, _entry, _repo
from test_queue import _rec as _qrec
from test_ui_inbox_ledger import MANAGER, _form, _start_world
from test_ui_queue import client, fake

from sessionorc import ledger
from sessionorc.models import ProgressEntry
from shiftlead import repoconfig
from shiftlead.ui.queue import card_session, item_start

# one kept card around samscrape#TD-030: TD-030 (a feature) and TD-031 (a debt), both archived; the reading's ids
# are `qid`s, padded
KEPT_ID = "samscrape#TD-030"


def _completed(**kw: Any) -> dict:
    return {
        "id": KEPT_ID,
        "ids": [KEPT_ID, "samscrape#TD-031"],
        "titles": {},
        "types": {KEPT_ID: "feature", "samscrape#TD-031": "debt"},
        "closed": TODAY,
        "pr": 31,
        "at": f"{TODAY}T09:00:00+00:00",
        "entries": [
            {
                "qid": "samscrape#TD-031",
                "id": "TD-031",
                "title": "its build",
                "priority": "medium",
                "closed": f"{TODAY}T09:00:00+00:00",
                "pr": 31,
                "sha": None,
                "resolved": "built (#31).",
            },
            {
                "qid": KEPT_ID,
                "id": "TD-030",
                "title": "a design",
                "priority": "medium",
                "closed": f"{TODAY}T08:00:00+00:00",
                "pr": 30,
                "sha": None,
                "resolved": "designed (#30).",
            },
        ],
        **kw,
    }


def _kq(**kw: Any) -> dict:
    return {"cards": [], "completed": [_completed(**kw)]}


def _ask(mid: str = "m-41", about: str = "samscrape#TD-031", **kw: Any) -> dict:
    from test_ui_inbox import entry

    return entry(mid, "ask", from_="ao-samscrape-manager-sam", about=about, text="was it right?", **kw)


def _press(c, **body: Any):
    return c.post("/api/ledger/start", json={"repo": "samscrape", "card": KEPT_ID, **body})


TAIL = (
    "Read the entry, check the code and the design for what is already built or decided, and tell me in a few lines "
    "what it asks of me and what you would do first. Then wait for me: I drive this one."
)


# -- the reading -------------------------------------------------------------------------------------------------


def test_the_completed_cards_carry_types_keyed_as_ids_an_unpadded_archive_id_among_them(tmp_path):
    root, r = _repo(tmp_path, "r", [], archive=[
        _entry(1, "a design", Type="Feature — the shape", Resolved=f"{TODAY} — designed (PR #1).", Part_of="TD-002"),
        "## TD-2: unpadded, no type\n\n**Resolved:** " + TODAY + " — (PR #2).\n\n",
        _entry(3, "an unknown type", Type="chore", Resolved=f"{TODAY} — (PR #3)."),
    ])  # fmt: skip
    done = {c["id"]: c for c in _cards({root: r})["completed"]}
    one = next(c for c in done.values() if "r#TD-001" in c["ids"])
    assert sorted(one["ids"]) == ["r#TD-001", "r#TD-002"], "the unpadded archive id is a `qid`, padded"
    assert one["types"] == {"r#TD-001": "feature", "r#TD-002": ledger.TYPES[0]}, "no Type: the first"
    assert done["r#TD-003"]["types"] == {"r#TD-003": ledger.TYPES[0]}, "an unknown Type: the first"


def test_a_claim_on_an_archived_entry_is_other_work_and_a_done_one_is_not(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "x", Priority="Low")],
                    archive=[_entry(9, "archived", Resolved=f"{TODAY} — (PR #9).")])  # fmt: skip
    s = _qrec("p", root, "TD-009", lane=["TD-009"])
    s.unattended = False
    assert [o["ref"] for o in _cards({root: r}, [s])["other_work"]] == ["TD-009"]
    s.progress = [ProgressEntry(ref="TD-009", status="done", pr=9, source="derived", branch="td-009")]
    assert _cards({root: r}, [s])["other_work"] == [], "a claim that reads done #9 draws no line"


# -- the button -------------------------------------------------------------------------------------------------


def _live(rid: str, *refs: str, repo: str = "/x/samscrape", lane=(), unattended=False, name="") -> dict:
    claims = [{"ref": x, "status": "claimed"} for x in refs]
    return {"id": rid, "name": name or rid, "repo": repo, "state": "working", "unattended": unattended,
            "progress": claims, "lane": list(lane)}  # fmt: skip


def test_an_item_on_a_kept_card_starts_on_the_archived_entry_it_is_tied_to():
    c = _completed()
    got = item_start(c, "m-41", [], "samscrape#TD-031")
    assert got == {"item": "m-41", "repo": "samscrape", "ref": "TD-031", "card": KEPT_ID, "own": ""}
    assert item_start(c, "board:91aa0c3e", [], KEPT_ID)["ref"] == "TD-030"
    assert item_start(c, "m-41", [], "samscrape#TD-099") == {}, "a row not of the card"
    assert item_start(c, "samscrape#12", [], KEPT_ID) == {}, "a red PR draws none"
    assert item_start({"id": "loose:other#TD-009", "ids": []}, "m-1", [], "other#TD-009") == {}, "a loose card"


def test_the_button_is_open_session_by_the_persons_name_claim_or_lane_on_any_entry_of_the_kept_card():
    c = _completed()
    # the person's session picked another name on the form: its lane is the archived entry
    own = _live("ao-samscrape-review-31", lane=["TD-31"])
    assert item_start(c, "m-41", [own], "samscrape#TD-031")["own"] == "ao-samscrape-review-31"
    # on another archived entry of the same kept card
    assert item_start(c, "m-41", [_live("p", lane=["TD-030"])], "samscrape#TD-031")["own"] == "p"
    assert item_start(c, "m-41", [_live("p", "TD-030")], "samscrape#TD-031")["own"] == "p", "by claim"
    assert item_start(c, "m-41", [_live("p", name="td-031")], "samscrape#TD-031")["own"] == "p", "by name"
    # an unattended session's lane marks nothing: the button stands, no Open session
    w = _live("g", lane=["TD-031"], unattended=True)
    assert item_start(c, "m-41", [w], "samscrape#TD-031") == {**item_start(c, "m-41", [], "samscrape#TD-031")}
    # the person's session in another repo, its lane the same number: not theirs here
    elsewhere = _live("q", repo="/x/other", lane=["TD-031"])
    assert item_start(c, "m-41", [elsewhere], "samscrape#TD-031")["own"] == ""
    # another session holding the item's entry by claim: no button
    assert item_start(c, "m-41", [_live("g1", "TD-031", unattended=True, name="grinder-1")], "samscrape#TD-031") == {}
    assert (
        card_session(c, [_live("g1", "TD-031", unattended=True, name="grinder-1")], on="samscrape#TD-031")["other"]
        == "grinder-1"
    )


def test_an_open_cards_session_reads_no_lane():
    c = {"id": "s#TD-020", "start": "s#TD-020", "top": {"qid": "s#TD-020"}, "rows": []}
    assert card_session(c, [_live("p", repo="/x/s", lane=["TD-020"])])["own"] == "", "an open card: claims and names"


@pytest.mark.parametrize("n", [1, 2])
def test_the_kept_cards_items_draw_start_session_and_its_header_none(tmp_path, monkeypatch, n):
    from test_ui_queue import mail, queue

    asks = [mail("m-1", "merge #13?", about="TD-3"), mail("m-2", "and the docs?", about="TD-3")][:n]
    c = client(monkeypatch, tmp_path, fake(queue(), asks))
    assert "qistart" not in c.get("/queue").text  # on the card's own page (TD-1763)
    html = c.get("/card/s%23TD-3").text
    i = html.index('data-card="s#TD-3"')
    card = html[i : html.index("</article>", i)] if "</article>" in html[i:] else html[i:]
    first = card.index('class="btn sm qstart qistart"')
    head = card[:first]
    assert 'data-act="ledger_start"' not in head, "a kept card asks only through its items"
    tags = [t[: t.index(">")] for t in card.split('class="btn sm qstart qistart"')[1:]]
    assert len(tags) >= n
    for k, tag in zip(range(n), tags, strict=False):
        assert f'data-item="m-{k + 1}"' in tag and 'data-ref="TD-3"' in tag and 'data-card="s#TD-3"' in tag, tag
        assert 'data-repo="s"' in tag and ">Start session<" not in head


# -- the road's kept path ---------------------------------------------------------------------------------------


def test_a_kept_items_press_starts_td_n_on_the_archived_entry_with_the_kept_prompt(tmp_path, monkeypatch):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_kq(), inbox=[_ask()])
    r = _press(c, id="TD-031", item="m-41")
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["name"] == "td-031" and kw["worktree"] == "td-031" and kw["lane"] == ["TD-031"]
    assert kw["role"] == "techlead", "TD-031's archived Type, a debt"
    assert kw["prompt"] == (
        "I opened this session from the Queue about m-41, on the completed card around TD-031 of samscrape's ledger "
        "(docs/technical_debt.md). TD-031 is archived: read it as the record of what was done, not as open work. "
        "Read the item first with `ao inbox --thread m-41`, and walk me through its goal and what each answer leads "
        f"to. Its entries are: waits on me — m-41; the rest — none. {TAIL}"
    )


def test_an_unpadded_card_names_the_padded_session_and_a_missing_type_reads_the_first(tmp_path, monkeypatch):
    q = _kq(id="samscrape#TD-30", ids=["samscrape#TD-30", "samscrape#TD-31"], types={})
    repo, c, created = _start_world(
        tmp_path, monkeypatch, fleet=[MANAGER], queue=q, inbox=[_ask(about="samscrape#TD-31")]
    )
    r = c.post(
        "/api/ledger/start", json={"repo": "samscrape", "card": "samscrape#TD-30", "id": "TD-31", "item": "m-41"}
    )
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["name"] == "td-031" and kw["role"] == "techlead", "ENTRY_TYPES[0], a debt"


def test_a_feature_entry_takes_its_role_and_a_board_line_is_read_by_ao_board_show():
    m = repoconfig.work_text(
        "TD-030", "s", "L", "card", "Queue", mine=["board:91aa0c3e"], item="board:91aa0c3e", kept=True
    )
    assert m.startswith(
        repoconfig.WORK_ITEM_KEPT.replace("{read}", " with `ao board show board:91aa0c3e`")
        .replace("{item}", "board:91aa0c3e").replace("{id}", "TD-030").replace("{repo}", "s").replace("{ledger}", "L")
    )  # fmt: skip
    assert "Its entries are: waits on me — board:91aa0c3e; the rest — none." in m


def test_a_taken_name_answers_the_form_and_a_session_under_another_name_is_opened(tmp_path, monkeypatch):
    import subprocess

    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_kq(), inbox=[_ask()])
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "td-031"], check=True)  # the old build's branch
    fields, why = _form(_press(c, id="TD-031", item="m-41"))
    assert fields["name"] == "td-031" and why and created == []
    # the person started it under another name on the form: its lane holds the entry, and a press opens it
    own = _live("ao-samscrape-review-31", repo=str(repo.resolve()), lane=["TD-031"])
    repo2, c2, created2 = _start_world(
        tmp_path / "again", monkeypatch, fleet=[MANAGER, own], queue=_kq(), inbox=[_ask()]
    )
    own["repo"] = str(repo2.resolve())
    r = _press(c2, id="TD-031", item="m-41")
    assert r.json() == {"ok": True, "focus": "ao-samscrape-review-31"} and created2 == []


def test_another_holder_of_the_entry_refuses_the_press_and_a_workers_lane_does_not(tmp_path, monkeypatch):
    held = _live("ao-samscrape-g1", "TD-31", unattended=True, name="grinder-1")
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER, held], queue=_kq(), inbox=[_ask()])
    held["repo"] = str(repo.resolve())
    r = _press(c, id="TD-031", item="m-41")
    assert r.status_code == 409 and "held by grinder-1" in r.text and created == []
    laned = _live("ao-samscrape-g2", lane=["TD-031"], unattended=True)
    repo, c, created = _start_world(tmp_path / "w", monkeypatch, fleet=[MANAGER, laned], queue=_kq(), inbox=[_ask()])
    laned["repo"] = str(repo.resolve())
    assert _press(c, id="TD-031", item="m-41").status_code == 200 and len(created) == 1


KEPT_409 = "the item is no longer open on the card around samscrape#TD-030 — nothing was started"


@pytest.mark.parametrize(
    ("why", "body", "inbox"),
    [
        ("no item", {"id": "TD-031"}, [_ask()]),
        ("the item closed", {"id": "TD-031", "item": "m-41"}, [_ask(closed_reason="answered")]),
        ("not the item's entry", {"id": "TD-030", "item": "m-41"}, [_ask()]),
        ("found nowhere, no open entry", {"id": "TD-031", "item": "m-41", "card": "samscrape#TD-099"}, [_ask()]),
        ("the mail read fails", {"id": "TD-031", "item": "m-41"}, None),
    ],
)
def test_every_failed_check_on_the_kept_path_is_the_one_refusal(tmp_path, monkeypatch, why, body, inbox):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_kq(), inbox=inbox)
    r = _press(c, **body)
    want = KEPT_409.replace(KEPT_ID, body.get("card") or KEPT_ID)
    assert r.status_code == 409 and want in r.text, (why, r.text)
    assert created == [], why


def test_a_card_found_nowhere_on_an_open_entry_keeps_todays_refusal(tmp_path, monkeypatch):
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_kq(), inbox=[_ask()])
    r = _press(c, id="TD-009", item="m-41", card="samscrape#TD-099")
    assert r.status_code == 409 and "the card around samscrape#TD-099 is no longer open" in r.text and created == []


def test_today_an_open_cards_press_is_unchanged(tmp_path, monkeypatch):
    from test_queue_start import _q

    q = {**_q(), "completed": [_completed()]}
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=q)
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-009", "card": "samscrape#TD-020"})
    assert r.status_code == 200 and created[0]["name"] == "td-9", r.text


def test_the_button_compares_the_items_row_with_the_cards_ids_as_qids():
    """The review of #3373: the button and the road read one spelling, so an unpadded id draws as the press starts."""
    c = _completed(ids=["samscrape#TD-30", "samscrape#TD-31"])
    assert item_start(c, "m-41", [], "samscrape#TD-031")["ref"] == "TD-031"
