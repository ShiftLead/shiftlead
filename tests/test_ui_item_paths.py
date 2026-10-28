"""A path in the Inbox and the Queue is a link too (design §4.6 *A path in the Inbox and the Queue is a
link too*, §4.5a **a path is a link**; TD-1108, built by TD-1115): `paths` takes `repo` beside `id`, and
neither; `POST /api/paths` answers `{label, file, wait, paths, refused}` by the row's context; the server
writes that context as `data-paths-ctx` on every mail, board, ledger and thread row; and the page links
each answered run in a row's texts, keeping their markup. The page's functions run as themselves under
node."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import scratch_dir
from fastapi.testclient import TestClient
from test_ui_inbox import entry

from sessionorc.agent import _registered_checkout, _resolve_paths
from sessionorc.agent_common import PATHS_RUN_CHARS, PATHS_RUNS_MAX
from sessionorc.client import AgentError, LocalClient
from shiftlead.ui import uiconf

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
REACH = "vscode://vscode-remote/attached-container+7b22636f6e7461696e65724e616d65223a222f6e31227d/workspaces/r?windowId=_blank"


def _person(text: str) -> None:
    uiconf.set_read({"person": yaml.safe_load(text) or {}, "migrate": []})


@pytest.fixture
def person():
    yield _person
    uiconf.set_read({"person": {}, "migrate": []})


def _home(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """A home on this host with one registered checkout, `repo`, holding `src/x.py` and `src/sub/`."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    repo = tmp_path / "repo"
    (repo / "src" / "sub").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "x.py").write_text("x\n")
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  name: kmaster\n  local: true\n  repos_registry: {home / 'repos.txt'}\n")
    return home, repo


# -- (a) the RPC ------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_paths_takes_repo_and_neither_beside_id(agent, tmp_path, monkeypatch):
    home = Path(os.environ["SHIFTLEAD_HOME"])
    repo = tmp_path / "repo"
    (repo / "src" / "sub").mkdir(parents=True)
    (repo / "src" / "x.py").write_text("x\n")
    (home / "repos.txt").write_text(f"{repo}\n")
    user = tmp_path / "user"
    (user / ".ssh").mkdir(parents=True)
    (user / ".ssh" / "config").write_text("x\n")
    (user / "h.txt").write_text("h\n")
    monkeypatch.setenv("HOME", str(user))
    async with LocalClient() as person:
        # the repo form: a relative run against the registered checkout, given by its path
        got = await person.call("paths", repo=str(repo), runs=["src/x.py", "src/sub", "./src/x.py", "~/h.txt"])
        assert got["paths"] == {
            "src/x.py": str(repo / "src" / "x.py"),
            "src/sub": None,  # a directory answers nothing
            "./src/x.py": str(repo / "src" / "x.py"),
            "~/h.txt": str(user / "h.txt"),  # `~` is the home's user's
        }
        for bad in (str(tmp_path / "elsewhere"), str(repo / "src"), ""):  # unregistered, a subdirectory, empty
            with pytest.raises(AgentError, match="no checkout in this host's repos registry"):
                await person.call("paths", repo=bad, runs=["src/x.py"])
        with pytest.raises(AgentError, match="id or repo, not both"):
            await person.call("paths", id="ao-nope", repo=str(repo), runs=["src/x.py"])
        # neither: an absolute and a `~/` file answer; a relative run answers `null` and is never resolved
        runs = [str(repo / "src" / "x.py"), "~/h.txt", "./x", "../x", "src/x.py", "~/.ssh/config", "/proc/self/environ"]
        assert (await person.call("paths", runs=runs))["paths"] == {
            str(repo / "src" / "x.py"): str(repo / "src" / "x.py"),
            "~/h.txt": str(user / "h.txt"),
            "./x": None,
            "../x": None,
            "src/x.py": None,
            "~/.ssh/config": None,  # `PATHS_PRIVATE` in every form
            "/proc/self/environ": None,
        }
        assert (await person.call("paths", repo=str(repo), runs=["~/.ssh/config"]))["paths"] == {"~/.ssh/config": None}
        # the bounds come first, in every form
        with pytest.raises(AgentError, match=f"past the {PATHS_RUNS_MAX} one row may ask about"):
            await person.call("paths", runs=["/a/b"] * (PATHS_RUNS_MAX + 1))
        with pytest.raises(AgentError, match=f"past the {PATHS_RUN_CHARS} one may be"):
            await person.call("paths", repo=str(repo), runs=["a/" * PATHS_RUN_CHARS])
        with pytest.raises(AgentError, match="runs, a list of strings"):
            await person.call("paths", runs="src/x.py")


