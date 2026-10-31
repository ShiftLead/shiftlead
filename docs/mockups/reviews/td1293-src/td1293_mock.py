"""TD-1293 mockups from a static copy of the live Queue page (read-only): the top section in three
shapes — now, A (house refinement), B (the frontend-design skill's own pick) — at 1600 and 400 px."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

D = Path("/home/kmaster/ao-shots/td1293")
STATIC = (D / "static.html").read_text()

READ = """() => ({
  teams: [...document.querySelectorAll('#qfilters .qfteam')].map(a => [a.innerText, a.getAttribute('aria-pressed') === 'true']),
  repos: [...document.querySelectorAll('#qfilters .qfrepo')].map(a => a.innerText),
  t: document.querySelector('.qtitlebar .qsub').innerText,
})"""

A_CSS = """
.ta-head { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-top:2px; }
.ta-head .h1 { margin:0; }
.ta-count { color:var(--muted); font-size:var(--t-small); }
.ta-right { margin-left:auto; display:inline-flex; align-items:center; gap:12px; align-self:center; flex-wrap:wrap; }
.ta-find { }
.ta-find input { font:inherit; font-size:var(--t-small); padding:4px 9px; width:18em; }
.ta-row { display:flex; align-items:center; flex-wrap:wrap; gap:6px 6px; margin-top:10px; padding-bottom:12px; border-bottom:1px solid var(--border); margin-bottom:6px; }
.ta-lab { color:var(--muted); font-size:var(--t-small); margin-right:4px; }
.ta-grp { display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap; }
.ta-div { width:1px; align-self:stretch; background:var(--border); margin:0 6px 0 8px; }
.ta-sw { display:inline-flex; align-items:center; gap:7px; border:1px solid var(--border); border-radius:5px; padding:2px 10px 2px 8px; font-size:var(--t-small); color:var(--fg); }
.ta-sw .ta-box { width:11px; height:11px; border:1.5px solid var(--muted); border-radius:2px; display:inline-block; }
.ta-sw b { color:var(--needs-fg); font-weight:600; }
.ta-wants { color:var(--needs-fg); font-size:var(--t-small); margin-left:2px; }
@media (max-width: 720px) {
  .ta-right { margin-left:0; flex-basis:100%; margin-top:6px; }
  .ta-find { flex-basis:100%; } .ta-find input { width:100%; box-sizing:border-box; }
  .ta-div { display:none; }
}
"""

def a_html(d):
    import re
    m = re.match(r"(\\d+ cards?): (.*?)\\.", d["t"])
    count = d["t"].split(" Decide")[0]
    wants = re.search(r"(Decide [0-9]+ · Do [0-9]+)", d["t"]).group(1)
    needs = re.search(r"([0-9]+) need", d["t"]).group(1)
    teams = "".join(f'<a class="qf qfteam" aria-pressed="{str(p).lower()}">{t}</a>' for t, p in d["teams"])
    repos = "".join(f'<a class="qf qfrepo" aria-pressed="false" title="no team services this repo">{r}</a>' for r in d["repos"])
    return f"""<div class="ta-head"><span class="h1">Queue</span><span class="ta-count">{count}</span>
