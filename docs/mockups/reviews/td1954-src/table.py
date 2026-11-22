"""The Flows page as records (TD-1954, 2026-11-20): each stage's model, actions and outcomes.

E: the built-in flow `td`, read-only. F: a flow of the person's own being edited.
Every outcome names what is checked before it is accepted, and where the entry goes next.
Run: PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python table.py <out-dir>
"""

import sys
from pathlib import Path

from build import CSS, nav, page

TCSS = """
.lim { display:flex; gap:22px; flex-wrap:wrap; font-size:13.5px; color:var(--soft); margin:10px 0 18px; }
.lim b { color:var(--ink); font-weight:600; font-family:"IBM Plex Mono", monospace; }
.rec { display:grid; grid-template-columns:34px 240px 1fr; background:var(--sheet); border:1px solid var(--rule2); border-radius:6px; margin-bottom:10px; }
.rec .n { display:grid; place-items:start center; padding-top:13px; border-radius:6px 0 0 6px; color:#fff; font-weight:600; }
.rec .who { padding:11px 16px 12px; border-right:1px solid var(--rule2); }
.rec .nm { font-weight:600; font-size:17px; }
.key { font:500 13px "IBM Plex Mono", monospace; background:#FFF1B8; border:1px solid #E2C55A; border-radius:3px; padding:0 7px; white-space:nowrap; }
.rec dl { margin:8px 0 0; display:grid; grid-template-columns:58px 1fr; gap:5px 8px; font-size:13px; }
.rec dt { color:var(--soft); } .rec dd { margin:0; }
.m { font:600 13px "IBM Plex Mono", monospace; }
.acts a { display:inline-block; font-size:13px; font-weight:500; border:1px solid var(--rule); border-radius:3px; padding:0 8px; margin:0 4px 3px 0; background:#fff; color:var(--ink); }
.acts a small { color:var(--soft); font-weight:400; }
.ends { padding:7px 16px 8px; }
.ends .h, .ends .e { display:grid; grid-template-columns:150px 1fr 215px; gap:14px; align-items:baseline; }
.ends .h { white-space:nowrap; font-size:11.5px; letter-spacing:.05em; text-transform:uppercase; color:var(--soft); padding-bottom:3px; border-bottom:1px solid var(--rule); }
.ends .e { font-size:14px; padding:4px 0; border-bottom:1px dashed var(--rule2); }
.ends .e:last-child { border-bottom:none; }
.by { font-size:13px; color:var(--soft); }
.upto { font-size:12.5px; color:var(--soft); display:block; margin-top:1px; }
.upto b { color:var(--ink); font-weight:600; }
.by.s { color:var(--design); }
.to { font-size:13.5px; }
.to .back { color:var(--bad); }
.to small { color:var(--soft); }
.you { font-size:13px; border:1px dashed var(--soft); border-radius:3px; padding:0 7px; }
.done { font-size:13px; color:var(--on); font-weight:600; }
.same { font-size:13px; color:var(--soft); }
.all { background:none; border-style:dashed; }
.all .n { background:var(--off); }
.out { display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; }
.out div { background:var(--sheet); border:1px solid var(--rule2); border-radius:6px; padding:8px 12px; font-size:13.5px; box-shadow:inset 3px 0 0 var(--call); }
.out b { display:block; font-weight:600; }
.out span { color:var(--soft); font-size:13px; }
.chk { display:grid; grid-template-columns:1fr 1fr; gap:6px 28px; font-size:14px; }
.chk div::before { content:"✓ "; color:var(--on); font-weight:700; }
.chk div small { color:var(--soft); }
.chk div.i::before { content:"→ "; color:var(--soft); }
"""

YOU, DONE = '<span class="you">you</span>', '<span class="done">done</span>'
HOME = "found by the home"
PR_OPEN = "it is open and its checks are green"
VERDICT = "a verdict is posted on this head"
MERGED = "the pull request is merged"
CANT = "it changed since review, or is red or conflicting"
REASON = "a reason is given"
PARTS = "the parts are filed"
WAITS = '<span class="same">waits for its parts</span>'
HDR = '<div class="h"><span>Outcome</span><span>Checked first</span><span>Next</span></div>'


def key(k):
    return f'<span class="key">Stage: {k}</span>'


def fwd(k):
    return f"→ {key(k)}"


def upto(k, n, extra=""):
    return f'→ {key(k)}<span class="upto">up to <b>{n}</b> times{extra}, then you</span>'


def same(a):
    return f'<span class="same">the next action, {a}</span>'


