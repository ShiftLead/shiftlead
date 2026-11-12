"""TD-1700 (TD-1568's build), design §4.5 *A taken-over member is marked*, §4.5a *card: taken over mark*,
*card: Hand back*, *team header: taken over count*: a member the person took over and did not hand back is
marked in the warning colour wherever its team is read. One predicate, `mail.taken_over`, read by
`unanswered`, the held row and the view; the view carries the hover's three parts; the card, the compact card,
the team header and Focus draw them."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessionorc import mail
from sessionorc.models import MailEntry, Session

NOW = datetime.now(UTC).replace(microsecond=0)
ROOT = Path(__file__).resolve().parent.parent


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


AGO = _iso(NOW - timedelta(hours=3, minutes=12))


def _ago() -> str:
    """3h 12m ago at the render, with 20 s to spare: a card's age is drawn at its own `now`."""
    return _iso(datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3, minutes=12, seconds=20))


def _rec(**kw) -> Session:
    base = dict(
        id="ao-x-tl", name="techlead-ao-1", kind="interactive", adapter="claude-code", dir="/tmp/x", state="idle",
        unattended=False, supervised=True, team="t", by_person=False,
    )  # fmt: skip
    return Session(**{**base, **kw})


# -- the predicate ----------------------------------------------------------------------------------


def test_taken_over_is_an_idle_interactive_member_and_one_also_suspended():
    assert mail.taken_over(_rec(), True)
    assert mail.taken_over(_rec(team=None, controllers=["ao-x-lead"]), True), "a member by its controllers"
    assert mail.taken_over(_rec(suspended={"at": AGO, "why": "x"}), True), "the base fact: a suspension ends nothing"
    assert mail.taken_over(_rec(state="working"), True)


@pytest.mark.parametrize(
    ("kw", "agent"),
    [
        ({"team": None}, True),  # the person's own session: no team, no controllers
        ({"by_person": True, "controllers": ["ao-x-lead"]}, True),  # a lead's member the person resumed by hand
        ({"unattended": True, "kind": "agent"}, True),  # its mail wakes it
        ({"state": "exited"}, True),
        ({"state": "closed"}, True),
        ({"state": "scheduled"}, True),
        ({}, False),  # a shell: no agent
    ],
)
def test_taken_over_is_false_otherwise(kw, agent):
    assert not mail.taken_over(_rec(**kw), agent), kw


def test_taken_over_reads_the_derived_by_person():
    # a record from before the field: interactive, not supervised, no controllers reads as the person's own
    assert not mail.taken_over(_rec(by_person=None, supervised=False), True)
    assert mail.taken_over(_rec(by_person=None, supervised=True), True)


# -- the view ---------------------------------------------------------------------------------------


def _held(agent, **kw) -> Session:
    s = _rec(host=agent.host, **kw)
    agent.sessions[s.id] = s
    return s


def _taken(v: dict) -> tuple:
    return v["taken_over"], v.get("taken_lead"), v.get("taken_at"), v.get("taken_tail")


TAIL = "— its mail does not wake it; Hand back returns it"


async def test_the_view_carries_the_hovers_parts_for_each_stamp(agent):
    flip = _held(agent, mode_at=AGO, mode_by="person", mode_via="focus")
    assert _taken(agent._view(flip)) == (True, "taken over", AGO, f"by you {TAIL}")
    lead = _held(agent, id="ao-x-lead", name="lead-ao-1", unattended=True, kind="agent", team="t")
    flip.mode_by = lead.id
    assert _taken(agent._view(flip)) == (True, "taken over", AGO, f"by lead-ao-1 {TAIL}"), "the taker by its name"
    flip.mode_by = "ao-x-gone"
    assert agent._view(flip)["taken_tail"] == f"by ao-x-gone {TAIL}", "a taker the home does not know: its id"
    start = _held(agent, mode_at=AGO, mode_by=None, mode_via="start")
    assert _taken(agent._view(start)) == (True, "held interactive from its start,", AGO, TAIL)
    bare = _held(agent, mode_at=None, mode_by=None, mode_via=None)
    assert _taken(agent._view(bare)) == (True, "held interactive", None, TAIL)


async def test_the_view_carries_none_on_another_record(agent):
    assert agent._view(_held(agent, unattended=True, kind="agent"))["taken_over"] is False
    v = agent._view(_held(agent, team=None))
    assert v["taken_over"] is False and "taken_lead" not in v


async def test_none_on_a_node_or_on_an_unreachable_view(agent, monkeypatch):
    s = _held(agent, mode_at=AGO, mode_by="person", mode_via="focus")
    assert agent._view(s)["taken_over"] is True
    s.state = "unreachable"
    assert agent._view(s)["taken_over"] is False, "the record's own state"
    s.state = "idle"
    monkeypatch.setattr(agent, "mode", "node")
    assert agent._view(s)["taken_over"] is False, "the home's alone"
    monkeypatch.setattr(agent, "mode", "home")
    del agent.sessions[s.id]
    s.host = "laptop"
    agent.remote.setdefault("laptop", {})[s.id] = s
    agent.links["laptop"] = {"up": False, "since": None, "why": "down"}
    v = agent._view(s)
    assert v["state"] == "unreachable" and v["taken_over"] is False, "the host link down"
    agent.links["laptop"] = {"up": True, "since": AGO, "why": None}
    assert agent._view(s)["taken_over"] is True


