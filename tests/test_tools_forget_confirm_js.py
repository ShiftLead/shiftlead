"""TD-2328, design §4.5a *Tools page: a login* **Forget this login** and §4.9e *A record's `profile`* (TD-2288): the
Tools page's Forget press (`AO.tools` in `src/shiftlead/ui/static/app.js`), run as itself under node against a stub
row, adds to its confirm the ended sessions that read nothing once the login is forgotten, from the row's
`data-ended`: none where it is 0 or missing, one in its own words, and several by their count."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js"

PROBE = r"""
const fs = require("fs");
const noop = () => {};
const tick = () => new Promise((r) => setImmediate(r));
const asked = [];
const posted = [];
const row = { dataset: { login: "claude-code:grind", version: "v1" } };
const button = {
  dataset: { toolAct: "forget" }, disabled: false, addEventListener: (k, f) => { button.on = f; },
  closest: (sel) => (sel === "[data-login], [data-account]" ? row : null),
};
const page = {
  querySelector: () => null,
  querySelectorAll: (sel) => (sel === ".toollogin [data-tool-act], .toolacct [data-tool-act]" ? [button] : []),
};
const document = {
  documentElement: { dataset: {}, classList: { toggle: noop, add: noop, remove: noop } }, body: {},
  addEventListener: noop, createElement: () => ({}), querySelectorAll: () => [],
  querySelector: (sel) => (sel === "#toolspage" ? page : null),
};
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/tools", protocol: "http:", host: "x", search: "", reload: noop };
global.Event = class { constructor(t) { this.type = t; } };
global.CSS = { escape: (s) => s };
global.confirm = (text) => { asked.push(text); return false; };  // the person says no: nothing is sent
global.fetch = async (url) => { posted.push(String(url)); return { ok: true, json: async () => ({}) }; };
eval(fs.readFileSync(process.argv[2], "utf8"));
async function run() {
  window.AO.tools();
  const out = {};
  for (const n of [undefined, "0", "1", "3"]) {
    if (n === undefined) delete row.dataset.ended; else row.dataset.ended = n;
    asked.length = 0;
    button.on(); await tick();
    out[String(n)] = asked.slice();
  }
  out.posted = posted;
  console.log(JSON.stringify(out));
}
run().catch((e) => { console.error(e); process.exit(1); });
"""

ASK = "Forget claude-code:grind? Its folder stays on disk, and adding that folder again takes back its name."


def _run(tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the confirm is JavaScript, and nothing else runs it")
    script = tmp_path / "forget_confirm_probe.js"
    script.write_text(PROBE)
    out = subprocess.run([node, str(script), str(APP)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_forgets_confirm_names_the_ended_sessions_at_none_one_and_several(tmp_path):
    got = _run(tmp_path)
    assert got["undefined"] == [ASK], "no count on the row: the confirm names no ended session"
    assert got["0"] == [ASK], "none ended: the confirm names no ended session"
    assert got["1"] == [f"{ASK} 1 ended session ran on this login: it reads nothing until its folder is added again."]
    assert got["3"] == [
        f"{ASK} 3 ended sessions ran on this login: they read nothing until its folder is added again."
    ]
    assert got["posted"] == [], "a confirm the person declines sends nothing"
