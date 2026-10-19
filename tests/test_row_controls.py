"""TD-905 (design §4.5 screen 12 *any open row*, §4.5a *Queue card: what needs the person*, *Repo page:
Hold / Release on an entry*): the row's controls are one macro in `queue_row.html` — Done… on a row that is
not *yours to do* and not a design with open builds, Back to design… on a pickable, live check or id-blocked
row, Hold… where a lane takes the row or it is *for you*, never on a held one — and the page's road refuses
where no team services the repo, or no lane takes design-first."""

from __future__ import annotations

from shiftlead.ui import app as ui


def _controls(**r) -> str:
    row = {"id": "TD-7", "title": "t", "repo": "r", "needs": None, "state": "", "page": "pickable"} | r
    tpl = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.controls(row, "/c/r") }}')
    return tpl.render(row=row)


def test_each_control_is_drawn_by_its_rule():
    got = _controls()
    assert 'data-road="done"' in got and 'data-road="design"' in got and 'data-act="ledger_hold"' in got
    assert 'data-repo="/c/r"' in got and "Done…" in got and "Back to design…" in got and "Hold…" in got
    mine = _controls(needs="owner", page="for-you")
    assert 'data-road="done"' not in mine and 'data-road="design"' not in mine and "Hold…" in mine
    design = _controls(page="design", builds_open=True)
    assert 'data-road="done"' not in design and 'data-road="design"' not in design and "Hold…" in design
    assert 'data-road="done"' in _controls(page="design")
    blocked = _controls(page="blocked", blocked_open=True)
    assert 'data-road="design"' in blocked and "Hold…" not in blocked, "no lane takes a blocked row"
    assert 'data-road="design"' not in _controls(page="blocked")
    assert "Hold…" not in _controls(state="held (person)")
    assert _controls(archived=True) == ""


def test_held_words_are_drawn_after_the_state_word():
    tpl = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.state(r) }}')
    got = tpl.render(r={"state": "held (person)", "held": {"at": "t", "why": "after Friday"}})
    assert "held (person) — after Friday" in got


def test_the_road_is_refused_where_nobody_would_read_the_line(tmp_path):
    from shiftlead import org as orgmod

    org = orgmod.Org(teams={}, roles={})
    assert "no team services" in ui.road_refusal(org, str(tmp_path), "done", "h")


def test_a_cards_top_entry_draws_the_controls_in_its_head():
    """A one-entry card has no rows: its head is the entry's row, so the head draws the macro (found by the
    scratch-home check, 2026-10-19)."""
    top = {"id": "TD-7", "qid": "r#TD-7", "show": "TD-7", "title": "t", "repo": "r", "needs": None, "state": ""}
    tpl = ui.templates.env.from_string('{% import "queue_card.html" as c %}{{ c.card(card) }}')
    got = tpl.render(card={"id": "r#TD-7", "top": top | {"page": "pickable"}, "ids": ["r#TD-7"], "group": "up_next"})
    assert got.count('data-road="done"') == 1 and 'data-road="design"' in got and "Hold…" in got
    held = tpl.render(card={"id": "r#TD-7", "top": top | {"page": "pickable", "state": "held (person)"}, "ids": []})
    assert "Hold…" not in held and 'data-road="done"' in held


def test_back_to_design_is_refused_where_no_lane_takes_design_first(tmp_path):
    from shiftlead import org as orgmod

    def org(members: str):
        f = tmp_path / "org.yml"
        f.write_text(
            f"projects:\n  p:\n    repos: {{r: {{h: {tmp_path}}}}}\n"
            f"teams:\n  t:\n    repo: r\n    manager: {{role: person}}\n    members:\n{members}",
            encoding="utf-8",
        )
        return orgmod.load(f)

    grind = org("      - {role: grinder, lane: free-pick}\n")
    assert ui.road_refusal(grind, str(tmp_path), "done", "h") == ""
    assert "no lane of t takes design-first" in ui.road_refusal(grind, str(tmp_path), "design", "h")
    both = org("      - {role: grinder, lane: free-pick}\n      - {role: designer, lane: design-first}\n")
    assert ui.road_refusal(both, str(tmp_path), "design", "h") == ""
