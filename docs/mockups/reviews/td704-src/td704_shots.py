"""TD-704: a phase chip is the claimant's flow stage. Read-only against the live UI: capture the Sessions page,
take the first team card's summary, and in a static copy (scripts stripped) redraw its TDs in motion facet as

  now  today's chips, as drawn (design / grind / review)
  A    the `td` flow: design · build · review from flow.yml, colours by stage name; a hunter outside the flow
       shows its role's label in a neutral chip, last
  B    a repo flow [find, build, fact-check, review], `color: teal` on fact-check; the chip column widens to
       the flow's longest stage name

Shot at 1600 px in both themes.  Run:
  PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python td704_shots.py <out-dir>
"""

import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
UI = "http://127.0.0.1:8765"
TEAM = "ao-grind"

# the stage palette: one name, a light and a dark value (design §4.9c *a stage's colour*)
PALETTE_CSS = """
:root { --hue-pink:#db2777; --hue-indigo:#4f46e5; --hue-blue:#2563eb; --hue-amber:#d97706; --hue-teal:#0d9488;
        --hue-green:#059669; --hue-violet:#7c3aed; --hue-red:#dc2626; }
html[data-theme="dark"] { --hue-pink:#ec4899; --hue-indigo:#6366f1; --hue-blue:#3b82f6; --hue-amber:#d97706;
        --hue-teal:#14b8a6; --hue-green:#10b981; --hue-violet:#8b5cf6; --hue-red:#ef4444; }
.phase.st-out { background: var(--k-other); color: var(--k-other-fg); }
.t7-hue { --t7-dot: currentColor; }
.t7-cap { font: 600 13px/1.4 "IBM Plex Sans", sans-serif; color: var(--muted); margin: 0 0 6px 2px; }
.t7-yml { font: 12px/1.5 "JetBrains Mono", monospace; white-space: pre; background: var(--card); border: 1px solid var(--line);
          border-radius: 6px; padding: 8px 10px; margin: 8px 0 0; color: var(--fg); }
"""

ROWS = {  # (stage, css class, ref, priority, title, who, pr)
    "A": [
        ("design", "hue-indigo", "TD-704", "medium", "Phase chips from the flow's stages", "designer-ao-1", None),
        ("design", "hue-indigo", "TD-1491", "medium", "/shiftlead-feedback: digest seats' transcripts", "designer-ao-2", None),
        ("build", "hue-blue", "TD-1637", "high", "The brief is typed into a start-hooks pane until it is in", "grinder-ao-1", None),
        ("build", "hue-blue", "TD-1610", "medium", "The usage chip by account", "grinder-ao-2", None),
        ("review", "hue-amber", "TD-1502", "medium", "Own work on the Queue card", "grinder-ao-3", 3661),
        ("review", "hue-amber", "TD-1711", "high", "The Fable reset plan, design 2", "designer-ao-3", 3652),
        ("hunter", "st-out", "TD-1720", "", "Stale worktrees named by no branch", "hunter-ao-1", None),
    ],
    "B": [
        ("find", "hue-pink", "TD-1720", "", "Stale worktrees named by no branch", "hunter-ao-1", None),
        ("build", "hue-blue", "TD-1637", "high", "The brief is typed into a start-hooks pane until it is in", "grinder-ao-1", None),
        ("fact-check", "hue-teal", "TD-1655", "medium", "Design §4.9c's examples against the shipped flows", "grinder-ao-4", 3667),
        ("review", "hue-amber", "TD-1502", "medium", "Own work on the Queue card", "grinder-ao-3", 3661),
        ("review", "hue-amber", "TD-1711", "high", "The Fable reset plan, design 2", "grinder-ao-2", 3652),
    ],
}
YML = {
    "A": "# shiftlead/flows/td/flow.yml — no color: key, so each stage takes its name's default\nstages:\n"
         "  - {name: design, role: designer, lane: [design-first, \"owner:designer\"], brief: design.md}\n"
         "  - {name: build,  role: grinder,  lane: [free-pick, \"owner:grinder\"],     brief: build.md}\n"
         "  - {name: review, role: techlead,                                          brief: review.md}\n"
         "# hunter-ao-1's role is in no stage: its claim reads its role's label, grey, last",
    "B": "# <repo>/.shiftlead/flows/checked/flow.yml\nstages:\n"
         "  - {name: find,       role: hunter,   lane: [free],      brief: find.md}\n"
         "  - {name: build,      role: grinder,  lane: [free-pick], brief: build.md}\n"
         "  - {name: fact-check, role: checker,  color: teal,       brief: check.md}\n"
         "  - {name: review,     role: techlead,                    brief: ../td/review.md}",
}
ORDER = {"A": ["design", "build", "review", "hunter"], "B": ["find", "build", "fact-check", "review"]}


