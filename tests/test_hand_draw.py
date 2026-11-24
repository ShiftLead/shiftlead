"""TD-1660 slice 3 (TD-1543's design), §4.5 screen 12 *Three verbs: Have a session do it*, §4.5a *Have a session do
it*: the draw. An `act` line whose `Doer:` resolves to another repo's techlead seat draws the button whatever the
board repo's lanes say, its press the hand-off and its title where it goes; one that does not resolve, or names the
board's own repo, draws by the lane test; the draw resolves by the press's own function (`doer_target`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from markupsafe import escape
from test_queue_item_shape import card, inbox

from shiftlead.ui import app as ui
from shiftlead.ui import help as helpmod

ACT = "act 2026-11-05 (session `grinder-ao-2` on kmaster) — **Rotate the token.** Context: TD-190. Due: 2026-11-06."
MARKED = (
    "act 2026-11-05 (session `grinder-ao-2` on kmaster) — **Sign in on the phone.** Only you can do this. "
    "Context: TD-190. Due: 2026-11-06."
)
HAND = 'data-board-act="hand"'
DECIDE = "data-answer=\"have a session do it\" data-answers='[]'"
TITLE = "goes to web's techlead seat; this item closes"


def ESC(text: str) -> str:  # noqa: N802 — the template's escape of an attribute
    return str(escape(text))


def _item(text: str = ACT, doer: str | None = "web", kind: str = "act", **kw) -> dict:
    got = {"kind": "team", "name": doer[5:], "text": doer} if doer and doer.startswith("team ") else None
    got = got or ({"kind": "repo", "name": doer, "text": doer} if doer else None)
    return {"line": 9, "text": text, "due": "2026-11-06", "overdue_days": 1, "due_tag": "1d overdue", "answers": [],
            "kind": kind, "doer": got, **kw}  # fmt: skip


def _rows(tmp_path, monkeypatch, *items, session_do: bool = False, target=None) -> list[dict]:
    from test_ui_board import host, report

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"], "session_do": session_do}
    seen: list[tuple[str, str]] = []

    def hands(r: str, doer: str):
        seen.append((r, doer))
        return target

    rows = ui.board_rows(report(root, *items), {str(root.resolve()): of}, hands)
    for row in rows:
        row["_seen"] = seen
    return rows


RESOLVED = {"root": "/c/web", "repo": "web", "team": "", "teams": [{"team": "web-grind", "seat": "techlead"}]}


def test_a_doer_that_resolves_draws_the_hand_off_where_no_lane_would_take_the_work(tmp_path, monkeypatch):
    (b,) = _rows(tmp_path, monkeypatch, _item(), session_do=False, target=RESOLVED)
    assert b["session_do"] is True and b["hand"] is True and b["hand_to"] == "web" and b["doer"] == "web"
    for html in (card(b, "do"), inbox(b)):
        assert html.count(HAND) == 1 and DECIDE not in html
        assert f'title="{ESC(TITLE)}"' in html
        assert "The step goes to web's techlead seat" in html


def test_a_doer_that_does_not_resolve_draws_by_the_lane_test_and_still_posts_the_hand_off(tmp_path, monkeypatch):
    (b,) = _rows(tmp_path, monkeypatch, _item(doer="nowhere"), session_do=False, target=None)
    assert b["session_do"] is False and b["hand"] is True and b["hand_to"] == ""
    assert "Have a session do it" not in card(b, "do") and "Have a session do it" not in inbox(b)
    (b,) = _rows(tmp_path, monkeypatch, _item(doer="nowhere"), session_do=True, target=None)
    assert b["session_do"] is True and b["hand"] is True
    html = inbox(b)
    assert html.count(HAND) == 1, "the route falls back on a doer that does not resolve"
    assert 'title="Asks a session to do this step' in html and ESC(TITLE) not in html


def test_a_doer_naming_the_boards_own_repo_is_the_press_with_no_doer(tmp_path, monkeypatch):
    for lane in (False, True):
        (b,) = _rows(tmp_path, monkeypatch, _item(doer="samscrape"), session_do=lane, target={"own": True})
        assert b["session_do"] is lane and b["hand"] is False and b["hand_to"] == ""
        if lane:
            assert inbox(b).count(DECIDE) == 1 and HAND not in inbox(b)


def test_no_doer_is_tested_by_the_lane_alone_and_never_resolved(tmp_path, monkeypatch):
    (b,) = _rows(tmp_path, monkeypatch, _item(doer=None), session_do=True, target=RESOLVED)
    assert b["hand"] is False and b["doer"] == "" and b["_seen"] == []
    assert inbox(b).count(DECIDE) == 1 and HAND not in inbox(b)


def test_a_resolved_doer_draws_nothing_on_a_decided_answered_or_marked_line(tmp_path, monkeypatch):
    cases = {
        "decided": _item(decided={"text": "have a session do it", "date": "2026-11-07"}),
        "answers": _item(answers=["Yes", "No"]),
        "marked": _item(MARKED),
    }
    for why, it in cases.items():
        (b,) = _rows(tmp_path, monkeypatch, it, target=RESOLVED)
        assert b["session_do"] is False, why
        assert HAND not in inbox(b) and HAND not in card(b, "do"), why


def test_a_team_doer_is_resolved_by_its_written_value(tmp_path, monkeypatch):
    (b,) = _rows(tmp_path, monkeypatch, _item(doer="team web-grind"), target={**RESOLVED, "team": "web-grind"})
    assert b["_seen"] == [(str((tmp_path / "samscrape").resolve()), "team web-grind")]
    assert b["hand_to"] == "web" and b["doer"] == "team web-grind"


def test_a_resolver_that_raises_resolves_nothing(tmp_path, monkeypatch):
    from test_ui_board import host, report

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": [], "session_do": False}

    def boom(_r, _d):
        raise ValueError("org.yml unreadable")

    (b,) = ui.board_rows(report(root, _item()), {str(root.resolve()): of}, boom)
    assert b["session_do"] is False and b["hand"] is True and b["hand_to"] == ""


@pytest.mark.unit
def test_the_draw_resolves_by_the_presss_own_function_once_per_pair(monkeypatch):
    calls: list[tuple] = []

    def target(org, root, doer, host, declared=None, records=()):
        calls.append((root, doer, host, declared))
        return {"own": True} if doer == "mine" else None

    monkeypatch.setattr(ui, "doer_target", target)
    hands = ui.doer_hands("ORG", "h", {"/r": ["t"]})  # type: ignore[arg-type]
    assert hands("/r", "web") is None and hands("/r", "web") is None and hands("/r", "mine") == {"own": True}
    assert calls == [("/r", "web", "h", {"/r": ["t"]}), ("/r", "mine", "h", {"/r": ["t"]})]


@pytest.mark.unit
def test_declared_of_reads_the_repos_reading():
    got = ui.declared_of({"/x/a": {"root": "/x/a", "ledger": {"declared_teams": ["t1", "t2"]}}, "/x/b": "nope"})
    assert got == {str(Path("/x/a").resolve()): ["t1", "t2"]}
    assert ui.declared_of(None) == {}


@pytest.mark.unit
def test_the_help_names_the_hand_off():
    (h,) = [h for h in helpmod.HELP if h.key == "board-have-a-session-do-it"]
    assert "goes straight to that repo or team and the item closes" in h.text


@pytest.mark.unit
def test_the_briefs_name_the_doer_on_an_act_line():
    root = Path(ui.__file__).resolve().parents[1] / "briefs"
    for name in ("grinder", "designer", "manager"):
        text = (root / f"{name}.md").read_text(encoding="utf-8")
        assert '`--doer <repo>` or `--doer "team <team>"`' in text, name
        assert "carries no `--doer`" in text, name


@pytest.mark.unit
def test_the_press_is_pending_handing_until_its_one_answer():
    js = (Path(ui.__file__).resolve().parent / "static" / "app.js").read_text(encoding="utf-8")
    assert 'board_hand: "handing…"' in js
    branch = js[js.index('if (key === "board_hand") {') :]
    branch = branch[: branch.index('pressed(key === "board_decide"')]
    assert 'res.end === "taken"' in branch and "AO.drawDecided(r, text)" in branch
    assert "decided: have a session do it" in branch
    assert "`hand-off not finished: ${m}`" in branch and "`not handed: ${m}`" in branch
    assert "sent without its key|could not check whether this was handed" in branch
