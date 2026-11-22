"""TD-2026 slice 4, design §4.4 *A design's question is asked once, on the design* (TD-2021), the Fix's steps 3 to 5,
and the gaps slice 3's review left: the design's own *with you* item gives way to the open undecided line that asks
its question; the line says *<label> releases TD-a to the grinders* in place of *holds* for the design's held builds;
a build whose design lost its gate, or one its own line asks, reads its own hold; a held build yields to *with you*, a
hand-off and a mail answer, and replaces a board answer; and the Queue draws no item for a held build."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_handed_cover import _handed, _seat
from test_queue import NOW, _entry
from test_queue_answered_hold import _asker, _q
from test_queue_board_hold import HELD, _open, _read, _row
from test_queue_held_word import PART, WORD, _ask, _design_and_build
from test_queue_lift_here import _setup
from test_queue_with_you import _mine

from sessionorc import queue
from shiftlead.ui.app import ledger_for_you, templates
from shiftlead.ui.queue import attach, item_home, releases_of


def _line(parts=("TD-002",), answers=("Go", "Not yet"), lifts=None, decided=None) -> dict:
    """The design's end-of-rounds line as the Inbox's board row carries it."""
    return {
        "row": "board",
        "kind": "decide",
        "key": "r:board:aaaa",
        "repo_name": "r",
        "context": "TD-001 decision (paul)",
        "parts": list(parts),
        "answers": list(answers),
        "lifts": lifts,
        "decided": decided,
        "text": "**Ship it?**",
    }


# the design's newest end-of-rounds line, answered *One more round* and carried to the round's entry
CLOSED = ("- [x] decide 2026-10-14 (session n/a) — **Another round?** Context: TD-001 decision (paul). Parts: TD-002. "
          "Due: 2026-10-20. Answers: Go | One more round. Decided: One more round (2026-10-15). Closed: 2026-10-15 "
          "— carried to TD-009.")  # fmt: skip


def _hold(q: str) -> dict:
    return {"id": q, "show": q.partition("#")[2], "href": "", "repo_href": "", "drawn": False}


@pytest.mark.unit
def test_the_line_says_what_go_releases_and_holds_the_rest():
    entries = {"r#TD-002": {"held_by": "r#TD-001", "owner": "grinder"}, "r#TD-005": {"owner": "grinder"}}
    holds = [_hold("r#TD-002"), _hold("r#TD-005")]
    got, rest = releases_of(_line(parts=("TD-002", "TD-005")), holds, entries)
    assert got == {"label": "Go", "to": "to the grinders", "ids": [holds[0]]}
    assert rest == [holds[1]], "an entry it covers that is no held build keeps its *holds* line"
    # a held build another seat owns: *to their lanes*
    mixed = {**entries, "r#TD-003": {"held_by": "r#TD-001", "owner": "designer"}}
    got, _ = releases_of(_line(parts=("TD-002", "TD-003")), [_hold("r#TD-002"), _hold("r#TD-003")], mixed)
    assert got["to"] == "to their lanes" and [x["id"] for x in got["ids"]] == ["r#TD-002", "r#TD-003"]
    # `Lifts:` names the label; no lifting answer says *holds*, as before
    got, _ = releases_of(_line(answers=("Yes", "No"), lifts=["Yes"]), holds[:1], entries)
    assert got["label"] == "Yes"
    assert releases_of(_line(answers=("One more round", "Hold: <note>")), holds[:1], entries) == (None, holds[:1])
    # a build not listed in its `Parts:`, or held by another design, is not released here
    assert releases_of(_line(parts=("TD-009",)), holds[:1], entries) == (None, holds[:1])
    other = {"r#TD-002": {"held_by": "r#TD-007", "owner": "grinder"}}
    assert releases_of(_line(), holds[:1], other) == (None, holds[:1])


@pytest.mark.unit
def test_the_inbox_line_draws_go_releases_from_ledger_for_yous_entries(tmp_path):
    grind = {**PART, "Owner": "grinder"}
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **grind), _entry(5, "build b", **grind)]
    root, r = _setup(tmp_path, entries, _ask("TD-002"))
    entries = ledger_for_you({root: r}, [], {}, NOW)["entries"]
    assert entries["r#TD-002"]["held_by"] == "r#TD-001"
    assert "held_by" not in entries["r#TD-005"], "TD-005 is no held build: the line does not list it"
    home = item_home({**_line(parts=("TD-002",)), "text": "**Ship it?** Context: TD-001."}, {}, entries=entries)
    assert [x["id"] for x in home["releases"]["ids"]] == ["r#TD-002"]
    # with no Queue the line has no home row: the design and a covered part the line does not list stay *holds*
    assert [x["id"] for x in home["holds"]] == ["r#TD-001", "r#TD-005"]
    html = str(templates.env.get_template("inbox_row.html").module.holds_line(home))
    rel, held = html.split("</div>")[:2]
    assert "Go releases <a" in rel and ">TD-002</a> to the grinders" in rel and "TD-005" not in rel
    assert ">holds <a" in held and ">TD-005</a>" in held and "TD-002" not in held


@pytest.mark.unit
def test_the_designs_with_you_item_gives_way_to_the_open_line():
    line = {**_line(), "home": "queue", "on_card": "r#TD-001", "on_row": "r#TD-001", "id": "board:r:aaaa"}
    line["covers"] = ["r#TD-001", "r#TD-002"]
    design = {"row": "ledger", "name": "r", "id": "TD-001", "home": "queue", "on_card": "r#TD-001",
              "on_row": "r#TD-001", "later_section": "later", "go_builds": ["TD-002"], "row_id": "ledger:r:TD-001",
              "answers": ["Go", "Not yet"]}  # fmt: skip

    def mine(card, ref):
        return "p" if ref == "r#TD-001" else None

    def wants(sections, later):
        got = attach(sections, lambda e, s: "x", later, with_of=mine)["cards"].get("r#TD-001") or {}
        return [m["want"] for sec in got.values() if isinstance(sec, list) for m in sec if isinstance(m, dict)]

    assert "with_you" not in wants({"needs": [line]}, [design]), "the line is its question"
    assert "with_you" in wants({}, [design]), "no line asks it: the item stands"
    assert "with_you" in wants({"needs": [{**line, "decided": {"text": "Go"}}]}, [design]), (
        "a decided line asks nothing"
    )
    assert "with_you" in wants({"needs": [line]}, [{**design, "go_builds": []}]), "no design with a question"


@pytest.mark.unit
def test_the_queue_draws_no_item_for_a_held_build():
    row = {"row": "ledger", "name": "r", "id": "TD-002", "home": "queue", "on_card": "r#TD-001", "on_row": "r#TD-002",
           "later_section": "later", "held_by": "r#TD-001", "row_id": "ledger:r:TD-002", "answers": []}  # fmt: skip
    got = attach({}, lambda e, s: "x", [row])["cards"]
    assert not any(m for sec in (got.get("r#TD-001") or {}).values() for m in sec), "no item, no Decide"
    assert attach({}, lambda e, s: "x", [{**row, "held_by": None}])["cards"]["r#TD-001"], "without the stamp: an item"


@pytest.mark.unit
def test_a_held_build_yields_to_with_you_a_hand_off_and_a_mail_answer(tmp_path):
    root, r = _design_and_build(tmp_path)
    row = _row(_read({root: r}, [_mine("p", root, "TD-002")]), "r#TD-002")
    assert row["state"] == "with you in p" and "held_by" not in row
    # a mail answer about the build holds over its word
    row = _row(_read({root: r}, [_asker()], [_q("TD-002", at=NOW - timedelta(minutes=30))]), "r#TD-002")
    assert row["state"] == "answered — waiting on designer" and "held_by" not in row
    # a decided open line's answer is replaced by the held word
    root, r = _setup(tmp_path / "d", [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)],
                     _open("TD-001 decision (paul)", decided="Go (2026-10-15)", parts="TD-002"))  # fmt: skip
    plain = _row(_read({root: r}), "r#TD-002")
    assert plain["state"] == WORD and plain["held_by"] == "r#TD-001", "the covering line's answer is replaced"
    # a hand-off, under the design's closed line (an open line's answer, or its asking again, wins over a hand-off)
    root, r = _setup(tmp_path / "h", [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)], CLOSED)
    plain = _row(_read({root: r}, [_seat()]), "r#TD-002")
    assert plain["state"] == WORD and plain["held_by"] == "r#TD-001"
    q = queue.reading({root: r}, [_seat()], NOW, handed=[_handed("r#TD-002")], archived={})
    assert _row(q, "r#TD-002")["state"] == "handed to techlead" and "held_by" not in _row(q, "r#TD-002")


@pytest.mark.unit
def test_a_build_whose_design_lost_its_gate_or_its_own_line_asks_reads_its_own_hold(tmp_path):
    lost = {"Priority": "High", "Added": "2026-10-01"}
    root, r = _setup(tmp_path, [_entry(1, "the design", **lost), _entry(2, "build a", **PART)], _ask("TD-002"))
    assert "held_by" not in _row(_read({root: r}), "r#TD-002"), "the design no longer carries the gate"
    root, r = _setup(tmp_path / "own", [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)],
                     _ask("TD-002"), _open("TD-002 decision (paul)", decided=None))  # fmt: skip
    assert "held_by" not in _row(_read({root: r}), "r#TD-002"), "its own open line asks it"


@pytest.mark.unit
def test_a_held_build_that_is_itself_a_design_with_a_question_reads_held(tmp_path):
    inner = {"Priority": "High", "Part_of": "TD-001", "Blocked_by": "decision (paul)"}
    deep = {"Priority": "High", "Part_of": "TD-002", "Blocked_by": "decision (paul)"}
    entries = [_entry(1, "outer", **HELD), _entry(2, "inner design", **inner), _entry(3, "inner build", **deep)]
    inner_line = _open("TD-002 decision (paul)", decided="One more round (2026-10-15)", parts="TD-003")
    root, r = _setup(tmp_path, entries, _ask("TD-002"), inner_line)
    q = _read({root: r})
    assert _row(q, "r#TD-002")["state"] == WORD and _row(q, "r#TD-002")["held_by"] == "r#TD-001"
    assert _row(q, "r#TD-003")["held_by"] == "r#TD-002", "its own builds read their own design's word"


@pytest.mark.unit
def test_ledger_for_yous_held_row_yields_to_its_own_session_a_press_and_a_hand_off(tmp_path):
    def row(repos, fleet=(), handed=()):
        got = ledger_for_you(repos, list(fleet), {}, NOW, [], handed=list(handed))
        return next(x for g in got["groups"] for x in g["rows"] if x["id"] == "TD-002")

    root, r = _design_and_build(tmp_path)
    assert row({root: r})["held_by"] == "r#TD-001"
    mine = {"id": "p", "name": "p", "state": "idle", "unattended": False, "repo": root, "dir": root,
            "progress": [{"ref": "TD-002", "status": "claimed", "at": NOW.isoformat()}]}  # fmt: skip
    assert not row({root: r}, [mine]).get("held_by"), "the person's own session holds it"
    marked = queue.lay_applying(r, {"ledger:r#TD-002": {"t": {"act": "decide", "at": "x"}}}, "r")
    assert not row({root: marked}).get("held_by"), "a press landing"
    root, r = _setup(tmp_path / "h", [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)], CLOSED)
    assert row({root: r})["held_by"] == "r#TD-001"
    seat = {"id": "ao-other-techlead", "name": "techlead", "state": "idle", "repo": "/x/other"}
    got = row({root: r}, [seat], [_handed("r#TD-002")])
    assert not got.get("held_by") and got["answered"]["kind"] == "handed", "a hand-off"
