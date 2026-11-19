"""The press's folder and the askers' key follow the record's `cwd` (design §4.6 *The press is two launches* and *A
path in the pane is a link*, §4.2 *The record's `cwd`*; TD-1959, built by TD-1988): a resolved path under
`cwd_root`, where that is the deeper of it and `dir`'s top level that holds the path, launches `editor.cwd_url` first
in place of the Session card's folder, in the pane and in a transcript; the pane's cache and the Inbox and Queue
`id:` askers key on the record's `cwd`, so a move asks each run again; an `id:` row carries the record's `cwd` as
`data-paths-cwd`. The page's functions run as themselves under node."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir
from test_ui_inbox import entry
from test_ui_item_paths import _home
from test_ui_transcript_paths import _paths_attr, page  # noqa: F401

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const out = {};
const top = "/r/main", wt = "/r/main/.claude/worktrees/w2";
out.under = [
  AO.underCwdRoot("/w/other/a.py", "/w/other", top),  // another repository: under cwd_root alone
  AO.underCwdRoot(wt + "/a.py", wt, top),  // a worktree nested in dir's top level: the inner wins
  AO.underCwdRoot(top + "/a.py", wt, top),  // under dir's top level alone
  AO.underCwdRoot("/x/dir/a.py", "/x", "/x/dir"),  // cwd_root an ancestor of dir (in no repository): dir is deeper
  AO.underCwdRoot("/w/otherwise/a.py", "/w/other", top),  // a prefix that is no parent
  AO.underCwdRoot("/w/other/a.py", "", top),  // no cwd_root
];
const ED = { label: "VS Code", file: "vscode://file{path}", url: "vscode://file/r/main?windowId=_blank", wait: 1 };
const fed = { ...ED };
out.changed = [AO.focusCwd(fed, { cwd: wt, cwd_root: wt, git: { top }, dir: top + "/sub",
  editor: { cwd_url: "vscode://file" + wt + "?windowId=_blank" } }), AO.focusCwd(fed, { cwd: wt, cwd_root: wt,
  git: { top }, editor: { cwd_url: "vscode://file" + wt + "?windowId=_blank" } })];
out.fed = { cwd: fed.cwd, cwd_root: fed.cwd_root, top: fed.top, cwd_url: fed.cwd_url, url: fed.url };
out.noGit = AO.focusCwd({}, { cwd: "/x", dir: "/x/dir" }) && true;
const opened = [];
const open = (url, label) => opened.push(url);
AO.pathLink({ ctrlKey: true }, fed, wt + "/src/a.py", 3, 0, open);
AO.pathLink({ ctrlKey: true }, fed, top + "/src/b.py", 3, 0, open);
AO.pathLink({ ctrlKey: true }, { ...fed, first: false }, wt + "/src/a.py", 3, 0, open);
out.opened = opened;
out.press = AO.pressEditor(ED, wt + "/a.py") === ED;  // no cwd_url: the editor as it is
const both = { "src/a.py": wt + "/src/a.py", "docs/b.py": top + "/docs/b.py" };
out.html = AO.pathLinksHtml("src/a.py and docs/b.py", both, fed);
const ia = (cwd) => AO.itemAsker("id:ao-w", cwd);
out.askers = [ia("/a") === ia("/a"), ia("/a") !== ia("/b"), ia("/a") !== ia()];
// the pane's provider: a row asked once, and again once the editor's `cwd` moved
const asks = [];
const row = { translateToString: () => "see src/a.py", isWrapped: false, length: 12 };
const term = { buffer: { active: { getLine: (y) => (y === 0 ? row : undefined) } } };
const ped = { ...fed };
const answer = { paths: { "src/a.py": wt + "/src/a.py" } };
const prov = AO.pathProvider(term, "ao-w", ped, (runs) => { asks.push(runs); return Promise.resolve(answer); });
const hover = () => new Promise((res) => prov.provideLinks(1, res));
(async () => {
  await hover(); await hover();
  out.asksBefore = asks.length;
  AO.focusCwd(ped, { cwd: "/w/other", cwd_root: "/w/other", git: { top } });
  await hover();
  out.asksAfter = asks.length;
  console.log(JSON.stringify(out));
})();
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the page's paths are JavaScript, and nothing else runs it")
    probe = scratch_dir() / "cwd_press_probe.js"
    probe.write_text(PROBE)
    got = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


@pytest.mark.unit
def test_a_path_under_cwd_root_by_the_deeper_root_rule_presses_its_folder_first():
    got = _probe()
    assert got["under"] == [True, True, False, False, False, False]
    wt = "/r/main/.claude/worktrees/w2"
    assert got["opened"] == [
        f"vscode://file{wt}?windowId=_blank",  # the moved worktree's window first
        "vscode://file/r/main?windowId=_blank",  # a file of dir's top level: the Session card's folder
        f"vscode://file{wt}/src/a.py:3",  # folder_first off: the file alone
    ]
    assert got["press"] is True
    assert f'data-folder="vscode://file{wt}?windowId=_blank"' in got["html"].split("</a>")[0]
    assert 'data-folder="vscode://file/r/main?windowId=_blank"' in got["html"].split("</a>")[1]


@pytest.mark.unit
def test_the_editor_object_follows_cwd_and_the_askers_key_on_it():
    got = _probe()
    wt = "/r/main/.claude/worktrees/w2"
    assert got["changed"] == [True, False]  # a new cwd, then the same
    assert got["fed"] == {
        "cwd": wt,
        "cwd_root": wt,
        "top": "/r/main",  # git.top before dir
        "cwd_url": f"vscode://file{wt}?windowId=_blank",
        "url": "vscode://file/r/main?windowId=_blank",  # the Session card's folder kept
    }
    assert got["noGit"] is True
    assert got["askers"] == [True, True, True]  # one asker per context and cwd pair
    assert got["asksBefore"] == 1 and got["asksAfter"] == 2  # a moved cwd asks the row again


@pytest.mark.unit
def test_the_transcript_page_is_served_cwd_root_and_the_top_level(page, monkeypatch):  # noqa: F811
    c, _, replies, _ = page
    replies["get"] = {**replies["get"], "cwd": "/r/wt2", "cwd_root": "/r/wt2", "git": {"top": "/r/top", "files": []}}
    got = _paths_attr(c.get("/transcript/ao-x-designer").text)
    assert got["cwd_root"] == "/r/wt2" and got["top"] == "/r/top"


@pytest.mark.unit
def test_an_id_row_carries_its_records_cwd(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    from shiftlead.ui.app import templates

    rows = templates.get_template("inbox_rows.html")
    html = rows.render(rows=[entry("m-1", "ask", text="see src/x.py", from_cwd="/r/wt2")], section="needs")
    assert 'data-paths-ctx="id:ao-w1" data-paths-cwd="/r/wt2"' in html
    html = rows.render(rows=[entry("m-2", "ask", from_open="", from_cwd="/r/wt2")], section="needs")
    assert "data-paths-cwd" not in html  # a `home` row: no record, no cwd
    assert "data-paths-cwd" not in rows.render(rows=[entry("m-3", "ask")], section="needs")