# -- (b) the route ----------------------------------------------------------------------------------


class _Fake:
    """The host agent as the route reaches it: `get` from `records`, and `paths` answered as the RPC
    does on this disk — or raising, for a host the record names as `unreachable`."""

    records: dict[str, dict] = {}
    asked: list[tuple[str, dict]] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def call(self, method, **kw):
        type(self).asked.append((method, kw))
        if method == "get":
            if kw["id"] not in self.records:
                raise AgentError(f"no session {kw['id']}")
            return self.records[kw["id"]]
        if method == "settings":  # the person's settings as this test set them, read by the app per request
            return {"person": uiconf._read["person"], "migrate": []}
        if method == "paths":
            runs = kw["runs"]
            if "id" in kw:
                rec = self.records[kw["id"]]
                if rec.get("state") == "unreachable":
                    raise AgentError(f"{rec['host']} is unreachable")
                return {"paths": _resolve_paths(runs, Path(rec["dir"]))}
            if "repo" in kw:
                return {"paths": _resolve_paths(runs, _registered_checkout(kw["repo"]))}
            bare = [r for r in runs if r.startswith(("/", "~/"))]
            got = _resolve_paths(bare, Path.home())
            return {"paths": {r: got.get(r) for r in runs}}
        return {}


@pytest.fixture
def route(tmp_path, monkeypatch, person):
    home, repo = _home(tmp_path, monkeypatch)
    from shiftlead.ui import app as ui

    _Fake.asked = []
    link = {"reach": {"vscode": REACH}}
    _Fake.records = {
        "ao-w": {"id": "ao-w", "host": "kmaster", "dir": str(repo), "state": "idle"},
        "ao-bare": {"id": "ao-bare", "host": "kmaster", "dir": "", "state": "idle"},
        "ao-c@cm": {"id": "ao-c@cm", "host": "cm", "dir": str(repo), "state": "idle", "host_link": link},
        "ao-n@lap": {"id": "ao-n@lap", "host": "lap", "dir": str(repo), "state": "idle"},
        "ao-u@cm": {"id": "ao-u@cm", "host": "cm", "dir": str(repo), "state": "unreachable", "host_link": link},
    }  # fmt: skip
    monkeypatch.setattr(ui, "LocalClient", _Fake)
    person("")
    return TestClient(ui.create_app()), home, repo


def _post(c, ctx, runs):
    return c.post("/api/paths", json={"runs": runs, "ctx": ctx})


@pytest.mark.unit
def test_the_route_answers_each_context_with_its_form_and_its_folder(route, monkeypatch):
    c, home, repo = route
    att = home / "attachments" / "draft-1a2b3c4d" / "x.png"
    att.parent.mkdir(parents=True)
    att.write_bytes(b"png")
    monkeypatch.setenv("HOME", str(home.parent))
    folder = f"vscode://file{repo}?windowId=_blank"
    # home: an attachment by its absolute path, the home's file form, no checkout to open first
    r = _post(c, "home", [str(att), "src/x.py"])
    assert r.status_code == 200
    assert r.json() == {
        "label": "VS Code",
        "file": "vscode://file{path}",
        "wait": 1,
        "paths": {str(att): {"path": str(att), "folder": None}, "src/x.py": None},
    }
    # repo: a relative run against the checkout, its folder first
    got = _post(c, f"repo:{repo}", ["src/x.py", "src/nope.py"]).json()
    assert got["file"] == "vscode://file{path}" and got["label"] == "VS Code" and got["wait"] == 1
    assert got["paths"] == {"src/x.py": {"path": str(repo / "src" / "x.py"), "folder": folder}, "src/nope.py": None}
    assert "refused" not in got
    # id: by that record's `dir`, its folder the record's own; a container node's by its reach form
    got = _post(c, "id:ao-w", ["src/x.py"]).json()
    assert got["paths"] == {"src/x.py": {"path": str(repo / "src" / "x.py"), "folder": folder}}
    got = _post(c, "id:ao-c@cm", ["src/x.py"]).json()
    assert got["file"] == REACH.removesuffix("/workspaces/r?windowId=_blank") + "{path}"
    assert got["paths"] == {"src/x.py": {"path": str(repo / "src" / "x.py"), "folder": REACH}}
    # `folder_first: false`: no folder anywhere
    _person("file_link: {folder_first: false}")
    assert _post(c, f"repo:{repo}", ["src/x.py"]).json()["paths"]["src/x.py"]["folder"] is None
    assert _post(c, "id:ao-w", ["src/x.py"]).json()["paths"]["src/x.py"]["folder"] is None


