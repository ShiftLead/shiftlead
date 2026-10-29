"""TD-227 slice 3, design §4.5a *Inbox row: team start* and the team card's *work waiting* note
(§6 rule 8): the row drawn from the home's `work_waiting` alone — counted, the ids linked to the
Repo page, the bound that held a start back said in words — its Snooze by time in the attention
store, Dismiss through `clear_work`, and the card's note beside *wound down*."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiftlead import teamrun
from shiftlead.ui import app as uiapp
from shiftlead.ui.app import inbox_sections
from shiftlead.ui.inbox import lanes_hold, lanes_rows, work_held, work_note, work_rows, work_started

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
AT = "2026-09-30T11:00:00+00:00"


def mark(**kw):
    return {
        "at": AT,
        "repo": "/home/k/agentorc",
        "members": {"grinder-ao-1": ["TD-213", "TD-214"], "designer-ao-1": ["TD-214", "TD-223"]},
        **kw,
    }


def test_a_mark_is_one_counted_row_with_its_ids_once_and_aged_from_at():
    (r,) = work_rows({"ao-grind": mark()}, {"ao-grind": "2026-09-30T00:56:00+00:00"}, NOW)
    assert r["row"] == "work" and r["sid"] == "work:ao-grind" and r["team"] == "ao-grind"
    assert r["ids"] == ["TD-213", "TD-214", "TD-223"] and r["n"] == 3 and r["more"] == 0
    assert r["repo"] == "agentorc" and r["at"] == AT and r["age"] == "1h 0m" and r["held"] == ""
    assert r["wound_down"] == "2026-09-30T00:56:00+00:00"
    assert "its lanes gained 3 entries: TD-213, TD-214, TD-223" in r["text"]
    s = inbox_sections([], states=[r])
    assert s["count"] == 1 and s["needs"][0]["row"] == "work"
    assert work_rows({}) == [] and work_rows(None) == [] and work_rows({"g": {"members": {}}}) == []
    assert work_rows({"g": "junk"}) == []


def test_a_running_team_names_its_finished_members_and_is_running():
    """§6 rule 8 *A member that finished while its team runs on* (TD-466): a team the card does not read
    as wound down, its mark naming members, reads *ao-grind · grinder-ao-1 finished <t> · its lane
    gained …*, each member by its record's name and the instant it closed."""
    recs = [
        {"id": "ao-g1", "name": "grinder-ao-1", "team": "ao-grind", "closed_at": "2026-09-30T00:56:00Z"},
        {"id": "ao-g1-old", "name": "grinder-ao-1", "team": "ao-grind", "closed_at": "2026-09-29T08:00:00Z"},
        {"id": "ao-g2", "name": "grinder-ao-2", "team": "ao-grind", "closed_at": "2026-09-30T01:10:00Z"},
        {"id": "ao-x1", "name": "grinder-ao-1", "team": "other", "closed_at": "2026-09-30T05:00:00Z"},
    ]
    # the mark keys its members by name (`_work_mark`); the time is the team's latest close under it
    (r,) = work_rows({"ao-grind": mark(members={"grinder-ao-1": ["TD-428"]})}, {}, NOW, records=recs)
    assert r["running"] and r["lanes"] == "its lane"
    assert r["finished"] == [{"name": "grinder-ao-1", "at": "2026-09-30T00:56:00Z"}]
    assert r["text"] == "ao-grind · grinder-ao-1 finished 2026-09-30T00:56:00Z · its lane gained 1 entry: TD-428"
    two_mark = mark(members={"grinder-ao-1": ["TD-1"], "grinder-ao-2": ["TD-2"]})
    (two,) = work_rows({"ao-grind": two_mark}, {}, NOW, records=recs)
    assert "grinder-ao-1 finished 2026-09-30T00:56:00Z, grinder-ao-2 finished 2026-09-30T01:10:00Z" in two["text"]
    assert "their lanes gained 2 entries: TD-1, TD-2" in two["text"]
    # a member the page holds no closed record of is drawn with no time; a wound-down team is the old row
    (gone,) = work_rows({"ao-grind": mark(members={"gone-ao-1": ["TD-1"]})}, {}, NOW)
    assert gone["text"].startswith("ao-grind · gone-ao-1 finished · its lane gained")
    (down,) = work_rows({"ao-grind": mark()}, {"ao-grind": AT}, NOW, records=recs)
    assert not down["running"] and down["text"].startswith("ao-grind · wound down · its lanes gained")


