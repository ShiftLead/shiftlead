"""The Gemini CLI adapter's composer and title (design §4.3 `composer`, `title`, TD-785): read from panes and
titles captured from the real tool (`tests/conformance/fixtures/gemini/`), and the send's paint wait and
retry that a composer gives it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shiftlead.adapters import gemini
from shiftlead.adapters.gemini import GeminiAdapter

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "conformance" / "fixtures" / "gemini"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _tail(name: str) -> list[str]:
    return (FIXTURES / "panes" / name).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("pane", MANIFEST["panes"], ids=lambda p: p["file"])
def test_the_composer_reads_what_was_painted(pane):
    assert GeminiAdapter().composer(_tail(Path(pane["file"]).name)) == pane["composer"]


def test_the_placeholder_is_grey_not_faint_so_it_is_read_by_its_words():
    row = next(r for r in _tail("idle-empty.txt") if gemini.PLACEHOLDER in r)
    assert "\x1b[2m" not in row  # had the tool painted it faint, `painted_text` would have dropped it
    assert GeminiAdapter().composer(_tail("idle-empty.txt")) == ""


def test_a_box_without_the_cursor_is_a_history_prompt_and_reads_as_no_composer():
    """A dialog in the composer's place leaves a history prompt's box the last on screen: never read as
    text still in the composer, which would hold a send as stuck."""
    tail = [r.replace(gemini.CURSOR, "") for r in _tail("idle-typed.txt")]
    assert GeminiAdapter().composer(tail) is None


def test_a_cursor_below_the_box_is_not_the_boxs():
    """Only the box's own rows are read for the cursor: a reverse-video cell in a footer below a history
    prompt's box never makes it a composer."""
    tail = [r.replace(gemini.CURSOR, "") for r in _tail("idle-typed.txt")]
    tail.append(gemini.CURSOR + " a footer cell")
    assert GeminiAdapter().composer(tail) is None


def test_no_box_on_screen_reads_as_no_composer():
    tail = [r for r in _tail("idle-typed.txt") if not gemini._border(gemini.painted_text(r))]
    assert GeminiAdapter().composer(tail) is None
    assert GeminiAdapter().composer([]) is None


def test_the_title_is_the_bracketed_cli_title():
    titles = json.loads((FIXTURES / "captured" / "titles.json").read_text(encoding="utf-8"))
    assert [GeminiAdapter().title(t) for t in titles] == MANIFEST["titles"][0]["names"]
    assert GeminiAdapter().title("✋  Action Required (a (b) c)") == "a (b) c"
    assert GeminiAdapter().title("kmaster@kmaster: ~/x") is None
    assert GeminiAdapter().title("") is None


def test_composer_and_title_are_declared():
    assert {"composer", "title"} <= GeminiAdapter.implements
