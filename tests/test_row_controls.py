"""TD-905 (design §4.5 screen 12 *any open row*, §4.5a *Queue card: what needs the person*): the row's
controls are one macro in `queue_row.html` — Done… on a row that is not *yours to do* and not a design with
open builds, Back to design… on a pickable, live check or id-blocked row, and no Hold… or Release anywhere
(TD-1297) — and the page's road refuses where no team services the repo, or no lane takes design-first."""

from __future__ import annotations

from shiftlead.ui import app as ui


def _controls(**r) -> str:
    row = {"id": "TD-7", "title": "t", "repo": "r", "needs": None, "state": "", "page": "pickable"} | r
    tpl = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.controls(row, "/c/r") }}')
    return tpl.render(row=row)


def test_each_control_is_drawn_by_its_rule():
    got = _controls()
    assert 'data-road="done"' in got and 'data-road="design"' in got
    assert 'data-repo="/c/r"' in got and "Done…" in got and "Back to design…" in got
    mine = _controls(needs="owner", page="for-you")
    assert 'data-road="done"' not in mine and 'data-road="design"' not in mine
    design = _controls(page="design", builds_open=True)
    assert 'data-road="done"' not in design and 'data-road="design"' not in design
    assert 'data-road="done"' in _controls(page="design")
    blocked = _controls(page="blocked", blocked_open=True)
    assert 'data-road="design"' in blocked
    assert 'data-road="design"' not in _controls(page="blocked")
    for row in (got, mine, design, blocked, _controls(page="for-you", needs="decision")):
        assert "Hold…" not in row and "ledger_hold" not in row and "Release" not in row, "TD-1297"
    assert _controls(archived=True) == ""


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
    assert got.count('data-road="done"') == 1 and 'data-road="design"' in got and "Hold…" not in got


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


def test_back_to_design_takes_the_road_a_flow_stage_lane_serves(tmp_path, monkeypatch):
    """No member's own lane takes design-first, but a stage of the servicing team's current flow does: the
    road is open (TD-910)."""
    from types import SimpleNamespace

    from shiftlead import org as orgmod
    from shiftlead import teams

    f = tmp_path / "org.yml"
    f.write_text(
        f"projects:\n  p:\n    repos: {{r: {{h: {tmp_path}}}}}\n"
        "teams:\n  t:\n    repo: r\n    manager: {role: person}\n    members:\n"
        "      - {role: grinder, lane: free-pick}\n",
        encoding="utf-8",
    )
    org = orgmod.load(f)
    stages = [SimpleNamespace(lane=["free-pick"])]
    monkeypatch.setattr(teams, "compiled", lambda *a: SimpleNamespace(flow=SimpleNamespace(stages=stages)))
    assert "no lane of t takes design-first" in ui.road_refusal(org, str(tmp_path), "design", "h")
    stages.append(SimpleNamespace(lane=["design-first"]))
    assert ui.road_refusal(org, str(tmp_path), "design", "h") == ""


def _route(tmp_path, monkeypatch, refusal=""):
    """The UI app with the home faked: every call recorded, `road_refusal` answering `refusal`, and the
    host's registered checkouts one, `/c/samscrape`."""
    from fastapi.testclient import TestClient

    from sessionorc import hosts
    from shiftlead import org as orgmod

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, dict]] = []
    seen: list[str] = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            return {"decided": "x"}

    def refuse(_org, root, road, _host):
        seen.append(f"{root} {road}")
        return refusal

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(ui, "org_here", lambda: (orgmod.Org(teams={}, roles={}), []))
    monkeypatch.setattr(ui, "road_refusal", refuse)
    monkeypatch.setattr(
        hosts, "local_host", lambda: type("H", (), {"name": "h", "repos": lambda self: ["/c/samscrape"]})()
    )
    return TestClient(ui.create_app()), calls, seen


def test_the_hold_route_is_gone(tmp_path, monkeypatch):
    """TD-1297: no `/api/ledger/hold`, so nothing reaches a `td_hold` the home no longer serves."""
    c, calls, _ = _route(tmp_path, monkeypatch)
    got = c.post("/api/ledger/hold", json={"repo": "samscrape", "id": "TD-7", "why": "after Friday"})
    assert got.status_code in (404, 405) and [m for m, _ in calls if m == "td_hold"] == []


