"""The terminal bridge (design §4.6): one pty per open Focus terminal, wrapping `tmux attach`
(local transport) or `ssh -tt host tmux attach` (phase 2), pumped to a websocket.

`ptyprocess` owns the child pty (controlling tty, SIGWINCH, teardown); this module adds only the
asyncio read loop and the websocket framing. Resize is `setwinsize` on the local pty.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable

import ptyprocess

from sessionorc.models import RECENT_PROMPTS
from sessionorc.settings import TERMINAL_GRID
from sessionorc.tmux import attach_argv as tmux_attach_argv

# The bridge's queue is bounded in bytes (TD-611 slice 5): past `QUEUE_HIGH` unsent the pty is no
# longer read — tmux holds the output, as it does for any slow client — and from `QUEUE_LOW` it is
# read again, so a stalled loop or a slow socket never grows the UI's memory without bound. One read
# joins at most `JOIN_MAX` (and one pty read past it), so no frame is a megabyte for xterm to parse
QUEUE_HIGH = 1 << 20
QUEUE_LOW = 1 << 18
JOIN_MAX = 1 << 18

log = logging.getLogger(__name__)


class PtySession:
    def __init__(self, argv: list[str], *, cols: int = 120, rows: int = 32, env: dict[str, str] | None = None):
        self.proc = ptyprocess.PtyProcess.spawn(
            argv, dimensions=(rows, cols), env={**os.environ, "TERM": "xterm-256color", **(env or {})}
        )
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._queued = 0  # bytes in the queue, not yet handed to `read`
        self._paused = False  # the pty's reader is off while the queue is past `QUEUE_HIGH`
        self._ended = False  # the end was taken out of the queue
        self._closed = False
        self._loop.add_reader(self.proc.fd, self._on_readable)

    def _on_readable(self) -> None:
        if self._closed:
            return
        try:
            data = os.read(self.proc.fd, 65536)
        except OSError:
            data = b""
        if not data:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(self.proc.fd)
            self._paused = False
            self._queue.put_nowait(None)
            return
        self._queue.put_nowait(data)
        self._queued += len(data)
        if self._queued > QUEUE_HIGH and not self._paused:
            self._paused = True
            with contextlib.suppress(Exception):
                self._loop.remove_reader(self.proc.fd)

    async def read(self) -> bytes | None:
        """What the pty has written since the last read, joined into one chunk up to `JOIN_MAX` — a
        stalled loop that wakes to many frames sends them as one (TD-611 slice 5) — or None when the
        child is gone."""
        if self._ended:
            return None
        first = await self._queue.get()
        if first is None:
            self._ended = True
            return None
        parts, size = [first], len(first)
        while size < JOIN_MAX and not self._queue.empty():
            more = self._queue.get_nowait()
            if more is None:
                self._ended = True  # the data before it goes now; the end on the next read
                break
            parts.append(more)
            size += len(more)
        got = b"".join(parts)
        self._queued -= len(got)
        if self._paused and not self._closed and self._queued <= QUEUE_LOW:
            self._paused = False
            with contextlib.suppress(Exception):
                self._loop.add_reader(self.proc.fd, self._on_readable)
        return got

    def write(self, data: bytes) -> None:
        if self.proc.isalive():
            self.proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        with contextlib.suppress(Exception):
            self.proc.setwinsize(max(2, rows), max(10, cols))

    def exit_status(self) -> int | None:
        """The attach process's exit code once it is gone, None while it is alive. `tmux attach`
        exits non-zero when the session it was given is not there, which is how the bridge tells a
        dead attach from a person detaching (TD-029)."""
        try:
            if not self.proc.isalive():  # isalive() reaps, so exitstatus is set after it
                return self.proc.exitstatus
        except Exception:  # noqa: BLE001 — already gone, or never started: nothing to report
            return None
        return None

    def close(self) -> None:
        self._closed = True
        with contextlib.suppress(Exception):
            self._loop.remove_reader(self.proc.fd)
        with contextlib.suppress(Exception):
            self.proc.terminate(force=True)


def attach_argv(session_id: str, *, socket_name: str | None = None, features: tuple[str, ...] = ()) -> list[str]:
    return tmux_attach_argv(session_id, socket_name=socket_name, features=features)


def scroll_argv(
    session_id: str, direction: str, lines: int | None = None, *, socket_name: str | None = None
) -> list[str]:
    """Scrollback, reached through tmux (TD-022): Shift+PageUp/PageDown in the browser, and the wheel
    (design §4.6 *The mouse is the browser's*, TD-174). Without `lines` it is a page: up enters copy
    mode and pages up (repeatable: each call pages further); down pages down and, thanks to `-e`,
    leaves copy mode on reaching the live screen. With `lines` — the wheel's notches of one animation
    frame — it enters copy mode (`-e`, a no-op when already in it) and scrolls that many lines up or
    down, so a notch is lines, not a page, and reaching the bottom leaves copy mode as before. Down
    outside copy mode is a harmless "not in a mode"."""
    argv = ["tmux", "-L", socket_name] if socket_name else ["tmux"]
    target = f"={session_id}:"
    if direction not in ("up", "down"):
        raise ValueError(f"scroll direction {direction!r}: expected 'up' or 'down'")
    if lines is not None:
        if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
            raise ValueError(f"scroll lines {lines!r}: expected a whole number from 1")
        n = str(min(lines, SCROLL_MAX))
        return argv + [
            "copy-mode",
            "-e",
            "-t",
            target,
            ";",
            "send-keys",
            "-X",
            "-N",
            n,
            "-t",
            target,
            f"scroll-{direction}",
        ]
    if direction == "up":
        return argv + ["copy-mode", "-e", "-u", "-t", target]
    return argv + ["send-keys", "-X", "-t", target, "page-down"]


def leave_argv(session_id: str, *, socket_name: str | None = None) -> list[str]:
    """Back to the live screen before a typed key (design §4.6 *Typing returns the pane to the live
    screen*, TD-667): `copy-mode -q` leaves any mode the pane is in, and does nothing when it is in none."""
    argv = ["tmux", "-L", socket_name] if socket_name else ["tmux"]
    return argv + ["copy-mode", "-q", "-t", f"={session_id}:"]


LEAVE_WITHIN = 2.0  # seconds a leave may take before the key is written anyway (design §4.6)

JUMP_WITHIN = 5.0  # seconds a jump's read may take before it is a miss (design §4.6 *A jump to a prompt*)
JUMP_DRAWN_MAX = 200  # characters of one opening in a `jump` message


def jump_argv(session_id: str, *, socket_name: str | None = None) -> list[str]:
    """A jump's one read, the view held (design §4.6 *A jump to a prompt*, TD-975): leave any copy mode
    (`copy-mode -e` on a pane already in mode keeps that mode's older view), enter it again, and print
    `history_size` and the cursor's row (`cursor_y`, which copy mode keeps through the landing), then every
    row of the pane, history and screen, as plain text."""
    argv = ["tmux", "-L", socket_name] if socket_name else ["tmux"]
    t = f"={session_id}:"
    return argv + [
        *("copy-mode", "-q", "-t", t, ";"),
        *("copy-mode", "-e", "-t", t, ";"),
        *("display-message", "-p", "-t", t, "#{history_size} #{cursor_y}", ";"),
        *("capture-pane", "-p", "-S", "-", "-E", "-", "-t", t),
    ]


def land_argv(session_id: str, line: int, *, socket_name: str | None = None) -> list[str]:
    """The landing: copy mode's `goto-line`, `line` the lines above the live screen, so the found row is
    the terminal's top (0 for a row on the live screen). `send-keys -F` is not used: on tmux 3.5a its
    `goto-line` argument did not land."""
    argv = ["tmux", "-L", socket_name] if socket_name else ["tmux"]
    return argv + ["send-keys", "-X", "-t", f"={session_id}:", "goto-line", str(max(0, int(line)))]


def jump_openings(value: object) -> list[dict] | None:
    """A `jump` message's openings, or None for one the bridge ignores (design §4.6): a list of at most
    `RECENT_PROMPTS` objects, each a string `drawn` of at most `JUMP_DRAWN_MAX` characters and a boolean
    `whole`, newest first, the pressed one last."""
    if not isinstance(value, list) or not value or len(value) > RECENT_PROMPTS:
        return None
    out = []
    for o in value:
        if not isinstance(o, dict):
            return None
        drawn, whole = o.get("drawn"), o.get("whole")
        if not isinstance(drawn, str) or len(drawn) > JUMP_DRAWN_MAX or not isinstance(whole, bool):
            return None
        out.append({"drawn": drawn, "whole": whole})
    return out


def _flat(text: str) -> str:
    # a row and an opening alike: leading whitespace stripped, trailing spaces trimmed, a non-breaking
    # space read as a space, since the tool may draw its glyph indented and followed by one
    return text.replace("\xa0", " ").strip()


def jump_walk(rows: list[str], openings: list[dict]) -> int | None:
    """The row the pressed prompt starts on, or None (design §4.6 *The walk*). From the bottom row up,
    the newest opening's row, then above it the next one's, and so on to the pressed one's, the last:
    each found above the last, so the newest copy of a repainted conversation is walked and a newer
    prompt with the same opening is passed on the way. A newer opening not found is skipped and the walk
    goes on from where it stood. An opening marked `whole` must equal the row; any other is its start."""
    flat = [_flat(r) for r in rows]
    stood = len(flat)
    for k, o in enumerate(openings):
        want = _flat(o["drawn"])
        hit = None
        if want:
            for i in range(stood - 1, -1, -1):
                if flat[i] == want if o["whole"] else flat[i].startswith(want):
                    hit = i
                    break
        if hit is None:
            if k == len(openings) - 1:
                return None
            continue
        stood = hit
    return stood


def jump_read(out: str) -> tuple[int, int, list[str]] | None:
    """`jump_argv`'s output as `(history_size, cursor_y, rows)`: its first line is `history_size` and
    `cursor_y`, row *i* the *i*-th line after it. None for output that does not start with two numbers."""
    lines = out.split("\n")
    head = lines[0].split() if lines else []
    if len(head) != 2 or not all(h.isdigit() for h in head):
        return None
    rows = lines[1:]
    if rows and rows[-1] == "":
        rows.pop()  # the newline that ends the capture
    return int(head[0]), int(head[1]), rows


async def run_jump(
    openings: list[dict],
    read: Callable[[list[str]], Awaitable[str | None]],
    run: Callable[[list[str]], Awaitable[None]],
    session_id: str,
    *,
    socket_name: str | None = None,
) -> tuple[int, int] | None:
    """One jump (design §4.6): the read through `read` (bounded by the caller at `JUMP_WITHIN`; None is a
    miss), the walk, and the landing or, on a miss, `copy-mode -q` through `run`. `(row, cursor)` when it
    landed — the landed row on the terminal (0 for a history row, which `goto-line` puts at the top; its row
    on the live screen for one there) and the cursor's — else None (test it with `is not None`: a history
    landing's row is 0)."""
    got = None
    with contextlib.suppress(Exception):
        out = await read(jump_argv(session_id, socket_name=socket_name))
        got = jump_read(out) if out is not None else None
    i = jump_walk(got[2], openings) if got else None
    try:
        if i is None:
            await run(leave_argv(session_id, socket_name=socket_name))
            return None
        hist, cursor = got[0], got[1]  # type: ignore[index]
        await run(land_argv(session_id, hist - i, socket_name=socket_name))
    except Exception as e:  # noqa: BLE001 — a failed landing is a miss, never the attach's end
        log.warning("a jump's landing failed: %s", type(e).__name__)
        return None
    return (0 if i < hist else i - hist), cursor


_KEYS_THAT_COUNT = (b"\r", b"\t", b"\x7f", b"\b")
_PASTE_OPENER = b"\x1b[200~"


def counts_as_typing(data: bytes) -> bool:
    """Whether a key frame is typing that leaves copy mode (design §4.6 *What counts as typing*): a
    bracketed paste (the one ESC-led frame that counts); no other ESC-led frame — arrows, function and
    Alt keys, and xterm.js's replies to the program's queries; Enter, Tab or Backspace alone; else a
    frame holding a printable character. Ctrl+C, Escape and every other control byte alone do not."""
    if data.startswith(b"\x1b"):
        return data.startswith(_PASTE_OPENER)
    if data in _KEYS_THAT_COUNT:
        return True
    return any(c.isprintable() for c in data.decode(errors="replace"))


SCROLL_MAX = 500  # lines in one wheel message: a frame's notches are a handful, so this only bounds a bad client


GRID_EVERY = 5.0  # seconds between the bridge's readings of the window (design §4.6)
GRID_READ_WITHIN = 3.0  # seconds a reading may take before it is no reading


def grid_argv(session_id: str, *, socket_name: str | None = None) -> list[str]:
    """The bridge's reading of the window (design §4.6 *Attach behaviour with another client present*,
    TD-1919): its size and how many lines tmux's status bar takes from it."""
    argv = ["tmux", "-L", socket_name] if socket_name else ["tmux"]
    return argv + ["display-message", "-p", "-t", f"={session_id}:", "#{window_width} #{window_height} #{status}"]


def grid_read(out: str | None) -> tuple[int, int] | None:
    """`grid_argv`'s output as `(cols, rows)`, the rows counted as a client's grid counts them — the window's
    height and the status bar's lines (tmux's `status` option: `on` one, `off` none, a number that many),
    which are none on a session's window. None for anything else."""
    parts = (out or "").split()
    if len(parts) != 3 or not all(p.isdigit() for p in parts[:2]):
        return None
    w, h = int(parts[0]), int(parts[1])
    st = parts[2]
    bar = 1 if st == "on" else 0 if st == "off" else int(st) if st.isdigit() else 0
    return w, h + bar


def fit_grid(value: object) -> tuple[int, int] | None:
    """A `fit` message's grid, `(cols, rows)`, or None for one outside `person.terminal.grid`'s bounds
    (`TERMINAL_GRID`, the setting's and the fit's) or not two whole numbers (design §4.6 *Fit to window*)."""
    (clo, chi), (rlo, rhi) = TERMINAL_GRID
    if not isinstance(value, list) or len(value) != 2:
        return None
    if any(isinstance(n, bool) or not isinstance(n, int) for n in value):
        return None
    cols, rows = value
    return (cols, rows) if clo <= cols <= chi and rlo <= rows <= rhi else None


class GridKeeper:
    """The one grid this bridge last sent the page, shared by the five-second watcher and a fit (design §4.6):
    a changed reading resizes the bridge's own pty before its `grid` frame goes, so a fit made from another
    browser leaves no client at the old size; one lock orders them, and a watcher reading taken before a fit
    is dropped rather than sent after it."""

    def __init__(
        self,
        pty: PtySession,
        read: Callable[[], Awaitable[str | None]],
        send_text: Callable[[str], Awaitable[object]],
        sent: tuple[int, int],
    ):
        self.pty, self.read, self.send_text, self.sent = pty, read, send_text, sent
        self.lock = asyncio.Lock()
        self.fits = 0  # how many fits have run: a watcher reading taken before one is stale

    async def _reading(self) -> tuple[int, int] | None:
        out = None
        with contextlib.suppress(Exception):
            out = await self.read()
        return grid_read(out)

    async def _take(self, grid: tuple[int, int], *, always: bool = False) -> None:
        # under the lock: the pty first, then the page's frame
        if grid == self.sent and not always:
            return
        if grid != self.sent:
            self.pty.resize(*grid)
        self.sent = grid
        await self.send_text(json.dumps({"grid": list(grid)}))

    async def watch(self, every: float = GRID_EVERY) -> None:
        """Read the window every `every` seconds while attached and take a reading that differs. A failed
        read changes nothing. Runs until cancelled, or until a send fails."""
        while True:
            await asyncio.sleep(every)
            fits = self.fits
            got = await self._reading()
            if got is None:
                continue
            async with self.lock:
                if fits != self.fits:
                    continue  # a fit ran while this was read: its answer stands
                try:
                    await self._take(got)
                except Exception:  # noqa: BLE001 — the socket went away: the pump's end cancels this anyway
                    return

    async def fit(self, grid: tuple[int, int], resize: Callable[[tuple[int, int]], Awaitable[None]]) -> None:
        """Carry out the person's fit: `resize` the window, read it again, resize the pty to that reading and
        answer with its `grid` frame, so a failed command answers with the grid the window kept."""
        async with self.lock:
            self.fits += 1
            with contextlib.suppress(Exception):
                await resize(grid)
            got = await self._reading()
            if got is not None:
                await self._take(got, always=True)


def resize_window_argv(session_id: str, cols: int, rows: int, *, socket_name: str | None = None) -> list[str]:
    """A fit's command (design §4.6 *Fit to window*): the session's window to `cols` × `rows`, which also
    keeps it `window-size manual`."""
    argv = ["tmux", "-L", socket_name] if socket_name else ["tmux"]
    return argv + ["resize-window", "-t", f"={session_id}:", "-x", str(int(cols)), "-y", str(int(rows))]


async def pump(
    pty: PtySession,
    send: Callable[[bytes], object],
    recv: Callable[[], object],
    scroll: Callable[[str, int | None], Awaitable[None]] | None = None,
    *,
    leave: Callable[[], Awaitable[None]] | None = None,
    jump: Callable[[list[dict]], Awaitable[object]] | None = None,
    fit: Callable[[tuple[int, int]], Awaitable[None]] | None = None,
    read_only: bool = False,
    name: str = "",
) -> None:
    """Run both directions until either side ends. `recv` yields str (keys), bytes, or a dict
    with `fit: [cols, rows]` or `scroll: "up" | "down"` and, for the wheel, `lines: n`; `send`
    takes raw bytes for xterm.js; `scroll` (optional) is awaited for scroll messages, which need a
    tmux command, not keys.

    `fit` (optional; design §4.6 *Fit to window*, TD-1919): a `fit` message within `TERMINAL_GRID` is
    logged as `term fit <name> <cols>x<rows>` and awaited as `fit((cols, rows))` in frame order, as a
    scroll is; the callback resizes the window and the pty and answers the page with its text frame. One
    outside the bounds is refused and logged. A `resize` message changes nothing — the pane's grid is the
    window's, pinned — and is logged once per attach.

    `leave` (optional; design §4.6 *Typing returns the pane to the live screen*, TD-667): any scroll
    message sets the *scrolled* mark, and a key frame that counts as typing (`counts_as_typing`) while
    it stands awaits `leave()` — bounded at `LEAVE_WITHIN`, a failure logged — and clears the mark
    before the key is written. Scroll and leave are awaited one at a time in frame order, so a leave
    never overtakes the scroll before it.

    `read_only` (design §4.6 *A read-only attach*, TD-096): key frames are dropped — str and bytes
    alike, every one: the wheel is a scroll message, never a mouse report (TD-174). Fit and
    scroll messages pass as ever: it types nothing, so an `unattended` session is fitted without a Take over.

    `jump` (optional; design §4.6 *A jump to a prompt*, TD-975): a dict with `jump: [{drawn, whole}, …]`
    is awaited as `jump(openings)` in frame order, as a scroll is, and sets the *scrolled* mark; one
    `jump_openings` refuses is ignored. The callback answers the page itself and returns whether it landed.
    A read-only attach passes it, as a scroll."""

    async def down() -> None:
        try:
            while (chunk := await pty.read()) is not None:
                await send(chunk)  # type: ignore[misc]
        except Exception:  # noqa: BLE001 — the socket went away mid-send: that ends the pump, quietly
            return

    scrolled = False
    resize_said = False

    async def up() -> None:
        nonlocal scrolled, resize_said
        while True:
            msg = await recv()  # type: ignore[misc]
            if msg is None:
                return
            if isinstance(msg, dict):
                if "resize" in msg:
                    if not resize_said:  # an older page's: the window is pinned (TD-1919)
                        resize_said = True
                        log.info("term %s: a resize message changes nothing (the window is pinned)", name or "-")
                elif "fit" in msg and fit is not None:
                    grid = fit_grid(msg["fit"])
                    if grid is None:
                        # ints never reach the log from a client's odd value: the refusal says only that
                        log.warning("term %s: a fit outside the grid's bounds refused", name or "-")
                        continue
                    # one line per fit, so a repeated or garbled repaint can be lined up with the fits before it
                    log.info("term fit %s %dx%d", name or "-", *grid)
                    try:
                        await fit(grid)
                    except Exception as e:  # noqa: BLE001 — a failed fit is never the attach's end
                        log.warning("a fit failed: %s", type(e).__name__)
                elif "scroll" in msg and scroll is not None:
                    lines = msg.get("lines")
                    scrolled = True
                    # returns once the tmux command is done, so the leave after it never overtakes it;
                    # a page when `lines` is absent
                    await scroll(
                        str(msg["scroll"]), lines if isinstance(lines, int) and not isinstance(lines, bool) else None
                    )
                elif "jump" in msg and jump is not None and (openings := jump_openings(msg["jump"])) is not None:
                    scrolled = True
                    try:
                        await jump(openings)
                    except Exception as e:  # noqa: BLE001 — a failed jump is a miss, never the attach's end
                        log.warning("a jump failed: %s", type(e).__name__)
                continue
            data = msg.encode() if isinstance(msg, str) else msg
            if read_only:
                continue
            if scrolled and leave is not None and counts_as_typing(data):
                scrolled = False
                try:
                    await asyncio.wait_for(leave(), LEAVE_WITHIN)
                except Exception as e:  # noqa: BLE001 — a slow or failed leave: the key is written anyway
                    log.warning("leaving copy mode before a typed key failed: %s", type(e).__name__)
            pty.write(data)

    d = asyncio.create_task(down())
    u = asyncio.create_task(up())
    try:
        await asyncio.wait({d, u}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (d, u):
            t.cancel()
        pty.close()
