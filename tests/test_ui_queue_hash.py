"""`/queue#TD-n` widened (design §4.5 screen 12 *Addresses*, TD-1762): the Queue's own *where is TD-n* rings what it
opens, falls back to the Recently completed line that lists the entry (widening the window to *month* for that draw),
and failing that reads the Queue once with `find=<id>` for the find's note and its Repo link."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_ui_queue import client, fake, queue

JS = Path(__file__).resolve().parents[1] / "src/shiftlead/ui/static/app.js"


def _lines(html: str) -> dict[str, str]:
    done = html[html.index('id="qcompleted"') : html.index('id="qinprogress"')]
    return dict(re.findall(r'data-key="([^"]+)" data-ids="([^"]*)"', done))


def test_each_completed_line_carries_its_entries_ids(tmp_path, monkeypatch):
    # a card's line its entries' ids, an open card's archived row its own: what the hash's fallback matches
    day = _lines(client(monkeypatch, tmp_path, fake(queue())).get("/queue").text)
    assert day == {"row:TD-9": "s#TD-9", "card:TD-1": "s#TD-2 s#TD-1"}
    # the hash's one read (`win=month`, `find=<id>`) carries a line past the day, and the find's note for an id
    # past the month, with its Repo link
    part = client(monkeypatch, tmp_path, fake(queue())).get("/queue?part=1&win=month&find=TD-4").text
    assert _lines(part)["card:TD-4"] == "s#TD-4"
    gone = client(monkeypatch, tmp_path, fake(queue())).get("/queue?part=1&win=month&find=TD-6").text
    assert "card:TD-6" not in _lines(gone)
    assert 'id="qfindmiss"' in gone and 'href="/repo/s#TD-006"' in gone


PROBE = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const AO = {};
for (const name of ["AO.qRefs = ", "AO.qIdsHave = "]) {
  const s = src.indexOf(name), e = src.indexOf("\\n  };\\n", s);
  eval(src.slice(s, e + 5));
}
const h = AO.qIdsHave;
console.log(JSON.stringify([
  h("s#TD-2 s#TD-1", "TD-1"), h("s#TD-009", "TD-9"), h("s#TD-9", "s#TD-009"), h("s#TD-9", "db#TD-9"),
  h("s#TD-19", "TD-1"), h("", "TD-1"), h("loose:x", "loose:x"),
]));
"""


def test_a_line_matches_the_hash_by_its_refs(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = tmp_path / "hash_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(JS)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    # a bare id any repo's, zero-padded either way; a repo's id that repo's alone; never a longer number
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [True, True, True, False, False, False, True]


def _show() -> str:
    js = JS.read_text()
    body = js[js.index("    function showHash() {") :]
    return body[: body.index("\n    }\n")]


def test_the_hash_rings_what_it_opens_then_falls_back_in_order():
    show = _show()
    # an open card or row first, ringed (the ring new with TD-1762), the picks hiding it dropped
    assert "const el = onCard(id);" in show and 'hidden(el, ""); reveal(el, true);' in show
    # then the completed line, then the one read
    assert show.index("onCard(id)") < show.index("lineFor(lists, id)") < show.index("findHash(id)")
    # a loose id is matched whole and, finding none, ends on the plain /queue: no archive ask
    loose = show[show.index('id.startsWith("loose:")') : show.index("const el = onCard(id);")]
    assert 'data-card="${CSS.escape(id)}"' in loose and "location.pathname + location.search" in loose
    assert "findHash" not in loose and "return;" in loose


def test_the_completed_line_widens_the_window_for_one_apply_and_opens():
    js = JS.read_text()
    line = js[js.index("    function showLine(ln) {") :]
    line = line[: line.index("\n    }\n")]
    assert 'winOnce = wide ? "month" : "";' in line and 'finally { winOnce = ""; }' in line
    assert 'hidden(ln, "")' in line and "openLine(ln)" in line and "reveal(ln, true)" in line
    # apply() reads the held window before the remembered one, and never writes it
    assert 'const win = winOnce || store.get("qwin", "day");' in js
    # an archived row's ✓ n done fold opens on the way to it
    rev = js[js.index("    function reveal(el, ring) {") :]
    assert 'el.closest("details.qfold")' in rev[: rev.index("\n    }\n")]


def test_the_hash_reads_the_queue_once_per_address_with_the_picks_untouched():
    js = JS.read_text()
    find = js[js.index("    async function findHash(id) {") :]
    find = find[: find.index("\n    }\n")]
    assert find.index("if (asked.has(id)) return;") < find.index("asked.add(id);") < find.index("await fetch(")
    # its own query, never location.search: the person's picks stay as they are
    assert 'new URLSearchParams({ part: "1", win: "month", find: id })' in find and "location.search" not in find
    # a line past the window held is drawn in and shown; else the find's note, outside the lists a re-read draws
    assert find.index("drawWindow(fresh)") < find.index("showLine(ln)") < find.index('$("#qfindmiss", fresh)')
    assert 'n.id = "qhashmiss"' in find and "hashMiss(n)" in find
    assert "lists.before(note)" in js
