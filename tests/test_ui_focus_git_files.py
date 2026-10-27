"""The Focus Git card's **changed files** (design §4.5a *Focus side panel, Git card: changed files*,
TD-627, built by TD-628): each `git.files` path a link by the recent files' form, joined to the
worktree's top level, the status code text before it; a deletion and a new directory stay text with
why on hover; no file form, every line text. The page's function runs as itself under node."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import scratch_dir
from test_ui import client  # noqa: F401 — the fixture, by name

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
const editor = { url: "vscode://file/w/wt?windowId=_blank", label: "VS Code", file: "vscode://file{path}" };
const files = ["M src/a b.py", "?? notes.txt", "UU conflict.py", "R renamed.py", "D gone.py", "MD md.py",
  "AD ad.py", "RD rd.py", "D c.py", "?? c.py", "?? newdir/"];
const v = { dir: "/w/wt/sub", git: { files } };
console.log(JSON.stringify({
  linked: AO.gitFiles(v, editor, "/w/wt"),
  noRoot: AO.gitFiles({ dir: "/w/wt/", git: { files: ["M a.py"] } }, editor, ""),
  folderOff: AO.gitFiles({ dir: "/w/wt", git: { files: ["M a.py"] } }, { ...editor, first: false }, "/w/wt"),
  text: AO.gitFiles(v, { url: "zed://x", label: "Zed", file: null }, "/w/wt"),
  none: AO.gitFiles(v, null, "/w/wt"),
  clean: AO.gitFiles({ dir: "/w/wt", git: { files: [] } }, editor, "/w/wt"),
}));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the Git card's lines are JavaScript, and nothing else runs it")
    probe = scratch_dir() / "git_files_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _rows(html: str) -> list[str]:
    return re.findall(r"<div>(.*?)</div>", html)


@pytest.mark.unit
def test_a_changed_path_is_a_link_joined_to_the_worktrees_top_level():
    got = _probe()
    rows = _rows(got["linked"])
    # the lines keep their text and their order: the code, then the path
    assert [re.sub(r"<[^>]+>", "", r) for r in rows] == [
        "M src/a b.py",
        "?? notes.txt",
        "UU conflict.py",
        "R renamed.py",
        "D gone.py",
        "MD md.py",
        "AD ad.py",
        "RD rd.py",
        "D c.py",
        "?? c.py",
        "?? newdir/",
    ]
    # a modified, an untracked, a conflicted and a renamed path: a link by the file form, joined to the
    # top level (not the directory below it), the folder first, as the recent files' are
    for row, path, enc in [
        (rows[0], "src/a b.py", "src/a%20b.py"),
        (rows[1], "notes.txt", "notes.txt"),
        (rows[2], "conflict.py", "conflict.py"),
        (rows[3], "renamed.py", "renamed.py"),
        (rows[9], "c.py", "c.py"),
    ]:
        assert row.startswith(row.split(" ", 1)[0] + " <a ")
        assert (
            f'<a class="editor" href="vscode://file/w/wt/{enc}:1" data-folder="vscode://file/w/wt?windowId=_blank"'
            f' data-label="VS Code" title="/w/wt/{path}">{path}</a>'
        ) in row
    # the status code stays text before the link
    assert rows[0].startswith("M <a ") and rows[1].startswith("?? <a ")


@pytest.mark.unit
def test_a_deletion_and_a_new_directory_stay_text_saying_why():
    rows = _rows(_probe()["linked"])
    for i, path in enumerate(["gone.py", "md.py", "ad.py", "rd.py", "c.py"], start=4):
        row = rows[i]
        assert "<a " not in row and f'<span title="deleted in the worktree">{path}</span>' in row
    # a file deleted and made again: the `D` line text, the `??` line a link (TD-632)
    assert "<a " not in rows[8] and '<a class="editor"' in rows[9]
    assert rows[10] == """?? <span title="a new directory: open it from the worktree's window">newdir/</span>"""


@pytest.mark.unit
def test_no_file_form_draws_every_line_as_text_and_none_reads_clean():
    got = _probe()
    for key in ("text", "none"):
        assert "<a " not in got[key] and "title=" not in got[key]
        assert len(_rows(got[key])) == 11
    assert got["clean"] == '<div class="muted">clean</div>'


@pytest.mark.unit
def test_with_no_top_level_the_directory_is_the_root_and_the_folder_launch_follows_the_person():
    got = _probe()
    assert 'href="vscode://file/w/wt/a.py:1"' in got["noRoot"]
    assert "data-folder" not in got["folderOff"] and 'href="vscode://file/w/wt/a.py:1"' in got["folderOff"]


@pytest.mark.unit
def test_focus_draws_the_card_by_the_same_function_on_load_and_each_delta():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    render = focus[focus.index("    function render(v) {") :]
    render = render[: render.index("\n    }\n")]
    assert '$("#gitfiles").innerHTML = AO.gitFiles(v, s.editor, s.git_root);' in render
    assert "    render(s);" in focus  # the load is a render of the served view


def test_focus_is_served_the_worktrees_top_level_for_a_directory_below_it(client, tmp_path):  # noqa: F811
    top = tmp_path / "wt"
    sub = top / "sub"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(top)], check=True)
    want = subprocess.run(
        ["git", "-C", str(sub), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    r = client.post("/new", data={"name": "gf", "dir": str(sub), "adapter": "hookstub"}, follow_redirects=False)
    sid = r.headers["location"].rsplit("/", 1)[-1]
    html = client.get(f"/focus/{sid}").text
    served = json.loads(html[html.index("AO.focus(") + len("AO.focus(") : html.index(", false);</script>")])
    assert served["editor"] and served["git_root"] == want
    client.post(f"/api/sessions/{sid}/kill")
