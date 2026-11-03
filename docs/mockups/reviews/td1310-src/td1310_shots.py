"""TD-1310 mockups, read-only against the live UI: the Queue page with ao-grind picked, copied without
scripts, its top line redrawn: now / A (recount, aligned, no needs mark) / B (recount, aligned, a needs
sliver in each segment, 'items' named) / C (B without the heading line's Decide · Do) / D (C's bar and
legend on their own line under one control row: Queue, the chips, the switch and find; Paul, 2026-11-02)."""
import re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(sys.argv[1]); UI = "http://127.0.0.1:8765"
# shown with ao-grind picked: (group, var, word, shown, needs among shown)
G = [("in_progress", "--working", "in progress", 4, 1), ("waiting", "--waiting", "waiting", 19, 0), ("up_next", "--ended", "up next", 24, 24)]
TOTAL, NEEDS, DEC, DO = 231, 25, 21, 12
CSS = """
.qhline { align-items: flex-start !important; }
.qhline .h1 { line-height: 26px; }
.qhline .qsum { padding-top: 0; }
.qhline .qhend { align-items: flex-start; }
.qhline .qf.qswitch { height: 26px; box-sizing: border-box; }
.qhline .qwantsn { line-height: 26px; }
.qhline .qfind input { height: 26px; box-sizing: border-box; }
.qhline .qsum .qsbar { margin-top: 0; height: 8px; border-radius: 3px; }
.tdm-seg { display: flex; overflow: hidden; border-radius: 2px; }
.tdm-seg > i { display: block; height: 100%; }
.tdm-wide .qsum { max-width: 500px !important; }
.tdm-items { color: var(--muted); margin-right: 4px; }
.tdm-d .qhline { align-items: center !important; }
.tdm-d .qhline .qteams { display: contents; }
.tdm-d .qhline .qteams > .qsub:first-child { margin-right: -6px; }
.tdm-d .qhend { margin-left: auto; }
.tdm-d .qhline { padding-bottom: 12px; border-bottom: 1px solid var(--border); margin-bottom: 10px; gap: 8px 8px; }
.tdm-d .qhline .h1 { margin-right: 10px !important; }
.tdm-d .qsum.tdm-line { display: flex; max-width: none !important; width: 100%; margin: 0 0 6px; }
.tdm-d .qsum.tdm-line .qsbar { height: 8px; }
"""
EDIT = r"""
([shape, G, TOTAL, NEEDS, DEC, DO, CSS]) => {
  if (shape === 'now') return;
  const hatch = shape === 'B' || shape === 'C' || shape === 'D';
  if (hatch && shape !== 'D') document.body.classList.add('tdm-wide');
  const st = document.createElement('style'); st.textContent = CSS; document.head.append(st);
  const bar = document.querySelector('.qsbar');
  bar.innerHTML = G.map(([g, v, w, n, nd]) => {
    if (hatch && nd) {
      const rest = n - nd;
      return `<span class="tdm-seg" style="flex: ${n}" title="${n} ${w}, ${nd} need you">${rest ? `<i style="flex: ${rest}; background: var(${v})"></i>` : ''}<i style="flex: ${nd}; background: repeating-linear-gradient(135deg, var(${v}) 0 3px, var(--needs) 3px 6px)"></i></span>`;
    }
    return `<span style="flex: ${n}; background: var(${v})" title="${n} ${w}"></span>`;
  }).join('');
  const shown = G.reduce((a, x) => a + x[3], 0);
  document.querySelector('.qsleg').innerHTML = G.map(([g, v, w, n]) => `<span><i style="background: var(${v})"></i><b>${n}</b>${w}</span>`).join('')
    + (hatch ? `<span><i style="background: repeating-linear-gradient(135deg, var(--ended) 0 2px, var(--needs) 2px 4px)"></i><b>${NEEDS}</b>need you</span>` : '')
    + `<span class="qscards">· ${shown} of ${TOTAL} cards</span>`;
  document.querySelector('#qfneedsn').textContent = NEEDS;
  document.querySelector('#qfneeds').title = `${NEEDS} cards need you`;
  const w = document.querySelector('.qwantsn');
  if (shape === 'C') { w.remove(); return; }
  if (shape === 'D') {
    w.remove(); document.body.classList.add('tdm-d');
    const line = document.querySelector('.qhline'), teams = document.querySelector('.qteams'), sum = document.querySelector('.qsum');
    teams.style.cssText = 'margin: 0; padding: 0; border: 0;';
    line.insertBefore(teams, document.querySelector('.qhend'));
    sum.classList.add('tdm-line'); document.querySelector('#qfilters').append(sum);
    return;
  }
  w.innerHTML = (shape === 'B' ? '<span class="tdm-items">items:</span>' : '') + `Decide ${DEC} · Do ${DO}`;
}
"""
with sync_playwright() as p:
    b = p.chromium.launch()
    for width in (1600, 400):
        pg = b.new_page(viewport={"width": width, "height": 900}, color_scheme="dark")
        pg.goto(UI + "/queue?team=ao-grind", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1500)
        html = pg.content()
        html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
        html = html.replace("<head>", f'<head><base href="{UI}/">', 1)
        for shape in ([s for s in sys.argv[2:]] or ["now", "A", "B"]):
            if width == 400 and shape == "now":
                continue
            pg.set_content(html, wait_until="networkidle")
            pg.evaluate(EDIT, [shape, G, TOTAL, NEEDS, DEC, DO, CSS])
            h = 170 if width == 1600 else 330
            pg.screenshot(path=str(OUT / f"2026-11-02-td1310-{shape.lower()}-{width}.png"), clip={"x": 0, "y": 44 if width == 1600 else 40, "width": width, "height": h})
        pg.close()
    b.close()
