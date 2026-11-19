"""The Flows page proposal (TD-1954), first shape: two renders in the Tools page's style (td1953-src/own.html).

A: the built-in flow `td`, read-only. B: a copy being edited (one session designs and builds, a seat reviews).
Run: PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python build.py <out-dir>
"""

import sys
from pathlib import Path

CSS = """
:root { --page:#E7EBEC; --sheet:#FAFBFB; --ink:#1F272C; --soft:#5D6970; --rule:#C6CFD3; --rule2:#DDE3E5;
  --on:#2E8A57; --used:#2D5F86; --keep:#C27A1A; --off:#9AA5AA; --bad:#B4432F;
  --design:#5B5BD6; --build:#2D7FB8; --review:#C27A1A; --find:#C2528B; --call:#3B8F86; --orders:#6B7780; }
* { box-sizing:border-box; }
body { margin:0; background:var(--page); color:var(--ink); font:15px/1.5 "IBM Plex Sans", system-ui, sans-serif; }
.wrap { max-width:1180px; margin:0 auto; padding:28px 24px 64px; }
header { display:flex; align-items:flex-end; gap:18px; flex-wrap:wrap; border-bottom:2px solid var(--ink); padding-bottom:12px; }
header h1 { font-size:34px; line-height:1; margin:0; font-weight:700; letter-spacing:-.01em; }
header .sub { color:var(--soft); font-size:14px; }
.cols { display:grid; grid-template-columns:210px 1fr; gap:32px; margin-top:22px; }
mono, .mono { font-family:"IBM Plex Mono", monospace; }

/* the list of flows */
nav h4 { margin:18px 0 4px; font-size:12px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--soft); }
nav h4:first-child { margin-top:0; }
nav a { display:block; padding:6px 10px; border-radius:4px; color:var(--ink); text-decoration:none; font:500 14px "IBM Plex Mono", monospace; }
nav a small { display:block; font:400 12.5px "IBM Plex Sans", sans-serif; color:var(--soft); }
nav a.sel { background:var(--sheet); border:1px solid var(--rule); box-shadow:inset 3px 0 0 var(--ink); }
nav a .warn { color:var(--bad); }

/* the flow's head */
.fhead { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
.fhead h2 { margin:0; font-size:24px; font-weight:600; }
.fhead h2 .ed::after { content:" ✎"; font-size:14px; font-weight:400; color:var(--off); }
.fhead .id { font:400 13px "IBM Plex Mono", monospace; color:var(--soft); }
.fhead .tag { font-size:12.5px; border:1px solid var(--rule); border-radius:10px; padding:0 9px; color:var(--soft); background:var(--sheet); }
.fhead .act { margin-left:auto; display:flex; gap:8px; }
button { font:inherit; font-size:13px; color:var(--ink); background:none; border:1px solid var(--ink); border-radius:3px; padding:3px 12px; }
button.pri { background:var(--ink); color:#fff; }
button.quiet { border-color:var(--rule); color:var(--soft); }
.used { color:var(--soft); font-size:14px; margin:4px 0 0; }
.used b { color:var(--ink); font-weight:500; }
.path { margin:14px 0 22px; font:500 14px "IBM Plex Mono", monospace; display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.path span { padding:2px 10px; border-radius:3px; color:#fff; }
.path i { font-style:normal; color:var(--soft); }
.path .you { background:none; color:var(--ink); border:1px dashed var(--soft); }

h3 { margin:26px 0 2px; font-size:16px; font-weight:600; }
h3 + p { margin:0 0 10px; color:var(--soft); font-size:14px; max-width:74ch; }

/* a step: who (left) and what it does (right) */
.step { display:grid; grid-template-columns:34px 250px 1fr; background:var(--sheet); border:1px solid var(--rule2); border-radius:6px; margin-bottom:10px; position:relative; }
.step .n { display:grid; place-items:start center; padding-top:14px; border-radius:6px 0 0 6px; color:#fff; font-weight:600; }
.step .n small { writing-mode:vertical-rl; font-weight:400; font-size:11px; opacity:.8; margin-top:8px; letter-spacing:.08em; }
.step .who { padding:12px 16px; border-right:1px solid var(--rule2); }
.step .who .nm { font-weight:600; font-size:17px; }
.step .who dl { margin:8px 0 0; display:grid; grid-template-columns:62px 1fr; gap:4px 8px; font-size:13px; }
.step .who dt { color:var(--soft); }
.step .who dd { margin:0; }
.sel-m { display:inline-flex; align-items:center; gap:6px; font:600 13px "IBM Plex Mono", monospace; border:1px solid var(--rule); border-radius:3px; padding:1px 8px; background:#fff; }
.sel-m::after { content:"▾"; color:var(--soft); font-size:11px; }
.ro .sel-m { border-color:transparent; background:none; padding-left:0; }
.ro .sel-m::after { content:""; }
.sel-m.bad { border-color:var(--bad); color:var(--bad); }
.does { list-style:none; margin:0; padding:8px 14px; }
.does li { display:grid; grid-template-columns:18px 132px 1fr auto; gap:10px; align-items:baseline; padding:5px 0; border-bottom:1px dashed var(--rule2); font-size:14px; }
.does li:last-child { border-bottom:none; }
.does .grip { color:var(--off); font-size:12px; cursor:grab; }
.ro .does .grip { visibility:hidden; }
.does .a { font-weight:600; }
.does .d { color:var(--soft); font-size:13.5px; }
.does .by { font-size:13px; white-space:nowrap; color:var(--soft); display:flex; gap:6px; align-items:center; }
.does li.drop { border:1.5px dashed var(--used); border-radius:4px; color:var(--used); display:block; text-align:center; font-size:13px; padding:5px; margin-top:4px; }
.does li.auto .a { font-weight:400; color:var(--soft); }
.does li.auto .d { font-size:13px; }
.x { color:var(--off); font-size:13px; }
.ro .x { display:none; }
.note { grid-column:2 / -1; border-top:1px solid var(--rule2); padding:6px 16px; font-size:13px; color:var(--bad); }
.hand { margin:-4px 0 6px 17px; padding-left:28px; border-left:2px solid var(--rule); font-size:13px; color:var(--soft); height:26px; display:flex; align-items:center; }
.addstep { margin:0 0 6px 44px; font-size:13px; color:var(--used); }

/* on call */
.call { display:grid; grid-template-columns:34px 190px 130px 1fr 150px; align-items:center; background:var(--sheet); border:1px solid var(--rule2); border-radius:6px; margin-bottom:6px; font-size:14px; }
.call .n { align-self:stretch; background:var(--call); border-radius:6px 0 0 6px; }
.call > div { padding:8px 12px; }
.call .nm { font-weight:600; }
.call .d { color:var(--soft); font-size:13.5px; }
.call.fixed .n { background:var(--off); }

/* the foot: what is covered, the actions, where it runs */
.foot { display:grid; grid-template-columns:1fr 1fr; gap:28px; margin-top:8px; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
td { padding:4px 8px 4px 0; border-bottom:1px solid var(--rule2); vertical-align:top; }
td:first-child { width:22px; color:var(--on); font-weight:700; }
td.no { color:var(--bad); }
td:last-child { color:var(--soft); }
.cat { display:flex; flex-wrap:wrap; gap:6px; }
.chip { font-size:13px; border:1px solid var(--rule); border-radius:3px; padding:2px 9px; background:var(--sheet); box-shadow:inset 3px 0 0 var(--c, var(--off)); }
.chip.un { color:var(--soft); background:none; border-style:dashed; }
.chip small { color:var(--soft); }
.fixedrow { color:var(--soft); font-size:13.5px; margin:6px 0 0; max-width:none; }
.fixedrow b { color:var(--ink); font-weight:500; }
.runs { font-size:13.5px; }
.runs .ok::before { content:"● "; color:var(--on); } .runs .nok::before { content:"● "; color:var(--bad); }
.cap { margin:0 0 14px; padding:8px 12px; background:#FFF7E6; border:1px solid #E7C98A; border-radius:4px; font-size:13px; color:#5C4514; }
"""