async def test_the_held_row_reads_the_predicate_and_leaves_a_scheduled_member_out(agent):
    s = _held(agent, state="scheduled", start_at=_iso(NOW + timedelta(hours=1)))
    s.inbox = [MailEntry(id="m-1", from_="ao-x-w", to=[s.id], at=_iso(NOW - timedelta(hours=1)), kind="ask", text="?")]
    assert agent._view(s)["unread_unrung"] is None
    s.state = "idle"
    assert agent._view(s)["unread_unrung"] == 1


# -- the card ---------------------------------------------------------------------------------------


def _card(**kw) -> dict:
    """A taken-over member as the host agent lists it: idle, clean, its checklist passing."""
    rec = {
        "id": "ao-w", "name": "w", "kind": "interactive", "adapter": "claude-code", "dir": "/r/.claude/worktrees/w",
        "repo": "/r", "state": "idle", "since": "2026-09-21T01:00:00Z", "confidence": "hook", "pane": True,
        "tail": ["done."], "created": "2026-09-21T00:00:00Z", "seen_at": "2026-09-21T02:00:00Z",
        "unattended": False, "team": "t", "by_person": False,
        "git": {"branch": "w", "dirty": 0, "unpushed": 0, "upstream": "origin/w"},
        "taken_over": True, "taken_lead": "taken over", "taken_at": _ago(), "taken_tail": f"by you {TAIL}",
    }  # fmt: skip
    rec.update(kw)
    return rec


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    return templates, view


def _foot(html: str) -> str:
    return html.split('<div class="sc-foot">', 1)[1]


def _classes(html: str) -> list[str]:
    return re.search(r'<div class="card sc ([^"]*)"', html).group(1).split()


def test_the_full_card_is_marked_and_its_hover_composed_with_a_server_age(ui):
    templates, view = ui
    v = view(_card())
    assert v["taken_line"] == "taken over 3h 12m ago" and v["taken_hover"] == f"taken over 3h 12m ago by you {TAIL}"
    html = templates.get_template("card.html").render(s=v)
    assert "tko" in _classes(html) and 'data-mine="1"' in html
    mode = re.search(r'<span class="meta mode mine"([^>]*)>(.*?)</span>', html, re.S)
    assert "taken over" in mode.group(2) and "interactive" not in mode.group(2)
    assert f'title="taken over 3h 12m ago by you {TAIL}"' in mode.group(1)
    assert f'data-taken-at="{v["taken_at"]}"' in mode.group(1) and 'data-taken-lead="taken over"' in mode.group(1)
    assert "yours — no policy acts on it" not in html
    # the person's own interactive session carries none of it
    own = templates.get_template("card.html").render(s=view(_card(team=None, taken_over=False)))
    assert "tko" not in own and "taken over" not in own and "data-taken" not in own