def test_five_ids_at_most_and_one_entry_is_singular():
    many = mark(members={"g": [f"TD-{i:03}" for i in range(1, 9)]})
    (r,) = work_rows({"g": many}, now=NOW)
    assert len(r["ids"]) == 5 and r["more"] == 3 and r["n"] == 8 and r["text"].endswith("TD-005 and 3 more")
    (one,) = work_rows({"g": mark(members={"g": ["TD-001"]})}, now=NOW)
    assert "gained 1 entry: TD-001" in one["text"] and one["wound_down"] == ""


def test_a_questions_end_is_its_own_clause_before_the_ids_and_one_of_the_notes_n():
    """§4.5a *Inbox row: team start* and *work waiting* note (§6 rule 8 *A question's end is work*,
    TD-274): `work_waiting.questions` is a clause of its own before the ids where both stand — *<name>'s
    steer about TD-222 lapsed to its default*, *… ask about TD-223 was answered* — its reference out
    of the lanes' count; alone, the row stands with no *its lanes gained*; the card's note counts it as
    one of the n and names it in the tooltip. A mark with no kind reads a lapse as a steer."""
    q = [
        {"id": "m-s", "ref": "TD-222", "name": "designer-ao-1", "how": "lapsed"},
        {"id": "m-a", "ref": "TD-223", "name": "designer-ao-1", "how": "answered", "kind": "ask"},
    ]
    both = mark(members={"designer-ao-1": ["TD-222", "TD-223", "TD-300"]}, questions=q)
    (r,) = work_rows({"g": both}, now=NOW)
    assert r["ids"] == ["TD-300"] and r["n"] == 1
    assert r["text"] == (
        "g · wound down · designer-ao-1's steer about TD-222 lapsed to its default; designer-ao-1's ask about "
        "TD-223 was answered; its lanes gained 1 entry: TD-300"
    )
    (alone,) = work_rows({"g": mark(members={"designer-ao-1": ["TD-222"]}, questions=q[:1])}, now=NOW)
    assert (
        alone["n"] == 0 and alone["text"] == "g · wound down · designer-ao-1's steer about TD-222 lapsed to its default"
    )
    note = work_note(both, NOW)
    assert note["n"] == 3 and note["title"].endswith("designer-ao-1's ask about TD-223 was answered")
    html = uiapp.templates.get_template("inbox_row.html").module.work_row({**alone, "snoozed_until": ""}, "needs")
    assert '<a class="mono" href="/repo/agentorc#TD-222">TD-222</a> lapsed to its default' in str(html)
    assert "entries:" not in str(html) and "entry:" not in str(html)  # no lanes clause
    both_html = str(uiapp.templates.get_template("inbox_row.html").module.work_row({**r, "snoozed_until": ""}, "needs"))
    assert (
        'was answered; its lanes gained 1 entry: <a class="mono" href="/repo/agentorc#TD-300">TD-300</a>' in both_html
    )


def test_a_held_start_says_which_bound():
    early = (NOW - timedelta(minutes=12)).isoformat()
    cases = {
        "grind is over its line": {"why": "usage", "profile": "grind"},
        "grind is over its line, resets in 3h 0m": {
            "why": "usage",
            "profile": "grind",
            "resets": (NOW + timedelta(hours=3)).isoformat(),
        },
        "its stop time has passed": {"why": "until", "until": AT},
        "started 3 times today": {"why": "day", "count": 3},
        "started 12m ago and wound down again": {"why": "early", "started": early},
        "laptop is unreachable": {"why": "link", "host": "laptop"},
        "laptop and nas are unreachable": {"why": "link", "host": "laptop", "hosts": ["laptop", "nas"]},
        "no record to start": {"why": "nothing"},
    }
    for words, held in cases.items():
        assert work_held(held, NOW) == words
    crossed = [{"line": "prs", "value": 9, "limit": 8}]
    said = work_held({"why": "balance", "repo": "/r", "crossed": crossed}, NOW)
    assert said.startswith("its repo is over its line") and "the line is 8" in said
    assert work_held(None, NOW) == "" and work_held("junk", NOW) == ""
    past = {"why": "usage", "profile": "grind", "resets": AT}  # a reset already past names no time
    assert work_held(past, NOW) == "grind is over its line"
    (r,) = work_rows({"g": mark(held={"why": "nothing"})}, now=NOW)
    assert r["held"] == "no record to start" and r["text"].endswith("not started: no record to start")


