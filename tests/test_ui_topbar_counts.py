"""design §4.5a Sessions top bar *the bar's three groups* (TD-931, built by TD-932): the stream's `counts` draw
two numbers, the Queue tab's (`queue_n`) and the Inbox tab's (the rest of `needs`), each shown only above zero
and kept as last drawn while the count is unknown — `AO.drawCounts` run as itself under node."""

import json
import pathlib
import shutil
import subprocess
import tempfile

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = """
const fs = require("fs");
const noop = () => {};
const badge = () => { const cls = new Set(["hidden"]); return { textContent: "", dataset: {}, title: "",
  classList: { toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)), add: (c) => cls.add(c),
    remove: (c) => cls.delete(c), contains: (c) => cls.has(c) }, addEventListener: noop }; };
const bar = { "#personneeds": badge(), "#queueneeds": badge() };
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: (s) => bar[s] || null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/settings", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const read = () =>
  Object.fromEntries(Object.entries(bar).map(([k, b]) => [k, [b.textContent, b.classList.contains("hidden")]]));
const seen = [];
for (const got of [
  { needs: 5, queue_n: 2, fyi_n: 0 },
  { needs: null, queue_n: null, fyi_n: null, agent_down: true },
  { needs: 2, queue_n: 2, fyi_n: 0 },
  { needs: 0, queue_n: 0, fyi_n: 0 },
]) { AO.drawCounts(got); seen.push(read()); }
console.log(JSON.stringify(seen));
"""


@pytest.mark.unit
def test_the_stream_draws_a_number_on_each_tab_and_keeps_them_while_unknown():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the drawing is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "topbar_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    inbox, unknown, queue_only, none = json.loads(out.stdout)
    assert inbox == {"#personneeds": ["3", False], "#queueneeds": ["2", False]}  # 5 needs: 3 + 2
    assert unknown == inbox  # the host agent down: each keeps its last number
    assert queue_only == {"#personneeds": ["", True], "#queueneeds": ["2", False]}  # only above zero
    assert none == {"#personneeds": ["", True], "#queueneeds": ["", True]}
