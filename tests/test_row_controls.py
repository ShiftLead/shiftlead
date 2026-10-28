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


def test_hold_words_reach_td_hold_through_the_route(tmp_path, monkeypatch):
    """**Hold…**'s words go to the home's `td_hold` as `why`, spaces folded; none sends no `why` (TD-910)."""
    c, calls, _ = _route(tmp_path, monkeypatch)
    assert c.post("/api/ledger/hold", json={"repo": "samscrape", "id": "TD-7", "why": " after\n Friday "}).json()["ok"]
    assert calls[-1] == ("td_hold", {"repo": "samscrape", "id": "TD-7", "release": False, "why": "after Friday"})
    c.post("/api/ledger/hold", json={"repo": "samscrape", "id": "TD-7"})
    assert calls[-1] == ("td_hold", {"repo": "samscrape", "id": "TD-7", "release": False})


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
    """`ledger_for_you` gives its rows the page kind, an open blocker, a design's open builds and the hold's
    words, and the Inbox's ledger row draws the controls and the words from that output (TD-910)."""
    from markupsafe import Markup
    from test_queue import NOW

    root, r = _ledger(tmp_path)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-001"]["held"] = {"at": NOW.isoformat(), "why": "after Friday"}
    rows = {x["id"]: x for x in ui.ledger_for_you({root: r}, [], {}, NOW)["groups"][0]["rows"]}
    assert sorted(rows) == ["TD-001", "TD-004"]
    keys = {i: (x["page"], x["blocked_open"], x["builds_open"], x["hold_why"]) for i, x in rows.items()}
    assert keys == {"TD-001": ("blocked", True, True, "after Friday"), "TD-004": ("for-you", True, False, "")}
    row = ui.templates.get_template("inbox_row.html").module.ledger
    held = str(Markup(row(rows["TD-001"], "later")))
    assert "(after Friday)" in held and 'data-road="done"' not in held, "a design with open builds"
    assert 'data-road="done"' not in str(row(rows["TD-004"], "later")), "yours to do"


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
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-001"]["held"] = {"at": NOW.isoformat(), "why": "x"}
    inbox = {x["id"]: x for x in ui.ledger_for_you({root: r}, [], {}, NOW)["groups"][0]["rows"]}
    assert (inbox["TD-001"]["blocked_open"], inbox["TD-001"]["builds_open"]) == (True, True)


def test_a_held_marks_title_names_its_presser_from_the_readings_words(tmp_path):
    """TD-1127 (§4.8 *The record names who pressed*): the `queue` and `repos` readings carry a hold's presser
    in words beside `held.by` — the queue's `pressers`, the home's `_held_words` — and the *held (person)*
    mark, the Queue row's and the Queue card's held row's, draws them in its `title`; the word stays."""
    from types import SimpleNamespace

    from markupsafe import Markup
    from test_queue import NOW

    from sessionorc import queue
    from sessionorc.agent_tick import TickMixin

    root, r = _ledger(tmp_path)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-002"]["held"] = {"at": NOW.isoformat(), "by": "s-1", "why": "after Friday"}
    words = {"s-1": "the person's session paul-1"}.get
    rows = lambda q: {x["id"]: x for c in q["cards"] for x in (c["top"], *c["rows"])}  # noqa: E731
    held = rows(queue.reading({root: r}, [], NOW, pressers=lambda b: words(b) or b))["TD-002"]
    assert held["state"] == "held (person)"
    assert held["held"] == {
        "at": NOW.isoformat(),
        "by": "s-1",
        "why": "after Friday",
        "words": "the person's session paul-1",
    }
    assert "words" not in rows(queue.reading({root: r}, [], NOW))["TD-002"]["held"], "no graph, no words"
    tpl = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.state(r) }}')
    got = tpl.render(r=held)
    assert 'title="held by the person&#39;s session paul-1"' in got and "held (person) — after Friday" in got
    assert "title=" not in tpl.render(r={"state": "held (person)", "held": {"at": "t", "by": "person"}})
    ext = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.extras(e, "/c/r") }}')
    got = ext.render(e={"settle": "held 2h", "held_words": "the person's session paul-1", "settle_mark": "held"})
    assert 'title="held by the person&#39;s session paul-1">· held 2h' in got, "the Repo row's settle mark"

    home = SimpleNamespace(_presser_words=lambda b: words(b) or "the person")
    view = TickMixin._held_words(home, r)  # type: ignore[arg-type]
    assert {e["id"]: e["held"].get("words") for e in view["ledger"]["entries"] if e.get("held")} == {
        "TD-002": "the person's session paul-1"
    }
    assert "words" not in by["TD-002"]["held"], "the stored reading is left as it is"
    by["TD-002"].pop("held")
    assert TickMixin._held_words(home, r) is r, "nothing held: the reading itself"
    by["TD-002"]["held"] = next(e["held"] for e in view["ledger"]["entries"] if e["id"] == "TD-002")
    row = next(x for x in ui.ledger_for_you({root: r}, [], {}, NOW)["groups"][0]["rows"] if x["id"] == "TD-002")
    assert row["hold_by"] == "the person's session paul-1"
    drawn = str(Markup(ui.templates.get_template("inbox_row.html").module.ledger({**row, "home": "queue"}, "later")))
    assert 'title="held by the person&#39;s session paul-1"' in drawn


