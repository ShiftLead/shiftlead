"""TD-1765 slice 1 (design §4.4 *The PR's reads*, TD-704): `held.reads` walks the mail the home holds into
`pr_orders.reads` — per open PR and addressee, where its latest ask stands — `held.merge_reads` keeps a saved
entry only where the mail no longer holds its ask, and `_red_prs` recomputes it at every pass."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import held
from sessionorc.models import PERSON, MailEntry, Session
from sessionorc.store import RepoStore

T0 = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _rec(sid, repo=None, **kw):
    kw.setdefault("name", sid)
    return Session(id=sid, kind="interactive", adapter="shell", dir="/tmp", state="idle", repo=repo, **kw)


def _at(minutes=0):
    return (T0 + timedelta(minutes=minutes)).isoformat()


def _ask(mid, pr=12, sender="ao-g", minutes=0, **kw):
    return MailEntry(id=mid, from_=sender, to=["x"], at=_at(minutes), kind="ask", text="read it", pr=pr, **kw)


def _reply(mid, verdict=None, sender="ao-tl"):
    return MailEntry(id=mid, from_=sender, to=["ao-g"], at=_at(30), kind="reply", text="ok", verdict=verdict)


def _repos(*roots):
    return {r: {"name": r.strip("/"), "root": r, "remote": f"git@github.com:o/{r.strip('/')}.git"} for r in roots}


def _graph(*records):
    return {s.id: s for s in records}


def _one(got, pr="12", root="/a"):
    return {x["to"]: x for x in got[root][pr]}


@pytest.mark.unit
def test_the_latest_ask_per_addressee_stands_a_re_ask_after_findings_replacing_the_first():
    author, lead = _rec("ao-g", repo="/a", team="t"), _rec("ao-tl", role="techlead", team="t")
    lead.inbox = [_ask("m-1", closed_by="r-1"), _ask("m-2", minutes=60)]
    lead.outbox = [_reply("r-1", "findings")]
    got = held.reads(_graph(author, lead), [], _repos("/a"))
    assert got == {"/a": {"12": [
        {"id": "m-2", "to": "ao-tl", "at": _at(60), "state": "open", "verdict": "", "again": False}
    ]}}  # fmt: skip
    # answered: its reply's verdict, from the outbox of the record that sent it
    lead.inbox[1].closed_by = "r-2"
    lead.outbox.append(_reply("r-2", "merged"))
    assert _one(held.reads(_graph(author, lead), [], _repos("/a")))["ao-tl"]["verdict"] == "merged"


@pytest.mark.unit
def test_an_expired_or_rerouted_copy_reads_closed_and_the_routed_copy_is_its_seats_own():
    author = _rec("ao-g", repo="/a", team="t")
    lead, other = _rec("ao-tl", role="techlead", team="t"), _rec("ao-tl2", seat={"name": "tl2"}, team="t")
    lead.inbox = [_ask("m-1", closed_reason="rerouted")]
    other.inbox = [_ask("m-1", routed={"seat": "ao-tl"})]
    by = _one(held.reads(_graph(author, lead, other), [], _repos("/a")))
    assert by["ao-tl"]["state"] == "closed" and by["ao-tl2"]["state"] == "open"
    assert [x["to"] for x in held.reads(_graph(author, lead, other), [], _repos("/a"))["/a"]["12"]] == [
        "ao-tl",
        "ao-tl2",
    ]
    lead.inbox, other.inbox = [_ask("m-3", expired_at=_at(120))], []
    assert _one(held.reads(_graph(author, lead), [], _repos("/a")))["ao-tl"]["state"] == "closed"


@pytest.mark.unit
def test_a_seats_pass_up_closes_the_passer_and_the_persons_copy_is_the_persons_entry():
    author, lead = _rec("ao-g", repo="/a", team="t"), _rec("ao-tl", role="techlead", team="t")
    up = {"passed_up": _at(10), "recommend": {"by": "ao-tl", "text": "merge it"}}
    lead.inbox = [_ask("m-1", **up)]
    person = [_ask("m-1", **up)]
    by = _one(held.reads(_graph(author, lead), person, _repos("/a")))
    assert by["ao-tl"]["state"] == "closed" and by[PERSON]["state"] == "open"
    # the recommendation pressed: the person answered, never *again* (no take-up stamp)
    lead.inbox[0].closed_by = person[0].closed_by = "p-1"
    person[0].answer = 0
    by = _one(held.reads(_graph(author, lead), person, _repos("/a")))
    assert by["ao-tl"]["state"] == "closed"  # whatever later closes its copy
    assert by[PERSON] | {"at": ""} == {"id": "m-1", "to": PERSON, "at": "", "state": "answered", "verdict": "",
                                      "again": False}  # fmt: skip
    # a pass-up to a director seat: its copy is an ordinary seat entry, keyed by its mailbox
    director = _rec("ao-dir", seat={"name": "director"})
    director.inbox = [_ask("m-1", closed_by="r-d", **up)]  # the director seat answered it
    by = _one(held.reads(_graph(author, lead, director), [], _repos("/a")))
    assert by["ao-dir"]["state"] == "answered" and by["ao-tl"]["state"] == "closed"


@pytest.mark.unit
def test_an_extras_copy_and_reply_are_its_seats():
    author = _rec("ao-g", repo="/a", team="t")
    extra = _rec("ao-x-techlead-2", name="techlead-2", seat={"name": "techlead"}, scale={"line": "techlead"})
    extra.inbox = [_ask("m-1", closed_by="r-1")]
    extra.outbox = [_reply("r-1", "pass", sender=extra.id)]
    by = _one(held.reads(_graph(author, extra), [], _repos("/a")))
    assert list(by) == ["ao-x-techlead"] and by["ao-x-techlead"]["verdict"] == "pass"


@pytest.mark.unit
def test_again_is_the_take_up_answered_with_ask_the_reader_again_alone():
    author, lead = _rec("ao-g", repo="/a", team="t"), _rec("ao-tl", role="techlead", team="t")
    stamp = {"unanswered": {"why": "limited"}, "closed_by": "p-1"}
    for answer, again in ((0, True), (1, False), (None, False)):  # Ask the reader again / I'll read it / typed
        person = [_ask("m-1", answer=answer, **stamp)]
        assert _one(held.reads(_graph(author, lead), person, _repos("/a")))[PERSON]["again"] is again
    # a person reader's own ask answered with its first answer carries no take-up stamp: never *again*
    person = [_ask("m-2", answer=0, closed_by="p-2")]
    assert _one(held.reads(_graph(author, lead), person, _repos("/a")))[PERSON]["again"] is False
    # open, it is not again either
    person = [_ask("m-3", answer=0, unanswered={"why": "x"})]
    assert _one(held.reads(_graph(author, lead), person, _repos("/a")))[PERSON]["again"] is False


@pytest.mark.unit
def test_a_newer_ask_to_a_seat_after_the_persons_answer_sorts_after_it():
    author, lead = _rec("ao-g", repo="/a", team="t"), _rec("ao-tl", role="techlead", team="t")
    person = [_ask("m-1", answer=0, unanswered={"why": "x"}, closed_by="p-1")]
    lead.inbox = [_ask("m-2", minutes=30)]
    got = held.reads(_graph(author, lead), person, _repos("/a"))["/a"]["12"]
    assert [(x["to"], x["state"], x["again"]) for x in got] == [(PERSON, "answered", True), ("ao-tl", "open", False)]


@pytest.mark.unit
def test_the_envelopes_repo_stamp_names_the_repo_and_an_empty_one_falls_back_to_the_sender():
    lead = _rec("ao-tl", role="techlead", team="t")
    author = _rec("ao-g", repo="/a", team="t")
    # a node's sender, whose record names no registered root: its stamp says repo b
    lead.inbox = [_ask("m-1", sender="ao-far@node", repo="b"), _ask("m-2", pr=13)]
    got = held.reads(_graph(author, lead), [], _repos("/a", "/b"))
    assert set(got["/b"]) == {"12"} and set(got["/a"]) == {"13"}
    # every checkout of the stamp's remote counts it
    two = {**_repos("/a"), "/a2": {"name": "a2", "root": "/a2", "remote": "git@github.com:o/a.git"}}
    lead.inbox = [_ask("m-1", repo="a")]
    assert set(held.reads(_graph(author, lead), [], two)) == {"/a", "/a2"}


@pytest.mark.unit
def test_a_saved_entry_stands_only_where_its_ask_is_gone_an_open_one_then_closed():
    old = {
        "12": [{"id": "m-1", "to": "ao-tl", "at": _at(), "state": "open", "verdict": "", "again": False}],
        "13": [{"id": "m-5", "to": "ao-tl", "at": _at(), "state": "answered", "verdict": "pass", "again": False}],
        "14": [{"id": "m-9", "to": "ao-tl", "at": _at(), "state": "open", "verdict": "", "again": False}],
    }
    # a forgotten or renamed seat: its open ask's copy is gone, so it reads closed; an answer stays as read
    got = held.merge_reads({}, old, set(), {"12", "13"})
    assert got["12"][0]["state"] == "closed" and got["13"] == old["13"] and "14" not in got  # 14 closed: pruned
    # the mail still holds it: the mail's reading wins, and a verdict once read is never blanked
    fresh = {"13": [{"id": "m-5", "to": "ao-tl", "at": _at(), "state": "answered", "verdict": "", "again": False}]}
    assert held.merge_reads(fresh, old, {"m-5"}, None)["13"][0]["verdict"] == "pass"
    # a newer ask in the mail replaces a saved one to the same addressee; an older saved one never wins
    fresh = {"12": [{"id": "m-2", "to": "ao-tl", "at": _at(60), "state": "open", "verdict": "", "again": False}]}
    assert [x["id"] for x in held.merge_reads(fresh, old, {"m-2"}, None)["12"]] == ["m-2"]
    # the open PRs unknown: nothing is pruned
    assert "14" in held.merge_reads({}, old, set(), None)


async def test_the_home_recomputes_reads_every_pass_and_keeps_them_across_a_reload(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    author = _rec("ao-g", repo=root, team="t", host=agent.host, review={"reader": "techlead", "held": ["src/**"]})
    lead = _rec("ao-tl", role="techlead", team="t", host=agent.host)
    lead.inbox = [_ask("m-1")]
    agent.sessions.update({author.id: author, lead.id: lead})
    row = {"held": ["src/a.py"], "held_head": "h", "held_key": ["src/**"], "checks": "green"}
    agent._repos[root] = {"name": "repo", "root": root, "remote": "", "prs": {"open": [{"number": 12, **row}]}}
    await agent._red_prs(T0)
    assert [(x["id"], x["state"]) for x in agent._repos[root]["pr_orders"]["reads"]["12"]] == [("m-1", "open")]
    # answered on a later pass: the reading moves with the mail (never merged as `asked` is)
    lead.inbox[0].closed_by = "r-1"
    lead.outbox = [_reply("r-1", "findings")]
    await agent._red_prs(T0 + timedelta(minutes=30))
    assert agent._repos[root]["pr_orders"]["reads"]["12"][0]["verdict"] == "findings"
    # the mail pruned and the home restarted: the entry stands as last read
    lead.inbox, lead.outbox = [], []
    agent._repos = RepoStore(agent.repos_store.path).load()
    await agent._red_prs(T0 + timedelta(hours=13))
    assert agent._repos[root]["pr_orders"]["reads"]["12"][0]["state"] == "answered"
    # the PR closes: pruned
    agent._repos[root]["prs"]["open"] = []
    await agent._red_prs(T0 + timedelta(hours=14))
    assert agent._repos[root]["pr_orders"]["reads"] == {}
