"""`ao connect` and `ao doctor`'s **route** line (design §4.7, §4.5b, TD-648): each check's *lacking* line
against a faked `tailscale`, each port's state read by asking it, the write–serve–probe order and its
undo, and `off` turning off only its own handler."""

from __future__ import annotations

import json

import pytest

from shiftlead import connect

pytestmark = pytest.mark.unit

DNS = "home.tail1234.ts.net"
STATUS = {
    "BackendState": "Running",
    "CertDomains": [DNS],
    "Self": {"DNSName": DNS + ".", "UserID": 7, "Tags": None},
    "User": {"7": {"LoginName": "paul@example.com"}},
}


def _serve(target: str | None = None, funnel: bool = False) -> dict:
    out: dict = {}
    if target:
        out = {"TCP": {"443": {"HTTPS": True}}, "Web": {f"{DNS}:443": {"Handlers": {"/": {"Proxy": target}}}}}
    if funnel:
        out["AllowFunnel"] = {f"{DNS}:443": True}
    return out


class Tailscale:
    """A faked `tailscale`: `status` and `serve status` from the given readings, every command recorded."""

    def __init__(self, status=None, serve=None, serve_err: str = ""):
        self.status = STATUS if status is None else status
        self.serve = {} if serve is None else serve
        self.serve_err = serve_err
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        if argv[:3] == ["tailscale", "status", "--json"]:
            return (0, json.dumps(self.status), "") if self.status != "down" else (1, "", "not logged in")
        if argv[:4] == ["tailscale", "serve", "status", "--json"]:
            return (1, "", self.serve_err) if self.serve_err else (0, json.dumps(self.serve), "")
        if argv[:2] == ["tailscale", "serve"]:
            if "--bg" in argv:
                self.serve = _serve(argv[-1])
            elif argv[-1] == "off":
                self.serve = {}
            return 0, "", ""
        if argv[0] == "ss":
            return 0, 'LISTEN 0 5 127.0.0.1:8766 0.0.0.0:* users:(("python3",pid=4121,fd=3))\n', ""
        return 127, "", "unknown"

    def ran(self, *head: str) -> list[list[str]]:
        return [c for c in self.calls if c[: len(head)] == list(head)]


def _ask(plain="ui", route="ui", route_listener="route", refused="3 2026-10-14T09:12:00Z"):
    def ask(port: int) -> dict:
        state, listener = (plain, "plain") if port == 8765 else (route, route_listener)
        return {
            "port": port,
            "state": state,
            "status": None if state == "down" else 200,
            "listener": listener if state == "ui" else None,
            "refused": refused if state == "ui" else None,
        }

    return ask


def _check(ts, allow=(), linux=True):
    return connect.tailscale(list(allow), 8766, 8765, ts, linux=linux, which=lambda _: "/usr/bin/tailscale")


@pytest.mark.parametrize(
    "ts, says",
    [
        (Tailscale(status="down"), "not logged in: run `tailscale up`"),
        (Tailscale(serve_err="access denied"), "sudo tailscale set --operator=$USER"),
        (Tailscale(status={**STATUS, "CertDomains": None}), "HTTPS is off for the tailnet"),
        (Tailscale(status={**STATUS, "Self": {**STATUS["Self"], "Tags": ["tag:server"]}}), "tagged: name your login"),
        (Tailscale(serve=_serve("http://127.0.0.1:3000")), "already served (http://127.0.0.1:3000)"),
        (Tailscale(serve=_serve("http://127.0.0.1:8765")), "`tailscale serve --https=443 off` first"),
        (Tailscale(serve=_serve(funnel=True)), "Funnel would put the UI on the internet"),
    ],
)
def test_each_check_names_the_step_it_cannot_take(ts, says):
    with pytest.raises(connect.Lacking, match=__import__("re").escape(says)):
        _check(ts)
    assert not ts.ran("tailscale", "serve", "--bg")  # nothing is set up past a lack


def test_not_installed_names_the_install_page():
    with pytest.raises(connect.Lacking, match="tailscale.com/download"):
        connect.tailscale([], 8766, 8765, Tailscale(), which=lambda _: None)


def test_the_owner_is_allowed_unless_allow_names_others_and_a_tagged_home_takes_allow():
    assert _check(Tailscale()) == {"url": f"https://{DNS}", "allow": ["paul@example.com"], "ours": False}
    assert _check(Tailscale(), allow=["me@x.org"])["allow"] == ["me@x.org"]
    tagged = Tailscale(status={**STATUS, "Self": {**STATUS["Self"], "Tags": ["tag:server"]}})
    assert _check(tagged, allow=["me@x.org"])["allow"] == ["me@x.org"]
    assert _check(Tailscale(serve=_serve("http://127.0.0.1:8766")))["ours"] is True  # already this route's


def test_each_port_is_read_by_asking_it():
    with pytest.raises(connect.Lacking, match=r"the UI is not running \(`ao service install`\)"):
        connect.ports(8765, 8766, _ask(plain="down"), Tailscale())
    with pytest.raises(connect.Lacking, match="port 8766 not bound: held by pid 4121 \\(python3\\)"):
        connect.ports(8765, 8766, _ask(route="other"), Tailscale())
    with pytest.raises(connect.Lacking, match="port 8766 not bound: the UI runs no route listener"):
        connect.ports(8765, 8766, _ask(route="down"), Tailscale())
    assert connect.ports(8765, 8766, _ask(), Tailscale())["route"]["listener"] == "route"


