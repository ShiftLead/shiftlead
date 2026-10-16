"""TD-789, design §4.4 *A held PR nobody asked is marked, never ordered*: the repo's held key, the
reading's per-head `held` read under `HELD_READS`, and `_red_prs`' `pr_orders.asked` and `unasked`."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import held, reports
from sessionorc.models import PERSON, MailEntry, Session
from sessionorc.store import RepoStore

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CORE = {"reader": "techlead", "held": ["src/core/**"]}


def _rec(sid, repo=None, state="idle", **kw):
    return Session(id=sid, name=sid, kind="interactive", adapter="shell", dir="/tmp", state=state, repo=repo, **kw)


def _ask(pr, sender, at=T0, mid=None, **kw):
    mid = mid or f"m-{sender}-{pr}-{at.minute}"
    return MailEntry(id=mid, from_=sender, to=["x"], at=at.isoformat(), kind="ask", text="read it", pr=pr, **kw)


# ── the key ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_the_key_is_the_repos_held_list_or_its_named_sets_union_else_the_live_records_review(tmp_path):
    root = str(tmp_path)
    reviewer = _rec("ao-g", repo=root, review=CORE)
    (tmp_path / ".shiftlead.yml").write_text('held: ["docs/briefs/**", "src/a/**"]\n')
    assert held.repo_key(root, [reviewer]) == ["docs/briefs/**", "src/a/**"]
    (tmp_path / ".shiftlead.yml").write_text("held: {core: [src/a/**], ui: [src/ui/**, src/a/**]}\n")
    assert held.repo_key(root, [reviewer]) == ["src/a/**", "src/ui/**"]
    # neither in the file: the union of the live records' `review` globs, chains included
    (tmp_path / ".shiftlead.yml").write_text("ledger: x.md\n")
    chain = {
        "chain": [
            {"stage": "ui", "reader": "ui-r", "held": ["src/ui/**"]},
            {"stage": "c", "reader": "t", "held": ["src/c/**"]},
        ]
    }
    gone = _rec("ao-x", repo=root, state="exited", review={"reader": "t", "held": ["gone/**"]})
    superseded = _rec("ao-y", repo=root, review={"reader": "t", "held": ["old/**"]}, superseded_by="ao-z")
    other = _rec("ao-o", repo=str(tmp_path / "other"), review={"reader": "t", "held": ["elsewhere/**"]})
    got = held.repo_key(root, [reviewer, _rec("ao-c", repo=root, review=chain), gone, superseded, other])
    assert got == ["src/c/**", "src/core/**", "src/ui/**"]
    # neither at all: an empty key, which reads nothing
    assert held.repo_key(root, [_rec("ao-p", repo=root)]) == []
    assert held.match(["src/a/x.py", "README.md"], ["src/a/**"]) == ["src/a/x.py"]


# ── the reading ──────────────────────────────────────────────────────────────────────────────────


def _pr(n, created, head, **kw):
    return {
        "number": n, "title": f"pr {n}", "url": f"https://x/{n}", "state": "OPEN",
        "createdAt": created.isoformat().replace("+00:00", "Z"), "headRefName": f"b{n}", "headRefOid": head,
        "author": {"login": "g"}, "isDraft": False, **kw,
    }  # fmt: skip


def _gh(monkeypatch, open_prs, files, reads, fail=()):
    def run(argv, **kw):
        if argv[1] == "api" and "/files" in argv[2]:
            n = int(argv[2].split("/")[-2])
            reads.append(n)
            if n in fail:
                return subprocess.CompletedProcess(argv, 1, "", "HTTP 502")
            return subprocess.CompletedProcess(argv, 0, "".join(f"{f}\n" for f in files[n]), "")
        if argv[1] == "api":
            data = {f.split("=", 1)[0]: {"issueCount": 0} for f in argv if "=repo:" in f}
            return subprocess.CompletedProcess(argv, 0, json.dumps({"data": data}), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps(open_prs if "open" in argv else []), "")

    monkeypatch.setattr(reports.subprocess, "run", run)


@pytest.mark.unit
def test_held_is_read_once_per_head_and_key_carried_through_old_and_a_failed_read_keeps_the_last_word(
    tmp_path, monkeypatch
):
    prs = [_pr(1, T0, "h1"), _pr(2, T0 + timedelta(minutes=1), "h2", isDraft=True)]
    prs.append(_pr(3, T0, "h3", headRefName="cadence-sync-1"))  # a sync candidate: never read for `held`
    files = {1: ["src/core/a.py", "README.md"], 2: ["README.md"], 3: ["docs/cadence-sync.lock"]}
    reads: list[int] = []
    _gh(monkeypatch, prs, files, reads)
    key = ["src/core/**"]
    first = reports.pr_reading(tmp_path, T0, held=key)
    by = {p["number"]: p for p in first["open"]}
    assert (by[1]["held"], by[1]["held_head"], by[1]["held_key"]) == (["src/core/a.py"], "h1", key)
    assert by[2]["held"] == [] and by[2]["draft"]  # a draft is read: marking it ready changes no head
    assert "held" not in by[3] and reads.count(3) == 1  # the sync read alone
    # the same heads and key: nothing read, the word carried
    reads.clear()
    second = reports.pr_reading(tmp_path, T0 + timedelta(minutes=5), old=first, held=key)
    assert reads == [] and {p["number"]: p.get("held") for p in second["open"]} == {
        1: ["src/core/a.py"],
        2: [],
        3: None,
    }
    # a changed key re-reads at the same head
    third = reports.pr_reading(tmp_path, T0 + timedelta(minutes=10), old=second, held=["README.md"])
    assert sorted(reads) == [1, 2] and third["open"][0]["held"] == ["README.md"]
    # a new head whose read fails keeps the last word, head and key with it
    reads.clear()
    prs[0]["headRefOid"] = "h9"
    _gh(monkeypatch, prs, files, reads, fail={1})
    fourth = reports.pr_reading(tmp_path, T0 + timedelta(minutes=15), old=third, held=["README.md"])
    one = {p["number"]: p for p in fourth["open"]}[1]
    assert reads == [1] and (one["held"], one["held_head"]) == (["README.md"], "h1")
    # no key (a repo whose readers wound down): nothing read, the last word kept
    reads.clear()
    fifth = reports.pr_reading(tmp_path, T0 + timedelta(minutes=20), old=fourth, held=[])
    assert reads == [] and {p["number"]: p.get("held_key") for p in fifth["open"]}[1] == ["README.md"]
    # an unread PR carries no `held`: never read, never judged
    fresh = reports.pr_reading(tmp_path, T0, held=None)
    assert all("held" not in p for p in fresh["open"])


@pytest.mark.unit
def test_held_reads_are_capped_a_pass_oldest_first(tmp_path, monkeypatch):
    prs = [_pr(n, T0 + timedelta(minutes=n), f"h{n}") for n in range(1, 8)]
    files = {n: ["src/core/a.py"] for n in range(1, 8)}
    reads: list[int] = []
    _gh(monkeypatch, prs, files, reads)
    first = reports.pr_reading(tmp_path, T0, held=["src/core/**"])
    assert reads == [1, 2, 3, 4, 5] and held.HELD_READS == 5
    # the next pass reads the two never read and the one read at another head, oldest first; the rest stand
    reads.clear()
    prs[3]["headRefOid"] = "h4b"
    second = reports.pr_reading(tmp_path, T0 + timedelta(minutes=5), old=first, held=["src/core/**"])
    assert reads == [4, 6, 7] and all(p["held"] == ["src/core/a.py"] for p in second["open"])


# ── asked and unasked ────────────────────────────────────────────────────────────────────────────


def _repos(*roots, remote=None):
    return {r: {"name": r, "root": r, "remote": remote or f"git@github.com:o/{r}.git"} for r in roots}


@pytest.mark.unit
def test_asked_reads_the_seats_and_the_persons_mail_by_the_senders_repo():
    repos = _repos("/a", "/b")
    lead = _rec("ao-tl", role="techlead", team="t")
    auditor = _rec("ao-au", seat={"name": "audit"}, team="t")
    plain = _rec("ao-pl", team="t")  # no seat: its inbox is not read
    author_a = _rec("ao-ga", repo="/a", team="t")
    lead.inbox = [_ask(12, "ao-ga"), _ask(12, "ao-ga", at=T0 + timedelta(hours=1), mid="m-later")]
    auditor.inbox = [_ask(13, "ao-ga", at=T0 + timedelta(minutes=5))]
    plain.inbox = [_ask(14, "ao-ga")]
    graph = {s.id: s for s in (lead, auditor, plain, author_a)}
    got = held.asks(graph, [], repos)
    # an ask for #12 from a session of repo A leaves repo B's #12 unasked; the first ask wins
    assert got == {
        "/a": {
            "12": {"at": T0.isoformat(), "to": "ao-tl"},
            "13": {"at": (T0 + timedelta(minutes=5)).isoformat(), "to": "ao-au"},
        }
    }
    # a forgotten sender, or a node's session: every repo the seat's team's live records name
    lead.inbox = [_ask(20, "ao-forgotten"), _ask(21, "ao-far@node")]
    graph["ao-far@node"] = _rec("ao-far", repo="/node/checkout", team="t")
    got = held.asks(graph, [], repos)
    assert set(got) == {"/a"} and set(got["/a"]) == {"13", "20", "21"}
    # in person_inbox: the sender's `team` stamp's repos, else every repo
    lead.inbox, auditor.inbox = [], []
    stamped = _ask(30, PERSON + "-nobody", team="t")
    unstamped = _ask(31, "ao-gone")
    got = held.asks(graph, [stamped, unstamped], repos)
    assert got["/a"]["30"] == {"at": T0.isoformat(), "to": PERSON} and "30" not in got.get("/b", {})
    assert got["/a"]["31"]["to"] == PERSON and got["/b"]["31"]["to"] == PERSON
    # a team that works two repos: the person's ask counts for each
    graph["ao-gb"] = _rec("ao-gb", repo="/b", team="t")
    got = held.asks(graph, [stamped], repos)
    assert got["/a"]["30"] == got["/b"]["30"] == {"at": T0.isoformat(), "to": PERSON}
    del graph["ao-gb"]
    # two checkouts of one remote both count it
    two = _repos("/a", "/a2", remote="git@github.com:o/a.git")
    lead.inbox = [_ask(40, "ao-ga")]
    assert set(held.asks(graph, [], two)) == {"/a", "/a2"}


@pytest.mark.unit
def test_asked_is_the_earliest_ask_by_at_whatever_the_order_the_mail_lists_it_in():
    """TD-793: the first ask by `at`, not by the graph's or an inbox's order — a later ask of the same
    PR listed first, to another seat, never wins."""
    repos = _repos("/a")
    lead = _rec("ao-tl", role="techlead", team="t")  # read first: the graph lists it first
    auditor = _rec("ao-au", seat={"name": "audit"}, team="t")
    author = _rec("ao-ga", repo="/a", team="t")
    later, earlier = T0 + timedelta(hours=2), T0 + timedelta(minutes=30)
    lead.inbox = [_ask(12, "ao-ga", at=later, mid="m-late"), _ask(12, "ao-ga", at=T0 + timedelta(hours=1))]
    auditor.inbox = [_ask(12, "ao-ga", at=earlier, mid="m-early")]
    graph = {s.id: s for s in (lead, auditor, author)}
    assert held.asks(graph, [], repos) == {"/a": {"12": {"at": earlier.isoformat(), "to": "ao-au"}}}
    # the person's inbox, read last, still wins with the earliest
    person = _ask(12, "ao-ga", at=T0, mid="m-person")
    assert held.asks(graph, [person], repos) == {"/a": {"12": {"at": T0.isoformat(), "to": PERSON}}}


@pytest.mark.unit
def test_unasked_needs_held_no_ask_a_green_or_unchecked_ready_pr_and_a_reader():
    base = {"held": ["src/core/a.py"], "checks": "green"}
    prs = [
        {"number": 1, **base},
        {"number": 2, **base, "checks": "none"},
        {"number": 3, **base, "draft": True},
        {"number": 4, **base, "sync": True},
        {"number": 5, **base, "conflicting": True},
        {"number": 6, **base, "checks": "red"},
        {"number": 7, **base, "checks": "pending"},
        {"number": 8, **base, "checks": "not_run"},
        {"number": 9, **base, "held": []},
        {"number": 10, "checks": "green"},  # never read
        {"number": 11, **base},
    ]
    assert held.unasked(prs, {"11": {"at": "x", "to": "ao-tl"}}, True) == [1, 2]
    assert held.unasked(prs, {}, False) == []  # nobody to ask
    repos = _repos("/a")
    reviewer = _rec("ao-g", repo="/a", review=CORE)
    assert held.has_reader("/a", {"ao-g": reviewer}, repos)
    for gone in (
        _rec("ao-g", repo="/a", review=CORE, state="exited"),
        _rec("ao-g", repo="/a", review=CORE, superseded_by="z"),
    ):
        assert not held.has_reader("/a", {"ao-g": gone}, repos)


async def test_the_home_keeps_asked_past_the_mails_prune_and_a_reload_and_lists_unasked(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    author = _rec("ao-g", repo=root, review=CORE, team="t", host=agent.host)
    lead = _rec("ao-tl", role="techlead", team="t", host=agent.host)
    lead.inbox = [_ask(12, "ao-g")]
    agent.sessions.update({author.id: author, lead.id: lead})
    row = {"held": ["src/core/a.py"], "held_head": "h", "held_key": ["src/core/**"], "checks": "green"}
    prs = [{"number": 12, **row}, {"number": 13, **row}, {"number": 14, **row, "draft": True}]
    agent._repos[root] = {"name": "repo", "root": root, "remote": "", "prs": {"open": prs}}
    await agent._red_prs(T0)
    po = agent._repos[root]["pr_orders"]
    assert po["asked"] == {"12": {"at": T0.isoformat(), "to": "ao-tl"}} and po["unasked"] == [13]
    # the mail pruned, the home restarted: the reading keeps the ask
    lead.inbox = []
    agent._repos = RepoStore(agent.repos_store.path).load()
    await agent._red_prs(T0 + timedelta(hours=13))
    assert agent._repos[root]["pr_orders"]["asked"] == {"12": {"at": T0.isoformat(), "to": "ao-tl"}}
    # the PR closes: its ask is pruned
    agent._repos[root]["prs"]["open"] = [{"number": 13, **row}]
    await agent._red_prs(T0 + timedelta(hours=14))
    assert agent._repos[root]["pr_orders"]["asked"] == {} and agent._repos[root]["pr_orders"]["unasked"] == [13]
    # the team wound down: its held kept, nothing unasked
    author.state = "exited"
    await agent._red_prs(T0 + timedelta(hours=15))
    assert agent._repos[root]["pr_orders"]["unasked"] == [] and agent._repos[root]["prs"]["open"][0]["held"]


async def test_a_later_ask_on_a_later_pass_never_moves_the_kept_first_one(agent, tmp_path):
    """TD-793: the first ask, kept, wins over a fresh ask of the same PR to another seat once the first
    is pruned from the mail — `at` and `to` never drift pass to pass."""
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    author = _rec("ao-g", repo=root, review=CORE, team="t", host=agent.host)
    lead = _rec("ao-tl", role="techlead", team="t", host=agent.host)
    auditor = _rec("ao-au", seat={"name": "audit"}, team="t", host=agent.host)
    lead.inbox = [_ask(12, "ao-g")]
    agent.sessions.update({s.id: s for s in (author, lead, auditor)})
    row = {"held": ["src/core/a.py"], "held_head": "h", "held_key": ["src/core/**"], "checks": "green"}
    agent._repos[root] = {"name": "repo", "root": root, "remote": "", "prs": {"open": [{"number": 12, **row}]}}
    await agent._red_prs(T0)
    first = {"12": {"at": T0.isoformat(), "to": "ao-tl"}}
    assert agent._repos[root]["pr_orders"]["asked"] == first
    lead.inbox, auditor.inbox = [], [_ask(12, "ao-g", at=T0 + timedelta(hours=3), mid="m-again")]
    await agent._red_prs(T0 + timedelta(hours=3))
    assert agent._repos[root]["pr_orders"]["asked"] == first


async def test_the_tick_passes_each_remotes_union_of_keys_to_the_read(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    agent.sessions["ao-a"] = _rec("ao-a", repo=a, review={"reader": "t", "held": ["src/a/**"]}, host=agent.host)
    agent.sessions["ao-b"] = _rec("ao-b", repo=b, review={"reader": "t", "held": ["src/b/**"]}, host=agent.host)
    agent._repos = {a: {"remote": "r1"}, b: {"remote": "r1"}}
    assert agent._held_keys([a, b]) == {a: ["src/a/**", "src/b/**"], b: ["src/a/**", "src/b/**"]}
    agent._repos = {a: {"remote": "r1"}, b: {"remote": "r2"}}
    assert agent._held_keys([a, b]) == {a: ["src/a/**"], b: ["src/b/**"]}


async def test_asked_and_unasked_are_kept_across_a_re_read_of_the_rows(agent, tmp_path, monkeypatch):
    """The rows are rebuilt at each read; `pr_orders` is `_red_prs`' own and carried through it."""
    from conftest import park_ticks

    from sessionorc import hosts

    await park_ticks(agent)
    root = tmp_path / "repo"
    root.mkdir()
    reg = hosts.default_repos_registry()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(f"{root}\n")
    agent.sessions["ao-g"] = _rec("ao-g", repo=str(root), review=CORE, host=agent.host)
    lead = _rec("ao-tl", role="techlead", host=agent.host)
    lead.inbox = [_ask(12, "ao-g")]
    agent.sessions[lead.id] = lead
    row = {"held": ["src/core/a.py"], "held_head": "h", "held_key": ["src/core/**"], "checks": "green"}
    keys = []

    def read(d, now, old=None, held=None, **kw):
        keys.append(held)
        return {"open": [{"number": 12, **row}, {"number": 13, **row}], "at": now.isoformat()}

    monkeypatch.setattr(reports, "pr_reading", read)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    assert keys == [["src/core/**"]]
    await agent._red_prs(T0)
    want = {"asked": {"12": {"at": T0.isoformat(), "to": "ao-tl"}}, "unasked": [13]}
    po = agent._repos[str(root)]["pr_orders"]
    assert {k: po[k] for k in want} == want
    lead.inbox = []
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()  # the rows read again, the mail pruned meanwhile
    po = agent._repos[str(root)]["pr_orders"]
    assert {k: po[k] for k in want} == want


