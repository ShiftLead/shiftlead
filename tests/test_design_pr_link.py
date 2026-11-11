# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1531 (design §4.5 screen 6 *An item about a design links the design's PR*, §4.5a *Queue card: what needs the
person*): the ledger reader reads an entry's `**Design PR:**` section, open or archived; the Queue's reading gives
each entry the design PR an item about it links — the section's last, an open *TD-n design: …* PR above it, the
one-hop `Part of:` parent's where it has neither — and a mail item by its `about`, a board line by its `Context:`
and a held entry's own row draw *· design #n* on its card and its Inbox row."""

from __future__ import annotations

from typing import Any

import pytest
from test_queue import _cards, _entry, _repo
from test_ui_queue import NOW, client, fake, mail, queue

from sessionorc import ledger
from sessionorc.queue import DESIGN_KEY, design_prs
from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import attach, card_index, design_link, split_later

pytestmark = pytest.mark.unit


def _with_section(n: int, title: str, section: str, **fields: str) -> str:
    return _entry(n, title, **fields) + f"**Why:** a reason.\n\n**Design PR:** {section}\n\n**Fix:** a fix.\n\n"


def test_the_section_is_read_as_its_numbers_and_none_when_absent():
    body = "**Why:** w.\n\n**Design PR:** #3025, #3136,\n  #3188\n\n**Fix:** #9 is not one.\n"
    assert ledger.design_pr_of(body) == [3025, 3136, 3188]
    assert ledger.design_pr_of("**Why:** see #12.\n") == []


def test_the_reader_carries_it_on_every_open_entry_and_on_an_archived_one(tmp_path):
    root, r = _repo(
        tmp_path,
        "s",
        [
            _with_section(10, "a design whose rounds run", "#10, #12", owner="designer", kind="design-first"),
            _with_section(11, "a held design", "#7", owner="designer", blocked_by="decision (paul)"),
            _entry(12, "no section"),
        ],
        [_with_section(5, "an archived design", "#3, #4")],
    )
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    assert by["TD-010"]["design_pr"] == [10, 12] and by["TD-010"]["for_page"] != "for-you"  # no gate, still read
    assert by["TD-011"]["design_pr"] == [7] and "design_pr" not in by["TD-012"]
    (a,) = ledger.archived(ledger.fs_io(root), str(r["ledger"].get("path") or ledger.DEFAULT))
    assert a["id"] == "TD-005" and a["design_pr"] == [3, 4]


def _pr(n: int, title: str) -> dict[str, Any]:
    return {"number": n, "title": title, "branch": f"b{n}"}


def test_design_prs_reads_the_section_the_open_design_pr_and_the_one_hop_parent():
    e = lambda tid, **kw: {"id": tid, "repo": "s", **kw}  # noqa: E731
    open_ = {
        "s#TD-001": e("TD-1", design_pr=[10, 12]),  # a section: its last
        "s#TD-002": e("TD-2", part_of="TD-1"),  # a round or build directly under it: the parent's
        "s#TD-003": e("TD-3", part_of="TD-2"),  # its part: one hop, never the parent's parent
        "s#TD-004": e("TD-4"),  # no section: the open *TD-4 design* PR, the lower of two
        "s#TD-005": e("TD-5", design_pr=[12]),  # a re-design above the section's last links it; a lower one does not
        "s#TD-006": e("TD-6", part_of="TD-7"),  # a design under an umbrella: its own open design PR first
        "s#TD-007": e("TD-7", design_pr=[12]),
        "s#TD-008": e("TD-8"),  # PRs that name it but are no design PR of its: nothing
        "s#TD-009": e("TD-9", part_of="TD-50"),  # an archived parent's section
        "s#TD-010": e("TD-10"),  # a title's case is no matter
    }
    archived = {"s#TD-050": {"id": "TD-50", "repo": "s", "design_pr": [40], "part_of_raw": ""}}
    prs = {
        "s": {
            "open": [
                _pr(31, "TD-4 design: the second"),
                _pr(30, "TD-4 design: the first"),
                _pr(30, "TD-5 design: a re-design"),
                _pr(8, "TD-5 design: an older one"),
                _pr(8, "TD-6 design: the round"),
                _pr(41, "TD-77: TD-8's build"),
                _pr(42, "TD-8: status line"),
                _pr(43, "TD-8 designs nothing"),
                _pr(44, "TD-1's round: TD-8 design"),
                _pr(45, "TD-10 Design: the first"),
            ]
        }
    }
    got = {q: d["n"] for q, d in design_prs({"s": "/r/s"}, prs, open_, archived).items()}
    assert got == {
        "s#TD-001": 12,
        "s#TD-002": 12,
        "s#TD-004": 30,
        "s#TD-005": 30,
        "s#TD-006": 8,
        "s#TD-007": 12,
        "s#TD-009": 40,
        "s#TD-010": 45,
        "s#TD-050": 40,
    }
    assert design_prs({"s": "/r/s"}, prs, open_, archived)["s#TD-001"]["root"] == "/r/s"