def test_the_road_goes_to_ledger_decide_by_the_checkout_and_a_refusal_is_a_409(tmp_path, monkeypatch):
    """`POST /api/person/ledger` with `road`: a Queue row's repo name is looked up to its registered checkout,
    a path is kept; the road and the words go to `ledger_decide`; where `road_refusal` refuses, a 409 in its
    words and no call (TD-910)."""
    c, calls, seen = _route(tmp_path, monkeypatch)
    got = c.post("/api/person/ledger", json={"repo": "samscrape", "id": "TD-7", "road": "design", "words": "w"})
    assert got.status_code == 200 and got.json()["decided"] == "x"
    assert seen == ["/c/samscrape design"]
    assert calls[-1] == ("ledger_decide", {"repo": "/c/samscrape", "id": "TD-7", "road": "design", "words": "w"})
    c.post("/api/person/ledger", json={"repo": "/elsewhere/r", "id": "TD-7", "road": "done"})
    assert seen[-1] == "/elsewhere/r done" and calls[-1][1]["repo"] == "/elsewhere/r"

    c, calls, _ = _route(tmp_path, monkeypatch, refusal="no team services samscrape: nobody would read the line")
    got = c.post("/api/person/ledger", json={"repo": "samscrape", "id": "TD-7", "road": "done"})
    assert got.status_code == 409 and "no team services samscrape" in got.json()["detail"]
    assert [m for m, _ in calls if m == "ledger_decide"] == []


def _ledger(tmp_path):
    """A ledger with a design and its open build, a design with none, a blocked for-you row and a pickable
    row: (root, the reading as the home keeps it)."""
    from test_queue import _entry, _repo

    return _repo(
        tmp_path,
        "r",
        [
            _entry(1, "a design", Priority="Medium", Kind="design-first"),
            _entry(2, "its build", Priority="Medium", Part_of="TD-001"),
            _entry(3, "a lone design", Priority="Medium", Kind="design-first"),
            _entry(4, "yours, blocked", Priority="Medium", Owner="paul", Blocked_by="TD-005"),
            _entry(5, "free", Priority="Medium"),
        ],
    )


def test_the_queue_builds_the_keys_the_controls_read(tmp_path):
    """`queue.reading` gives each row its page kind, an open blocker and a design's open builds, and the macro
    drawn from those rows, not a literal, puts Done… and Back to design… where the rule says (TD-910)."""
    from test_queue import NOW

    from sessionorc import queue

    root, r = _ledger(tmp_path)
    q = queue.reading({root: r}, [], NOW)
    rows = {x["id"]: x for c in q["cards"] for x in (c["top"], *c["rows"])}
    keys = {i: (x["page"], x["blocked_open"], x["builds_open"]) for i, x in rows.items()}
    assert keys == {
        "TD-001": ("blocked", True, True),
        "TD-002": ("pickable", False, False),
        "TD-003": ("design", False, False),
        "TD-004": ("for-you", True, False),
        "TD-005": ("pickable", False, False),
    }
    drawn = {i: _controls(**x) for i, x in rows.items()}
    assert 'data-road="done"' not in drawn["TD-001"] and 'data-road="done"' in drawn["TD-003"]
    assert 'data-road="design"' in drawn["TD-002"] and 'data-road="design"' in drawn["TD-005"]


