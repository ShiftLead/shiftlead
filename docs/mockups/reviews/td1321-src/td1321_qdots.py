"""TD-1321 slice 2: Done… / Back to design… from a Queue card's ⋯ on a scratch home (`scripts/look_home.py --v2`),
each `/api/person/ledger` request held by `page.route`.

The scratch repo's ledger gains three fixture entries first (committed in the home's `repo`): TD-002 gets
`Part of: TD-001` and `Blocked by: decision (paul)` (a row drawn *your decision*, with the card's ledger item),
TD-004 `Part of: TD-001` (a second row), TD-003 alone on its card (its header's ⋯, no state word drawn).

Run: PYTHONPATH=~/ao-shots/pwlib python td1321_qdots.py <look home URL> <shot prefix>
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright

U, OUT = sys.argv[1], sys.argv[2]
held = []


def release(i, ok, detail="refused by the test"):
    held[i].fulfill(
        status=200 if ok else 409, content_type="application/json", body=json.dumps({} if ok else {"detail": detail})
    )


res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    pg.route("**/api/person/ledger", lambda r: held.append(r))
    pg.goto(U + "/queue", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    tgt = lambda kind, ref: pg.locator(f'.{kind}[data-qid="repo#{ref}"]').first  # noqa: E731
    state = lambda t: t.evaluate(  # noqa: E731
        "t => { const d = AO.qDotsOf(t); return [...d.parentElement.children].filter(x => x.classList.contains('qstate'))"
        ".map(x => x.textContent).join('|') }"
    )
    off = lambda t: t.evaluate("t => AO.qDotsOf(t).querySelector('summary').getAttribute('aria-disabled')")  # noqa: E731
    ledrow = lambda: pg.locator('.mailrow[data-msg="ledger:repo:TD-002"]')  # noqa: E731

    def press(t, name, words):
        t.evaluate("t => AO.qDotsOf(t).querySelector('summary').click()")
        pg.wait_for_timeout(150)
        t.evaluate(
            f"t => [...AO.qDotsOf(t).querySelectorAll('[role=menuitem]')].find(x => x.textContent === '{name}').click()"
        )
        pg.fill("#mailtext", words)
        t0 = time.monotonic()
        pg.evaluate("document.querySelector('#mailbox').close('send')")
        return t0

    res["before"] = {
        "TD-002": state(tgt("qrow", "TD-002")),
        "TD-003": state(tgt("qhead", "TD-003")),
        "ledger_row": ledrow().count(),
    }
    t0 = press(tgt("qrow", "TD-002"), "Done…", "finished by hand")
    pg.wait_for_function("() => document.querySelector('.qrow[data-qid=\"repo#TD-002\"] .qstate.s-pressed')")
    res["press_ms"] = round((time.monotonic() - t0) * 1000)
    res["row_press"] = {
        "state": state(tgt("qrow", "TD-002")),
        "dots_off": off(tgt("qrow", "TD-002")),
        "ledger_row": ledrow().count(),
    }
    tgt("qrow", "TD-002").screenshot(path=OUT + "-qrow-writing.png")
    press(tgt("qhead", "TD-003"), "Back to design…", "needs its design again")
    pg.wait_for_timeout(200)
    res["head_press"] = {"state": state(tgt("qhead", "TD-003")), "dots_off": off(tgt("qhead", "TD-003"))}
    tgt("qhead", "TD-003").screenshot(path=OUT + "-qhead-writing.png")
    press(tgt("qrow", "TD-004"), "Done…", "done elsewhere")
    pg.wait_for_timeout(200)
    # a keyboard open of an off ⋯ closes again
    s = tgt("qrow", "TD-004").locator("details.qdots summary").first
    s.evaluate("s => s.parentElement.open = true")
    pg.wait_for_timeout(100)
    res["off_reopens"] = s.evaluate("s => s.parentElement.open")
    # a re-read while all three are held
    pg.evaluate("AO.refreshInboxPage()")
    pg.wait_for_timeout(2500)
    res["after_reread"] = {
        "TD-002": state(tgt("qrow", "TD-002")),
        "TD-002_off": off(tgt("qrow", "TD-002")),
        "TD-003": state(tgt("qhead", "TD-003")),
        "TD-003_off": off(tgt("qhead", "TD-003")),
        "TD-004": state(tgt("qrow", "TD-004")),
        "ledger_row": ledrow().count(),
        "TD-001_head": state(tgt("qhead", "TD-001")),
    }
    res["held"] = len(held)
    # release: TD-002 refused, TD-003 and TD-004 answered
    # the answer's own words, read before the press's re-read replaces the cell: the re-read is held back for this
    pg.evaluate("AO.keepReread = AO.refreshInboxPage; AO.refreshInboxPage = () => {}")
    release(1, True)
    pg.wait_for_timeout(300)
    res["answered_head"] = {"state": state(tgt("qhead", "TD-003")), "dots_off": off(tgt("qhead", "TD-003"))}
    tgt("qhead", "TD-003").screenshot(path=OUT + "-qhead-written.png")
    pg.evaluate("AO.refreshInboxPage = AO.keepReread")
    release(0, False, "the board moved")
    pg.wait_for_timeout(50)
    res["refused_row"] = {"state": state(tgt("qrow", "TD-002")), "dots_off": off(tgt("qrow", "TD-002"))}
    release(2, True)
    pg.wait_for_timeout(3000)
    res["after_release"] = {
        "TD-002": state(tgt("qrow", "TD-002")),
        "TD-002_off": off(tgt("qrow", "TD-002")),
        "ledger_row_err": ledrow().locator(".rowerr").first.inner_text() if ledrow().count() else None,
        "toasts": pg.evaluate("[...document.querySelectorAll('.toast')].map(t=>t.textContent.trim())"),
    }
    pg.locator('.qcard[data-card*="TD-001"]').first.screenshot(path=OUT + "-refused.png")
    print(json.dumps(res, indent=1))
    b.close()
