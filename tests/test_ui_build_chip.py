"""TD-547: the build chip's browser half (design §4.5a top bar **build** chip, TD-539). The server
renders `data-at`/`data-rest` (`test_ui_promote.py`); `app.js` reprints *live <MM-DD HH:MM><rest>* in
the browser's zone at load, the year in front only when it is not this one, and again from each Inbox
poll's `build_chip`, so a merge shows without a reload. Run in node against a stub `#buildchip`."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const year = new Date().getFullYear();
// as the server renders it: the sentence in the host's zone, the instant in `data-at`
const chip = { ...el(), className: "mono", title: "", textContent: "live 10-10 15:41 · main +2",
  dataset: { at: `${year}-10-10T15:41:00Z`, rest: " · main +2" } };
chip.appendChild = (a) => { chip.appended = a; };
const document = { documentElement: el(), body: el(), addEventListener: noop, createElement: el,
  querySelector: (s) => (s === "#buildchip" ? chip : null), querySelectorAll: () => [] };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("no calls at load"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const seen = () => ({ text: chip.textContent, cls: chip.className, title: chip.title, at: chip.dataset.at,
  rest: chip.dataset.rest });
const poll = async (build_chip) => {
  chip.appended = undefined;
  global.fetch = async () => ({ ok: true, json: async () => ({ needs: 0, build_chip }) });
  await AO.refreshInboxCount();
  return seen();
};
(async () => {
  const out = { load: seen() };
  out.lastYear = await poll({ cls: "behind", title: "a\\nb", at: `${year - 1}-03-04T05:06:00Z`, rest: " · main +1" });
  out.noAt = await poll({ cls: "", title: "host agent: build unknown", text: "build unknown" });
  out.noChip = await poll(undefined);
  out.thisYear = await poll({ cls: "", title: "t", at: `${year}-12-31T23:59:00Z`, rest: "" });
  const linked = await poll({ cls: "behind", title: "t", at: `${year}-12-31T23:59:00Z`, rest: " · main +2",
    link: "main +2", href: "/inbox#promote-shiftlead" });
  out.linked = { ...linked, href: chip.dataset.href, a: chip.appended && { href: chip.appended.href,
    text: chip.appended.textContent } };
  const unlinked = await poll({ cls: "", title: "t", at: `${year}-12-31T23:59:00Z`, rest: "" });
  out.unlinked = { ...unlinked, href: chip.dataset.href, a: chip.appended };
  console.log(JSON.stringify({ year, ...out }));
})();
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the build chip's reprint is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "build_chip_probe.js"
    probe.write_text(PROBE)
    env = {**os.environ, "TZ": "America/New_York"}  # the browser's zone, never the host's UTC
    out = subprocess.run(
        [node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30, env=env
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_load_reprints_the_servers_sentence_in_the_browsers_zone_without_the_year():
    got = _probe()
    # 15:41Z on 10-10 is 11:41 in New York (EDT); this year's stamp carries no year
    assert got["load"]["text"] == "live 10-10 11:41 · main +2"


def test_each_inbox_poll_redraws_the_chip_with_the_year_only_when_it_is_not_this_one():
    got = _probe()
    y = got["year"]
    assert got["lastYear"] == {
        "text": f"live {y - 1}-03-04 00:06 · main +1",  # 05:06Z is 00:06 EST: the year in front
        "cls": "mono behind",
        "title": "a\nb",
        "at": f"{y - 1}-03-04T05:06:00Z",
        "rest": " · main +1",
    }
    # 23:59Z on 12-31 is 18:59 in New York, still this year
    assert got["thisYear"]["text"] == "live 12-31 18:59"


def test_a_chip_with_no_instant_keeps_its_text_and_a_poll_with_no_chip_changes_nothing():
    got = _probe()
    assert got["noAt"] == {"text": "build unknown", "cls": "mono ", "title": "host agent: build unknown"}
    assert got["noChip"] == got["noAt"]  # the agent did not answer: the chip keeps what it showed


def test_main_ahead_is_drawn_as_a_link_to_the_inbox_row_and_dropped_when_live_catches_up():
    """TD-581: *main +n* is the chip's one pressable part, a link to `/inbox#promote-<repo>`; the
    sentence before it stays text, and a later poll with no link draws plain text again."""
    got = _probe()
    assert got["linked"]["text"] == "live 12-31 18:59 · " and got["linked"]["href"] == "/inbox#promote-shiftlead"
    assert got["linked"]["a"] == {"href": "/inbox#promote-shiftlead", "text": "main +2"}
    assert got["unlinked"]["text"] == "live 12-31 18:59" and "href" not in got["unlinked"]
    assert "a" not in got["unlinked"]
