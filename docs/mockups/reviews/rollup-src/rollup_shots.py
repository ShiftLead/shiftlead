"""Sessions rollup as a list of teams, read-only against the live UI: capture the Sessions page, read each
repo's kind bar and each team's members, newest doing line and needs-you count from it, then replace the
four-facet rollup in a static copy (no scripts, so no delta undoes the edit) with each shape and shoot the top.

  A  one row per team, and per repo with no team: name, state, the kind bar, members by state, last work, needs you;
     the page totals a footer line under the rows
  B  the same readings as tiles, one per row of A, in a grid
  A2 A after Paul's first pass: no State column (Members says stopped), the doing line on the name's hover, the
     legend under the debt column, one needs-you count, a ⋯ menu per row (shown open on one row), no idle chip,
     and member blocks that tell working from waiting
  A3 A2 after a frontend-design pass: one line a row, the members strip the row's strong mark, thinner debt bars,
     the open count a column of its own, blanks for nothing (no dashes)
  A5 the chosen shape: A3, with A4's member blocks whose height says the state (Paul, 2026-10-28)
  A4 the design pass let loose: its own palette and type (Archivo, its width axis), people first, a quiet ledger
     bar that lights only the pickable share, the repo in a gutter, the totals as one sentence
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
UI = "http://127.0.0.1:8765"

READ = r"""
() => {
  const txt = (e) => (e ? e.textContent.replace(/\s+/g, ' ').trim() : '');
  const rows = [];
  const seen = new Set();
  for (const line of document.querySelectorAll('.rline[data-repo]')) {
    const repo = line.dataset.repo;
    if (seen.has(repo)) continue;
    seen.add(repo);
    const kbar = line.querySelector('.bar[aria-label="open entries by kind"]');
    const open = (txt(line.querySelector('.frepo .kind')).match(/\((\d+) open\)/) || [, '0'])[1];
    const pick = kbar && kbar.querySelector('.k-pickable') ? +kbar.querySelector('.k-pickable').textContent : 0;
    const teams = [...document.querySelectorAll(`section.tgroup[data-repo="${repo}"]`)];
    const base = { repo, kbar: kbar ? kbar.outerHTML.replace(/<a\b/g, '<span').replace(/<\/a>/g, '</span>').replace(/ href="[^"]*"/g, '') : '', open: +open, pick };
    if (!teams.length) { rows.push({ ...base, team: null }); continue; }
    for (const s of teams) {
      const t = s.dataset.team;
      const head = txt(s.querySelector('.ghead'));
      const cards = [...(document.getElementById('tgrid-' + t) || { children: [] }).children].filter((c) => !c.classList.contains('plus'));
      const states = cards.map((c) => {
        const m = c.className.match(/\bs-(needs|working|waiting|idle|oncall|exited|stalled|limited)\b/);
        return m ? m[1] : 'idle';
      });
      const sum = document.getElementById('tsum-' + t);
      const drow = sum && sum.querySelector('.fv[data-fv="doing"] .drow');
      const asked = sum && sum.querySelector('.fv[data-fv="doing"] .asked a');
      const ans = sum ? +((txt(sum.querySelector('.fv[data-fv="answer"] .kind')).match(/\((\d+)\)/) || [, 0])[1]) : 0;
      const live = +s.dataset.live > 0;
      const defined = +((head.match(/(\d+) members?/) || [, 0])[1]);
      const ended = (head.match(/(stopped|concluded \S+ ago|wound down \S+ ago)/) || [, ''])[1];
      rows.push({
        ...base, team: t, live, ended: live ? '' : (ended || 'stopped'), states, total: live ? states.length : defined + 2,
        last: drow ? txt(drow.querySelector('.dage')) : '', lastWho: drow ? txt(drow.querySelector('.name')).replace(/^ao-[a-z-]*?-(?=(grinder|designer|techlead|manager|queue|hunter|tester))/, '') : '',
        lastWhat: drow ? txt(drow.querySelector('.dtext')) : '',
        askers: asked ? [...(asked.title || '').matchAll(/(?:^|\n|[.?!)] )([a-z][a-z0-9_-]*-[a-z0-9_-]+): /g)].map((m) => m[1]) : [],
        asked: asked ? +((txt(asked).match(/· (\d+) ·/) || [, 0])[1]) : 0, askedAge: asked ? txt(asked).split('·').pop().trim() : '', ans,
      });
    }
  }
  const nr = document.querySelector('section[data-key="norepo"], section.norepo') ||
    [...document.querySelectorAll('section')].find((s) => /^No repo/.test(txt(s)));
  const ru = document.querySelector('#rollup .rollup');
  const facets = ru ? [...ru.querySelectorAll(':scope > .facet')] : [];
  return {
    rows,
    queue: txt([...document.querySelectorAll('a')].find((a) => /^\s*Queue/.test(a.textContent))).replace(/\D+/g, ''),
    norepo: nr ? txt(nr).match(/(\d+) sessions?/)[1] : '0',
    pills: facets[0] ? facets[0].querySelector('.row').outerHTML : '',
    agents: facets[0] ? txt(facets[0].querySelector('.kind')) : '',
    prs: facets[2] ? [txt(facets[2].querySelector('.kind')).replace(/PRs in motion/,'').trim() + ' open ·', ...[...facets[2].querySelector('.blocks').children].map(txt), 'today'].join(' ') : '',
    needs: facets[3] ? txt(facets[3]).replace(/^Needs you\s*/i, '') : '',
  };
}
"""

CSS = r"""
.ru-tl { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 6px 0 0; }
.ru-tl .ru-thd, .ru-tl .ru-tr { display: grid; grid-template-columns: minmax(170px, 1.1fr) 120px minmax(240px, 2.2fr) minmax(170px, 1.2fr) minmax(190px, 1.5fr) 120px;
  gap: 14px; align-items: center; padding: 7px 14px; }
