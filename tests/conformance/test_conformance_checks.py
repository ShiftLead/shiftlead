"""The conformance suite's own checks fail where they should (design §4.3 *The conformance suite*, TD-784):
an adapter missing a method it declares, one with a method it does not declare, and one whose reading
carries a tool's field name each fail."""

from __future__ import annotations

import pytest
from _harness import (
    check_background,
    check_context,
    check_declaration,
    check_neutral,
    check_spend,
    check_state,
    check_transcript,
)

from sessionorc.adapters import Transcript, TranscriptEntry

pytestmark = pytest.mark.unit

TOOL = frozenset({"isSidechain", "input_tokens"})


class Declares:
    name = "fake"
    implements = frozenset({"links"})

    def links(self, *a, **k):
        return [], 0


def test_a_declared_method_that_is_missing_fails():
    class Missing:
        implements = frozenset({"links", "context"})

        def links(self, *a, **k):
            return [], 0

    with pytest.raises(AssertionError, match="declares 'context'"):
        check_declaration(Missing())


def test_a_method_not_declared_fails():
    class Extra(Declares):
        def composer(self, tail):
            return ""

    with pytest.raises(AssertionError, match="has 'composer' without declaring it"):
        check_declaration(Extra())


def test_a_declaration_of_no_optional_method_fails():
    class Odd(Declares):
        implements = frozenset({"links", "teleport"})

    with pytest.raises(AssertionError, match="teleport"):
        check_declaration(Odd())


def test_a_permission_channel_that_is_no_bool_fails():
    class Odd(Declares):
        permission_channel = "yes"

    with pytest.raises(AssertionError, match="permission_channel"):
        check_declaration(Odd())
    check_declaration(Declares())  # and the honest one passes


def test_a_tool_field_name_in_a_reading_fails():
    with pytest.raises(AssertionError, match="isSidechain"):
        check_neutral({"entries": [{"kind": "text", "isSidechain": False}]}, TOOL)
    with pytest.raises(AssertionError, match="input_tokens"):
        check_spend(
            {
                "turns": [
                    {
                        "at": None,
                        "id": "x",
                        "source": "f",
                        "offset": 0,
                        "response": None,
                        "model": "m",
                        "input": 1,
                        "output": 1,
                        "cache_read": 0,
                        "cache_write": 0,
                        "cost": {"input_tokens": 1},
                    }
                ],
                "cursors": {},
                "reason": "ok",
            },
            TOOL,
        )
    check_neutral({"entries": [{"kind": "text", "text": "isSidechain"}]}, TOOL)  # a value is not a key


def test_a_kind_that_is_not_neutral_fails():
    tr = Transcript(path="p", size=0, entries=[TranscriptEntry(kind="tool_use")])
    with pytest.raises(AssertionError, match="tool_use"):
        check_transcript(tr, TOOL)
    with pytest.raises(AssertionError, match="not a Transcript"):
        check_transcript({"entries": []}, TOOL)


def test_the_shapes_are_held():
    with pytest.raises(AssertionError):
        check_state("thinking")
    check_state(None)
    check_state("needs-you")
    with pytest.raises(AssertionError):
        check_context({"tokens": 10, "at": None, "window": 5})  # more than the window holds
    with pytest.raises(AssertionError):
        check_context({"tokens": 10, "at": None, "window": None, "model": "m"})
    check_context({"tokens": 10, "at": None, "window": None})
    with pytest.raises(AssertionError):
        check_background([{"pid": 1, "cmd": "x"}])
    check_background(None)
