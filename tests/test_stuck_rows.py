"""TD-1497 slice 1 (design §6 rule 13 *What the person sees*, §4.5 screen 6, §4.5a *Queue card / Inbox: stuck row*):
the home serves an `ask:` stuck entry's work (never its text); the UI draws it once, as a need — a Do item on the card
of the entry its work names, which then reads *needs you*, else a row under the Inbox's *Needs you* — or at
*waiting*, under *Waiting on them* and in no number, while every reason names its end within the wait. Its one
control is Open, the actor's Focus; `ao card` prints it with its stuck key as id and kind *stuck*."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks
from test_ui_queue import NOW, at, queue

from sessionorc import models
from shiftlead import cli
from shiftlead.ui.inbox import inbox_sections, stuck_rows
from shiftlead.ui.queue import attach, card_index, card_view, items_n, queue_view


def drawn(e, sec):
    return f'<div class="mailrow" data-msg="{e.get("id")}">{e.get("text")}</div>'


def reading(mid="m-9", about="TD-21", refs=(), repo="s", reason=None, actor="g7", name="techlead-1", **kw):
    """One `ask:` entry as `rpc_host` serves it, its work included."""
    return {
        f"ask:{mid}": {
            "since": at(1.5),
            "reason": reason or {"state": "limited", "name": name, "cap": "resets 08:00"},
            "actor": {"id": actor, "host": "h", "name": name, "more": 0},
            "work": {
                "from": "g2",
                "from_name": "grinder-2",
                "to_names": [name],
                "about": about,
                "refs": list(refs),
                "repo": repo,
            },  # fmt: skip
            **kw,
        }
    }


def sections(stuck, records=None):
    q = queue()
    rows = stuck_rows(stuck, now=NOW, records=records)
    secs = inbox_sections([], now=NOW, states=rows, cards=card_index(q))
    return q, secs, queue_view(q, NOW, attach(secs, drawn, start=lambda c, i, r="": {"item": i} if i else {}))


def card(v, cid):
    return next(c for g in ("in_progress", "up_next", "waiting") for c in v[g] if c["id"] == cid)


@pytest.mark.unit
def test_a_stuck_ask_naming_a_held_entry_is_a_do_item_on_its_card_and_makes_it_needs_you():
    assert card(sections({})[2], "s#TD-20")["status"] != "needs you"
    _, secs, v = sections(reading())
    (r,) = secs["needs"]
    assert (r["home"], r["on_card"], r["on_row"]) == ("queue", "s#TD-20", "s#TD-21")
    assert r["tied"] == {"by": "stuck", "ref": "s#TD-021"}
    assert secs["count"] == 1 and secs["queue_n"] == 1
    c = card(v, "s#TD-20")
    (m,) = c["wants"]["do"]
    assert m["id"] == "ask:m-9" and m.get("stuck") and m["kind"] == "stuck" and m["want"] == "do"
    assert c["status"] == "needs you" and c["wants"]["n"]["do"] == 1
    assert items_n(c["wants"]) == 0, "outside the header's Start session count"
    assert "qistart" not in m["html"]
    # a bare ref in its words is its sender's repo's; one in another repo is no card's
    assert sections(reading(about="", refs=["TD-21"]))[1]["needs"][0]["on_card"] == "s#TD-20"
    assert sections(reading(about="", refs=["TD-21"], repo="db"))[1]["needs"][0]["home"] == "inbox"


@pytest.mark.unit
def test_a_stuck_ask_at_waiting_is_under_waiting_on_them_in_no_number_and_leaves_the_status():
    _, secs, v = sections(reading(waiting_until=(NOW + timedelta(minutes=20)).isoformat()))
    assert not secs["needs"] and secs["count"] == 0 and secs["queue_n"] == 0
    (r,) = secs["waiting"]
    assert r["home"] == "queue" and r["on_card"] == "s#TD-20"
    c = card(v, "s#TD-20")
    assert c["status"] != "needs you" and not c["wants"]["do"] and c["wants"]["n"]["do"] == 0
    assert [m["id"] for m in c["wants"]["read"]["waiting"]] == ["ask:m-9"]


@pytest.mark.unit
def test_a_stuck_ask_naming_no_entry_is_an_inbox_needs_you_row_counted():
    for about in ("", "TD-99", "the build"):
        _, secs, _v = sections(reading(about=about))
        (r,) = secs["needs"]
        assert r["home"] == "inbox" and secs["count"] == 1 and secs["queue_n"] == 0, about


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reason", "words"),
    [
        ({"state": "limited", "name": "techlead-1", "cap": "resets 08:00"},
         "techlead-1 is at its usage cap: resets 08:00 — it is rung after"),
        ({"state": "stalled", "since": at(2)},
         "techlead-1 is stalled? — a request held past 20m with nothing new on its screen"),
        ({"state": "unfillable", "why": "fill ceiling"}, "fill ceiling"),
        ({"state": "no_lane"}, "no lane takes it"),
    ],
)  # fmt: skip
def test_the_rows_words(reason, words):
    (r,) = stuck_rows(reading(reason=reason), now=NOW)
    assert r["text"] == f"stuck 1h 30m: grinder-2's ask to techlead-1 — {words}"
    assert r["row"] == "stuck" and r["id"] == r["sid"] == "ask:m-9"


@pytest.mark.unit
def test_an_idle_actors_words_name_its_idle_start_and_more_actors_read_plus_n():
    since = datetime(2026, 10, 16, 18, 5, tzinfo=UTC)
    stuck = reading(reason={"state": "idle", "since": since.isoformat()})
    stuck["ask:m-9"]["actor"]["more"] = 2
    (r,) = stuck_rows(stuck, now=NOW)
    local = since.astimezone().strftime("%H:%M")
    assert r["text"].endswith(f"— techlead-1 has been idle since {local} with it open (+2)")


@pytest.mark.unit
def test_a_needs_you_reason_a_board_entry_and_a_malformed_reading_draw_no_row():
    assert stuck_rows(reading(reason={"state": "needs_you", "name": "techlead-1"}), now=NOW) == []
    board = {"board:k": {"since": at(2), "reason": {"state": "no_lane"}, "repo": "s"}}
    assert stuck_rows(board, now=NOW) == []
    no_work = reading()
    del no_work["ask:m-9"]["work"]
    assert stuck_rows(no_work, now=NOW) == []
    for odd in (None, [], "x", {"ask:m-1": "x"}, {"ask:m-1": {"reason": "x", "actor": {}, "work": {}}}):
        assert stuck_rows(odd, now=NOW) == []


@pytest.mark.unit
def test_open_is_the_actors_focus_and_none_for_a_gone_actor_or_a_record_the_page_does_not_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    one = ui.templates.get_template("queue_mail.html")
    (r,) = stuck_rows(reading(), now=NOW, records=[{"id": "g7"}])
    html = one.render(e={**r, "want": "do"}, section="needs", origin="", board_choices={})
    assert 'href="/focus/g7"' in html and ">Open<" in html
    assert "Snooze" not in html and "qistart" not in html and "Answer" not in html
    (r,) = stuck_rows(reading(), now=NOW, records=[{"id": "g8"}])
    assert not r["open"]
    gone = {"state": "gone", "name": "techlead-1"}
    (r,) = stuck_rows(reading(reason=gone), now=NOW, records=[{"id": "g7"}])
    html = one.render(e={**r, "want": "do"}, section="needs", origin="", board_choices={})
    assert not r["open"] and "/focus/" not in html


@pytest.mark.unit
def test_two_stuck_asks_with_one_actor_and_reason_on_one_card_cut_the_second():
    stuck = {**reading("m-1"), **reading("m-2", about="TD-20")}
    stuck["ask:m-2"]["since"] = at(1)
    stuck["ask:m-2"]["work"]["from_name"] = "grinder-3"
    _, secs, _v = sections(stuck)
    by = {r["id"]: r["text"] for r in secs["needs"]}
    assert by["ask:m-1"].endswith("— techlead-1 is at its usage cap: resets 08:00 — it is rung after")
    assert (
        by["ask:m-2"] == "stuck 1h 0m: grinder-3's ask to techlead-1 — techlead-1, as on grinder-2's ask to techlead-1"
    )
    # on two surfaces each is drawn in full
    stuck["ask:m-2"]["work"]["about"] = "TD-99"
    _, secs, _v = sections(stuck)
    assert all("as on" not in r["text"] for r in secs["needs"])


@pytest.mark.unit
def test_the_cut_compares_the_reasons_words_and_never_crosses_a_section():
    # one actor, one state, two causes: each drawn in full
    stuck = {
        **reading("m-1", reason={"state": "unfillable", "why": "profile gated"}),
        **reading("m-2", about="TD-20", reason={"state": "unfillable", "why": "fill ceiling"}),
    }
    stuck["ask:m-2"]["since"] = at(1)
    _, secs, _v = sections(stuck)
    assert all("as on" not in r["text"] for r in secs["needs"])
    # one at *waiting* (earlier) and one counted: the counted one keeps its words
    stuck = {**reading("m-1"), **reading("m-2", about="TD-20")}
    stuck["ask:m-1"]["waiting_until"] = (NOW + timedelta(minutes=20)).isoformat()
    stuck["ask:m-2"]["since"] = at(1)
    _, secs, _v = sections(stuck)
    (n,) = secs["needs"]
    assert n["id"] == "ask:m-2" and "as on" not in n["text"] and [r["id"] for r in secs["waiting"]] == ["ask:m-1"]


@pytest.mark.unit
def test_ao_card_prints_the_stuck_item_with_its_key_and_kind_stuck():
    q = queue()
    secs = inbox_sections([], now=NOW, states=stuck_rows(reading(), now=NOW), cards=card_index(q))
    got = attach(secs, drawn, raw=True)
    for words in (True, False):
        v = card_view(q, got, "TD-21", NOW, [], words=words)
        (m,) = v["wants"]["do"]
        assert m["item"] == "ask:m-9" and m["kind"] == "stuck" and m["row"]["kind"] == "stuck"
        assert m["tied"] == {"by": "stuck", "ref": "s#TD-021"}
        assert m["row"]["text"].startswith("stuck 1h 30m: grinder-2's ask"), "the home's words, kept on the cut"
        text = "\n".join(cli._card_text(v))
        assert "  ask:m-9 · stuck · on s#TD-21 · tied by stuck: s#TD-021" in text
        assert "    stuck 1h 30m: grinder-2's ask to techlead-1 — techlead-1 is at its usage cap" in text


# -- the home serves the work of an `ask:` entry, never its text


@pytest.mark.integration
async def test_rpc_host_serves_an_ask_entrys_work_and_never_its_text(agent):
    await park_ticks(agent)
    now = datetime.now(UTC)

    def rec(n):
        s = models.Session(id=f"ao-{n}", name=n, kind="claude", adapter="claude-code", dir="/w", state="limited")
        s.host = agent.host
        return s

    w, tl = rec("w"), rec("tl")
    e = models.MailEntry(id="m-5", from_="ao-w", to=["ao-tl"], at=now.isoformat(), kind="ask",
                         text="SECRET: does TD-21 hold? see shiftlead#TD-7", subject="SECRET subject TD-30",
                         about="TD-20", repo="s")  # fmt: skip
    tl.inbox.append(e)
    agent.sessions.clear()
    agent.sessions.update({w.id: w, tl.id: tl})
    agent._host_rec["stuck"] = {
        "ask:m-5": {"since": now.isoformat(), "reason": {"state": "limited"}, "actor": {"id": "ao-tl"}},
        "ask:m-gone": {"since": now.isoformat(), "reason": {"state": "limited"}, "actor": {"id": "ao-tl"}},
        "board:k": {"since": now.isoformat(), "reason": {"state": "no_lane"}, "repo": "s"},
    }
    try:
        got = (await agent.rpc_host())["stuck"]
        assert "work" not in agent._host_rec["stuck"]["ask:m-5"], "never stored"
    finally:
        agent._host_rec.pop("stuck", None)
    assert got["ask:m-5"]["work"] == {
        "from": "ao-w",
        "from_name": "w",
        "to_names": ["tl"],
        "about": "TD-20",
        "refs": ["TD-030", "TD-021", "shiftlead#TD-007"],
        "repo": "s",
    }
    assert "SECRET" not in str(got), "never the subject or the text"
    assert "work" not in got["ask:m-gone"] and "work" not in got["board:k"]
