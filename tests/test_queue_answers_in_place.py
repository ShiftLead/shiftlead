"""TD-1808, design §4.5 screen 12 *An item is answered where it is read* (TD-1801); §4.5a *Queue card: Its own page*.
On the Queue every card is drawn as the card's page draws it, one renderer for both: each item its whole sentence and
every control *Three verbs* names, a stopped holder's **Allow / Deny** with its *why?* box, each row's **⋯**, the
header's **Start session** and **⋯**, then **Its own page**, a quiet link to the card's page. TD-1763's previews,
**Open card ›** and **Answer on its card ›** are gone. The page still holds still (TD-1558): a box opened on a card
holds that card alone, a refused press ends it, and a reason typed in *why?* survives every patch and whole draw on
the Queue and on the card's page.

The pure helpers run under node on `test_ui_press_draw`'s small DOM; the pages' wiring is pinned by its source, as
`test_ui_holds_still.py` pins it."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from markupsafe import Markup
from test_queue_kept_loose import hold, state
from test_queue_kept_loose import queue as loose_queue
from test_ui_press_draw import APP_JS, PROBE
from test_ui_queue import NOW, at, client, fake, ledger_repos, mail, queue

from shiftlead.ui.app import templates
from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import attach, card_index, queue_view

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
JS = APP_JS.read_text(encoding="utf-8")
Q = JS[JS.index("AO.queue = function") :]
Q = Q[: Q.index("AO.REPO_WINDOWS")]
CP = JS[JS.index("AO.cardPage = function") :]
CP = CP[: CP.index("connectEvents(")]
GONE = ("Open card ›", "Answer on its card ›", "qpreview", "qpline", "qopencard")


def _page(tmp_path, monkeypatch, path: str = "/queue", items: bool = True) -> str:
    q = queue()
    for c in q["cards"]:
        c["start"] = c["id"]  # each card's start entry, so the Start session buttons are drawn
    asks = [mail("m1", "TD-21: which one?", answers=["a", "b"])] if items else []
    return client(monkeypatch, tmp_path, fake(q, asks, ledger_repos() if items else None)).get(path).text


def _card(html: str, cid: str, end: str | None) -> str:
    i = html.index(f'data-card="{cid}"')
    return html[i : html.index(f'data-card="{end}"', i)] if end else html[i:]


# -- every control on the Queue, as on the card's page ----------------------------------------------------------


def test_the_queue_draws_every_item_whole_with_every_control_and_no_preview(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    card20 = _card(html, "s#TD-20", "s#TD-30")
    for gone in GONE:
        assert gone not in html, gone
    # the ask on TD-21: its whole sentence, both answers, Answer…, its own Start session and its ⋯
    assert "which one?" in card20 and ">Answer…</button>" in card20
    assert card20.count('class="btn sm answer') >= 2  # its Start session: test_queue_start.py, on the Queue again
    # the ledger's items: Done and Lift the hold, which the previews had left to the card's page
    assert ">Lift the hold</button>" in html and 'data-words="done"' in html
    # the header's ⋯ on the top entry, and each row's
    head = card20[: card20.index('class="qgap"')]
    assert 'class="more qdots"' in head and 'href="/repo/s#TD-20" role="menuitem"' in head
    assert card20.count('class="more qdots"') >= 3  # the header's, the item's and the row's


def test_the_header_draws_start_session_and_its_dots_then_its_own_page(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch, items=False)
    # a card with no item draws Start session in its header, then ⋯, then Its own page
    head = _card(html, "s#TD-30", None)
    head = head[: head.index('class="qgap"')]
    assert head.index(">Start session</button>") < head.index('class="more qdots"') < head.index("Its own page")
    own = re.search(r'<a class="qownpage" href="([^"]+)" data-cardhref title="([^"]+)">Its own page</a>', head)
    assert own and own.group(1) == "/card/s%23TD-30"
    assert own.group(2).startswith("Opens this card alone on a page of its own")
    # every Queue card draws it, once, in its header
    assert html.count(">Its own page</a>") == html.count('<div class="qhead"')


def test_the_part_the_queue_rereads_draws_the_same(tmp_path, monkeypatch):
    part = _page(tmp_path, monkeypatch, "/queue?part=1")
    assert "Its own page" in part and ">Answer…</button>" in part and "qdots" in part
    for gone in GONE:
        assert gone not in part, gone


def test_the_cards_page_draws_every_control_and_its_own_page(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch, "/card/s%23TD-20")
    assert ">Answer…</button>" in page and "qdots" in page and ">Lift the hold</button>" in page
    # the header draws Its own page on the card's page too, as on the Queue (§4.5a *Queue card: Its own page*)
    assert '<a class="qownpage" href="/card/s%23TD-20" data-cardhref' in page
    for gone in GONE:
        assert gone not in page, gone


def test_one_renderer_draws_both_pages():
    # no preview mode is left anywhere it sat: the item renderer, the card, the rows and the Queue's read
    row = (UI / "templates" / "inbox_row.html").read_text()
    for gone in ("queue_preview", "preview_sentence", "one=True", "one=False", "qpans"):
        assert gone not in row, gone
    for name in ("queue_card.html", "queue_row.html", "queue_part.html", "queue_mail.html"):
        assert "preview" not in (UI / "templates" / name).read_text(), name
    app = (UI / "app.py").read_text()
    assert "async def queue_read(request: Request) -> SimpleNamespace:" in app and "preview=" not in app
    assert '"addr"' not in (UI / "queue.py").read_text()
    css = (UI / "static" / "app.css").read_text()
    assert not re.search(r"\.qp(line|sent|ans|card|review)\b", css) and ".qownpage" in css


# -- a stopped holder's Allow / Deny with its why? on the Queue ------------------------------------------------


def _drawn(e: dict, drawn_as: str) -> Markup:
    """The renderer the Queue's read hands `attach`, as `app.queue_read` does."""
    return Markup(templates.get_template("queue_mail.html").render(e=e, section=drawn_as, origin="", board_choices={}))


