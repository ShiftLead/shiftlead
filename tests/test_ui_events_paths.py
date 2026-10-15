"""TD-575 (TD-572's other paths, §4.5a *team groups*, §4.6): what the events stream sends for an event
that is not a session delta, and the two guards on its groups. A `gone` carries the groups on the full
stream, even when they equal the last reading, and nothing but itself on a light one; a `doing` or a
`repos` event marks the groups for the flush; a reading equal to the last one sent is not sent again;
a flush whose reading failed tries again on its next turn."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from test_ui_events_light import received
from test_ui_waiting_wiring import NOW, member
from test_ui_waiting_wiring import reading as fresh

# the repo reading three days old: its ages (*read 3d ago*) do not move while a test runs, so a
# reading the stream takes twice is the same reading
OLD = (datetime.now(UTC) - timedelta(days=3)).isoformat().replace("+00:00", "Z")


def reading(root: str) -> dict:
    r = fresh(root)
    return {**r, "at": OLD, "prs": {"open": [{**r["prs"]["open"][0], "created": OLD}]}}


pytestmark = pytest.mark.unit


def client(monkeypatch, tmp_path, pushed, *, wait=1.6, doing_log=None):
    """g1 holds TD-301, g2 works; `subscribe` yields `pushed(g1, g2)` and stays open `wait` seconds:
    one `HEADS_EVERY` and some, the flush's turn."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = str(tmp_path / "samscrape")
    claim = [{"ref": "TD-301", "status": "claimed", "at": NOW, "pr": 811}]
    g1, g2 = member("g1", root, progress=claim, tail=["a"]), member("g2", root, state="working")
    replies = {"repos": {root: reading(root)}, "doing_log": doing_log or {}, "list": [g1, g2], "usage": {}, "host": {}}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": []}
            return replies.get(method, {})

        async def subscribe(self):
            for ev in pushed(g1, g2):
                yield ev
            await asyncio.sleep(wait)

    from fastapi.testclient import TestClient

    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def first_then(*evs):
    """g1's tail moves first — the stream's first delta, which carries the groups — then `evs`."""
    return lambda g1, g2: [{"event": "session", "session": {**g1, "tail": ["b"]}}, *evs]


def test_a_gone_carries_the_groups_on_the_full_stream_even_unchanged_and_nothing_on_a_light_one(tmp_path, monkeypatch):
    """A record nobody knew went: the groups read the same, and still ride on the `gone` (`always`),
    so the page drops the card from its team count; a light page gets the `gone` alone."""
    pushed = first_then({"event": "gone", "id": "ghost"})
    evs = received(client(monkeypatch, tmp_path, pushed, wait=0), "/events")
    (went,) = [e for e in evs if e["event"] == "gone"]
    assert went["id"] == "ghost" and went["groups"] == evs[0]["groups"] and "rollup" in went
    light = received(client(monkeypatch, tmp_path, pushed, wait=0), "/events?light=1")
    assert [e for e in light if e["event"] == "gone"] == [{"event": "gone", "id": "ghost"}]


def test_a_doing_line_is_passed_through_and_marks_the_groups_for_the_flush(tmp_path, monkeypatch):
    """A member said what it is doing: the team card's summary moves, so one `groups` follows it."""
    entry = {"at": NOW, "id": "g1", "name": "g1", "text": "TD-301: reading the fetcher"}
    pushed = first_then({"event": "doing", "team": "grind", "entry": entry})
    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    assert [e["event"] for e in evs] == ["session", "doing", "groups"]
    assert evs[1]["entry"] == entry and evs[2]["groups"] != evs[0]["groups"]