FONT = (
    '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&'
    'family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">'
)


def nav(sel):
    def a(key, name, small, warn=""):
        cls = ' class="sel"' if key == sel else ""
        w = f' <span class="warn">{warn}</span>' if warn else ""
        return f"<a{cls}>{name}{w}<small>{small}</small></a>"

    return (
        "<nav><h4>Built in</h4>"
        + a("td", "td", "design → build → read")
        + a("br", "build-review", "build → read")
        + a("b", "build", "build")
        + "<h4>This install</h4>"
        + a("solo", "one-owner", "design+build → review", "●" if sel == "solo" else "")
        + "<h4>shiftlead (repo)</h4>"
        + a("ao", "ao-grind", "td, two outside fact-checkers")
        + "</nav>"
    )


def act(name, desc, by="", auto=False, x=True):
    cls = ' class="auto"' if auto else ""
    return (
        f'<li{cls}><span class="grip">⠿</span><span class="a">{name}</span><span class="d">{desc}</span>'
        f'<span class="by">{by}{" <span class=x>✕</span>" if x and not auto else ""}</span></li>'
    )


def model(m, bad=False):
    return f'<span class="sel-m{" bad" if bad else ""}">{m}</span>'


def step(n, color, name, role, takes, m, acts, count="", note="", tag="step"):
    c = f"<dt>Seats</dt><dd>{count}</dd>" if count else ""
    nt = f'<div class="note">{note}</div>' if note else ""
    return (
        f'<div class="step"><div class="n" style="background:var(--{color})">{n}</div>'
        f'<div class="who"><div class="nm">{name}</div><dl><dt>Role</dt><dd>{role}</dd>'
        f"<dt>Model</dt><dd>{m}</dd><dt>Takes</dt><dd>{takes}</dd>{c}</dl></div>"
        f'<ul class="does">{"".join(acts)}</ul>{nt}</div>'
    )


