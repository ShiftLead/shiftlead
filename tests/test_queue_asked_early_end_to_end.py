"""TD-2185, design §4.5 screen 12 *A question asked early is no want while its entry waits*, §4.4 *A question whose
entry only waits is asked early* (TD-2172): TD-2172's own case read end to end — the ledger read as the home reads it,
*Later*'s rows split onto their cards, each drawn by the Queue's renderer, the view shaped and the card drawn — so a
Waiting card holding early questions is amber-edged and counted nowhere, an In progress card takes nothing from them, a
folded card still shows them, a press on an early answer is written, and the Repo page draws a line covering only early
members with its *Asked early* line as the Queue and the Inbox do.

TD-2172's case is TD-2078 gated on the person, blocked by TD-2077 and TD-2073, each gated too, TD-2073 waiting on builds
of its own. A gated blocker with no wait of its own is the person's now and asked as any (§4.4, accepted), so its card
needs the person by it; where that blocker waits on its own date instead, every question on the card is early and the
card is Waiting."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from conftest import park_ticks
from markupsafe import Markup
from test_board import keep_ledger, origin_item, repo  # noqa: F401  (`repo` is a fixture)
from test_queue import NOW, _entry
from test_queue_asked_early import LATER, _gated, _one
from test_queue_board_hold import _read, _worker
from test_ui_queue import client

from sessionorc import queue
from sessionorc.client import LocalClient
from shiftlead.ui.app import ledger_for_you, templates
from shiftlead.ui.queue import attach, card_index, queue_view, split_later

ONE = templates.get_template("queue_mail.html")
CARD = templates.env.get_template("queue_card.html").module.card
TODAY = NOW.date().isoformat()


def _case(tmp_path, *, waits: bool = True) -> tuple[str, dict]:
    """TD-2172's case in repo `r`: TD-001 the question, blocked by TD-002 and TD-003, each gated; TD-003 blocked by
    its build TD-004, which waits until `LATER`. With `waits`, TD-002 waits until `LATER` too; else it has no wait."""
    two = f"until {LATER}, decision (paul)" if waits else "decision (paul)"
    return _one(
        tmp_path,
        _gated(1, "the question", "TD-002", "TD-003"),
        _entry(2, "a gated blocker", Priority="High", Blocked_by=two),
        _gated(3, "a gated blocker with builds", "TD-004"),
        _entry(4, "a build", Priority="High", Blocked_by=f"until {LATER}"),
    )


def _view(repos: dict, records=()) -> dict:
    """The Queue page's view as the page builds it: the reading, *Later*'s rows on their cards, each drawn by
    `queue_mail.html`, then `queue_view`."""
    q = _read(repos, records)
    lf = ledger_for_you(repos, [], {}, now=NOW)
    later = split_later(lf, [], card_index(q), entries=lf.get("entries"))[2]
    mail = attach(
        {},
        lambda e, sec: Markup(ONE.render(e=e, section=sec, board_choices={}, own="r")),
        later,
        lambda c, item, on_row: {"repo": "r", "ref": item},
    )
    return queue_view(q, NOW, mail)


def _the_card(v: dict, ref: str = "r#TD-002") -> tuple[str, dict]:
    return next((g, c) for g in ("in_progress", "waiting", "up_next") for c in v.get(g) or () if c["id"] == ref)


@pytest.mark.unit
def test_tdtwo172s_case_sits_in_waiting_amber_edged_and_counted_nowhere(tmp_path):
    root, r = _case(tmp_path)
    group, c = _the_card(_view({root: r}))
    assert (group, c["status"], c["edge"]) == ("waiting", "waiting", "needs"), "the orange card belongs in Waiting"
    assert not c["lneed"] and not c["wants"]["n"]["decide"] and not c["wants"]["n"]["do"]
    assert c["wants"]["n"]["early"] == 3 and c["items_n"] == 3, "each counts for the header's Start session"
    got = [(m["item"], m["want"], m["early"]) for m in c["wants"]["answered"]]
    assert got == [("r#TD-001", "answered", True), ("r#TD-002", "answered", True), ("r#TD-003", "answered", True)]
    html = str(CARD(c))
    assert 'class="qcard edge-needs g-waiting' in html
    assert "qwpill" not in html and "needsyou" not in html, "on no pill, and no *needs you*"
    # each its press line, its first wait named as the design orders them, then its whole bar
    lines = re.findall(r'<div class="qpress qp-idle qearly" role="status">([^<]*)</div>', html)
    assert lines == [
        "Asked early: your answer acts once 2026-12-01 and 1 more close.",
        "Asked early: your answer acts once 2026-12-01.",
        "Asked early: your answer acts once TD-004 closes.",
    ]
    for kept in ("Lift the hold", "Not clear", "Answer…", "Start session", ">Open</a>"):
        assert html.count(kept) >= 3, kept
    # a folded card hides its rows alone: the early items are drawn in its header, above them
    head = html[: html.index('<div class="qrows">')]
    assert head.count("qearly") == 3
    css = (Path(templates.env.loader.searchpath[0]).parent / "static" / "app.css").read_text()
    assert ".qcard.folded .qrows { display: none; }" in css


@pytest.mark.unit
def test_a_gated_blocker_with_no_wait_is_asked_as_any_and_its_card_needs_the_person(tmp_path):
    root, r = _case(tmp_path, waits=False)
    _group, c = _the_card(_view({root: r}))
    assert c["status"] == "needs you" and c["edge"] == "needs" and c["lneed"], "TD-002 is the person's now"
    assert c["wants"]["n"]["early"] == 2, "TD-001 and TD-003 are still early beside it"
    html = str(CARD(c))
    assert html.count('class="qpress qp-idle qearly"') == 2


@pytest.mark.unit
def test_an_in_progress_card_takes_nothing_from_its_early_items(tmp_path):
    root, r = _case(tmp_path)
    rec = _worker("ao-r-grinder", "TD-004")
    rec.repo = rec.dir = root
    group, c = _the_card(_view({root: r}, [rec]))
    assert (group, c["edge"]) == ("in_progress", "working") and c["status"] != "needs you"
    assert c["wants"]["n"]["early"] == 3 and not c["wants"]["n"]["decide"]
    html = str(CARD(c))
    assert "g-waiting" not in html and "edge-needs" not in html and "qwpill" not in html
    assert html.count('class="qpress qp-idle qearly"') == 3, "the items' own edge is grey here (app.css)"


async def test_a_press_on_an_early_answer_is_written(agent, repo, tmp_path, monkeypatch):  # noqa: F811
    """No 409: the home's stale refusal reads the fact alone, so an answer to an early member lands as a decided line.
    The entries are TD-2172's case read from a ledger as the home reads it (`blocked_ids`, `gates` marked), so TD-001
    and TD-003 are asked early before the press: TD-001 on gated blockers alone, TD-003 on the open build TD-004, which
    carries no gate of the person's and so is counted work. A refusal reading every counted wait (`counted.work` or
    `counted.wide`) in place of the fact refuses the press on TD-003, or on both."""
    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", repo / "scripts", dirs_exist_ok=True)
    root = str(repo)

    async def held() -> None:
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    keep_ledger(agent, monkeypatch)
    await park_ticks(agent)

    asks = {"Answers": "Go (default) | Not yet"}
    _, r = _one(
        tmp_path / "read",
        _gated(1, "the question", "TD-002", "TD-003", **asks),
        _entry(2, "a gated blocker", Priority="High", Blocked_by=f"until {LATER}, decision (paul)"),
        _gated(3, "a gated blocker with builds", "TD-004", **asks),
        _entry(4, "a build", Priority="High", Blocked_by=f"until {LATER}"),
    )
    entries = r["ledger"]["entries"]
    by = {e["id"]: e for e in entries}
    assert by["TD-001"]["blocked_ids"] == ["TD-002", "TD-003"] and by["TD-003"]["blocked_ids"] == ["TD-004"]
    agent._repos = {root: {"name": "repo", "root": root, "ledger": {"entries": entries}, "work_orders": {"orders": []}}}
    opens = agent._open_work()[0]
    counted = queue.counted_work(opens, queue.item_resolver({"repo": ""}), {})
    got = queue.asked(counted, opens, {})
    assert {"repo#TD-001", "repo#TD-003"} <= set(got.early) and not got.fact, "both asked early, neither the fact"
    assert counted.work.get("repo#TD-003") == ["repo#TD-004"], "TD-003's build is counted work"
    async with LocalClient() as me:
        for n in ("TD-001", "TD-003"):
            got = await me.call("ledger_decide", repo=root, id=n, answer=0)
            assert got["decided"] == "Go", n
            it = origin_item(repo, got["key"])
            assert it.kind == "decide" and it.context == n and it.decided[0] == "Go"


@pytest.mark.unit
def test_the_repo_page_draws_a_line_covering_only_early_members_early(tmp_path, monkeypatch):
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-003"),
        _gated(3, "a gated blocker with builds", "TD-004"),
        _entry(4, "a build", Priority="High", Blocked_by=f"until {LATER}"),
    )
    item = {"at": 3, "text": f"decide 2026-11-01 — **Go with TD-001?** Context: TD-001 decision (paul). Due: {TODAY}.",
            "context": "TD-001 decision (paul)", "kind": "decide", "decided": None, "due": TODAY,
            "answers": ["Go", "Not yet"], "default": "Go", "refs": ["TD-001"], "key": "board:abc12345",
            "overdue_days": 0, "due_tag": "due today"}  # fmt: skip
    board = {"root": root, "board": f"{root}/docs/user_attention.md", "items": [item]}
    repos = {root: {**r, "boards": {"today": TODAY, "boards": [board]}}}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": []}
            return {"repos": repos, "list": [], "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setenv("SHIFTLEAD_INBOX_BOARD_SHOW", "all")
    c = client(monkeypatch, tmp_path, Fake)
    for page in ("/repo/r", "/inbox"):
        html = c.get(page).text
        early = re.findall(r"Asked early: your answer acts ([^<.]*)", html)
        assert "once TD-003 closes" in early, f"{page}: the line, in TD-001's place"
        assert "once TD-004 closes" in early, f"{page}: TD-003's own row"
    html = c.get("/repo/r").text
    assert html.count('data-copy="board:abc12345"') == 1, "the line drawn once"
    assert 'data-answer="Not yet"' in html, "its answers drawn whole"