def test_the_pages_doing_ring_keeps_what_the_host_agents_keeps(tmp_path, monkeypatch):
    """TD-705 (§4.8 *the doing log*): the stream's copy of a team's ring takes a `doing` event by the
    host agent's own rule, `kept` — the last fifty and each doer's newest five — so a seldom doer's
    lines, past the fifty, are still on the team card after a busy member's next call."""
    from sessionorc.store import kept

    now = datetime.now(UTC)

    def at(minutes: int) -> str:
        return (now - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

    seldom = [{"team": "grind", "id": "g1", "text": f"audit {i}", "at": at(300 - i)} for i in range(6)]
    busy = [{"team": "grind", "id": "g2", "text": f"busy {i}", "at": at(200 - i)} for i in range(50)]
    entry = {"team": "grind", "id": "g2", "text": "busy 50", "at": at(0)}
    pushed = first_then({"event": "doing", "team": "grind", "entry": entry})
    evs = received(client(monkeypatch, tmp_path, pushed, doing_log={"grind": seldom + busy}), "/events")
    want = kept(seldom + busy + [entry], now)
    assert [e["text"] for e in want if e["id"] == "g1"] == [f"audit {i}" for i in range(1, 6)], "the newest five"
    (grind,) = [g for g in evs[-1]["groups"] if g["team"] == "grind"]
    drawn = list(dict.fromkeys(re.findall(r"(?:busy|audit) \d+", grind["summary"])))  # a row's words and title
    assert drawn == [e["text"] for e in reversed(want)], "newest first, the page's ring the store's"


def test_a_repos_reading_is_passed_through_and_marks_the_groups_for_the_flush(tmp_path, monkeypatch):
    """A checkout's repo facts changed: kept, passed through as sent, and the groups re-read."""

    def pushed(g1, g2):
        root = g1["repo"]
        merged = {**reading(root), "prs": {"open": []}}  # PR #811 merged: the claim's chip moves
        return first_then({"event": "repos", "root": root, "repo": merged})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    assert [e["event"] for e in evs] == ["session", "repos", "groups"]
    assert evs[2]["groups"] != evs[0]["groups"]
    assert "pr_marks" not in evs[0]["session"]  # no session view carries them (TD-617)


def test_a_repos_push_carries_the_repos_pr_marks_once_for_every_stream(tmp_path, monkeypatch):
    """§4.4 *Per-session views* (TD-617 fix 2): a PR's marks are the repo's — the `repos` push carries
    the repo's map, computed once, to a full stream and a light one alike."""
    from shiftlead.ui import app as ui

    real, calls = ui.repo_pr_marks, []
    monkeypatch.setattr(ui, "repo_pr_marks", lambda root, r: calls.append(root) or real(root, r))

    def pushed(g1, g2):
        root = g1["repo"]
        merged = {**reading(root), "prs": {"open": [], "recent": [{"number": 811, "state": "merged"}]}}
        return first_then({"event": "repos", "root": root, "repo": merged})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    (rep,) = [e for e in evs if e["event"] == "repos"]
    assert rep["pr_marks"] == {"811": "merged"} and calls == [rep["root"]]  # once for the push
    light = received(client(monkeypatch, tmp_path, pushed), "/events?light=1")
    assert [e["pr_marks"] for e in light if e["event"] == "repos"] == [{"811": "merged"}]


def test_a_light_stream_takes_a_repos_marks_alone(tmp_path, monkeypatch):
    """TD-670: a light stream (Focus, the Inbox) is sent a repo's root and PR marks, never its facts —
    which run to most of a megabyte a push — on every push, which the Inbox re-reads on; a dropped
    repo is `pr_marks: null`. The full stream still takes every push whole."""

    def pushed(g1, g2):
        root = g1["repo"]
        merged = {**reading(root), "prs": {"open": [], "recent": [{"number": 811, "state": "merged"}]}}
        again = {**merged, "ledger": {"moved": True}}  # the facts moved, the marks did not
        return first_then(
            {"event": "repos", "root": root, "repo": merged},
            {"event": "repos", "root": root, "repo": again},
            {"event": "repos", "root": root, "repo": None},
        )(g1, g2)

    light = [e for e in received(client(monkeypatch, tmp_path, pushed), "/events?light=1") if e["event"] == "repos"]
    root = str(tmp_path / "samscrape")
    assert light == [
        {"event": "repos", "root": root, "pr_marks": {"811": "merged"}},
        {"event": "repos", "root": root, "pr_marks": {"811": "merged"}},
        {"event": "repos", "root": root, "pr_marks": None},
    ]
    full = [e for e in received(client(monkeypatch, tmp_path, pushed), "/events") if e["event"] == "repos"]
    assert [bool(e["repo"]) for e in full] == [True, True, False] and full[1]["repo"]["ledger"] == {"moved": True}


def test_the_groups_are_built_off_the_loop(tmp_path, monkeypatch):
    """TD-670: a regroup's views of every record and its rendered headers are built on a worker thread
    — up to ~300 ms a regroup on the live home — never on the loop every Focus terminal shares."""
    import asyncio

    from shiftlead.ui import app as ui

    on_loop, real = [], ui.team_groups

    def spy(*a, **k):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real(*a, **k)

    monkeypatch.setattr(ui, "team_groups", spy)
    evs = received(client(monkeypatch, tmp_path, first_then()), "/events")
    assert evs[0]["groups"] and on_loop and not any(on_loop)


def test_a_reading_equal_to_the_last_one_sent_is_not_sent_again(tmp_path, monkeypatch):
    """g1's tail moves twice: the second marks the groups, the flush reads them, and they are the
    same as the first delta's — so nothing is sent."""
    from shiftlead.ui import app as ui

    real, calls = ui.render_heads, []
    monkeypatch.setattr(ui, "render_heads", lambda groups: calls.append(1) or real(groups))

    def pushed(g1, g2):
        return first_then({"event": "session", "session": {**g1, "tail": ["c"]}})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    assert len(calls) == 2  # the first delta's reading and the flush's: the flush did read
    assert [e["event"] for e in evs] == ["session", "session"]


def test_a_flush_whose_reading_failed_tries_again_on_its_next_turn(tmp_path, monkeypatch):
    """g1 drops its claim (the groups wait for the flush); the flush's first reading fails, and the
    next turn, `HEADS_EVERY` later, sends it."""
    from shiftlead.ui import app as ui

    real, calls = ui.render_heads, []

    def flaky(groups):
        calls.append(1)
        if len(calls) == 2:  # the first delta's reading is the first call; the flush's is the second
            raise RuntimeError("the agent did not answer")
        return real(groups)

    monkeypatch.setattr(ui, "render_heads", flaky)

    def pushed(g1, g2):
        return first_then({"event": "session", "session": {**g1, "tail": ["b"], "progress": []}})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed, wait=2.8), "/events")
    assert len(calls) == 3
    assert [e["event"] for e in evs] == ["session", "session", "groups"]