def rec(n, color, name, model, takes, acts, ends, cls=""):
    a = "".join(f"<a>{x}</a>" for x in acts)
    e = "".join(f'<div class="e"><span>{t}</span><span class="by">{c}</span><span class="to">{to}</span></div>' for t, c, to in ends)
    dl = f"<dt>Model</dt><dd class='m'>{model}</dd>" if model else ""
    dl += f"<dt>Takes</dt><dd>{takes}</dd>" if takes else ""
    dl += f"<dt>Does</dt><dd class='acts'>{a}</dd>" if a else ""
    return (
        f'<div class="rec {cls}"><div class="n" style="background:{color}">{n}</div>'
        f'<div class="who"><div class="nm">{name}</div><dl>{dl}</dl></div>'
        f'<div class="ends">{HDR}{e}</div></div>'
    )


def every(you_stuck=YOU, again='<span class="same">offered again</span>'):
    return rec("∗", "var(--off)", "Every stage", "", "", [], [
        ("question", "a question is given", f"{YOU} <small>with a board item</small>"),
        ("stuck", REASON, you_stuck),
        ("session lost", HOME, again),
        ("session silent for 4 h", HOME, '<span class="same">offered again once, then you</span>'),
    ], cls="all")


OUT_P = "<h3>Outside the flow</h3><p>These take no entry and set no stage. They are here to be given a model.</p>"


def td():
    body = (
        '<div class="fhead"><h2>td</h2><span class="id">format 2</span><span class="tag">built in</span>'
        '<div class="act"><button>Copy</button></div></div>'
        '<p class="used">Used by <b>ao-grind</b>, <b>docs</b>.</p>'
        '<div class="lim"><span>A far-reaching design gets <b>6</b> rounds</span><span>A session is silent after <b>4 h</b></span></div>'
        + rec(1, "var(--design)", "Design", "fable", "a design-first entry with no stage yet", ["Design"], [
            ("pull request open", PR_OPEN, fwd("design-rounds")),
            ("split into parts", PARTS, WAITS),
            ("not needed", REASON, YOU),
        ])
        + rec(2, "var(--review)", "Design rounds", "sonnet, fable <small>in turn</small>", "", ["Review <small>reviewers in turn</small>"], [
            ("ship", "each reviewer's verdict is posted on this head", fwd("fact-check")),
            ("changes wanted", "a verdict is posted", upto("design", 3, ", 6 if far-reaching")),
        ])
        + rec(3, "var(--find)", "Fact-check", "sonnet", "", ["Fact-check", "Merge"], [
            ("ship", VERDICT, same("Merge")),
            ("changes wanted", "a verdict is posted", upto("design", 3)),
            ("merged", MERGED, DONE),
            ("cannot merge", CANT, upto("design", 3)),
        ])
        + rec(4, "var(--build)", "Build", "opus", "any other entry with no stage yet", ["Build", "Live checks"], [
            ("pull request open", PR_OPEN, fwd("review")),
            ("design needs changing", REASON, YOU),
            ("split into parts", PARTS, WAITS),
            ("not needed", REASON, YOU),
        ])
        + rec(5, "var(--review)", "Review", "sonnet", "", ["Review <small>every pull request</small>"], [
            ("ship", VERDICT, fwd("second-read")),
            ("changes wanted", "a verdict is posted", upto("build", 3)),
        ])
        + rec(6, "var(--review)", "Second read", "opus", "", ["Review <small>protected paths, skipped when none are touched</small>", "Merge"], [
            ("ship", VERDICT, same("Merge")),
            ("changes wanted", "a verdict is posted", upto("build", 3)),
            ("merged", MERGED, DONE),
            ("cannot merge", CANT, upto("build", 3)),
        ])
        + every()
        + OUT_P
        + '<div class="out"><div><b>Questions</b><span class="m">opus</span> <span>answers members by mail</span></div>'
        '<div><b>Board answers</b><span class="m">sonnet</span> <span>acts on what you decided</span></div>'
        '<div><b>Pull requests nobody holds</b><span class="m">sonnet</span> <span>on the clock</span></div>'
        '<div><b>Manager</b><span class="m">sonnet</span> <span>starts and stops sessions</span></div></div>'
        "<h3>Does it flow?</h3><p></p>"
        '<div class="chk"><div>Every stage a Next names exists <small>6 of 6</small></div>'
        "<div>Every loop has a limit <small>4 loops</small></div>"
        "<div>Every pull request opened can reach Merge</div>"
        "<div>Every kind of entry has a way in <small>design-first, other</small></div>"
        '<div class="i">5 outcomes go to you, and 6 more at a limit <small>none by omission</small></div>'
        '<div class="i">A plain build changes stage 2 times <small>each round adds 2</small></div></div>'
    )
    cap = (
        "E — the built-in flow td as records. Each stage has a model, its actions, and its outcomes: "
        "what is checked before an outcome is accepted, and where the entry goes next."
    )
    return page("td", body, cap, sub="the stages an entry passes through, and where each outcome sends it").replace(
        "<style>", "<style>" + TCSS
    )


