"""A hyperlink in the pane is a link (design §4.6 *A hyperlink in the pane is a link*, §4.5a **a
hyperlink is a link**, TD-845, built by TD-847): the pty bridge's attach asks tmux for the
`hyperlinks` feature, so an OSC 8 run in the pane reaches xterm.js with its target, and the Focus
terminal's `linkHandler` opens it under the URL rule, its target shown on hover."""

from __future__ import annotations

import json
import os
import pathlib
import re
import select
import shutil
import subprocess
import time

import pytest
from conftest import kill_private_server, private_socket_name, scratch_dir

from sessionorc import containers
from sessionorc.tmux import Tmux
from sessionorc.tmux import attach_argv as tmux_attach_argv
from shiftlead.ui import help as helpmod
from shiftlead.ui import pty_bridge

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
TARGET = "https://claude.ai/code/artifact/td847"


def _tmux_version() -> tuple[int, int]:
    out = subprocess.run(["tmux", "-V"], capture_output=True, text=True, timeout=10).stdout
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m[1]), int(m[2])) if m else (0, 0)


@pytest.mark.unit
def test_only_the_bridge_asks_for_hyperlinks():
    assert tmux_attach_argv("ao-x", socket_name="s", features=("hyperlinks",)) == [
        "tmux", "-L", "s", "-T", "hyperlinks", "attach", "-t", "=ao-x:"
    ]  # fmt: skip
    assert pty_bridge.attach_argv("ao-x", features=("hyperlinks",))[:3] == ["tmux", "-T", "hyperlinks"]
    # without features, no `-T`: `ao focus` and every other caller keep their argv
    assert "-T" not in tmux_attach_argv("ao-x") and "-T" not in pty_bridge.attach_argv("ao-x", socket_name="s")
    assert "-T" not in containers.attach_argv_in("c", "u", "ao-x")
    inside = containers.attach_argv_in("c", "u", "ao-x", features=("hyperlinks",))
    # the flag goes after the binary, so the websocket's `inside` still splits at "tmux"
    assert inside[: inside.index("tmux")] == ["docker", "exec", "-u", "u", "-it", "c"]
    assert inside[inside.index("tmux") :] == ["tmux", "-T", "hyperlinks", "attach", "-t", "=ao-x:"]


@pytest.mark.unit
def test_the_terminal_websocket_attaches_with_hyperlinks():
    src = (UI / "app.py").read_text()
    assert 'attach_argv(sid, socket_name=sock, features=("hyperlinks",))' in src
    assert 'sid, features=("hyperlinks",))' in src[src.index("attach_argv_in(reach") :][:200]


@pytest.mark.integration
def test_an_osc8_run_reaches_the_bridges_attach_with_its_target(tmp_path):
    if not shutil.which("tmux") or _tmux_version() < (3, 4):
        pytest.skip("tmux before 3.4 keeps no hyperlinks to send")
    sock = private_socket_name()
    tmux = Tmux(socket_name=sock)
    script = tmp_path / "link.sh"
    script.write_text(f"printf '\\033]8;;{TARGET}\\033\\\\Team Spend\\033]8;;\\033\\\\\\n'; exec sleep 60\n")
    env = {**os.environ, "TERM": "xterm-256color"}
    subprocess.run(
        ["tmux", "-L", sock, "-f", "/dev/null", "new-session", "-d", "-s", "ao-link", "-x", "80", "-y", "10",
         f"sh {script}"],
        check=True, timeout=10, env=env,
    )  # fmt: skip
    master, slave = os.openpty()
    proc = None
    try:
        time.sleep(0.5)  # the printf has run before the client attaches
        argv = pty_bridge.attach_argv("ao-link", socket_name=sock, features=("hyperlinks",))
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
        got, end = b"", time.monotonic() + 5
        while time.monotonic() < end and TARGET.encode() not in got:
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                got += os.read(master, 65536)
        assert b"\x1b]8;" in got and TARGET.encode() in got, got[-400:]
    finally:
        if proc:
            proc.kill()
            proc.wait(timeout=5)
        os.close(master)
        os.close(slave)
        kill_private_server(tmux)


PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
const opened = [];
global.window = { open: (...a) => { opened.push(a); } }; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const url = process.argv[3];
const range = { start: { x: 1, y: 1 }, end: { x: 10, y: 1 } };
const box = { title: "" };
const h = AO.paneLinkHandler(box);
const take = () => opened.splice(0);
const out = {};
h.activate({ ctrlKey: true }, url, range); out.ctrl = take();
h.activate({}, url, range); out.plain = take();
h.activate({ ctrlKey: true }, "javascript:alert(1)", range); out.js = take();
h.hover({}, url, range); out.hover = box.title;
h.leave({}, url, range); out.leave = box.title;
console.log(JSON.stringify(out));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the link's handler is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "hyperlink_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run(
        [node, str(probe), str(UI / "static" / "app.js"), TARGET], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_the_handler_opens_on_ctrl_click_only_and_shows_the_target_on_hover():
    got = _probe()
    # xterm passes the range third: the wrapper never hands it to `AO.paneLink` as its `open`
    assert got["ctrl"] == [[TARGET, "_blank", "noopener"]]
    assert got["plain"] == [] and got["js"] == []
    assert got["hover"] == TARGET and got["leave"] == ""


@pytest.mark.unit
def test_focus_passes_the_handler_and_the_vendored_provider_keeps_its_http_check():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    made = focus[focus.index("const term = new Terminal(") :]
    made = made[: made.index("\n")]
    assert 'linkHandler: AO.paneLinkHandler($("#term"))' in made
    assert "allowNonHttpProtocols" not in made and "allowNonHttpProtocols:" not in js
    # the drop of any other target is xterm's own: pin the vendored copy's check
    xterm = (UI / "static" / "vendor" / "xterm.js").read_text()
    assert 'if(!r?.allowNonHttpProtocols)try{const e=new URL(i);["http:","https:"].includes(e.protocol)' in xterm


@pytest.mark.unit
def test_the_help_carries_the_hyperlink_under_focus():
    h = {x.key: x for x in helpmod.HELP}["pane-hyperlink"]
    assert h.name == "a hyperlink is a link" and h.where == "Focus pane"
    assert "Ctrl+click (Cmd+click on a Mac)" in h.text
    assert "pane-hyperlink" in dict((g[0], g[2]) for g in helpmod.SCREENS)["focus"]