def test_focus_loads_its_repos_pr_marks_and_the_view_carries_none(tmp_path, monkeypatch):
    """§4.4 *Per-session views* (TD-617 fix 2): the Focus page's first load carries its repo's PR marks
    for the Reports panel, keyed as the view's `pr_repo` names the repo; the view carries no marks."""
    from shiftlead.ui import app as ui

    c = client(monkeypatch, tmp_path, lambda g1, g2: [], wait=0)
    root = str(tmp_path / "samscrape")
    g1 = {**member("g1", root, progress=[{"ref": "TD-301", "status": "done", "at": NOW, "pr": 811}]), "created": NOW}
    merged = {**reading(root), "prs": {"open": [], "recent": [{"number": 811, "state": "merged"}]}}
    real = ui.LocalClient.call

    async def call(self, method, **kw):
        return {"seen": g1, "get": g1, "list": [g1], "repos": {root: merged}}.get(method) or await real(
            self, method, **kw
        )

    monkeypatch.setattr(ui.LocalClient, "call", call)
    html = c.get("/focus/g1").text
    card = html[html.index('id="reportscard"') :]
    marks = json.loads(card[card.index("data-pr-marks='") + len("data-pr-marks='") :].split("'", 1)[0])
    assert marks == {root: {"811": "merged"}}
    focus = html[html.index("<script>AO.focus(") + len("<script>AO.focus(") :]
    s = json.loads(focus[: focus.index("</script>")].rsplit(", ", 1)[0])
    assert "pr_marks" not in s and s["pr_repo"] == root and s["report"].startswith("TD-301 → #811 merged")
