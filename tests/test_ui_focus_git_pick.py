"""The Focus Git card's **pick** (design §4.5a *Focus side panel, Git card: the pick · ↑ · ↓*, §4.2 *The Git
card's pick*, TD-856, built by TD-862): a select of Working tree, the newest ten commits and Session, ↑ and ↓
stepping it and disabled at its ends; a commit drawn with its naming line and its lines, Session with *n more*;
a `D` and a `gone` path text with why on hover; a held commit relabelled on a new one and back to Working tree
once it leaves the ten; a failed read said in place of the lines. The page's functions run as themselves under
node, and the route hands the pick to the host agent's `git_files` read."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest
from fastapi.testclient import TestClient


def S(n: int) -> str:
    """The probe's fake sha of commit `n`."""
    return chr(97 + n) * 40


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
const sha = (n) => String.fromCharCode(97 + n).repeat(40);  // a, b, … — never two alike
const commits = (from) => Array.from({ length: 10 }, (_, i) => ({
  ref: i ? `HEAD~${i}` : "HEAD", sha: sha(from + i), subject: `subject ${from + i} ` + "x".repeat(i === 1 ? 50 : 0),
  at: "2026-10-17T10:00:00Z", author: "Tess" }));
// a fake card: elements that keep what the glue writes, and listeners the probe presses
const node = () => { const h = {}; return { innerHTML: "", value: "", disabled: false, h,
  classList: { hidden: false, toggle(_, on) { this.hidden = !!on; } }, addEventListener: (k, f) => { h[k] = f; } }; };
const els = { sel: node(), up: node(), down: node(), line: node(), files: node() };
let answers = [], asked = [];
const read = (pick) => {
  asked.push(pick);
  const a = answers.shift();
  return a instanceof Error ? Promise.reject(a) : Promise.resolve(a);
};
const tick = () => new Promise((r) => setImmediate(r));
const snap = () => ({ pick: card.state.pick, sel: els.sel.innerHTML, up: els.up.disabled, down: els.down.disabled,
  line: els.line.innerHTML, lineHidden: els.line.classList.hidden, files: els.files.innerHTML, asked: [...asked] });
const v = (oid, files) => ({ dir: "/w/wt", git: { oid, files } });
let card;
(async () => {
  const out = {};
  out.options = AO.gitPickOptions(commits(1), sha(2));
  out.steps = [AO.gitPickStep(commits(1), "tree", -1), AO.gitPickStep(commits(1), "tree", 1),
    AO.gitPickStep(commits(1), sha(1), 1), AO.gitPickStep(commits(1), "session", 1),
    AO.gitPickStep(commits(1), "session", -1)];
  out.held = [AO.gitPickHeld(commits(1), sha(3)), AO.gitPickHeld(commits(2), sha(1)),
    AO.gitPickHeld(commits(1), "session")];
  const answer = { files: [{ code: "M", path: "src/a b.py" }, { code: "A", path: "new.py" },
    { code: "D", path: "old.py" },
    { code: "R", path: "moved.py", gone: true }] };
  out.commitLines = AO.gitPickLines(answer, sha(2), editor, "/w/wt");
  out.sessionLines = AO.gitPickLines({ ...answer, more: 7 }, "session", editor, "/w/wt");
  out.textLines = AO.gitPickLines(answer, sha(2), null, "/w/wt");

  card = AO.gitPick(els, read);
  answers.push({ commits: commits(1), files: [] });
  card.update(v("o1", ["M a.py"]), editor, "/w/wt"); await tick();
  out.load = snap();
  answers.push({ commits: commits(1), files: answer.files });
  els.down.h.click(); await tick();
  out.head = snap();
  answers.push({ commits: commits(1), files: answer.files });
  els.down.h.click(); await tick();
  out.head1 = snap();
  // a new commit: the commits are read again, the held sha relabelled HEAD~2 and its lines kept
  answers.push({ commits: commits(0), files: answer.files });
  card.update(v("o2", ["M a.py"]), editor, "/w/wt"); await tick();
  out.relabelled = snap();
  // the sha leaves the ten: the host refuses it, and the card goes back to Working tree, drawn from the
  // record, with the commits read again
  answers.push(new Error("git_files: not among the last ten commits"));
  answers.push({ commits: commits(5), files: [] });
  card.update(v("o3", ["M a.py"]), editor, "/w/wt"); await tick(); await tick();
  out.gone = snap();
  // Session, at the bottom: ↓ disabled; read again when the porcelain changes; a failed read said
  els.sel.value = "session";
  answers.push({ commits: commits(5), files: [{ code: "??", path: "n.txt" }], more: 0 });
  els.sel.h.change(); await tick();
  out.session = snap();
  answers.push(new Error("git_files: git read failed"));
  card.update(v("o3", ["M a.py", "?? n.txt"]), editor, "/w/wt"); await tick();
  out.failed = snap();
  console.log(JSON.stringify(out));
})();
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the Git card's pick is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "git_pick_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _options(html: str) -> list[str]:
    return re.findall(r"<option[^>]*>(.*?)</option>", html)


