"""TD-913, design §4.10 *An item leads with one sentence* and *The answers' split*: `render.one_sentence`, the
test of a first paragraph; an answer read as its label and what it leads to; a ledger entry's `**Ask:**` line."""

from __future__ import annotations

from sessionorc import ledger, mail
from shiftlead import cli
from shiftlead.ui import render


def test_one_sentence_is_the_first_paragraph_matched_whole():
    assert render.one_sentence("Which Gemini account should the walk sign in with?")
    assert render.one_sentence("Merge #12 today?\n\nIt ships Friday. It waits a week.")
    assert render.one_sentence("Which\n  account   signs in?")  # folded first
    assert render.one_sentence("Run `a.b. c` before the merge?")  # a stop inside a code span ends nothing
    assert not render.one_sentence("Merge it. Then tag it.")
    assert not render.one_sentence("which account")  # no stop at all
    assert not render.one_sentence("")
    long = " ".join(["word"] * render.FIRST_PARA_WORDS) + " more?"
    assert not render.one_sentence(long) and render.one_sentence(" ".join(["word"] * 59) + " more?")
    # the false warnings the design names: an id or an abbreviation followed by a space
    assert not render.one_sentence("TD-909. Which card first?")
    assert not render.one_sentence("Keep it, e.g. this one?")


def test_first_para_words_lives_in_render_and_ao_msg_reads_it():
    assert render.FIRST_PARA_WORDS == 60 and not hasattr(cli, "FIRST_PARA_WORDS")
    assert cli.shape_warning(" ".join(["w"] * 61)) is not None and cli.shape_warning("Short?") is None


def test_a_question_to_the_person_is_warned_unless_it_leads_with_one_sentence():
    """TD-916, design §4.10 *The home warns, never refuses*: an `ask` or `steer` whose first paragraph is not
    one sentence gets the rule's own line, a long one too (one line, not two); a note keeps the old rule."""
    line = "the person reads one sentence first: this paragraph is not one"
    assert cli.shape_warning("Merge it. Then tag it.", question=True) == line
    assert cli.shape_warning(" ".join(["w"] * 90) + "?", question=True) == line
    assert cli.shape_warning("Merge #12 today?\n\nMerge — it ships. Wait — a week.", question=True) is None
    assert cli.shape_warning("Merge it. Then tag it.") is None  # not a question: one to three sentences


def test_an_answer_splits_on_its_first_dash_and_a_dashless_one_reads_whole():
    assert mail.split_answer("Merge it (default) — it ships — Friday") == ("Merge it (default)", "it ships — Friday")
    assert mail.split_answer("Merge it - no em dash") == ("Merge it - no em dash", "")
    assert mail.split_answer("x" * 150 + " — y") == ("x" * mail.ANSWER_CAP, "y")
    assert mail.answer_mark("Merge it (default)") == ("Merge it", True)
    assert mail.answer_mark("(default)") == ("(default)", False)


def test_the_recommended_mark_one_default_label_or_a_steers_default():
    def rec(**e):
        return mail.read_answers(e)["recommended"]

    two = ["A (default) — x", "B (default)"]
    assert rec(kind="ask", answers=["A — x", "B (default) — y"]) == 1
    assert rec(kind="ask", answers=two) is None  # two marks: no single recommendation
    assert rec(kind="steer", default="B", answers=["A — x", "B — y"]) == 1
    assert rec(kind="steer", default="B — y", answers=["A — x", "B — y"]) == 1
    assert rec(kind="steer", default="something else", answers=["A — x"]) is None
    assert mail.read_answers({"kind": "note", "text": "x"}) == {"kind": "note", "text": "x"}


def test_a_press_matches_the_whole_line_or_its_label():
    line = "Merge it (default) — it ships Friday"
    assert mail.picks_answer(line, line) and mail.picks_answer("Merge it", line)
    assert mail.picks_answer("Merge it (default)", line)
    assert not mail.picks_answer("it ships Friday", line) and not mail.picks_answer("Merge", line)


def test_a_ledger_entry_carries_its_ask_and_its_answers_consequences():
    text = (
        "## TD-060: pick one\n\n**Priority:** Low\n**Owner:** paul\n\n"
        "**Why:** the reason.\n\n**Ask:** Which account should the walk\nsign in with?\n\n"
        "**Answers:** The team's (default) — one login for all | Yours — your quota.\n\n"
        "## TD-061: no ask\n\n**Owner:** paul\n\n**Why:** x\n"
    )
    asked, bare = ledger.entries(text)
    assert asked["ask"] == "Which account should the walk sign in with?"
    assert asked["answers"] == ["The team's", "Yours"]
    assert asked["consequences"] == ["one login for all", "your quota"] and asked["default"] == 0
    assert "**Ask:**" not in "\n".join(asked["detail"])  # context is Why and Fix alone
    long = "x" * 120 + " (default)"  # a ledger answer is not capped: it is what the decided line writes
    assert ledger.answers_of(f"{long} — y | b") == (["x" * 120, "b"], ["y", ""], 0)
    assert bare["ask"] == "" and bare["answers"] == [] and bare["consequences"] == []


def test_the_inbox_row_shows_each_answer_whole_and_a_press_sends_its_label(tmp_path, monkeypatch):
    """A row with no card mode draws `<label> — <consequence>` as before the split; the route reads the
    label by the pressed index, which the home matches word for word (§4.10 *The answers' split*)."""
    from fastapi.testclient import TestClient

    from shiftlead.ui import app as ui

    e = {"id": "m-1", "answers": ["Merge it", "Hold it"], "consequences": ["it ships Friday", ""]}
    assert ui.suggested_answers(e) == ["Merge it — it ships Friday", "Hold it"]
    marked = {**e, "kind": "ask", "recommended": 0}
    assert ui.suggested_answers(marked) == ["Merge it (default) — it ships Friday", "Hold it"]
    assert ui.suggested_answers({**marked, "kind": "steer"})[0] == "Merge it — it ships Friday"
    # a steer's default badge sits on its recommended answer, whatever the shown text is
    row = ui.templates.get_template("inbox_row.html").module.answers
    steer = {**e, "kind": "steer", "default": "Merge it (default) — it ships Friday", "recommended": 0, "from": "s"}
    drawn = str(row(steer))
    assert drawn.count('class="st adflt"') == 1 and drawn.index("adflt") < drawn.index("Hold it")
    assert ui.suggested_answers({"answers": ["a"], "consequences": "bad"}) == ["a"]
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            if method == "inbox":
                return {"entries": [e]}
            return {"entry": {"id": "m-2"}, "delivered": []}

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    assert c.post("/api/person/reply", json={"reply_to": "m-1", "answer": 0}).status_code == 200
    assert calls[-1] == ("msg", {"text": "Merge it", "kind": "reply", "reply_to": "m-1", "answer": 0})