ECSS = """
.sel { display:inline-flex; align-items:center; gap:6px; font-size:13px; border:1px solid var(--rule); border-radius:3px; padding:0 8px; background:#fff; white-space:nowrap; }
.sel::after { content:"▾"; color:var(--soft); font-size:11px; }
.sel .key { border:none; background:none; padding:0; }
.sel.bad { border-color:var(--bad); color:var(--bad); background:#FBEDEA; }
.num { display:inline-block; min-width:30px; text-align:center; font:600 13px "IBM Plex Mono", monospace; border:1px solid var(--rule); border-radius:3px; background:#fff; padding:0 6px; }
.num { min-height:20px; vertical-align:middle; }
.ed-ends .h, .ed-ends .e { grid-template-columns:140px 1fr 235px; }
.num.bad { border-color:var(--bad); background:#FBEDEA; color:var(--bad); }
.fix { color:var(--off); font-size:13px; }
.nmf { font-weight:600; font-size:17px; border:1px solid var(--rule); border-radius:3px; background:#fff; padding:0 8px; display:inline-block; }
.slug { display:block; margin-top:3px; font:400 12px "IBM Plex Mono", monospace; color:var(--soft); }
.acts a .x { margin-left:6px; }
.acts .drop { display:inline-block; font-size:12.5px; color:var(--used); border:1.5px dashed var(--used); border-radius:3px; padding:0 8px; }
.rec .grip { color:#fff; opacity:.7; font-size:12px; margin-top:8px; }
.rec.err { border-color:var(--bad); }
.e.err span:first-child { color:var(--bad); }
.why { grid-column:1 / -1; font-size:12.5px; color:var(--bad); margin-top:-2px; }
.chg { font-size:12px; color:var(--used); }
.chk div.no::before { content:"✗ "; color:var(--bad); font-weight:700; }
.chk div.no { color:var(--bad); }
.lim .num { margin-left:4px; }
.probs { color:var(--bad); font-size:13px; align-self:center; }
button[disabled] { border-color:var(--rule); color:var(--off); background:var(--rule2); }
"""


def sel(inner, bad=False):
    return f'<span class="sel{" bad" if bad else ""}">{inner}</span>'


def num(n, bad=False):
    return f'<span class="num{" bad" if bad else ""}">{n}</span>'


def nx(k, n=None, bad=False, note=""):
    lim = "" if n is None else f'<span class="upto">up to {num(n, bad)} times, then you</span>'
    return f"{sel(key(k))}{note}{lim}"


def erec(n, color, name, model, takes, acts, ends, err=False):
    a = "".join(f'<a>{x}<span class="x">✕</span></a>' for x in acts) + '<span class="drop">drop an action here</span>'
    rows = ""
    for row in ends:
        t, c, to = row[:3]
        why = f'<span class="why">{row[3]}</span>' if len(row) > 3 else ""
        rows += f'<div class="e{" err" if why else ""}"><span>{t}</span><span class="by">{c}</span><span class="to">{to}</span>{why}</div>'
    slug = name.lower().replace(" ", "-")
    dl = f"<dt>Model</dt><dd>{model}</dd>"
    dl += f"<dt>Takes</dt><dd>{takes}</dd>" if takes else ""
    dl += f"<dt>Does</dt><dd class='acts'>{a}</dd>"
    return (
        f'<div class="rec{" err" if err else ""}"><div class="n" style="background:{color}">{n}<span class="grip">⠿</span></div>'
        f'<div class="who"><span class="nmf">{name}</span><span class="slug">Stage: {slug}</span><dl>{dl}</dl></div>'
        f'<div class="ends ed-ends">{HDR}{rows}</div></div>'
    )


