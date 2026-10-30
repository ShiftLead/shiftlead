"""A path in the pane is a link (design §4.6 *A path in the pane is a link*, §4.5a **a path is a link**,
TD-493, built by TD-501): the page is served the editor button's file form beside the button
(`editor.file`), a link provider of its own asks the `paths` read once per row through
`POST /api/sessions/<id>/paths`, and only what the host resolved underlines and opens, on Ctrl or Cmd,
the line riding after the path on every `vscode` form (TD-526). The page's functions run as themselves
under node."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
import yaml
from conftest import scratch_dir
from fastapi.testclient import TestClient

from shiftlead.ui import help as helpmod
from shiftlead.ui import uiconf

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
REACH = "vscode://vscode-remote/attached-container+7b22636f6e7461696e65724e616d65223a222f6e31227d/workspaces/r?windowId=_blank"


def _person(text: str) -> None:
    uiconf.set_read({"person": yaml.safe_load(text) or {}, "migrate": []})


@pytest.fixture
def person():
    yield _person
    uiconf.set_read({"person": {}, "migrate": []})


@pytest.mark.unit
def test_the_file_form_is_the_buttons_template_with_path_unfilled(person):
    person("")
    # no windowId=_blank on a file form: a file lands in the window used last (TD-526)
    assert uiconf.editor_file(local=True, remote="km") == "vscode://file{path}"
    assert uiconf.editor_file(local=False, remote="km") == "vscode://vscode-remote/ssh-remote+km{path}"
    # a container's record: the reach link's own prefix, the file in its folder's place, its query dropped
    got = uiconf.editor_file(local=False, remote="km", reach=REACH)
    assert got == REACH.removesuffix("/workspaces/r?windowId=_blank") + "{path}"
    # the button's folder forms keep `_blank`: a folder into a used window replaces what it showed
    assert uiconf.editor_link("/r", local=True, remote="km")["url"] == "vscode://file/r?windowId=_blank"
    assert uiconf.editor_link("/r", local=False, remote="km")["url"].endswith("km/r?windowId=_blank")
    assert uiconf.editor_file(local=False, remote="km", reach="vscode://vscode-remote/x") is None
    person("open_in: {label: Zed, url: 'zed://ssh/{remote}{path}'}")
    assert uiconf.editor_file(local=False, remote="km") == "zed://ssh/km{path}"
    # a template names no container, and one without {path} names no file: no file links
    assert uiconf.editor_file(local=False, remote="km", reach=REACH) is None
    person("open_in: {label: Zed, url: 'zed://ssh/{remote}'}")
    assert uiconf.editor_file(local=False, remote="km") is None
    person("open_in: none")
    assert uiconf.editor_file(local=True, remote="km") is None


@pytest.mark.unit
def test_focus_is_served_editor_file_only_beside_its_editor_button(tmp_path, monkeypatch, person):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    from shiftlead.ui.app import view

    rec = {"id": "ao-x-1", "name": "w", "kind": "agent", "dir": str(tmp_path), "state": "idle"}
    person("")
    v = view(rec)
    assert v["editor"]["file"] == "vscode://file{path}" and v["editor"]["url"].startswith("vscode://")
    person("open_in: none")
    assert view(rec)["editor"] is None
    # a record on another host the button cannot reach: no button, so no file form
    person("")
    assert view({**rec, "host": "elsewhere"})["editor"] is None


@pytest.mark.unit
def test_the_route_forwards_the_runs_to_the_paths_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui import app as ui

    asked: list[tuple[str, dict]] = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            asked.append((method, kw))
            if method == "paths" and kw["id"] == "gone":
                raise ui.AgentError("no session gone")
            return {"paths": {"src/a.py": "/r/src/a.py", "build/review": None}} if method == "paths" else {}

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    r = c.post("/api/sessions/ao-x-1/paths", json={"runs": ["src/a.py", "build/review"]})
    assert r.status_code == 200 and r.json() == {"paths": {"src/a.py": "/r/src/a.py", "build/review": None}}
    assert ("paths", {"id": "ao-x-1", "runs": ["src/a.py", "build/review"]}) in asked
    # the host agent's refusal is the route's, as the transcript's is; not the generic action route's
    r = c.post("/api/sessions/gone/paths", json={"runs": ["x/y"]})
    assert r.status_code == 400 and "no session gone" in r.text


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
const timers = [];
global.setInterval = noop; global.setTimeout = (f, ms) => timers.push([f, ms]); global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// the pair (TD-535): what opened at the press, the wait asked for, and what opened when it ran
const pair = (event, editor, resolved, line) => {
  const opened = [];
  timers.length = 0;
  const r = AO.pathLink(event, editor, resolved, line, null, (...a) => opened.push(a));
  const atPress = opened.slice(), waits = timers.map(([, ms]) => ms);
  timers.splice(0).forEach(([f]) => f());
  return { r, atPress, waits, opened };
};
const runs = (t) => AO.pathRuns(t).map((r) => [r.run, r.path, r.line, r.col, r.start, r.end]);
const press = (event, file, resolved, line, col) => {
  const opened = [];
  const r = AO.pathLink(event, { file }, resolved, line, col, (...a) => opened.push(a));
  return { r, opened };
};
const FILE = "vscode://file{path}", SSH = "vscode://vscode-remote/ssh-remote+km{path}";
const BOX = "vscode://vscode-remote/attached-container+7b7d{path}";
(async () => {
  const rows = ["see src/shiftlead/cli.py:364 and build/review.", "nothing here at all",
    "Edit(scripts/x.py) then https://github.com/eyecantell/agentorc/pull/1"];
  const term = { buffer: { active: { getLine: (y) => rows[y] === undefined ? undefined
    : { translateToString: () => rows[y] } } } };
  const asked = [];
  let fail = false;
  const answer = { "src/shiftlead/cli.py": "/r/src/shiftlead/cli.py", "build/review": null,
    "scripts/x.py": "/r/scripts/x.py" };
  const p = AO.pathProvider(term, "ao-x-1", { file: FILE }, (r) => { asked.push(r);
    const paths = Object.fromEntries(r.map((k) => [k, answer[k] ?? null]));
    return fail ? Promise.reject(500) : Promise.resolve({ paths }); });
  const shape = (k) => ({ text: k.text, range: k.range, decorations: k.decorations });
  const hover = (y) => new Promise((res) => p.provideLinks(y, (l) => res(l ? l.map(shape) : null)));
  const first = await hover(1), again = await hover(1), empty = await hover(2), third = await hover(3);
  const askedBefore = asked.length;
  p.clear(); fail = true;
  const failed = await hover(1);
  fail = false;
  const after = await hover(1);
  let link;
  p.provideLinks(1, (l) => { link = l; });
  await new Promise((r) => setImmediate(r));
  const opened = [];
  const savedOpen = AO.openEditor; AO.openEditor = (...a) => opened.push(a);
  const plainClick = link[0].activate({}), ctrlClick = link[0].activate({ ctrlKey: true });
  AO.openEditor = savedOpen;
  // a wide character before the path: one character, two cells (xterm's width-0 cell after it)
  const cells = [["界", 2], ["", 0], [" ", 1], ..."a/b.py".split("").map((c) => [c, 1])];
  const wide = { buffer: { active: { getLine: (y) => (y === 0 ? { length: cells.length,
    translateToString: () => "界 a/b.py",
    getCell: (x) => ({ getChars: () => cells[x][0], getWidth: () => cells[x][1] }) } : undefined) } } };
  const wp = AO.pathProvider(wide, "ao-x-1", { file: FILE },
    (r) => Promise.resolve({ paths: { "a/b.py": "/r/a/b.py" } }));
  const wideLinks = await new Promise((res) => wp.provideLinks(1, (l) => res(l.map((k) => k.range))));
  // an answer that lands after a re-attach's clear is not kept: the next hover asks again
  let release;
  const slowAsked = [];
  const sp = AO.pathProvider(term, "ao-x-1", { file: FILE }, (r) => { slowAsked.push(r);
    return new Promise((res) => { release = () => res({ paths: { "scripts/x.py": "/r/scripts/x.py" } }); }); });
  const pending = new Promise((res) => sp.provideLinks(3, res));
  // a row of two lists without spaces (TD-1262): every member asked, eight paths an ask, and a member links
  const lists = { buffer: { active: { getLine: (y) => (y === 0
    ? { translateToString: () => "a/1,b/2,c/3,d/4 e/5,f/6,g/7,h/8 src/a.py#L12" } : undefined) } } };
  const listAsks = [];
  const lp = AO.pathProvider(lists, "ao-x-1", { file: FILE }, (r) => { listAsks.push(r);
    const ok = (k) => (["h/8", "src/a.py"].includes(k) ? "/r/" + k : null);
    return Promise.resolve({ paths: Object.fromEntries(r.map((k) => [k, ok(k)])) }); });
  const listLinks = await new Promise((res) => lp.provideLinks(1, (l) => res((l || []).map((k) => k.text))));
  // nine runs, each a list of two (TD-1272): the first eight are asked with their pieces, the ninth and its pieces not
  const nine = Array.from({ length: 9 }, (_, i) => `a/${i + 1},b/${i + 1}`).join(" ");
  const capped = { buffer: { active: { getLine: (y) => (y === 0 ? { translateToString: () => nine } : undefined) } } };
  const capAsks = [];
  const cp = AO.pathProvider(capped, "ao-x-1", { file: FILE }, (r) => { capAsks.push(r);
    return Promise.resolve({ paths: Object.fromEntries(r.map((k) => [k, null])) }); });
  await new Promise((res) => cp.provideLinks(1, res));
  sp.clear(); release(); await pending;
  sp.provideLinks(3, noop); await new Promise((r) => setImmediate(r));
  console.log(JSON.stringify({
    wideLinks, slowAsks: slowAsked.length, listAsks, listLinks, capAsks,
    long: runs("x/" + "a".repeat(600) + " and src/ok.py"),
    one: runs("see src/shiftlead/cli.py:364 and build/review."),
    shapes: runs("(./a/b.py) ~/x/y.md, /etc/hosts; ../up/z.ts:3:7] word a/"),
    url: runs("https://github.com/a/b/pull/1 and http://x/y/z"),
    bare: runs("no paths, just words and a.b and ./ and /"),
    wide: runs("docs/café/notes.md, build/a#1.txt out/a,b.txt dir/name=v.txt --file=src/a.py docs/界/a.md"),
    pieces: runs("src/a.py#L12 a/b.py,c/d.py x/a=b/c.py e/f.py= g/h.py:3,"),
    first, again, empty, third, askedBefore, asked, failed, after, plainClick, ctrlClick, opened,
    file: press({ ctrlKey: true }, FILE, "/r/my dir/a#b.py", 12, 3),
    fileNoLine: press({ metaKey: true }, FILE, "/r/a.py", null, null),
    ssh: press({ ctrlKey: true }, SSH, "/r/a.py", 12, null),
    sshNoLine: press({ ctrlKey: true }, SSH, "/r/a.py", null, null),
    box: press({ ctrlKey: true }, BOX, "/w/a.py", 7, 2),
    boxNoLine: press({ ctrlKey: true }, BOX, "/w/a.py", null, null),
    tmpl: press({ ctrlKey: true }, "zed://ssh/km{path}:{line}", "/r/a.py", 12, 3),
    tmplNoLine: press({ ctrlKey: true }, "zed://ssh/km{path}:{line}", "/r/a.py", null, null),
    tmplTwice: press({ ctrlKey: true }, "x://o?f={path}&l={line}&g={line}", "/r/a.py", 9, null),
    tmplBare: press({ ctrlKey: true }, "zed://ssh/km{path}", "/r/a.py", 12, null),
    tmplQuery: press({ ctrlKey: true }, "vscode://file{path}?windowId=_blank", "/r/a.py", 12, null),
    plain: press({}, FILE, "/r/a.py", 1, null),
    none: press({ ctrlKey: true }, FILE, null, 1, null),
    pairSsh: pair({ ctrlKey: true }, { url: "vscode://vscode-remote/ssh-remote+km/r?windowId=_blank", label: "VS Code",
      file: SSH }, "/r/a.py", 12),
    pairPlain: pair({}, { url: "vscode://file/r?windowId=_blank", label: "VS Code", file: FILE }, "/r/a.py", 12),
    wait: AO.FOLDER_WAIT,
    // the person's `file_link` on the record's editor (TD-536): off, the file alone; on, their wait
    pairOff: pair({ ctrlKey: true }, { url: "vscode://file/r?windowId=_blank", label: "VS Code", file: FILE,
      first: false, wait: 2 }, "/r/a.py", 12),
    pairWait: pair({ ctrlKey: true }, { url: "vscode://file/r?windowId=_blank", label: "VS Code", file: FILE,
      first: true, wait: 2.5 }, "/r/a.py", 12),
    pairNoWait: pair({ ctrlKey: true }, { url: "vscode://file/r?windowId=_blank", label: "VS Code", file: FILE,
      first: true, wait: 0 }, "/r/a.py", 12),
  }));
})();
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the provider is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "path_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_the_runs_a_row_yields():
    got = _probe()
    assert got["one"] == [["src/shiftlead/cli.py:364", "src/shiftlead/cli.py", 364, None, 4, 28],
                          ["build/review", "build/review", None, None, 33, 45]]  # fmt: skip
    # relative, ./, ~/, ../ and absolute; the bracket or sentence stop at the tail is not the run's
    assert [r[0] for r in got["shapes"]] == ["./a/b.py", "~/x/y.md", "/etc/hosts", "../up/z.ts:3:7"]
    assert got["shapes"][3][2:4] == [3, 7]
    # a run inside a URL is the URL's, and a bare word, `./` or `/` is never a candidate
    assert got["url"] == [] and got["bare"] == []
    # a run past the read's 512 characters is no candidate, so the rest of its row is still asked
    assert [r[0] for r in got["long"]] == ["src/ok.py"]
    # any letter, and `#`, `,` and `=` after the first `/`; the tail's `,` is still cut (TD-1262)
    # each run holding `#`, `,` or `=` is followed by its pieces without them: the first the host resolves links
    assert [r[0] for r in got["wide"]] == ["docs/café/notes.md", "build/a#1.txt", "build/a", "out/a,b.txt", "out/a",
                                           "dir/name=v.txt", "dir/name", "src/a.py", "docs/界/a.md"]  # fmt: skip
    # so an anchor, a list without spaces and a trailing `=` still ask what linked before
    assert [r[0] for r in got["pieces"]] == ["src/a.py#L12", "src/a.py", "a/b.py,c/d.py", "a/b.py", "c/d.py",
                                             "x/a=b/c.py", "x/a", "b/c.py", "e/f.py=", "e/f.py",
                                             "g/h.py:3"]  # fmt: skip
    assert [r[4] for r in got["pieces"]][:5] == [0, 0, 13, 13, 20]  # a piece's columns are the row's


@pytest.mark.unit
def test_a_links_range_is_in_cells_and_an_answer_from_before_a_reattach_is_not_kept():
    got = _probe()
    # `界` is one character over two cells: the path starts at cell 4, not 3
    assert got["wideLinks"] == [{"start": {"x": 4, "y": 1}, "end": {"x": 9, "y": 1}}]
    assert got["slowAsks"] == 2


@pytest.mark.unit
def test_a_runs_pieces_are_asked_beside_eight_runs_eight_paths_an_ask():
    got = _probe()
    # three runs and their nine pieces: twelve paths over two asks, none past eight (PATHS_RUNS_MAX)
    asked = [p for ask in got["listAsks"] for p in ask]
    assert [len(a) for a in got["listAsks"]] == [8, 4]
    assert {"a/1", "d/4", "e/5", "h/8", "src/a.py#L12", "src/a.py"} <= set(asked)
    assert got["listLinks"] == ["h/8", "src/a.py"]  # the member and the anchor's file, where the wholes are no file
    # past eight runs (TD-1272): the ninth run is not asked, nor its pieces, and each of the first eight's pieces is
    capped = {p for ask in got["capAsks"] for p in ask}
    assert len(capped) == 24 and all(len(a) <= 8 for a in got["capAsks"])
    assert {f"a/{i},b/{i}" for i in range(1, 9)} | {f"{c}/{i}" for c in "ab" for i in range(1, 9)} == capped


@pytest.mark.unit
def test_a_row_is_asked_once_and_only_what_the_host_resolved_is_a_link():
    got = _probe()
    link = {"text": "src/shiftlead/cli.py:364", "range": {"start": {"x": 5, "y": 1}, "end": {"x": 28, "y": 1}},
            "decorations": {"underline": True, "pointerCursor": True}}  # fmt: skip
    # build/review in the same row is not a file: text
    assert got["first"] == [link] and got["again"] == [link]
    assert got["empty"] is None  # a row with no candidates asks nothing
    assert [k["text"] for k in got["third"]] == ["scripts/x.py"]  # the URL on the row is the addon's
    assert got["askedBefore"] == 2  # rows 1 and 3, once each; the second hover was answered from memory
    assert got["asked"][0] == ["src/shiftlead/cli.py", "build/review"]
    # a failed ask is no link and remembered nowhere: the next hover asks again
    assert got["failed"] is None and got["after"] == [link]


@pytest.mark.unit
def test_only_ctrl_or_cmd_opens_and_the_line_rides_on_every_vscode_form():
    got = _probe()
    assert got["plainClick"] is False and got["ctrlClick"] is True
    assert got["opened"] == [["vscode://file/r/src/shiftlead/cli.py:364", "the editor"]]
    # percent-encoded, `/` kept (§5, TD-011); the line and column after the path
    assert got["file"]["opened"] == [["vscode://file/r/my%20dir/a%23b.py:12:3", "the editor"]]
    # no line printed: `:1`, so a remote path opens as a file and not a folder (TD-524, TD-526)
    assert got["fileNoLine"]["opened"] == [["vscode://file/r/a.py:1", "the editor"]]
    assert got["ssh"]["opened"] == [["vscode://vscode-remote/ssh-remote+km/r/a.py:12", "the editor"]]
    assert got["sshNoLine"]["opened"] == [["vscode://vscode-remote/ssh-remote+km/r/a.py:1", "the editor"]]
    assert got["box"]["opened"] == [["vscode://vscode-remote/attached-container+7b7d/w/a.py:7:2", "the editor"]]
    assert got["boxNoLine"]["opened"] == [["vscode://vscode-remote/attached-container+7b7d/w/a.py:1", "the editor"]]
    # a template's {line} takes the line, `1` where none was printed; one without it is filled as it
    # stands, and one of the person's own with a query is a template, not a `vscode` form
    assert got["tmpl"]["opened"] == [["zed://ssh/km/r/a.py:12", "the editor"]]
    assert got["tmplNoLine"]["opened"] == [["zed://ssh/km/r/a.py:1", "the editor"]]
    assert got["tmplTwice"]["opened"] == [["x://o?f=/r/a.py&l=9&g=9", "the editor"]]
    assert got["tmplBare"]["opened"] == [["zed://ssh/km/r/a.py", "the editor"]]
    assert got["tmplQuery"]["opened"] == [["vscode://file/r/a.py?windowId=_blank", "the editor"]]
    assert got["plain"] == {"r": False, "opened": []} and got["none"] == {"r": False, "opened": []}


@pytest.mark.unit
def test_a_press_is_two_launches_the_folder_then_the_file_a_second_after():
    """§4.6 *The press is two launches* (TD-532, built by TD-535): the folder link exactly as the Session
    card's button sends it, then after the fixed wait the file form, quietly — one toast for the pair."""
    got = _probe()
    p = got["pairSsh"]
    assert p["r"] is True and got["wait"] == 1000 and p["waits"] == [1000]
    assert p["atPress"] == [["vscode://vscode-remote/ssh-remote+km/r?windowId=_blank", "VS Code"]]
    assert p["opened"] == [
        ["vscode://vscode-remote/ssh-remote+km/r?windowId=_blank", "VS Code"],
        ["vscode://vscode-remote/ssh-remote+km/r/a.py:12", "VS Code", True],  # quiet: no second toast
    ]
    assert got["pairPlain"] == {"r": False, "atPress": [], "waits": [], "opened": []}