.ru-tl .ru-thd { font-size: var(--t-cap); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); padding-bottom: 4px; }
.ru-tl .ru-thd .ru-r, .ru-tl .ru-tr .ru-r { text-align: right; justify-self: end; }
.ru-tl .ru-tr { border-top: 1px solid var(--line); color: var(--fg); text-decoration: none; cursor: pointer; }
.ru-tl .ru-tr:hover, .ru-tl .ru-tr.ru-hov { background: var(--hover); }
.ru-tl .ru-tr.ru-attn { box-shadow: inset 3px 0 0 var(--needs); }
.ru-tl .ru-nm { display: flex; flex-direction: column; min-width: 0; }
.ru-tl .ru-nm .ru-rp { color: var(--link); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ru-tl .ru-nm .ru-tm { font-family: var(--mono, ui-monospace, monospace); font-size: var(--t-mono-s); color: var(--strong); }
.ru-tl .ru-nm .ru-tm.ru-none { color: var(--muted); font-style: italic; font-family: inherit; }
.ru-tl .ru-st { font-size: var(--t-small); color: var(--muted); white-space: nowrap; }
.ru-tl .ru-st.ru-live { color: var(--working-fg); }
.ru-tl .ru-tdc { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ru-tl .ru-tdc .bar { flex: 1; height: 20px; min-width: 0; }
.ru-tl .ru-tdc .ru-n { font-size: var(--t-small); color: var(--muted); white-space: nowrap; width: 54px; text-align: right; }
.ru-tl .ru-idlework { font-size: var(--t-small); color: var(--needs-fg); background: var(--needs-bg); border-radius: 3px; padding: 1px 6px; white-space: nowrap; }
.ru-tl .ru-mem { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ru-tl .ru-dots { flex: none; display: flex; gap: 2px; flex-wrap: wrap; max-width: 120px; }
.ru-tl .ru-dots i { width: 7px; height: 14px; border-radius: 2px; background: var(--idle); }
.ru-tl .ru-dots i.ru-working { background: var(--working); } .ru-tl .ru-dots i.ru-waiting { background: var(--waiting); }
.ru-tl .ru-dots i.ru-needs { background: var(--needs); } .ru-tl .ru-dots i.ru-oncall, .ru-tl .ru-dots i.ru-exited { background: transparent; box-shadow: inset 0 0 0 1px var(--ended-fg); }
.ru-tl .ru-dots i.ru-off { background: transparent; box-shadow: inset 0 0 0 1px var(--line2); }
.ru-tl .ru-mem .ru-n, .ru-tl .ru-lw .ru-n { font-size: var(--t-small); color: var(--muted); white-space: nowrap; }
.ru-tl .ru-mem .ru-n b { color: var(--working-fg); font-weight: 600; }
.ru-tl .ru-lw { display: flex; gap: 8px; align-items: baseline; min-width: 0; }
.ru-tl .ru-lw .ru-age { font-family: var(--mono, ui-monospace, monospace); font-size: var(--t-mono-s); color: var(--strong); width: 26px; text-align: right; flex: none; }
.ru-tl .ru-lw .ru-who { font-family: var(--mono, ui-monospace, monospace); font-size: var(--t-mono-s); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ru-tl .ru-ny { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.ru-tl .ru-ny .ru-c { font-size: var(--t-small); font-weight: 600; white-space: nowrap; color: var(--needs-fg); background: var(--needs-bg); border-radius: 3px; padding: 1px 7px; }
.ru-tl .ru-ny .ru-c.ru-ans { background: var(--needs); color: var(--bg); }
.ru-tl .ru-ny .ru-z { color: var(--muted); }
.ru-tl .ru-tot { display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: center; border-top: 1px solid var(--line); padding: 10px 14px; font-size: var(--t-small); color: var(--muted); }
.ru-tl .ru-tot .kind { font-size: var(--t-cap); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--strong); margin-right: 6px; }
.ru-tl .ru-tot .ru-grp { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ru-tl .ru-tot .pill { font-size: var(--t-cap); }
.ru-tl .ru-tot a { color: var(--link); text-decoration: none; }
.ru-tl .legend { padding: 0 14px 8px; }
/* B: tiles */
.ru-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 10px; }
.ru-tile { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; color: var(--fg); text-decoration: none; }
.ru-tile.ru-attn { box-shadow: inset 3px 0 0 var(--needs); }
.ru-tile .ru-th { display: flex; align-items: baseline; gap: 8px; }
.ru-tile .ru-th .ru-rp { color: var(--link); font-weight: 600; } .ru-tile .ru-th .ru-tm { font-family: var(--mono, ui-monospace, monospace); font-size: var(--t-mono-s); color: var(--strong); }
.ru-tile .ru-th .ru-tm.ru-none { color: var(--muted); font-style: italic; font-family: inherit; }
.ru-tile .ru-th .ru-grow { flex: 1; }
.ru-tile .bar { height: 20px; }
.ru-tile .ru-ln { display: flex; gap: 10px; align-items: center; font-size: var(--t-small); color: var(--muted); }
.ru-tile .ru-ln .ru-grow { flex: 1; }
.ru-tl.ru-btot { margin-top: 10px; padding: 0; }
.ru-tl.ru-btot .ru-tot { border-top: 0; }
@media (max-width: 760px) {
  .ru-tl .ru-thd { display: none; }
  .ru-tl .ru-tr { grid-template-columns: 1fr auto; grid-template-areas: "nm ny" "tdc tdc" "mem lw"; gap: 6px 10px; }
  .ru-tl .ru-nm { grid-area: nm; flex-direction: row; gap: 8px; align-items: baseline; } .ru-tl .ru-st { display: none; }
  .ru-tl .ru-tdc { grid-area: tdc; } .ru-tl .ru-mem { grid-area: mem; } .ru-tl .ru-lw { grid-area: lw; justify-self: end; } .ru-tl .ru-ny { grid-area: ny; }
  .ru-tl .ru-lw .ru-who { display: none; }
}

/* A2 */
.ru-tl.ru-v2 .ru-thd, .ru-tl.ru-v2 .ru-tr { grid-template-columns: minmax(170px, 1fr) minmax(300px, 2.4fr) minmax(190px, 1.3fr) minmax(170px, 1.2fr) 90px 32px; column-gap: 28px; }
.ru-v2 .ru-tdc .ru-n { width: 64px; flex: none; font-variant-numeric: tabular-nums; }
.ru-v2 .ru-tdc { gap: 10px; }
.ru-v2 .ru-tr { position: relative; }
.ru-v2 .ru-dots i { width: 7px; height: 14px; border-radius: 2px; }
.ru-v2 .ru-dots i.ru-working { background: var(--working); }
.ru-v2 .ru-dots i.ru-needs { background: var(--needs); }
.ru-v2 .ru-dots i.ru-waiting { background: transparent; box-shadow: inset 0 0 0 2px var(--waiting); }
.ru-v2 .ru-dots i.ru-idle { background: var(--idle); opacity: .45; }
.ru-v2 .ru-dots i.ru-oncall { background: transparent; box-shadow: none; outline: 1px dashed var(--ended-fg); outline-offset: -1px; }
.ru-v2 .ru-dots i.ru-off { background: transparent; box-shadow: inset 0 0 0 1px var(--line2); }
.ru-v2 .ru-mem .ru-n .ru-stp { color: var(--muted); }
.ru-v2 .ru-lw .ru-who { text-decoration: underline dotted var(--line2); text-underline-offset: 3px; }
.ru-v2 .ru-ny .ru-c { min-width: 26px; text-align: center; }
.ru-v2 .ru-more { justify-self: end; background: none; border: 1px solid transparent; color: var(--muted); border-radius: 4px; width: 26px; height: 24px; font-size: 16px; line-height: 1; cursor: pointer; }
.ru-v2 .ru-tr:hover .ru-more, .ru-v2 .ru-more.ru-open { border-color: var(--line); color: var(--fg); }
.ru-v2 .ru-menu { position: absolute; right: 14px; top: 38px; z-index: 5; background: var(--card); border: 1px solid var(--line2); border-radius: 6px; box-shadow: 0 6px 20px rgba(0,0,0,.45); padding: 4px 0; min-width: 210px; font-size: var(--t-small); }
.ru-v2 .ru-menu div { padding: 6px 14px; color: var(--fg); white-space: nowrap; }
.ru-v2 .ru-menu div.ru-hi { background: var(--hover); }
.ru-v2 .ru-menu div.ru-stopc { color: var(--alarm-fg); }
.ru-v2 .ru-menu hr { border: 0; border-top: 1px solid var(--line); margin: 4px 0; }
.ru-v2 .ru-menu .meta { color: var(--muted); padding-left: 6px; }
.ru-v2 .ru-nymenu { position: absolute; right: 52px; top: 38px; z-index: 5; background: var(--card); border: 1px solid var(--line2); border-radius: 6px; box-shadow: 0 6px 20px rgba(0,0,0,.45); padding: 4px 0; min-width: 300px; font-size: var(--t-small); }
.ru-v2 .ru-nymenu .ru-h { padding: 6px 14px 4px; font-size: var(--t-cap); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.ru-v2 .ru-nymenu a { display: flex; gap: 10px; padding: 6px 14px; color: var(--fg); text-decoration: none; }
.ru-v2 .ru-nymenu a.ru-hi { background: var(--hover); }
.ru-v2 .ru-nymenu a .ru-k { margin-left: auto; color: var(--muted); font-family: var(--mono, ui-monospace, monospace); font-size: var(--t-mono-s); }
.ru-v2 .ru-nymenu a .ru-cnt { color: var(--needs-fg); font-weight: 600; width: 14px; text-align: right; }
.ru-v2 .ru-nymenu hr { border: 0; border-top: 1px solid var(--line); margin: 4px 0; }
.ru-v2 .ru-tip { position: absolute; z-index: 6; background: var(--card); border: 1px solid var(--line2); border-radius: 4px; padding: 6px 9px; font-size: var(--t-small); color: var(--fg); max-width: 460px; box-shadow: 0 6px 20px rgba(0,0,0,.45); }
.ru-v2 .ru-lgrow { display: grid; grid-template-columns: minmax(170px, 1fr) minmax(300px, 2.4fr) minmax(190px, 1.3fr) minmax(170px, 1.2fr) 90px 32px; gap: 28px; padding: 2px 14px 10px; border-top: 1px solid var(--line); }
.ru-v2 .ru-lgrow .legend { grid-column: 2; padding: 6px 0 0; flex-wrap: wrap; }
@media (max-width: 760px) {
  .ru-tl.ru-v2 .ru-tr { grid-template-columns: 1fr auto auto; grid-template-areas: "nm ny more" "tdc tdc tdc" "mem lw lw"; }
  .ru-v2 .ru-more { grid-area: more; } .ru-v2 .ru-lgrow { display: block; } .ru-v2 .ru-menu { top: 34px; }
}

/* A3 */
.ru-tl.ru-v3 .ru-thd, .ru-tl.ru-v3 .ru-tr, .ru-v3 .ru-lgrow { grid-template-columns: minmax(230px, 1.3fr) minmax(260px, 2.2fr) 44px minmax(210px, 1.3fr) minmax(170px, 1.1fr) 72px 28px; column-gap: 22px; }
.ru-v3 .ru-tr { padding: 6px 14px; min-height: 38px; }
.ru-v3 .ru-thd { padding-top: 4px; }
.ru-v3 .ru-nm { flex-direction: row; align-items: baseline; gap: 0; }
.ru-v3 .ru-nm .ru-rp { flex: none; }
.ru-v3 .ru-nm .ru-tm { margin-left: 8px; padding-left: 8px; border-left: 1px solid var(--line2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ru-v3 .ru-nm .ru-tm.ru-none { border-left-color: transparent; }
.ru-v3 .ru-tr[data-row=""] .ru-nm { padding-left: 18px; }
.ru-v3 .ru-tdc .bar { height: 14px; gap: 1px; }
.ru-v3 .ru-tdc .bseg { font-size: 11px; min-width: 16px; padding: 0 3px; }
.ru-v3 .ru-open { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); font-size: var(--t-small); }
.ru-v3 .ru-dots { max-width: 170px; gap: 3px; }
.ru-v3 .ru-dots i { width: 9px; height: 18px; border-radius: 2px; }
.ru-v3 .ru-mem { gap: 10px; }
.ru-v3 .ru-mem .ru-n { font-variant-numeric: tabular-nums; }
.ru-v3 .ru-mem .ru-n b { color: var(--working); font-weight: 700; }
.ru-v3 .ru-ny .ru-c.ru-v3c { min-width: 28px; padding: 2px 8px; font-variant-numeric: tabular-nums; }
.ru-v3 .ru-lgrow .legend { grid-column: 2 / 4; }
.ru-v3 .ru-nymenu { top: 34px; } .ru-v3 .ru-menu { top: 34px; }
@media (max-width: 760px) {
  .ru-tl.ru-v3 .ru-tr { grid-template-columns: 1fr auto auto auto; grid-template-areas: "nm nm ny more" "tdc tdc tdc open" "mem mem lw lw"; }
  .ru-v3 .ru-open { grid-area: open; } .ru-v3 .ru-nm { grid-area: nm; }
}

/* A4 */
.ru4 { --g: #1b2227; --g2: #222b31; --ink: #e6e1d3; --mut: #8b959c; --rule: #2e383f; --work: #4cc98c; --wait: #56b7c4;
  --need: #f0a63a; --idl: #46525d; --steel1: #3b4750; --steel2: #4c5963; --pick: #d9e4ff;
  font-family: Archivo, system-ui, sans-serif; font-variation-settings: "wdth" 100; font-feature-settings: "tnum";
  background: var(--g); color: var(--ink); border-radius: 4px; border: 1px solid var(--rule); }
.ru4 .h, .ru4 .r { display: grid; grid-template-columns: 112px minmax(150px, 1fr) minmax(250px, 1.5fr) minmax(190px, 1.1fr) minmax(250px, 1.5fr) 64px 28px;
  column-gap: 24px; align-items: center; padding: 0 16px; }
.ru4 .h { font-size: 12px; color: var(--mut); padding-top: 12px; padding-bottom: 8px; font-variation-settings: "wdth" 87; }
.ru4 .h .end { text-align: right; }
.ru4 .r { min-height: 42px; border-top: 1px solid var(--rule); cursor: pointer; position: relative; }
.ru4 .r:hover { background: var(--g2); }
.ru4 .r.cont { border-top-color: transparent; }
.ru4 .repo { font-size: 12px; color: var(--mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variation-settings: "wdth" 87; }
.ru4 .team { font-size: 19px; font-weight: 650; letter-spacing: .005em; font-variation-settings: "wdth" 72; white-space: nowrap; }
.ru4 .team.none { font-weight: 400; color: var(--mut); font-size: 15px; font-style: italic; font-variation-settings: "wdth" 87; }
.ru4 .ros { display: flex; align-items: center; gap: 12px; }
.ru4 .ticks { display: flex; gap: 3px; align-items: flex-end; height: 24px; }
.ru4 .ticks i { width: 6px; height: 14px; border-radius: 1px; background: var(--idl); }
.ru4 .ticks i.working { height: 24px; background: var(--work); }
.ru4 .ticks i.needs { height: 24px; background: var(--need); }
.ru4 .ticks i.waiting { height: 18px; background: transparent; box-shadow: inset 0 0 0 1.5px var(--wait); }
.ru4 .ticks i.oncall { height: 10px; background: transparent; box-shadow: inset 0 0 0 1px var(--mut); }
.ru4 .ticks i.off { height: 6px; background: var(--rule); }
.ru4 .wk { font-size: 13px; color: var(--mut); white-space: nowrap; }
.ru4 .wk b { color: var(--work); font-weight: 700; font-size: 15px; }
.ru4 .wk.stop { font-style: italic; }
.ru4 .lw { font-size: 13px; color: var(--mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ru4 .lw b { color: var(--ink); font-weight: 500; display: inline-block; min-width: 34px; }
.ru4 .lw u { text-decoration: none; border-bottom: 1px dotted var(--mut); }
.ru4 .led { display: flex; flex-direction: column; gap: 5px; }
.ru4 .lbar { display: flex; height: 6px; gap: 2px; }
.ru4 .lbar span { border-radius: 1px; background: var(--steel1); }
.ru4 .lbar span:nth-child(odd) { background: var(--steel2); }
.ru4 .lbar span.pick { background: var(--pick); }
.ru4 .lnum { font-size: 12px; color: var(--mut); font-variation-settings: "wdth" 87; }
.ru4 .lnum b { color: var(--pick); font-weight: 600; }
.ru4 .need { justify-self: end; font-size: 17px; font-weight: 700; color: var(--need); border-left: 3px solid var(--need); padding: 0 0 0 9px; line-height: 22px; }
.ru4 .more { justify-self: end; color: var(--mut); font-size: 18px; line-height: 1; }
.ru4 .foot { border-top: 1px solid var(--rule); padding: 12px 16px 14px; font-size: 13px; color: var(--mut); line-height: 1.6; display: flex; flex-wrap: wrap; gap: 4px 28px; }
.ru4 .foot b { color: var(--ink); font-weight: 600; }
.ru4 .foot .w { color: var(--work); } .ru4 .foot .n { color: var(--need); }
.ru4 .pop { position: absolute; right: 44px; top: 36px; z-index: 5; background: var(--g2); border: 1px solid var(--rule); border-radius: 4px; box-shadow: 0 10px 28px rgba(0,0,0,.5); padding: 6px 0; min-width: 280px; font-size: 13px; cursor: default; }
.ru4 .pop a { display: flex; gap: 12px; padding: 6px 14px; color: var(--ink); text-decoration: none; }
.ru4 .pop a:first-child { background: #2a343b; }
.ru4 .pop a span:first-child { color: var(--need); font-weight: 700; width: 14px; text-align: right; }
.ru4 .pop a em { margin-left: auto; font-style: normal; color: var(--mut); }
@media (max-width: 760px) {
  .ru4 .h { display: none; }
  .ru4 .r { grid-template-columns: 1fr auto auto; grid-template-areas: "repo need more" "team team team" "ros ros lw" "led led led"; row-gap: 6px; padding: 10px 16px; }
  .ru4 .repo { grid-area: repo; } .ru4 .team { grid-area: team; } .ru4 .ros { grid-area: ros; } .ru4 .lw { grid-area: lw; justify-self: end; }
  .ru4 .led { grid-area: led; } .ru4 .need { grid-area: need; } .ru4 .more { grid-area: more; } .ru4 .r.cont .repo { display: none; }
  .ru4 .pop { right: 16px; }
}

/* A5: a block's height says its state */
.ru-v5 .ru-dots { align-items: flex-end; height: 20px; flex-wrap: nowrap; max-width: none; }
.ru-v5 .ru-dots i { width: 7px; }
.ru-v5 .ru-dots i.ru-working, .ru-v5 .ru-dots i.ru-needs { height: 20px; }
.ru-v5 .ru-dots i.ru-waiting { height: 14px; }
.ru-v5 .ru-dots i.ru-idle { height: 9px; opacity: .6; }
.ru-v5 .ru-dots i.ru-oncall { height: 6px; }
.ru-v5 .ru-dots i.ru-off { height: 4px; background: var(--line2); box-shadow: none; }
"""

BUILD = r"""
([shape, d, css]) => {
  const st = document.createElement('style'); st.textContent = css; document.head.append(st);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const host = document.querySelector('#rollup');
  const parts = (r) => {
    const working = (r.states || []).filter((s) => s === 'working').length;
    const needs = (r.ans || 0) + (r.asked || 0);
    const name = `<span class="ru-rp">${esc(r.repo)}</span>${r.team ? `<span class="ru-tm">${esc(r.team)}</span>` : '<span class="ru-tm ru-none">no team</span>'}`;
    const state = !r.team ? '' : r.live ? `<span class="ru-st ru-live">live</span>` : `<span class="ru-st">${esc(r.ended)}</span>`;
    const idle = r.pick && (!r.team || !working) ? `<span class="ru-idlework" title="${r.pick} pickable and nobody working on them">${r.pick} pickable · idle</span>` : '';
    const tdc = `<div class="ru-tdc">${r.kbar || '<span class="meta">no ledger</span>'}<span class="ru-n">${r.open} open</span></div>`;
    const dots = !r.team ? '' : r.live ? r.states.map((s) => `<i class="ru-${s}"></i>`).join('') : Array.from({ length: r.total }, () => '<i class="ru-off"></i>').join('');
    const mem = !r.team ? `<div class="ru-mem">${idle}</div>` : `<div class="ru-mem"><span class="ru-dots">${dots}</span><span class="ru-n">${r.live ? `<b>${working}</b> / ${r.states.length} working` : `0 / ${r.total}`}</span>${idle}</div>`;
    const lw = r.last ? `<div class="ru-lw" title="${esc(r.lastWhat)}"><span class="ru-age">${esc(r.last)}</span><span class="ru-who">${esc(r.lastWho)}</span></div>` : '<div class="ru-lw"><span class="ru-n">—</span></div>';
    const ny = needs ? `<div class="ru-ny">${r.ans ? `<span class="ru-c ru-ans">${r.ans} answer needed</span>` : ''}${r.asked ? `<span class="ru-c" title="members' open asks to you, oldest ${esc(r.askedAge)}">asked you · ${r.asked} · ${esc(r.askedAge)}</span>` : ''}</div>` : '<div class="ru-ny"><span class="ru-z">—</span></div>';
    return { working, needs, name, state, idle, tdc, mem, lw, ny, attn: !!r.ans };
  };
  const rows = d.rows.concat([{ repo: 'No repo', team: null, norepo: true, open: 0, kbar: '' }]);
  const tot = `<div class="ru-tot"><span class="ru-grp"><span class="kind">${esc(d.agents)}</span>${d.pills}</span>
    <span class="ru-grp"><span class="kind">PRs</span>${esc(d.prs)}</span>
    <span class="ru-grp"><span class="kind">Needs you</span><a href="/inbox">${esc(d.needs)}</a></span></div>`;
  const legend = document.querySelector('.rline .frepo .legend').outerHTML;


  if (shape === 'A4') {
    const font = document.createElement('link'); font.rel = 'stylesheet';
    font.href = 'https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap'; document.head.append(font);
    const ORDER = ['needs', 'working', 'waiting', 'idle', 'oncall'];
    const kinds = (html) => {
      const t = document.createElement('div'); t.innerHTML = html;
      return [...t.querySelectorAll('.bseg')].map((x) => ({ k: (x.className.match(/k-([a-z-]+)/) || [, ''])[1], n: +x.textContent.trim() }));
    };
    let prev = '';
    const body = rows.map((r) => {
      const cont = r.repo === prev && !r.norepo; prev = r.repo;
      const strip = r.team === '';
      const states = (r.states || []).slice().sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
      const working = states.filter((x) => x === 'working').length;
      const ticks = r.norepo ? '<i class="idle"></i>' : r.team === null ? '' : (r.live || strip) ? states.map((x) => `<i class="${x}"></i>`).join('') : Array.from({ length: r.total }, () => '<i class="off"></i>').join('');
      const wk = r.norepo ? `<span class="wk"><b>0</b> of ${d.norepo} working</span>` : r.team === null ? '' : (r.live || strip) ? `<span class="wk"><b>${working}</b> of ${states.length} working</span>` : `<span class="wk stop">${esc(r.ended)}</span>`;
      const team = r.norepo ? '<span class="team none">no repo</span>' : strip ? `<span class="team none">no team, ${states.length} session</span>` : r.team ? `<span class="team">${esc(r.team)}</span>` : '<span class="team none">no team</span>';
      const ks = r.kbar && !strip ? kinds(r.kbar) : [];
      const led = ks.length ? `<div class="led"><div class="lbar">${ks.map((k) => `<span class="${k.k === 'pickable' ? 'pick' : ''}" style="flex:${k.n}"></span>`).join('')}</div>
        <span class="lnum">${r.pick ? `<b>${r.pick} pickable</b> of ` : ''}${r.open} open</span></div>` : '<span></span>';
      const lw = r.last ? `<span class="lw"><b>${esc(r.last)}</b><u title="${esc(r.lastWhat)}">${esc(r.lastWho)}</u></span>` : '<span></span>';
      const n = (r.ans || 0) + (r.asked || 0);
      const by = {}; (r.askers || []).forEach((w) => { by[w] = (by[w] || 0) + 1; });
      const pop = r.team === 'ao-grind' && n ? `<div class="pop"><a href="#"><span>${r.asked}</span>asked you<em>oldest ${esc(r.askedAge)}, open in the Inbox</em></a>${Object.entries(by).map(([w, c]) => `<a href="#"><span>${c}</span>${esc(w)}</a>`).join('')}</div>` : '';
      return `<div class="r${cont ? ' cont' : ''}"><span class="repo">${cont ? '' : esc(r.norepo ? '' : r.repo)}</span>${team}<span class="ros"><span class="ticks">${ticks}</span>${wk}</span>${lw}${led}${n ? `<span class="need">${n}</span>` : '<span></span>'}<span class="more">${r.norepo ? '' : '⋯'}</span>${pop}</div>`;
    }).join('');
    const pills = [...new DOMParser().parseFromString(d.pills, 'text/html').querySelectorAll('button')].map((b) => b.textContent.trim());
    const ag = pills.map((t) => { const m = t.match(/^(.*) \((\d+)\)$/); return m ? `${m[2]} ${m[1]}` : t; });
    const prs = d.prs.match(/\((\d+)\) open · (\d+) opened (\d+) closed/) || [];
    const inbox = (d.needs.match(/(\d+) in the Inbox/) || [, '?'])[1], over = (d.needs.match(/(\d+) overdue/) || [, '?'])[1];
    const teamsN = d.rows.reduce((a, r) => a + (r.asked || 0) + (r.ans || 0), 0);
    const foot = `<div class="foot"><span><b>${esc(d.agents.replace(/\D+/g, ''))} agents</b>: <span class="w">${ag[0]}</span>, ${ag.slice(1).join(', ')}</span>
      <span><b>${prs[1]} PRs open</b>, ${prs[2]} opened and ${prs[3]} closed today</span>
      <span><b>Needs you</b>: <span class="n">${teamsN} from teams</span>, ${esc(d.queue)} on the Queue, ${inbox} in the Inbox (${over} overdue)</span></div>`;
    host.innerHTML = `<div class="ru4"><div class="h"><span>Repo</span><span>Team</span><span>Who's working</span><span>Last work</span><span>Ledger</span><span class="end">Needs you</span><span></span></div>${body}${foot}</div>`;
    return;
  }
  if (shape === 'A2' || shape === 'A3' || shape === 'A5') {
    const v3 = shape !== 'A2';
    const ORDER = ['needs', 'working', 'waiting', 'idle', 'oncall'];
    const menuFor = (r) => r.team === '' ? ['New session here'] : !r.team
      ? ['Add entry…', 'New session here']
      : r.live ? ['Add entry…', `New session in ${r.team}`, '-', 'Wind down', '!Stop now'] : ['Start', 'Add entry…', `New session in ${r.team}`];
    const body = rows.map((r) => {
      const p = parts(r);
      const states = (r.states || []).slice().sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
      const working = states.filter((x) => x === 'working').length;
      const dots = r.norepo ? '<i class="ru-idle"></i>' : r.team === '' ? states.map((x) => `<i class="ru-${x}"></i>`).join('') : !r.team ? '' : r.live ? states.map((x) => `<i class="ru-${x}"></i>`).join('') : Array.from({ length: r.total }, () => '<i class="ru-off"></i>').join('');
      const memtxt = v3 ? (r.norepo ? `<b>0</b> of ${d.norepo}` : !r.team && r.team !== '' ? '' : r.live || r.team === '' ? `<b>${working}</b> of ${states.length}` : `<span class="ru-stp">${esc(r.ended)}</span>`) : r.team === '' ? `<b>${working}</b> / ${states.length} working` : r.norepo ? `<b>0</b> / ${d.norepo} working` : !r.team ? '<span class="ru-stp">no team</span>' : r.live ? `<b>${working}</b> / ${states.length} working` : `<span class="ru-stp">${esc(r.ended)} · 0 / ${r.total}</span>`;
      const mem = `<div class="ru-mem"><span class="ru-dots">${dots}</span><span class="ru-n">${memtxt}</span></div>`;
      const lw = v3 && !r.last ? '<span></span>' : r.last ? `<div class="ru-lw"><span class="ru-age">${esc(r.last)}</span><span class="ru-who" title="${esc(r.lastWhat)}">${esc(r.lastWho)}</span></div>` : '<div class="ru-lw"><span class="ru-n">—</span></div>';
      const n = (r.ans || 0) + (r.asked || 0);
      const ny = v3 && !n ? '<span></span>' : n ? `<div class="ru-ny"><span class="ru-c${r.ans ? ' ru-ans' : ''}" title="${r.ans ? r.ans + ' answer needed · ' : ''}asked you ${r.asked}, oldest ${esc(r.askedAge)}">${n}</span></div>` : '<div class="ru-ny"><span class="ru-z">—</span></div>';
      const open = r.team === 'dc-grind';
      const nyOpen = r.team === 'ao-grind' && n;
      const by = {}; (r.askers || []).forEach((w) => { by[w] = (by[w] || 0) + 1; });
      const nymenu = nyOpen ? `<div class="ru-nymenu"><div class="ru-h">needs you · ${n}</div>
        <a class="ru-hi" href="/inbox?team=${esc(r.team)}&kind=questions"><span class="ru-cnt">${r.asked}</span>asked you<span class="ru-k">oldest ${esc(r.askedAge)} · Inbox →</span></a>
        ${Object.entries(by).map(([w, c]) => `<a href="/inbox?team=${esc(r.team)}&kind=questions&from=${esc(w)}"><span class="ru-cnt">${c}</span>${esc(w)}<span class="ru-k">→</span></a>`).join('')}
        ${r.ans ? `<hr><a href="#"><span class="ru-cnt">${r.ans}</span>answer needed<span class="ru-k">on the card →</span></a>` : ''}</div>` : '';
      const menu = open ? `<div class="ru-menu">${menuFor(r).map((m, j) => m === '-' ? '<hr>' : `<div class="${j === 1 ? 'ru-hi' : ''}${m[0] === '!' ? ' ru-stopc' : ''}">${esc(m.replace(/^!/, ''))}</div>`).join('')}</div>` : '';
      const strip = r.team === '';
      const tdc = r.norepo || strip ? (v3 ? '<span></span><span></span>' : '<span></span>') : v3 ? `<div class="ru-tdc">${r.kbar}</div><span class="ru-open">${r.open}</span>` : p.tdc;
      const nm = v3 ? (strip ? `<div class="ru-nm"><span class="ru-tm ru-none">no team · ${states.length} session${states.length === 1 ? '' : 's'}</span></div>`
        : r.norepo ? `<div class="ru-nm"><span class="ru-rp">No repo</span></div>`
        : `<div class="ru-nm"><span class="ru-rp">${esc(r.repo)}</span>${r.team ? `<span class="ru-tm">${esc(r.team)}</span>` : '<span class="ru-tm ru-none">no team</span>'}</div>`)
        : strip ? `<div class="ru-nm"><span class="ru-tm ru-none">↳ no team · ${states.length} session${states.length === 1 ? '' : 's'}</span></div>` : r.norepo ? `<div class="ru-nm"><span class="ru-rp">No repo</span><span class="ru-tm ru-none">${d.norepo} session</span></div>` : `<div class="ru-nm">${p.name}</div>`;
      const more = r.norepo ? '<span></span>' : `<button class="ru-more${open ? ' ru-open' : ''}" type="button" aria-label="more">⋯</button>`;
      return `<div class="ru-tr${p.attn ? ' ru-attn' : ''}" role="link" tabindex="0" data-row="${esc(r.team || r.repo)}">${nm}${tdc}${mem}${lw}${ny}${more}${menu}${nymenu}</div>`;
    }).join('');
    const tot2 = `<div class="ru-tot"><span class="ru-grp"><span class="kind">${esc(d.agents)}</span>${d.pills}</span>
      <span class="ru-grp"><span class="kind">PRs</span>${esc(d.prs)}</span>
      <span class="ru-grp"><span class="kind">Needs you</span><a href="#">${d.rows.reduce((a, r) => a + (r.asked || 0) + (r.ans || 0), 0)} from teams</a> · <a href="/queue">${esc(d.queue)} on the Queue</a> · <a href="/inbox">${esc(d.needs.replace(/^.*?(\d+ in the Inbox)/, '$1'))}</a></span></div>`;
    host.innerHTML = `<div class="ru-tl ru-v2${v3 ? ' ru-v3' : ''}"><div class="ru-thd"><span>Teams (${d.rows.filter((r) => r.team).length}) · repos</span><span>Technical debt, by kind</span>${v3 ? '<span class="ru-r">open</span>' : ''}<span>members</span><span>last work</span><span class="ru-r">needs you</span><span></span></div>${body}<div class="ru-lgrow"><span></span>${legend}</div>${tot2}</div>`;
    if (shape === 'A5') host.querySelector('.ru-tl').classList.add('ru-v5');
    if (v3) host.querySelectorAll('.ru-ny .ru-c').forEach((c) => c.classList.add('ru-v3c'));
    // the doing line's hover, drawn on the shiftlead row's name
    const who = host.querySelector('.ru-tr[data-row="ao-grind"] .ru-who');
    if (false && who && innerWidth > 760) {
      const b = who.getBoundingClientRect(), hb = host.getBoundingClientRect();
      const tip = document.createElement('div'); tip.className = 'ru-tip'; tip.textContent = who.title;
      tip.style.left = (b.left - hb.left) + 'px'; tip.style.top = (b.bottom - hb.top + 6) + 'px';
      host.querySelector('.ru-tl').style.position = 'relative'; host.querySelector('.ru-tl').append(tip);
    }
    return;
  }
  if (shape === 'A') {
    const body = rows.map((r, i) => {
      if (r.norepo) return `<a class="ru-tr" href="#norepo"><div class="ru-nm"><span class="ru-rp">No repo</span><span class="ru-tm ru-none">${d.norepo} session</span></div><span></span><span></span><div class="ru-mem"><span class="ru-dots"><i class="idle"></i></span><span class="ru-n"><b>0</b> / ${d.norepo} working</span></div><div class="ru-lw"><span class="ru-n">—</span></div><div class="ru-ny"><span class="ru-z">—</span></div></a>`;
      const p = parts(r);
      return `<a class="ru-tr${p.attn ? ' ru-attn' : ''}${i === 2 ? ' ru-hov' : ''}" href="#team=${esc(r.team || 'repo:' + r.repo)}"><div class="ru-nm">${p.name}</div>${p.state || '<span></span>'}${p.tdc}${p.mem}${p.lw}${p.ny}</a>`;
    }).join('');
    host.innerHTML = `<div class="ru-tl"><div class="ru-thd"><span>Teams (${d.rows.filter((r) => r.team).length}) · repos</span><span>state</span><span>Technical debt, by kind</span><span>members</span><span>last work</span><span class="ru-r">needs you</span></div>${body}${legend}${tot}</div>`;
  } else {
    const body = rows.filter((r) => !r.norepo).map((r) => {
      const p = parts(r);
      return `<a class="ru-tile${p.attn ? ' ru-attn' : ''}" href="#team=${esc(r.team || r.repo)}"><div class="ru-th">${p.name}${p.state}<span class="ru-grow"></span>${p.needs ? p.ny : ''}</div>
        <div class="ru-tl" style="border:0;padding:0;background:none">${p.tdc}</div>
        <div class="ru-tl ru-ln" style="border:0;padding:0;background:none;display:flex;gap:12px;align-items:center">${p.mem}<span class="ru-grow" style="flex:1"></span>${p.lw}</div></a>`;
    }).join('');
    host.innerHTML = `<div class="ru-tiles">${body}</div><div class="ru-tl ru-btot">${tot}</div>`;
  }
}
"""


def static(pg) -> str:
    html = pg.evaluate("document.documentElement.outerHTML")
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    return "<!doctype html>\n" + html.replace("<head>", f'<head><base href="{UI}/">', 1)


def shoot(b, html, d, shape, width, name, height):
    pg = b.new_page(viewport={"width": width, "height": height}, color_scheme="dark")
    pg.set_content(html, wait_until="networkidle")
    if shape != "now":
        pg.evaluate(BUILD, [shape, d, CSS])
    pg.wait_for_timeout(1500 if shape == "A4" else 300)
    pg.screenshot(path=str(OUT / name))
    pg.close()


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1000}, color_scheme="dark")
    pg.goto(f"{UI}/")
    pg.wait_for_timeout(6000)
    d = pg.evaluate(READ)
    html = static(pg)
    pg.close()
    for r in d["rows"]:
        print({k: v for k, v in r.items() if k != "kbar"})
    for shape, w, h, name in (
        ("now", 1600, 560, "2026-10-28-rollup-0-now.png"),
        ("A", 1600, 760, "2026-10-28-rollup-A-rows.png"),
        ("B", 1600, 760, "2026-10-28-rollup-B-tiles.png"),
        ("A", 400, 1500, "2026-10-28-rollup-A-phone.png"),
        ("A2", 1600, 760, "2026-10-28-rollup-A2-rows.png"),
        ("A2", 400, 1300, "2026-10-28-rollup-A2-phone.png"),
        ("A3", 1600, 760, "2026-10-28-rollup-A3-rows.png"),
        ("A3", 400, 1100, "2026-10-28-rollup-A3-phone.png"),
        ("A5", 1600, 760, "2026-10-28-rollup-A5-chosen.png"),
        ("A5", 400, 1100, "2026-10-28-rollup-A5-phone.png"),
        ("A4", 1600, 760, "2026-10-28-rollup-A4-restyled.png"),
        ("A4", 400, 1300, "2026-10-28-rollup-A4-phone.png"),
    ):
        shoot(b, html, d, shape, w, name, h)
    b.close()