@pytest.mark.unit
def test_a_refusal_is_a_200_and_anything_else_that_fails_is_not(route):
    c, home, repo = route
    for ctx in (f"repo:{home.parent / 'elsewhere'}", f"repo:{repo / 'src'}", "id:ao-gone"):
        r = _post(c, ctx, ["src/x.py", "/etc/hosts"])
        assert r.status_code == 200, ctx
        got = r.json()
        assert got["refused"] and got["paths"] == {"src/x.py": None, "/etc/hosts": None} and got["file"] is None
    assert not any(m == "paths" for m, _ in _Fake.asked), "a refused context's host is never asked"
    # no file form: a node record with no reach, and a home record with an empty `dir` — its host never asked
    for ctx in ("id:ao-n@lap", "id:ao-bare"):
        got = _post(c, ctx, ["src/x.py"]).json()
        assert got["file"] is None and got["paths"] == {"src/x.py": None} and "refused" not in got
    assert not any(m == "paths" for m, _ in _Fake.asked)
    # an unreachable record's host is a non-200: the page caches nothing
    assert _post(c, "id:ao-u@cm", ["src/x.py"]).status_code != 200


@pytest.mark.unit
def test_the_grammar_and_the_bounds_are_400s_before_any_read(route):
    c, _, repo = route
    bad = [
        ("nope:x", ["a/b"]),
        ("repo:", ["a/b"]),
        ("id:", ["a/b"]),
        ("home:x", ["a/b"]),
        (None, ["a/b"]),
        ("home", ["a/b", 3]),
        ("home", "a/b"),
        ("home", ["/a/b"] * (PATHS_RUNS_MAX + 1)),
        ("home", ["/" + "a" * PATHS_RUN_CHARS]),
    ]
    for ctx, runs in bad:
        assert _post(c, ctx, runs).status_code == 400, (ctx, runs)
    assert not [m for m, _ in _Fake.asked if m in ("get", "paths")], "nothing is read before the grammar holds"
    assert _post(c, f"repo:{repo}", ["a/b"] * PATHS_RUNS_MAX).status_code == 200


@pytest.mark.unit
def test_no_file_form_on_the_home_answers_every_run_null(route):
    c, _, repo = route
    _person("open_in: none")
    for ctx in ("home", f"repo:{repo}", "id:ao-w"):
        got = _post(c, ctx, ["src/x.py"]).json()
        assert got["file"] is None and got["paths"] == {"src/x.py": None}
    assert not any(m == "paths" for m, _ in _Fake.asked)


# -- (c) the rows -----------------------------------------------------------------------------------


def _ctx(html: str, mid: str) -> str | None:
    """The `data-paths-ctx` on the row root whose `data-msg` is `mid`, or None."""
    at = html.index(f'data-msg="{mid}"')
    tag = html[html.rindex("<div ", 0, at) : html.index(">", at)]
    marker = 'data-paths-ctx="'
    return (
        tag[tag.index(marker) + len(marker) : tag.index('"', tag.index(marker) + len(marker))]
        if marker in tag
        else None
    )


def _board(root: str) -> dict:
    return {
        "row": "board", "id": f"board:{root}:7", "key": "", "line": 7, "repo": "r", "repo_name": "r", "root": root,
        "team": "", "teams": [], "text": "see docs/x.md", "due": "2026-10-27", "due_now": True, "today": "2026-10-27",
    }  # fmt: skip