def test_allow_and_deny_with_its_why_box_are_drawn_on_the_queue_card():
    q = {**loose_queue(), "holds": [hold("g1", "s#TD-21", at(1))]}
    perm = state("g1", "permission", call="t1", deadline="", left="2 min")
    secs = inbox_sections([], now=NOW, states=[perm], cards=card_index(q))
    v = queue_view(q, NOW, attach(secs, _drawn, start=lambda c, i: {"item": i} if i else {}))
    (c,) = [c for c in v["up_next"] if c["id"] == "s#TD-20"]
    html = templates.env.from_string('{% from "queue_card.html" import card %}{{ card(c) }}').render(c=c)
    deny = html.index('data-act="deny" data-id="g1" data-call="t1"')
    assert html.index('data-act="allow" data-id="g1" data-call="t1"') < deny
    why = html.index('<input class="denywhy"', deny)
    assert why - deny < 200, "the why? box sits beside Deny"
    assert 'class="denywhy" type="text" maxlength="200" data-id="g1" data-call="t1"' in html
    # the Deny press reads the box beside it, as on the card's page and the Inbox
    assert (
        'const w = b.parentElement && b.parentElement.querySelector("input.denywhy"); body = AO.denyBody(w && w.value);'
        in JS
    )


# -- a press on an item's sentence --------------------------------------------------------------------------------


def _sentence_press(src: str) -> str:
    i = src.index('const link = e.target.closest(".mailrow a.pagelink");')
    return src[i : src.index("AO.openEntry(", i)]


def test_a_press_on_an_items_sentence_does_on_the_queue_what_it_does_on_the_cards_page(tmp_path, monkeypatch):
    # the same handler on both pages: a mail item's sentence opens its message page, Back to the page it was read on
    assert _sentence_press(Q) == _sentence_press(CP)
    # and the Queue draws the item the card's page draws, its sentence the press's target
    q, p = _page(tmp_path, monkeypatch), _page(tmp_path, monkeypatch, "/card/s%23TD-20")
    item = 'class="mailrow" tabindex="0" data-page="/inbox/m1"'
    assert item in q and item in p
    one = lambda h: h[h.index(item) : h.index('class="st rowerr"', h.index(item))]  # noqa: E731
    assert one(q) == one(p)


# -- the page holds still under a box; a refused press ends the hold ---------------------------------------------


def test_a_box_open_on_one_card_holds_that_card_while_another_card_patches():
    # a press on a button inside a card names that card the box's; the hold is per card, read inside the patch's own
    # loop over the drawn cards, so every other card patches its values while this one waits
    assert "boxOn = id;" in Q and 'if (!document.querySelector("dialog[open]")) boxOn = "";' in Q
    h = Q[Q.index("function holds(el)") :]
    h = h[: h.index("\n    }\n")]
    assert 'if (id === boxOn && !!document.querySelector("dialog[open]")) return true;' in h
    p = Q[Q.index("function patch()") : Q.index("function patchLines()")]
    loop = p[p.index('$$(".qgroup .qcard[data-card]", lists).forEach((el) => {') :]
    loop = loop[: loop.index("});")]
    assert loop.index("if (holds(el))") < loop.index("patchCard(el, r,")
    assert 'el.dataset.waits = "1"; return;' in loop  # this card waits, the loop goes on to the next
    # a box's hold follows its card through a re-top, and a hidden page's draw keeps the boxed card's node
    assert "if (boxOn === from) boxOn = to;" in p
    w = Q[Q.index("function drawWhole(opts)") : Q.index("function slide(was)")]
    assert '(c.dataset.card === boxOn && !!document.querySelector("dialog[open]"))' in w