def rows_html(shape: str) -> str:
    out = []
    for stage, cls, ref, prio, title, who, pr in ROWS[shape]:
        bg = f"background: var(--{cls})" if cls.startswith("hue-") else ""
        p = (f'<span class="mprio bseg p-{prio}" title="{prio.capitalize()}">{prio[0].upper()}</span>'
             if prio else '<span class="mprio"></span>')
        out.append(
            f'<div class="mrow"><span class="mphase"><span class="phase {cls}" style="{bg}">{stage}</span></span>{p}'
            f'<span class="mref mono strong">{ref}</span><span class="mtitle">{html.escape(title)}</span>'
            f'<span class="mwho"><span class="name">{who}</span></span>'
            f'<span class="mpr">{f"<span>#{pr}</span>" if pr else ""}</span></div>')
    counts = {}
    for r in ROWS[shape]:
        counts[r[0]] = counts.get(r[0], 0) + 1
    meta = " · ".join(f"{counts[s]} {s}" for s in ORDER[shape] if counts.get(s))
    return (f'<div class="fhead"><span class="kind">TDs in motion ({len(ROWS[shape])})</span> '
            f'<span class="meta">{meta}</span></div>' + "".join(out))


INJECT = r"""
([sel, body, yml, cap, chipw]) => {
  const f = document.querySelector(sel + ' .fmotion');
  const mv = f.querySelector('[data-mv="motion"]');
  mv.innerHTML = body;
  f.querySelectorAll('[data-mv="completed"]').forEach((e) => e.remove());
  f.querySelectorAll('.mrow').forEach((r) => { r.style.gridTemplateColumns = r.style.gridTemplateColumns || ''; });
  if (chipw) f.querySelectorAll('.mrow').forEach((r) => r.style.gridTemplateColumns =
    `${chipw}px 18px calc(8 * var(--mch)) minmax(0,1fr) calc(13 * var(--mch)) calc(5 * var(--mch))`);
  else f.style.setProperty('--ref-n', 8), f.style.setProperty('--who-n', 13), f.style.setProperty('--pr-n', 5);
  const wrap = document.createElement('div');
  wrap.id = 't7';
  wrap.style.cssText = 'padding:16px;background:var(--bg);width:1560px';
  wrap.innerHTML = `<div class="t7-cap">${cap}</div>`;
  const card = f.closest('.tsum');
  wrap.appendChild(card);
  if (yml) { const pre = document.createElement('div'); pre.className = 't7-yml'; pre.textContent = yml; wrap.appendChild(pre); }
  document.body.innerHTML = '';
  document.body.appendChild(wrap);
}
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.goto(UI + "/", wait_until="networkidle")
        page = pg.evaluate("() => { document.querySelectorAll('script').forEach((s) => s.remove()); return document.documentElement.outerHTML; }")
        page = page.replace("<head>", f'<head><base href="{UI}/"><style>{PALETTE_CSS}</style>', 1)
        caps = {
            "now": "Now: fixed chips — DESIGN · GRIND · REVIEW (the live card)",
            "A": "A — the td flow: the chips are its stages, design · build · review; a hunter outside the flow reads its role, grey, last",
            "B": "B — a repo's own flow: find · build · fact-check · review; fact-check says color: teal; the chip column fits the longest name",
        }
        for theme in ("light", "dark"):
            for shape in ("now", "A", "B"):
                pg.set_content(page.replace("<html", f'<html data-theme="{theme}"', 1), wait_until="networkidle")
                if shape == "now":
                    body, yml, chipw = None, "", 0
                    pg.evaluate("""([sel, cap]) => { const card = document.querySelector(sel); const f = card.querySelector('.fmotion');
                      f.querySelectorAll('[data-mv="completed"]').forEach((e) => e.remove());
                      const w = document.createElement('div'); w.id = 't7'; w.style.cssText = 'padding:16px;background:var(--bg);width:1560px';
                      w.innerHTML = `<div class="t7-cap">${cap}</div>`; w.appendChild(card); document.body.innerHTML = ''; document.body.appendChild(w); }""",
                                [f"#tsum-{TEAM}", caps["now"]])
                else:
                    chipw = 86 if shape == "B" else 0
                    pg.evaluate(INJECT, [f"#tsum-{TEAM}", rows_html(shape), YML[shape], caps[shape], chipw])
                pg.locator("#t7").screenshot(path=str(OUT / f"td704-{shape}-{theme}.png"))
        b.close()


main()
