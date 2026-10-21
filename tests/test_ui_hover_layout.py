"""design §4.5 *A hover changes colour, never layout* (TD-926, built by TD-928): a pointer or focus
state sets only colour-like properties, so nothing in a page's flow is drawn, hidden or resized under
the pointer — held over the one stylesheet every page loads."""

from __future__ import annotations

import re

import pytest
from test_css import CSS, _rules

pytestmark = pytest.mark.unit

STATES = re.compile(r":(hover|focus-within|focus-visible|focus|active)\b")
ALLOWED = re.compile(
    r"(color|background(-[a-z-]+)?|border-color|outline(-[a-z-]+)?|text-decoration(-[a-z-]+)?|box-shadow|filter|cursor)"
)


def test_a_pointer_or_focus_state_sets_only_colour():
    bad = [
        f"{sel} {{ {decl.strip()} }}"
        for sel, body in _rules(CSS.read_text(encoding="utf-8"))
        if STATES.search(sel)
        for decl in body.split(";")
        if decl.strip() and not ALLOWED.fullmatch(decl.split(":", 1)[0].strip())
    ]
    assert bad == [], "a state rule that changes layout (design §4.5 *A hover changes colour*):\n" + "\n".join(bad)


def test_the_rule_reads_a_state_inside_has_and_not():
    rules = _rules(".a:not(:hover) > .b { display: none; } .c:has(.d:focus-within) .e { color: red; }")
    assert [bool(STATES.search(sel)) for sel, _ in rules] == [True, True]