@pytest.mark.parametrize(
    ("lead", "at", "line"),
    [
        ("taken over", True, "taken over 3h 12m ago"),
        ("held interactive from its start,", True, "held interactive from its start, 3h 12m ago"),
        ("held interactive", False, "held interactive"),
    ],
)
def test_the_compact_cards_last_line_in_each_form(ui, lead, at, line):
    templates, view = ui
    at = _ago() if at else ""
    v = view(_card(taken_lead=lead, taken_at=at, taken_tail=TAIL))
    assert v["taken_line"] == line
    html = templates.get_template("card.html").render(s={**v, "compact": True, "compact_line": "x"})
    assert "tko" in _classes(html)
    got = re.search(r'<div class="meta tkoline"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert re.sub(r"<[^>]+>", "", got).strip() == line
    if at:
        assert f'<span class="age" data-since="{at}">3h 12m</span>' in got
    glyph = re.search(r'<span class="mine"([^>]*)>', html).group(1)
    assert "data-taken-lead" in glyph and "yours: an interactive session" not in html
    # the line is the card's last, after the routed-around and held lines
    routed = {**v, "compact": True, "compact_line": "x", "routed_to": "asks go to the techlead", "routed_why": "w"}
    order = templates.get_template("card.html").render(s=routed)
    assert order.index("asks go to the techlead") < order.index("tkoline")


def test_a_taken_over_cards_foot_leads_with_hand_back_never_close(ui):
    templates, view = ui
    v = view(_card())
    assert v["ready_ok"] and v["slot"]["caption"] != "ready to close ✓", "handed back, not closed"
    for compact in (False, True):
        html = templates.get_template("card.html").render(s={**v, "compact": compact, "compact_line": "x"})
        foot = _foot(html)
        first = re.search(r"<(button|a) [^>]*>", foot).group(0)
        assert 'class="btn sm tko"' in first and 'data-act="mode"' in first and 'data-via="card"' in first
        assert 'data-unattended="0"' in first and "data-confirm" not in first
        assert ">Close session</button>" not in foot
        assert 'class="btn sm link" href="/focus/ao-w"' in foot, "Focus a plain link beside it"
        assert "Switch to unattended" not in foot and ">Close</button>" in foot, "more ⋯ keeps Close"
    # Focus still offers Close session: the record stays the person's own
    assert v["own"] is True


def test_a_taken_over_needs_you_card_keeps_its_lead_and_its_tint(ui):
    templates, view = ui
    perm = {"kind": "permission", "text": "Bash: ls", "tool_use_id": "tu"}
    v = view(_card(state="needs-you", pending=perm))
    html = templates.get_template("card.html").render(s=v)
    assert {"tko", "s-needs"} <= set(_classes(html))
    foot = _foot(html)
    assert foot.index(">Allow</button>") < foot.index(">Hand back</button>")
    # a compact card leads with Focus, Hand back after it
    compact = _foot(templates.get_template("card.html").render(s={**v, "compact": True, "compact_line": "x"}))
    assert "Allow" not in compact and compact.index("Focus</a>") < compact.index(">Hand back</button>")
    # a question: Focus leads, Hand back after
    q = view(_card(state="needs-you", pending={"kind": "question", "text": "a or b?"}))
    foot = _foot(templates.get_template("card.html").render(s=q))
    assert foot.index("Focus</a>") < foot.index(">Hand back</button>") and foot.count(">Hand back</button>") == 1
    css = (ROOT / "src/shiftlead/ui/static/app.css").read_text()
    assert ".sc.tko:not(.s-needs) { border-color: var(--warn-line); }" in css, "the amber border and ring win"


def test_the_taken_tokens_and_scoped_rules():
    css = (ROOT / "src/shiftlead/ui/static/app.css").read_text()
    light, dark = css.split('html[data-theme="dark"]', 1)
    assert "--taken: #fdba74; --taken-fg: #7c2d12;" in light
    assert "--taken: #fdba74; --taken-fg: #3a2410;" in dark.split("}", 1)[0]
    assert not re.search(r"(^|[\s,}])\.tko\b", css), "no bare .tko rule"


def test_the_header_counts_ready_without_a_taken_over_member_and_names_the_taken(ui):
    templates, view = ui
    from shiftlead.ui.app import team_groups

    clean = {"branch": "x", "dirty": 0, "unpushed": 0, "upstream": "origin/x"}
    views = [
        view(_card(id="ao-b", name="designer-ao-1")),
        view(_card(id="ao-a", name="fact-check-ao-1")),
        view(_card(id="ao-c", name="grinder-ao-1", unattended=True, kind="agent", taken_over=False, git=clean)),
    ]
    g = next(x for x in team_groups(views) if x["team"] == "t")
    assert g["taken"] == ["designer-ao-1", "fact-check-ao-1"] and g["ready"] == 1
    head = templates.get_template("group_head.html").render(g=g)
    assert re.search(
        r'<span class="meta tkocount" title="designer-ao-1, fact-check-ao-1 — taken over and not handed back; '
        r'each card says since when">2 taken over</span>',
        head,
    )
    none = {**g, "taken": []}
    assert "taken over" not in templates.get_template("group_head.html").render(g=none)
    assert "taken over" not in templates.get_template("group_head.html").render(g={**g, "team": None})


def test_no_team_group_lists_taken():
    from shiftlead.ui.app import team_groups

    views = [
        {"id": "ao-a", "name": "a", "team": "t", "state": "idle", "rank": 5, "controllers": [], "taken_over": True},
        {"id": "ao-b", "name": "b", "team": None, "state": "idle", "rank": 5, "controllers": [], "taken_over": True},
    ]
    groups = {g["team"]: g for g in team_groups(views)}
    assert groups["t"]["taken"] == ["a"] and all(g["taken"] == [] for k, g in groups.items() if k != "t")


def test_focus_fills_hand_back_on_a_taken_over_member_alone(ui):
    templates, view = ui
    focus = templates.get_template("focus.html")

    def fmodeact(v: dict) -> str:
        html = focus.render(s={**v, "grants_all": [], "ready": []}, host="h", active="Sessions")
        return re.search(r'<button class="([^"]*)"[^>]*id="fmodeact"', html).group(1)

    assert "tko" in fmodeact(view(_card())).split()
    resumed = view(_card(team=None, controllers=["ao-x-lead"], by_person=True, taken_over=False))
    assert resumed["mode_act"] == "Hand back" and "tko" not in fmodeact(resumed).split()
    js = (ROOT / "src/shiftlead/ui/static/app.js").read_text()
    assert 'ma.classList.toggle("tko", !!v.taken_over)' in js, "the live update follows the view"
    assert 'b.classList.toggle("tko", back && $("#fmodeact").classList.contains("tko"))' in js, "the sheet's fill()"
    assert "takenTitles();" in js, "the ticker rewrites the hover"
