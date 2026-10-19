"""TD-227 (the review of #824): the Inbox's team start row links an entry as `/repo/<name>#TD-n`, and
the Repo page folds each Technical debt list past its fourth row. A folded row is `display: none`,
which a browser cannot scroll to, so the page unfolds the list its hash names. The hash's reading is
JavaScript, run as itself under node; the wiring is read from the source and the template."""

import json
import pathlib
import shutil
import subprocess
import tempfile

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
JS = UI / "static" / "app.js"

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
const h = window.AO.hashId;
console.log(JSON.stringify([h("#TD-227"), h(""), h("#"), h(undefined), h("#a%20b"), h("#%E0%A4%A")]));
"""


@pytest.mark.unit
def test_the_hash_names_an_id_or_nothing():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "hash_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(JS)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    # a hash that does not decode names nothing, and never throws on the page's first run
    assert json.loads(out.stdout) == ["TD-227", "", "", "", "a b", ""]


@pytest.mark.unit
def test_the_repo_page_unfolds_the_list_its_hash_names():
    js = JS.read_text()
    start = js.index("AO.repo = function ()")
    body = js[start : js.index("\n  };\n", start)]
    show = body[body.index("function showHash()") :]
    show = show[: show.index("\n    }\n")]
    # only a ledger row of this page (it carries its list), unfolded before it is scrolled to
    assert "box.contains(row)" in show and "row.dataset.list" in show
    assert show.index("unfold(row.dataset.list)") < show.index("row.scrollIntoView(")
    assert show.index("fold.open = true") < show.index("row.scrollIntoView(")  # the board's no-lane fold (TD-903)
    # on the first draw, and when a link on the page itself changes the hash
    assert body.index("showHash();") < body.index("setInterval(reread")
    assert 'window.addEventListener("hashchange", showHash)' in body
    # the unfolding is the *+n more* press's own, so a re-read keeps it (`opened`, sent whole by `open`)
    assert "opened.forEach((k) => unfold(k, true))" in body
    # a row past its list's fold was not sent (TD-882): the lists' read asks for it by its id, once, then lands
    assert show.index("sought.add(id); want = id; return reread();") < show.index("box.contains(row)")
    assert 'if (ask.length) q.set("open", ask.join(","));' in body
    assert 'if (asked && want === asked) { want = ""; showHash(); }' in body
    # …and the board's row is the Queue card's row partial, which carries the id the link names (TD-903)
    part = (UI / "templates" / "repo_part.html").read_text()
    assert '{% from "queue_row.html" import row as qrow %}' in part
    assert '{% if r.anchor %} id="{{ r.anchor }}"{% endif %}' in (UI / "templates" / "queue_row.html").read_text()
    assert 'href="/repo/{{ e.repo }}#{{ i }}"' in (UI / "templates" / "inbox_row.html").read_text()


def test_an_anchor_to_a_row_past_the_fold_fetches_its_list(tmp_path, monkeypatch):
    """TD-882, §4.5 *Page loads*: `/repo/<name>#TD-n` for a row past the seventh queued of its column (TD-903) —
    not sent at load — is read by the lists' `open=TD-n`, which sends that column whole, and the row is there."""
    from test_ui_repo_page import client, fake, reading

    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["ledger"]["entries"] = [
        {"id": f"TD-{700 + i}", "title": f"open {i}", "for_page": "pickable", "priority": "medium", "owner": "grinder"}
        for i in range(9)
    ]
    c = client(monkeypatch, tmp_path, fake({root: r}, []))
    html = c.get("/repo/samscrape").text
    assert 'id="TD-706"' in html and 'id="TD-707"' not in html and "+2 more up next" in html
    part = c.get("/repo/samscrape?part=1&open=TD-708").text
    assert 'id="TD-708"' in part and "more up next" not in part
    # an id in no column opens nothing
    assert 'id="TD-708"' not in c.get("/repo/samscrape?part=1&open=TD-999").text
