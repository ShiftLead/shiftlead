"""Where **Lift the hold** is drawn (design §4.4 *Where Lift the hold is drawn*, TD-1829, built by TD-1879): the two
stamps `ledger_for_you` sets — `lift_item` on every row it builds, and `answered.lift: {root, id}` on a mail-answered
row whose `lift_item` is set — and every Lift on an entry's own item or row read from them, never from a test of the
template's own."""

from __future__ import annotations

from test_queue import NOW
from test_ui_answered_hold import _ask, _render, _repos, _rows

from sessionorc import queue as queue_mod


def _one(repos, inbox=(), **kw):
    (row,) = _rows(repos, list(inbox), **kw)
    return row


def test_lift_item_is_set_on_a_held_row_and_its_answered_handed_and_waiting_rows(tmp_path, monkeypatch):
    """Set on a plain held row, a mail-answered one (beside `answered.lift`), a *waits until* one and a handed one."""
    repos = _repos(tmp_path, "r")
    plain = _one(repos)
    assert plain["lift_item"] is True and plain["answered"] is None
    mail = _one(repos, [_ask()])
    assert mail["lift_item"] is True
    assert mail["answered"]["lift"] == {"root": str(tmp_path / "r"), "id": "TD-60", "go_builds": []}
    waiting = {"kind": "board", "asker": "", "closed_at": "2026-11-10", "until": "2026-11-20",
               "line": {"key": "board:0000abcd", "open": False, "said": "Not yet", "to": []}}  # fmt: skip
    monkeypatch.setattr(queue_mod, "answered_hold", lambda *a, **k: waiting)
    row = _one(repos)
    assert row["lift_item"] is True and row["answered"]["until"] == "2026-11-20"
    assert row["answered"].get("lift") is None, "a board answer carries no outcome's stamp"
    monkeypatch.setattr(queue_mod, "answered_hold", lambda *a, **k: None)
    handed = {"kind": "handed", "mid": "m-h", "asker": "ao-r-designer", "closed_at": NOW.isoformat(), "outcome": None}
    monkeypatch.setattr(queue_mod, "handed_hold", lambda *a, **k: handed)
    from shiftlead.ui.inbox import ledger_for_you

    (row,) = [r for g in ledger_for_you(repos, [], {}, NOW, [], handed=[{"id": "m-h"}])["groups"] for r in g["rows"]]
    assert row["lift_item"] is True and row["answered"]["kind"] == "handed"
    assert row["answered"].get("lift") is None, "a handed entry's outcome draws no Lift"


def test_lift_item_is_unset_on_an_entry_you_own_where_case_d_holds_and_under_a_press(tmp_path, monkeypatch):
    """Unset on an `Owner: paul` entry, where case (d) holds (and its mail answer then carries no `answered.lift`),
    and on a row a press is landing on; a session claiming the entry clears nothing (*No holder test*)."""
    owned = _repos(tmp_path, "r")
    for v in owned.values():
        v["ledger"]["entries"][0]["owner"] = "paul"
    assert _one(owned)["lift_item"] is False
    pressed = _repos(tmp_path, "r")
    for v in pressed.values():
        v["ledger"]["entries"][0]["applying"] = {"act": "decide", "answer": "Yes", "at": NOW.isoformat()}
    assert _one(pressed, [_ask()])["lift_item"] is False
    claimed = [{"id": "ao-r-w", "name": "w", "state": "working", "repo": str(tmp_path / "r"), "unattended": True,
                "progress": [{"ref": "TD-60", "status": "claimed", "at": NOW.isoformat()}]}]  # fmt: skip
    held = _one(_repos(tmp_path, "r"), fleet=claimed)
    assert held["held"] == "w" and held["lift_item"] is True
    seen: list[tuple] = []

    def case_d(member, boards, entries, repo_key, held=None):
        seen.append((member["repo"], member["id"], repo_key, sorted(entries)))
        return True

    monkeypatch.setattr(queue_mod, "lift_case_d", case_d)
    asked = _one(_repos(tmp_path, "r"), [_ask()])
    assert asked["lift_item"] is False and asked["answered"]["lift"] is None
    assert seen[-1] == ("r", "TD-60", "r", ["r#TD-060"]), "called with the qualified open entries and the repo's key"


def test_lift_item_reads_the_gate_as_the_homes_person(tmp_path):
    """An entry no longer carrying `decision (paul)` (another person's gate) draws no Lift."""
    repos = _repos(tmp_path, "r")
    for v in repos.values():
        v["ledger"]["entries"][0]["blocked_by"] = ["decision (alex)"]
    rows = _rows(repos, [])
    assert all(r["lift_item"] is False for r in rows)


def test_the_newest_unreplied_blocked_outcome_carries_the_stamp(tmp_path):
    """Two unreplied `blocked` outcomes about one entry: the newer is the one `_mail_hold` links, and its row's
    `answered` (mid and stamp) is that one's; the older draws no Lift of its own."""
    blocked = {"state": "blocked", "text": "waits on the vendor", "at": NOW.isoformat()}
    old = _ask(id="m-old", outcome=blocked, closed_at=(NOW.replace(hour=1)).isoformat())
    new = _ask(id="m-new", outcome=blocked, closed_at=(NOW.replace(hour=2)).isoformat())
    row = _one(_repos(tmp_path, "r"), [old, new])
    assert row["answered"]["mid"] == "m-new" and row["answered"]["lift"]["id"] == "TD-60"


def test_a_covered_entry_has_no_row_and_so_no_stamp(tmp_path):
    """An entry an open decided line by the person covers has no ledger row: nothing is stamped."""
    repos = _repos(tmp_path, "r")
    for v in repos.values():
        v["boards"] = {"boards": [{"items": [{"kind": "decide", "key": "board:0000abcd", "refs": ["TD-60"],
                                              "decided": {"date": "2026-11-15", "text": "Go"},
                                              "decided_by": "paul"}]}]}  # fmt: skip
    assert _rows(repos, [_ask()]) == []


def test_every_lift_on_an_entrys_own_rows_reads_the_stamp(tmp_path):
    """The Inbox's *answered* row's ⋯ and a card's grey item draw Lift only where `lift_item` is set; an `Owner: paul`
    entry draws none anywhere; an Inbox *Later* Decide row draws none among its answers."""
    row = _one(_repos(tmp_path, "r"), [_ask()])
    assert "Lift the hold" in _render(row) and "Lift the hold" in _render(row, mode="card", home="queue")
    unset = {**row, "lift_item": False}
    assert "Lift the hold" not in _render(unset)
    assert "Lift the hold" not in _render(unset, mode="card", home="queue")
    later = _one(_repos(tmp_path, "r"))
    assert later["lift_item"] and "Lift the hold" not in _render(later), "an Inbox Later row keeps no Lift"
    owned = _repos(tmp_path, "r")
    for v in owned.values():
        v["ledger"]["entries"][0]["owner"] = "paul"
    mine = _one(owned)
    for html in (_render(mine), _render({**mine, "home": "queue"})):
        assert "Lift the hold" not in html
