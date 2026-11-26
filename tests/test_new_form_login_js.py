"""TD-2293, design §4.5a New session **the form** and §4.9e *A session the person starts*: the browser half of the
**Login** pick (`AO.newSession` in `src/shiftlead/ui/static/app.js`: `applyLogin`, `applyShell`, `lockLine`,
`loadLine`), run as itself under node against a stub of the form. On another host the home reads no node's logins
(§4.9e *Not here*), so the pick's logins give way to *a login typed below*, shown and required; back on this host
they come back; a shell takes no Model; and under a member line the pick, the typed field and Model are locked, the
line's fill keeping the pick's value."""

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
const opts = (html) => [...html.matchAll(/<option value="([^"]*)"[^>]*>/g)].map((m) => opt(m[1]));
function el(props) {
  const on = {};
  const e = Object.assign({
    on, value: "", checked: false, hidden: false, disabled: false, readOnly: false, required: false,
    dataset: {}, style: {}, textContent: "", title: "", placeholder: "",
    classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
    addEventListener: (k, f) => { (on[k] = on[k] || []).push(f); },
    dispatchEvent: (ev) => { for (const f of on[ev.type] || []) f(ev); },
    querySelector: () => null, querySelectorAll: () => [], closest: () => null,
    focus: noop, remove: noop, appendChild: noop, insertBefore: noop, insertAdjacentHTML: noop,
  }, props || {});
  if (!e.parentElement) e.parentElement = { hidden: false };
  if (e.innerHTML === undefined) e.innerHTML = "";
  return e;
}
function opt(value, dataset) { return { value, dataset: dataset || {}, hidden: false, disabled: false, remove: noop }; }
function select(options, index) {
  const s = el();
  let list = options, at = index === undefined ? 0 : index;
  Object.defineProperties(s, {
    options: { get: () => list },
    selectedIndex: { get: () => at, set: (i) => { at = i; } },
    selectedOptions: { get: () => (at >= 0 && list[at] ? [list[at]] : []) },
    value: { get: () => (at >= 0 && list[at] ? list[at].value : ""),
      set: (v) => { at = list.findIndex((o) => o.value === v); } },
    innerHTML: { get: () => "", set: (html) => { list = opts(html); at = list.length ? 0 : -1; } },
  });
  s.appendChild = (o) => { o.hidden = !!o.hidden; o.disabled = !!o.disabled; list.push(o); };
  return s;
}
const login = select([
  opt("claude-code:first", { here: "1", models: "opus,sonnet" }),
  opt("claude-code:second", { here: "1", models: "haiku" }),
  Object.assign(opt("", { typed: "1" }), { hidden: true }),
  opt("shell", { adapter: "shell" }),
], 0);
const typedField = { hidden: true };
const typedIn = el({ parentElement: typedField, disabled: true });
const model = el(), models = el();
const host = select([opt("home"), opt("node-a")], 0);
const role = select([opt("", { interactive: "1" }), opt("worker")], 0);
const team = select([opt(""), opt("t", { lines: JSON.stringify([{ role: "worker", line: "w" }]), dirs: '["/r"]', roles: "worker" })], 0);
const repo = select([opt("/r", { name: "r" }), opt("", { other: "1" })], 0);
const linePick = select([], -1);
const els = {
  "#login": login, "#logintyped": typedIn, "#model": model, "#loginmodels": models, "#host": host, "#role": role,
  "#team": team, "#repo": repo, "#linepick": linePick, "[name=unattended]": el(), "#memberfield": el(),
  "[name=line]": el(), "#keep": el(), "form[action='/new'] [name=dir]": el({ value: "/r" }),
};
const absent = new Set(["#profile", "form[data-prefilled]", "#rolemode", "#whenfields"]);
const made = {};
const document = {
  documentElement: el(), body: el(), addEventListener: noop, createElement: () => el(),
  querySelector: (sel) => (absent.has(sel) ? null : els[sel] || (made[sel] = made[sel] || el())),
  querySelectorAll: () => [],
};
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/new", protocol: "http:", host: "x", search: "" };
global.Event = class { constructor(t) { this.type = t; } };
global.CSS = { escape: (s) => s };
const worker = { name: "worker", lane: [], controllers: [], grants: [], prompts: [], source: "built-in" };
const answers = {
  "/api/team_line": { name: "w-1", profile: "not-a-pick", lane: [], prompt: "", grants: [] },
  "/api/roles": { roles: [worker], controllers: [] },
  "/api/repos": { repos: [{ path: "/r", name: "r" }], host: "home" },
};
global.fetch = async (url) => {
  const path = String(url).split("?")[0];
  return { ok: true, json: async () => answers[path] || { repos: [], roles: [], controllers: [], worktrees: [] } };
};
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const read = () => ({
  value: login.value, disabled: login.disabled,
  here: login.options.filter((o) => o.dataset.here).map((o) => [o.hidden, o.disabled]),
  typed_option_hidden: login.options[2].hidden,
  typed: { shown: !typedField.hidden, disabled: typedIn.disabled, required: typedIn.required },
  model_disabled: model.disabled, models: models.innerHTML,
});
async function run() {
  const out = {};
  AO.newSession();
  await tick(); await tick();
  out.here = read();
  host.selectedIndex = 1; host.dispatchEvent(new Event("change")); await tick(); await tick();
  out.away = read();
  host.selectedIndex = 0; host.dispatchEvent(new Event("change")); await tick(); await tick();
  out.back = read();
  login.value = "shell"; login.dispatchEvent(new Event("change")); await tick();
  out.shell = read();
  login.value = "claude-code:second"; login.dispatchEvent(new Event("change")); await tick();
  out.second = read();
  team.selectedIndex = 1; role.value = "worker"; role.dispatchEvent(new Event("change"));
  for (let i = 0; i < 6; i++) await tick();
  out.member = read();
  host.selectedIndex = 1; host.dispatchEvent(new Event("change")); for (let i = 0; i < 6; i++) await tick();
  out.member_away = read();
  console.log(JSON.stringify(out));
}
run().catch((e) => { console.error(e); process.exit(1); });
"""


def _run(tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the pick's wiring is JavaScript, and nothing else runs it")
    script = tmp_path / "login_pick_probe.js"
    script.write_text(PROBE)
    out = subprocess.run([node, str(script), str(APP)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_the_login_pick_follows_the_host_the_shell_and_a_member_line(tmp_path):
    got = _run(tmp_path)
    # this host: its logins offered, the first picked, the typed field hidden and not required
    assert got["here"]["here"] == [[False, False], [False, False]] and got["here"]["value"] == "claude-code:first"
    assert got["here"]["typed_option_hidden"] is True
    assert got["here"]["typed"] == {"shown": False, "disabled": True, "required": False}
    assert got["here"]["models"] == '<option value="opus"><option value="sonnet">'
    # another host: this host's logins hidden and disabled, *a login typed below* picked, shown and required
    assert got["away"]["here"] == [[True, True], [True, True]]
    assert got["away"]["value"] == "" and got["away"]["typed_option_hidden"] is False
    assert got["away"]["typed"] == {"shown": True, "disabled": False, "required": True}
    # this host again: its logins back, the first picked, the typed field hidden and not required
    assert got["back"]["here"] == [[False, False], [False, False]] and got["back"]["value"] == "claude-code:first"
    assert got["back"]["typed"] == {"shown": False, "disabled": True, "required": False}
    # a shell takes no Model; a login again offers its own models
    assert got["shell"]["model_disabled"] is True and got["shell"]["models"] == ""
    assert got["second"]["model_disabled"] is False and got["second"]["models"] == '<option value="haiku">'
    # under a member line: the pick, the typed field and Model locked, and the line's fill keeps the pick's value
    assert got["member"]["disabled"] is True and got["member"]["model_disabled"] is True
    assert got["member"]["typed"]["disabled"] is True
    assert got["member"]["value"] == "claude-code:second", "a member's login is its team's list's, never the line's"
    # …and on another host, *a login typed below* picked: the typed field shown but locked, so not required
    assert got["member_away"]["value"] == "" and got["member_away"]["disabled"] is True
    assert got["member_away"]["typed"] == {"shown": True, "disabled": True, "required": False}
