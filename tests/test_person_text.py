"""Text a person reads is checked at its writer (design §4.10, TD-1846, slice 1): the home's `msg` refuses an
`ask` or `steer` to the person whose first paragraph is not one plain sentence (rule 1) or one of whose answers,
or a steer's default, names nobody who acts (rule 2), listing every problem and filing nothing; it files one whose
context holds code with rule 4's line in `warnings`; a look skips rule 2; a send `_route_around` turned to the
person, a note, and the person's own words are not checked."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import park_ticks

from sessionorc import ledgerboard, mail
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import PERSON

pytestmark = [pytest.mark.integration, pytest.mark.person_text]

ROOT = Path(__file__).resolve().parent.parent
GOOD = "Should the grinders build the plain-text checks now?"
ANSWERS = ["Go (default) — the grinders build it", "Hold — nobody builds it until you say"]


async def _worker(person, tmp_path, name="w", **kw):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    kw.setdefault("unattended", True)
    return (await person.call("create", name=name, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))[
        "id"
    ]


def _held(agent, sender: str) -> list:
    return [e for e in agent.person_inbox if e.from_ == sender]


async def test_an_ask_that_breaks_rules_one_and_two_is_refused_listing_every_problem_and_filing_nothing(
    agent, tmp_path
):
    async with LocalClient() as person:
        w = await _worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            long = " ".join(["word"] * 30) + "?"
            with pytest.raises(AgentError) as e:
                await c.call("msg", to="person", kind="ask", text=long, answers=ANSWERS)
            assert str(e.value).startswith("rule 1:") and "30 words" in str(e.value)
            with pytest.raises(AgentError, match=r"rule 1: .*code token"):
                await c.call("msg", to="person", kind="ask", text="Should `ao msg` refuse it?", answers=ANSWERS)
            with pytest.raises(AgentError, match=r"rule 1: .*\?"):  # an ask is a question
                await c.call("msg", to="person", kind="ask", text="The grinders build it.", answers=ANSWERS)
            with pytest.raises(AgentError, match="rule 2: answer 2 names nobody who acts"):
                await c.call("msg", to="person", kind="ask", text=GOOD, answers=[ANSWERS[0], "Pinned, run it again"])
            # both refusing rules at once: one line each, in rule order
            with pytest.raises(AgentError) as e:
                await c.call("msg", to="person", kind="ask", text=long, answers=["yes"])
            lines = str(e.value).splitlines()
            assert [ln.split(":")[0] for ln in lines] == ["rule 1", "rule 2"]
        assert _held(agent, w) == [], "a refused send files nothing"
        assert agent.sessions[w].sends == [] or all(s.verdict != "submitted" for s in agent.sessions[w].sends)


async def test_an_ask_written_to_the_rules_files_with_or_without_a_context(agent, tmp_path):
    async with LocalClient() as person:
        w = await _worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to="person", kind="ask", text=GOOD, answers=ANSWERS)
            assert got["entry"]["to"] == [PERSON]
            assert not any(x.startswith("rule ") for x in got["warnings"])
            # a context in plain words: no warning; one holding code: rule 4's line, and the send files
            two = await c.call(
                "msg",
                to="person",
                kind="ask",
                text=f"{GOOD}\n\nThe check lives in profiles.yml and grammar.py.",
                answers=ANSWERS,
                about="TD-2",
            )
            assert two["entry"]["to"] == [PERSON]
            assert any(x.startswith("rule 4:") and "profiles.yml" in x for x in two["warnings"])
        assert len(_held(agent, w)) == 2


async def test_a_steers_default_is_held_to_rule_two_unless_it_is_one_of_its_answers(agent, tmp_path):
    async with LocalClient() as person:
        w = await _worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            with pytest.raises(AgentError, match="rule 2: the default names nobody who acts"):
                await c.call("msg", to="person", kind="steer", text="I will pin it tonight.", default="Pinned")
            got = await c.call(
                "msg", to="person", kind="steer", text="I will pin it tonight.", default="Pin it — I pin it tonight"
            )
            assert got["entry"]["kind"] == "steer"
            # a default equal to an answer's label is that answer, which rule 2 read already
            got = await c.call(
                "msg",
                to="person",
                kind="steer",
                text="I will merge it tonight.",
                default="Go",
                answers=ANSWERS[:1],
                about="TD-3",
            )
            assert got["entry"]["default"] == "Go"
            # a steer's sentence is a statement or a question, never two sentences
            with pytest.raises(AgentError, match="rule 1:"):
                await c.call(
                    "msg", to="person", kind="steer", text="I pin it. Then I tag it.", default="Pin it — I pin it"
                )


async def test_a_look_reads_rules_one_and_four_and_never_rule_two(agent, tmp_path):
    shot = "docs/mockups/reviews/2026-11-16-td1846-row.png"
    async with LocalClient() as person:
        w = await _worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            ask = await c.call(
                "msg",
                to="person",
                kind="ask",
                text="Does the row read right?",
                answers=["Works", "Not right: <what>"],
                shots=[shot],
            )
            assert ask["entry"]["shots"] == [shot]
            steer = await c.call(
                "msg",
                to="person",
                kind="steer",
                text="The row reads right.",
                default="Works",
                shots=[shot],
                about="TD-4",
            )
            assert steer["entry"]["default"] == "Works"
            with pytest.raises(AgentError, match="rule 1:"):
                await c.call(
                    "msg",
                    to="person",
                    kind="ask",
                    text="Does `row` read right?",
                    answers=["Works"],
                    shots=[shot],
                    about="TD-5",
                )


async def test_a_send_routed_around_to_the_person_a_note_and_the_persons_own_words_are_not_checked(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl = await _worker(person, tmp_path, "tl", team="beta", seat={"trigger": "asks", "tags": True})
        w = await _worker(person, tmp_path, "w", team="beta")
        rec = agent.sessions[tl]
        rec.state, rec.limited_reset = "limited", None
        async with LocalClient(caller=w) as c:
            # a seat's text, written for the seat: `_route_around` takes it to the person, unchecked (§4.10)
            got = await c.call("msg", to=tl, text="may I drop `x`? it is in a.py", kind="ask", answers=["yes", "no"])
            assert got["entry"]["to"] == [PERSON] and got["routed"]["seat"] == tl
            # a note is never refused on these rules: its TD-127 warning stays the client's
            note = await c.call("msg", to="person", kind="note", text="Merged. It lives in `a.py`.", about="TD-6")
            assert note["entry"]["kind"] == "note"
        # the person's own words are never checked
        own = await person.call("msg", to=w, kind="ask", text="why `a.py`. and b", answers=["yes"])
        assert own["entry"]["from"] == PERSON


def test_person_actors_are_the_role_nouns_and_phrases_design_4_10_lists():
    text = " ".join((ROOT / "docs/design/4.10-messages.md").read_text().split())
    nouns = re.search(r"`actors=PERSON_ACTORS` \(`sessionorc.mail`\), a role noun of \*([^*]+)\*", text)
    phrases = re.search(r"and the phrases \*([^*]+)\* and \*([^*]+)\*", text)
    assert nouns and phrases
    listed = [n.strip() for n in nouns.group(1).split(",")] + [phrases.group(1), phrases.group(2)]
    assert list(mail.PERSON_ACTORS) == listed


@pytest.mark.parametrize(
    "answers",
    [
        # a gate's (§4.10 *The sets writers type by convention*, TD-1848)
        [
            "Yes — a session lifts the gate and the entry can be picked",
            "Not yet — nobody picks the entry until you say",
        ],
        # the end-of-rounds item's
        [
            "Go (default) — the grinders build it",
            "One more round — a session runs one more review round, then asks again",
            "Hold: <note> — a session revises the design as your note says",
        ],
        # a look's
        ["Works", "Not right: <what>"],
    ],
)
def test_the_answers_the_briefs_teach_as_a_convention_pass_rule_two(answers):
    look = answers[0] == "Works"
    got = mail.person_text_problems(GOOD, kind="ask", answers=answers, look=look)
    assert got == [], [p.line for p in got]
    assert all(isinstance(p, ledgerboard.PersonTextProblem) for p in got)


def test_the_first_paragraph_is_the_sentence_and_the_rest_the_context():
    got = mail.person_text_problems(f"{GOOD}\n\nSee `x.py`.", kind="ask", answers=ANSWERS)
    assert [(p.rule, p.refuse) for p in got] == [(4, False)]
    assert mail.paragraph_break("a\n\n```\nb\n\nc\n```") == ("a", "```\nb\n\nc\n```")
    assert mail.paragraph_break("```\na\n\nb\n```") is None  # a blank line inside a fence breaks nothing