@pytest.fixture(scope="module")
def got():
    return _probe()


@pytest.mark.unit
def test_the_select_lists_working_tree_the_ten_by_gits_names_and_session(got):
    opts = _options(got["options"])
    assert opts[0] == "Working tree" and opts[-1] == "Session" and len(opts) == 12
    assert opts[1] == "HEAD · " + S(1)[:7] + " · subject 1 " and opts[10].startswith("HEAD~9 · ")
    # the subject cut at forty, whole on hover; the held pick selected
    assert opts[2] == "HEAD~1 · " + S(2)[:7] + " · " + ("subject 2 " + "x" * 50)[:40] + "…"
    assert f'value="{S(2)}" selected title="subject 2 {"x" * 50}"' in got["options"]


@pytest.mark.unit
def test_up_and_down_step_the_pick_and_stop_at_its_ends(got):
    assert got["steps"] == ["tree", S(1), S(2), "session", S(10)]
    assert got["held"] == [S(3), "tree", "session"]


@pytest.mark.unit
def test_a_commits_lines_link_their_paths_and_a_d_and_a_gone_path_are_text(got):
    rows = re.findall(r"<div>(.*?)</div>", got["commitLines"])
    assert rows[0].startswith('M <a class="editor" href="vscode://file/w/wt/src/a%20b.py:1"')
    assert rows[1].startswith("A <a ")
    assert rows[2] == 'D <span title="deleted by this commit">old.py</span>'
    assert rows[3] == 'R <span title="not in the worktree now">moved.py</span>'
    assert 'D <span title="deleted since the base">old.py</span>' in got["sessionLines"]
    assert got["sessionLines"].endswith('<div class="muted">7 more</div>')
    assert "<a " not in got["textLines"]


@pytest.mark.unit
def test_the_card_opens_on_working_tree_with_up_disabled(got):
    load = got["load"]
    assert load["pick"] == "tree" and load["up"] is True and load["down"] is False
    assert load["asked"] == ["tree"] and load["lineHidden"] is True
    assert "a.py" in load["files"] and len(_options(load["sel"])) == 12


@pytest.mark.unit
def test_a_pick_of_head_1_draws_its_naming_line_and_its_lines(got):
    head1 = got["head1"]
    assert head1["pick"] == S(2) and head1["asked"] == ["tree", S(1), S(2)]
    assert head1["up"] is False and head1["down"] is False and head1["lineHidden"] is False
    assert (
        '<span title="subject 2 ' in head1["line"]
        and "— Tess" in head1["line"]
        and S(2)[:7] + " · subject 2" in head1["line"]
    )
    assert "deleted by this commit" in head1["files"]


@pytest.mark.unit
def test_a_new_commit_relabels_a_held_pick_and_a_sha_gone_from_the_ten_returns_to_working_tree(got):
    rel = got["relabelled"]
    assert rel["pick"] == S(2) and f'value="{S(2)}" selected' in rel["sel"]
    assert "HEAD~2 · " + S(2)[:7] in rel["sel"] and "deleted by this commit" in rel["files"]
    gone = got["gone"]
    assert gone["pick"] == "tree" and gone["lineHidden"] is True and "a.py" in gone["files"] and gone["up"] is True
    assert gone["asked"][-2:] == [S(2), "tree"] and S(7) in gone["sel"] and S(2) not in gone["sel"]


@pytest.mark.unit
def test_session_is_the_bottom_read_again_on_the_porcelain_and_a_failed_read_is_said(got):
    s = got["session"]
    assert s["pick"] == "session" and s["down"] is True and "n.txt" in s["files"]
    f = got["failed"]
    assert f["pick"] == "session" and f["asked"][-1] == "session"
    assert f["files"] == '<div class="muted">could not read: git read failed</div>'


@pytest.mark.unit
def test_focus_draws_the_pick_and_reads_through_the_route():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    assert "/git_files?pick=${encodeURIComponent(pick)}" in focus
    assert "if (gitPick) gitPick.update(v, s.editor, s.git_root);" in focus
    html = (UI / "templates" / "focus.html").read_text()
    for want in ('id="gitup" title="newer"', 'id="gitdown" title="older"', 'id="gitpicksel"', 'id="gitpickline"'):
        assert want in html


@pytest.mark.unit
def test_the_route_hands_the_pick_to_the_git_files_read(monkeypatch):
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
            if method == "git_files" and kw["pick"] == "x":
                raise ui.AgentError("git_files: pick is tree, session or a sha of the last ten commits, not 'x'")
            return {"commits": [], "files": []} if method == "git_files" else {}

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    r = c.get("/api/sessions/ao-x-1/git_files?pick=session")
    assert r.status_code == 200 and r.json() == {"commits": [], "files": []}
    assert ("git_files", {"id": "ao-x-1", "pick": "session"}) in asked
    r = c.get("/api/sessions/ao-x-1/git_files?pick=x")
    assert r.status_code == 400 and "pick is tree, session" in r.text