def call(name, when, does, m, fixed=False):
    return (
        f'<div class="call{" fixed" if fixed else ""}"><div class="n"></div><div class="nm">{name}</div>'
        f'<div class="d">{when}</div><div class="d">{does}</div><div>{m}</div></div>'
    )


FIXED = (
    '<p class="fixedrow"><b>Done by whichever step holds the work, with no model of its own:</b> take an id · claim · '
    "make the worktree · open the PR · precheck · wait for checks · archive the entry · report done · remove the "
    "worktree. <b>Done by the host:</b> settle a new entry · pull main · precheck main · promote · smoke. "
    "<b>Always the person's:</b> the last word, and anything passed up.</p>"
)


def cover(rows):
    return "<table>" + "".join(f'<tr><td class="{c}">{m}</td><td>{t}</td><td>{w}</td></tr>' for c, m, t, w in rows) + "</table>"


def catalogue(used):
    items = [
        ("Find", "find", "probe an area, file what is wrong"),
        ("Design", "design", "write the design, file its builds"),
        ("Design rounds", "design", "fresh readers review a design"),
        ("Fact-check", "review", "check a doc against the repo"),
        ("Build", "build", "change the code, test it"),
        ("Review", "review", "an independent read of the PR"),
        ("Read held paths", "review", "a seat's verdict on a held PR"),
        ("Merge", "build", "the gate, then the squash"),
        ("Board answers", "orders", "carry out what you answered"),
        ("Unheld PRs", "orders", "PRs nobody holds: sync, red, lift, sweep, filing"),
        ("Live checks", "orders", "confirm a build on the running system"),
        ("Answer", "call", "members' questions"),
        ("Draft an entry", "call", "an entry you or another repo hand over"),
        ("Audit", "call", "the last n merged PRs"),
        ("Sweep", "call", "stranded work"),
    ]
    out = []
    for n, c, d in items:
        un = "" if n in used else " un"
        out.append(f'<span class="chip{un}" style="--c:var(--{c})">{n} <small>{d}</small></span>')
    return '<div class="cat">' + "".join(out) + "</div>"


