"""Each page route's `Server-Timing` (design §4.5 *Page loads*, *Measured on every load*; TD-881): its RPCs by
name, the person inbox, the board and ledger reads, the render and the total; the last twenty per route kept
in memory, and no header on a route that is no page."""

from __future__ import annotations

import types

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
    assert len(timing.RECENT["/settings"]) == 20 and "total" in timing.RECENT["/settings"][-1]
    assert list(timing.RECENT) == ["/settings", "/queue?part=1"]


def test_a_page_that_answers_an_error_still_says_where_its_time_went(tmp_path, monkeypatch):
    calls: list[str] = []
    c = _client(monkeypatch, tmp_path, calls)
    r = c.get("/repo/nowhere")  # a repo this home does not know: refused, and timed
    assert r.status_code == 404 and list(_steps(r.headers["server-timing"]))[-1] == "total"
    assert set(timing.RECENT) == {"/repo/{name}"} and "rpc_repos" in timing.RECENT["/repo/{name}"][-1]


def test_a_page_route_asked_by_anything_but_a_get_is_no_load(tmp_path, monkeypatch):
    c = _client(monkeypatch, tmp_path, [])
    r = c.post("/queue")
    assert "server-timing" not in r.headers and timing.RECENT == {}


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


def test_a_nested_step_is_timed_by_the_outer_alone(monkeypatch):
    """Each clock read is a second on: the outer step reads two of them, so its one second is the figure, and
    an inner one counted too would make it four (TD-886)."""
    clock = iter(range(100))
    monkeypatch.setattr(timing, "time", types.SimpleNamespace(perf_counter=lambda: next(clock)))
    steps = timing.begin()
    with timing.step("board"), timing.step("board"):
        pass
    timing._STEPS.set(None)
    assert steps["ms"] == {"board": 1000.0}