def enav():
    def a(name, c, used=""):
        u = f"<i>{used}</i>" if used else ""
        return f'<a class="pal" style="--c:var(--{c})"><span class="grip">⠿</span> {name}{u}</a>'

    return (
        '<nav><a class="back">← All flows</a><h4>Actions</h4>'
        '<p class="why" style="color:var(--soft)">Drag one into a stage. Each brings its own outcomes.</p>'
        "<h4>In the path</h4>" + a("Design", "design") + a("Build", "build", "in 1") + a("Review", "review", "in 1")
        + a("Fact-check", "find") + a("Merge", "review", "in 1")
        + "<h4>Chores</h4>" + a("Live checks", "orders", "in 1") + a("Board answers", "orders") + a("Pull requests nobody holds", "orders")
        + "<h4>Yours</h4>" + a("Troubleshoot", "call", "in 1") + "</nav>"
    )


def edit():
    msel = lambda m: sel(f'<span class="m">{m}</span>')  # noqa: E731
    you = sel("you")
    fixed = lambda t: f'<span class="fix">{t}</span>'  # noqa: E731
    body = (
        '<div class="fhead"><h2><span class="ed">careful-build</span></h2><span class="id">format 2</span>'
        '<span class="tag">this install</span><span class="tag">copied from build-review</span>'
        '<div class="act"><span class="probs">2 problems</span><button class="quiet">Discard</button><button disabled>Save</button></div></div>'
        '<p class="used">Used by no team yet.</p>'
        f'<div class="lim"><span>A session is silent after {num(4)} h</span></div>'
        + erec(1, "var(--build)", "Build", msel("sonnet"), "any entry with no stage yet", ["Build", "Live checks"], [
            ("pull request open", PR_OPEN, nx("review")),
            ("stuck", REASON, nx("troubleshoot", 1, note=' <span class="chg">was you</span>')),
            ("design needs changing", REASON, you),
            ("split into parts", PARTS, fixed("waits for its parts")),
            ("not needed", REASON, you),
        ])
        + erec(2, "var(--review)", "Review", msel("sonnet"), "", ["Review <small>every pull request</small>", "Merge"], [
            ("ship", VERDICT, sel("the next action, Merge")),
            ("changes wanted", "a verdict is posted", nx("build", "", bad=True), "Build → Review → Build is a loop with no limit."),
            ("merged", MERGED, sel('<span class="done">done</span>')),
            ("cannot merge", CANT, nx("build", 3)),
        ], err=True)
        + erec(3, "var(--call)", "Troubleshoot", msel("opus"), "", ["Troubleshoot <small>yours</small>"], [
            ("pull request open", PR_OPEN, sel(key("second-read"), bad=True), "Pick a stage that exists. Second read was removed."),
            ("stuck", REASON, you),
            ("not needed", REASON, you),
        ], err=True)
        + '<p class="addstep">+ Add a stage</p>'
        + every(you_stuck=f"{you} <small>changed in Build</small>", again=fixed("offered again"))
        + OUT_P
        + f'<div class="out"><div><b>Questions</b>{msel("opus")}</div><div><b>Board answers</b>{msel("sonnet")}</div>'
        f'<div><b>Pull requests nobody holds</b>{msel("sonnet")}</div><div><b>Manager</b>{msel("sonnet")}</div></div>'
        "<h3>Does it flow?</h3><p></p>"
        '<div class="chk"><div class="no">Every stage a Next names exists <small>second-read does not</small></div>'
        '<div class="no">Every loop has a limit <small>Build → Review → Build has none</small></div>'
        "<div>Every pull request opened can reach Merge</div>"
        "<div>Every kind of entry has a way in <small>all enter at Build</small></div>"
        '<div class="i">6 outcomes go to you, and 3 more at a limit <small>none by omission</small></div>'
        '<div class="i">A plain build changes stage once <small>each round adds 2</small></div></div>'
    )
    cap = (
        "F — a flow of your own being edited: a copy of build-review with a Troubleshoot stage added. "
        "Next is a pick-list, any move can carry a limit, and the checks run as you edit. Grey values are fixed. "
        "The order of the stages is for reading only."
    )
    return page("", body, cap, sub="the stages an entry passes through, and where each outcome sends it", navhtml=enav()).replace(
        "<style>", "<style>" + TCSS + ECSS
    )


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    out = Path(sys.argv[1])
    src = Path(__file__).parent
    assert CSS and nav
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, html in (("e-states", td()), ("f-editing", edit())):
            (src / f"{name}.html").write_text(html)
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.set_content(html, wait_until="networkidle")
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(out / f"2026-11-20-td1954-flows-{name}-1440.png"), full_page=True)
            pg.close()
        b.close()
