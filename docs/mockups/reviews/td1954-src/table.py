"""The Flows page as records (TD-1954, 2026-11-20): each step's Owner key, model, actions and endings.

E: the built-in flow `td`, read-only. Every ending names who picks it and where the entry goes.
Run: PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python table.py <out-dir>
"""

import sys
from pathlib import Path

from build import CSS, nav, page

TCSS = """
.lim { display:flex; gap:22px; flex-wrap:wrap; font-size:13.5px; color:var(--soft); margin:10px 0 18px; }
.lim b { color:var(--ink); font-weight:600; font-family:"IBM Plex Mono", monospace; }
.rec { display:grid; grid-template-columns:34px 270px 1fr; background:var(--sheet); border:1px solid var(--rule2); border-radius:6px; margin-bottom:10px; }
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
.ends .h, .ends .e { display:grid; grid-template-columns:1fr 84px 250px; gap:12px; align-items:baseline; }
.ends .h { font-size:11.5px; letter-spacing:.05em; text-transform:uppercase; color:var(--soft); padding-bottom:3px; border-bottom:1px solid var(--rule); }
.ends .e { font-size:14px; padding:4px 0; border-bottom:1px dashed var(--rule2); }
.ends .e:last-child { border-bottom:none; }
.by { font-size:12.5px; color:var(--soft); }
.by.s { color:var(--design); }
.to { font-size:13.5px; white-space:nowrap; }
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

HELP, SESS = '<span class="by">helper</span>', '<span class="by s">session</span>'
YOU, DONE = '<span class="you">you</span>', '<span class="done">done</span>'


def key(k):
    return f'<span class="key">Owner: {k}</span>'


def fwd(k):
    return f"→ {key(k)}"


def back(k, limit=""):
    lim = f" <small>limit {limit}</small>" if limit else ""
    return f'<span class="back">↩</span> {key(k)}{lim}'


def same(a):
    return f'<span class="same">carries on to {a}, same session</span>'


def rec(n, color, name, k, model, takes, acts, ends, cls=""):
    a = "".join(f"<a>{x}</a>" for x in acts)
    e = "".join(f'<div class="e"><span>{t}</span>{by}<span class="to">{to}</span></div>' for t, by, to in ends)
    kk = key(k) if k else ""
    dl = f"<dt>Model</dt><dd class='m'>{model}</dd>" if model else ""
    dl += f"<dt>Takes</dt><dd>{takes}</dd>" if takes else ""
    dl += f"<dt>Does</dt><dd class='acts'>{a}</dd>" if a else ""
    return (
        f'<div class="rec {cls}"><div class="n" style="background:{color}">{n}</div>'
        f'<div class="who"><div class="nm">{name}</div>{kk}<dl>{dl}</dl></div>'
        f'<div class="ends"><div class="h"><span>Ends as</span><span>Picked by</span><span>Goes to</span></div>{e}</div></div>'
    )


def td():
    body = (
        '<div class="fhead"><h2>td</h2><span class="id">format 2</span><span class="tag">built in</span>'
        '<div class="act"><button>Copy</button></div></div>'
        '<p class="used">Used by <b>ao-grind</b>, <b>docs</b>.</p>'
        '<div class="lim"><span>Rounds, ordinary design <b>3</b></span><span>Rounds, far-reaching design <b>6</b></span>'
        "<span>Review rounds on a build <b>3</b></span><span>Silent before it goes to you <b>4 h</b></span></div>"
        + rec(1, "var(--design)", "Design", "design", "fable", "a design-first entry with no Owner", ["Design"], [
            ("pull request open and green", HELP, fwd("rounds")),
            ("split into parts", HELP, '<span class="same">rests until its parts are done</span>'),
            ("not needed", SESS, YOU),
        ])
        + rec(2, "var(--review)", "Design rounds", "rounds", "sonnet, fable <small>in turn</small>", "", ["Review <small>reviewers in turn</small>"], [
            ("ship, from each reviewer on the same head", SESS, fwd("facts")),
            ("changes wanted", SESS, back("design", "3 or 6")),
            ("pull request not ready", HELP, back("design", "3")),
            ("limit reached", HELP, YOU),
        ])
        + rec(3, "var(--find)", "Fact-check", "facts", "sonnet", "", ["Fact-check", "Merge"], [
            ("ship", SESS, same("Merge")),
            ("changes wanted", SESS, back("design", "3")),
            ("merged", HELP, '<span class="same">rests until its builds are done</span>'),
            ("changed since review", HELP, back("rounds", "3")),
            ("red or conflicting", HELP, back("design", "3")),
        ])
        + rec(4, "var(--build)", "Build", "build", "opus", "any other entry with no Owner", ["Build", "Live checks"], [
            ("pull request open and green", HELP, fwd("review")),
            ("design needs changing", SESS, YOU),
            ("split into parts", HELP, '<span class="same">rests until its parts are done</span>'),
            ("not needed", SESS, YOU),
        ])
        + rec(5, "var(--review)", "Review", "review", "sonnet", "", ["Review <small>every pull request</small>"], [
            ("ship", SESS, fwd("second")),
            ("changes wanted", SESS, back("build", "3")),
            ("pull request not ready", HELP, back("build", "3")),
            ("limit reached", HELP, YOU),
        ])
        + rec(6, "var(--review)", "Second read", "second", "opus", "", ["Review <small>protected paths</small>", "Merge"], [
            ("not on protected paths", HELP, same("Merge")),
            ("ship", SESS, same("Merge")),
            ("changes wanted", SESS, back("build", "3")),
            ("merged", HELP, DONE),
            ("changed since review", HELP, back("review", "3")),
            ("red or conflicting", HELP, back("build", "3")),
        ])
        + rec("∗", "var(--off)", "Every step", "", "", "", [], [
            ("question", SESS, f"{YOU} <small>with a board item</small>"),
            ("stuck", SESS, YOU),
            ("session lost", HELP, '<span class="same">the same step, offered again</span>'),
            ("silent for 4 h", HELP, YOU),
        ], cls="all")
        + "<h3>Outside the flow</h3><p>These take no entry and file no Owner. They are here to be given a model.</p>"
        '<div class="out"><div><b>Questions</b><span class="m">opus</span> <span>answers members by mail</span></div>'
        '<div><b>Board answers</b><span class="m">sonnet</span> <span>acts on what you decided</span></div>'
        '<div><b>Pull requests nobody holds</b><span class="m">sonnet</span> <span>on the clock</span></div>'
        '<div><b>Manager</b><span class="m">sonnet</span> <span>starts and stops sessions</span></div></div>'
        "<h3>Does it flow?</h3><p></p>"
        '<div class="chk"><div>Every Owner a step can file has a step that takes it <small>6 of 6</small></div>'
        "<div>Every way back has a limit <small>10 of 10</small></div>"
        "<div>Every pull request opened can reach Merge</div>"
        "<div>Every kind of entry has a way in <small>design-first, other</small></div>"
        '<div class="i">8 endings go to you <small>none by omission</small></div>'
        '<div class="i">A plain build files 2 state changes <small>each round back adds 2</small></div></div>'
    )
    cap = (
        "E — the built-in flow td as records. Each step has an Owner key, a model, its actions, and every way it can end. "
        "A yellow tag is the Owner value written to the entry."
    )
    return page("td", body, cap, sub="the steps an entry passes through, and where each ending sends it").replace(
        "<style>", "<style>" + TCSS
    )


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    out = Path(sys.argv[1])
    src = Path(__file__).parent
    assert CSS and nav
    with sync_playwright() as p:
        b = p.chromium.launch()
        html = td()
        (src / "e-states.html").write_text(html)
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.set_content(html, wait_until="networkidle")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(out / "2026-11-20-td1954-flows-e-states-1440.png"), full_page=True)
        pg.close()
        b.close()
