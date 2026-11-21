"""The Focus Git card's summary and its *working in* line (design §4.5a *Focus side panel, Git card: working in*,
§4.2 *The record's `cwd`*; TD-1959, built by TD-1988): a linked worktree whose folder is not its branch's name reads
*worktree <folder> · on branch <branch>*, a detached head there *worktree <folder> · detached at <sha>*; the line
*working in <path>* is drawn where the record has `cwd_root`, a link to `editor.cwd_url`, text where the view
serves none. The page's painter runs as itself under node."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir
from test_ui_events_paths import client
from test_ui_waiting_wiring import NOW, member

from shiftlead.ui.cards import git_head

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"


@pytest.mark.unit
def test_the_summary_names_the_worktree_where_it_is_not_the_branch():
    assert git_head({"branch": "td-1953-tools", "worktree": "td-1153"}) == "worktree td-1153 · on branch td-1953-tools"
    assert git_head({"branch": "td-1153", "worktree": "td-1153"}) == "td-1153"  # the folder is the branch
    assert git_head({"branch": "main"}) == "main"  # a main checkout
    assert (
        git_head({"branch": "(detached)", "worktree": "w", "oid": "0123456789ab"}) == "worktree w · detached at 0123456"
    )
    assert git_head({"branch": "(detached)", "oid": "0123456789ab"}) == "(detached)"  # a main checkout's, as before


def _focus(monkeypatch, tmp_path, rec):
    from shiftlead.ui import app as ui

    c = client(monkeypatch, tmp_path, lambda g1, g2: [], wait=0)
    real = ui.LocalClient.call

    async def call(self, method, **kw):
        return {"seen": rec, "get": rec, "list": [rec]}.get(method) or await real(self, method, **kw)

    monkeypatch.setattr(ui.LocalClient, "call", call)
    return c.get(f"/focus/{rec['id']}").text


def _card(html: str) -> str:
    return html[html.index('id="gitcard"') : html.index("</details>", html.index('id="gitcard"'))]


@pytest.mark.unit
def test_the_card_draws_the_long_summary_and_the_working_in_link(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    root = str(tmp_path / "repo")
    git = {"branch": "td-1953-tools", "worktree": "td-1153", "top": root, "files": [], "unpushed": 2}
    rec = {**member("g1", root), "created": NOW, "git": git, "cwd": "/w/other", "cwd_root": "/w/other"}
    card = _card(_focus(monkeypatch, tmp_path, rec))
    assert "worktree td-1153 · on branch td-1953-tools · 2 unpushed" in card
    assert 'id="gitcwd"' in card and "gitcwd hidden" not in card
    assert 'id="gitcwdlink" href="vscode://file/w/other?windowId=_blank"' in card and 'title="/w/other"' in card


@pytest.mark.unit
def test_the_working_in_line_is_text_without_a_link_and_hidden_without_cwd_root(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    from shiftlead.ui import uiconf

    monkeypatch.setattr(uiconf, "open_in", lambda: uiconf.OpenIn(kind="none"))
    root = str(tmp_path / "repo")
    rec = {
        **member("g1", root),
        "created": NOW,
        "git": {"branch": "main", "files": []},
        "cwd": "/w/o",
        "cwd_root": "/w/o",
    }
    card = _card(_focus(monkeypatch, tmp_path, rec))
    assert "gitcwd hidden" not in card and "gitcwdlink" not in card and "<bdi>/w/o</bdi>" in card
    card = _card(_focus(monkeypatch, tmp_path, {**rec, "cwd": None, "cwd_root": None}))
    assert "gitcwd hidden" in card


PROBE = """
const fs = require("fs");
const noop = () => {};
const mk = (tag) => { const e = { tag, children: [], dataset: {}, title: "", className: "", id: "", href: "",
  _text: "", classList: { set: new Set(), toggle(c, on) { on ? this.set.add(c) : this.set.delete(c); },
    contains(c) { return this.set.has(c); }, add: noop, remove: noop },
  appendChild(c) { this.children.push(c); return c; },
  set textContent(t) { this._text = t; this.children = []; },
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); },
  querySelector(sel) { return sel === ".gitcwdpath" ? this._path : null; } }; return e; };
const document = { documentElement: mk("html"), body: mk("body"), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: mk };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const el = mk("div"); el._path = mk("span");
const out = [];
const read = () => ({ hidden: el.classList.set.has("hidden"), title: el._path.title, text: el._path.textContent,
  link: el._path.children[0] && el._path.children[0].tag === "a" ? el._path.children[0].href : null });
AO.paintWorkingIn(el, { cwd_root: "/w/a", editor: { label: "VS Code", cwd_url: "vscode://file/w/a" } });
out.push(read());
AO.paintWorkingIn(el, { cwd_root: "/w/b", editor: null }); out.push(read());
AO.paintWorkingIn(el, { cwd_root: null, editor: null }); out.push(read());
console.log(JSON.stringify(out));
"""


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_painter_redraws_the_line_from_each_view():
    probe = scratch_dir() / "git_cwd_probe.js"
    probe.write_text(PROBE)
    got = json.loads(
        subprocess.run(
            ["node", str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, check=True
        ).stdout
    )
    assert got == [
        {"hidden": False, "title": "/w/a", "text": "/w/a", "link": "vscode://file/w/a"},
        {"hidden": False, "title": "/w/b", "text": "/w/b", "link": None},  # no `cwd_url`: text
        {"hidden": True, "title": "", "text": "", "link": None},
    ]
