"""The theme is set before the first paint (design §4.5 *Browser mechanics*, TD-737): `base.html`'s
`<head>` writes `html[data-theme]` before the stylesheet, so a page change never paints the light
theme on a dark browser. The script is JavaScript, run as itself under node."""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
BASE = UI / "templates" / "base.html"

pytestmark = pytest.mark.unit

PROBE = """
const cases = JSON.parse(process.argv[2]);
const script = require("fs").readFileSync(process.argv[3], "utf8");
const out = [];
for (const c of cases) {
  global.document = { documentElement: { dataset: {} } };
  global.localStorage = { getItem: (k) => { if (c.store === "throw") throw new Error("blocked");
    return k === "ao.theme" ? c.store : null; } };
  global.matchMedia = (q) => { if (c.dark === "throw") throw new Error("none");
    return { matches: q === "(prefers-color-scheme: dark)" && c.dark }; };
  eval(script);
  out.push(document.documentElement.dataset.theme);
}
console.log(JSON.stringify(out));
"""


def _head() -> str:
    return BASE.read_text(encoding="utf-8").split("</head>", 1)[0]


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


def test_the_head_reads_the_theme_as_apply_theme_does(tmp_path):
    """A stored theme wins, else the system's; a stored value that is not a theme is the system's;
    a read that fails is dark."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    head = _head()
    start = head.index("<script>") + len("<script>")
    (tmp_path / "theme.js").write_text(head[start : head.index("</script>", start)])
    (tmp_path / "probe.js").write_text(PROBE)
    cases = [
        {"store": '"light"', "dark": True},
        {"store": '"dark"', "dark": False},
        {"store": None, "dark": True},
        {"store": None, "dark": False},
        {"store": '"blue"', "dark": True},
        {"store": "not json", "dark": False},
        {"store": "throw", "dark": True},
        {"store": None, "dark": "throw"},
    ]
    out = subprocess.run(
        [node, str(tmp_path / "probe.js"), json.dumps(cases), str(tmp_path / "theme.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["light", "dark", "dark", "light", "dark", "light", "dark", "dark"]