def test_a_snoozed_row_is_in_no_count_and_later_entries_do_not_wake_it():
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    for m in (mark(), mark(members={"g": ["TD-900"]})):
        s = inbox_sections([], states=work_rows({"ao-grind": m}), attention_snoozed={"work:ao-grind|work": until})
        assert s["count"] == 0 and [e["row"] for e in s["snoozed"]] == ["work"]


def test_the_cards_note_and_the_started_line():
    n = work_note(mark(), NOW)
    assert n["n"] == 3 and n["at"] == AT and n["age"] == "1h 0m"
    assert n["title"] == "grinder-ao-1: TD-213, TD-214; designer-ao-1: TD-214, TD-223"
    assert work_note(None) is None and work_note({"members": {}}) is None
    older = {"at": "2026-09-30T09:00:00+00:00", "why": "work", "ids": ["TD-100"]}
    newer = {"at": "2026-09-30T11:30:00+00:00", "why": "work", "ids": ["TD-213", "TD-214", "TD-223"]}
    live = {"state": "idle", "restarts": [older, {"at": "2026-09-30T11:45:00+00:00", "why": "crash"}, newer]}
    got = work_started(
        [live, {"state": "exited", "restarts": [{"at": "2026-09-30T11:50:00+00:00", "why": "work"}]}], NOW
    )
    assert got == {"at": newer["at"], "age": "30m", "first": "TD-213", "more": 2}
    assert work_started([{"state": "idle", "restarts": [{"at": AT, "why": "crash"}]}]) is None
    assert work_started([{"state": "idle", "restarts": [{"at": AT, "why": "work", "error": "x"}]}]) is None
    # a start whose replays partly failed says how many came up and which did not (TD-227)
    one = {"why": "work", "ids": ["TD-213"], "start": AT, "of": 3}
    crew = [
        {"name": "grinder-ao-1", "state": "working", "restarts": [{**one, "at": AT}]},
        {"name": "grinder-ao-2", "state": "idle", "restarts": [{**one, "at": AT}]},
        {"name": "manager-ao-1", "state": "exited", "restarts": [{**one, "at": AT, "error": "no launch record"}]},
    ]
    got = work_started(crew, NOW)
    assert (got["n"], got["of"], got["failed"]) == (2, 3, ["manager-ao-1"])
    assert "failed" not in work_started(crew[:2], NOW), "every replay came up: the note is as it was"
    # started later by a crash restart or a person: the errored entry rides its history, and it is up
    back = {"name": "manager-ao-1", "state": "idle", "restarts": [*crew[2]["restarts"], {"at": AT, "why": "start"}]}
    assert "failed" not in work_started([*crew, back], NOW) and "failed" not in work_started([*crew[:2], back], NOW)


def _session(name: str, **kw) -> dict:
    return {
        "id": f"ao-r-{name}",
        "name": name,
        "host": "kmaster",
        "dir": "/tmp/r",
        "adapter": "claude",
        "state": "exited",
        "team": "wt",
        "unattended": True,
        "controllers": [],
        "capabilities": [],
        "created": "2026-09-30T00:00:00+00:00",
        **kw,
    }


