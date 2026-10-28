"""TD-1155, design §4.5 *A tab's icon* (TD-1150) and §4.5a **tab icon**: every page that extends
`base.html` links its own tile, Focus its state's with every state's URL in `data-icons`; the twenty
files under `static/icons/` are tiles of the colours `app.css` names, drawn as paths; and they are
served as `app.css` is, hashed and kept."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import scratch_dir
from test_ui import client  # noqa: F401 — the fixture, by name
from test_ui_build_chip_pages import PAGES
from test_ui_entry import client as entry_client
from test_ui_entry import fake, world
from test_ui_inbox import send, sender_session

from shiftlead.ui import cards
from shiftlead.ui.common import static_url

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui"
ICONS = UI / "static" / "icons"

# the Fix's map, written out: each template's icon (Focus's is its state's, read below)
ICON = {
    "org.html": "page-sessions",
    "inbox.html": "page-inbox",
    "inbox_entry.html": "page-inbox",
    "queue.html": "page-queue",
    "repo.html": "page-repo",
    "settings.html": "page-settings",
    "help.html": "page-help",
    "spend.html": "page-spend",
    "new.html": "page-new",
    "transcript.html": "page-transcript",
    "focus.html": "state-",
}
ENDED = {"scheduled", "exited", "closed", "oncall", "unreachable"}
LINK = re.compile(
    r'<link rel="icon" type="image/svg\+xml" href="(/static/icons/([a-z-]+)\.svg\?v=[0-9a-f]{12})"([^>]*)>'
)


def light_tokens() -> dict[str, str]:
    css = (UI / "static" / "app.css").read_text()
    block = css[css.index(":root") :]
    block = block[: block.index("}")]
    return dict(re.findall(r"--([a-z-]+):\s*([^;]+);", block))


def tile(name: str) -> tuple[str, str]:
    """A file's tile: its first rect's fill and stroke."""
    m = re.search(
        r'<rect x="\.5" y="\.5" width="15" height="15" rx="3\.5" fill="([^"]+)" stroke="([^"]+)"',
        (ICONS / f"{name}.svg").read_text(),
    )
    assert m, name
    return m.group(1), m.group(2)


def icon_of(html: str) -> tuple[str, str, str]:
    (got,) = LINK.findall(html)
    return got


@pytest.mark.unit
def test_the_map_names_every_page_and_each_page_file_exists():
    assert set(ICON) == set(PAGES)
    pages = {p.stem for p in ICONS.glob("page-*.svg")}
    assert pages == {v for v in ICON.values() if v.startswith("page-")}


@pytest.mark.unit
def test_the_state_classes_are_the_state_files():
    assert {p.stem.removeprefix("state-") for p in ICONS.glob("state-*.svg")} == cards.STATE_ICON_CLASSES
    assert len(cards.STATE_ICON_CLASSES) == 11 and {"needs", "stalled", "oncall", "waiting"} <= cards.STATE_ICON_CLASSES
    assert set(cards.state_icons()) == cards.STATE_ICON_CLASSES


@pytest.mark.unit
def test_each_tile_is_its_tokens_colour_and_no_file_holds_text():
    tokens = light_tokens()
    for c in cards.STATE_ICON_CLASSES:
        assert tile(f"state-{c}") == (tokens["ended" if c in ENDED else c], "rgba(0,0,0,.18)"), c
    for p in ICONS.glob("page-*.svg"):
        assert tile(p.stem) == (tokens["top"], tokens["muted"]), p.stem
    for p in ICONS.glob("*.svg"):
        body = p.read_text()
        assert 'viewBox="0 0 16 16"' in body and "<text" not in body, p.name


@pytest.mark.integration
def test_every_page_links_its_own_icon_and_focus_its_states(client, tmp_path, monkeypatch):  # noqa: F811
    sid = sender_session(client, tmp_path, name="icons")
    mid = send(sid, text="merge #9?", kind="ask")["id"]
    try:
        for template, path in PAGES.items():
            if template == "repo.html":
                continue  # a registered repo: the next test
            got = client.get(path.format(sid=sid, mid=mid))
            assert got.status_code == 200, path
            url, name, attrs = icon_of(got.text)
            assert url == static_url(f"icons/{name}.svg"), path
            if template != "focus.html":
                assert name == ICON[template] and not attrs, path
                continue
            assert name.startswith("state-") and name.removeprefix("state-") in cards.STATE_ICON_CLASSES
            icons = re.search(r"data-icons='([^']+)'", attrs)
            assert icons and set(json.loads(icons.group(1))) == cards.STATE_ICON_CLASSES
    finally:
        client.post(f"/api/sessions/{sid}/kill")


@pytest.mark.unit
def test_the_repo_page_links_its_icon(tmp_path, monkeypatch):
    repo = world(tmp_path)
    root = str(repo)
    reading = {"name": "samscrape", "root": root, "ledger": {"path": "docs/technical_debt.md", "entries": []}}

    class Fake(fake([])):
        async def call(self, method, **kw):
            if method == "repos":
                return {root: reading}
            return await super().call(method, **kw)

    got = entry_client(monkeypatch, tmp_path, Fake).get(PAGES["repo.html"])
    assert got.status_code == 200 and icon_of(got.text)[1] == "page-repo"


@pytest.mark.unit
def test_an_icon_is_served_as_svg_and_kept(tmp_path, monkeypatch):
    world(tmp_path)
    c = entry_client(monkeypatch, tmp_path, fake([]))
    got = c.get(static_url("icons/state-working.svg"))
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/svg+xml")
    assert got.headers["cache-control"] == "public, max-age=31536000, immutable"


PROBE = """
const fs = require("fs");
const noop = () => {};
const el = (o) => Object.assign({
  dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [], contains: () => false,
}, o);
const icons = process.argv[3];
const link = el({ href: "/static/icons/state-idle.svg?v=1", dataset: icons === "-" ? {} : { icons } });
const document = { documentElement: el(), body: el(), addEventListener: noop, createElement: () => el(),
  querySelector: (s) => (s === "link[rel=icon]" ? link : null), querySelectorAll: () => [] };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO, out = [];
for (const c of ["working", "nosuch", "exited"]) { AO.focusIcon({ state_class: c }); out.push(link.href); }
link.dataset.icons = JSON.stringify({ working: "/changed" });  // read once: a later change is not read
AO.focusIcon({ state_class: "working" }); out.push(link.href);
console.log(JSON.stringify(out));
"""


def probe(icons: str) -> list[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    f = scratch_dir() / "tab_icon_probe.js"
    f.write_text(PROBE)
    out = subprocess.run(
        [node, str(f), str(UI / "static" / "app.js"), icons], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_focus_icon_follows_the_state_and_leaves_what_it_cannot_name():
    """`AO.focusIcon`: a class with a URL sets the link's `href`, one without leaves it; `data-icons`
    is read once; a missing or unreadable `data-icons` leaves the icon as it is."""
    urls = {"working": "/w.svg", "exited": "/x.svg"}
    assert probe(json.dumps(urls)) == ["/w.svg", "/w.svg", "/x.svg", "/w.svg"]
    first = "/static/icons/state-idle.svg?v=1"
    assert probe("-") == [first, first, first, first]  # read once, missing: never read again
    assert probe("{not json") == [first, first, first, first]