@pytest.mark.unit
def test_the_persons_file_link_turns_the_folder_off_and_sets_the_wait():
    """§4.6, §5 `person.file_link` (TD-536, built by TD-537): `first: false` on the record's editor is
    TD-526's one launch, the file form alone and with its toast; on, the wait is the person's seconds."""
    got = _probe()
    off = got["pairOff"]
    assert off["r"] is True and off["waits"] == [] and off["opened"] == [["vscode://file/r/a.py:12", "VS Code"]]
    on = got["pairWait"]
    assert on["waits"] == [2500] and on["atPress"] == [["vscode://file/r?windowId=_blank", "VS Code"]]
    assert on["opened"][1] == ["vscode://file/r/a.py:12", "VS Code", True]
    assert got["pairNoWait"]["waits"] == [0] and len(got["pairNoWait"]["opened"]) == 2


@pytest.mark.unit
def test_focus_registers_the_provider_only_where_the_header_draws_its_editor_button():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    made = "const pathLinks = s.editor && s.editor.file ? AO.pathProvider(term, id, s.editor) : null;"
    assert made in focus and "if (pathLinks) term.registerLinkProvider(pathLinks);" in focus
    # beside the web-links addon, before the attach decides read-only; a re-attach forgets the answers
    assert focus.index("new WebLinksAddon.WebLinksAddon") < focus.index(made) < focus.index("let readOnly = false")
    assert "if (pathLinks) pathLinks.clear();" in focus