def test_the_reading_carries_them_and_the_index_keys_them_apart_from_the_cards(tmp_path):
    repos = dict(
        [
            _repo(
                tmp_path,
                "s",
                [
                    _with_section(10, "a design", "#10, #12", owner="designer", kind="design-first"),
                    _entry(11, "a build", part_of="TD-010"),
                ],
            )
        ]
    )
    q = _cards(repos)
    assert {k: v["n"] for k, v in q["design_prs"].items()} == {"s#TD-010": 12, "s#TD-011": 12}
    idx = card_index(q)
    root = q["design_prs"]["s#TD-010"]["root"]
    assert idx[DESIGN_KEY + "s#TD-010"] == ("12", root) and idx[DESIGN_KEY + "TD-010"] == ("12", root)
    assert idx[DESIGN_KEY + "o/s#TD-010"] == ("12", root)  # the origin's path too


def _index(**design: int) -> dict[str, Any]:
    """`queue()`'s cards, with `{TD-n: last}` design PRs on repo `s`."""
    q = queue()
    q["design_prs"] = {f"s#TD-{k[2:]}": {"n": n, "root": "", "only": True} for k, n in design.items()}
    return card_index(q)


def test_a_mail_item_a_board_line_and_a_held_row_link_it_and_the_rest_do_not():
    idx = _index(TD20=12, TD30=7)
    steer = mail("m1", "which way?", kind="steer", about="TD-20")
    assert design_link(steer, idx) == {"design_pr": 12, "design_pr_url": ""}
    assert design_link(mail("m2", "fyi", kind="note", about="TD-20, TD-30"), idx)["design_pr"] == 12  # the first alone
    assert design_link(mail("m3", "read #12?", pr=12, about="TD-20"), idx) == {}  # its own pr is that number
    assert design_link(mail("m4", "read #20?", pr=20, about="TD-20"), idx)["design_pr"] == 12  # another: both
    assert design_link(mail("m4b", "read #12?", pr="#12", about="TD-20"), idx) == {}  # a pr written as text too
    assert design_link(mail("m5", "read it", about="#12"), idx) == {}  # an about of #n names no entry
    assert design_link(mail("m6", "TD-20 in the words only"), idx) == {}  # never the words
    assert design_link(mail("m7", "the other repo's", about="other#TD-20"), idx) == {}  # its own repo wins
    assert design_link(mail("m8", "s's", about="TD-20", repo=None), idx, {"m8": "other"}) == {}  # the sender's repo's
    # with no repo, a bare `about` links nothing and a qualified ref after it is the one read (TD-1541)
    assert design_link(mail("m9", "?", about="TD-20", repo=None), idx) == {}
    assert design_link(mail("m10", "?", about="TD-20, s#TD-30", repo=None), idx)["design_pr"] == 7
    line = {
        "row": "board",
        "id": "b1",
        "kind": "decide",
        "repo_name": "s",
        "text": "Go? Context: TD-30 decision (paul). Due: 2026-10-16",
    }
    assert design_link(line, idx)["design_pr"] == 7
    held = {"row": "ledger", "id": "TD-30", "name": "s", "why": "decision"}
    assert design_link(held, idx)["design_pr"] == 7
    assert design_link({**held, "why": "yours"}, idx) == {}  # only the held row
    assert design_link({"row": "red_pr", "title": "TD-20: red", "repo": "s"}, idx) == {}
    assert design_link(steer, {}) == {}  # a home that serves no Queue