def test_settings_reads_each_rpc_once_all_at_once_and_times_its_files(tmp_path, monkeypatch):
    """TD-884: the Settings page's RPCs wait on none of each other, so they are made at once; the top bar's
    chips take the route's own `usage`, `gate` and `host` rather than read them again; and the page's reads
    of this host's files are a step of their own (`files`), on a worker thread beside the RPCs."""
    import asyncio

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    calls: list[str] = []
    live = {"now": 0, "most": 0}

    class Slow:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append(method)
            live["now"] += 1
            live["most"] = max(live["most"], live["now"])
            await asyncio.sleep(0.02)
            live["now"] -= 1
            return {"list": [], "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setattr(ui, "LocalClient", Slow)
    monkeypatch.setattr(timing, "RECENT", {})
    c = TestClient(ui.create_app())
    c.get("/settings")  # the first load also reads the person's settings for every page (TD-174), held after
    calls.clear()
    live["most"] = 0
    r = c.get("/settings")
    assert r.status_code == 200
    # each once (an empty fleet is the one read the usage chip makes again: no session to name an account)
    assert sorted(m for m in calls if m != "list") == ["gate", "host", "repos", "settings", "usage"]
    assert live["most"] == 6  # the six the route makes, all in flight at once
    steps = _steps(r.headers["server-timing"])
    assert "files" in steps and "flows" in steps


def test_settings_refused_by_the_agent_still_draws_its_files_with_the_words(tmp_path, monkeypatch):
    """A `settings` the host agent refuses, gathered with the rest, is still its words on the page
    and the page still drawn (TD-884)."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from sessionorc.client import AgentError
    from shiftlead.ui import app as ui

    class Refuses:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "settings":
                raise AgentError("settings.yml: not a mapping")
            return {"list": [], "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setattr(ui, "LocalClient", Refuses)
    seen = []

    async def chip(call, info=None):
        seen.append(info)
        return None

    monkeypatch.setattr(ui, "chip_build", chip)
    r = TestClient(ui.create_app()).get("/settings")
    assert r.status_code == 200 and "settings.yml: not a mapping" in r.text
    assert seen == [{"name": "kmaster"}]  # the build chip still has the `host` that answered


def test_the_repo_page_reads_at_once_names_its_steps_and_reads_each_once(tmp_path, monkeypatch):
    """TD-893: the Repo page's reads that wait on none of each other are made at once, every seat's two
    inbox reads among them; the top bar's chips take the route's own `list`, `usage`, `gate` and `host`;
    the definitions are read once, for the page and its flows; and its own work is in named steps
    (`files`, `flows`, `views`, `groups`, `lists`), so nothing it waits on is in no step."""
    import asyncio

    from test_ui_repo_page import fake, reading, rec

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui
    from shiftlead.ui import common

    root = str(tmp_path / "samscrape")
    fleet = [rec(f"techlead-{n}", root, role="techlead") for n in (1, 2)]
    calls: list[str] = []
    live = {"now": 0, "most": 0, "inbox": 0, "inbox_most": 0}

    class Slow(fake({root: reading(root)}, fleet)):
        async def call(self, method, **kw):
            calls.append(method)
            seat = method == "inbox" and kw.get("id") != "person"
            live["now"] += 1
            live["inbox"] += seat
            live["most"] = max(live["most"], live["now"])
            live["inbox_most"] = max(live["inbox_most"], live["inbox"])
            await asyncio.sleep(0.02)
            live["now"] -= 1
            live["inbox"] -= seat
            return await super().call(method, **kw)

    reads = []
    real = common.org_here
    monkeypatch.setattr(ui, "org_here", lambda: reads.append(1) or real())
    monkeypatch.setattr(ui, "LocalClient", Slow)
    monkeypatch.setattr(timing, "RECENT", {})
    c = TestClient(ui.create_app())
    c.get("/repo/samscrape")  # the first load fills what is held between loads (the person inbox, the spend)
    calls.clear()
    reads.clear()
    live["most"] = 0
    r = c.get("/repo/samscrape")
    assert r.status_code == 200
    assert all(calls.count(m) == 1 for m in ("list", "host", "usage", "gate", "queue")), calls
    assert calls.count("inbox") == 4 and live["inbox_most"] == 4  # two seats, two reads each, at once
    assert live["most"] >= 5  # the fleet, the home, the cards, the chip's two: in flight together
    assert len(reads) == 1  # the definitions, once: the page's and its flows'
    steps = _steps(r.headers["server-timing"])
    assert {"files", "flows", "views", "groups", "lists", "render"} <= set(steps)


@pytest.mark.parametrize(
    ("refused", "status"), [("list", 503), ("host", 200), ("queue", 200), ("usage", 200), ("gate", 200)]
)
def test_the_repo_page_fails_and_stands_on_the_reads_it_did_before(tmp_path, monkeypatch, refused, status):
    """TD-893: gathered, the Repo page's reads keep their old weight — a refused fleet is the page's error,
    the home, the cards and the chip's reads cost only their own part, and none is read a second time."""
    from test_ui_repo_page import fake, reading

    from sessionorc.client import AgentError, AgentUnavailable

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    root = str(tmp_path / "samscrape")
    calls: list[str] = []

    class Refuses(fake({root: reading(root)}, [])):
        async def call(self, method, **kw):
            calls.append(method)
            if method == refused:
                raise AgentUnavailable("down") if refused == "list" else AgentError("no such method")
            return await super().call(method, **kw)

    monkeypatch.setattr(ui, "LocalClient", Refuses)
    c = TestClient(ui.create_app())
    calls.clear()
    r = c.get("/repo/samscrape")
    assert r.status_code == status
    if refused in ("usage", "gate"):
        assert calls.count(refused) == 1  # a refused read is not made again by the chip
    calls.clear()
    assert c.get("/repo/samscrape?part=1").status_code == status
    assert "usage" not in calls and "gate" not in calls  # the part has no top bar


def test_settings_with_the_agent_down_draws_the_banner_and_reads_no_chip(tmp_path, monkeypatch):
    """A `settings` read the host agent cannot answer (a 503) is the page's *host agent unreachable* banner,
    and the top bar's chips are not read, gathered as the reads are (TD-884, TD-895)."""
    from sessionorc.client import AgentUnavailable

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    class Down:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "settings":
                raise AgentUnavailable("no socket")
            return {"list": [], "host": {"name": "kmaster"}}.get(method, {})

    chips: list[str] = []

    async def build(call, info=None):
        chips.append("build")

    async def usage(call, *a, **k):
        chips.append("usage")
        return {}

    monkeypatch.setattr(ui, "LocalClient", Down)
    monkeypatch.setattr(ui, "chip_build", build)
    monkeypatch.setattr(ui, "chip_usage", usage)
    r = TestClient(ui.create_app()).get("/settings")
    assert r.status_code == 200
    assert '<div class="warn" id="agentdown">' in r.text  # drawn, not hidden
    assert chips == []


def test_settings_reads_its_files_off_the_loops_thread(tmp_path, monkeypatch):
    """The Settings page's file reads (`settings_files`: the profiles, the org, `hosts.yml`) run on a worker
    thread, so a YAML load does not hold the loop the page's RPCs answer on (TD-884, TD-895)."""
    import threading

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    where: dict[str, int] = {}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            where["loop"] = threading.get_ident()
            return {"list": [], "host": {"name": "kmaster"}}.get(method, {})

    load = ui.profiles_mod.load

    def recorded():
        where["files"] = threading.get_ident()
        return load()

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(ui.profiles_mod, "load", recorded)
    assert TestClient(ui.create_app()).get("/settings").status_code == 200
    assert {"loop", "files"} <= set(where) and where["files"] != where["loop"]