def page(sel, body, cap, title='Flows', sub='the path an entry takes: who does what, in what order, on which model', navhtml=''):
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">{FONT}'
        f"<style>{CSS}</style></head><body><div class='wrap'><div class='cap'>{cap}</div>"
        f"<header><h1>{title}</h1><span class='sub'>{sub}</span></header>"
        f"<div class='cols'>{navhtml or nav(sel)}<main>{body}</main></div></div></body></html>"
    )


def td():
    fresh = lambda m: f"a fresh reader on {m}"  # noqa: E731
    steps = (
        step(1, "design", "Design", "designer", "design-first entries", model("opus"), [
            act("Design", "the design's sections, mockups and synopsis; files its builds"),
            act("Design rounds", "up to 4 rounds (6 for a wide design), then the counted verdict", fresh(model("sonnet") + " then " + model("fable"))),
            act("Fact-check", "the whole design at round 1, each round's changes after", fresh(model("sonnet"))),
            act("Merge", "on the gate; the builds wait for your Go where the verdict asks"),
        ], count="1")
        + '<div class="hand">the builds it filed become pickable</div>'
        + step(2, "build", "Build", "builder", "every other entry", model("opus"), [
            act("Build", "the change, its tests, the PR"),
            act("Review", "one independent read; its evidence on the PR", fresh(model("sonnet"))),
            act("Merge", "on the gate, unless the PR touches a held path"),
            act("Board answers", "an answered card is carried out before any entry"),
            act("Unheld PRs", "a PR nobody holds: sync, red, lift, sweep, filing"),
            act("Live checks", "once a build is live, confirm it on the running system"),
        ], count="1 – 4, set on the team")
        + '<div class="hand">a PR on a held path is asked of the reader</div>'
        + step(3, "review", "Read", "the question seat", "PRs on held paths", model("opus"), [
            act("Read held paths", "findings, or pass; unread after 2 h it goes to you"),
            act("Merge", "once it passes"),
        ])
    )
    calls = (
        call("Question seat", "when asked", "Answer · Draft an entry — passes the rest to you", model("opus"))
        + call("Docs audit", "every 10 merged PRs", "audits them against the docs, files findings", model("sonnet"))
        + call("Test audit", "every 10 merged PRs", "audits them against the tests, files findings", model("sonnet"))
        + call("Manager", "every team has one", "stalls, permission prompts, idle with work", model("sonnet"), fixed=True)
    )
    cov = cover([
        ("", "✓", "Merge a PR", "its author; a held PR, the reader"),
        ("", "✓", "Review evidence", "a fresh reader, in Design and Build"),
        ("", "✓", "Read a held path", "step 3"),
        ("", "✓", "Answer a member", "the question seat"),
        ("", "✓", "Notice a stall", "the manager and the host"),
    ])
    body = (
        '<div class="ro"><div class="fhead"><h2>Design, build, read</h2><span class="id">td</span>'
        '<span class="tag">built in · read only</span><div class="act"><button class="pri">Copy to edit</button></div></div>'
        '<p class="used">Run by <b>ao-grind</b> (now), <b>cm-grind</b>, <b>ss-grind</b>.</p>'
        '<div class="path"><span style="background:var(--design)">design</span><i>→</i>'
        '<span style="background:var(--build)">build</span><i>→</i><span style="background:var(--review)">read</span>'
        '<i>→</i><span class="you">you, through the question seat</span></div>'
        "<h3>Steps</h3><p>Each step is one session's sitting. It does its actions top to bottom; "
        "an action marked <i>a fresh reader</i> is handed to a new session on that model, never done by the author.</p>"
        f"{steps}<h3>On call</h3><p>Seats outside the path, started when their trigger fires.</p>{calls}"
        f"{FIXED}<div class='foot'><div><h3>Every task has someone</h3><p></p>{cov}</div>"
        "<div><h3>Actions</h3><p>Dashed ones are not used by this flow. Each has its brief on the Actions page.</p>"
        f'{catalogue({"Design", "Design rounds", "Fact-check", "Build", "Review", "Read held paths", "Merge", "Answer", "Audit", "Board answers", "Unheld PRs", "Live checks", "Draft an entry"})}'
        '<h3>Where it can run</h3><p class="runs"><span class="ok">ao-grind</span> — every model has a signed-in login '
        'and a smoke pass<br><span class="nok">cm-grind</span> — no smoke pass for sonnet as manager on contractmatch</p>'
        "</div></div></div>"
    )
    return page("td", body, "A — a built-in flow, read only. Nothing here is editable until it is copied.")


