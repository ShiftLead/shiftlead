"""TD-2021 round 0 (for Paul): a design's end-of-rounds question drawn once, on the design.

Read-only against the live UI: it GETs /queue, keeps TD-794's card (TD-1919's design and its two held
builds), strips the scripts, and redraws the card by DOM edits. Nothing is pressed.
Run from the repo root:
  PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python \
    docs/mockups/reviews/td2021-src/td2021_shots.py docs/mockups/reviews/2026-11-19-td2021
It writes <prefix>-{today,open,answered}.png and <prefix>-open-phone.png.
"""

import sys

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8765/"

CSS = """
body { padding: 18px 22px 30px !important; }
.m21-cap { font-size: 13px; color: var(--muted); margin: 0 0 12px; max-width: 95ch; line-height: 1.45; }
.m21-cap b { color: var(--fg); }
.m21-wait { color: var(--idle-fg, #0f766e); background: var(--waiting-bg, #ccfbf1); border-radius: 3px; padding: 0 5px; }
.m21-go { font-weight: 600; }
"""

KEEP_CARD = """
(cap) => {
  const one = [...document.querySelectorAll('.qcard')].find(c => c.querySelector('[data-qid="shiftlead#TD-1947"]'));
  document.querySelectorAll('script').forEach(s => s.remove());
  const main = document.createElement('div');
  main.innerHTML = '<p class="m21-cap">' + cap + '</p>';
  main.appendChild(one);
  document.body.innerHTML = '';
  document.body.appendChild(main);
  document.querySelectorAll('details.qread').forEach(d => d.removeAttribute('open'));
  document.querySelectorAll('.qsec-answered, .qsec-fyi').forEach(s => s.remove());
}
"""

# One question, one row: the design's own ledger item goes (the board line covers it), each held build
# reads that it waits on the design's question, and the line names what Go releases.
OPEN = """
() => {
  document.querySelectorAll('.qsec.qwith').forEach(s => s.remove());
  const holds = document.querySelector('.st.holds');
  if (holds) holds.innerHTML = 'Go releases <a class="ref">TD-1947</a>, <a class="ref">TD-1948</a> to the grinders';
  for (const id of ['shiftlead#TD-1947', 'shiftlead#TD-1948']) {
    const r = document.querySelector('[data-qid="' + id + '"]');
    r.classList.remove('needsyou');
    r.querySelectorAll('.qrail.b-needs').forEach(x => x.remove());
    const s = r.querySelector('.qstate');
    s.className = 'qstate s-waiting m21-wait';
    s.textContent = "waits on TD-1919's question";
  }
  document.querySelectorAll('[data-qid="shiftlead#TD-1919"] .qseg').forEach(g => {
    g.className = 'qseg b-waiting'; g.style.background = '#5eead4';
  });
}
"""

# Answered One more round: the line closes, the design reads its answer and who acts, the builds still
# wait on its question, and the design's own ⋯ holds the one way out, named for what it does.
ANSWERED = """
() => {
  document.querySelectorAll('.qsec.qwant, .qsec.qwith').forEach(s => s.remove());
  const card = document.querySelector('.qcard');
  card.classList.remove('wants', 'edge-needs', 'st-needs-you');
  for (const id of ['shiftlead#TD-1947', 'shiftlead#TD-1948']) {
    const r = document.querySelector('[data-qid="' + id + '"]');
    r.classList.remove('needsyou');
    r.querySelectorAll('.qrail.b-needs').forEach(x => x.remove());
    const w = r.querySelector('.qstate');
    w.className = 'qstate s-waiting m21-wait';
    w.textContent = "waits on TD-1919's question";
  }
  document.querySelectorAll('[data-qid="shiftlead#TD-1919"] .qseg').forEach(g => {
    g.className = 'qseg b-waiting'; g.style.background = '#5eead4';
  });
  const pill = document.querySelector('.qhead .qstatus'); if (pill) pill.remove();
  const st = document.querySelector('.qhead .qstate'); if (st) st.textContent = 'waiting';
  const d = document.querySelector('[data-qid="shiftlead#TD-1919"]');
  const s = d.querySelector('.qstate');
  s.className = 'qstate s-waiting m21-wait';
  s.textContent = 'answered One more round — waiting on designer-ao-1';
  const menu = d.querySelector('details.qdots');
  menu.setAttribute('open', '');
  const m = menu.querySelector('.menu');
  m.style.position = 'static'; m.style.display = 'block';
  m.insertAdjacentHTML('afterbegin',
    '<button role="menuitem" type="button" class="m21-go" title="Lifts the hold on TD-1919, TD-1947 and TD-1948 in one PR">' +
    'Go now — build TD-1947, TD-1948…</button>');
}
"""

CAPS = {
    "today": "<b>Today.</b> One end-of-rounds question, drawn twice: the board's line, and TD-1919's own ledger hold "
    "(with its <b>Lift the hold</b>). Each held build reads <b>your decision</b> as well, so the card looks like "
    "three things to decide.",
    "open": "<b>Proposed, the question open.</b> One Decide item: the board's line, its answers the end-of-rounds "
    "ones, naming what <b>Go</b> releases. The design's own hold draws no item of its own, and each held build reads "
    "<b>waits on TD-1919's question</b>, with no answers and no <b>Lift the hold</b>.",
    "answered": "<b>Proposed, answered One more round.</b> The item goes. The design's row says the answer and who "
    "acts; the builds still wait on its question. The way out, if the round is not wanted after all, is in the "
    "design's ⋯ and named for what it does: <b>Go now — build TD-1947, TD-1948…</b>, whose confirm names every hold "
    "it lifts (the design's and both builds'). No build row carries a press of its own.",
}

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, edit, width in (("today", None, 1100), ("open", OPEN, 1100), ("answered", ANSWERED, 1100), ("open-phone", OPEN, 420)):
        pg = b.new_page(viewport={"width": width, "height": 900})
        pg.goto(BASE + "queue", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2000)
        pg.evaluate(KEEP_CARD, CAPS[name.split("-")[0]])
        pg.add_style_tag(content=CSS)
        if edit:
            pg.evaluate(edit)
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}-{name}.png", full_page=True)
        pg.close()
    b.close()