@pytest.mark.unit
def test_every_mail_board_ledger_and_thread_row_carries_its_context(tmp_path, monkeypatch, person):
    _home(tmp_path, monkeypatch)
    person("")
    from shiftlead.ui.app import templates

    rows = templates.get_template("inbox_rows.html")

    def one(e, section="needs"):
        return rows.render(rows=[e], section=section)

    assert _ctx(one(entry("m-1", "ask", text="see src/x.py")), "m-1") == "id:ao-w1"
    assert _ctx(one(entry("m-2", "note"), section="fyi"), "m-2") == "id:ao-w1"  # an FYI from a known sender
    assert _ctx(one(entry("m-3", "ask", from_open=""), section="needs"), "m-3") == "home"  # a forgotten sender
    assert _ctx(one(entry("m-4", "note", handed_row=True), section="needs"), "m-4") == "home"  # a handed row
    assert _ctx(one(_board("/c/r")), "board:/c/r:7") == "repo:/c/r"
    assert _ctx(one(_board("")), "board::7") == "home"  # a board row with no root
    from test_ui_inbox_ledger import _repos

    from shiftlead.ui.app import ledger_for_you

    lrow = ledger_for_you(_repos(tmp_path), [], {})["groups"][0]["rows"][0]
    card = templates.get_template("queue_mail.html").render(e={**lrow, "want": "decide"}, section="later")
    assert _ctx(card, lrow["row_id"]) == f"repo:{lrow['root']}"  # a Queue card's ledger item
    # a trail row carries none
    trail = {
        "row": "trail",
        "id": "t-1",
        "sid": "ao-w1",
        "name": "w1",
        "team": "",
        "text": "x",
        "at": "",
        "kind": "trail",
    }
    assert _ctx(one(trail, section="fyi"), "t-1") is None
    # the message page's thread rows, each by its own sender
    page = templates.env.from_string(
        '{% from "inbox_entry.html" import thread_row with context %}{{ thread_row(a) }}{{ thread_row(b) }}'
    ).render(
        a={"id": "t-a", "from": "ao-w1", "from_open": "ao-w1", "kind": "reply", "text": "x"},
        b={"id": "t-b", "from": "ao-gone", "from_open": "", "kind": "reply", "text": "x"},
        origin="",
        entry=None,
        gone="the module renders its page body too: no entry",
    )
    assert _ctx(page, "t-a") == "id:ao-w1" and _ctx(page, "t-b") == "home"
    # `open_in: none`: no row carries one
    person("open_in: none")
    card = templates.get_template("queue_mail.html").render(e={**lrow, "want": "decide"}, section="later")
    assert "data-paths-ctx" not in one(entry("m-1", "ask")) + one(_board("/c/r")) + card


# -- (d) the page -----------------------------------------------------------------------------------