def test_the_inbox_ledger_row_carries_the_keys_and_draws_the_controls_from_them(tmp_path):
    """`ledger_for_you` gives its rows the page kind, an open blocker and a design's open builds, and the
    Inbox's ledger row draws the controls from that output (TD-910). An old clock's `held` mark adds no row
    (TD-1297): the rows are the *for you* entries alone."""
    from markupsafe import Markup
    from test_queue import NOW

    root, r = _ledger(tmp_path)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-001"]["held"] = {"at": NOW.isoformat(), "why": "after Friday"}
    rows = {x["id"]: x for x in ui.ledger_for_you({root: r}, [], {}, NOW)["groups"][0]["rows"]}
    assert sorted(rows) == ["TD-004"]
    assert (rows["TD-004"]["page"], rows["TD-004"]["blocked_open"], rows["TD-004"]["builds_open"]) == (
        "for-you",
        True,
        False,
    )
    row = ui.templates.get_template("inbox_row.html").module.ledger
    drawn = str(Markup(row(rows["TD-004"], "later")))
    assert 'data-road="done"' not in drawn, "yours to do"
    assert "Release" not in drawn and "held (person)" not in drawn and "ledger · held" not in drawn


def test_a_parents_open_parts_keep_done_off_and_back_to_design_on(tmp_path):
    """TD-1130 (§4.5 screen 12, §4.9c): an entry some open entry names in `Part of:` has open builds and,
    blocked by its open parts, a way back to design; an open id a `Blocked by:` names is a blocker, never a
    build, whether the entry has archived parts or none (TD-1133 removed the not-yet-backfilled reading)."""
    from test_queue import NOW, _entry, _repo

    from sessionorc import queue

    root, r = _repo(
        tmp_path,
        "r",
        [
            _entry(1, "a design", Priority="Medium", Kind="design-first"),
            _entry(2, "its part", Priority="Medium", Part_of="TD-001"),
            _entry(3, "a converted design", Priority="Medium", Kind="design-first", Blocked_by="TD-005"),
            _entry(4, "a design with a blocker", Priority="Medium", Kind="design-first", Blocked_by="TD-005"),
            _entry(5, "free", Priority="Medium"),
        ],
        [_entry(9, "a done part", Part_of="TD-003")],
    )
    q = queue.reading({root: r}, [], NOW)
    rows = {x["id"]: x for c in q["cards"] for x in (c["top"], *c["rows"])}
    keys = {i: (x["page"], x["blocked_open"], x["builds_open"]) for i, x in rows.items()}
    assert keys["TD-001"] == ("blocked", True, True)
    assert keys["TD-002"] == ("pickable", False, False)
    assert keys["TD-003"] == ("blocked", True, False), "converted: TD-005 is a blocker"
    assert keys["TD-004"] == ("blocked", True, False), "no part names it: TD-005 is a blocker"
    assert 'data-road="done"' in _controls(**rows["TD-004"])
    drawn = _controls(**rows["TD-001"])
    assert 'data-road="done"' not in drawn and 'data-road="design"' in drawn
    assert 'data-road="done"' in _controls(**rows["TD-003"])


def test_no_reading_or_row_carries_a_hold_and_the_repo_row_settles_with_no_press(tmp_path):
    """TD-1297: the Queue's rows carry no `held`, the Repo page's ledger rows no `held_words` or
    `settle_mark`, and the Repo row draws *settles in 7m* with no Hold or Release beside it; an old clock's
    `held` mark on the reading is read as nothing."""
    from datetime import timedelta

    from test_queue import NOW

    from sessionorc import queue
    from shiftlead.ui import repo

    root, r = _ledger(tmp_path)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-002"]["held"] = {"at": NOW.isoformat(), "by": "s-1", "why": "after Friday"}
    by["TD-005"]["settling"] = {"until": (NOW + timedelta(minutes=7, seconds=30)).isoformat()}
    q = queue.reading({root: r}, [], NOW)
    for c in q["cards"]:
        for x in (c["top"], *c["rows"]):
            assert "held" not in x and x["state"] != "held (person)", x["id"]
    rows = {e["id"]: e for lst in repo.ledger_lists(r, [], None, NOW) for e in lst["rows"]}
    assert all("held_words" not in e and "settle_mark" not in e for e in rows.values())
    assert rows["TD-002"]["settle"] == "" and rows["TD-005"]["settle"] == "settles in 7m"
    ext = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.extras(e, "/c/r") }}')
    got = ext.render(e=rows["TD-005"])
    assert '<span class="meta settle">· settles in 7m</span>' in got
    assert "<button" not in got and "data-tdhold" not in got and "Release" not in got