async def test_the_tick_hands_a_holds_presser_to_the_queue_and_the_repo_view(agent, tmp_path, monkeypatch):
    """TD-1180: the home's two call sites, not the functions alone — `_queue_pass` passes `pressers` to the
    Queue's reading and `_repo_view` runs `_held_words`, so both live readings carry `held.words`."""
    from conftest import park_ticks
    from test_queue import NOW

    await park_ticks(agent)
    root, r = _ledger(tmp_path)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-002"]["held"] = {"at": NOW.isoformat(), "by": "s-1", "why": "after Friday"}
    agent._repos = {root: r}
    monkeypatch.setattr(agent, "_presser_words", lambda b: "the person's session paul-1" if b == "s-1" else b)

    async def push(ev: dict[str, object]) -> None:
        pass

    monkeypatch.setattr(agent, "_broadcast", push)
    await agent._queue_pass(NOW)
    q = await agent.rpc_queue()
    rows = {x["id"]: x for c in q["cards"] for x in (c["top"], *c["rows"])}
    assert rows["TD-002"]["held"]["words"] == "the person's session paul-1", "the queue's pass names the presser"
    view = agent._repo_view(root)
    held = {e["id"]: e["held"] for e in view["ledger"]["entries"] if e.get("held")}
    assert held["TD-002"]["words"] == "the person's session paul-1", "the repos view names the presser"


def test_the_repo_ledger_rows_settle_mark_titles_the_presser_from_the_reading(tmp_path):
    """TD-1180: `ledger_lists` carries a reading's `held.words` onto its row as `held_words`, and the row it
    returns, not one handed the key by hand, draws the settle mark with *held by <words>* in its `title`."""
    from test_queue import NOW

    from shiftlead.ui import repo

    root, r = _ledger(tmp_path)
    by = {e["id"]: e for e in r["ledger"]["entries"]}
    by["TD-002"]["held"] = {
        "at": NOW.isoformat(),
        "by": "s-1",
        "why": "after Friday",
        "words": "the person's session paul-1",
    }
    rows = {e["id"]: e for lst in repo.ledger_lists(r, [], None, NOW) for e in lst["rows"]}
    assert rows["TD-002"]["held_words"] == "the person's session paul-1"
    assert rows["TD-005"]["held_words"] == "", "an entry nobody held has none"
    ext = ui.templates.env.from_string('{% import "queue_row.html" as q %}{{ q.extras(e, "/c/r") }}')
    assert 'title="held by the person&#39;s session paul-1">· held' in ext.render(e=rows["TD-002"])
