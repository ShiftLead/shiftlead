"""A jump to a prompt (design §4.6 *A jump to a prompt*, TD-975, built by TD-977): the walk is a pure
function of the pane's rows and the card's openings, the bridge ignores a bad `jump`, and a jump sets the
*scrolled* mark as a scroll does. The landing on a real tmux is `test_pty_bridge_jump_tmux.py`."""

from __future__ import annotations

import asyncio

import pytest

from shiftlead.ui import pty_bridge
from shiftlead.ui.pty_bridge import jump_openings, jump_read, jump_walk, land_argv, leave_argv, pump, run_jump

pytestmark = pytest.mark.unit


def op(drawn: str, whole: bool = True) -> dict:
    return {"drawn": drawn, "whole": whole}


def test_a_repeated_opening_walks_past_the_newer_copy():
    rows = ["❯ yes", "⏺ done", "❯ do the thing", "⏺ did it", "❯ yes", "⏺ again"]
    assert jump_walk(rows, [op("❯ yes")]) == 4  # the newest *yes*, nearest the bottom
    # the older *yes*: found above *do the thing*, which is found above the newer *yes*
    assert jump_walk(rows, [op("❯ yes"), op("❯ do the thing"), op("❯ yes")]) == 0


def test_a_repainted_conversation_walks_its_newest_copy():
    conv = ["❯ first", "⏺ one", "❯ second", "⏺ two"]
    rows = conv + ["─" * 20] + conv  # a resize repaint draws every prompt again (TD-794)
    assert jump_walk(rows, [op("❯ second"), op("❯ first")]) == 5
    assert jump_walk(rows, [op("❯ second")]) == 7


def test_a_newer_prompt_not_found_is_skipped():
    rows = ["❯ old one", "⏺ reply", "[Pasted text #1 +40 lines]", "⏺ more"]
    assert jump_walk(rows, [op("❯ a long paste the tool drew as its placeholder", False), op("❯ old one")]) == 0


def test_a_skipped_newer_prompt_with_the_same_opening_gives_its_row():
    # accepted (design §4.6): both rows read the same
    rows = ["❯ yes", "⏺ a", "❯ yes"]
    assert jump_walk(rows, [op("❯ gone"), op("❯ yes")]) == 2


def test_an_indented_dialog_row_counts_only_where_an_opening_is_that_row():
    rows = ["❯ 1", "⏺ which one?", "  ❯ 1. Yes", "    2. No"]
    assert jump_walk(rows, [op("❯ 1")]) == 0  # whole: `❯ 1. Yes` is not `❯ 1`
    assert jump_walk(rows, [op("❯ 1.", False)]) == 2  # an opening that is that very row
    assert jump_walk(["  ❯\xa0hello there  "], [op("❯ hello there")]) == 0  # indented, a non-breaking space


def test_whole_must_equal_and_a_cut_opening_is_a_start():
    rows = ["❯ yes please", "⏺ ok"]
    assert jump_walk(rows, [op("❯ yes")]) is None
    assert jump_walk(rows, [op("❯ yes", False)]) == 0


def test_a_miss_and_an_empty_opening():
    assert jump_walk(["⏺ nothing here"], [op("❯ hello")]) is None
    assert jump_walk(["❯ x", ""], [op("   ", False)]) is None  # an empty opening matches nothing
    assert jump_walk([], [op("❯ x")]) is None


def test_the_openings_a_jump_takes():
    assert jump_openings([op("❯ a"), op("❯ b", False)]) == [op("❯ a"), op("❯ b", False)]
    assert jump_openings([{**op("❯ a"), "extra": 1}]) == [op("❯ a")]
    for bad in (
        None,
        "❯ a",
        {},
        [],
        ["❯ a"],
        [{"drawn": 1, "whole": True}],
        [{"drawn": "x", "whole": 1}],
        [{"drawn": "x"}],
        [op("x" * 201)],
        [op("x")] * 21,
    ):
        assert jump_openings(bad) is None, bad
    assert jump_openings([op("x" * 200)] * 20) is not None


