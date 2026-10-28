"""TD-1189 mockups, read-only against the live UI: capture the Sessions page and the shiftlead Repo
page's Merged rows, then rearrange a static copy (no scripts, so no delta undoes the edit) into each
shape and shoot the shiftlead repo line with the ao-grind team's summary.

  A  the whole Repo facet (Technical debt + Pull requests) first on the team card; the line keeps its name
  B  Technical debt alone on the team card; Pull requests stays on the repo line
  C  shape A with TDs in motion turned to its *completed* face
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
UI = "http://127.0.0.1:8765"
REPO, TEAM = "shiftlead", "ao-grind"

EDIT = r"""
([shape, rows]) => {
  if (shape === 'now') return;
  const line = document.querySelector(`.rline[data-repo="${REPO}"]`);
  const tsum = document.querySelector(`#tsum-${TEAM}`);
  const frepo = line.querySelector('.frepo');
  const lineSum = line.querySelector('.rsum');
  // the facet's children from the Pull requests head on are the PR half
  const kids = [...frepo.children];
  const prAt = kids.findIndex((k) => k.classList.contains('fhead') && /Pull requests/.test(k.textContent));
  if (shape === 'B') {
    const debt = frepo.cloneNode(true);
    [...debt.children].slice(prAt).forEach((k) => k.remove());
    tsum.prepend(debt);
    kids.slice(0, prAt).forEach((k) => k.remove());
    frepo.classList.remove('frepo'); frepo.classList.add('fprs');
  } else {
    tsum.prepend(frepo);
    lineSum.remove();
  }
  if (innerWidth > 1100) tsum.style.gridTemplateColumns = 'minmax(0, 1fr) minmax(0, 1.15fr) minmax(0, 1.05fr)';
  const mo = tsum.querySelector('.fmotion');
  const head = mo.querySelector('.fhead');
  const seg = (vals, on) => `<span class="seg">${vals.map((v) => `<button type="button" aria-pressed="${v === on}">${v}</button>`).join('')}</span>`;
  if (shape !== 'C') { head.insertAdjacentHTML('beforeend', `<span class="grow"></span>${seg(['in motion', 'completed'], 'in motion')}`); return; }
  head.innerHTML = `<span class="kind">Completed (${rows.length})</span>${seg(['day', 'week', 'month'], 'day')}<span class="grow"></span>${seg(['in motion', 'completed'], 'completed')}`;
  mo.style.setProperty('--who-n', '0');
  [...mo.children].filter((k) => k !== head).forEach((k) => k.remove());
  for (const r of rows.slice(0, 8)) {
    const d = document.createElement('div');
    d.className = 'mrow';
    d.innerHTML = `<span class="mphase meta mono">${r.age}</span><span class="mprio"></span>`
      + `<a class="mref mono strong" href="#">${r.id}</a><span class="mtitle" title="${r.title}">${r.title}</span>`
      + `<span class="mwho"></span><span class="mpr">${r.pr ? `<a href="#">${r.pr}</a>` : '<span class="meta">no PR</span>'}</span>`;
    mo.append(d);
  }
  if (rows.length > 8) mo.insertAdjacentHTML('beforeend', `<div class="meta">+${rows.length - 8} more · all on the Repo page →</div>`);
}
""".replace("${REPO}", REPO).replace("${TEAM}", TEAM)

ROWS = """
() => [...document.querySelectorAll('#completed .wv[data-wv="day"] .rrow:not(.livediv):not(.livewords)')]
  .filter((r) => r.querySelector('.mono.strong'))
  .map((r) => {
    const t = [...r.querySelectorAll('a.mono, span.mono')].map((x) => x.textContent.trim());
    const pr = t.find((x) => x.startsWith('#')) || '';
    return {
      id: r.querySelector('.mono.strong').textContent.trim(),
      title: r.querySelector('.rtitle').textContent.trim(),
      pr, who: t.filter((x) => x !== pr && !/^TD-/.test(x)).pop() || '',
      age: (r.textContent.match(/·\\s*([^·]+)$/) || ['', ''])[1].trim(),
    };
  })
"""


def static(pg) -> str:
    html = pg.evaluate("document.documentElement.outerHTML")
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    return "<!doctype html>\n" + html.replace("<head>", f'<head><base href="{UI}/">', 1)


def shoot(b, html, shape, rows, width, name):
    pg = b.new_page(viewport={"width": width, "height": 1200}, color_scheme="dark")
    pg.set_content(html, wait_until="networkidle")
    pg.evaluate(EDIT, [shape, rows])
    pg.wait_for_timeout(300)
    box = pg.evaluate(
        f"""() => {{
        const a = document.querySelector('.rline[data-repo="{REPO}"]').getBoundingClientRect();
        const t = document.querySelector('#tsum-{TEAM}').getBoundingClientRect();
        const g = document.querySelector('#tsum-{TEAM}').closest('.tgroup') || document.querySelector('#tsum-{TEAM}');
        const h = g.querySelector('.ghead') ? g.querySelector('.ghead').getBoundingClientRect() : t;
        return {{ x: 0, y: a.top + scrollY - 8, width: innerWidth, height: t.bottom - a.top + 20 }};
    }}"""
    )
    pg.screenshot(path=str(OUT / name), clip=box, full_page=True)
    pg.close()


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1000}, color_scheme="dark")
    pg.goto(f"{UI}/repo/{REPO}")
    pg.wait_for_timeout(5000)
    rows = pg.evaluate(ROWS)
    pg.goto(f"{UI}/")
    pg.wait_for_timeout(6000)
    html = static(pg)
    pg.close()
    print(len(rows), "completed rows today;", rows[:2])
    for shape, w, name in (
        ("now", 1600, "2026-10-28-td1189-0-now.png"),
        ("A", 1600, "2026-10-28-td1189-A-facet-on-card.png"),
        ("B", 1600, "2026-10-28-td1189-B-debt-only.png"),
        ("C", 1600, "2026-10-28-td1189-C-completed-face.png"),
        ("C", 1000, "2026-10-28-td1189-C-one-column.png"),
    ):
        shoot(b, html, shape, rows, w, name)
    b.close()
