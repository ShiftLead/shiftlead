"""design §4.5a **Inbox row: routed around** (§4.9b *A seat that cannot answer is routed around*, TD-1443, built by
TD-1473 slice 4): a question whose entry carries `routed` draws one line, *routed around <name>: <why>*, as text —
on the Inbox row, the message page and the Queue card's mail item, all through the row macro — and `ao inbox`
prints it indented under the entry, `ao msg`'s reply before its *when it is read* lines. An entry without
`routed` draws none."""

from __future__ import annotations

import pytest
from test_ui_inbox import entry, rows
from test_ui_queue import client, fake, mail, queue

from sessionorc.mail import routed_line
from shiftlead import cli
from shiftlead.ui.app import templates

ROUTED = {"seat": "ao-x-techlead-ao-1", "name": "techlead-ao-1", "why": "limited, resets 08:00Z", "at": "t"}
LINE = "routed around techlead-ao-1: limited, resets 08:00Z"


@pytest.mark.unit
def test_the_words_and_a_malformed_envelope():
    assert routed_line(ROUTED) == LINE
    assert routed_line({"seat": "ao-x-rv"}) == "routed around ao-x-rv"
    assert routed_line(None) is None and routed_line("limited") is None


@pytest.mark.unit
def test_the_row_draws_the_line_under_the_text_and_no_button():
    html = rows("needs", [entry("m-1", "ask", text="which test covers this?", routed=ROUTED)])
    line = html[html.index('class="st dflt routed"') :]
    line = line[: line.index("</div>")]
    assert LINE in line and "<button" not in line and "<a " not in line
    assert html.index('class="body md"') < html.index('class="st dflt routed"')
    assert "routed around" not in rows("needs", [entry("m-2", "ask", text="which test covers this?")])


@pytest.mark.unit
def test_the_queue_mail_item_draws_the_same_line():
    e = entry("m-1", "ask", text="which test covers this?", routed=ROUTED)
    assert LINE in templates.get_template("queue_mail.html").render(e={**e, "want": "decide"}, section="needs")


def test_the_message_page_draws_the_line(tmp_path, monkeypatch):
    m = mail("m1", "which test covers this?", routed=ROUTED)
    assert LINE in client(monkeypatch, tmp_path, fake(queue(), [m])).get("/inbox/m1").text


def test_ao_inbox_prints_the_line_only_under_a_routed_entry(monkeypatch, capsys):
    def e(mid, **kw):
        return {"id": mid, "from": "ao-x-w", "from_role": "other", "to": ["person"], "at": "t", "kind": "ask",
                "text": f"text {mid}", "root": mid, **kw}  # fmt: skip

    got = {"id": "person", "entries": [e("m-1", routed=ROUTED), e("m-2")], "unread": 0}
    monkeypatch.setattr(cli, "call_sync", lambda m, **kw: got)
    assert cli.main(["inbox"]) == 0
    out = capsys.readouterr().out
    assert out.count("routed around") == 1 and out.index("text m-1") < out.index(f"  {LINE}") < out.index("text m-2")


def test_ao_msgs_reply_prints_where_it_went_before_when_it_is_read(monkeypatch, capsys):
    sent = {
        "entry": {"id": "m-9", "kind": "ask", "to": ["person"], "routed": ROUTED},
        "delivered": ["person"],
        "routed": ROUTED,
        "read_when": {"person": "on the Inbox now"},
    }
    monkeypatch.setattr(cli, "call_sync", lambda m, **kw: sent)
    assert cli.main(["msg", "ao-x-techlead-ao-1", "--kind", "ask", "which test covers this?"]) == 0
    out = capsys.readouterr().out
    assert out.count("routed around") == 1 and out.index(LINE) < out.index("person: on the Inbox now")


@pytest.mark.unit
def test_the_homes_words_are_escaped():
    hostile = {**ROUTED, "why": "<script>x</script>"}
    html = rows("needs", [entry("m-1", "ask", text="which?", routed=hostile)])
    assert "&lt;script&gt;" in html and "<script>x" not in html


