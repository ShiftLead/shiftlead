"""TD-1240 mockups, read-only against the live UI: a static copy of the Sessions page (scripts
stripped), cropped to a repo with no team (ledgerboard) and a repo whose one team card is folded
(agent-cadence). *Today* is the page as it draws; *TD-1240* replaces each repo line's whole Repo
facet with its compact form: two rows, Technical debt and Pull requests, with **Add entry…**.

  usage: td1240_shots.py <out-dir>
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
UI = "http://127.0.0.1:8765"
REPOS = ("ledgerboard", "agent-cadence")

CSS = """
.cf-form { display: grid; gap: 4px; margin-top: 4px; }
.cf-row { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; font-size: 13px; }
.cf-row .kind { min-width: 118px; }
.cf-sw { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 3px; vertical-align: -1px; }
.cf-fig { white-space: nowrap; }
.cf-dim { color: var(--muted); }
"""

# Reads the facet's own numbers off the line and draws the compact form in its place.
COMPACT = r"""
([css, repos]) => {
  document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
  for (const repo of repos) {
    const l = document.querySelector(`.rline[data-repo="${repo}"]`);
    const s = l.querySelector('.rsum');
    const heads = [...s.querySelectorAll('.fhead')];
    const n = (h) => (h.querySelector('.kind').textContent.match(/\((\d+) open\)/) || [, '0'])[1];
    const figs = [...s.querySelector('.bar').querySelectorAll('.bseg')].map((b) =>
      `<span class="cf-fig"><i class="cf-sw" style="background:${getComputedStyle(b).backgroundColor}"></i>${b.title.toLowerCase()}</span>`);
    const tip = heads[0].querySelector('.tipmark');
    const meta = [...s.querySelectorAll('.meta')].pop().textContent.trim();
    const red = heads[1].querySelector('.prred');
    s.outerHTML = `<div class="cf-form">
      <div class="cf-row"><span class="kind">Technical debt</span><b>${n(heads[0])}</b> open
        <span class="cf-dim">·</span> ${figs.join(' <span class="cf-dim">·</span> ')}${tip ? ' ' + tip.outerHTML : ''}
        <button class="btn sm ghost" type="button">Add entry…</button></div>
      <div class="cf-row"><span class="kind">Pull requests</span><b>${n(heads[1])}</b> open
        ${red ? '<span class="cf-dim">·</span> ' + red.outerHTML.replace('· ', '') : ''}
        <span class="cf-dim">· ${meta}</span></div></div>`;
  }
}
"""

CLIP = r"""
(repos) => {
  const els = repos.map((r) => document.querySelector(`.rline[data-repo="${r}"]`));
  const last = els[els.length - 1].nextElementSibling;
  if (last && last.matches('section.tgroup')) els.push(last);
  const bs = els.map((e) => e.getBoundingClientRect());
  const top = Math.min(...bs.map((b) => b.top)) - 8, bot = Math.max(...bs.map((b) => b.bottom)) + 8;
  return { x: 0, y: top + window.scrollY, width: document.documentElement.clientWidth, height: bot - top };
}
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 900})
    pg.goto(UI + "/", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    html = pg.content()
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    html = html.replace("<head>", f'<head><base href="{UI}/">', 1)
    for w in (1600, 400):
        for shape in ("today", "td1240"):
            pg2 = b.new_page(viewport={"width": w, "height": 900})
            pg2.set_content(html, wait_until="networkidle")
            if shape == "td1240":
                pg2.evaluate(COMPACT, [CSS, list(REPOS)])
            clip = pg2.evaluate(CLIP, list(REPOS))
            pg2.screenshot(path=str(OUT / f"2026-10-30-td1240-{shape}-{w}.png"), clip=clip, full_page=True)
            pg2.close()
    b.close()
