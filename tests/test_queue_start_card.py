"""TD-1903, design §4.5 screen 12 *Three verbs: Start session*, §4.5a *Inbox row: ledger entry*, §4.7 *`ao card`*: a
**Start session** prompt carries the card as `ao card` prints it under a pane — no mail's words — between the id
lists and the closing sentence, marked as data by a sentence of its own and *— end of the card —*, bounded at
`CARD_PROMPT_CAP` and cut at a row's or an item's boundary. It is read last and left out where no open card holds
the entry, on a kept card's press, where the read fails or answers anything but a card, and on the form road."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from test_cli_card import view
from test_queue_kept_start import KEPT_ID, _kq
from test_queue_kept_start import _ask as _kept_ask
from test_queue_start import TAIL, _q, bare
from test_ui_inbox import entry
from test_ui_inbox_ledger import MANAGER, _start_world

from shiftlead import cardtext, cli, repoconfig
from shiftlead.ui import app as ui

CID = "samscrape#TD-020"
DATA = cardtext.CARD_DATA.format(id=CID)


def _got(words: bool = False) -> dict:
    """`test_cli_card`'s card — a Decide board line with its answers, an ask, an answered ledger row with its Ask —
    through the JSON round trip the road makes, its mail whole where `words`, as a wrongly served read would be."""
    return json.loads(json.dumps(view(words=words), default=str))


def _reads(monkeypatch, got: Any = None, exc: Exception | None = None) -> list[tuple[str, bool]]:
    """`Readings.card` answering `got` (or raising `exc`), each read recorded; set before the world's client."""
    asked: list[tuple[str, bool]] = []

    async def card(self, id, words):
        asked.append((id, words))
        if exc is not None:
            raise exc
        return got

    monkeypatch.setattr(ui.Readings, "card", card)
    return asked


def _press(tmp_path, monkeypatch, body: dict, **world) -> str:
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], **world)
    r = c.post("/api/ledger/start", json={"repo": "samscrape", **body})
    assert r.status_code == 200 and r.json().get("ok"), r.text
    (kw,) = created
    return kw["prompt"]


CARD_PRESS = {"id": "TD-009", "card": CID}
IDS = "Its entries are: waits on me — samscrape#TD-012, samscrape#TD-009; the rest — samscrape#TD-020."


# -- the template ------------------------------------------------------------------------------------------


def test_the_closing_sentence_drops_i_drive_this_one_and_no_card_leaves_one_paragraph():
    text = repoconfig.work_text("TD-9", "s", "L", "yours", "Queue", ["s#TD-9"], [])
    assert text.endswith(f"the rest — none. {TAIL}") and "\n" not in text
    assert "{card}" not in text and "I drive this one" not in text


def test_the_card_sits_between_the_id_lists_and_the_closing_sentence_and_no_line_of_it_is_a_slot():
    block = ["data:", "", "a line naming {mine}, {rest}, {opening} and {card}", "", "— end —"]
    text = repoconfig.work_text("TD-9", "s", "L", "yours", "Queue", ["s#TD-9"], [], card=block)
    ids, card, tail = text.split("\n\n", 2)[0], text.split("\n\n")[1:-1], text.split("\n\n")[-1]
    assert ids.endswith("the rest — none.") and tail == TAIL
    assert card == ["data:", "a line naming {mine}, {rest}, {opening} and {card}", "— end —"]


# -- the block ---------------------------------------------------------------------------------------------


def test_the_block_is_the_data_sentence_ao_cards_text_with_no_mail_words_and_the_end_line():
    got = _got(words=True)  # a read that wrongly carried the mail whole: the block still cuts it
    block = cardtext.card_block(got, CID)
    assert block[:2] == [DATA, ""] and block[-2:] == ["", cardtext.CARD_END]
    assert block[2:-2] == cli._card_text(got, cut=True), "`ao card`'s one renderer, under a pane"
    text = "\n".join(block)
    assert "SECRET" not in text and cardtext.MAIL_WORDS_CUT in text
    assert "  board:k1 · decide · on s#TD-21" in text and "    - B (default)" in text, "a board line comes whole"
    assert "    Go with TD-20?" in text and "    - Go (default) — it builds" in text, "a ledger row's Ask whole"
    assert "`ao card samscrape#TD-020` prints it again" in DATA


def test_an_oversize_card_is_cut_at_a_row_or_an_item_boundary_naming_ao_card():
    got = _got()
    whole = cli._card_text(got, cut=True)
    # every cap from just past the header to just short of the whole: the cut keeps whole units only
    starts = {i for i, ln in enumerate(whole) if ln and not ln.startswith("    ")}
    rows_end = whole.index("rows") + 1 + len(got["card"]["rows"]) + 1
    starts |= set(range(rows_end))  # every row line is a unit of its own, however deep
    total = sum(len(ln) + 1 for ln in whole)
    for cap in range(len(whole[0]) + 1, total, 7):
        block = cardtext.card_block(got, CID, cap=cap)
        card = block[2:-2]
        assert card[-1] == cardtext.CARD_CUT.format(id=CID), cap
        kept = card[:-1]
        assert kept == whole[: len(kept)] and len(kept) in starts, f"cut mid-unit at cap {cap}"
        assert len(kept) <= rows_end or kept[-1].startswith(" "), f"a label left bare at cap {cap}"
        assert sum(len(ln) + 1 for ln in kept) <= cap
    assert cardtext.card_block(got, CID, cap=total)[2:-2] == whole, "a card within the cap is whole, no cut line"