@pytest.mark.unit
def test_the_seat_card_says_where_its_questions_go_while_it_cannot_answer(tmp_path, monkeypatch):
    """§4.5a card **routed around** line (TD-1473 slice 4b): an `asks` seat the home reads unable draws one line,
    *its questions go to <the techlead | you> while it cannot answer*, display only; gone once it is able."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import view

    base = {"id": "ao-x-rv", "name": "rv", "kind": "agent", "adapter": "claude-code", "dir": "/tmp/x",
            "state": "limited", "since": "2026-11-07T01:00:00Z", "pane": False, "tail": [],
            "created": "2026-11-07T00:00:00Z", "confidence": "tick", "seat": {"trigger": "asks"}}  # fmt: skip
    card = templates.get_template("card.html")
    for to in ("the techlead", "you"):
        html = card.render(s=view({**base, "seat_unable": "limited, resets 08:00Z", "seat_routed_to": to}))
        line = html[html.index('class="meta routed"') :]
        line = line[: line.index("</div>")]
        assert f"its questions go to {to} while it cannot answer" in line and "limited, resets 08:00Z" in line
        assert "<button" not in line and "<a " not in line
    assert "its questions go to" not in card.render(s=view({**base, "seat_unable": None, "seat_routed_to": None}))
    # the compact card (a member of a live team) draws it too
    v = {**view({**base, "seat_unable": "not supervised", "seat_routed_to": "you"}), "compact": True}
    assert "its questions go to you while it cannot answer" in card.render(s=v)


@pytest.mark.unit
def test_a_handed_entry_waiting_on_an_unable_seat_says_why_under_waiting_on_them():
    """§4.5a *Inbox row: routed around* (TD-1473 slice 4b): a handed entry under *Waiting on them* whose holder
    cannot answer says *waits: <name> <why>*; an able holder's row says nothing of it."""
    from datetime import UTC, datetime

    from test_ui_inbox import handed_entry

    from shiftlead.ui.app import handed_rows, inbox_sections

    at = datetime(2026, 9, 19, 12, tzinfo=UTC)
    rec = {"id": "ao-shiftlead-techlead-ao-1", "name": "techlead-ao-1", "team": "ao-grind", "state": "limited"}
    fleet = {rec["id"]: {**rec, "seat_unable": "limited, resets 08:00Z"}}
    got = inbox_sections([], now=at, handed=handed_rows([handed_entry("m-h1")], fleet, at))
    html = rows("waiting", got["waiting"])
    assert "waits: techlead-ao-1 limited, resets 08:00Z" in html
    able = inbox_sections([], now=at, handed=handed_rows([handed_entry("m-h1")], {rec["id"]: rec}, at))
    assert "waits:" not in rows("waiting", able["waiting"])


@pytest.mark.unit
def test_a_handed_entry_whose_move_is_held_says_the_moves_own_line():
    """§4.9b *A question already waiting* (TD-1480): a handed entry the tick would move but a count holds carries
    `waits`, and *Waiting on them* draws that line in place of the seat's own."""
    from datetime import UTC, datetime

    from test_ui_inbox import handed_entry

    from shiftlead.ui.app import handed_rows, inbox_sections

    at = datetime(2026, 9, 19, 12, tzinfo=UTC)
    rec = {"id": "ao-shiftlead-techlead-ao-1", "name": "techlead-ao-1", "team": "ao-grind", "state": "limited"}
    fleet = {rec["id"]: {**rec, "seat_unable": "limited, resets 08:00Z"}}
    held = {**handed_entry("m-h1"), "waits": "waits on techlead-db-1: its inbox holds 50 unread entries"}
    got = inbox_sections([], now=at, handed=handed_rows([held], fleet, at))
    html = rows("waiting", got["waiting"])
    assert "waits on techlead-db-1: its inbox holds 50 unread entries" in html and "waits: techlead-ao-1" not in html


def test_ao_inbox_and_sent_print_a_waits_line_only_while_it_is_open(monkeypatch, capsys):
    """§4.9b *A question already waiting* (TD-1480): `ao inbox` and `ao inbox --sent` print an open entry's
    `waits` indented under its text; a closed one's is not printed, and a rerouted one names its close."""
    line = "waits on the person: you have m-0 open to the person"

    def e(mid, **kw):
        return {"id": mid, "from": "ao-x-w", "from_role": "other", "to": ["ao-x-tl"], "at": "t", "kind": "ask",
                "text": f"text {mid}", "root": mid, **kw}  # fmt: skip

    got = {"id": "ao-x-w", "entries": [e("m-1", waits=line), e("m-2", waits=line, closed_reason="rerouted")]}
    monkeypatch.setattr(cli, "call_sync", lambda m, **kw: {**got, "unread": 0})
    for argv in (["inbox"], ["inbox", "--sent"]):
        assert cli.main(argv) == 0
        out = capsys.readouterr().out
        assert out.count(line) == 1 and out.index("text m-1") < out.index(line) < out.index("text m-2")
        assert "rerouted" in out


@pytest.mark.unit
def test_a_rerouted_question_says_so_on_its_row():
    html = rows("fyi", [entry("m-1", "ask", text="q?", closed_reason="rerouted", closed_at="t")])
    assert "closed · routed around a seat that could not answer" in html
