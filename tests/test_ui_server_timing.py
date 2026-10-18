"""Each page route's `Server-Timing` (design §4.5 *Page loads*, *Measured on every load*; TD-881): its RPCs by
name, the person inbox, the board and ledger reads, the render and the total; the last twenty per route kept
in memory, and no header on a route that is no page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shiftlead.ui import timing

pytestmark = pytest.mark.unit


def _client(monkeypatch, tmp_path, calls: list[str]) -> TestClient:
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append(method)
            return {"list": [], "inbox": {"entries": []}, "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(timing, "RECENT", {})
    return TestClient(ui.create_app())


def _steps(header: str) -> dict[str, float]:
    out = {}
    for part in header.split(", "):
        name, _, dur = part.partition(";dur=")
        out[name] = float(dur)
    return out


@pytest.mark.parametrize("route", ["/", "/inbox", "/queue", "/settings", "/spend"])
def test_a_page_names_each_rpc_it_made_and_its_total(tmp_path, monkeypatch, route):
    calls: list[str] = []
    r = _client(monkeypatch, tmp_path, calls).get(route)
    assert r.status_code == 200
    steps = _steps(r.headers["server-timing"])
    assert list(steps)[-1] == "total" and "render" in steps
    assert {f"rpc_{m}" for m in calls} == {n for n in steps if n.startswith("rpc_")}
    assert all(steps["total"] >= ms for ms in steps.values())
    if route in ("/inbox", "/queue"):
        assert {"inbox", "board", "ledger"} <= set(steps)  # the person inbox, the board and ledger reads


def test_the_last_twenty_are_kept_per_route_and_a_fragment_apart(tmp_path, monkeypatch):
    c = _client(monkeypatch, tmp_path, [])
    for _ in range(timing.KEPT + 3):
        c.get("/settings")
    c.get("/queue?part=1")
    assert len(timing.RECENT["/settings"]) == timing.KEPT and "total" in timing.RECENT["/settings"][-1]
    assert list(timing.RECENT) == ["/settings", "/queue?part=1"]


def test_a_page_that_answers_an_error_still_says_where_its_time_went(tmp_path, monkeypatch):
    calls: list[str] = []
    c = _client(monkeypatch, tmp_path, calls)
    r = c.get("/repo/nowhere")  # a repo this home does not know: refused, and timed
    assert r.status_code == 404 and list(_steps(r.headers["server-timing"]))[-1] == "total"
    assert set(timing.RECENT) == {"/repo/{name}"} and "rpc_repos" in timing.RECENT["/repo/{name}"][-1]


def test_a_route_that_is_no_page_carries_none(tmp_path, monkeypatch):
    c = _client(monkeypatch, tmp_path, [])
    assert "server-timing" not in c.get("/api/person/inbox").headers
    assert "server-timing" not in c.get("/static/app.css").headers
    assert timing.route_key("/repo/shiftlead") == "/repo/{name}" and timing.route_key("/repo/x/shot/1") is None
    assert timing.route_key("/transcript/ao-x") == "/transcript/{sid}" and timing.route_key("/focus/ao-x") is None


def test_a_step_outside_a_page_request_adds_to_nothing_and_a_nested_one_counts_once():
    with timing.step("board"):  # the counts keeper's read: no request's figures
        pass
    steps = timing.begin()
    with timing.step("inbox"), timing.step("inbox"):
        pass
    with timing.step("rpc_x", nests=False), timing.step("rpc_x", nests=False):
        pass
    timing._STEPS.set(None)  # this test's own figures end with it
    assert set(steps["ms"]) == {"inbox", "rpc_x"} and not steps["open"]