PROBE = r"""
const fs = require("fs");
const noop = () => {};
// a DOM small enough to read: elements and text nodes, `closest` and `querySelectorAll` by tag or class
class Node_ {
  constructor(type, name, value) { this.nodeType = type; this.nodeName = name; this.nodeValue = value;
    this.childNodes = []; this.parentNode = null; this.attrs = {}; this.dataset = {}; this.className = ""; }
  get ownerDocument() { return document; }
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(ref), 0, c); return c; }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  set textContent(t) { this.childNodes = []; this.appendChild(new Node_(3, "#text", t)); }
  get textContent() {
    return this.nodeType === 3 ? this.nodeValue : this.childNodes.map((c) => c.textContent).join(""); }
  matches(sel) { return sel.split(",").some((s) => { s = s.trim();
    const attr = s.match(/\[data-paths-ctx\]$/);
    if (attr) { s = s.slice(0, attr.index); if (!this.dataset.pathsCtx) return false; }
    if (s.startsWith(".")) return s.slice(1).split(".").every((k) => this.className.split(" ").includes(k));
    return this.nodeName === s.toUpperCase(); }); }
  closest(sel) {
    let n = this; while (n && n.nodeType === 1) { if (n.matches(sel)) return n; n = n.parentNode; } return null; }
  querySelectorAll(sel) { const out = []; const walk = (n) => n.childNodes.forEach((c) => {
    if (c.nodeType === 1) { if (c.matches(sel)) out.push(c); walk(c); } }); walk(this); return out; }
  get html() { if (this.nodeType === 3) return this.nodeValue;
    const a = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${v}"`).join("");
    const cls = this.className ? ` class="${this.className}"` : "";
    const tag = this.nodeName.toLowerCase();
    return `<${tag}${cls}${a}>${this.childNodes.map((c) => c.html).join("")}</${tag}>`; }
}
const elem = (tag, cls, ...kids) => { const e = new Node_(1, tag.toUpperCase()); e.className = cls || "";
  kids.forEach((k) => e.appendChild(typeof k === "string" ? new Node_(3, "#text", k) : k)); return e; };
const document = { documentElement: elem("html"), body: elem("body"),
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: (t) => elem(t), createTextNode: (t) => new Node_(3, "#text", t) };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
const asks = [];
let answers = {}, failNext = false;
global.fetch = async (url, opts) => {
  const body = JSON.parse(opts.body);
  asks.push([body.ctx, body.runs]);
  if (failNext) { failNext = false; return { ok: false, status: 503 }; }
  const a = answers[body.ctx] || {};
  return { ok: true, json: async () => ({ label: "VS Code", wait: 1, ...a.meta,
    paths: Object.fromEntries(body.runs.map((r) => [r, (a.paths || {})[r] || null])) }) };
};
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const FILE = "vscode://file{path}";
const row = (ctx, ...kids) => { const r = elem("div", "mailrow", ...kids); r.dataset.pathsCtx = ctx; return r; };
(async () => {
  answers["repo:/r"] = { meta: { file: FILE }, paths: {
    "src/x.py": { path: "/r/src/x.py", folder: "vscode://file/r?windowId=_blank" },
    "~/.shiftlead/attachments/d/x.png": { path: "/h/.shiftlead/attachments/d/x.png", folder: null } } };
  answers["id:ao-w"] = { meta: { file: FILE }, paths: { "src/x.py": { path: "/w/src/x.py", folder: null } } };
  answers["repo:/gone"] = { meta: { file: null, refused: "not registered" } };
  answers["id:ao-n"] = { meta: { file: null } };
  // markup kept: `<code>src/x.py</code>` and a plain attachment path, both linked; a run under `summary` stays text
  const body = elem("div", "body md", "see ", elem("code", "", "src/x.py"), " and ~/.shiftlead/attachments/d/x.png.");
  const sum = elem("summary", "", elem("div", "body", "src/x.py too"));
  const r1 = row("repo:/r", body, elem("details", "", sum));
  await AO.askItem(r1);
  const kept = body.html, under = sum.html;
  const asked1 = asks.length;
  // two lines of one file: one ask, two hrefs (the cache answers this one: no ask at all)
  const lines = elem("div", "body", "src/x.py:12 then src/x.py:30");
  await AO.askItem(row("repo:/r", lines));
  const hrefs = lines.querySelectorAll("a").map((a) => a.attrs.href);
  const asked2 = asks.length;
  // one run under two contexts is asked twice
  const other = elem("div", "body", "src/x.py");
  await AO.askItem(row("id:ao-w", other));
  const asked3 = asks.slice(asked2);
  // a refused context, and one answering `file: null`: asked once, then quiet with no fetch
  const before = asks.length;
  const g1 = elem("div", "body", "src/a.py"), g2 = elem("div", "body", "src/b.py");
  await AO.askItem(row("repo:/gone", g1)); await AO.askItem(row("repo:/gone", g2));
  const n1 = elem("div", "body", "src/a.py"), n2 = elem("div", "body", "src/b.py");
  await AO.askItem(row("id:ao-n", n1)); await AO.askItem(row("id:ao-n", n2));
  const quietAsks = asks.slice(before).map((a) => a[0]);
  const quietAnswer = await AO.itemAsker("repo:/gone").asker.resolve(["src/c.py"]);
  // a failed fetch caches nothing: the next row asks again
  failNext = true;
  const f1 = elem("div", "body", "lib/f.py");
  await AO.askItem(row("id:ao-w", f1));
  const f2 = elem("div", "body", "lib/f.py");
  const failedBefore = asks.length;
  await AO.askItem(row("id:ao-w", f2));
  const askedAfterFail = asks.length - failedBefore;
  // a row a poll redrew: relinked from the cache, no new ask
  const polled = elem("div", "body", "now src/x.py");
  const pr = row("repo:/r", polled);
  const box = elem("div", "", pr);
  const pollBefore = asks.length;
  AO.reopenFolds(box);
  const pollLinked = polled.querySelectorAll("a").length, pollAsks = asks.length - pollBefore;
  // a fold filled later is linked from the cache; filled again by the refetch, it keeps its links
  const fr = row("repo:/r");
  const fold = elem("details", "fold"); fold.dataset.lazy = "1"; fold.dataset.fold = "card:x";
  fold.insertAdjacentHTML = function (_where, html) { this.appendChild(elem("div", "body", html)); };
  Object.defineProperty(fold, "children", { get() { return this.childNodes.filter((c) => c.nodeType === 1); } });
  fr.appendChild(fold);
  const foldBefore = asks.length;
  const realFetch = global.fetch;
  const foldReply = { ok: true, status: 200, text: async () => "fold src/x.py" };
  global.fetch = async (url, opts) => (String(url).startsWith("/api/fold") ? foldReply : realFetch(url, opts));
  const rm = (c) => { c.remove = () => fold.removeChild(c); return c; };
  const origAppend = fold.appendChild.bind(fold);
  fold.appendChild = (c) => rm(origAppend(c));
  await AO.fillFold(fold);
  await new Promise((r) => setImmediate(r));
  delete fold.dataset.filled;  // opened again: the kept body first, then the refetch's
  await AO.fillFold(fold);
  await new Promise((r) => setImmediate(r));
  const foldLinks = fold.querySelectorAll("a").length, foldAsks = asks.length - foldBefore;
  // a new page (a fresh copy of the script) asks a quiet context again
  eval(fs.readFileSync(process.argv[2], "utf8"));
  const pageBefore = asks.length;
  await window.AO.askItem(row("repo:/gone", elem("div", "body", "src/a.py")));
  const newPageAsks = asks.length - pageBefore;
  console.log(JSON.stringify({ kept, under, asked1, hrefs, asked2, asked3, quietAsks, quietAnswer,
    askedAfterFail, pollLinked, pollAsks, foldLinks, foldAsks, newPageAsks, first: asks[0] }));
})();
"""


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_links_an_items_runs_by_its_context_and_keeps_its_markup():
    d = scratch_dir("item-paths")
    probe = d / "probe.js"
    probe.write_text(PROBE)
    out = subprocess.run(
        ["node", str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30, check=True
    )
    got = json.loads(out.stdout.strip().splitlines()[-1])
    # both runs wrapped, the `<code>` kept around its link, the folder first on the checkout's file
    assert got["kept"] == (
        '<div class="body md">see <code><a class="editor tpath" data-ctrl="" href="vscode://file/r/src/x.py:1"'
        ' data-label="VS Code" title="Ctrl+click: /r/src/x.py in VS Code"'
        ' data-folder="vscode://file/r?windowId=_blank" data-wait="1">src/x.py</a></code> and '
        '<a class="editor tpath" data-ctrl="" href="vscode://file/h/.shiftlead/attachments/d/x.png:1"'
        ' data-label="VS Code" title="Ctrl+click: /h/.shiftlead/attachments/d/x.png in VS Code">'
        "~/.shiftlead/attachments/d/x.png</a>.</div>"
    )
    assert "<a " not in got["under"], "a run under a summary stays text"
    assert got["first"] == ["repo:/r", ["src/x.py", "~/.shiftlead/attachments/d/x.png"]] and got["asked1"] == 1
    assert got["hrefs"] == ["vscode://file/r/src/x.py:12", "vscode://file/r/src/x.py:30"] and got["asked2"] == 1
    assert got["asked3"] == [["id:ao-w", ["src/x.py"]]], "the same run under another context is asked again"
    assert got["quietAsks"] == ["repo:/gone", "id:ao-n"], "a refused or formless context is asked once"
    assert got["quietAnswer"] == {}
    assert got["askedAfterFail"] == 1, "a failed fetch caches nothing"
    assert got["pollLinked"] == 1 and got["pollAsks"] == 0, "a redrawn row is relinked from the cache"
    assert got["foldLinks"] == 1 and got["foldAsks"] == 0, "a fold's body is linked from the cache, on both puts"
    assert got["newPageAsks"] == 1, "quiet lasts the page's life"
