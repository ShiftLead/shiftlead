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
