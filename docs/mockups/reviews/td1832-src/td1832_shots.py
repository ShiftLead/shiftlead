"""TD-1832 round 0 (for Paul): one answer set on every Queue item, and no press left stranded.

Static: the page is built here from the repo's own app.css (its tokens and buttons), so nothing live is read.
Run from the repo root:
  PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python \
    docs/mockups/reviews/td1832-src/td1832_shots.py docs/mockups/reviews/2026-11-14-td1832
It writes <prefix>-{today,one-set,tray}-{light,dark}.png and <prefix>-one-set-phone.png.
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[4]
CSS_APP = (ROOT / "src/shiftlead/ui/static/app.css").read_text()
OUT = sys.argv[1]

CSS = """
body { padding: 20px 24px 40px; }
.m32-page { max-width: 1320px; margin: 0 auto; }
.m32-cap { font-size: var(--t-small); color: var(--muted); margin: 0 0 14px; max-width: 90ch; }
.m32-cap b { color: var(--fg); }
.m32-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); gap: 18px 22px; align-items: start; }
.m32-colh { font-size: var(--t-title); font-weight: 600; margin: 4px 0 8px; }
.m32-kind { font-size: var(--t-small); color: var(--muted); margin: 14px 0 4px; }
.m32-item { background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--needs); border-radius: 4px; padding: 10px 12px 0; }
.m32-head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; font-size: var(--t-small); color: var(--muted); }
.m32-head .m32-mark { font-weight: 600; color: var(--needs-fg); background: var(--needs-bg); border-radius: 3px; padding: 0 6px; }
html[data-theme="dark"] .m32-head .m32-mark { color: #fde68a; background: #4a3410; }
.m32-head .m32-grow { flex: 1; }
.m32-head a { color: var(--link); text-decoration: none; }
.m32-sent { margin: 4px 0 2px; }
.m32-ctx { font-size: var(--t-small); color: var(--muted); margin: 2px 0 6px; }
.m32-dflt { font-size: var(--t-small); color: var(--strong); margin: 0 0 6px; }
/* the one answer set: one row, three groups, the same places on every item */
.m32-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; border-top: 1px solid var(--line2); margin: 6px -12px 0; padding: 8px 12px; }
.m32-bar .m32-g { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.m32-bar .m32-grow { flex: 1; min-width: 12px; }
.m32-bar .btn.sm.ghost { border-color: var(--border); }
.m32-bar .btn.sm.ghost.m32-rec { border: 2px solid var(--link); }
.m32-bar .btn.m32-pressed { background: var(--ended-bg); }
.m32-bar .btn.m32-pressed::before { content: "✓"; color: var(--done); }
.m32-bar .m32-sep { width: 1px; align-self: stretch; background: var(--line); margin: 2px 4px; }
.m32-bar .m32-quiet { color: var(--muted); }
.m32-why { height: 26px; border: 1px solid var(--border); border-radius: 4px; background: var(--input); color: var(--fg); padding: 0 6px; font: inherit; font-size: var(--t-small); }
/* what happened, in a fixed slot just above the bar */
.m32-said { margin: 6px 0 0; padding: 6px 10px; border-left: 3px solid var(--idle); background: var(--idle-bg); color: var(--idle-fg); font-size: var(--t-small); border-radius: 0 3px 3px 0; }
.m32-said.m32-stuck { border-left-color: var(--needs); background: var(--warn-bg); color: var(--warn-fg); }
.m32-said.m32-refused { border-left-color: var(--stalled); background: var(--stalled-bg); color: var(--stalled-fg); }
html[data-theme="dark"] .m32-said { background: #14243d; color: #bcd4f6; }
html[data-theme="dark"] .m32-said.m32-stuck { background: #33240c; color: #fcd9a8; }
html[data-theme="dark"] .m32-said.m32-refused { background: #3a1616; color: #f8c4c4; }
/* today's drawing, as the live page has it */
.m32-old .m32-line { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 6px 0; }
.m32-old .m32-line.m32-right { justify-content: flex-end; }
.m32-old .btn.sm.ghost { border-color: var(--border); }
.m32-old .m32-out { font-size: var(--t-small); color: var(--muted); }
.m32-old .m32-out b { color: var(--stalled-fg); font-weight: 600; }
.m32-old .m32-foot { font-size: var(--t-small); color: var(--muted); padding: 2px 0 8px; }
/* the tray: the frontend-design skill's own pick, free of the house style */
.m32-tray .m32-item { border-left-color: transparent; border-radius: 10px; padding: 14px 16px 0; box-shadow: 0 1px 0 var(--line); }
.m32-tray .m32-head .m32-mark { background: transparent; color: var(--needs-fg); padding: 0; font-variant: small-caps; letter-spacing: .03em; }
html[data-theme="dark"] .m32-tray .m32-head .m32-mark { color: var(--needs); background: transparent; }
.m32-tray .m32-sent { font-size: 17px; line-height: 1.4; font-weight: 500; }
.m32-tray .m32-bar { margin: 10px -16px 0; padding: 10px 16px 12px; background: var(--hover); border-top: 0; border-radius: 0 0 10px 10px; }
.m32-tray .m32-seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--card); }
.m32-tray .m32-seg button { border: 0; border-right: 1px solid var(--line); background: transparent; color: var(--fg); font: inherit; font-size: var(--t-btn); padding: 6px 12px; cursor: pointer; display: inline-flex; gap: 8px; align-items: center; }
.m32-tray .m32-seg button:last-child { border-right: 0; }
.m32-tray .m32-seg button.m32-rec { background: var(--idle-bg); color: var(--idle-fg); font-weight: 600; }
html[data-theme="dark"] .m32-tray .m32-seg button.m32-rec { background: #14243d; color: #bcd4f6; }
.m32-tray .m32-key { font-family: "JetBrains Mono", monospace; font-size: var(--t-cap); color: var(--muted); border: 1px solid var(--border); border-radius: 3px; padding: 0 4px; }
.m32-tray .m32-said { border-left: 0; border-radius: 8px; margin: 10px 0 0; }
.m32-tray .m32-link { color: var(--link); font-size: var(--t-small); text-decoration: none; }
@media (max-width: 600px) { body { padding: 12px 16px 30px; } .m32-cols { grid-template-columns: 1fr; } }
"""


def btn(label, cls="ghost", extra=""):
    return f'<button class="btn sm {cls} {extra}" type="button">{label}</button>'


def head(mark, where, right):
    return (f'<div class="m32-head"><span class="m32-mark">{mark}</span><span>{where}</span>'
            f'<span class="m32-grow"></span><span>{right}</span></div>')


def bar(answers, answer_box=True, start="Start session", dismiss=False, open_label="Open", dots=True):
    """The one set: [its answers] [Answer…] | [Start session] ··· [Dismiss] [Open] [⋯]."""
    left = "".join(answers) + (btn("Answer…") if answer_box else "")
    mid = btn(start, "") if start else ""
    right = (btn("Dismiss", "ghost", "m32-quiet") if dismiss else "") + btn(open_label) + (btn("⋯", "ghost") if dots else "")
    sep = '<span class="m32-sep"></span>' if mid else ""
    return (f'<div class="m32-bar"><span class="m32-g">{left}</span>{sep}<span class="m32-g">{mid}</span>'
            f'<span class="m32-grow"></span><span class="m32-g">{right}</span></div>')


def item(h, sent, ctx="", dflt="", said="", b=""):
    return (f'<div class="m32-item">{h}<div class="m32-sent">{sent}</div>'
            + (f'<div class="m32-dflt">{dflt}</div>' if dflt else "")
            + (f'<div class="m32-ctx">{ctx}</div>' if ctx else "")
            + said + b + "</div>")


def said(text, kind=""):
    return f'<div class="m32-said {kind}">{text}</div>'


CTX = "▸ context"
GATE = "Decide whether TD-1796 goes ahead: Fable rounds on every design, or Sonnet alone for in-repo ones."
ASK = "TD-1796 is held for you. May I lift the hold and start the build?"
STEER = "TD-108 slice 2 found a gap the TD-098 plan leaves open: drop the item-line start from the fixtures?"
DECIDE = "TD-1832's design rounds have ended. Go, one more round, or hold with a note?"
ACT = "Once #2820 is live, turn on push on your iPhone and confirm one notification arrives."
PERM = "grinder-ao-1 wants to run <code>gh pr merge 3838 --squash</code>."

# ---- the one answer set, every kind -------------------------------------------------------------
ONE = [
    ("A ledger entry held for you", item(
        head("Decide", "TD-1796 · held for you in shiftlead's ledger", "added Nov 14"), GATE, CTX,
        b=bar([btn("Lift the hold", "ghost", "m32-rec")]))),
    ("A session's question (ask)", item(
        head("Decide", 'asked by <a href="#">grinder-ao-2</a> · on TD-1796', "2h ago"), ASK, CTX,
        b=bar([btn("Lift it", "ghost", "m32-rec"), btn("Keep it held")]))),
    ("A session's steer", item(
        head("Decide", 'steer from <a href="#">lb-grinder</a> · on TD-108', "3h ago"), STEER, CTX,
        dflt="Unless you say otherwise by 9 pm: drop it, and exempt it by name in the tests.",
        b=bar([btn("Go with it", "ghost", "m32-rec")]))),
    ("A decision on a repo's board", item(
        head("Decide", "from shiftlead's board · holds TD-1840, TD-1841", "due tomorrow"), DECIDE, CTX,
        b=bar([btn("Go", "ghost", "m32-rec"), btn("One more round"), btn("Hold…")]))),
    ("A step on a repo's board (act)", item(
        head("Do", "from shiftlead's board · on TD-1305", "due 10 days ago"), ACT, CTX,
        b=bar([btn("Done"), btn("Have a session do it")]))),
    ("A session waiting on a permission", item(
        head("Do", '<a href="#">grinder-ao-1</a> is waiting on you', "4 min"), PERM, "",
        b=bar([btn("Allow"), btn("Deny"), '<input class="m32-why" placeholder="why?" size="14">'],
              answer_box=False, start=None, dots=False))),
]

# ---- a press that did not finish: the set stays, a sentence says what happened ----------------
STUCK = [
    ("An ask you answered, which the session could not do", item(
        head("Do", 'asked by <a href="#">grinder-ao-2</a> · on TD-1796', "2h ago"), ASK, CTX,
        said=said("You answered <b>Lift it</b>. grinder-ao-2 could not do it: a session may not lift your hold. "
                  "Press <b>Lift the hold</b> to lift TD-1796's hold yourself, answer again, or start a session.",
                  "m32-stuck"),
        b=bar([btn("Lift the hold", "ghost", "m32-rec"), btn("Lift it", "ghost", "m32-pressed"),
               btn("Keep it held")], dismiss=True))),
    ("A held entry whose answer is still with a session", item(
        head("Decide", "TD-1796 · held for you in shiftlead's ledger", "added Nov 14"), GATE, CTX,
        said=said("You answered <b>\u201cLift it\u201d</b> in grinder-ao-2's ask, 2 hours ago \u2014 the hold goes "
                  "when its PR merges.")
        , b=bar([btn("Lift the hold", "ghost", "m32-rec")]))),
    ("A press that was refused", item(
        head("Decide", "from shiftlead's board · holds TD-1840, TD-1841", "due tomorrow"), DECIDE, CTX,
        said=said("<b>Go</b> was not written: the line changed after this page was drawn, and nothing was sent. "
                  "It now reads as above; press again to answer it.", "m32-refused"),
        b=bar([btn("Go", "ghost", "m32-rec"), btn("One more round"), btn("Hold…")]))),
]

# ---- today, as the live Queue draws them ------------------------------------------------------
def old(h, sent, *lines, foot=""):
    body = "".join(f'<div class="m32-line {c}">{x}</div>' for c, x in lines)
    return (f'<div class="m32-item m32-old">{h}<div class="m32-sent">{sent}</div><div class="m32-ctx">{CTX}</div>'
            + body + (f'<div class="m32-foot">{foot}</div>' if foot else "") + "</div>")


TODAY = [
    ("A ledger entry held for you", old(
        head("Decide", "· from the ledger · held until you decide", "added Nov 14 · M"), GATE,
        ("", btn("Lift the hold") + btn("Answer…") + btn("Start session", "")),
        foot="in shiftlead's ledger — waits on you, with no date")),
    ("A session's question (ask)", old(
        head("Ask", 'grinder-ao-2 <button class="btn sm ghost">Open</button> re TD-1796', "2h 3m · whole entry ›"),
        ASK, ("", btn("Lift it") + btn("Keep it held") + btn("Answer…") + btn("Start session", "")),
        ("m32-right", btn("Dismiss") + btn("Snooze ▾")))),
    ("A decision on a repo's board", old(
        head("Decide", "· from shiftlead's board", "due tomorrow"), DECIDE,
        ("", btn("Go") + btn("One more round") + btn("Hold…") + btn("Answer…") + btn("Start session", "")
         + btn("⋯", "ghost")))),
    ("A step on a repo's board (act)", old(
        head("Do", "· from shiftlead's board", "due 10 days ago"), ACT,
        ("", btn("Done") + btn("Have a session do it") + btn("Start session", "") + btn("⋯", "ghost")),
        foot="Answer… is in the ⋯")),
    ("The ask after you answered it (TD-1796, Nov 14)", old(
        head("Ask", 'grinder-ao-2 <button class="btn sm ghost">Open</button> re TD-1796', "2h 3m"), ASK,
        ("", '<span class="m32-out">outcome · <b>blocked</b> — a session may not lift a hold; the person must</span>'),
        ("", btn("Answer…")), ("m32-right", btn("Open") + btn("Dismiss")))),
    ("The held entry after that answer", old(
        head("Decide", "· from the ledger", "added Nov 14 · M"), GATE,
        ("", '<span class="m32-out">answered — waiting on grinder-ao-2</span>'),
        foot="no buttons")),
]


def col(title, cap, rows):
    out = f'<div><div class="m32-colh">{title}</div><div class="m32-cap">{cap}</div>'
    for kind, html in rows:
        out += f'<div class="m32-kind">{kind}</div>{html}'
    return out + "</div>"


def page(theme, body, extra_cls=""):
    return (f'<!doctype html><html data-theme="{theme}"><head><meta charset="utf-8">'
            f'<style>{CSS_APP}</style><style>{CSS}</style></head>'
            f'<body><div class="m32-page {extra_cls}">{body}</div></body></html>')


INTRO = ('<div class="m32-cap"><b>Mockup, TD-1832.</b> Every item ends in the same answer bar, in the same order: '
         'its own answers (the recommended one outlined), then <b>Answer…</b> for your own words, then '
         '<b>Start session</b>; at the right, <b>Dismiss</b> where the item can be dismissed (a report, never an open question), <b>Open</b>, and '
         '<b>⋯</b>. A slot the item has no use for is left out, and the right group stays at the right. '
         'The heading names what the item is and who asks; it holds no buttons.</div>')

BODIES = {
    "today": '<div class="m32-cap"><b>Today, for comparison.</b> How the live Queue draws each kind now: the '
    "buttons change place and name from kind to kind, and an answer that did not finish leaves Answer… alone, "
    "or nothing.</div>"
    + '<div class="m32-cols">' + col("Today", "", TODAY[:4]) + col("Today, after a press that did not finish", "",
                                                                   TODAY[4:]) + "</div>",
    "one-set": INTRO + '<div class="m32-cols">'
    + col("One answer set", "Every kind, the same bar.", ONE)
    + col("A press that did not finish",
          "The bar stays whole. One sentence above it says what happened and what you can do next; the answer "
          "you pressed is ticked.", STUCK) + "</div>",
    "tray": '<div class="m32-cap"><b>The frontend-design skill\'s own pick</b>, free of the house style: the '
    "answers as one segmented control with their number keys, sitting in a tray at the foot of the item, and the "
    "what-happened sentence inside the tray. Adopting it would mean restyling the Inbox's rows to match.</div>"
    '<div class="m32-cols m32-tray">' + col("The tray", "", []) + "</div>",
}


def tray_item(h, sent, answers, rec, said_html="", start="Start session", dismiss=False):
    seg = "".join(f'<button class="{"m32-rec" if a == rec else ""}"><span class="m32-key">{i + 1}</span>{a}</button>'
                  for i, a in enumerate(answers))
    right = ('<a class="m32-link" href="#">Dismiss</a> · ' if dismiss else "") + '<a class="m32-link" href="#">Open</a>'
    return (f'<div class="m32-item">{h}<div class="m32-sent">{sent}</div><div class="m32-ctx">{CTX}</div>'
            f'<div class="m32-bar">{said_html}<span class="m32-seg">{seg}</span>{btn("Answer…")}{btn(start, "")}'
            f'<span class="m32-grow"></span>{right}{btn("⋯", "ghost")}</div></div>')


TRAY = [
    ("A ledger entry held for you", tray_item(head("Decide", "TD-1796 · held for you in shiftlead's ledger", "Nov 14"),
                                              GATE, ["Lift the hold"], "Lift the hold")),
    ("A session's question (ask)", tray_item(head("Decide", 'asked by <a href="#">grinder-ao-2</a>', "2h ago"), ASK,
                                             ["Lift it", "Keep it held"], "Lift it", dismiss=True)),
    ("A decision on a repo's board", tray_item(head("Decide", "from shiftlead's board", "due tomorrow"), DECIDE,
                                               ["Go", "One more round", "Hold…"], "Go")),
    ("An ask you answered, which the session could not do", tray_item(
        head("Decide", 'asked by <a href="#">grinder-ao-2</a>', "2h ago"), ASK, ["Lift it", "Keep it held"], "",
        said_html='<div class="m32-said m32-stuck" style="flex-basis:100%;margin:0 0 6px">You answered <b>Lift it</b>. '
        "grinder-ao-2 could not do it: a session may not lift your hold. Press <b>Lift the hold</b> on TD-1796, "
        "answer again, or start a session.</div>", dismiss=True)),
]
BODIES["tray"] = BODIES["tray"].replace('<div class="m32-cols m32-tray"><div><div class="m32-colh">The tray</div>'
                                        '<div class="m32-cap"></div></div></div>',
                                        '<div class="m32-cols m32-tray">' + col("The tray", "", TRAY[:2])
                                        + col("", "", TRAY[2:]) + "</div>")

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, body in BODIES.items():
        for theme in ("light", "dark"):
            pg = b.new_page(viewport={"width": 1400, "height": 900}, color_scheme=theme)
            pg.set_content(page(theme, body))
            pg.screenshot(path=f"{OUT}-{name}-{theme}.png", full_page=True)
            pg.close()
    pg = b.new_page(viewport={"width": 420, "height": 900})
    pg.set_content(page("light", BODIES["one-set"]))
    pg.screenshot(path=f"{OUT}-one-set-phone.png", full_page=True)
    b.close()
