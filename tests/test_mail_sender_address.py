"""TD-1561 (TD-1541's build; design §4.5 screen 6 *A mail item's bare ref is its sender's repo's*): an unstamped
item's sender is found by its whole address — `<id>@<host>` for another host's record, its bare id for the home's —
its root named by the readings' roots and, on the home's host alone, by its last component; failing the orphan
stamp and the record, its team's one repo; failing all, the item is read as no repo's (`own_refs`), its bare refs
matching no key."""

from __future__ import annotations

import pytest

from sessionorc import queue as q
from sessionorc.models import MailEntry, Session
from shiftlead.ui.queue import design_link, item_home

pytestmark = pytest.mark.unit

ROOTS = {"contractmatch": "/home/k/contractmatch", "shiftlead": "/home/k/shiftlead"}


def _ask(mid: str = "m-1", sender: str = "x@node", **kw) -> MailEntry:
    return MailEntry(id=mid, from_=sender, to=["person"], at="2026-11-07T12:00:00Z", kind="ask", text="?", **kw)


def _rec(sid: str, root: str = "", host: str = "", team: str = "", **kw) -> Session:
    return Session(id=sid, name=sid, kind="interactive", adapter="shell", dir=root or "/", host=host, team=team, **kw)


def test_a_view_dicts_whole_address_names_the_node_records_repo():
    view = [{"id": "x@node", "repo": "/home/k/contractmatch", "host": "kmaster"}, {"id": "x", "repo": "/home/k/sl"}]
    assert q.asker_repos([_ask(about="TD-064")], view, ROOTS) == {"m-1": "contractmatch"}
    # its `dir` when it names no `repo`, as the send's stamp reads it
    by_dir = [{"id": "x@node", "dir": "/home/k/contractmatch"}]
    assert q.asker_repos([_ask()], by_dir, ROOTS) == {"m-1": "contractmatch"}


def test_session_records_are_keyed_against_the_homes_host():
    recs = [_rec("x", "/home/k/contractmatch", host="node"), _rec("x", "/home/k/shiftlead", host="kmaster")]
    got = q.asker_repos([_ask("m-1", "x@node"), _ask("m-2", "x"), _ask("m-3", "x@kmaster")], recs, ROOTS, "kmaster")
    assert got == {"m-1": "contractmatch", "m-2": "shiftlead", "m-3": "shiftlead"}, "two hosts' x each by its address"
    keys = q.record_keys(recs, "kmaster")
    assert keys == {"x@node": ("node", "/home/k/contractmatch", ""), "x": ("", "/home/k/shiftlead", "")}


def test_a_home_record_is_keyed_bare_and_named_by_its_last_component():
    for host in ("kmaster", ""):
        recs = [_rec("h", "/home/k/elsewhere", host=host)]
        assert q.record_keys(recs, "kmaster") == {"h": ("", "/home/k/elsewhere", "")}
        assert q.asker_repos([_ask(sender="h")], recs, ROOTS, "kmaster") == {"m-1": "elsewhere"}
    # a home record's view dict (bare id, `host` the home's) takes the same fallback
    view = [{"id": "h", "repo": "/home/k/elsewhere", "host": "kmaster"}]
    assert q.asker_repos([_ask(sender="h")], view, ROOTS) == {"m-1": "elsewhere"}


def test_a_node_path_no_reading_holds_names_nothing():
    recs = [_rec("x", "/home/k/elsewhere", host="node")]
    assert q.asker_repos([_ask()], recs, ROOTS, "kmaster") == {}, "never by the name a node's path ends in"
    assert q.asker_repos([_ask()], [{"id": "x@node", "repo": "/home/k/elsewhere"}], ROOTS) == {}


def test_a_gone_node_sender_never_reads_the_homes_namesake():
    home_x = [_rec("x", "/home/k/shiftlead", host="kmaster", team="sl")]
    assert q.asker_repos([_ask()], home_x, ROOTS, "kmaster") == {}, "x@node gone: not the home's x"
    team = [*home_x, _rec("cm-1", "/home/k/contractmatch", host="node", team="cm")]
    assert q.asker_repos([_ask(team="cm")], team, ROOTS, "kmaster") == {"m-1": "contractmatch"}, "its team's repo"


