import re, json
from playwright.sync_api import sync_playwright
UI = "http://127.0.0.1:8765"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 900}, color_scheme="dark")
    pg.goto(UI + "/queue", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    info = pg.evaluate("""() => ({
      filters: document.querySelector('#qfilters')?.outerHTML.length,
      title: document.querySelector('.qtitlebar')?.innerText,
      chips: [...document.querySelectorAll('#qfilters .qf')].map(a => a.innerText),
      font: getComputedStyle(document.body).fontFamily,
      bg: getComputedStyle(document.body).backgroundColor,
      theme: document.documentElement.dataset.theme || '',
      h1: getComputedStyle(document.querySelector('.qtitlebar .h1')).fontSize,
    })""")
    print(json.dumps(info, indent=1))
    pg.screenshot(path="/home/kmaster/ao-shots/td1293/now-1600.png", clip={"x": 0, "y": 0, "width": 1600, "height": 260})
    html = pg.evaluate("document.documentElement.outerHTML")
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    open("/home/kmaster/ao-shots/td1293/static.html", "w").write("<!doctype html>\n" + html.replace("<head>", f'<head><base href="{UI}/">', 1))
    b.close()