def test_two_checkouts_of_one_remote_read_at_the_first_key_then_the_union(tmp_path, monkeypatch):
    """§4.4 *The key's scope*: on a first pass no `remote` is read yet, so the second checkout takes
    the first's reading at the first's key; the next pass reads every root of the remote at the union."""
    from sessionorc.agent_tick import TickMixin

    roots = []
    for name in ("a", "b"):
        r = tmp_path / name
        r.mkdir()
        for argv in (["init", "-q", "-b", "main"], ["remote", "add", "origin", "git@github.com:o/r.git"]):
            subprocess.run(["git", "-C", str(r), *argv], check=True, capture_output=True)
        roots.append(str(r))
    a, b = roots
    keys = []

    def read(d, now, old=None, held=None, **kw):
        keys.append((d, held))
        return {"open": [], "at": now.isoformat()}

    monkeypatch.setattr(reports, "pr_reading", read)
    first = TickMixin._read_repos(roots, {}, set(roots), keys={a: ["src/a/**"], b: ["src/b/**"]})
    assert keys == [(a, ["src/a/**"])] and first[b]["prs"] == first[a]["prs"]
    assert first[a]["remote"] == first[b]["remote"] == "git@github.com:o/r.git"

    class Home:
        _repos = first
        _graph = staticmethod(
            lambda: {
                "ao-a": _rec("ao-a", repo=a, review={"reader": "t", "held": ["src/a/**"]}),
                "ao-b": _rec("ao-b", repo=b, review={"reader": "t", "held": ["src/b/**"]}),
            }
        )

    union = TickMixin._held_keys(Home(), roots)
    keys.clear()
    TickMixin._read_repos(roots, first, set(roots), keys=union)
    assert keys == [(a, ["src/a/**", "src/b/**"])]