def solo():
    fresh = lambda m: f"a fresh reader on {m}"  # noqa: E731
    steps = (
        step(1, "build", "Design and build", "builder", "every entry", model("opus"), [
            act("Design", "only where the entry is design-first"),
            act("Fact-check", "the design, before any code", fresh(model("flash-lite", bad=True))),
            act("Build", "the change, its tests, the PR"),
            '<li class="drop">drop an action here</li>',
        ], count="1 – 4, set on the team", note="No login on ao-grind offers flash-lite — pick another model, or add a login on the Tools page.")
        + '<div class="hand">every PR is asked of the reviewer</div>'
        + step(2, "review", "Review", "reviewer", "every PR", model("sonnet"), [
            act("Review", "the independent read, by this seat instead of a fresh reader"),
            act("Merge", "once it passes"),
        ])
        + '<div class="hand">beside the path: a cheaper seat takes the work orders</div>'
        + step(3, "orders", "Chores", "builder", "work orders only", model("sonnet"), [
            act("Board answers", "an answered card is carried out before any entry"),
            act("Unheld PRs", "a PR nobody holds: sync, red, lift, sweep, filing"),
            act("Live checks", "once a build is live, confirm it on the running system"),
        ], count="1")
        + '<div class="addstep">+ Add a step</div>'
    )
    calls = (
        call("Manager", "every team has one", "stalls, permission prompts, idle with work", model("sonnet"), fixed=True)
        + '<div class="addstep" style="margin-left:0">+ Add an on-call seat</div>'
    )
    cov = cover([
        ("", "✓", "Merge a PR", "step 2"),
        ("", "✓", "Review evidence", "step 2"),
        ("", "–", "Read a held path", "nobody: no step reads held paths, so held: does nothing"),
        ("", "–", "Answer a member", "you: this flow has no question seat"),
        ("", "✓", "Notice a stall", "the manager and the host"),
    ])
    body = (
        '<div class="fhead"><h2><span class="ed">One owner, then a review</span></h2><span class="id">one-owner</span>'
        '<span class="tag">this install · unsaved changes</span><div class="act"><button class="quiet">Discard</button>'
        '<button class="quiet">Copy</button><button class="pri">Save</button></div></div>'
        '<p class="used">Run by no team yet. Saved at once; a repo\'s flow is saved as a pull request.</p>'
        '<div class="path"><span style="background:var(--build)">design and build</span><i>→</i>'
        '<span style="background:var(--review)">review</span><i>→</i><span class="you">you, directly</span></div>'
        "<h3>Steps</h3><p>Drag a step to reorder it, drag an action between steps, pick each step's model. "
        "An action is offered only where it can go: a review is never the author's own.</p>"
        f"{steps}<h3>On call</h3><p></p>{calls}{FIXED}"
        f"<div class='foot'><div><h3>Every task has someone</h3><p></p>{cov}</div>"
        "<div><h3>Actions</h3><p>Drag one into a step to use it. Yours are listed with the built-in ones.</p>"
        f'{catalogue({"Design", "Fact-check", "Build", "Review", "Merge", "Board answers", "Unheld PRs", "Live checks"})}'
        '<h3>Where it can run</h3><p class="runs"><span class="nok">ao-grind</span> — no login offers flash-lite</p>'
        "</div></div>"
    )
    return page("solo", body, "B — a copy being edited: one session designs and builds, a reviewer seat reads every PR.")