class Reach:
    def __init__(self, before=None):
        self.held, self.writes = before, []

    def __call__(self, reach):
        before, self.held = self.held, reach
        self.writes.append(reach)
        return {"reach": reach, "before": before}


def test_connect_writes_then_serves_then_probes():
    ts, reach, said = Tailscale(), Reach(), []
    got = connect.connect_tailscale(
        [],
        8766,
        8765,
        reach,
        run=ts,
        ask=_ask(),
        fetch=lambda u: {"status": 200, "listener": "route"},
        sleep=lambda s: None,
        say=said.append,
        which=lambda _: "x",
    )
    assert got["url"] == f"https://{DNS}" and got["added"] is True
    assert reach.held == {"route": "tailscale", "url": f"https://{DNS}", "allow": ["paul@example.com"]}
    assert ts.ran("tailscale", "serve", "--bg") == [
        ["tailscale", "serve", "--bg", "--https=443", "http://127.0.0.1:8766"]
    ]


def test_a_failed_probe_restores_the_setting_and_turns_off_only_what_it_added():
    before = {"route": "tailscale", "url": "https://old.ts.net", "allow": ["p@x.org"]}
    for status, listener, says in (
        (200, "plain", "the plain port"),
        (421, "route", "rewrote Host"),
        (None, None, "did not answer"),
    ):
        ts, reach = Tailscale(), Reach(before)
        with pytest.raises(connect.Lacking, match=says):
            connect.connect_tailscale(
                [],
                8766,
                8765,
                reach,
                run=ts,
                ask=_ask(),
                fetch=lambda u, s=status, li=listener: {"status": s, "listener": li},
                sleep=lambda s: None,
                say=lambda line: None,
                which=lambda _: "x",
            )
        assert reach.held == before and ts.ran("tailscale", "serve", "--https=443", "off")
    # a handler already this route's is not this run's: a failed probe leaves it
    ts, reach = Tailscale(serve=_serve("http://127.0.0.1:8766")), Reach()
    with pytest.raises(connect.Lacking, match="the setting restored$"):
        connect.connect_tailscale(
            [],
            8766,
            8765,
            reach,
            run=ts,
            ask=_ask(),
            fetch=lambda u: {"status": 403, "listener": "plain"},
            sleep=lambda s: None,
            say=lambda line: None,
            which=lambda _: "x",
        )
    assert reach.held is None and not ts.ran("tailscale", "serve", "--https=443", "off")


def test_off_removes_the_setting_and_only_its_own_serve():
    tailscale = {"route": "tailscale", "url": f"https://{DNS}", "allow": ["p@x.org"]}
    ts, reach = Tailscale(serve=_serve("http://127.0.0.1:8766")), Reach(tailscale)
    done = connect.off(tailscale, 8766, reach, run=ts)
    assert reach.held is None and ts.ran("tailscale", "serve", "--https=443", "off") and len(done) == 2
    ts, reach = Tailscale(serve=_serve("http://127.0.0.1:3000")), Reach(tailscale)  # another serve: left
    connect.off(tailscale, 8766, reach, run=ts)
    assert reach.held is None and not ts.ran("tailscale", "serve", "--https=443", "off")
    assert not any("reset" in c for call in ts.calls for c in call)


def test_the_doctors_route_line():
    tailscale = {"route": "tailscale", "url": f"https://{DNS}", "allow": ["paul@example.com"]}
    ours = Tailscale(serve=_serve("http://127.0.0.1:8766"))
    (row,) = connect.route_line(tailscale, ask=_ask(), run=ours)
    assert row["verdict"] == "ok" and row["text"].startswith(
        f"route — tailscale, https://{DNS}, allows paul@example.com"
    )
    assert " · 3 refused since " in row["text"]
    (row,) = connect.route_line(None, ask=_ask(refused="0 2026-10-14T09:12:00Z"), run=ours)
    assert row["verdict"] == "warning" and row["text"] == (
        "route — none set; the UI is reached over `ssh -L` (`ao connect tailscale`)"
    )
    (row,) = connect.route_line(tailscale, ask=_ask(), run=Tailscale())
    assert row["verdict"] == "lacking" and "no longer points at the route port" in row["text"]
    (row,) = connect.route_line(tailscale, ask=_ask(route="other"), run=ours)
    assert row["verdict"] == "lacking" and "port 8766 not bound: held by pid 4121 (python3)" in row["text"]
    (row,) = connect.route_line(tailscale, ask=_ask(plain="down"), run=ours)
    assert row["text"] == "route — the UI is not running (`ao service install`)"
    (row,) = connect.route_line(tailscale, node=True)
    assert row["verdict"] == "home only"


def test_a_probe_reads_the_listener_mark():
    assert connect.probe("https://h", lambda u: {"status": 403, "listener": "route"}) is None  # marked: reached
    assert "plain port" in connect.probe("https://h", lambda u: {"status": 403, "listener": "plain"})
    assert "not the UI" in connect.probe("https://h", lambda u: {"status": 200, "listener": None})
