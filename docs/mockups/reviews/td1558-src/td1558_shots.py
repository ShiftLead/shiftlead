"""TD-1558 round 1: the Queue as previews with a refresh bar, and a card's own page that holds still.

Read-only against the live UI: one GET of /queue, then a script-free copy is edited in place.
Run: PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python td1558_shots.py <base URL> <out prefix>
"""

import sys
from playwright.sync_api import sync_playwright

U, OUT = sys.argv[1], sys.argv[2]
CARD = "shiftlead#TD-1551"

CSS = """
.t58-bar{position:sticky;top:0;z-index:20;display:flex;gap:14px;align-items:center;margin:10px 0 14px;
  padding:9px 14px;border:1px solid #3b82f6;border-radius:8px;background:#0f1d33;font-size:14px}
.t58-bar .t58-live{color:#7ee2a8}.t58-bar .t58-grow{flex:1}.t58-bar b{color:#fff}
.t58-bar .t58-ask{color:#f6b73c;font-weight:600}
.t58-btn{background:#3b82f6;color:#fff;border:0;border-radius:6px;padding:5px 12px;font-weight:600}
.t58-prev{display:flex;gap:10px;align-items:center;padding:6px 0;white-space:nowrap}
.t58-prev .t58-sent{overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;font-weight:600}
.t58-open{color:#7fb3ff;text-decoration:none;font-weight:600;white-space:nowrap}
.t58-held{outline:2px solid #3b82f6;outline-offset:2px}
.t58-heldtag{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;background:#1e3a66;
  color:#cfe1ff;font-size:12px;font-weight:600}
.t58-crumb{display:flex;gap:12px;align-items:center;margin:14px 0 8px;font-size:14px}
.t58-crumb a{color:#7fb3ff;text-decoration:none;font-weight:600}
.t58-note{color:#9aa4b2;font-size:13px}
.t58-chg{background:#2a2410;color:#f6d77a;border-radius:4px;padding:0 4px}
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1100}, color_scheme="dark")
    pg.route("**/*", lambda r: r.continue_() if r.request.method == "GET" else r.abort())
    pg.goto(U + "/queue", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    html = pg.evaluate(
        """(u) => { const d = document.documentElement.cloneNode(true);
        d.querySelectorAll('script').forEach(s => s.remove());
        const base = document.createElement('base'); base.href = u + '/'; d.querySelector('head').prepend(base);
        return '<!doctype html>' + d.outerHTML; }""",
        U,
    )

    def page():
        q = b.new_page(viewport={"width": 1600, "height": 1100}, color_scheme="dark")
        q.route("**/*", lambda r: r.continue_() if r.request.method == "GET" else r.abort())
        q.set_content(html, wait_until="networkidle")
        q.add_style_tag(content=CSS)
        return q

    # 1. The Queue: previews, the bar, one card held under the pointer
    q = page()
    q.evaluate(
        """(card) => {
      const sec = g => document.querySelector(`section.qgroup[data-group="${g}"]`);
      sec('completed').remove();
      const ip = sec('in_progress');
      const bar = document.createElement('div'); bar.className = 't58-bar';
      bar.innerHTML = '<span class="t58-live">● live</span><span>values update in place · order holds while you are on the page</span>'
        + '<span class="t58-grow"></span><span class="t58-ask">1 new ask for you</span><span>· <b>2</b> cards moved · <b>1</b> done</span>'
        + '<button class="t58-btn">Refresh</button>';
      ip.parentNode.insertBefore(bar, ip);
      document.querySelectorAll('.qcard').forEach(c => {
        c.querySelectorAll('.qhead .qstart, .qhead .qmain > .qright > details.qdots, .qrow details.qdots').forEach(e => e.remove());
        const right = c.querySelector('.qhead .qright');
        if (right) { const o = document.createElement('a'); o.className = 't58-open'; o.textContent = 'Open card ›'; right.appendChild(o); }
        c.querySelectorAll('.qmail .mailrow').forEach(m => {
          const kind = m.querySelector('.kindmark'); const body = m.querySelector('.body');
          const rec = m.querySelector('button.answer.rec');
          const p = document.createElement('div'); p.className = 't58-prev';
          if (kind) p.appendChild(kind.cloneNode(true));
          const s = document.createElement('span'); s.className = 't58-sent'; s.textContent = body ? body.innerText.replace(/\\s+/g, ' ') : ''; p.appendChild(s);
          if (rec) { const r = rec.cloneNode(true); r.classList.add('sm'); p.appendChild(r); }
          const o = document.createElement('a'); o.className = 't58-open'; o.textContent = 'Answer on its card ›'; p.appendChild(o);
          m.replaceWith(p);
        });
      });
      const h = document.querySelector(`.qcard[data-card="${card}"]`);
      h.classList.add('t58-held');
      const t = document.createElement('span'); t.className = 't58-heldtag'; t.textContent = 'held — the pointer is on it';
      h.querySelector('.qid').after(t);
      window.scrollTo(0, 0);
    }""",
        CARD,
    )
    q.screenshot(path=OUT + "-queue.png", clip={"x": 250, "y": 0, "width": 1100, "height": 1700}, full_page=True)
    q.set_viewport_size({"width": 400, "height": 900})
    q.screenshot(path=OUT + "-queue-narrow.png", clip={"x": 0, "y": 0, "width": 400, "height": 1500}, full_page=True)

    # 2. The card page: the one card, every action, nothing moves
    c = page()
    c.evaluate(
        """(card) => {
      const keep = document.querySelector(`.qcard[data-card="${card}"]`);
      const ip = document.querySelector('section.qgroup[data-group="in_progress"]');
      const host = ip.parentNode;
      [...host.parentNode.children].forEach(e => { if (e !== host && !e.contains(document.querySelector('.topbar'))) {} });
      const wrap = document.createElement('div');
      wrap.innerHTML = '<div class="t58-crumb"><a>‹ Queue</a><span class="t58-note">In progress · 5th of 8 · shiftlead · ao-grind</span>'
        + '<span style="flex:1"></span><span class="t58-note">● live — values update in place; nothing on this page moves or re-orders</span></div>';
      keep.querySelectorAll('details.fold').forEach(d => d.open = true);
      const st = keep.querySelector('.qmail .mailrow .mhead .grow + .st');
      if (st) st.innerHTML = '<span class="t58-chg">due in 3 d · Nov 14</span>';
      wrap.appendChild(keep);
      host.replaceWith(wrap);
      document.querySelectorAll('section.qgroup, .t58-bar').forEach(e => e.remove());
      [...wrap.parentNode.children].forEach(e => { if (e !== wrap && !e.matches('nav, header, .topbar, #topbar')) e.style.display = 'none'; });
      window.scrollTo(0, 0);
    }""",
        CARD,
    )
    c.screenshot(path=OUT + "-card.png", full_page=True, clip={"x": 250, "y": 0, "width": 1100, "height": 1300})
    b.close()
