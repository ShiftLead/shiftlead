from playwright.sync_api import sync_playwright
top=open('topbar.html').read()
def house(body):
    return f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><base href="http://127.0.0.1:8765/"><link rel="stylesheet" href="/static/app.css"></head><body>{top}{body}</body></html>'
with sync_playwright() as p:
    b=p.chromium.launch()
    for name,html in [('own',open('own.html').read())]:
        for w in (1440,420):
            pg=b.new_page(viewport={'width':w,'height':900})
            pg.set_content(html, wait_until='networkidle'); pg.wait_for_timeout(800)
            pg.screenshot(path=f'{name}3-{w}.png', full_page=True); pg.close()
    b.close()