ACSS = """
.facts { display:grid; grid-template-columns:150px 1fr; gap:5px 14px; font-size:14px; margin:14px 0 4px; max-width:760px; }
.facts dt { color:var(--soft); } .facts dd { margin:0; }
.brief { background:var(--sheet); border:1px solid var(--rule2); border-radius:6px; padding:14px 20px; font-size:14px; max-width:820px; }
.brief p { margin:0 0 9px; } .brief p:last-child { margin:0; }
.brief code { font:12.5px "IBM Plex Mono", monospace; background:#EEF1F2; padding:0 4px; border-radius:2px; }
.brief .slot { font:12.5px "IBM Plex Mono", monospace; color:var(--used); }
.brief.edit { background:#fff; border-color:var(--ink); font:13.5px/1.6 "IBM Plex Mono", monospace; min-height:230px; }
.more { color:var(--soft); font-size:13px; margin:6px 0 0; }
.add2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; max-width:820px; }
.add2 > div { border:1px dashed var(--rule); border-radius:6px; padding:10px 14px; font-size:13.5px; background:var(--sheet); }
.add2 b { display:block; font-weight:600; font-size:13px; } .add2 span { color:var(--soft); }
.add2 em { color:var(--used); font-style:normal; }
.tools { display:flex; gap:14px; font-size:13px; color:var(--soft); margin:0 0 6px; max-width:820px; }
.tools span:last-child { margin-left:auto; }
nav a i { float:right; font:400 11.5px "IBM Plex Sans", sans-serif; color:var(--off); font-style:normal; }
"""


def anav(sel):
    def a(name, tag=""):
        cls = ' class="sel"' if name == sel else ""
        return f"<a{cls} style='font-family:inherit;font-weight:{600 if name == sel else 400}'>{name}<i>{tag}</i></a>"

    groups = [
        ("Every session", [("ShiftLead mechanics", ""), ("Taking work", "lane steps")]),
        ("In the path", [(n, "") for n in ("Find", "Design", "Design rounds", "Fact-check", "Build", "Review", "Read held paths", "Merge")]),
        ("Work orders", [(n, "") for n in ("Board answers", "Unheld PRs", "Live checks")]),
        ("On call", [(n, "") for n in ("Answer", "Draft an entry", "Audit", "Sweep", "Manage")]),
        ("Yours", [("Build, docs only", "this install")]),
    ]
    return "<nav>" + "".join(f"<h4>{g}</h4>" + "".join(a(n, t) for n, t in items) for g, items in groups) + "</nav>"


SUB = "what a session can be asked to do, and the words it is told"


