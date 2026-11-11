"""TD-1497 slice 4 (design §6 rule 13 *What the person sees*, §4.5 screen 6, §4.5a *Queue card / Inbox: stuck row*):
a stuck handed entry's row moves as a decided line's does — from *Waiting on them* to *Needs you* (on a card, its Do
group), counted, the stuck words a line under it, while it is a need; left under *Waiting on them*, uncounted, at
*waiting*; never a second row. Where a stopped holder's state row names its actor on the same surface, that row takes
the line alone and the handed row stays under *Waiting on them*. `ao card` prints it with kind *stuck*."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_stuck_rows import reading
from test_ui_queue import NOW, queue

from shiftlead import cli
from shiftlead.ui.inbox import handed_rows, inbox_sections, stuck_rows
from shiftlead.ui.queue import attach, card_index, card_view, items_n, queue_view


def drawn(e, sec):
    return f'<div class="mailrow" data-msg="{e.get("id")}">{e.get("text")}</div>'


def handed(mid="m-9", **kw):
    """An entry the person handed techlead-1 (g7), as the `inbox` read lists it: the holder's open `ask` copy."""
    return {
        "id": mid, "from": "person", "to": ["g7"], "kind": "ask", "subject": "build the queue",
        "text": "build the queue: TD-21", "repo": "s", "at": "2026-10-20T10:00:00Z", "handed": True, "owes": True,
        "entry": {"repo": "s", "type": "debt"}, "holder": "g7", "holder_name": "techlead-1",
        "holder_state": "limited", **kw,
    }  # fmt: skip


def state(row="limited", sid="g7", name="techlead-1"):
    return {"row": row, "id": f"{sid}:{row}", "sid": sid, "name": name, "subject": f"{row} · {name}",
            "text": "the profile is at its cap", "team": "", "at": "", "age": ""}  # fmt: skip


def sections(stuck, entries=None, states=(), held_on=None):
    q = queue()
    index = card_index(q)
    if held_on:
        index = {**index, "holder:g7": index[held_on]}
    rows = [*states, *stuck_rows(stuck, now=NOW, records=[{"id": "g7"}])]
    h = handed_rows([handed()] if entries is None else entries, {}, NOW)
    secs = inbox_sections([], now=NOW, states=rows, handed=h, cards=index)
    return q, secs


def card(v, cid):
    return next(c for g in ("in_progress", "up_next", "waiting") for c in v[g] if c["id"] == cid)


@pytest.mark.unit
def test_an_unstuck_handed_entry_waits_on_them_uncounted():
    _, secs = sections({})
    (r,) = secs["waiting"]
    assert r["id"] == "m-9" and not r.get("stuck") and secs["count"] == 0


@pytest.mark.unit
def test_a_stuck_handed_entry_moves_its_own_row_to_the_do_group_counted_never_a_second_row():
    q, secs = sections(reading(about="TD-21"))
    assert not secs["waiting"]
    (r,) = secs["needs"]
    assert r["id"] == "m-9" and r.get("handed_row"), "the handed entry's own row, no stuck row beside it"
    assert r["stuck"]["text"].startswith("stuck 1h 30m: grinder-2's ask to techlead-1 — techlead-1 is at its usage")
    assert r["stuck"]["open"] == "g7" and r["stuck"]["id"] == "ask:m-9"
    assert secs["count"] == 1 and secs["queue_n"] == 1 and r["on_card"] == "s#TD-20"
    v = queue_view(q, NOW, attach(secs, drawn, start=lambda c, i, r="": {"item": i} if i else {}))
    c = card(v, "s#TD-20")
    (m,) = c["wants"]["do"]
    assert m["id"] == "m-9" and m["kind"] == "stuck" and m["want"] == "do" and m.get("stuck")
    assert not c["wants"]["decide"] and c["status"] == "needs you" and items_n(c["wants"]) == 0
    assert "qistart" not in m["html"], "a stuck item starts no session"


@pytest.mark.unit
def test_a_stuck_handed_entry_at_waiting_stays_under_waiting_on_them_uncounted():
    until = (NOW + timedelta(minutes=20)).isoformat()
    _, secs = sections(reading(about="TD-21", waiting_until=until))
    assert not secs["needs"] and secs["count"] == 0
    (r,) = secs["waiting"]
    assert r["id"] == "m-9" and r["stuck"]["waiting_until"] == until


@pytest.mark.unit
def test_a_stuck_ask_that_is_no_handed_entry_stays_a_row_of_its_own():
    _, secs = sections(reading(mid="m-1", about="TD-21"))
    rows = {r.get("row") or r["id"]: r for r in secs["needs"]}
    assert rows["stuck"]["id"] == "ask:m-1"
    (w,) = secs["waiting"]
    assert w["id"] == "m-9" and not w.get("stuck")


@pytest.mark.unit
def test_a_needs_you_actors_handed_entry_stays_waiting_its_words_under_the_pending_row():
    st = reading(about="TD-21", reason={"state": "needs_you", "name": "techlead-1"})
    _, secs = sections(st, states=[state("question")])
    (w,) = secs["waiting"]
    assert w["id"] == "m-9" and not w.get("stuck")
    (p,) = secs["needs"]
    assert p["row"] == "question" and p["stuck_lines"][0]["id"] == "ask:m-9"