def test_the_link_is_the_repos_origin_where_it_says_where_it_is(monkeypatch):
    from shiftlead import review

    monkeypatch.setattr(review, "_github", lambda d: "https://github.com/o/s" if d == "/r/s" else "")
    q = queue()
    q["design_prs"] = {
        "s#TD-020": {"n": 12, "root": "/r/s", "only": True},
        "s#TD-030": {"n": 7, "root": "/r/x", "only": True},
    }
    idx = card_index(q)
    assert design_link(mail("m1", "?", about="TD-20"), idx)["design_pr_url"] == "https://github.com/o/s/pull/12"
    assert design_link(mail("m2", "?", about="TD-30"), idx) == {"design_pr": 7, "design_pr_url": ""}
    q["design_prs"]["agent-cadence#TD-036"] = {"n": 164, "root": ""}
    idx = card_index(q)
    assert (
        design_link(mail("m3", "?", about="agent-cadence#TD-36"), idx, {"m3": "s"})["design_pr"] == 164
    )  # its own repo wins


def test_split_later_and_the_sections_carry_it_and_attach_puts_it_on_the_item():
    idx = _index(TD20=12, TD99=5)
    secs = inbox_sections(
        [mail("m1", "which way?", kind="steer", about="TD-20", bound="2026-10-17T00:00:00+00:00")], now=NOW, cards=idx
    )
    (s,) = secs["steering"]
    assert s["design_pr"] == 12 and s["home"] == "queue"
    lf = {
        "groups": [
            {
                "rows": [
                    {"row": "ledger", "id": "TD-20", "name": "s", "row_id": "l1"},
                    {"row": "ledger", "id": "TD-99", "name": "s", "row_id": "l2"},
                ]
            }
        ]
    }
    got, _, moved, _ = split_later(lf, [], idx)
    assert (
        moved[0]["design_pr"] == 12 and got["groups"][0]["rows"][0]["design_pr"] == 5
    )  # on its card, and kept in Later
    cards = attach(secs, lambda e, sec: "", moved)["cards"]
    items = [m for v in cards["s#TD-20"].values() for m in v]
    assert {m.get("design_pr") for m in items} == {12}


def test_the_card_and_the_inbox_row_draw_it(tmp_path, monkeypatch):
    q = queue()
    q["design_prs"] = {"s#TD-020": {"n": 12, "root": "", "only": True}, "s#TD-003": {"n": 13, "root": "", "only": True}}
    entries = [
        mail("m1", "which way?", about="TD-20"),
        mail("m2", "other#TD-9 first?", about="other#TD-9"),
        mail("m3", "TD-3 shipped", kind="note", about="TD-3"),  # needs nobody: the Inbox's row
    ]
    c = client(monkeypatch, tmp_path, fake(q, entries))
    html = c.get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    assert 'class="st designpr"' in card20 and "· design #12</span>" in card20
    assert html.count('class="st designpr"') == 1  # the item about other#TD-9 links nothing
    # with no origin the number is bare; an Inbox row draws the same words
    inbox = c.get("/inbox").text
    fyi = inbox[inbox.index('id="sec-fyi"') :]
    assert "TD-3 shipped" in fyi and "· design #13</span>" in fyi and "· design #12" not in inbox


def test_a_bare_ref_is_looked_up_only_where_one_repo_holds_the_id():
    """The review of TD-1531: repo b's TD-20 has no design PR, so a bare `TD-20` with no known repo links nothing
    rather than repo s's design."""
    q = queue()
    q["design_prs"] = {"s#TD-020": {"n": 12, "root": "", "only": False}}
    idx = card_index(q)
    assert DESIGN_KEY + "TD-020" not in idx and idx[DESIGN_KEY + "s#TD-020"] == ("12", "")
    assert design_link(mail("m1", "?", about="TD-20", repo=None), idx) == {}
    assert design_link(mail("m2", "?", about="TD-20", repo=None), idx, {"m2": "s"})["design_pr"] == 12
    e = lambda tid, repo: {"id": tid, "repo": repo, "design_pr": [3]}  # noqa: E731
    got = design_prs(
        {}, {}, {"s#TD-020": e("TD-20", "s"), "s#TD-021": e("TD-21", "s")}, {"b#TD-020": {"id": "TD-20", "repo": "b"}}
    )
    assert got["s#TD-020"]["only"] is False and got["s#TD-021"]["only"] is True