def action_builtin():
    body = (
        '<div class="fhead"><h2>Build</h2><span class="id">build</span>'
        '<span class="tag">built in · read only · last changed 2026-11-02</span>'
        '<div class="act"><button class="pri">Copy to edit</button></div></div>'
        '<p class="used">The change an entry asks for, its tests, and the pull request.</p>'
        "<dl class='facts'><dt>Done by</dt><dd>a step that holds a lane — never a fresh reader, never an on-call seat</dd>"
        "<dt>Used in</dt><dd><b>td</b> step 2 · <b>build-review</b> step 1 · <b>build</b> step 1 · <b>one-owner</b> step 1</dd>"
        "<dt>Ends when</dt><dd>its pull request merges, or the claim is dropped with a reason</dd>"
        "<dt>Brings with it</dt><dd>claim · worktree · open the PR · precheck · wait for checks · archive the entry · report done</dd>"
        "<dt>Needs after it</dt><dd>Review and Merge, in this step or a later one</dd></dl>"
        "<h3>The brief</h3><p>What a session doing this action is told, after the ShiftLead mechanics and before the path.</p>"
        "<div class='brief'><p><b>Build.</b> Resolve each entry you take to a pull request, in this order: verify the "
        "current code first — entries lag reality, so search before you build — then fix, test "
        "(<span class='slot'>{test}</span>, <span class='slot'>{lint}</span>) and open the pull request against "
        "<code>main</code>.</p><p>A change in behaviour is a change to the design "
        "(<span class='slot'>{design_dir}</span>) first, in the same pull request; the dated fact goes to the history.</p>"
        "<p>A page you change is looked at before the pull request: run it on a scratch home, never the live one, "
        "and keep the screenshots with the change.</p><p>Archive the entry in the pull request that completes it, and "
        "its parent with the last of its parts.</p></div><p class='more'>412 words · filled per repo: "
        "<span class='mono'>{test} {lint} {design_dir} {ledger}</span></p>"
        "<h3>Added words</h3><p>Yours, told after the built-in brief wherever this action is used. The built-in brief itself is never edited.</p>"
        "<div class='add2'><div><b>This install</b><em>Add…</em></div>"
        "<div><b>shiftlead (repo)</b><span>Run the UI check before any PR that touches <span class='mono'>src/shiftlead/ui/</span>…</span> "
        "<em>Edit… (a pull request)</em></div></div>"
    )
    cap = "C — the Actions page: a built-in action, its facts and its brief. Read only; your words are added beside it."
    return page("", body, cap, title="Actions", sub=SUB, navhtml=anav("Build")).replace("<style>", "<style>" + ACSS)


def action_own():
    body = (
        '<div class="fhead"><h2><span class="ed">Build, docs only</span></h2><span class="id">build-docs</span>'
        '<span class="tag">this install · unsaved changes</span><div class="act"><button class="quiet">Delete</button>'
        '<button class="quiet">Discard</button><button class="pri">Save</button></div></div>'
        '<p class="used">Started as a copy of Build. It is its own action from here: nothing follows the built-in.</p>'
        "<dl class='facts'><dt>Done by</dt><dd>a step that holds a lane</dd>"
        "<dt>Used in</dt><dd>no flow yet</dd>"
        "<dt>Ends when</dt><dd>its pull request merges, or the claim is dropped with a reason</dd>"
        "<dt>Brings with it</dt><dd>claim · worktree · open the PR · precheck · wait for checks · archive the entry · report done</dd>"
        "<dt>Needs after it</dt><dd>Review or Fact-check, and Merge, in this step or a later one</dd></dl>"
        "<h3>The brief</h3><p>Plain Markdown. A word in braces is filled per repo.</p>"
        "<div class='tools'><span><b>Write</b></span><span>Preview</span><span>Slots: {test} {lint} {design_dir} {ledger}</span><span>88 words</span></div>"
        "<div class='brief edit'>**Build, docs only.** Take only entries whose change is to the docs: the design, the "
        "briefs, the glossary, a README.<br><br>Verify the page as it stands first — an entry lags reality. Write the "
        "change in the present tense; the dated fact goes to the history, never the design.<br><br>Run {lint} and the "
        "doc tests before you open the pull request against `main`.<br><br>Never change code in the same pull request: "
        "an entry that needs both is not yours — pass it over and say why in your doing line.▍</div>"
        "<p class='more'>Saved at once on this install. To use it in a repo's flow, the repo holds its own copy, saved as a pull request.</p>"
    )
    cap = "D — an action of your own, started from a copy of Build and now edited freely."
    return page("", body, cap, title="Actions", sub=SUB, navhtml=anav("Build, docs only")).replace("<style>", "<style>" + ACSS)


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    out = Path(sys.argv[1])
    src = Path(__file__).parent
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, html in (
            ("a-builtin", td()),
            ("b-editing", solo()),
            ("c-action", action_builtin()),
            ("d-own-action", action_own()),
        ):
            (src / f"{name}.html").write_text(html)
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.set_content(html, wait_until="networkidle")
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(out / f"2026-11-18-td1954-flows-{name}-1440.png"), full_page=True)
            pg.close()
        b.close()