@pytest.mark.unit
def test_a_stopped_holder_on_the_same_surface_takes_the_line_and_the_handed_row_goes_back():
    _, secs = sections(reading(about="TD-21"), states=[state()], held_on="s#TD-020")
    (w,) = secs["waiting"]
    assert w["id"] == "m-9" and not w.get("stuck") and "waiting_on" not in w
    (h,) = secs["needs"]
    assert h["row"] == "limited" and secs["count"] == 1 and h["stuck_lines"][0]["id"] == "ask:m-9"


@pytest.mark.unit
def test_on_two_surfaces_the_handed_rows_words_say_where_the_holder_row_is():
    _, secs = sections(reading(about="TD-21"), states=[state()])
    r = next(x for x in secs["needs"] if x.get("handed_row"))
    assert r["home"] == "queue" and r["stuck"]["text"].endswith("— its holder row is in the Inbox")
    assert secs["count"] == 2


@pytest.mark.unit
def test_ao_card_prints_a_stuck_handed_entry_with_kind_stuck_and_its_words():
    q, secs = sections(reading(about="TD-21"))
    v = card_view(q, attach(secs, drawn, raw=True), "TD-21", NOW, [], words=False)
    (m,) = v["wants"]["do"]
    assert m["kind"] == "stuck" and m["row"]["stuck"]["id"] == "ask:m-9"
    text = "\n".join(cli._card_text(v))
    assert "  m-9 · stuck · from you" in text and "    stuck 1h 30m: grinder-2's ask to techlead-1 — " in text


@pytest.mark.unit
def test_the_handed_row_draws_its_stuck_line_and_open(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    _, secs = sections(reading(about="TD-21"))
    (r,) = secs["needs"]
    html = ui.templates.get_template("queue_mail.html").render(e={**r, "want": "do"}, section="needs", origin="")
    assert "stuckline" in html and 'href="/focus/g7"' in html
    assert 'title="Opens the session the stuck work waits on, in Focus."' in html, "§4.5a's help: stuck-open"
    assert "blocked on something only a person can move" not in html, "stuck, not blocked"


@pytest.mark.unit
def test_a_blocked_handed_entry_stays_a_need_when_its_holder_row_takes_the_stuck_line():
    blocked = handed(outcome={"state": "blocked", "text": "needs a key", "at": "2026-10-20T11:00:00Z"})
    _, secs = sections(reading(about="TD-21"), entries=[blocked], states=[state()], held_on="s#TD-020")
    assert not secs["waiting"] and secs["count"] == 2
    r = next(x for x in secs["needs"] if x.get("handed_row"))
    assert not r.get("stuck"), "its words are the holder row's line"
    h = next(x for x in secs["needs"] if x.get("row") == "limited")
    assert h["stuck_lines"][0]["id"] == "ask:m-9"


@pytest.mark.unit
def test_a_blocked_handed_entry_at_waiting_still_says_it_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    until = (NOW + timedelta(minutes=20)).isoformat()
    blocked = handed(outcome={"state": "blocked", "text": "needs a key", "at": "2026-10-20T11:00:00Z"})
    _, secs = sections(reading(about="TD-21", waiting_until=until), entries=[blocked])
    (r,) = secs["needs"]
    assert r["stuck"]["waiting_until"] == until
    html = ui.templates.get_template("queue_mail.html").render(e={**r, "want": "do"}, section="needs", origin="")
    assert "blocked on something only a person can move" in html


@pytest.mark.unit
def test_a_stuck_row_counts_under_session_states_on_the_rail_server_and_script_alike():
    """§4.5 screen 6 *The rail*, *Kinds* (TD-1497): a stuck row of its own is a *session state*; a handed entry moved
    while stuck keeps its own kind, *questions*."""
    import json
    import shutil
    import subprocess

    from conftest import scratch_dir
    from test_ui_inbox import RAIL_PROBE, UI

    from shiftlead.ui.inbox import rail_counts, rail_picks, rail_rows

    # both drawn in the Inbox (a row on a Queue card is on no rail line): the handed entry names no entry
    two = {**reading(about="", repo="db"), **reading(mid="m-1", about="", repo="db")}
    _, secs = sections(two, entries=[handed(subject="draft it", text="draft it")])
    moved = next(r for r in secs["needs"] if r.get("handed_row"))
    assert moved["home"] == "inbox" and moved.get("stuck")
    rows = rail_rows(secs, [])
    assert sorted(r["kind"] for r in rows) == ["questions", "states"]
    counts = rail_counts(rows, rail_picks({"kind": "states"}))
    assert counts["kinds"]["states"] == {"shown": 1, "all": 1} and counts["kinds"]["questions"]["shown"] == 0
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the script's count is JavaScript, and nothing else runs it")
    tmp = scratch_dir()
    (tmp / "probe.js").write_text(RAIL_PROBE)
    (tmp / "cases.json").write_text(json.dumps({"rows": rows, "picks": ["?kind=states", ""]}))
    out = subprocess.run(
        [node, str(tmp / "probe.js"), str(UI / "static" / "app.js"), str(tmp / "cases.json")],
        capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)["counts"]
    assert js == [rail_counts(rows, rail_picks({"kind": "states"})), rail_counts(rows, rail_picks({}))]
