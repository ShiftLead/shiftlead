"""TD-1321 slice 1: rule 4 presses on a scratch home (`scripts/look_home.py --v2`), each request held by `page.route`.

Run: PYTHONPATH=~/ao-shots/pwlib python td1321_presses.py <look home URL> <shot prefix>
"""

import sys, time, json
from playwright.sync_api import sync_playwright

U, OUT = sys.argv[1], sys.argv[2]
held = []


def hold(route):
    held.append(route)


def release(i, ok, detail="refused by the test"):
    r = held[i]
    r.fulfill(
        status=200 if ok else 409, content_type="application/json", body=json.dumps({} if ok else {"detail": detail})
    )


res = {}
B = "board:/tmp/{h}/repo:{n}"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    pg.on("dialog", lambda d: d.accept())
    pg.route("**/api/person/board", hold)
    pg.route("**/api/person/ledger", hold)
    pg.route("**/api/entry/hand", hold)
    pg.goto(U + "/repo/repo", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    row = lambda sel: pg.locator(f'.mailrow[data-msg$="{sel}"]').first
    # 1. a board answer: drawn on the press
    r11 = row("repo:11")
    t0 = time.monotonic()
    r11.locator('button[data-board-act="decide"]', has_text="drop").first.click()
    pg.wait_for_selector('.mailrow[data-msg$="repo:11"] .st.decided')
    res["press_ms"] = round((time.monotonic() - t0) * 1000)
    res["drawn"] = r11.locator(".st.decided").inner_text()
    res["answers_hidden"] = r11.locator(".sugg").first.is_hidden()
    res["gwi_hidden"] = r11.locator(".boardgo").is_hidden()
    res["dimmed"] = "pending" in (r11.get_attribute("class") or "")
    r11.screenshot(path=OUT + "-decided-landing.png")
    # 2. a ledger answer: the row leaves
    row("TD-002").locator('button[data-act="ledger"]', has_text="Drop it").first.click()
    pg.wait_for_timeout(200)
    res["ledger_gone"] = pg.locator('.mailrow[data-msg="ledger:repo:TD-002"]').count() == 0
    # 3. Works on line 8, to be refused
    row("repo:8").locator('button[data-board-act="decide"]', has_text="Works").first.click()
    pg.wait_for_timeout(200)
    # 4. a board Reply on line 10
    row("repo:10").locator('button[data-act="board_reply"]').first.click()
    pg.fill("#mailtext", "a reply from the test")
    pg.evaluate("document.querySelector('#mailbox').close('send')")
    pg.wait_for_timeout(300)
    res["reply_drawn"] = row("repo:10").locator(".st.boardreply").last.inner_text()
    # a re-read while all four are held
    pg.evaluate("AO.refreshInboxPage()")
    pg.wait_for_timeout(2500)
    res["after_reread"] = {
        "decided": row("repo:11").locator(".st.decided").inner_text(),
        "ledger_gone": pg.locator('.mailrow[data-msg="ledger:repo:TD-002"]').count() == 0,
        "works": row("repo:8").locator(".st.decided").inner_text(),
        "reply": row("repo:10").locator(".st.boardreply").count(),
    }
    res["held"] = len(held)
    # release: 11 ok, ledger refused, 8 refused, reply refused
    release(0, True)
    release(1, False, "the board moved")
    release(2, False, "the line changed")
    release(3, False, "no such line")
    pg.wait_for_timeout(3000)
    res["after_release"] = {
        "decided11": row("repo:11").locator(".st.decided").inner_text(),
        "row8_err": row("repo:8").locator(".rowerr").inner_text(),
        "row8_answers": row("repo:8").locator('button[data-board-act="decide"]').first.is_visible(),
        "row8_decided": row("repo:8").locator(".st.decided").count(),
        "row10_err": row("repo:10").locator(".rowerr").inner_text(),
        "row10_replies": row("repo:10").locator(".st.boardreply").count(),
        "ledger_back": pg.locator('.mailrow[data-msg="ledger:repo:TD-002"] .rowerr').first.inner_text()
        if pg.locator('.mailrow[data-msg="ledger:repo:TD-002"]').count()
        else None,
        "toasts": pg.evaluate("[...document.querySelectorAll('.toast')].map(t=>t.textContent.trim())"),
    }
    # a lagging board read after the success: still decided
    pg.evaluate("AO.refreshInboxPage()")
    pg.wait_for_timeout(2500)
    res["lag_keeps"] = row("repo:11").locator(".st.decided").inner_text()
    pg.screenshot(path=OUT + "-repo-after.png", full_page=False)
    # Queue: a card's board answer and Not right… with its hand-off refused
    held.clear()
    pg.goto(U + "/queue", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    q9 = row("repo:9")
    q9.locator('button[data-act="board_notright"]').first.click()
    pg.fill("#mailtext", "Not right: too small")
    pg.evaluate("document.querySelector('#mailbox').close('send')")
    pg.wait_for_timeout(300)
    res["q_notright"] = q9.locator(".st.decided").inner_text()
    pg.evaluate("AO.refreshInboxPage()")
    pg.wait_for_timeout(2500)
    res["q_after_reread"] = row("repo:9").locator(".st.decided").inner_text()
    release(0, True)
    pg.wait_for_timeout(500)
    while len(held) < 2:
        pg.wait_for_timeout(100)
    release(1, False, "the techlead seat is closed")
    pg.wait_for_timeout(1500)
    res["q_final"] = row("repo:9").locator(".st.decided").inner_text()
    res["q_toast"] = pg.evaluate("[...document.querySelectorAll('.toast')].map(t=>[t.textContent.trim(), t.className])")
    row("repo:9").screenshot(path=OUT + "-queue-notright.png")
    print(json.dumps(res, indent=1))
    b.close()