def test_a_refused_send_under_a_box_ends_its_cards_hold():
    h = Q[Q.index("function holds(el)") :]
    h = h[: h.index("\n    }\n")]
    # the refused card is let go before the box is read
    assert h.index("if (id && id === freed) return false;") < h.index("boxOn")
    r = Q[Q.index('document.addEventListener("ao:refused"') :]
    r = r[: r.index("});")]
    assert r.index("freed = id;") < r.index("patch();") < r.index('freed = ""')
    # on the card's page a refusal patches past the open box too
    cp = CP[CP.index("function patch()") :]
    assert "if (boxOpen() && !freed) return;" in cp[: cp.index("\n    }\n")]
    assert (
        'document.addEventListener("ao:refused", () => { freed = true; try { patch(); } finally { freed = false; } });'
        in CP
    )


def test_refresh_cannot_be_pressed_under_a_box_on_the_cards_page():
    assert "refreshBtn.disabled = boxOpen();" in CP
    assert "if (boxOpen()) return;  // Refresh cannot be pressed while a box is open" in CP


# -- a reason typed in why? survives every patch and whole draw ------------------------------------------------------


def test_the_queues_patches_and_whole_draws_keep_a_reason_typed_in_why():
    s = Q[Q.index("function swapIn(") :]
    s = s[: s.index("\n    }\n")]
    # every patch goes through swapIn: a whole card, a unit, a header part and a completed line
    assert "const whys = AO.denyWhys(el), n = from.cloneNode(true);" in s
    assert s.index("el.replaceWith(n);") < s.index("AO.restoreDenyWhys(n, whys);")
    pc = Q[Q.index("function patchCard(") : Q.index("function patch()")]
    assert ".replaceWith(" not in pc.replace("np.replaceWith(op)", "")  # no unit replaced around it
    # Refresh, a hidden page's draw and a back-forward return are drawWhole: the boxes read before, put back after
    w = Q[Q.index("function drawWhole(opts)") : Q.index("function slide(was)")]
    assert w.index("whys = AO.denyWhys(lists)") < w.index("lists.innerHTML = readingHtml;")
    assert w.index("lists.innerHTML = readingHtml;") < w.index("AO.restoreDenyWhys(lists, whys);")
    # …and before the focus is moved, so a box the person was in keeps its focus and its card's header does not take it
    assert w.index("AO.restoreDenyWhys(lists, whys);") < w.index("if (focusCard && !back)")
    assert "drawWhole({ slide: true });" in Q and "if (document.hidden || whole) drawWhole({ keepOpen: true });" in Q


def test_the_cards_pages_patch_and_whole_draw_keep_a_reason_typed_in_why():
    sw = CP[CP.index("function swap(el, from)") :]
    sw = sw[: sw.index("\n    }\n")]
    assert sw.index("AO.denyWhys(el)") < sw.index("el.replaceWith(n);") < sw.index("AO.restoreDenyWhys(n, whys);")
    p = CP[CP.index("function patch()") : CP.index("function boxLeft(")]
    assert ".replaceWith(" not in p  # every unit and header part goes through swap
    assert "swap(u, ru);" in p and "swap(a, b);" in p
    w = CP[CP.index("function drawWhole(back)") :]
    w = w[: w.index("\n    }\n")]
    assert w.index("whys = AO.denyWhys(lists)") < w.index("lists.innerHTML = readingHtml;")
    assert w.index("lists.innerHTML = readingHtml;") < w.index("AO.restoreDenyWhys(lists, whys);")


