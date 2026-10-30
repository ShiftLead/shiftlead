"""TD-1190's review shots: the proposed Add entry form on the app's own CSS, as a static page.

Run from the repo root (headless Chromium, docs/claude-memory/headless-screenshots-on-kmaster.md):

    PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python docs/mockups/reviews/td1190-src/td1190_shots.py

Writes docs/mockups/reviews/2026-10-28-td1190-add-entry-{wide,taken,phone}.png; the -before.png beside them is the
form as built on 2026-10-28, shot from a scratch home, not made here. Every mockup class is
prefixed `ae-` (app.css defines the short generic names); the rest are the app's own classes.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
STATIC = ROOT / "src/shiftlead/ui/static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")  # inlined: a set_content page reads no file:// sheet
OUT = ROOT / "docs/mockups/reviews"

STYLE = """
body { background: var(--bg); padding: 16px; }
.ae-dlg { position: static; display: block; margin: 0 auto; width: min(720px, 94vw); box-sizing: border-box; }
.ae-head { display: flex; align-items: flex-start; gap: 10px; }
.ae-title { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 10px; row-gap: 2px; min-width: 0; flex: 1; }
.ae-where { font-family: "JetBrains Mono", monospace; font-size: var(--t-mono-s); color: var(--muted); }
.ae-opts { display: flex; flex-wrap: wrap; gap: 6px; }
.ae-opt { display: flex; align-items: center; gap: 8px; padding: 5px 12px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--card); }
.ae-opt.ae-on { border-color: var(--strong); }
.ae-opt input { margin: 0; }
.ae-hint { font-size: var(--t-small); color: var(--muted); }
.ae-ways { border-top: 1px solid var(--border); padding-top: 14px; display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ae-way { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.ae-way + .ae-way { border-left: 1px solid var(--border); padding-left: 16px; }
.ae-way:first-child { padding-right: 16px; }
.ae-btnline { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ae-btnline.ae-named { flex-wrap: nowrap; }
.ae-name { width: auto; flex: 1 1 0; min-width: 0; max-width: 180px; box-sizing: border-box; height: 30px; font-family: "JetBrains Mono", monospace; font-size: var(--t-mono-s); }
.ae-name.ae-bad { border-color: #dc2626; }
.ae-bad-line { color: #b91c1c; }
@media (max-width: 640px) {
  .ae-ways { grid-template-columns: minmax(0, 1fr); row-gap: 14px; }
  .ae-way + .ae-way { border-left: 0; padding-left: 0; border-top: 1px solid var(--border); padding-top: 14px; }
  .ae-way:first-child { padding-right: 0; }
  .ae-opts { display: grid; grid-template-columns: repeat(var(--ae-n), minmax(0, 1fr)); }
  .ae-opt { align-items: flex-start; }
  .ae-opt .ae-hint { display: block; }
}
.ae-word { display: flex; flex-wrap: wrap; column-gap: 6px; align-items: baseline; }
"""


def form(name: str, taken: bool) -> str:
    bad = " ae-bad" if taken else ""
    line = (
        f'<span class="note ae-bad-line">{name} is running — switch to it, or pick another name</span>'
        if taken
        else '<span class="note">Starts an interactive designer session in a new worktree, with your words in its'
        " composer, not sent.</span>"
    )
    go = "disabled" if taken else ""

    def opt(word: str, hint: str, on: bool, group: str) -> str:
        h = f'<span class="ae-hint">{hint}</span>' if hint else ""
        return (
            f'<label class="ae-opt{" ae-on" if on else ""}"><input type="radio" name="{group}"'
            f'{" checked" if on else ""}><span class="ae-word"><span>{word}</span>{h}</span></label>'
        )

    return f"""
<div class="card pad ae-dlg"><div class="col gap">
  <div class="ae-head"><div class="ae-title"><span class="h2">Add an entry to the ledger</span>
    <span class="ae-where">shiftlead · docs/ledger</span></div>
    <button class="btn sm ghost">Close</button></div>
  <div class="field"><label>What</label>
    <span class="note">A title or a page: the number, the header lines and the locations are found for you.</span>
    <textarea class="input" style="height: 84px; padding: 8px 10px;">The Sessions page's filter forgets its text when the page reloads.</textarea></div>
  <div class="row gap" style="margin-top: -6px;"><button class="btn sm">Attach</button>
    <span class="note">or paste a screenshot, or drop a file on the box.</span></div>
  <div class="field"><label>Type</label><div class="ae-opts" style="--ae-n: 2;">
    {opt("debt", "something wrong now", True, "t")}{opt("feature", "something new", False, "t")}</div></div>
  <div class="field"><label>Priority</label><div class="ae-opts" style="--ae-n: 3;">
    {opt("High", "", False, "p")}{opt("Medium", "", True, "p")}{opt("Low", "", False, "p")}</div></div>
  <div class="ae-ways">
    <div class="ae-way">
      <div class="ae-btnline"><button class="btn primary">Hand to the techlead</button><span class="mono">techlead-ao-1</span></div>
      <span class="note">Drafts the entry and lands it by PR; its questions and the result come to your Inbox.</span>
      <span class="note">No techlead is running: one starts on the next tick and reads it first.</span>
    </div>
    <div class="ae-way">
      <div class="ae-btnline ae-named"><button class="btn" {go}>Open a session</button><span class="note">named</span>
        <input class="input ae-name{bad}" value="{name}"></div>
      {line}
    </div>
  </div>
</div></div>"""


def page(body: str) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><base href="{STATIC.as_uri()}/"><style>{CSS}</style><style>{STYLE}</style></head><body>{body}</body></html>'


SHOTS = (("wide", 760, form("entry-3", False)), ("taken", 760, form("entry-2", True)), ("phone", 390, form("entry-3", False)))

with sync_playwright() as p:
    b = p.chromium.launch()
    for key, width, body in SHOTS:
        pg = b.new_page(viewport={"width": width, "height": 400}, color_scheme="light")
        pg.set_content(page(body))
        pg.locator(".ae-dlg").screenshot(path=str(OUT / f"2026-10-28-td1190-add-entry-{key}.png"))
        pg.close()
    b.close()
