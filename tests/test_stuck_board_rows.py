"""TD-1497 slice 2 (design §6 rule 13 *What the person sees*, §4.5 screen 6, §4.5a *Queue card / Inbox: stuck row*):
a stuck decided board line is drawn on its own row, never a second one — moved from *Waiting on them* to *Needs you*
(on a card, its Do group), counted, the stuck words a line under it, while it is a need; left under *Waiting on them*
with the words its line at *waiting*; read as its mark says under `applying`. A team read whole reads rule 13's own
words for its `work_waiting.held`. `ao card` prints the moved line with its stuck key as id and kind *stuck*."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from test_ui_queue import NOW, at, queue

from shiftlead import cli
from shiftlead.ui.inbox import inbox_sections, stuck_rows
from shiftlead.ui.queue import attach, card_index, card_view, items_n, queue_view

DAY = {"state": "team", "team": "ao-grind", "held": {"why": "day", "count": 3}}


def drawn(e, sec):
    return f'<div class="mailrow" data-msg="{e.get("id")}">{e.get("text")}</div>'


def line(key="board:k1", refs=("TD-21",), **kw):
    """A decided `decide` line as `board_rows` draws it, waiting on its session."""
    return {
        "row": "board", "id": f"board:/r/s:{key[-1]}", "key": key, "repo": "s", "repo_name": "s", "name": "s",
        "root": "/r/s", "board": "/r/s/docs/user_attention.md", "line": 5, "team": "", "teams": ["ao-grind"],
        "text": f"decide — **Go?** Context: {refs[0] if refs else 'none'}", "kind": "decide",
        "answers": ["Go", "Hold"], "default": "Go",
        "decided": {"text": "Go", "date": "2026-10-15"}, "answered": "decided", "answered_at": "2026-10-15",
        "refs": list(refs), "session": "", "due": "2026-10-20", "at": "2026-10-20", "applying": None, **kw,
    }  # fmt: skip


def stuck(key="board:k1", reason=None, actor=True, **kw):
    v = {"since": at(1.5), "reason": reason or {"state": "limited", "name": "grinder-1"}, "repo": "s", **kw}
    if actor:
        v["actor"] = {"id": "g1", "host": "h", "name": "grinder-1", "more": 0}
    return {key: v}


def sections(st, boards=None, records=None):
    boards = [line()] if boards is None else boards
    q = queue()
    rows = stuck_rows(st, now=NOW, records=records)
    secs = inbox_sections([], now=NOW, states=rows, boards=list(boards), cards=card_index(q))
    return q, secs, queue_view(q, NOW, attach(secs, drawn, start=lambda c, i, r="": {"item": i} if i else {}))


def card(v, cid):
    return next(c for g in ("in_progress", "up_next", "waiting") for c in v[g] if c["id"] == cid)


@pytest.mark.unit
def test_an_unstuck_decided_line_waits_on_them_uncounted():
    _, secs, v = sections({})
    (r,) = secs["waiting"]
    assert r["key"] == "board:k1" and not r.get("stuck") and secs["count"] == 0
    assert card(v, "s#TD-20")["status"] != "needs you"


@pytest.mark.unit
def test_a_stuck_decided_line_moves_its_own_row_to_the_do_group_counted_never_a_second_row():
    _, secs, v = sections(stuck(reason=DAY, actor=False), records=[{"id": "g1"}])
    assert not secs["waiting"]
    (r,) = secs["needs"]
    assert r["row"] == "board" and r["key"] == "board:k1", "the line's own row, no stuck row beside it"
    assert r["stuck"]["text"] == (
        "stuck 1h 30m: the Go on TD-21 — ao-grind is held by its daily start cap: 3 idle starts today"
    )
    assert not r["stuck"]["open"], "a team read whole has no live actor: no Open"
    assert secs["count"] == 1 and secs["queue_n"] == 1 and r["on_card"] == "s#TD-20"
    c = card(v, "s#TD-20")
    (m,) = c["wants"]["do"]
    assert m["id"] == "board:/r/s:1" and m["kind"] == "stuck" and m["want"] == "do" and m.get("stuck")
    assert not c["wants"]["decide"], "decided already: never Decide again"
    assert c["status"] == "needs you" and items_n(c["wants"]) == 0 and "qistart" not in m["html"]


@pytest.mark.unit
def test_a_stuck_decided_line_with_an_actor_opens_its_focus(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    _, secs, _v = sections(stuck(), records=[{"id": "g1"}])
    (r,) = secs["needs"]
    assert r["stuck"]["open"] == "g1"
    assert r["stuck"]["text"].startswith("stuck 1h 30m: the Go on TD-21 — grinder-1 is at its usage cap")
    one = ui.templates.get_template("queue_mail.html")
    html = one.render(e={**r, "want": "do"}, section="needs", origin="", board_choices={})
    assert 'href="/focus/g1"' in html and "stuck 1h 30m: the Go on TD-21" in html


@pytest.mark.unit
def test_a_stuck_decided_line_at_waiting_stays_under_waiting_on_them_uncounted_its_words_a_line():
    until = (NOW + timedelta(minutes=20)).isoformat()
    _, secs, v = sections(stuck(waiting_until=until))
    assert not secs["needs"] and secs["count"] == 0
    (r,) = secs["waiting"]
    assert r["key"] == "board:k1" and r["stuck"]["waiting_until"] == until
    assert r["stuck"]["text"].startswith("stuck 1h 30m: the Go on TD-21")
    c = card(v, "s#TD-20")
    assert c["status"] != "needs you" and not c["wants"]["do"]


@pytest.mark.unit
def test_a_stuck_decided_line_under_applying_reads_as_its_mark_and_makes_no_need():
    applying = {"verb": "decide", "answer": "Go", "at": at(0.01)}
    _, secs, v = sections(stuck(), boards=[line(applying=applying)])
    assert not secs["needs"] and secs["count"] == 0
    (r,) = secs["waiting"]
    assert "stuck" not in r, "its draw held until the press's re-read"
    assert card(v, "s#TD-20")["status"] != "needs you"


@pytest.mark.unit
def test_a_stuck_line_the_page_does_not_hold_is_a_row_of_its_own():
    for boards in ((), (line(key="board:k2"),), (line(name="other"),)):
        _, secs, _v = sections(stuck(), boards=boards)
        (r,) = [x for x in secs["needs"] if x["row"] == "stuck"]
        assert r["id"] == "board:k1" and r["text"].startswith("stuck 1h 30m: the decided line on s's board — ")
        assert r["home"] == "inbox"


@pytest.mark.unit
def test_two_stuck_lines_with_one_actor_and_reason_on_one_card_cut_the_second():
    st = {**stuck("board:k1"), **stuck("board:k2", since=at(1))}
    _, secs, _v = sections(st, boards=[line("board:k1"), line("board:k2", refs=("TD-20",))])
    by = {r["key"]: r["stuck"]["text"] for r in secs["needs"]}
    assert "as on" not in by["board:k1"]
    assert by["board:k2"] == "stuck 1h 0m: the Go on TD-20 — grinder-1, as on the Go on TD-21"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("held", "words"),
    [
        (None, "ao-grind waits for your Start"),
        ({"why": "day", "count": 3}, "ao-grind is held by its daily start cap: 3 idle starts today"),
        ({"why": "usage", "profile": "claude-code:paul"},
         "ao-grind is held by the usage gate on claude-code:paul until its usage reading resets"),
        ({"why": "balance", "repo": "shiftlead"}, "ao-grind is over its balance line on shiftlead"),
        ({"why": "link", "hosts": ["n1", "n2"]}, "ao-grind waits for n1 and n2 to answer"),
        ({"why": "nothing"}, "ao-grind has no record left to start"),
        ({"why": "stopped"}, "ao-grind is not running"),
        ({"why": "wound_down"}, "ao-grind wound down with it seen and unpicked"),
    ],
)  # fmt: skip
def test_a_team_read_whole_reads_rule_13s_words(held, words):
    reason = {"state": "team", "team": "ao-grind", **({"held": held} if held else {})}
    (r,) = stuck_rows(stuck(reason=reason, actor=False), now=NOW)
    assert r["text"] == f"stuck 1h 30m: the decided line on s's board — {words}"
    assert r["name"] == "ao-grind" and not r["open"]


@pytest.mark.unit
def test_a_team_held_until_or_early_names_its_instant():
    t = datetime(2026, 10, 16, 21, 30, tzinfo=UTC)
    local = t.astimezone().strftime("%H:%M")
    for held, words in (
        ({"why": "until", "until": t.isoformat()}, f"ao-grind is held until {local}"),
        ({"why": "early", "started": t.isoformat()}, f"ao-grind started at {local} and waits to start again"),
        ({"why": "usage", "profile": "p", "resets": t.isoformat()},
         f"ao-grind is held by the usage gate on p until {local}"),
    ):  # fmt: skip
        reason = {"state": "team", "team": "ao-grind", "held": held}
        (r,) = stuck_rows(stuck(reason=reason, actor=False), now=NOW)
        assert r["text"].endswith(f"— {words}")


@pytest.mark.unit
def test_ao_card_prints_the_moved_line_with_its_key_and_kind_stuck():
    q = queue()
    secs = inbox_sections([], now=NOW, states=stuck_rows(stuck(), now=NOW), boards=[line()], cards=card_index(q))
    got = attach(secs, drawn, raw=True)
    v = card_view(q, got, "TD-21", NOW, [], words=False)
    (m,) = v["wants"]["do"]
    assert m["item"] == "board:k1" and m["kind"] == "stuck"
    text = "\n".join(cli._card_text(v))
    assert "  board:k1 · stuck · on s#TD-21 · board of s" in text
    assert "    stuck 1h 30m: the Go on TD-21 — grinder-1 is at its usage cap" in text


@pytest.mark.unit
def test_a_stale_line_at_waiting_is_no_stuck_item_and_ao_card_prints_its_own_kind():
    until = (NOW + timedelta(minutes=20)).isoformat()
    q = queue()
    secs = inbox_sections(
        [], now=NOW, states=stuck_rows(stuck(waiting_until=until), now=NOW),
        boards=[line(stale=True)], cards=card_index(q),
    )  # fmt: skip
    (r,) = secs["needs"]  # past its wait days: where it would be unanswered, as before
    got = attach(secs, drawn, raw=True, start=lambda c, i, r="": {"item": i} if i else {})
    v = card_view(q, got, "TD-21", NOW, [], words=False)
    (m,) = v["wants"]["decide"]
    assert m["kind"] == "decide" and not m.get("stuck"), "at waiting: never the stuck item"
    text = "\n".join(cli._card_text(v))
    assert "  board:k1 · decide · " in text and "stuck 1h 30m: the Go on TD-21" in text


@pytest.mark.unit
def test_a_moved_line_homed_on_no_card_is_an_inbox_needs_you_row_counted():
    _, secs, _v = sections(stuck(), boards=[line(refs=())])
    (r,) = secs["needs"]
    assert r["key"] == "board:k1" and r["home"] == "inbox" and secs["count"] == 1 and secs["queue_n"] == 0
    assert r["stuck"]["text"].startswith("stuck 1h 30m: the Go on s's board — ")


@pytest.mark.unit
def test_a_link_hold_names_every_down_host_or_its_one_host():
    for held, hosts in (
        ({"why": "link", "hosts": ["a", "b", "c"]}, "a, b and c"),
        ({"why": "link", "host": "n9"}, "n9"),
    ):
        reason = {"state": "team", "team": "t", "held": held}
        (r,) = stuck_rows(stuck(reason=reason, actor=False), now=NOW)
        assert r["text"].endswith(f"— t waits for {hosts} to answer")