<span class="ta-right"><a class="ta-sw" role="switch" aria-checked="false"><span class="ta-box"></span>Needs you <b>{needs}</b></a><span class="ta-wants">{wants}</span><form class="ta-find"><input type="search" placeholder="find an id or a title"></form></span></div>
<div class="ta-row"><span class="ta-lab">teams</span><a class="qf" aria-pressed="true">All</a>{teams}
<span class="ta-div" title="no team services these repos"></span><span class="ta-grp"><span class="ta-lab"><i>no team</i></span>{repos}</span></div>"""

B_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600&display=swap');
.tb { --tb-ink:#e8ebf0; --tb-mut:#8b95a5; --tb-amb:#f0b44c; --tb-prog:#6aa6d9; --tb-wait:#7f8a99; --tb-next:#3a4350; --tb-line:#2a313c; }
.tb-top { display:grid; grid-template-columns:auto 1fr auto; align-items:end; gap:28px; }
.tb-h { font-family:'Barlow Semi Condensed', var(--sans, sans-serif); font-weight:600; font-size:30px; line-height:1; color:var(--tb-ink); letter-spacing:.01em; }
.tb-h small { display:block; font-size:13px; font-weight:500; color:var(--tb-mut); margin-top:6px; letter-spacing:0; }
.tb-bar { display:flex; height:8px; border-radius:2px; overflow:hidden; gap:2px; }
.tb-bar span { display:block; }
.tb-leg { display:flex; gap:18px; margin-top:7px; font-size:12.5px; color:var(--tb-mut); }
.tb-leg b { font-family:'Barlow Semi Condensed', sans-serif; font-size:15px; font-weight:600; color:var(--tb-ink); margin-right:4px; font-variant-numeric:tabular-nums; }
.tb-leg i { display:inline-block; width:8px; height:8px; border-radius:1px; margin-right:6px; vertical-align:0; }
.tb-tally { display:flex; align-items:center; gap:12px; border:1px solid var(--tb-amb); border-radius:6px; padding:6px 14px 6px 10px; color:var(--tb-ink); text-decoration:none; cursor:pointer; }
.tb-tally .n { font-family:'Barlow Semi Condensed', sans-serif; font-size:30px; font-weight:600; color:var(--tb-amb); line-height:1; font-variant-numeric:tabular-nums; }
.tb-tally .w { font-size:12.5px; line-height:1.35; color:var(--tb-mut); }
.tb-tally .w strong { color:var(--tb-ink); font-weight:600; font-size:13px; }
.tb-tally .tog { width:28px; height:16px; border-radius:8px; background:var(--tb-line); position:relative; }
.tb-tally .tog::after { content:''; position:absolute; left:2px; top:2px; width:12px; height:12px; border-radius:50%; background:var(--tb-mut); }
.tb-tabs { display:flex; align-items:end; gap:20px; margin-top:20px; border-bottom:1px solid var(--tb-line); flex-wrap:wrap; }
.tb-tab { padding:0 0 8px; font-size:13.5px; color:var(--tb-mut); border-bottom:2px solid transparent; margin-bottom:-1px; cursor:pointer; }
.tb-tab.on { color:var(--tb-ink); border-color:var(--tb-ink); font-weight:600; }
.tb-tab.repo { font-style:italic; }
.tb-gap { color:#5b6574; font-size:12px; padding-bottom:9px; margin-left:6px; }
.tb-find { margin-left:auto; padding-bottom:6px; }
.tb-find input { background:transparent; border:0; border-bottom:1px dashed #4a5361; color:var(--tb-ink); font:inherit; font-size:13px; width:15em; padding:2px 0; outline:none; }
@media (max-width: 720px) {
  .tb-top { grid-template-columns:1fr; gap:14px; }
  .tb-tabs { gap:14px; } .tb-find { margin-left:0; flex-basis:100%; } .tb-find input { width:100%; }
}
"""

def b_html(d):
    import re
    nums = dict((k, int(v)) for v, k in re.findall(r"([0-9]+) (in progress|waiting|up next)", d["t"]))
    total = sum(nums.values())
    dec, do = re.search(r"Decide ([0-9]+) · Do ([0-9]+)", d["t"]).groups()
    needs = re.search(r"([0-9]+) need", d["t"]).group(1)
    col = {"in progress": "var(--tb-prog)", "waiting": "var(--tb-wait)", "up next": "var(--tb-next)"}
    bar = "".join(f'<span style="flex:{max(n, total*0.012)};background:{col[k]}"></span>' for k, n in nums.items())
    leg = "".join(f'<span><i style="background:{col[k]}"></i><b>{n}</b>{k}</span>' for k, n in nums.items())
    tabs = '<span class="tb-tab on">All teams</span>' + "".join(f'<span class="tb-tab">{t}</span>' for t, _ in d["teams"])
    repos = '<span class="tb-gap">no team</span>' + "".join(f'<span class="tb-tab repo">{r}</span>' for r in d["repos"])
    return f"""<div class="tb"><div class="tb-top"><div class="tb-h">Queue<small>{total} cards, ranked by you</small></div>
<div><div class="tb-bar">{bar}</div><div class="tb-leg">{leg}</div></div>
<a class="tb-tally" role="switch" aria-checked="false"><span class="n">{needs}</span><span class="w"><strong>need you</strong><br>{dec} to decide, {do} to do</span><span class="tog"></span></a></div>
<div class="tb-tabs">{tabs}{repos}<form class="tb-find"><input type="search" placeholder="Find an id or a title"></form></div></div>"""

def inject(pg, html, css):
    pg.evaluate("""([html, css]) => {
      document.querySelector('#qfilters')?.remove();
      const bar = document.querySelector('.qtitlebar');
      const box = document.createElement('div'); box.innerHTML = html;
      document.querySelector('#queuepage').prepend(box);
      bar.remove();
      const st = document.createElement('style'); st.textContent = css; document.head.append(st);
    }""", [html, css])

with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h in ((1600, 230), (400, 560)):
        pg = b.new_page(viewport={"width": w, "height": 900}, color_scheme="dark")
        pg.set_content(STATIC, wait_until="networkidle")
        d = pg.evaluate(READ)
        pg.screenshot(path=str(D / f"now-{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": h})
        for name, fn, css in (("A", a_html, A_CSS), ("B", b_html, B_CSS)):
            pg.set_content(STATIC, wait_until="networkidle")
            inject(pg, fn(d), css)
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(D / f"{name}-{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": h})
        pg.close()
    b.close()
print("ok")
