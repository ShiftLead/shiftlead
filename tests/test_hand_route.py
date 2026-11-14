"""TD-1660 slice 2 (TD-1543's design), §4.5 screen 12 *Three verbs: Have a session do it*: the page's `hand` route —
the look by key, `board_find`, the doer resolved by the function the draw reads, `entry_add` with the relay text,
`refs`, `key` and `doer`, and the Done naming the ask; TD-1624's press where anything refuses before the send; every
end state's words."""

from __future__ import annotations

import subprocess

import pytest
import yaml

from sessionorc.client import AgentError, AgentUnavailable
from shiftlead.ui import app as ui

pytestmark = pytest.mark.unit

KEY = "board:0123abcd"
ACT = (
    "act 2026-11-14 (session `designer-ao-1` on kmaster) — **Bump the pin.** Context: TD-7, other#TD-9, PR #12. "
    "Doer: other. Due: 2026-11-16."
)
FOUND = {
    "doer": "other",
    "text": "**Bump the pin.**",
    "context": "the pin is two weeks old",
    "session": "designer-ao-1",
    "due": "2026-11-16",
    "context_refs": ["TD-7", "other#TD-9", "PR #12"],
    "refs": ["TD-7", "other#TD-9"],
    "key": KEY,
}


def world(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    roots = {}
    for name in ("samscrape", "other", "loose"):
        r = tmp_path / name
        r.mkdir()
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        roots[name] = r
    roster = tmp_path / "repos.txt"
    roster.write_text("".join(f"{r}\n" for r in roots.values()))
    (home / "hosts.yml").write_text(f"local:\n  name: kmaster\n  local: true\n  repos_registry: {roster}\n")
    doc = {
        "projects": {
            "p": {"repos": {n: {"kmaster": str(r)} for n, r in roots.items()} | {"gone": {"kmaster": "/nowhere"}}}
        },
        "teams": {
            "sam-grind": {"repo": "samscrape", "manager": {"name": "m-sam"}, "techlead": {"name": "tl-sam"},
                          "members": [{"role": "grinder", "lane": "free-pick"}]},
            "oth": {"repo": "other", "manager": {"name": "m-oth"}, "techlead": {"name": "tl-oth"},
                    "members": [{"role": "grinder"}]},
            "bare": {"repo": "other", "manager": {"name": "m-bare"},
                     "members": [{"role": "grinder", "name": "g-bare"}]},
        },
    }  # fmt: skip
    (home / "org.yml").write_text(yaml.safe_dump(doc))
    return roots


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    return world(tmp_path)


def test_the_doer_resolves_to_a_seat_the_boards_own_repo_or_nothing(roots):
    org, _ = ui.org_here()
    board = str(roots["samscrape"].resolve())
    got = ui.doer_target(org, board, "other", "kmaster")
    assert got["root"] == str(roots["other"].resolve()) and got["team"] == "" and got["teams"][0]["team"] == "oth"
    got = ui.doer_target(org, board, "team oth", "kmaster")
    assert got["team"] == "oth" and got["teams"][0]["team"] == "oth"
    assert ui.doer_target(org, board, "team bare", "kmaster") is None  # a team with no techlead seat
    assert ui.doer_target(org, board, "loose", "kmaster") is None  # no team services it
    assert ui.doer_target(org, board, "gone", "kmaster") is None  # no registered root
    assert ui.doer_target(org, board, "nope", "kmaster") is None and ui.doer_target(org, board, "team x", "h") is None
    assert ui.doer_target(org, board, "samscrape", "kmaster") == {"own": True}
    assert ui.doer_target(org, board, "team sam-grind", "kmaster") == {"own": True}
    assert ui.doer_target(org, board, "", "kmaster") is None


class Script:
    """The host agent as the route sees it: each method answers the next of its scripted replies, a reply being
    `(result or exception, ignored)`; every call recorded."""

    def __init__(self, **replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls: list[tuple[str, dict]] = []

    def client(self):
        script = self

        class Fake:
            def __init__(self, *a, **k):
                self.ignored: list[str] = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def call(self, method, **kw):
                script.calls.append((method, kw))
                self.ignored = []
                queue = script.replies.get(method) or []
                got, ignored = queue.pop(0) if queue else ({}, [])
                self.ignored = list(ignored)
                if isinstance(got, Exception):
                    raise got
                return got

        return Fake

    def of(self, method):
        return [kw for m, kw in self.calls if m == method]


def press(roots, monkeypatch, script):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(ui, "LocalClient", script.client())
    c = TestClient(ui.create_app())
    body = {"action": "hand", "board": str(roots["samscrape"] / "docs/user_attention.md"), "line": 9, "text": ACT,
            "key": KEY}  # fmt: skip
    return c.post("/api/person/board", json={**body, "action": "hand"})


NONE = ({"existing": False}, [])
SENT = ({"id": "m-1", "to": "tl-oth", "team": "oth", "doer": "other"}, [])


def test_a_press_hands_the_line_to_the_doers_seat_and_closes_it_naming_the_ask(roots, monkeypatch):
    s = Script(entry_add=[NONE, SENT], board_find=[(FOUND, [])], board_edit=[({"line": 9}, [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 200 and got.json()["end"] == "taken" and got.json()["toast"] == "handed to other"
    look, send = s.of("entry_add")
    assert look == {"key": f"samscrape:{KEY}", "find_only": True}
    assert send["repo"] == str(roots["other"].resolve()) and send["type"] == "debt" and send["team"] == ""
    assert send["teams"][0] == {"team": "oth", "seat": send["teams"][0]["seat"]} and send["teams"][0]["seat"]
    assert send["refs"] == ["samscrape#TD-7", "other#TD-9"] and send["key"] == f"samscrape:{KEY}"
    assert send["doer"] == "other"
    first, rest = send["text"].split("\n", 1)
    assert first == (
        f"Relayed from samscrape's board ({KEY}): session designer-ao-1 wrote it and the person pressed Have a session"
        " do it; context: TD-7, other#TD-9, PR #12; due 2026-11-16"
    )
    assert rest == "**Bump the pin.**\n\nthe pin is two weeks old"
    (done,) = s.of("board_edit")
    assert done["action"] == "done" and done["why"] == "handed to other: m-1" and done["key"] == KEY


def test_a_team_doer_passes_the_team_and_its_repo(roots, monkeypatch):
    s = Script(entry_add=[NONE, SENT], board_find=[({**FOUND, "doer": "team oth"}, [])], board_edit=[({}, [])])
    assert press(roots, monkeypatch, s).json()["toast"] == "handed to team oth"
    send = s.of("entry_add")[1]
    assert send["team"] == "oth" and send["repo"] == str(roots["other"].resolve()) and send["doer"] == "team oth"


def test_a_refusal_before_the_send_makes_the_decide_and_with_no_lane_a_409(roots, monkeypatch):
    # an unresolved doer: TD-1624's press, the refusal in the toast
    s = Script(entry_add=[NONE], board_find=[({**FOUND, "doer": "loose"}, [])], board_edit=[({"line": 9}, [])])
    got = press(roots, monkeypatch, s)
    assert got.json()["end"] == "fallback" and "loose does not resolve" in got.json()["toast"]
    (decide,) = s.of("board_edit")
    assert decide["action"] == "decide" and decide["answer"] == "have a session do it" and decide["answers"] == []
    assert len(s.of("entry_add")) == 1  # the look alone: nothing sent
    # board_find's refusal, and the send's own refusal with no ask found after it
    s = Script(entry_add=[NONE], board_find=[(AgentError("this line names no Doer"), [])], board_edit=[({}, [])])
    assert "names no Doer" in press(roots, monkeypatch, s).json()["toast"]
    s = Script(entry_add=[NONE, (AgentError("too many asks"), []), NONE], board_find=[(FOUND, [])],
               board_edit=[({}, [])])  # fmt: skip
    got = press(roots, monkeypatch, s)
    assert got.json()["end"] == "fallback" and "too many asks" in got.json()["toast"]
    # the board's own repo: TD-1624's press, no words of its own
    s = Script(entry_add=[NONE], board_find=[({**FOUND, "doer": "samscrape"}, [])], board_edit=[({}, [])])
    assert press(roots, monkeypatch, s).json()["toast"] == "sent to samscrape's lane"
    # no lane either: a 409 that writes nothing
    monkeypatch.setattr(ui, "road_refusal", lambda *a: "no lane of samscrape takes a work order")
    s = Script(entry_add=[NONE], board_find=[({**FOUND, "doer": "loose"}, [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 409 and "does not resolve" in got.json()["detail"] and "no lane" in got.json()["detail"]
    assert s.of("board_edit") == []


def test_a_found_ask_only_retries_the_done_and_a_closed_line_is_taken(roots, monkeypatch):
    had = ({"id": "m-0", "to": "tl-oth", "team": "oth", "doer": "other", "existing": True}, [])
    s = Script(entry_add=[had], board_edit=[(AgentError(f"no line {KEY} on the board — reworded or closed"), [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 200 and got.json()["end"] == "taken" and got.json()["id"] == "m-0"
    assert s.of("board_find") == [] and len(s.of("entry_add")) == 1
    assert s.of("board_edit")[0]["why"] == "handed to other: m-0"
    # a fresh send whose Done meets a closed line is taken too
    s = Script(entry_add=[NONE, SENT], board_find=[(FOUND, [])],
               board_edit=[(AgentError(f"no line {KEY} on the board — reworded or closed"), [])])  # fmt: skip
    assert press(roots, monkeypatch, s).json()["end"] == "taken"


def test_a_done_refused_or_lost_after_the_send_leaves_the_line_open_and_says_so(roots, monkeypatch):
    s = Script(entry_add=[NONE, SENT], board_find=[(FOUND, [])], board_edit=[(AgentError("the merge failed"), [])])
    got = press(roots, monkeypatch, s)
    assert (
        got.status_code == 409 and got.json()["detail"] == "handed to other — the line is still open: the merge failed"
    )
    s = Script(entry_add=[NONE, (AgentUnavailable("timed out"), [])], board_find=[(FOUND, [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 503 and got.json()["detail"].startswith("the hand-off may have been sent:")
    assert s.of("board_edit") == []
    # a refused send whose ask is found by the look after it: it may have gone, no fallback
    s = Script(entry_add=[NONE, (AgentError("bad params"), []), had_ask()], board_find=[(FOUND, [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 409 and got.json()["detail"] == "the hand-off may have been sent: bad params"
    assert s.of("board_edit") == []


def had_ask():
    return ({"id": "m-0", "to": "tl-oth", "doer": "other", "existing": True}, [])


def test_a_failed_look_stops_the_press_and_an_older_agent_says_so(roots, monkeypatch):
    s = Script(entry_add=[(AgentError("no registered repo is ''"), ["find_only", "key"])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 400 and got.json()["detail"] == (
        "could not check whether this was handed: the host agent is older than this page (it does not know "
        "find_only): promote it"
    )
    assert [m for m, _ in s.calls if m != "settings"] == ["entry_add"]
    s = Script(entry_add=[(AgentUnavailable("down"), [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 503 and got.json()["detail"].startswith("could not check whether this was handed:")
    assert "older" not in got.json()["detail"]


def test_a_keyless_send_is_taken_red_and_its_failed_done_says_a_second_press_sends_again(roots, monkeypatch):
    keyless = (SENT[0], ["doer", "key", "refs"])
    s = Script(entry_add=[NONE, keyless], board_find=[(FOUND, [])], board_edit=[({}, [])])
    got = press(roots, monkeypatch, s).json()
    assert got["end"] == "taken" and got["red"] is True
    assert got["toast"] == "handed to other — sent without its key (the host agent is older than this page): m-1"
    assert [kw["action"] for kw in s.of("board_edit")] == ["done"]  # no decide
    s = Script(entry_add=[NONE, keyless], board_find=[(FOUND, [])], board_edit=[(AgentError("refused"), [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 409 and got.json()["detail"] == (
        "sent without its key: m-1 — a second press would send it again; mark the line Done: refused"
    )
    s = Script(entry_add=[NONE, keyless], board_find=[(FOUND, [])], board_edit=[(AgentUnavailable("lost"), [])])
    got = press(roots, monkeypatch, s)
    assert got.status_code == 503 and got.json()["detail"].startswith(
        "sent without its key: m-1 — the line may still be open; a second press would send it again:"
    )
    # only refs or doer dropped: its key stored, taken, the toast naming what was not
    s = Script(entry_add=[NONE, (SENT[0], ["doer"])], board_find=[(FOUND, [])], board_edit=[({}, [])])
    got = press(roots, monkeypatch, s).json()
    assert got["red"] is False and got["toast"] == (
        "handed to other (the host agent is older than this page: refs or doer not stored)"
    )


def test_a_keyless_done_meeting_a_closed_line_is_taken_red(roots, monkeypatch):
    keyless = (SENT[0], ["doer", "key", "refs"])
    s = Script(entry_add=[NONE, keyless], board_find=[(FOUND, [])],
               board_edit=[(AgentError(f"no line {KEY} on the board — reworded or closed"), [])])  # fmt: skip
    got = press(roots, monkeypatch, s)
    assert got.status_code == 200 and got.json()["end"] == "taken" and got.json()["red"] is True
    assert got.json()["toast"].startswith("handed to other — sent without its key")


def test_a_named_team_that_does_not_service_its_repo_is_refused_not_re_picked(roots, monkeypatch):
    org, _ = ui.org_here()
    board = str(roots["samscrape"].resolve())
    real = ui.entry_teams
    monkeypatch.setattr(ui, "entry_teams", lambda *a: [t for t in real(*a) if t["team"] != "oth"])
    assert ui.doer_target(org, board, "team oth", "kmaster") is None