WHY_PROBE = r"""
global.CSS = { escape: (s) => s };
const out = {};
const box = (attrs, value) => {
  const i = h("input", "denywhy", attrs, []);
  i.value = value; i.focus = () => { document.activeElement = i; };
  return i;
};
// two permissions of one session (one call each), and a box with no call (the Focus header's, the card's): the
// reason is kept by the permission's call where the box carries one, else by the session
const a1 = box({ "data-id": "g1", "data-call": "t1" }, "not that file");
const a2 = box({ "data-id": "g1", "data-call": "t2" }, "");
const plain = box({ "data-id": "g9" }, "use the fixture");
document.activeElement = a2;  // the person is in the second box, nothing typed yet
const before = h("div", "", {}, [a1, a2, plain]);
const kept = AO.denyWhys(before);
document.activeElement = null;  // the draw took the focused node away
// the redraw: t2 first now, t1 still there, the plain box redrawn, and a new permission t3
const b1 = box({ "data-id": "g1", "data-call": "t2" }, ""), b2 = box({ "data-id": "g1", "data-call": "t1" }, "");
const b3 = box({ "data-id": "g1", "data-call": "t3" }, ""), b4 = box({ "data-id": "g9" }, "");
AO.restoreDenyWhys(h("div", "", {}, [b1, b2, b3, b4]), kept);
out.kept = kept;
out.after = [b1, b2, b3, b4].map((i) => [i.dataset.call || "", i.value, document.activeElement === i]);
// a permission the reading no longer holds is gone, and its words with it
const c1 = box({ "data-id": "g1", "data-call": "t4" }, "");
AO.restoreDenyWhys(h("div", "", {}, [c1]), { t1: { value: "not that file", focused: false } });
out.gone = c1.value;

// a gone item, and a done header, keep Its own page: the link is the header's, and neither mark takes it
El.prototype.prepend = function (n) { n.remove(); n.parentElement = this; this.children.unshift(n); };
const own = h("a", "qownpage", { href: "/card/A", "data-cardhref": "" }, []);
const dots = h("details", "more qdots", {}, []);
const right = h("span", "qright", {}, [dots, own]);
const head = h("div", "qhead", { "data-qid": "A" }, [h("div", "qmain", {}, [right])]);
const unit = h("div", "mailrow", { "data-msg": "m1" },
  [h("div", "row gap wrap sugg qanswers", {}, [h("button", "btn sm answer", {}, [])])]);
const card = h("div", "qcard", { "data-card": "A" }, [head, h("div", "qrows", {}, [unit])]);
AO.qGone(unit, true);
out.gone_unit = { marked: unit.classList.contains("qgone"), own: !!card.querySelector("a.qownpage"),
  word: (unit.querySelector(".qgonew") || {}).textContent };
// the probe's selectors have no `:scope >`: the header's own right edge is handed back for it
head.querySelector = (sel) => (sel.startsWith(":scope") ? right : El.prototype.querySelector.call(head, sel));
AO.qHeadDone(head, true);
out.done_head = { marked: head.classList.contains("qheaddone"), own: right.children.includes(own),
  word: right.children[0].textContent, href: own.getAttribute("href") };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    f = tmp_path_factory.mktemp("answers_in_place") / "answers_in_place_probe.js"
    f.write_text(PROBE.split("// ---- fixtures")[0] + WHY_PROBE)
    run = subprocess.run(["node", str(f), str(APP_JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_a_reason_is_kept_by_its_permissions_call_where_the_box_carries_one(probe):
    assert probe["kept"] == {
        "t1": {"value": "not that file", "focused": False},
        "t2": {"value": "", "focused": True},
        "g9": {"value": "use the fixture", "focused": False},
    }
    # each box gets its own words back wherever the redraw put it, the focused one its focus; a new one stays empty
    assert probe["after"] == [
        ["t2", "", True],
        ["t1", "not that file", False],
        ["t3", "", False],
        ["", "use the fixture", False],
    ]
    assert probe["gone"] == ""


def test_a_gone_item_and_a_done_header_keep_its_own_page(probe):
    assert probe["gone_unit"] == {"marked": True, "own": True, "word": "gone — refresh"}
    assert probe["done_head"] == {"marked": True, "own": True, "word": "done", "href": "/card/A"}
    # what *gone* and *done* hide is the controls, never a link
    css = (UI / "static" / "app.css").read_text()
    hide = [ln for ln in css.splitlines() if ln.startswith((".qgone ", ".qheaddone ")) and "visibility: hidden" in ln]
    assert len(hide) == 2 and not any(re.search(r"(^|[\s,>])a([\s,.{:\[]|$)", ln.split("{")[0]) for ln in hide)


# -- ‹ Queue from a card opened by Its own page -----------------------------------------------------------------------


def test_queue_back_from_a_card_opened_by_its_own_page_returns_to_it(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    head = _card(html, "s#TD-20", "s#TD-30")
    assert '<a class="qownpage" href="/card/s%23TD-20" data-cardhref' in head[: head.index('class="qgap"')]
    # a plain press on it writes the card and its screen place before the card's page opens in this tab
    click = Q[Q.index('const a = e.target.closest && e.target.closest("a[data-cardhref]");') :]
    click = click[: click.index("});")]
    assert "e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey" in click
    assert "AO.qSess.set(CARD_FROM, { card: c.dataset.card, group:" in click
    # the card's page goes back in history when that entry names it and the Queue opened it
    assert 'from.card === id && ref === "/queue" && history.length > 1' in CP
    # a back-forward return reads the entry, clears it, and draws whole anchored on that card
    show = Q[Q.index('window.addEventListener("pageshow"') :]
    show = show[: show.index("});")]
    assert show.index("AO.qSess.set(CARD_FROM, null)") < show.index('nav.type === "back_forward"')
    assert "anchorOn = o && o.card ? o : null;" in show and "whole = true;" in show
    draw = Q[Q.index("function drawWhole(") : Q.index("function slide(")]
    assert "ownG.dataset.group === at.group ? own : (at.after || []).map(at1).find(Boolean)" in draw
