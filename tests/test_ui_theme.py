"""The theme is set before the first paint (design §4.5 *Browser mechanics*, TD-737): `base.html`'s
`<head>` writes `html[data-theme]` before the stylesheet, so a page change never paints the light
theme on a dark browser, and `app.js`'s `applyTheme` reads the same theme again at load. The scripts
are JavaScript, run as themselves under node."""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
BASE = UI / "templates" / "base.html"

pytestmark = pytest.mark.unit

# the stubs each case runs under: what `localStorage` holds for `ao.theme` (or throws), and whether the
# system is dark (or `matchMedia` throws)
STUBS = """
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
const cases = JSON.parse(process.argv[2]);
const script = require("fs").readFileSync(process.argv[3], "utf8");
const out = [];
for (const c of cases) {
  global.window = {};
  global.document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
    addEventListener: noop, createElement: el };
  global.localStorage = { getItem: (k) => { if (c.store === "throw") throw new Error("blocked");
    return k === "ao.theme" ? c.store : null; }, setItem: noop };
  global.matchMedia = (q) => { if (c.dark === "throw") throw new Error("none");
    return { matches: q === "(prefers-color-scheme: dark)" && c.dark }; };
  eval(script);
  out.push(document.documentElement.dataset.theme);
}
console.log(JSON.stringify(out));
"""

CASES = [
    {"store": '"light"', "dark": True},
    {"store": '"dark"', "dark": False},
    {"store": None, "dark": True},
    {"store": None, "dark": False},
    {"store": '"blue"', "dark": True},
    {"store": "true", "dark": False},
    {"store": "not json", "dark": False},
    {"store": "throw", "dark": True},
    {"store": None, "dark": "throw"},
]
# a stored theme wins, else the system's; a stored value that is not a theme is the system's; a read
# that fails is dark
WANT = ["light", "dark", "dark", "light", "dark", "light", "light", "dark", "dark"]


def _head() -> str:
    return BASE.read_text(encoding="utf-8").split("</head>", 1)[0]


def _run(tmp_path, script: pathlib.Path) -> list:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    (tmp_path / "probe.js").write_text(STUBS)
    out = subprocess.run(
        [node, str(tmp_path / "probe.js"), json.dumps(CASES), str(script)], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_theme_script_runs_before_the_stylesheet():
    head = _head()
    script = head.index("<script>")
    assert script < head.index('rel="stylesheet"'), "the theme is written after the stylesheet loads"
    assert "src=" not in head[script : head.index("</script>", script)], "the theme script is inline"
    assert '<meta name="color-scheme" content="dark light">' in head


def test_each_theme_sets_its_own_color_scheme():
    css = (UI / "static" / "app.css").read_text(encoding="utf-8")
    assert re.search(r":root \{\s*color-scheme: light;", css)
    assert re.search(r'html\[data-theme="dark"\] \{\s*color-scheme: dark;', css)


def test_the_head_reads_the_theme(tmp_path):
    head = _head()
    start = head.index("<script>") + len("<script>")
    (tmp_path / "theme.js").write_text(head[start : head.index("</script>", start)])
    assert _run(tmp_path, tmp_path / "theme.js") == WANT


def test_apply_theme_reads_as_the_head_does(tmp_path):
    """`app.js` sets the theme again at load; were its read to differ from the head's, the page would
    turn from one theme to the other there, which is the flash again."""
    assert _run(tmp_path, UI / "static" / "app.js") == WANT
