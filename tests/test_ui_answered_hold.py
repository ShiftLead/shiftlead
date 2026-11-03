"""TD-1331 slice 2 (TD-1316's build), design §4.5 screen 12 *Three wants*, screen 11 *For you*, screen 6 *Later*:
a held entry whose question the person answered is drawn *answered — waiting on <asker>* — on its Queue card in the
grey section beside *with you*, uncounted, with no answers, Answer… or Start session, Lift the hold and Open in its
⋯ — and `ledger_for_you` draws the same on the Repo page's For you and the Inbox's *Later*."""

from __future__ import annotations

from datetime import UTC, timedelta

from markupsafe import Markup
from test_queue import NOW

from shiftlead.ui.queue import attach, branch, item_start, qid, queue_view

ANSWERED = NOW - timedelta(minutes=30)


def _repos(tmp_path, *names: str, answers: bool = True) -> dict:
    """Repo facts with one held `decision (paul)` entry, TD-60, in each repo named."""
    out = {}
    for name in names:
        root = tmp_path / name
        led = {
            "for_page": "for-you",
            "priority": "medium",
            "id": "TD-60",
            "title": "held",
            "blocked_by": ["decision (paul)"],
            "written": (ANSWERED - timedelta(hours=2)).timestamp(),
            **({"answers": ["Yes", "No"], "default": 0} if answers else {}),
        }
        out[str(root)] = {"name": name, "root": str(root), "ledger": {"path": "docs/ledger", "entries": [led]}}
    return out


def _ask(about="TD-60", **kw) -> dict:
    """The person inbox's answered `ask` about the entry, as `person_inbox` hands it (`_owing` applied)."""
    e = {
        "id": "m-1",
        "from": "ao-r-designer@kmaster",
        "to": ["person"],
        "kind": "ask",
        "text": "Lift the hold on TD-60?",
        "about": about,
        "closed_reason": "replied",
        "closed_at": ANSWERED.isoformat().replace("+00:00", "Z"),
        "outcome": None,
        "answer_given": "",
        "answer_how": "you answered",
    }
    return {**e, **kw}


FLEET = [{"id": "ao-r-designer", "name": "designer", "state": "working", "repo": "/x/r"}]


def _rows(repos, inbox, fleet=FLEET, every=None):
    from shiftlead.ui.inbox import ledger_for_you

    got = ledger_for_you(repos, fleet, {}, NOW, inbox, every)
    return [r for g in got["groups"] for r in g["rows"]]


def test_ledger_for_you_carries_answered_while_the_question_owes(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    a = row["answered"]
    assert a["name"] == "designer" and a["kind"] == "ask" and a["mid"] == "m-1"
    assert a["words"] == "you answered" and a["age"] == "30m" and a["outcome"] is None
    # a pressed suggested answer is named in its words
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(answer_given="Yes")])
    assert row["answered"]["words"] == "you answered “Yes”"
    # no question, or an asker gone with the debt unpaid: the need again
    assert _rows(_repos(tmp_path, "r"), [])[0]["answered"] is None
    assert _rows(_repos(tmp_path, "r"), [_ask()], fleet=[])[0]["answered"] is None


def test_a_bare_id_carried_by_two_repos_links_to_neither(tmp_path):
    repos = _repos(tmp_path, "r", "s")
    assert all(r["answered"] is None for r in _rows(repos, [_ask()]))
    # the Repo page passes one repo, and every repo's facts for the link's index
    one = {k: v for k, v in repos.items() if v["name"] == "r"}
    assert _rows(one, [_ask()], every=repos)[0]["answered"] is None
    assert _rows(one, [_ask()])[0]["answered"] is not None, "one repo alone: the bare id links"
    assert _rows(one, [_ask(about="r#TD-60")], every=repos)[0]["answered"] is not None


def test_a_done_outcome_draws_the_askers_line(tmp_path):
    done = {"state": "done", "text": "#2900 drops the hold", "at": (NOW - timedelta(minutes=5)).isoformat()}
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(outcome=done)])
    assert row["answered"]["outcome"] == {"text": "#2900 drops the hold"}
    html = _render(row)
    assert "designer: #2900 drops the hold" in html and "the hold goes when its PR merges" not in html


def _render(row, mode=None, home=None) -> str:
    from shiftlead.ui.app import templates

    e = {**row, **({"home": home} if home else {})}
    if mode == "card":
        e["want"] = "answered"
        return templates.get_template("queue_mail.html").render(e=e, section="needs")
    return templates.env.get_template("inbox_row.html").module.row(e, "later")