def test_the_team_step_names_one_repo_and_never_several_or_none():
    def keyed(*recs):
        return q.record_keys(recs, "kmaster")

    named = {("", "/home/k/a"): "a", ("", "/home/k/b"): "b", ("node", "/home/k/a"): "a"}

    def name_of(h, root):
        return named.get((h, root), "")

    assert q.team_repos(keyed(_rec("w", "/home/k/a", team="t")), name_of) == {"t": "a"}
    two = keyed(_rec("w", "/home/k/a", team="t"), _rec("seat", "/home/k/b", team="t"))
    assert q.team_repos(two, name_of) == {}, "a seat in another repo's checkout: several, none named"
    assert q.team_repos(keyed(_rec("w", "/home/k/z", team="t")), name_of) == {}, "a root naming none is skipped"
    skip = keyed(_rec("w", "/home/k/a", team="t"), _rec("z", "/home/k/z", team="t"), _rec("n", "/home/k/b"))
    assert q.team_repos(skip, name_of) == {"t": "a"}, "an unnamed root, and a record with no team, count for none"
    gone = _ask(sender="ghost", team="t")
    assert q.mail_repo(gone, {}, name_of, {"t": "a"}) == "a"
    assert q.mail_repo(_ask(sender="ghost", team="u"), {}, name_of, {"t": "a"}) is None


def test_the_persons_own_item_reads_its_first_addressee():
    recs = [{"id": "x@node", "repo": "/home/k/contractmatch"}, {"id": "y", "repo": "/home/k/shiftlead"}]
    mine = {"id": "m-p", "from": "person", "to": ["x@node", "y"], "kind": "ask", "about": "TD-064"}
    assert q.asker_repos([mine], recs, ROOTS) == {"m-p": "contractmatch"}
    assert q.asker_repos([{**mine, "to": "y"}], recs, ROOTS) == {"m-p": "shiftlead"}, "`to` written as one address"


def test_an_orphan_stamps_host_and_repo_are_named_as_a_pair():
    seen = []

    def name_of(h, root):
        seen.append((h, root))
        return "cm" if (h, root) == ("node", "/p") else ""

    assert q.mail_repo(_ask(orphaned={"host": "node", "repo": "/p"}), {}, name_of, home="kmaster") == "cm"
    assert q.mail_repo(_ask(orphaned={"host": "kmaster", "repo": "/p"}), {}, name_of, home="kmaster") is None
    assert ("", "/p") in seen, "the home's host is written empty"


def test_no_repo_reads_only_qualified_refs():
    assert q.own_refs(["TD-064", "contractmatch#TD-070"], None) == ["contractmatch#TD-070"]
    assert q.first_ref("TD-64", "see contractmatch#TD-70", None) == "contractmatch#TD-070"
    assert q.first_ref("TD-64", "see TD-70", None) is None
    assert q.first_ref("TD-64", "", "cm") == "cm#TD-064"


def test_an_item_with_no_repo_draws_in_the_inbox_whatever_a_bare_key_holds():
    index = {
        "TD-064": ("shiftlead#TD-64", "shiftlead#TD-64"),
        q.KEPT + "TD-064": ("shiftlead#TD-64", "shiftlead#TD-64"),
        q.DESIGN_KEY + "TD-064": ("12", ""),
        "cm#TD-070": ("cm#TD-70", "cm#TD-70"),
    }
    ask = {"id": "m-1", "from": "x@node", "kind": "ask", "about": "TD-064", "text": "?"}
    assert item_home(ask, index, {}, True)["home"] == "inbox", "no open, kept or loose card from a bare ref"
    assert design_link(ask, index, {}) == {}, "and no design link"
    got = item_home({**ask, "text": "or cm#TD-70?"}, index, {}, True)
    assert got["on_card"] == "cm#TD-70", "a qualified ref still draws"
    assert q.mail_card("TD-064", "?", index, None, needs=True) is None


def test_the_queue_reading_takes_the_homes_host():
    recs = [_rec("x", "/home/k/contractmatch", host="node"), _rec("x", "/home/k/shiftlead", host="kmaster")]
    repos = {
        r: {"root": r, "name": n, "ledger": {"entries": [{"id": "TD-064", "title": "t", "priority": "medium"}]}}
        for n, r in ROOTS.items()
    }
    got = q.reading(repos, recs, q._aware("2026-11-07T13:00:00Z"), questions=[_ask(about="TD-064")], host="kmaster")
    assert "cards" in got  # the reading runs with the home's host; the keying itself is asker_repos' above
