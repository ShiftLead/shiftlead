# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1414, design §4.7 *`ao card`*: the whole Queue card in the terminal. Under a pane or with `--ui` it reads the UI's
`/api/queue/card`, which carries no mail's words; from the person's own terminal it builds the card in-process with
`Readings.card`. Each refusal is §4.7's words with its exit code, and `--json` prints `card_view`'s answer as it is."""

from __future__ import annotations

import http.server
import json
import pathlib
import socket
import sys
import threading
import time

import pytest
from test_queue_card import fixture
from test_ui_queue import NOW

from shiftlead import cli
from shiftlead.ui import app as ui
from shiftlead.ui.queue import card_view

pytestmark = pytest.mark.unit


def view(i: str = "TD-21", words: bool = True) -> dict:
    """`card_view`'s answer over the TD-1413 fixture, with what a live reading adds: the places, the card's
    `start`, a board line's card text, detail and answers, an ask's answers, a ledger row's Ask and answers."""
    q, got = fixture()
    v = card_view(q, got, i, NOW, [], words=words)
    c = v["card"]
    c["places"], c["start"] = [{"repo": "s", "n": 1}, {"repo": "db", "n": 4}], "s#TD-21"
    for r in c["rows"][:1]:
        r["page"] = "for-you"
    for x in v["wants"]["decide"]:
        r = x["row"]
        if r.get("row") == "board":
            r.update(card={"sentence": "Pick one.", "leads": "", "context": "decide · Context: TD-21"},
                     detail="the recommended one is B", answers=["A", "B"], default="B")  # fmt: skip
        elif words:
            r.update(subject="which build first", answers=["this one", "that one"], default="that one")
    for x in v["wants"]["answered"]:
        x["row"].update(ask="Go with TD-20?", detail="the entry's detail", answers=["Go", "Not yet"],
                        consequences=["it builds", "it waits"], default="Go")  # fmt: skip
    return v