def test_the_default_cap_holds_a_big_card_to_twelve_thousand_characters():
    got = _got()
    item = got["wants"]["decide"][0]
    got["wants"]["decide"] = [item] * 400
    block = cardtext.card_block(got, CID)
    assert cardtext.CARD_PROMPT_CAP == 12000
    assert sum(len(ln) + 1 for ln in block[2:-3]) <= 12000 and block[-3] == cardtext.CARD_CUT.format(id=CID)


# -- the road ----------------------------------------------------------------------------------------------


def test_a_card_press_carries_the_card_between_the_id_lists_and_the_closing_sentence(tmp_path, monkeypatch):
    got = _got()
    asked = _reads(monkeypatch, got)
    prompt = _press(tmp_path, monkeypatch, CARD_PRESS, queue=_q())
    assert asked == [(CID, False)], "the read `/api/queue/card` serves: no mail's words"
    assert prompt == repoconfig.work_text(
        "TD-9", "samscrape", "docs/technical_debt.md", "yours", "Queue",
        ["samscrape#TD-012", "samscrape#TD-009"], ["samscrape#TD-020"], card=cardtext.card_block(got, CID),
    )  # fmt: skip
    assert f"{IDS}\n\n{DATA}\n\n" in prompt and prompt.endswith(f"\n\n{cardtext.CARD_END}\n\n{TAIL}")
    assert "SECRET" not in prompt and "I drive this one" not in prompt


def test_the_real_read_carries_the_card_ao_card_prints_and_never_a_mails_words(tmp_path, monkeypatch):
    """No stub: the road's own `Readings.card` over the world's `queue`, `list` and person inbox — the same read the
    UI's card endpoint serves, so the block is that answer through `card_block`, its ask by id alone."""
    ask = entry("m-41", "ask", from_="ao-samscrape-manager-sam", about="samscrape#TD-012", text="SECRET which name?")
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q(), inbox=[ask])
    got = c.get("/api/queue/card", params={"id": CID}).json()
    assert isinstance(got.get("card"), dict), got
    r = c.post("/api/ledger/start", json={"repo": "samscrape", **CARD_PRESS})
    assert r.status_code == 200, r.text
    (kw,) = created
    block = "\n".join(cardtext.card_block(got, CID))
    assert f".\n\n{block}\n\n{TAIL}" in kw["prompt"]
    assert "  m-41 · ask · from " in block and "SECRET" not in kw["prompt"]


def test_an_inbox_row_press_reads_the_card_that_holds_its_entry(tmp_path, monkeypatch):
    got = _got()
    asked = _reads(monkeypatch, got)
    prompt = _press(tmp_path, monkeypatch, {"id": "TD-9"}, queue=_q())
    assert asked == [(CID, False)]
    assert prompt.startswith("I opened this session from the Inbox") and f"\n\n{DATA}\n\n" in prompt


def test_an_inbox_entry_on_no_card_carries_none_and_reads_none(tmp_path, monkeypatch):
    asked = _reads(monkeypatch, _got())
    prompt = _press(tmp_path, monkeypatch, {"id": "TD-9"})
    assert asked == [] and "\n" not in prompt and prompt.endswith(f"the rest — none. {TAIL}")


@pytest.mark.parametrize(
    ("answer", "exc"),
    [
        (None, None),
        ({"ambiguous": ["a", "b"]}, None),
        ({"completed": {"closed": "2026-11-16"}}, None),
        ({"card": "not a card"}, None),
        (None, ui.CardRefused("down", "no socket")),
        (None, RuntimeError("anything at all")),
    ],
)
def test_a_read_that_is_no_card_or_fails_leaves_the_card_out_and_never_refuses(tmp_path, monkeypatch, answer, exc):
    asked = _reads(monkeypatch, answer, exc)
    prompt = _press(tmp_path, monkeypatch, CARD_PRESS, queue=_q())
    assert asked == [(CID, False)] and prompt == f"I opened this session from the Queue to work TD-9 of samscrape's " \
        f"ledger (docs/technical_debt.md) myself: it waits on me (its owner is me). {IDS} {TAIL}"  # fmt: skip


def test_a_kept_cards_press_reads_no_card(tmp_path, monkeypatch):
    asked = _reads(monkeypatch, _got())
    prompt = _press(tmp_path, monkeypatch, {"id": "TD-031", "item": "m-41", "card": KEPT_ID}, queue=_kq(),
                    inbox=[_kept_ask()])  # fmt: skip
    assert asked == [] and DATA.split("(")[0] not in prompt and prompt.endswith(f"the rest — none. {TAIL}")


def test_the_form_roads_url_carries_the_prompt_without_the_card(tmp_path, monkeypatch):
    """A create the host agent refuses comes after the card's read: the form still carries the card-less prompt."""
    asked = _reads(monkeypatch, _got())
    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], queue=_q(), refuse="no room")
    r = c.post("/api/ledger/start", json={"repo": "samscrape", **CARD_PRESS})
    got = r.json()
    assert r.status_code == 200 and got["ok"] is False and "no room" in got["why"], r.text
    assert asked == [(CID, False)], "read before the create, as the press would have sent it"
    prompt = parse_qs(urlsplit(got["form"]).query)["prompt"][0]
    assert prompt.endswith(f"{IDS} {TAIL}") and "end of the card" not in prompt and bare(prompt) == prompt