def test_the_read_and_the_argvs():
    assert jump_read("282\nrow 0\nrow 1\n") == (282, ["row 0", "row 1"])
    assert jump_read("0\n") == (0, [])
    assert jump_read("") is None and jump_read("can't find pane\n") is None
    argv = pty_bridge.jump_argv("ao-x", socket_name="s")
    assert argv[:3] == ["tmux", "-L", "s"]
    assert " ".join(argv[3:]) == (
        "copy-mode -q -t =ao-x: ; copy-mode -e -t =ao-x: ; display-message -p -t =ao-x: #{history_size} ; "
        "capture-pane -p -S - -E - -t =ao-x:"
    )
    assert land_argv("ao-x", 82) == ["tmux", "send-keys", "-X", "-t", "=ao-x:", "goto-line", "82"]
    assert land_argv("ao-x", -3)[-1] == "0"


def _jump(out: str | None, openings: list[dict], *, land_fails: bool = False):
    ran: list = []

    async def read(argv):
        ran.append(("read", argv))
        return out

    async def run(argv):
        ran.append(("run", argv))
        if land_fails and "goto-line" in argv:
            raise TimeoutError

    landed = asyncio.run(run_jump(openings, read, run, "ao-x"))
    return landed, [a for k, a in ran if k == "run"]


def test_run_jump_lands_or_leaves():
    out = "3\n❯ hello\n⏺ hi\nmore\n❯ next\n⏺ ok\n"  # three rows of history, then the screen
    assert _jump(out, [op("❯ hello")]) == (True, [land_argv("ao-x", 3)])
    assert _jump(out, [op("❯ next")]) == (True, [land_argv("ao-x", 0)])  # on the live screen
    assert _jump(out, [op("❯ gone")]) == (False, [leave_argv("ao-x")])
    assert _jump(None, [op("❯ hello")]) == (False, [leave_argv("ao-x")])  # a read past `JUMP_WITHIN`
    assert _jump("oops", [op("❯ hello")]) == (False, [leave_argv("ao-x")])
    assert _jump(out, [op("❯ hello")], land_fails=True)[0] is False


class FakePty:
    def __init__(self, log: list):
        self.log = log
        self._end = asyncio.Event()

    async def read(self):
        await self._end.wait()
        return None

    def write(self, data: bytes) -> None:
        self.log.append(("write", data))

    def resize(self, cols: int, rows: int) -> None:
        pass

    def close(self) -> None:
        self._end.set()


def _pump(frames: list, *, read_only: bool = False, fails: bool = False) -> list:
    log: list = []
    queue = list(frames)

    async def recv():
        await asyncio.sleep(0)
        return queue.pop(0) if queue else None

    async def send(data: bytes) -> None:
        pass

    async def scroll(direction, lines):
        log.append(("scroll",))

    async def leave():
        log.append(("leave",))

    async def jump(openings):
        await asyncio.sleep(0.01)  # a key after it waits for it
        log.append(("jump", openings))
        if fails:
            raise RuntimeError("tmux failed")
        return True

    asyncio.run(
        asyncio.wait_for(pump(FakePty(log), send, recv, scroll, leave=leave, jump=jump, read_only=read_only), 10)
    )
    return log


def test_a_jump_is_awaited_in_order_and_sets_the_scrolled_mark():
    log = _pump([{"jump": [op("❯ a")]}, "x"])
    assert log == [("jump", [op("❯ a")]), ("leave",), ("write", b"x")]


def test_a_bad_jump_is_ignored_and_sets_nothing():
    log = _pump([{"jump": "❯ a"}, {"jump": [op("x" * 201)]}, "x"])
    assert log == [("write", b"x")]


def test_a_read_only_attach_passes_a_jump_and_a_failed_one_keeps_the_attach():
    assert _pump([{"jump": [op("❯ a")]}, "x"], read_only=True) == [("jump", [op("❯ a")])]
    log = _pump([{"jump": [op("❯ a")]}, {"jump": [op("❯ b")]}], fails=True)
    assert [e[0] for e in log] == ["jump", "jump"]
