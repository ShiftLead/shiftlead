"""A path in a transcript is a link too (design §4.6 *A path in a transcript is a link too*, §4.5a
*Transcript*; TD-688, built by TD-691): the Transcript page is served what a press sends beside its
**VS Code** button and absent with it; a turn block, on its first hover, asks the pane's `paths` read
for its runs — eight at most per ask, one ask in flight, each answer kept for the page's life — and
each run the host resolved becomes an `a.editor` opened on Ctrl or Cmd, the session's folder first.
The page's functions run as themselves under node."""

from __future__ import annotations

import html as htmllib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest
from test_ui_transcript import page  # noqa: F401 — the fixture

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"


def _paths_attr(html: str) -> dict | None:
    m = re.search(r"id=\"transcript\" data-id=\"[^\"]*\" data-paths='([^']*)'", html)
    return json.loads(htmllib.unescape(m.group(1))) if m else None


@pytest.mark.unit
def test_the_page_is_served_the_press_beside_its_editor_button_and_absent_with_it(page, monkeypatch):  # noqa: F811
    c, _, replies, _ = page
    got = _paths_attr(c.get("/transcript/ao-x-designer").text)
    assert got["file"].startswith("vscode://") and got["file"].endswith("{path}")
    assert got["url"].startswith("vscode://") and "/r/wt" in got["url"] and got["wait"] == 1  # the session's folder
    from shiftlead.ui import uiconf

    monkeypatch.setattr(uiconf, "file_link", lambda: {"folder_first": False, "wait": 1})
    assert _paths_attr(c.get("/transcript/ao-x-designer").text)["url"] is None  # one launch
    replies["get"] = {**replies["get"], "host": "laptop"}  # another host's record: no button, no links
    html = c.get("/transcript/ao-x-designer").text
    assert "data-paths" not in html
    replies["get"] = {k: v for k, v in replies["get"].items() if k != "host"}
    monkeypatch.setattr(uiconf, "open_in", lambda: uiconf.OpenIn(kind="none"))
    assert "data-paths" not in c.get("/transcript/ao-x-designer").text


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
const ED = { label: "VS Code", file: "vscode://file{path}", url: "vscode://file/r/wt?windowId=_blank", wait: 1 };
const text = (t) => ({ textContent: t, innerHTML: null });
const block = (...els) => ({ dataset: {}, querySelectorAll: (sel) => (sel === AO.TRANSCRIPT_TEXT ? els : []) });
const ANSWER = { "src/a.py": "/r/wt/src/a.py", "docs/x.md": "/r/wt/docs/x.md", "build/review": null };
(async () => {
  const asked = [];
  let inFlight = 0, most = 0, fail = false;
  const ask = (runs) => { asked.push(runs); inFlight += 1; most = Math.max(most, inFlight);
    return new Promise((res, rej) => setImmediate(() => { inFlight -= 1;
      fail ? rej(500) : res({ paths: Object.fromEntries(runs.map((r) => [r, ANSWER[r] ?? null])) }); })); };
  const asker = AO.pathsAsker(ask);
  const askedAtStart = asked.length;
  // a turn with a resolving path and one without
  const said = text("see src/a.py:12 and build/review. <b>"), plain = text("nothing to link here");
  const b1 = block(said, plain);
  const first = AO.transcriptBlock(b1, asker, ED);
  const again = AO.transcriptBlock(b1, asker, ED);  // a block is asked once
  await first;
  // a run met twice, in two blocks hovered together: asked once; the second's answer is the kept one
  const t2 = text("src/a.py again, and docs/x.md"), t3 = text("docs/x.md:3");
  await Promise.all([AO.transcriptBlock(block(t2), asker, ED), AO.transcriptBlock(block(t3), asker, ED)]);
  // eleven runs: two asks of eight at most, one at a time
  const many = text(Array.from({ length: 11 }, (_, i) => `d/f${i}.py`).join(" "));
  await AO.transcriptBlock(block(many), asker, ED);
  // a failed ask leaves the text as it was, and is kept nowhere
  fail = true;
  const lost = text("e/g.py");
  await AO.transcriptBlock(block(lost), asker, ED);
  fail = false;
  // the chain goes on after a failure; a run the answer leaves out is not kept, so it is asked again
  const after = text("src/a.py and e/g.py");
  await AO.transcriptBlock(block(after), asker, ED);
  const short = AO.pathsAsker((runs) => Promise.resolve({ paths: {} }));
  await short.resolve(["x/y.py"]);
  const shortAsks = [];
  const short2 = AO.pathsAsker((runs) => { shortAsks.push(runs); return Promise.resolve({ paths: {} }); });
  await short2.resolve(["x/y.py"]); await short2.resolve(["x/y.py"]);
  const hostile = AO.pathLinksHtml(`src/a.py <i>'"`, { "src/a.py": `/r/"a'.py` }, { ...ED, label: `V"S <x>` });
  // a block with no run asks nothing
  const before = asked.length;
  const none = AO.transcriptBlock(block(text("no paths")), asker, ED);
  console.log(JSON.stringify({ askedAtStart, again, asked, most, none, noRunAsks: asked.length - before,
    after: after.innerHTML, shortAsks, hostile,
    said: said.innerHTML, plain: plain.innerHTML, t2: t2.innerHTML, t3: t3.innerHTML, lost: lost.innerHTML,
    oneLaunch: AO.pathLinksHtml("src/a.py", { "src/a.py": "/r/wt/src/a.py" }, { ...ED, url: null }) }));
})();
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the page's paths are JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "transcript_paths_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_a_block_is_asked_on_its_first_hover_and_a_run_met_twice_once():
    got = _probe()
    assert got["askedAtStart"] == 0  # no ask before a hover
    assert got["again"] is None  # the second hover of a block asks nothing
    assert got["asked"][0] == ["src/a.py", "build/review"]
    assert got["asked"][1] == ["docs/x.md"]  # src/a.py was kept; docs/x.md met twice, asked once
    assert [len(a) for a in got["asked"][2:4]] == [8, 3] and got["most"] == 1  # eight at most, one in flight
    assert got["asked"][4] == ["e/g.py"] and got["asked"][5] == ["e/g.py"]  # the failure kept nothing
    assert got["none"] is None and got["noRunAsks"] == 0
    assert got["after"].count("<a ") == 1  # the chain goes on after a failed ask
    assert got["shortAsks"] == [["x/y.py"], ["x/y.py"]]  # a run the answer left out is asked again


