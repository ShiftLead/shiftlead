# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1933, design §4.5 screen 12 *Recently completed* (its **who closed it**, TD-1899) and §4.5a *Queue page,
Recently completed | who closed it*: an opened line draws, under each entry's `Resolved:` text, one quiet line
from its closing commit's trailers — *built by*, *reviewed by*, *merged by*, or *closed in #n* where the closing
PR is not the drawn one — with *no review*, *no precheck*, *merged past the gate* and an unpassed *blocked*
in the warning colour; nothing where `by` is None, and nothing on a kept card."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from test_ui_queue import NOW as QNOW
from test_ui_queue import mail, queue

from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import attach, card_index, queue_view, who_closed

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 17, 20, 0, tzinfo=UTC)
TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "templates"


def at(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


def by(**kw) -> dict:
    return {"pr": 4082, "built": ["grinder-ao-2"], "reviews": [{"model": "sonnet", "verdict": "SHIP"}],
            "precheck": True, "merged": "techlead-ao-1", "override": False, **kw}  # fmt: skip


def words(parts) -> str:
    """The line as text, a marked span in `[…]`."""
    return " · ".join("".join(f"[{s['t']}]" if s["w"] else s["t"] for s in p) for p in parts)


def test_every_part_reads_quietly_when_the_flow_ran():
    assert (
        words(who_closed(by(), 4082)) == "built by grinder-ao-2 · reviewed by sonnet, passed · merged by techlead-ao-1"
    )
    two = by(
        built=["grinder-ao-2", "techlead-ao-1"],
        reviews=[{"model": "sonnet", "verdict": "BLOCK"}, {"model": "sonnet", "verdict": "FIXED"}],
    )
    assert words(who_closed(two, 4082)) == (
        "built by grinder-ao-2 and techlead-ao-1 · reviewed by sonnet, blocked; sonnet, passed after fixes · merged by techlead-ao-1"
    )


def test_no_session_and_no_review():
    assert words(who_closed(by(built=[], reviews=[]), 4082)) == "[no review] · merged by techlead-ao-1"


def test_an_override_and_no_precheck_are_marked_and_a_none_precheck_is_not():
    b = by(override=True, precheck=False, merged="Paul")
    assert (
        words(who_closed(b, 4082))
        == "built by grinder-ao-2 · reviewed by sonnet, passed · [no precheck] · [merged past the gate] · merged by Paul"
    )
    assert "precheck" not in words(who_closed(by(precheck=None), 4082))


def test_a_blocked_is_marked_only_where_no_later_review_passed():
    last = by(reviews=[{"model": "sonnet", "verdict": "SHIP"}, {"model": "claude-sonnet", "verdict": "BLOCK"}])
    assert words(who_closed(last, 1)).split(" · ")[1] == "reviewed by sonnet, passed; claude-sonnet, [blocked]"
    # a later review with no verdict passes nothing
    nov = by(reviews=[{"model": "sonnet", "verdict": "BLOCK"}, {"model": "sonnet", "verdict": None}])
    assert "reviewed by sonnet, [blocked]; sonnet ·" in words(who_closed(nov, 4082))


def test_a_review_with_no_model_or_no_verdict():
    assert "reviewed by an unnamed reviewer, passed after fixes" in words(
        who_closed(by(reviews=[{"model": None, "verdict": "FIXED"}]), 4082)
    )
    assert "reviewed by sonnet · merged" in words(who_closed(by(reviews=[{"model": "sonnet", "verdict": None}]), 4082))


def test_a_closing_pr_that_is_not_the_drawn_one_opens_the_line():
    assert words(who_closed(by(merged="designer-ao-1", built=["designer-ao-1"]), 4080)).startswith(
        "closed in #4082 by designer-ao-1 · reviewed"
    )
    assert words(who_closed(by(built=[]), 4080)).startswith("closed in #4082 · reviewed")
    # the same PR, or no closing PR, compares nothing
    assert words(who_closed(by(), 4082)).startswith("built by")
    assert words(who_closed(by(pr=None), 4080)).startswith("built by")


def test_no_by_draws_nothing():
    assert who_closed(None, 4082) is None


# -- the view and the page


def ent(tid: str, resolved: str = "", pr=None, b=None) -> dict:
    return {"qid": f"s#{tid}", "id": tid, "title": f"{tid}'s title", "priority": "medium", "closed": at(2), "pr": pr,
            "resolved": resolved, "sha": None, "by": b}  # fmt: skip


def completed(*cards) -> dict:
    return {"cards": [], "other_work": [], "at": NOW.isoformat(),
            "completed": [{"id": es[0]["qid"], "ids": [e["qid"] for e in es], "titles": {}, "closed": at(2), "at": at(2), "pr": es[0]["pr"],
                           "entries": list(es)} for es in cards]}  # fmt: skip


def lines(q: dict) -> list[dict]:
    return queue_view(q, NOW)["completed"]["lines"]


def test_a_card_line_lists_an_entry_for_its_by_alone_and_opens():
    (ln,) = lines(completed([ent("TD-1", pr=4082, b=by())]))
    assert [e["show"] for e in ln["entries"]] == ["TD-1"]
    assert words(ln["entries"][0]["who"]).startswith("built by grinder-ao-2")
    # nothing to say: it does not open
    (ln,) = lines(completed([ent("TD-2", pr=5)]))
    assert ln["entries"] == []


def test_a_card_entry_whose_resolved_pr_differs_from_its_closing_pr():
    (ln,) = lines(completed([ent("TD-1", "designed and built", pr=4080, b=by(built=["designer-ao-1"]))]))
    assert words(ln["entries"][0]["who"]).startswith("closed in #4082 by designer-ao-1")


def card_with_row(r: dict) -> dict:
    top = {"qid": "s#TD-10", "repo": "s", "id": "TD-10", "title": "open", "priority": "Medium", "state": "ready",
           "needs": None, "pr": None, "holder": None, "key": "", "lined": False, "archived": False, "parent": None, "depth": 0, "after": []}  # fmt: skip
    row = {**top, "qid": "s#TD-9", "id": "TD-9", "title": "a part", "archived": True, "closed": at(2), "depth": 1,
           "parent": "s#TD-10", "state": "done", **r}  # fmt: skip
    return {"cards": [{"id": "s#TD-10", "key": "0i", "lined": True, "top": top, "rows": [row], "done": 1, "of": 2,
                       "status": "ready", "group": "up_next", "place": 1, "order": ["s#TD-10"], "repos": ["s"], "passed_over": []}],
            "other_work": [], "at": NOW.isoformat(), "completed": []}  # fmt: skip


def test_a_row_with_no_resolved_pr_draws_the_closing_one_and_no_closed_in():
    (ln,) = lines(card_with_row({"pr": None, "resolved": "", "by": by()}))
    (e,) = ln["entries"]
    assert e["pr"] == 4082 and words(e["who"]).startswith("built by")
    # a row whose closing PR is None still lists for its by, and draws no PR
    (ln,) = lines(card_with_row({"pr": None, "resolved": "", "by": by(pr=None)}))
    assert ln["entries"][0]["pr"] is None and ln["entries"][0]["who"]
    # no by, no Resolved: the row does not open
    (ln,) = lines(card_with_row({"pr": None, "resolved": "", "by": None}))
    assert ln["entries"] == []


def test_a_row_whose_resolved_pr_differs():
    (ln,) = lines(card_with_row({"pr": 70, "resolved": "the first step", "by": by()}))
    assert ln["entries"][0]["pr"] == 70 and words(ln["entries"][0]["who"]).startswith("closed in #4082 by grinder-ao-2")


def render(ln: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
    body = (TEMPLATES / "queue_part.html").read_text()
    start = body.index('{% if ln.entries %}<div class="qdbody"')
    end = body.index("\n", start)  # the opened line's body is one line of the partial
    return env.from_string(body[start:end]).render(ln=ln)


def test_the_page_draws_the_words_and_the_marks():
    q = completed([ent("TD-1", "done.", pr=4082, b=by(reviews=[], override=True, precheck=False, merged="Paul")),
                   ent("TD-2", pr=4083, b=by(pr=4083)), ent("TD-3", pr=7)])  # fmt: skip
    (ln,) = lines(q)
    html = render(ln)
    assert (
        '<div class="qsub">done.</div><div class="qsub qwho">built by grinder-ao-2 <span class="qwsep">·</span> <span class="warnish">no review</span>'
        in html
    )
    assert (
        '<span class="warnish">no precheck</span> <span class="qwsep">·</span> <span class="warnish">merged past the gate</span> <span class="qwsep">·</span> merged by Paul</div>'
        in html
    )
    # TD-2 is listed for its by alone: its line in place of the *no Resolved line* words; TD-3 has neither
    two = html[html.index(">TD-2<") : html.index(">TD-3<")]
    assert "no Resolved line" not in two and "qwho" in two
    three = html[html.index(">TD-3<") :]
    assert "no Resolved line" in three and "qwho" not in three


def test_a_kept_card_draws_no_who_closed_line_and_its_line_does_once_it_goes_back():
    q = queue()
    q["completed"][1]["entries"][0]["by"] = by(pr=13)  # TD-3, kept while an ask about it is open

    def view(entries):
        secs = inbox_sections(list(entries), now=QNOW, boards=[], cards=card_index(q))
        return queue_view(q, QNOW, attach(secs, lambda e, sec: ""))

    ask = mail("m1", "merge #13?", about="TD-3")
    (k,) = view([ask])["kept"]
    assert all("who" not in r and "by" not in r for r in [k["top"], *k["rows"]])
    v = view([{**ask, "closed_reason": "answered"}])
    (ln,) = [ln for ln in v["completed"]["lines"] if ln["show"] == "TD-3"]
    assert (
        words(ln["entries"][0]["who"]) == "built by grinder-ao-2 · reviewed by sonnet, passed · merged by techlead-ao-1"
    )
