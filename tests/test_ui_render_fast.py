"""TD-747: what the Inbox's render no longer pays for, each drawing exactly what it drew — a row's key read
at once on a plain dict, a text's markdown rendered once, a text's subject derived once."""

from __future__ import annotations

import pytest
from test_ui_inbox import entry, rows


@pytest.mark.unit
def test_a_dict_key_is_read_as_jinja_reads_it():
    """A plain dict's key is its value, a missing one undefined, and a name a `dict` has (`items`, `get`)
    is still the method, as Jinja's own attribute-first lookup draws them; anything else goes Jinja's way."""
    from shiftlead.ui.common import _getattr, _jinja_getattr, templates

    tpl = templates.env.from_string(
        "{{ e.text }}|{{ e.gone }}|{{ e.items is callable }}|{{ e.get('text') }}|{{ o.real }}"
    )
    e = {"text": "a", "items": 3}
    assert tpl.render(e=e, o=2) == "a||True|a|2"
    assert _getattr(e, "text") == _jinja_getattr(e, "text") == "a"
    assert _getattr(e, "items") == _jinja_getattr(e, "items") == e.items


@pytest.mark.unit
def test_the_inbox_rows_draw_the_same_with_jinjas_own_lookup(monkeypatch):
    """Four sections' rows, of every mail kind, render byte for byte as they do with Jinja's
    attribute-first lookup."""
    from shiftlead.ui import common

    es = [
        entry("m-1", "ask", text="Merge it? It is green.\n\n- one\n- two", answers=["Yes", "No"]),
        entry("m-2", "steer", text="I will go with **A**.", default="A"),
        entry("m-3", "note", text="FYI: [a link](https://example.com/x) and `code`.", pr=12),
        entry("m-4", "reply", text="merged #12", about="TD-7", reply_to="m-1"),
    ]
    sections = ("needs", "steering", "fyi", "snoozed")
    ours = [rows(s, es) for s in sections]
    monkeypatch.setattr(common.templates.env, "getattr", common._jinja_getattr)
    assert [rows(s, es) for s in sections] == ours


@pytest.mark.unit
def test_a_text_is_rendered_once_and_its_subject_derived_once():
    """`render` is kept per argument triple and `row_subject` per text: the second row with the same text
    renders and derives nothing, and draws what the first drew."""
    from shiftlead.ui import inbox, render

    render.render.cache_clear()
    inbox._subject_of.cache_clear()
    text = "A text only this test sends. Its reading follows."
    one, two = rows("fyi", [entry("m-1", text=text)]), rows("fyi", [entry("m-1", text=text)])
    assert one == two and "A text only this test sends." in one
    assert render.render.cache_info().hits >= 1 and inbox._subject_of.cache_info().hits >= 1
