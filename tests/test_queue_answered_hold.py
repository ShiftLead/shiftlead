"""TD-1331 (TD-1316's build), design §4.4 *A row's state*, *The card's status*, *Repo facts*: a `decision (paul)`
entry whose question the person has answered reads *answered — waiting on <asker>* and is no need while its asker
acts on the answer — while the question owes its outcome, and after a `done` until the entry's file is written
after the answer or a day passes — and needs the person again on any other outcome, a gone asker, or a second
repo carrying the same bare id."""

from __future__ import annotations

import os
from datetime import timedelta

from test_queue import NOW, _by_id, _cards, _entry, _rec, _repo, archives

from sessionorc import ledger, queue
from sessionorc.models import MailEntry, Session

ANSWERED = NOW - timedelta(minutes=30)


def _q(about: str | None = "TD-001", *, mid: str = "m-1", at=ANSWERED, outcome=None, asker: str = "ao-r-designer",
       reason: str = "replied", kind: str = "ask", text: str = "Lift the hold?") -> MailEntry:  # fmt: skip
    """A question from `asker` to the person, answered at `at` (the home's `closed_at`)."""
    e = MailEntry(id=mid, from_=asker, to=["person"], at=(at - timedelta(hours=1)).isoformat(),
                  kind=kind, text=text, about=about)  # fmt: skip
    e.closed_reason, e.closed_at = reason, at.isoformat().replace("+00:00", "Z")
    e.outcome = outcome
    return e


def _held(tmp_path, name: str = "r", n: int = 1, *, written=None):
    root, r = _repo(tmp_path, name, [_entry(n, "the held one", Priority="High", Blocked_by="decision (paul)")])
    if written is not None:  # the one file's mtime is every entry's `written` in a v1 ledger
        f = os.path.join(root, "docs", "technical_debt.md")
        os.utime(f, (written.timestamp(), written.timestamp()))
        r["ledger"] = ledger.reading(root, NOW, with_history=False)
    return root, r


def _asker(state: str = "working") -> Session:
    s = _rec("ao-r-designer", "/x/r", state=state)  # works in repo `r` (TD-1509)
    s.name = "designer"
    return s


def _top(repos, questions, records=None):
    q = _cards(repos, [_asker()] if records is None else records, questions=questions)
    return q, _by_id(q)