@pytest.mark.unit
def test_a_resolved_run_is_a_ctrl_link_with_the_folder_first_and_the_rest_stays_text():
    got = _probe()
    said = got["said"]
    assert said.startswith('see <a class="editor tpath" data-ctrl href="vscode://file/r/wt/src/a.py:12"')
    assert 'data-folder="vscode://file/r/wt?windowId=_blank" data-wait="1"' in said
    assert ">src/a.py:12</a> and build/review. &lt;b&gt;" in said  # unresolved and the session's words: escaped text
    assert got["plain"] is None  # a text with nothing resolved is left as it was
    assert got["t2"].count("<a ") == 2 and 'href="vscode://file/r/wt/docs/x.md:1"' in got["t2"]
    assert 'href="vscode://file/r/wt/docs/x.md:3"' in got["t3"]
    assert got["lost"] is None
    assert "data-folder" not in got["oneLaunch"]  # folder_first off: the file alone
    hostile = got["hostile"]  # the session's words and the person's label are escaped wherever they land
    assert hostile.count("<a ") == 1 and "<i>" not in hostile and "&lt;i&gt;" in hostile
    assert 'data-label="V&quot;S &lt;x&gt;"' in hostile and "/r/%22a'.py:1" in hostile  # the path percent-encoded


@pytest.mark.unit
def test_a_plain_click_on_a_transcript_path_opens_nothing():
    js = (UI / "static" / "app.js").read_text()
    assert 'if ("ctrl" in a.dataset && !(ev.ctrlKey || ev.metaKey)) return;' in js
    assert js.index("ev.preventDefault();\n    // a file's link") < js.index('if ("ctrl" in a.dataset')