def test_the_inbox_and_repo_row_reads_answered_with_no_answers_and_lift_the_hold_in_its_dots(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render(row)
    assert '<span class="st qans">answered — waiting on designer</span>' in html
    assert "you answered · in designer's ask, 30m ago — the hold goes when its PR merges" in html
    assert "its answers" not in html and 'data-index="0"' not in html, "no answers"
    assert ">Reply<" not in html and ">Go with it<" not in html and ">Start session<" not in html
    assert ">Done…<" not in html
    dots = html.split('class="more qdots"')[1]
    assert ">Lift the hold</button>" in dots and 'data-words="go ahead"' in dots and ">Open</a>" in dots
    # the same row unanswered draws its answers and controls as before
    plain = _render({**row, "answered": None})
    assert "qans" not in plain and "its answers" in plain and ">Reply<" in plain and ">Start session<" in plain


def _world(tmp_path, inbox, asks=()):
    """A card whose only member, `r#TD-60`, is held for the person, with its ledger item attached."""
    from shiftlead.ui.app import _with_you

    (row,) = _rows(_repos(tmp_path, "r"), inbox)
    q = qid("r", "TD-60")
    answered = row["answered"]
    word = "answered — waiting on designer" if answered else ""
    top = {"qid": q, "id": "TD-60", "repo": "r", "title": "held", "priority": "Medium", "needs": "decision",
           "state": word, "with_you": None, "answered": answered}  # fmt: skip
    card = {"id": q, "group": "up_next", "status": "" if answered else "needs you", "top": top, "rows": [],
            "order": [q], "start": q}  # fmt: skip
    reading = {"at": NOW.isoformat(), "cards": [card]}
    item = {**row, "home": "queue", "on_card": q, "on_row": q}
    drawn: list[dict] = []
    got = attach(
        {"needs": [item, *asks]},
        lambda e, sec: drawn.append(e) or Markup(f'<div class="mailrow">{e.get("id")}</div>'),
        (),
        lambda c, i: item_start(card, i, FLEET),
        lambda c, i: _with_you(card, i),
    )
    return queue_view(reading, NOW, got, fleet=FLEET), drawn


def test_the_card_draws_the_item_grey_uncounted_with_no_start_session(tmp_path):
    v, drawn = _world(tmp_path, [_ask()])
    (c,) = v["up_next"]
    assert c["wants"]["n"] == {"decide": 0, "do": 0, "read": 0} and len(c["wants"]["answered"]) == 1
    assert v["n"]["needs_you"] == 0 and c["edge"] != "needs"
    assert c["items_start"] is False, "it draws no Start session, so the header may draw its own"
    (e,) = drawn
    assert e["want"] == "answered" and e["start"] == {} and c["wants"]["answered"][0]["kind"] == ""
    from shiftlead.ui.app import templates

    html = templates.env.get_template("queue_card.html").module.card(c)
    head = html.split('<div class="qrows">')[0]
    assert 'class="qsec qwith" data-sec="with_you"' in head and "qwant" not in head
    word = templates.env.get_template("queue_row.html").module.state(c["top"])
    assert word == '<span class="qstate s-with">answered — waiting on designer</span>', "the row's word, grey"
    assert branch(c["top"]) == "open"


def test_the_card_item_draws_no_answers_or_answer_and_lift_the_hold_in_its_dots(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render(row, mode="card", home="queue")
    assert "answered — waiting on designer" in html and "you answered · in designer's ask" in html
    assert "Answer…" not in html and 'data-index="0"' not in html and ">Start session<" not in html
    assert 'class="st qneed"' not in html
    dots = html.split('class="more qdots"')[1]
    assert ">Lift the hold</button>" in dots and ">Open</a>" in dots
    assert html.count(">Lift the hold<") == 1, "Lift the hold only in its ⋯"


def test_a_second_open_question_is_its_own_decide_beside_the_word(tmp_path):
    from test_ui_inbox import entry

    ask = {**entry("m-2", "ask", text="and the other?"), "home": "queue", "on_card": "r#TD-060", "on_row": "r#TD-060"}
    v, _ = _world(tmp_path, [_ask()], asks=[ask])
    (c,) = v["up_next"]
    assert c["wants"]["n"]["decide"] == 1 and len(c["wants"]["answered"]) == 1
    assert c["status"] == "needs you"


def test_the_queue_reading_feeds_the_row_and_the_ui_reads_it_aware(tmp_path):
    # the `later` row's age is the answer's, read from a `Z` time
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(closed_at=(NOW - timedelta(hours=2)).astimezone(UTC).isoformat())])
    assert row["answered"]["age"].startswith("2h")


def test_on_a_card_it_is_drawn_whole_its_details_folded_and_with_you_wins(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render({**row, "ask": "Lift the hold on TD-60?", "detail": "why"}, mode="card", home="queue")
    assert '<div class="body sentence">Lift the hold on TD-60?</div>' in html, "its Ask: sentence, as a whole item"
    assert '" open>' not in html.split("data-fold=")[1][:80], "its details folded though it has answers"
    # the person's own session holding it: *with you* wins over the answered word, in `put` and in the row
    from shiftlead.ui.app import templates

    item = {**row, "home": "queue", "on_card": "r#TD-060", "on_row": "r#TD-060"}
    drawn: list[dict] = []
    attach({"needs": [item]}, lambda e, sec: drawn.append(e) or Markup(""), (), None, lambda c, i: "p")
    assert drawn[0]["want"] == "with_you"
    html = templates.get_template("queue_mail.html").render(e={**drawn[0], "with_you": "p"}, section="needs")
    assert "with you in p" in html and "answered — waiting on" not in html