class UI:
    """A stub UI on a free loopback port: each GET answers `status` and `body`, and records its path."""

    def __init__(self, status: int = 200, body: object = None, delay: float = 0.0) -> None:
        self.status, self.body, self.delay, self.paths = status, body, delay, []
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — the handler's name
                stub.paths.append(self.path)
                time.sleep(stub.delay)
                raw = stub.body if isinstance(stub.body, bytes) else json.dumps(stub.body).encode()
                self.send_response(stub.status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def stub():
    made: list[UI] = []

    def make(*a, **kw) -> UI:
        made.append(UI(*a, **kw))
        return made[-1]

    yield make
    for u in made:
        u.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def pane(monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-s-grinder")
    monkeypatch.setattr(cli.service, "DEFAULT_PORT", free_port())


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.delenv("SHIFTLEAD_SESSION", raising=False)
    monkeypatch.setattr(cli.service, "DEFAULT_PORT", free_port())  # nothing answers there: never read


def local(monkeypatch, got=None, exc: Exception | None = None) -> list[tuple[str, bool]]:
    asked: list[tuple[str, bool]] = []

    async def card(self, id, words):
        asked.append((id, words))
        if exc is not None:
            raise exc
        return got

    monkeypatch.setattr(ui.Readings, "card", card)
    return asked


def run(capsys, *argv: str) -> tuple[int, str, str]:
    rc = cli.main(["card", *argv])
    out = capsys.readouterr()
    return rc, out.out, out.err


# ── the roads ────────────────────────────────────────────────────────────────────────────────────


def test_a_pane_reads_the_ui_with_the_id_quoted_and_the_mail_cut(pane, monkeypatch, stub, capsys):
    u = stub(body=view(words=False))
    monkeypatch.setattr(cli.service, "DEFAULT_PORT", u.port)
    asked = local(monkeypatch, view())
    rc, out, _ = run(capsys, "s#TD-21")
    assert rc == 0 and u.paths == ["/api/queue/card?id=s%23TD-21"] and asked == [], (rc, out, _)
    assert "m1 · ask · from g1 · " in out and "its words are the person's to read" in out
    assert "SECRET-ASK" not in out


def test_ui_reads_that_ui_outside_a_pane(terminal, monkeypatch, stub, capsys):
    u = stub(body=view(words=False))
    asked = local(monkeypatch, view())
    rc, out, _ = run(capsys, "TD-21", "--ui", u.url)
    assert rc == 0 and len(u.paths) == 1 and asked == [] and "its words are the person's to read" in out


def test_outside_a_pane_the_card_is_built_in_process_with_the_mail_whole(terminal, monkeypatch, capsys):
    asked = local(monkeypatch, view())
    rc, out, _ = run(capsys, "TD-21")
    assert rc == 0 and asked == [("TD-21", True)]
    assert "SECRET-ASK" in out and "its words are the person's to read" not in out


def test_a_pane_with_no_ui_and_a_ui_with_nothing_there_are_refused(pane, monkeypatch, capsys):
    local(monkeypatch, view())
    rc, _, err = run(capsys, "TD-21")
    assert rc == 1 and cli.NO_UI_CARD in err
    url = f"http://127.0.0.1:{free_port()}"
    rc, _, err = run(capsys, "TD-21", "--ui", url)
    assert rc == 1 and f"no UI answers at {url}" in err


@pytest.mark.parametrize(
    ("status", "body", "code", "words"),
    [
        (404, {"error": "no open card holds TD-99"}, 1, "no open card holds TD-99"),
        (400, {"error": "the person inbox is the person's"}, 1, "the person inbox is the person's"),
        (502, {"error": "the home did not serve the Queue: old"}, 1, "the home did not serve the Queue: old"),
        (503, {"agent_down": True}, 3, "host agent unreachable"),
        (404, {"detail": "Not Found"}, 1, "no card endpoint at "),
        (404, b"<html>not here</html>", 1, "no card endpoint at "),
        (422, {"error": "a 422 is no refusal"}, 1, "no card endpoint at "),
        (500, b"boom", 1, "no card endpoint at "),
        (200, {"something": "else"}, 1, "no card endpoint at "),
        (200, b"<html>a page</html>", 1, "no card endpoint at "),
    ],
)
def test_the_uis_answers_are_refused_in_their_words(pane, monkeypatch, stub, capsys, status, body, code, words):
    u = stub(status=status, body=body)
    rc, _, err = run(capsys, "TD-99", "--ui", u.url)
    assert rc == code and words in err, err


def test_a_ui_that_does_not_answer_in_time_is_said(pane, monkeypatch, stub, capsys):
    monkeypatch.setattr(cli, "UI_CARD_WAIT", 0.3)
    u = stub(body=view(words=False), delay=2)
    rc, _, err = run(capsys, "TD-21", "--ui", u.url)
    assert rc == 1 and "the UI did not answer in" in err


@pytest.mark.parametrize(
    ("kind", "code", "words"),
    [
        ("down", 3, "no socket"),
        ("no_queue", 1, "the home did not serve the Queue: no queue RPC"),
        ("refused", 1, "not yours"),
    ],
)
def test_a_card_refused_exits_as_its_kind_says(terminal, monkeypatch, capsys, kind, code, words):
    why = {"down": "no socket", "no_queue": "no queue RPC", "refused": "not yours"}[kind]
    local(monkeypatch, exc=ui.CardRefused(kind, why))
    rc, _, err = run(capsys, "TD-21")
    assert rc == code and words in err
    local(monkeypatch, exc=ui.CardRefused("down", ""))
    if kind == "down":
        assert run(capsys, "TD-21")[0] == 3


def test_the_completed_ambiguous_and_unheld_refusals(terminal, monkeypatch, capsys):
    local(monkeypatch, {"completed": {"closed": "2026-10-16", "pr": 12}})
    assert run(capsys, "s#TD-2")[1:] == ("", "error: s#TD-2 is on a completed card: closed 2026-10-16, #12\n")
    local(monkeypatch, {"completed": {"closed": "2026-10-16", "pr": None}})
    assert "closed 2026-10-16\n" in run(capsys, "s#TD-2")[2]
    local(monkeypatch, {"ambiguous": ["db#TD-021", "s#TD-021"]})
    assert "TD-21 is in more than one repo: db#TD-021, s#TD-021" in run(capsys, "TD-21")[2]
    local(monkeypatch, None)
    rc, _, err = run(capsys, "TD-99")
    assert rc == 1 and "no open card holds TD-99" in err


def test_outside_a_pane_with_no_ui_extra_is_named(terminal, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "shiftlead.ui.app", None)  # an import of it raises ImportError
    rc, _, err = run(capsys, "TD-21")
    assert rc == 1 and "ao card needs the [ui] extra" in err


def test_json_prints_the_answer_as_it_is_and_a_refusal_as_its_error(terminal, monkeypatch, capsys):
    v = view()
    local(monkeypatch, v)
    rc, out, _ = run(capsys, "TD-21", "--json")
    assert rc == 0 and json.loads(out) == json.loads(json.dumps(v, default=str))
    local(monkeypatch, None)
    rc, out, _ = run(capsys, "TD-99", "--json")
    assert rc == 1 and json.loads(out) == {"error": "no open card holds TD-99"}
    local(monkeypatch, exc=ui.CardRefused("down", "no socket"))
    rc, out, _ = run(capsys, "TD-21", "--json")
    assert rc == 3 and json.loads(out) == {"error": "no socket"}


# ── the text form ────────────────────────────────────────────────────────────────────────────────


def test_the_text_form_holds_the_header_rows_wants_and_mentions():
    text = "\n".join(cli._card_text(view()))
    # the header: the id and title, each place with its repo, status, done of, start
    assert text.startswith(
        "s#TD-20 — the queue's design\nup next 1 in s, 4 in db · needs you · 0/2 done · start s#TD-21\n"
    )
    # the rows, indented by depth, the after named whole, the page kind
    assert "\nrows\n  s#TD-20  high  ready\n    s#TD-21  medium  for-you  waiting · after s#TD-20\n" in text
    # each want headed by its count, each item's first line its id, kind, sender, on and tied by
    assert "\ndecide 2\n" in text and "\ndo 2\n" in text and "\nanswered 1\n" in text
    assert "  board:k1 · decide · on s#TD-21 · board of s · tied by context: s#TD-021 · due 2026-10-16\n" in text
    assert "  m1 · ask · from g1 · 2026-10-16 19:00 · on s#TD-21 · tied by words: TD-021\n" in text
    assert "  s#5 · red PR · on s#TD-20 · tied by pr: TD-020\n    TD-20 slice\n" in text
    assert "  fork PR s#6 · fork PR · on s#TD-20 · tied by title: TD-020\n" in text
    # a board line's card text, its detail and its answers with the default marked
    assert (
        "    Pick one.\n    decide · Context: TD-21\n    the recommended one is B\n    - A\n    - B (default)\n" in text
    )
    # a message whole on this road, its answers with the default
    assert (
        "    which build first\n    TD-21: SECRET-ASK? TD-30 SECRET-MENTION waits on it\n    - this one\n    - that one (default)\n"
        in text
    )
    # a ledger row: title, Ask, detail, and each answer with its consequence
    assert (
        "    entry\n    Go with TD-20?\n    the entry's detail\n    - Go (default) — it builds\n    - Not yet — it waits"
        in text
    )
    # what the items mention, by the row they name
    t30 = "\n".join(cli._card_text(view("TD-30")))
    assert "\nmentioned\n  s#TD-30\n    m1 · ask · TD-21: SECRET-ASK? TD-30 SECRET-MENTION waits on it" in t30


def test_the_text_form_opens_every_fold_and_cuts_mail_on_the_ui_road():
    q, got = fixture()
    text = "\n".join(cli._card_text(card_view(q, got, "TD-10", NOW, [], words=True)))
    # an archived row in its place with its done and Resolved text; a holder named once
    assert text.startswith("s#TD-10 — recover stuck notices\nin progress · ready · 1/2 done\n")
    assert "  s#TD-10  medium  held by grinder-1\n" in text
    assert "    s#TD-9  medium  done #70 · 2026-10-16 (grinder-1, #70) — the first step." in text
    cut = "\n".join(cli._card_text(card_view(q, got, "TD-20", NOW, [], words=False)))
    assert (
        "  m1 · ask · from g1 · 2026-10-16 19:00 · on s#TD-21 · tied by words: TD-021 · its words are the person's to read\n"
        in cut
    )
    assert "SECRET" not in cut
    t30 = "\n".join(cli._card_text(card_view(q, got, "TD-30", NOW, [], words=False)))
    assert "\nmentioned\n  s#TD-30\n    m1 · ask" in t30 and "SECRET" not in t30


def test_the_ui_road_cuts_the_mail_whatever_the_ui_answers(pane, monkeypatch, stub, capsys):
    u = stub(body=view(words=True))  # a UI that wrongly serves the mail whole
    rc, out, _ = run(capsys, "TD-21", "--ui", u.url)
    assert rc == 0 and "SECRET" not in out and "its words are the person's to read" in out


def test_a_waiting_card_says_its_phrase_and_would_be_places():
    v = view()
    v["card"].update(group="waiting", wait={"phrase": "waits on TD-5"}, would_be=[{"repo": "s", "n": 2}])
    assert cli._card_text(v)[1] == "waiting · waits on TD-5 · would be 2 in s · needs you · 0/2 done · start s#TD-21"
    v["card"].update(group="up_next", places=[{"repo": "s", "n": 3}])
    assert cli._card_text(v)[1].startswith("up next 3 · ")


def test_the_skill_names_the_command():
    skill = (pathlib.Path(__file__).parents[1] / "src" / "shiftlead" / "skill.md").read_text()
    assert "`ao card <id>`" in skill
