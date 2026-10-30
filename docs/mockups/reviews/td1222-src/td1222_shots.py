"""TD-1222 mockups, read-only against the live UI: a static copy of the Sessions page (scripts
stripped) with the grid replaced by the same compact cards before and after the design —
the pill says what the session is doing, and *unseen* is a mark beside it.

  usage: td1222_shots.py <out-dir>
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
UI = "http://127.0.0.1:8765"

CSS = """
.t2-wrap { padding: 20px 24px; display: grid; gap: 18px; }
.t2-row { display: grid; grid-template-columns: 150px repeat(4, minmax(0, 1fr)); gap: 12px; align-items: start; }
.t2-head { font-weight: 600; color: var(--muted); font-size: 12px; }
.t2-case { font-size: 12px; color: var(--muted); }
.t2-mark { color: var(--new); font-size: 11px; margin-left: 6px; white-space: nowrap; }
.t2-mark.t2-chip { border: 1px solid var(--new); border-radius: 999px; padding: 0 7px; line-height: 18px; color: var(--new-fg); }
@media (max-width: 700px) { .t2-row { grid-template-columns: 1fr; } }
"""

CASES = [
    ("A person's session: its turn ended, you have not looked",
     ("idle · unseen", "s-idle", "interactive", False),
     ("idle", "s-idle", "interactive", True)),
    ("A person's session: answered, then a background `gh pr checks`",
     ("working", "s-working", "interactive · working · 1 shell: timeout 1500 gh pr checks 2658 --watch · 4m", False),
     ("working", "s-working", "interactive · working · 1 shell: timeout 1500 gh pr checks 2658 --watch · 4m", True)),
    ("A grinder with an ask out and its own shell running",
     ("waiting", "s-waiting", "Grinder · waiting on you: TD-959", False),
     ("working", "s-working", "Grinder · waiting on you: TD-959 · working · 1 shell", False)),
    ("A grinder with an ask out and nothing running",
     ("waiting", "s-waiting", "Grinder · waiting on you: TD-959", False),
     ("waiting", "s-waiting", "Grinder · waiting on you: TD-959", False)),
]

EDIT = r"""
([css, cases, chip]) => {
  const proto = document.querySelector('#card-ao-shiftlead-ao-paul');
  const grid = proto.closest('main') || document.body;
  const card = ([word, cls, line, unseen], name) => {
    const c = proto.cloneNode(true);
    c.removeAttribute('id');
    [...c.attributes].filter((a) => a.name.startsWith('data-')).forEach((a) => c.removeAttribute(a.name));
    if (name !== 'ao-paul') c.querySelector('.mine')?.remove();
    c.className = `card sc ${cls} compact`;
    c.querySelector('.name').textContent = name;
    c.querySelector('.name').outerHTML = `<span class="name">${name}</span>`;
    const pill = c.querySelector('.pill');
    pill.className = `pill nog ${cls}`; pill.textContent = word;
    if (unseen) pill.insertAdjacentHTML('afterend', chip
      ? '<span class="t2-mark t2-chip" title="a turn ended 6m ago, after you last looked">● unseen</span>'
      : '<span class="t2-mark" title="a turn ended 6m ago, after you last looked">●</span>');
    c.querySelector('.cline').textContent = line;
    c.querySelectorAll('a').forEach((a) => { const s = document.createElement('span'); s.className = a.className; s.innerHTML = a.innerHTML; a.replaceWith(s); });
    c.querySelector('details')?.remove();
    return c.outerHTML;
  };
  const row = (label, cells) => `<div class="t2-row"><div class="t2-head">${label}</div>${cells.join('')}</div>`;
  const names = ['ao-paul', 'ao-paul', 'grinder-ao-1', 'grinder-ao-1'];
  let html = `<style>${css}</style><div class="t2-wrap">`;
  html += row('', cases.map(([c]) => `<div class="t2-case">${c}</div>`));
  html += row('Today', cases.map(([, b], i) => card(b, names[i])));
  html += row('TD-1222', cases.map(([, , a], i) => card(a, names[i])));
  html += '</div>';
  grid.innerHTML = html;
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
    for theme in ("light",):
        for chip in (True,):
            for w in (1600, 400):
                pg2 = b.new_page(viewport={"width": w, "height": 900}, color_scheme=theme)
                pg2.set_content(html, wait_until="networkidle")
                pg2.evaluate(EDIT, [CSS, CASES, chip])
                name = f"2026-10-29-td1222-working-waiting-unseen-{w}.png"
                pg2.locator(".t2-wrap").screenshot(path=str(OUT / name))
                pg2.close()
    b.close()