@pytest.mark.unit
def test_the_help_carries_the_path_link_under_focus():
    h = {x.key: x for x in helpmod.HELP}["pane-path"]
    assert h.name == "a path is a link" and h.where == "Focus pane"
    assert "Ctrl+click (Cmd+click on a Mac)" in h.text and "no file links" in h.text
    assert "pane-path" in dict((g[0], g[2]) for g in helpmod.SCREENS)["focus"]


QUIET_PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop, remove: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const frames = [];
const body = { ...el(), appendChild: (f) => frames.push(f.src) };
const document = { documentElement: el(), body, querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
const timers = [];
global.setInterval = noop; global.setTimeout = (f, ms) => timers.push([f, ms]); global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const toasts = [];
AO.toast = (...a) => toasts.push(a);
// the real `AO.openEditor`, its toast and its hidden frame recorded; the frame's removal timer dropped
const run = (f) => { toasts.length = 0; frames.length = 0; timers.length = 0; f();
  timers.splice(0).filter(([, ms]) => ms !== 3000).forEach(([g]) => g());
  return { toasts: toasts.slice(), frames: frames.slice() }; };
console.log(JSON.stringify({
  loud: run(() => AO.openEditor("vscode://file/r?windowId=_blank", "VS Code")),
  quiet: run(() => AO.openEditor("vscode://file/r/a.py:1", "VS Code", true)),
  pair: run(() => AO.openFile({ url: "vscode://file/r?windowId=_blank", label: "VS Code" }, "vscode://file/r/a.py:1")),
}));
"""


@pytest.mark.unit
def test_open_editor_toasts_unless_quiet_and_a_pair_toasts_once():
    """TD-540 (test audit of #1483): the real `AO.openEditor` — a launch toasts once, a quiet one none,
    and `AO.openFile`'s pair (§4.6 *The press is two launches*) sends both frames under one toast."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the opener is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "quiet_probe.js"
    probe.write_text(QUIET_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["loud"] == {"toasts": [["opening in VS Code…", True]], "frames": ["vscode://file/r?windowId=_blank"]}
    assert got["quiet"] == {"toasts": [], "frames": ["vscode://file/r/a.py:1"]}
    assert got["pair"]["frames"] == ["vscode://file/r?windowId=_blank", "vscode://file/r/a.py:1"]
    assert got["pair"]["toasts"] == [["opening in VS Code…", True]]


# TD-1259: the provider reads a row in its logical line. The screen's rows are strings padded to the width, a
# cell a character, with a soft wrap marked `isWrapped`; `links(y)` is what the provider hands xterm for row y.
WRAP_PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.window = {}; global.document = { documentElement: el(), body: el(), querySelector: () => null,
  querySelectorAll: () => [], addEventListener: noop, createElement: el };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const cols = 40;
const cell = (ch) => ({ getChars: () => ch, getWidth: () => 1 });
const screen = (rows, files) => {
  const lines = rows.map(([text, wrapped]) => {
    const cells = text.padEnd(cols, "\\0").slice(0, cols).split("").map((c) => (c === "\\0" ? "" : c));
    return { isWrapped: wrapped, length: cols, getCell: (x) => cell(cells[x]),
      translateToString: (trim) => { const t = cells.map((c) => c || " ").join(""); return trim ? t.trimEnd() : t; } };
  });
  const asked = [];
  const term = { registerLinkProvider: noop,
    buffer: { active: { getLine: (y) => lines[y], getNullCell: () => cell("") } } };
  const p = AO.pathProvider(term, "ao-x-1", { file: "vscode://file{path}" }, (r) => { asked.push(r);
    return Promise.resolve({ paths: Object.fromEntries(r.map((k) => [k, files[k] || null])) }); });
  const links = (y) => new Promise((res) => p.provideLinks(y, (l) =>
    res(l ? l.map((k) => ({ text: k.text, range: k.range })) : null)));
  return { links, asked };
};
(async () => {
  // one path over three rows: row 2 soft-wrapped, row 3 cut by the program at the width (no wrap mark)
  const path = "/tmp/claude-1000/-home-kmaster-agent-cadence/5634736a-ec3f-495f-82d9/scratchpad/td203-plan.md";
  const head = "see " + path.slice(0, cols - 4), mid = path.slice(cols - 4, 2 * cols - 4);
  const rest = path.slice(2 * cols - 4);
  const long = screen([[head, false], [mid, true], [rest + " done", false], ["next line", false]],
    { [path]: "/r" + path });
  const spans = [await long.links(1), await long.links(2), await long.links(3), await long.links(4)];
  // a path that ends at the last column, and a cut row of prose after it: the joined run is no file,
  // the row's own run is, so the link stays the row's
  const full = "x".repeat(cols - 11) + " src/a/b.py";
  const prose = screen([[full.slice(-cols), false], ["and more words", false]], { "src/a/b.py": "/r/src/a/b.py" });
  const kept = [await prose.links(1), await prose.links(2)];
  // both the joined run and the row's own run it covers are files (TD-1273): one link, the joined one
  const both = screen([[full.slice(-cols), false], ["and more words", false]],
    { "src/a/b.py": "/r/src/a/b.py", "src/a/b.pyand": "/r/src/a/b.pyand" });
  const won = await both.links(1);
  console.log(JSON.stringify({ path, rest, spans, longAsked: long.asked, kept, proseAsked: prose.asked, won }));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.mark.unit
def test_a_path_that_wraps_or_is_cut_across_rows_is_one_link_on_every_row():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the provider is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "wrap_probe.js"
    probe.write_text(WRAP_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    path, rest = got["path"], got["rest"]
    link = {"text": path, "range": {"start": {"x": 5, "y": 1}, "end": {"x": len(rest), "y": 3}}}
    # the same link from each of its three rows, the soft-wrapped one and the cut one alike; the row after is none
    assert got["spans"] == [[link], [link], [link], None]
    assert all(path in a for a in got["longAsked"])
    # a joined run that is no file leaves the row's own run its link, and the prose row takes none
    one = {"text": "src/a/b.py", "range": {"start": {"x": 31, "y": 1}, "end": {"x": 40, "y": 1}}}
    assert got["kept"] == [[one], None]
    assert got["proseAsked"][0] == ["src/a/b.pyand", "src/a/b.py"]
    # where both are files, the joined run wins and the row's own run it covers is no second link (TD-1273)
    assert got["won"] == [{"text": "src/a/b.pyand", "range": {"start": {"x": 31, "y": 1}, "end": {"x": 3, "y": 2}}}]