def test_an_answered_question_still_owing_reads_answered_and_is_no_need(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    _, cards = _top({root: r}, [_q()])
    c = cards["r#TD-001"]
    t = c["top"]
    assert t["state"] == "answered — waiting on designer" and t["needs"] == "decision", "it keeps its need"
    assert t["answered"]["mid"] == "m-1" and t["answered"]["asker"] == "ao-r-designer"
    assert t["answered"]["kind"] == "ask" and t["answered"]["outcome"] is None
    assert c["status"] != "needs you"
    # the id lists still name it the person's (Start session's *waits on me*)
    assert queue.card_entries(c)[0] == ["r#TD-001"]
    # unanswered: the need, as before
    _, cards = _top({root: r}, [])
    assert cards["r#TD-001"]["top"]["state"] == "" and cards["r#TD-001"]["status"] == "needs you"


def test_a_go_with_it_and_an_about_free_question_link_by_their_words(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    q = _q(None, reason="go_with_it", kind="steer", text="TD-001: I will drop the hold")
    _, cards = _top({root: r}, [q])
    assert cards["r#TD-001"]["top"]["answered"]["kind"] == "steer"
    # a lapse or a decline is nobody's answer
    for reason in ("lapsed", "declined"):
        _, cards = _top({root: r}, [_q(reason=reason)])
        assert cards["r#TD-001"]["top"]["answered"] is None, reason


def test_after_done_the_word_holds_until_the_file_is_written_after_the_answer_or_a_day_passes(tmp_path):
    done = {"state": "done", "text": "#9 merged", "at": (NOW - timedelta(minutes=5)).isoformat(), "by": "m-9"}
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    _, cards = _top({root: r}, [_q(outcome=done)])
    assert cards["r#TD-001"]["top"]["state"] == "answered — waiting on designer"
    # the file written after the answer, the hold still standing: the need again (the merge never pulled, or a
    # sibling's edit) — a write before the `done` was sent counts too
    for when in (NOW - timedelta(minutes=1), ANSWERED + timedelta(minutes=1)):
        sub = tmp_path / f"w{int(when.timestamp())}"
        sub.mkdir()
        root2, r2 = _held(sub, written=when)
        c = _by_id(_cards({root2: r2}, [_asker()], questions=[_q(outcome=done)]))["r#TD-001"]
        assert c["top"]["answered"] is None and c["status"] == "needs you"
    # a day after the outcome with the file unwritten: the need again
    old = {**done, "at": (NOW - timedelta(days=1, minutes=1)).isoformat()}
    _, cards = _top({root: r}, [_q(outcome=old)])
    assert cards["r#TD-001"]["top"]["answered"] is None


def test_any_outcome_but_done_or_a_gone_asker_is_the_need_again(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    for state in ("dropped", "asker_gone", "dismissed", "asked_again"):  # `blocked` holds (TD-1695, below)
        out = {"state": state, "text": "", "at": NOW.isoformat(), "by": ""}
        c = _top({root: r}, [_q(outcome=out)])[1]["r#TD-001"]
        assert c["top"]["answered"] is None and c["status"] == "needs you", state
    # the asker exited, closed or absent with the debt unpaid
    for recs in ([_asker("exited")], [_asker("closed")], []):
        c = _top({root: r}, [_q()], records=recs)[1]["r#TD-001"]
        assert c["top"]["answered"] is None and c["status"] == "needs you", recs


def test_the_newest_answered_question_names_the_asker_and_an_open_one_is_its_own(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    older = _q(mid="m-0", at=ANSWERED - timedelta(minutes=10), outcome={"state": "asked_again", "text": "",
               "at": ANSWERED.isoformat(), "by": ""})  # fmt: skip
    _, cards = _top({root: r}, [older, _q(mid="m-1")])
    assert cards["r#TD-001"]["top"]["answered"]["mid"] == "m-1"
    # asked again and the new one not yet answered: the newest answered is the old one, settled — the need
    _, cards = _top({root: r}, [older])
    assert cards["r#TD-001"]["top"]["answered"] is None


def _asker_in(repo: str) -> Session:
    """The asker, its record's repo `repo` ('' for a record that names none)."""
    s = _rec("ao-r-designer", repo)
    s.name = "designer"
    return s


def test_a_bare_id_with_no_repo_links_nowhere_and_a_qualified_one_links(tmp_path):
    """An asker whose record names no repo, with no stamp and no team: the question is no repo's, so its bare id
    links nothing even where one repo alone carries it open; a `<repo>#` ref links (§4.5 screen 6, TD-1541)."""
    nowhere = [_asker_in("")]
    a, ra = _held(tmp_path, "alpha", written=ANSWERED - timedelta(hours=2))
    b, rb = _repo(tmp_path, "beta", [_entry(2, "another", Priority="Low")])
    _, cards = _top({a: ra, b: rb}, [_q()], nowhere)
    assert cards["alpha#TD-001"]["top"]["answered"] is None, "one repo alone: no repo's bare id still links none"
    c, rc = _repo(tmp_path, "gamma", [_entry(1, "gamma's own TD-001", Priority="Low")])
    _, cards = _top({a: ra, c: rc}, [_q()], nowhere)
    assert cards["alpha#TD-001"]["top"]["answered"] is None, "two repos' TD-001: no link"
    _, cards = _top({a: ra, c: rc}, [_q("alpha#TD-001")], nowhere)
    assert cards["alpha#TD-001"]["top"]["answered"] is not None, "a `<repo>#` ref links"


def test_a_bare_id_is_the_askers_repos(tmp_path):
    """TD-1509 (§4.5 screen 6 *A bare ref elsewhere*): a question's bare `TD-n` is its asker's record's repo's — an
    asker in alpha links alpha's TD-001 though gamma carries one too, and an asker in gamma never answers alpha's,
    whether or not alpha alone carries it; an orphaned question's `orphaned.repo` stands in for a gone record."""
    a, ra = _held(tmp_path, "alpha", written=ANSWERED - timedelta(hours=2))
    c, rc = _repo(tmp_path, "gamma", [_entry(1, "gamma's own TD-001", Priority="Low")])
    _, cards = _top({a: ra, c: rc}, [_q()], [_asker_in(a)])
    assert cards["alpha#TD-001"]["top"]["answered"] is not None, "the asker's repo settles two repos' TD-001"
    _, cards = _top({a: ra, c: rc}, [_q()], [_asker_in(c)])
    assert cards["alpha#TD-001"]["top"]["answered"] is None, "gamma's asker is about gamma's TD-001"
    _, cards = _top({a: ra}, [_q()], [_asker_in(c)])
    assert cards["alpha#TD-001"]["top"]["answered"] is None, "alpha alone holding it is no reason to link"
    q = _q()
    q.orphaned = {"repo": str(c), "ref": "TD-001", "how": "closed"}
    assert queue.asker_repos([q], []) == {"m-1": "gamma"}
    # §4.10's order (TD-1467): the entry's stamp, else its orphan stamp's, else its asker's live record's
    assert queue.asker_repos([q], [_asker_in(a)]) == {"m-1": "gamma"}, "the orphan stamp before the record"
    q.orphaned = None
    assert queue.asker_repos([q], [_asker_in(a)]) == {"m-1": "alpha"}, "the record where nothing is stamped"
    q.repo = "beta"
    assert queue.asker_repos([q], [_asker_in(a)]) == {"m-1": "beta"}, "the send's stamp first"


def test_answered_hold_links_a_question_by_its_own_stamped_repo(tmp_path):
    """TD-1467 (§4.4 *The card's status*, §4.10 *An envelope carries its sender's `repo`*): `answered_hold` reads a
    question's bare `TD-n` as its own stamped `repo`'s, never the member's nor its asker's record's — a question
    stamped `gamma` naming bare `TD-001` does not link alpha's TD-001, and one stamped `alpha` does, though its
    asker's record is now in gamma."""
    a, ra = _held(tmp_path, "alpha", written=ANSWERED - timedelta(hours=2))
    c, rc = _repo(tmp_path, "gamma", [_entry(1, "gamma's own TD-001", Priority="Low")])
    other = _q()
    other.repo = "gamma"
    _, cards = _top({a: ra}, [other], [_asker_in(a)])
    assert cards["alpha#TD-001"]["top"]["answered"] is None, "another repo's question never links this member"
    mine = _q()
    mine.repo = "alpha"
    _, cards = _top({a: ra, c: rc}, [mine], [_asker_in(c)])
    assert cards["alpha#TD-001"]["top"]["answered"] is not None, "its own stamp, not its asker's record now"
    # read off the question itself, with no caller's map: bare `TD-001` from gamma is never alpha's
    member, states = {"repo": "alpha", "id": "TD-001"}, {"ao-r-designer": "working"}
    both = queue.open_refs(["alpha#TD-001", "gamma#TD-001"])
    assert queue._mail_hold(member, [other], states, both, NOW) is None
    assert queue._mail_hold(member, [mine], states, both, NOW)["mid"] == "m-1"


def test_an_origin_path_ref_links_its_repos_member(tmp_path):
    """TD-1371: `refs` reads `o/a#TD-n` whole, so the open members' index carries each repo's origin path too."""
    a, ra = _held(tmp_path, "alpha", written=ANSWERED - timedelta(hours=2))
    c, rc = _repo(tmp_path, "gamma", [_entry(1, "gamma's own TD-001", Priority="Low")])
    _, cards = _top({a: ra, c: rc}, [_q("O/Alpha#TD-1")])
    assert cards["alpha#TD-001"]["top"]["answered"] is not None, "an origin path links as the name does"
    _, cards = _top({a: ra, c: rc}, [_q("o/gamma#TD-1")])
    assert cards["alpha#TD-001"]["top"]["answered"] is None, "another repo's origin path does not"
    assert queue.open_refs(["alpha#TD-001"], {"alpha": "o/alpha"})["o/alpha#TD-001"] == "alpha#TD-001"


def test_with_you_wins_over_the_answered_word(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    mine = _rec("p", root, "TD-001", state="idle")
    mine.unattended = False
    t = _by_id(_cards({root: r}, [_asker(), mine], questions=[_q()]))["r#TD-001"]["top"]
    assert t["state"] == "with you in p" and t["answered"] is None


def test_the_facts_carry_each_entrys_written(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED)
    assert r["ledger"]["entries"][0]["written"] == ANSWERED.timestamp(), "the one file's mtime"
    d = tmp_path / "v2" / "docs" / "ledger"
    d.mkdir(parents=True)
    (d / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n", encoding="utf-8")
    for n in (1, 2):
        (d / f"TD-00{n}.md").write_text(_entry(n, f"entry {n}", Priority="Low"), encoding="utf-8")
        t = (NOW - timedelta(hours=n)).timestamp()
        os.utime(d / f"TD-00{n}.md", (t, t))
    got = {e["id"]: e["written"] for e in ledger.reading(tmp_path / "v2", NOW, with_history=False)["entries"]}
    assert got == {"TD-001": (NOW - timedelta(hours=1)).timestamp(), "TD-002": (NOW - timedelta(hours=2)).timestamp()}


async def test_the_home_hands_its_person_inbox_to_the_reading_it_pushes(agent, tmp_path, monkeypatch):
    """TD-1334: the tick's `_queue_pass` passes the home's person inbox as the reading's `questions`, so the
    `queue` event it pushes draws an answered held entry as answered, and the same entry unanswered as needs you."""
    from conftest import park_ticks

    await park_ticks(agent)
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    agent._repos = {root: r}
    agent._archived = archives(agent._repos)  # what the ledger reads hand the Queue
    agent.sessions["ao-r-designer"] = _asker()
    sent: list[dict] = []

    async def push(ev: dict) -> None:
        sent.append(ev)

    monkeypatch.setattr(agent, "_broadcast", push)
    await agent._queue_pass(NOW)
    assert _by_id(sent[-1]["queue"])["r#TD-001"]["status"] == "needs you"  # nothing in the inbox yet
    agent.person_inbox.append(_q())
    await agent._queue_pass(NOW + timedelta(seconds=2))
    assert [e["event"] for e in sent] == ["queue", "queue"]
    c = _by_id(sent[-1]["queue"])["r#TD-001"]
    assert c["top"]["state"] == "answered — waiting on designer" and c["status"] != "needs you"
    assert _by_id(await agent.rpc_queue())["r#TD-001"]["top"]["answered"]["mid"] == "m-1"


BLOCKED = {"state": "blocked", "text": "needs your token", "at": NOW.isoformat(), "by": "m-9"}


def test_an_unreplied_blocked_outcome_holds_whatever_its_asker_the_file_or_a_newer_answer(tmp_path):
    """TD-1695, §4.4 *A `blocked` outcome keeps the word*: the outcome's own row is the need (a Do item on the
    card), so the member is held while it has no `replied` — its asker exited, its file written after the answer, a
    day past, and a newer answered question about the entry beside it — and the hold carries the outcome whole."""
    root, r = _held(tmp_path, written=NOW - timedelta(minutes=1))
    old = {**BLOCKED, "at": (NOW - timedelta(days=2)).isoformat()}
    newer = _q(mid="m-2", at=NOW - timedelta(minutes=5))  # answered after it, still owing
    first = _q(outcome=old)
    first.repo = newer.repo = "r"  # the send's stamp (TD-1467), so an absent asker's bare ref still links
    for recs in ([_asker("exited")], [_asker("closed")], [], [_asker()]):
        c = _top({root: r}, [first, newer], records=recs)[1]["r#TD-001"]
        held = c["top"]["answered"]
        assert held is not None and held["mid"] == "m-1" and held["outcome"] == old, recs
        assert c["status"] != "needs you", recs


def test_a_replied_blocked_outcome_holds_as_an_unreported_answer_and_ends_with_its_asker(tmp_path):
    root, r = _held(tmp_path, written=ANSWERED - timedelta(hours=2))
    replied = {**BLOCKED, "replied": {"at": NOW.isoformat(), "by": "m-10"}}
    c = _top({root: r}, [_q(outcome=replied)])[1]["r#TD-001"]
    assert c["top"]["answered"]["outcome"] == replied and c["status"] != "needs you"
    for recs in ([_asker("exited")], [_asker("closed")], []):
        c = _top({root: r}, [_q(outcome=replied)], records=recs)[1]["r#TD-001"]
        assert c["top"]["answered"] is None and c["status"] == "needs you", recs
    # a replied one is not taken before a newer answered question: the newest holds, as any
    c = _top({root: r}, [_q(outcome=replied, at=ANSWERED - timedelta(minutes=9)), _q(mid="m-2")])[1]["r#TD-001"]
    assert c["top"]["answered"]["mid"] == "m-2"


def test_of_two_unreplied_blocked_outcomes_the_newest_holds(tmp_path):
    """TD-1738: `_mail_hold` keeps the newest unreplied `blocked` question, so with two on one entry the one the
    person answered last is the hold — in either order in the mail — never the older."""
    root, r = _held(tmp_path, written=NOW - timedelta(minutes=1))
    older = _q(mid="m-1", at=NOW - timedelta(hours=3), outcome={**BLOCKED, "by": "m-8"})
    newer = _q(mid="m-2", at=NOW - timedelta(hours=1), outcome=BLOCKED)
    older.repo = newer.repo = "r"
    for qs in ([older, newer], [newer, older]):
        held = _top({root: r}, qs)[1]["r#TD-001"]["top"]["answered"]
        assert held is not None and held["mid"] == "m-2" and held["outcome"] == BLOCKED, [q.id for q in qs]
