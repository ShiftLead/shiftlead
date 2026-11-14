"""TD-1801 round 0 (for Paul): the Queue answers in place again, the Refresh bar kept, in plain words.

Read-only against the live UI: GETs of /queue and two cards' pages; a script-free copy is edited in place.
Run: PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python td1801_shots.py <base URL> <out prefix>
"""
import sys
from playwright.sync_api import sync_playwright

U, OUT = sys.argv[1], sys.argv[2]
CARDS = ["loose%3Asamscrape%23TD-275", "loose%3Asamscrape%23TD-293"]
CSS = """
.t01-cap{margin:6px 0 12px;padding:8px 12px;border-left:3px solid #3b82f6;font-size:13px;opacity:.85}
.t01-own{font-size:12px;opacity:.75;text-decoration:none;margin-left:10px;white-space:nowrap}
.t01-own:hover{opacity:1;text-decoration:underline}
.t01-hbtn{margin-left:8px}
"""
PLAIN = r"""(args) => {
  const [cards, scheme] = args;
  document.querySelectorAll('script').forEach(s => s.remove());
  const c = document.querySelector('section.qgroup[data-group="completed"]'); if (c) c.remove();
  // 1. each held card: the card page's full card in place of the preview
  for (const html of cards) {
    const t = document.createElement('div'); t.innerHTML = html; const full = t.firstElementChild;
    const id = full.getAttribute('data-card');
    const old = document.querySelector(`.qcard[data-card="${CSS.escape(id)}"]`);
    if (old) old.replaceWith(full);
  }
  // 2. plain words on those cards
  const due = s => { const m = s.match(/(\d+)d overdue/); return m ? `due ${m[1]} days ago` : s; };
  for (const card of document.querySelectorAll('.qcard.wants')) {
    const sent = card.querySelector('.body.sentence');
    const title = card.querySelector('.qtitle');
    if (sent && title) { title.textContent = sent.textContent.trim();
      if (card.querySelectorAll('.body.sentence').length === 1) sent.remove(); }
    card.querySelectorAll('.qsech span').forEach(s => {
      const m = s.textContent.match(/^Decide \((\d+)\)$/);
      if (m) s.textContent = m[1] === '1' ? 'One decision for you' : `${m[1]} decisions for you`; });
    card.querySelectorAll('.mhead').forEach(h => {
      const st = h.querySelectorAll('.st');
      const repo = card.getAttribute('data-repos');
      if (st[0] && st[0].textContent.trim() === 'board line') st[0].textContent = `from ${repo}'s board`;
      if (st[1]) st[1].textContent = due(st[1].textContent);
      const k = h.querySelector('.kindmark'); if (k) k.textContent = 'Decide';
    });
    card.querySelectorAll('.alabel').forEach(a => { a.textContent = a.textContent.charAt(0).toUpperCase() + a.textContent.slice(1); });
    card.querySelectorAll('.qsec-decide .qsec .qdots, .qsec .qdots').forEach(()=>{});
    const head = card.querySelector('.qhead .qright');
    if (head && !head.querySelector('.t01-own')) {
      const a = document.createElement('a'); a.className = 't01-own'; a.href = '#'; a.textContent = 'Its own page';
      head.prepend(a);
    }
  }
  // 3. a card with no items: Start session and ⋯ back where Open card › was
  for (const card of document.querySelectorAll('.qcard')) {
    const oc = [...card.querySelectorAll('.qhead a, .qhead button')].find(e => /Open card/.test(e.textContent));
    if (!oc) continue;
    const box = document.createElement('span');
    box.innerHTML = '<button class="btn sm t01-hbtn" type="button">Start session</button>'
      + '<button class="btn sm ghost t01-hbtn" type="button" aria-label="More">⋯</button>'
      + '<a class="t01-own" href="#">Its own page</a>';
    oc.replaceWith(box);
  }
  // 4. the caption
  const bar = document.querySelector('#qbar') || document.querySelector('.qbar');
  const cap = document.createElement('div'); cap.className = 't01-cap';
  cap.textContent = 'Mockup, TD-1801: each item is answered where it is read. The bar above stays: nothing moves while you read; Refresh draws what changed.';
  (bar || document.querySelector('section.qgroup')).after(cap);
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    get = lambda pg: pg.route("**/*", lambda r: r.continue_() if r.request.method == "GET" else r.abort())
    pg = b.new_page(); get(pg)
    cards = []
    for cid in CARDS:
        pg.goto(f"{U}/card/{cid}", wait_until="networkidle"); pg.wait_for_timeout(1200)
        cards.append(pg.evaluate("() => document.querySelector('#cardlists .qcard').outerHTML"))
    def snap(scheme):
      g = b.new_page(color_scheme=scheme); get(g)
      g.goto(U + "/queue", wait_until="networkidle"); g.wait_for_timeout(1500)
      return g.evaluate("""(u) => { const d = document.documentElement.cloneNode(true);
        d.querySelectorAll('script').forEach(s => s.remove());
        const base = document.createElement('base'); base.href = u + '/'; d.querySelector('head').prepend(base);
        return '<!doctype html>' + d.outerHTML; }""", U)
    htmls = {s: snap(s) for s in ("dark", "light")}
    for scheme, w, h in (("dark", 1400, 1500), ("light", 1400, 1500), ("dark", 420, 1700)):
        q = b.new_page(viewport={"width": w, "height": h}, color_scheme=scheme); get(q)
        q.set_content(htmls[scheme], wait_until="networkidle"); q.add_style_tag(content=CSS)
        q.evaluate(PLAIN, [cards, scheme]); q.wait_for_timeout(300)
        # scroll to the decide cards
        q.evaluate("() => { const e = document.querySelector('.qcard[data-card=\"shiftlead#TD-1801\"]') || document.querySelector('.qcard.wants'); e.scrollIntoView(); window.scrollBy(0,-260); }")
        q.screenshot(path=f"{OUT}-{scheme}-{w}.png")
    b.close()
