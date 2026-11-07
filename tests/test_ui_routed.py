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