@pytest.fixture
def page(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (home / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    (home / "org.yml").write_text(
        f"projects:\n  p:\n    repos:\n      r: {{kmaster: {tmp_path}}}\n"
        "teams:\n  wt:\n    repo: r\n    manager: {role: manager, name: m}\n"
        "    members: [{role: grinder, name: g}]\n"
    )
    calls: list[tuple[str, dict]] = []
    work = {"wt": mark(members={"g": ["TD-213", "TD-214"]})}
    out = {"at": "2026-09-30T00:56:00+00:00", "why": "nothing to pick"}
    answers = {
        "list": [_session("m", out_of_work=out), _session("g", out_of_work=out)],
        "inbox": {"id": "person", "entries": [], "threads": {}, "sends": [], "unread": 0},
        "identity": {
            "host": "kmaster",
            "mode": "off",
            "detached_check": False,
            "tally": {},
            "alarms": [],
            "sessions": {},
        },
        "usage": {},
        "host": {
            "host": "kmaster",
            "home": "kmaster",
            "mode": "home",
            "home_reachable": True,
            "links": {},
            "work": work,
        },
        "clear_work": {"team": "wt", "cleared": True, "ids": ["TD-213", "TD-214"]},
        "attention_snooze": {"id": "person", "row": "work:wt|work", "snoozed_until": "x"},
    }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def call(self, method, **params):
            calls.append((method, params))
            return answers[method]

    monkeypatch.setattr(uiapp, "LocalClient", FakeClient)
    with TestClient(uiapp.create_app()) as c:
        c.app.state.answers = answers  # a test that reads a running team moves the list
        yield c, calls, work


def test_the_inbox_draws_the_row_with_its_three_controls_and_counts_it(page):
    c, calls, work = page
    html = c.get("/inbox").text
    assert 'data-row="work"' in html and "its lanes gained 2 entries:" in html
    assert '<a class="mono" href="/repo/agentorc#TD-213">TD-213</a>' in html
    assert 'data-at="2026-09-30T00:56:00+00:00"' in html  # wound down <t>, the card's own reading
    assert 'data-act="work_start" data-id="person" data-team="wt"' in html
    assert 'data-sid="work:wt" data-row="work" data-when="1w"' in html
    assert 'data-act="clear_work" data-id="person" data-team="wt"' in html and "not started:" not in html
    assert c.get("/api/person/inbox").json()["needs"] == 1
    work["wt"]["held"] = {"why": "day", "count": 3}
    assert "not started: started 3 times today" in c.get("/inbox").text
    assert c.post("/api/person/clear_work", json={"team": "wt"}).json()["cleared"] is True
    assert c.post("/api/person/clear_work", json={}).status_code == 400
    assert c.post("/api/person/attention_snooze", json={"id": "work:wt", "kind": "work", "until": "x"}).json()["ok"]
    assert ("clear_work", {"team": "wt"}) in calls
    assert ("attention_snooze", {"id": "work:wt", "kind": "work", "until": "x"}) in calls


def test_the_org_counts_the_row_and_the_card_says_work_waiting(page):
    c, _calls, work = page
    got = c.get("/")
    assert got.status_code == 200 and 'id="personneeds">1<' in got.text
    assert "wound down" in got.text and "2 entries waiting since" in got.text
    assert 'title="g: TD-213, TD-214"' in got.text
    work.clear()
    again = c.get("/").text
    assert "entries waiting since" not in again and 'id="personneeds">1<' not in again


def test_a_running_teams_row_starts_its_members_through_work_start(page):
    """The row for a team that runs on (§4.5a **Inbox row: team start**, TD-466): its finished member
    named, its **Start** marked running so the page posts `work_start`, which the server refuses in
    the row's words when a bound holds it back."""
    c, calls, work = page
    answers = c.app.state.answers
    out = {"at": "2026-09-30T00:56:00+00:00", "why": "nothing to pick"}
    answers["list"] = [
        _session("m", state="idle"),
        _session("g", state="closed", out_of_work=out, closed_at="2026-09-30T00:56:00+00:00"),
    ]
    work["wt"] = mark(members={"g": ["TD-213"]})
    html = c.get("/inbox").text
    assert re.search(r"· g finished <span class=\"localtime\" data-at=\"2026-09-30T00:56:00\+00:00\"", html)
    assert "its lane gained 1 entry:" in html and "wound down" not in html
    assert 'data-act="work_start" data-id="person" data-team="wt" data-running="1"' in html
    answers["work_start"] = {"team": "wt", "started": True, "ids": ["TD-213"], "held": None}
    assert c.post("/api/person/work_start", json={"team": "wt"}).json()["started"] is True
    assert ("work_start", {"team": "wt"}) in calls
    answers["work_start"] = {"team": "wt", "started": False, "ids": ["TD-213"], "held": {"why": "day", "count": 3}}
    held = c.post("/api/person/work_start", json={"team": "wt"})
    assert held.status_code == 409 and held.json()["detail"] == "started 3 times today"
    answers["work_start"] = {"team": "wt", "started": False, "ids": [], "held": None}
    assert c.post("/api/person/work_start", json={"team": "wt"}).status_code == 409
    assert c.post("/api/person/work_start", json={}).status_code == 400


def test_the_team_headers_times_stay_fuzzy():
    """The header's *started <t>* and *waiting since <t>* draw the age the server wrote, the instant on
    hover: a `localtime` span there was rewritten to a datetime by the page's tick and back to the age
    by each header delta, so the two flashed in turn."""
    from shiftlead.ui.app import team_groups

    rec = {"id": "w", "name": "w", "team": "t", "state": "idle", "state_class": "idle", "state_label": "idle",
           "scraped": False, "rank": 5, "controllers": [], "capabilities": []}  # fmt: skip
    (g,) = team_groups([rec])
    render = uiapp.templates.get_template("group_head.html").render
    head = render(g={**g, "work_started": {"at": AT, "age": "2m", "first": "TD-213"}})
    assert f'started <span title="{AT}">2m ago</span> for TD-213' in head and "localtime" not in head
    note = {"at": AT, "age": "5m", "n": 2, "title": "g: TD-213, TD-214"}
    head = render(g={**g, "live": False, "wound_down": True, "work_note": note})
    assert f'2 entries waiting since <span title="{AT}">5m ago</span>' in head and "localtime" not in head


def test_a_stopped_teams_row_says_how_it_stopped_and_is_never_a_running_teams():
    """§6 rule 8 *A team that stopped* (TD-781, TD-782 slice 2): a mark carrying `stopped` reads *ao-grind ·
    stopped at its stop time <t> · its lanes gained …*, *by you* for `person`, nothing more for `other`;
    `<t>` is `stopped.at`, never the card's *wound down*; it is never *finished*, so its Start is the
    card's; under `on_work: start` it ends *not started: a stopped team is started by Start*; one the
    person stopped is `later`, out of Needs you and its count, and `until` and `other` are counted."""
    recs = [{"id": "ao-g1", "name": "grinder-ao-1", "team": "ao-grind", "closed_at": "2026-09-30T00:56:00Z"}]
    stop = "2026-09-30T02:00:00+00:00"
    words = {"until": "stopped at its stop time", "person": "stopped by you", "other": "stopped"}
    rows = {}
    for by, said in words.items():
        m = mark(members={"grinder-ao-1": ["TD-428"]}, stopped={"by": by, "at": stop})
        # `wound` naming no team and a member's closed record: a running team's row but for `stopped`
        (r,) = work_rows({"ao-grind": m}, {}, NOW, records=recs, on_work=lambda t: "ask")
        assert r["text"] == f"ao-grind · {said} · its lanes gained 1 entry: TD-428", by
        assert not r["running"] and r["finished"] == [] and r["wound_down"] == stop and r["held"] == ""
        assert r["stopped"] == by and r["later"] is (by == "person")
        rows[by] = r
    (started,) = work_rows(
        {"ao-grind": mark(stopped={"by": "until", "at": stop})}, {"ao-grind": AT}, NOW, on_work=lambda t: "start"
    )
    assert started["held"] == "a stopped team is started by Start" and started["wound_down"] == stop
    assert started["text"].endswith("· not started: a stopped team is started by Start")
    # a hold the home wrote is its own words; a mark with no `stopped` is the wound-down row as it was
    (held,) = work_rows({"t": mark(stopped={"by": "other", "at": stop}, held={"why": "day", "count": 3})}, {})
    assert held["held"] == "started 3 times today"
    (down,) = work_rows({"t": mark()}, {"t": AT}, NOW, on_work=lambda t: "start")
    assert down["held"] == "" and down["stopped"] == "" and not down["later"]
    s = inbox_sections([], states=list(rows.values()))
    assert s["count"] == 2 and sorted(e["stopped"] for e in s["needs"]) == ["other", "until"]
    assert [e["stopped"] for e in s["later"]] == ["person"]  # Later's, uncounted (TD-782 slice 3)


def test_a_stopped_teams_row_and_card_on_the_pages(page):
    """The Inbox draws a stopped team's row with the card's Start (no `data-running`), and the Org card
    says *stopped* with its *work waiting* note (§4.5a *team card: work waiting note*, TD-781)."""
    c, _calls, work = page
    answers = c.app.state.answers
    answers["list"] = [_session("m"), _session("g", closed_at="2026-09-30T00:56:00+00:00")]  # nobody declared
    work["wt"] = mark(members={"g": ["TD-213"]}, stopped={"by": "other", "at": "2026-09-30T01:00:00+00:00"})
    html = c.get("/inbox").text
    assert re.search(r"wt · stopped <span class=\"localtime\" data-at=\"2026-09-30T01:00:00\+00:00\"", html)
    assert 'data-act="work_start" data-id="person" data-team="wt" title=' in html and "finished" not in html
    assert c.get("/api/person/inbox").json()["needs"] == 1
    org = c.get("/").text
    assert '<span class="meta">stopped</span>' in org and "1 entry waiting since" in org
    work["wt"]["stopped"]["by"] = "person"
    assert c.get("/api/person/inbox").json()["needs"] == 0
    # the person's own Stop: under Later, uncounted (TD-782 slice 3), its Start the card's
    later = c.get("/inbox").text.split('id="rows-later"', 1)[1].split("</section>", 1)[0]
    assert "wt · stopped by you" in later and 'data-act="work_start" data-id="person" data-team="wt"' in later
    assert 'data-act="clear_work"' in later  # a stored mark: Dismiss clears it


async def _answer(v):
    return v


def lanes(*ids, n=None):
    """A `teamrun.lanes` reading: one grinder role holding `ids`, or `n` None for a ledger unread."""
    got = len(ids) if n is None else n
    return {
        "line": f"grinder: {len(ids)} pickable",
        "empty": not ids,
        "roles": {"grinder": {"n": got}},
        "ids": list(ids),
    }


def test_a_team_with_no_record_is_a_later_row_of_what_its_lanes_hold():
    """§6 rule 8 *A team with no record* (TD-781, TD-782 slice 3): *dc-grind · stopped · its lanes hold 1
    entry: TD-119*, under Later, uncounted, under `ask` and `start` and never `off`; drawn only while no
    unattended record carries the badge (a person's own session does not take it away), and only for a
    reading that holds an entry — an unread ledger is *unknown*, never a row."""
    teams = [{"name": "dc-grind", "repo": "/home/k/agent-cadence"}, {"name": "ao-grind", "repo": "agentorc"}]
    readings = {"dc-grind": lanes("TD-119"), "ao-grind": lanes(*(f"TD-{i}" for i in range(1, 8)))}
    rows = lanes_rows(teams, readings, on_work=lambda t: "ask")
    dc, ao = sorted(rows, key=lambda r: r["team"], reverse=True)
    assert dc["row"] == "lanes" and dc["sid"] == "lanes:dc-grind" and dc["later"] and dc["repo"] == "agent-cadence"
    assert dc["text"] == "dc-grind · stopped · its lanes hold 1 entry: TD-119" and dc["ids"] == ["TD-119"]
    assert ao["n"] == 7 and ao["ids"] == ["TD-1", "TD-2", "TD-3", "TD-4", "TD-5"] and ao["more"] == 2
    assert ao["text"].endswith("TD-4, TD-5 and 2 more")
    assert len(lanes_rows(teams, readings, on_work=lambda t: "start")) == 2
    assert lanes_rows(teams, readings, on_work=lambda t: "off") == []
    mine = [{"id": "ao-p", "team": "dc-grind", "unattended": False}]
    assert len(lanes_rows(teams, readings, records=mine, on_work=lambda t: "ask")) == 2
    crew = [{"id": "ao-w", "team": "dc-grind", "unattended": True, "state": "closed"}]
    assert [r["team"] for r in lanes_rows(teams, readings, records=crew, on_work=lambda t: "ask")] == ["ao-grind"]
    unread = {"dc-grind": lanes(n=None) | {"roles": {"grinder": {"n": None}}}, "ao-grind": lanes()}
    assert lanes_rows(teams, unread, on_work=lambda t: "ask") == [] and lanes_rows(teams, {}) == []
    assert lanes_hold(None) is None and lanes_hold(unread["dc-grind"]) is None and lanes_hold(lanes()) == []
    # Later's, never counted; a snooze under `lanes:<team>` sets it aside as any state row's
    s = inbox_sections([], states=[dc], now=NOW)
    assert s["count"] == 0 and [e["id"] for e in s["later"]] == ["lanes:dc-grind"] and not s["needs"]
    until = (NOW + timedelta(days=1)).isoformat()
    s = inbox_sections([], states=[dc], attention_snoozed={"lanes:dc-grind|lanes": until}, now=NOW)
    assert not s["later"] and [e["id"] for e in s["snoozed"]] == ["lanes:dc-grind"]


def test_a_team_with_no_record_on_the_inbox_and_its_card(page, monkeypatch):
    """The Inbox draws the no-record row under Later with Start and Snooze kept under `lanes:<team>` and no
    Dismiss; the Org card reads *· its lanes hold n entries* beside *stopped*, its tooltip Start's line; the
    lanes are read at most once in `DEFS_TTL` (§4.5a *team card: work waiting note*, TD-781)."""
    c, _calls, work = page
    reads: list[str] = []

    def fake(call, org, name, host):
        reads.append(name)
        return lanes("TD-119", "TD-120")

    monkeypatch.setattr(teamrun, "lanes", fake)
    work.clear()
    c.app.state.answers["list"] = []
    html = c.get("/inbox").text
    later = html.split('id="rows-later"', 1)[1].split("</section>", 1)[0]
    assert "wt · stopped · its lanes hold 2 entries:" in later and 'data-row="lanes"' in later
    assert '<a class="mono" href="/repo/r#TD-119">TD-119</a>' in later
    assert 'data-act="work_start" data-id="person" data-team="wt"' in later and "data-running" not in later
    assert 'data-sid="lanes:wt" data-row="lanes" data-when="1d"' in later and "clear_work" not in later
    assert c.get("/api/person/inbox").json()["needs"] == 0
    org = c.get("/").text
    assert '<span class="meta lanesheld" title="grinder: 2 pickable">· its lanes hold 2 entries</span>' in org
    assert reads == ["wt"]  # the Inbox, the poll and the Org within `DEFS_TTL`: one reading
    # an unattended record carrying the badge takes the row and the note away
    c.app.state.answers["list"] = [_session("g", closed_at="2026-09-30T00:56:00+00:00")]
    assert "its lanes hold" not in c.get("/inbox").text and "its lanes hold" not in c.get("/").text


def test_one_teams_failed_lanes_read_costs_only_its_own_row_and_note(page, tmp_path, monkeypatch):
    """TD-799: a `teamrun.lanes` that raises for one of two teams with no record leaves the other's Later
    row and card note and both pages rendered; the failed one reads *unknown* — `lanes_hold` None."""
    c, _calls, work = page
    (tmp_path / "home" / "org.yml").write_text(
        f"projects:\n  p:\n    repos:\n      r: {{kmaster: {tmp_path}}}\n"
        "teams:\n  wx:\n    repo: r\n    manager: {role: manager, name: n}\n"
        "    members: [{role: grinder, name: h}]\n"
        "  wt:\n    repo: r\n    manager: {role: manager, name: m}\n"
        "    members: [{role: grinder, name: g}]\n"
    )
    reads: list[str] = []

    def fake(call, org, name, host):
        reads.append(name)
        if name == "wx":
            raise RuntimeError("the ledger moved")
        return lanes("TD-119", "TD-120")

    monkeypatch.setattr(teamrun, "lanes", fake)
    work.clear()
    c.app.state.answers["list"] = []
    got = c.get("/inbox")
    assert got.status_code == 200
    later = got.text.split('id="rows-later"', 1)[1].split("</section>", 1)[0]
    assert "wt · stopped · its lanes hold 2 entries:" in later and "wx · stopped" not in later
    org = c.get("/")
    assert org.status_code == 200 and org.text.count("· its lanes hold 2 entries</span>") == 1
    assert sorted(reads) == ["wt", "wx"]
    rd = uiapp.Readings(call=lambda method, **kw: _answer({}))
    rd.defs_cache.update(at=float("inf"), org=object())
    rows = asyncio.run(rd.with_lanes([{"name": "wx"}, {"name": "wt"}], []))
    assert [(r["name"], r["lanes_hold"], r["lanes_line"]) for r in rows] == [
        ("wx", None, ""),
        ("wt", 2, "grinder: 2 pickable"),
    ]


def test_a_node_reads_no_teams_lanes(monkeypatch):
    """TD-799: a node reads no definition, so `team_lanes` is `{}` and reads nothing — no RPC, no lanes."""
    from sessionorc import hosts

    reads, rpcs = [], []
    monkeypatch.setattr(teamrun, "lanes", lambda *a: reads.append(a) or lanes("TD-1"))
    monkeypatch.setattr(hosts, "is_node", lambda: True)

    def call(method, **kw):
        rpcs.append(method)
        return _answer({})

    rd = uiapp.Readings(call=call)
    assert asyncio.run(rd.team_lanes([{"name": "wt"}], [])) == {}
    rows = asyncio.run(rd.with_lanes([{"name": "wt"}], []))
    assert rows[0]["lanes_hold"] is None and reads == [] and rpcs == [] and rd.lanes_cache == {}
