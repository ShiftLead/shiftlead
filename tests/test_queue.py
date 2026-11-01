"""TD-769 slice 2, design §4.4 *The Queue: cards, and the rank that orders them*: `sessionorc.queue`
derives the cards — connected components of the open ledgers' `Blocked by:` ids across repos — their
top entry, rows, row states, the ledger's part of each card's status, keys and order, the completed
cards of the archive and the passed-over flags, from the home's readings alone."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import ledger, queue
from sessionorc.models import ProgressEntry, Session

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TODAY = NOW.date().isoformat()


def _entry(n: int, title: str, **fields: str) -> str:
    head = "".join(f"**{k.replace('_', ' ').capitalize()}:** {v}\n" for k, v in fields.items())
    return f"## TD-{n:03d}: {title}\n\n{head}\n"


def _repo(tmp: Path, name: str, entries: list[str], archive: list[str] = ()) -> tuple[str, dict[str, Any]]:
    root = tmp / name
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text("# Technical Debt\n\n" + "".join(entries), encoding="utf-8")
    (root / "docs" / "technical_debt_archive.md").write_text("# Archive\n\n" + "".join(archive), encoding="utf-8")
    led = ledger.reading(root, NOW, with_history=False)
    return str(root), {"name": name, "root": str(root), "remote": f"git@github.com:o/{name}.git", "ledger": led,
                       "prs": {"open": []}}  # fmt: skip


def _cards(repos: dict[str, dict[str, Any]], records: list[Session] = (), **kw: Any) -> dict[str, Any]:
    return queue.reading(repos, list(records), NOW, **kw)


def _by_id(q: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in q["cards"]}


def _rec(rid: str, repo: str, *refs: str, state: str = "working", lane: list[str] = (), team: str = "t") -> Session:
    s = Session(id=rid, name=rid, kind="interactive", adapter="shell", dir=repo, repo=repo, state=state)  # type: ignore[arg-type]
    s.progress = [ProgressEntry(ref=r, at=(NOW - timedelta(hours=1)).isoformat()) for r in refs]
    s.lane, s.team, s.unattended = list(lane), team, True
    return s


def test_a_card_is_a_component_across_two_repos_in_both_directions(tmp_path):
    a, ra = _repo(tmp_path, "alpha", [_entry(1, "a design", Priority="Medium", Kind="design-first"),
                                      _entry(2, "its build", Priority="Medium", Blocked_by="TD-001, beta#TD-005"),
                                      _entry(3, "alone", Priority="Low")])  # fmt: skip
    b, rb = _repo(tmp_path, "beta", [_entry(5, "the other repo's step", Priority="High"),
                                     _entry(6, "names alpha", Priority="Low", Blocked_by="alpha#TD-003")])  # fmt: skip
    cards = _by_id(_cards({a: ra, b: rb}))
    one = cards["alpha#TD-001"]
    assert sorted([one["top"]["qid"], *(r["qid"] for r in one["rows"])]) == [
        "alpha#TD-001",
        "alpha#TD-002",
        "beta#TD-005",
    ]
    assert one["repos"] == ["alpha", "beta"] and one["of"] == 3 and one["done"] == 0
    # named from the other side: beta's TD-006 joins alpha's TD-003
    two = next(c for c in cards.values() if "alpha#TD-003" in [c["top"]["qid"], *(r["qid"] for r in c["rows"])])
    assert {two["top"]["qid"], *(r["qid"] for r in two["rows"])} == {"alpha#TD-003", "beta#TD-006"}
    # a card's key is its best implicit key: the High member's
    assert one["key"] == "1|0|000005|beta" and not one["lined"]


def test_the_top_entry_a_design_naming_its_builds_no_design_and_a_tie(tmp_path):
    root, r = _repo(tmp_path, "r", [
        _entry(10, "a design that lists its builds", Priority="Low", Kind="design-first", Blocked_by="TD-011"),
        _entry(11, "its build", Priority="High", Blocked_by="TD-010"),
        _entry(20, "a prerequisite", Priority="Low"),
        _entry(21, "after it", Priority="High", Blocked_by="TD-020"),
        _entry(30, "one of a tie", Priority="Medium"),
        _entry(31, "the other", Priority="High", Blocked_by="TD-032"),
        _entry(32, "a third", Priority="High"),
        _entry(33, "the tie's second", Priority="Medium", Blocked_by="TD-031"),
    ])  # fmt: skip
    tops = {c["top"]["id"] for c in _cards({root: r})["cards"]}
    assert "TD-010" in tops  # a design-first is the top entry even when it names its own builds
    assert "TD-020" in tops  # no design: the entry with no open blocker in the card
    assert "TD-032" in tops  # the one entry nothing in its card blocks


def test_a_blocker_is_a_word_on_its_row_never_an_edge_of_the_tree(tmp_path):
    """TD-1130 (§4.4 *Rows*): with no `Part of:` line every row is loose, at the card's left edge, in the
    pick order of the card, and what it waits on is its `after`, its open blockers by key."""
    root, r = _repo(tmp_path, "r", [
        _entry(1, "top", Priority="High"),
        _entry(2, "left", Priority="Low", Blocked_by="TD-001"),
        _entry(3, "right", Priority="Medium", Blocked_by="TD-001"),
        _entry(4, "after both", Priority="Medium", Blocked_by="TD-002, TD-003"),
    ])  # fmt: skip
    card = _cards({root: r})["cards"][0]
    rows = {x["id"]: x for x in card["rows"]}
    assert card["top"]["id"] == "TD-001" and [x["id"] for x in card["rows"]] == ["TD-003", "TD-002", "TD-004"]
    assert {(x["parent"], x["depth"]) for x in card["rows"]} == {(None, 1)}
    assert rows["TD-004"]["after"] == ["r#TD-003", "r#TD-002"] and rows["TD-002"]["after"] == ["r#TD-001"]
    assert rows["TD-004"]["state"] == "waiting" and card["top"]["after"] == []
    # the pick order within a card: after every member it is blocked by, then by key
    assert card["order"] == ["r#TD-001", "r#TD-003", "r#TD-002", "r#TD-004"]


def test_archived_rows_are_one_hop_and_done_with_their_pr(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(5, "open", Priority="Medium", Blocked_by="TD-002"),
                                    _entry(6, "named by an archived one", Priority="Low")],
                    archive=[_entry(1, "two hops away", Resolved=f"{TODAY} — done (PR #11)."),
                             _entry(2, "one hop, named", Blocked_by="TD-001", Resolved=f"{TODAY} — done (PR #12)."),
                             _entry(3, "one hop, naming", Blocked_by="TD-006",
                                    Resolved=f"{TODAY} — (PR #13).")])  # fmt: skip
    cards = {c["top"]["id"]: c for c in _cards({root: r})["cards"]}
    assert [(x["id"], x["state"], x["archived"]) for x in cards["TD-005"]["rows"]] == [("TD-002", "done #12", True)]
    assert cards["TD-005"]["done"] == 1 and cards["TD-005"]["of"] == 2
    assert [x["id"] for x in cards["TD-006"]["rows"]] == ["TD-003"]
    # TD-001 is named by an archived row, not by an open one: in no card, and no completed card either
    # (its component touches an open entry)
    q = _cards({root: r})
    assert all("r#TD-001" not in c["ids"] for c in q["completed"])


def test_completed_cards_are_the_archives_untouched_components_in_the_window(tmp_path):
    old = (NOW - timedelta(days=40)).date().isoformat()
    root, r = _repo(tmp_path, "r", [_entry(9, "open", Priority="Low")],
                    archive=[_entry(1, "a design", Resolved=f"{TODAY} — designed (PR #21)."),
                             _entry(2, "its build", Blocked_by="TD-001", Resolved=f"{TODAY} — built (PR #22)."),
                             _entry(3, "long ago", Resolved=f"{old} — (PR #3).")])  # fmt: skip
    done = _cards({root: r})["completed"]
    assert [(c["id"], sorted(c["ids"]), c["pr"]) for c in done] == [("r#TD-001", ["r#TD-001", "r#TD-002"], 22)]


def test_each_row_state_word(tmp_path):
    root, r = _repo(tmp_path, "r", [
        _entry(1, "an old clock mark", Priority="High"),
        _entry(2, "in review", Priority="High"),
        _entry(3, "conflicting", Priority="High"),
        _entry(4, "claimed", Priority="High"),
        _entry(5, "settling", Priority="High"),
        _entry(6, "waits until", Priority="High"),
        _entry(7, "waits on an event", Priority="High"),
        _entry(8, "after another", Priority="High", Blocked_by="TD-009"),
        _entry(9, "ready", Priority="High"),
        _entry(10, "the person's", Priority="High", Owner="paul"),
        _entry(11, "a decision of the person's", Priority="High", Blocked_by="decision (paul) — when I say"),
        _entry(12, "stalled holder", Priority="High"),
        _entry(13, "red nobody holds", Priority="High"),
    ])  # fmt: skip
    ents = {e["id"]: e for e in r["ledger"]["entries"]}
    ents["TD-001"]["held"] = {"at": NOW.isoformat()}  # a mark the clock no longer writes: read as nothing (TD-1297)
    ents["TD-005"]["settling"] = {"until": NOW.isoformat()}
    ents["TD-006"]["waiting"] = {"on": "until", "until": "2026-10-21"}
    ents["TD-007"]["waiting"] = {"on": "event", "until": ""}
    long_red = (NOW - queue.QUEUE_STALL_AFTER - timedelta(minutes=1)).isoformat()
    r["prs"]["open"] = [
        {"number": 102, "branch": "td002-review", "checks": "green", "conflicting": False},
        {"number": 103, "branch": "td003-fix", "checks": "red", "failing": ["test"], "conflicting": True},
        {"number": 113, "branch": "td013-red", "checks": "red", "failing": ["test"], "red_since": long_red},
    ]
    recs = [_rec("w1", root, "TD-004"), _rec("w2", root, "TD-012", state="idle"), _rec("w3", root, "TD-003")]
    rows = {}
    for c in _cards({root: r}, recs)["cards"]:
        for x in [c["top"], *c["rows"]]:
            rows[x["id"]] = x
    got = {t: (x["state"], x["needs"]) for t, x in rows.items()}
    assert got == {
        "TD-001": ("ready", None),
        "TD-002": ("in review #102", None),
        "TD-003": ("#103 conflicting · being fixed", None),
        "TD-004": ("held by w1", None),
        "TD-005": ("settling", None),
        "TD-006": ("waits until 2026-10-21", None),
        "TD-007": ("waits on an event", None),
        "TD-008": ("waiting", None),  # its blocker is its `after`, not its word (TD-1130)
        "TD-009": ("ready", None),
        "TD-010": ("", "owner"),
        "TD-011": ("", "decision"),
        "TD-012": ("stalled", None),
        "TD-013": ("stalled", None),
    }
    assert rows["TD-004"]["holder"] == {"id": "w1", "name": "w1", "state": "working"}
    # an idle holder that waits on a question is not stalled
    again = _cards({root: r}, recs, waiting={"w2"})["cards"]
    assert next(c for c in again if c["top"]["id"] == "TD-012")["top"]["state"] == "held by w2"


def test_the_cards_status_by_need_and_a_designers_decision_item_reads_blocked(tmp_path):
    root, r = _repo(tmp_path, "r", [
        _entry(1, "the person's, beside a stalled one", Priority="High", Owner="paul"),
        _entry(2, "stalled", Priority="High", Blocked_by="TD-001"),
        _entry(3, "someone else's decision", Priority="High", Blocked_by="decision (techlead)"),
        _entry(4, "waits", Priority="High", Waits="event — a thing"),
        _entry(5, "after it", Priority="High", Blocked_by="TD-004"),
        _entry(6, "the designer's decision", Priority="High", Kind="build", Blocked_by="decision (designer)"),
        _entry(7, "an unknown id", Priority="High", Blocked_by="TD-999"),
    ])  # fmt: skip
    ents = {e["id"]: e for e in r["ledger"]["entries"]}
    ents["TD-004"]["waiting"] = {"on": "event", "until": ""}
    status = {
        c["top"]["id"]: c["status"] for c in _cards({root: r}, [_rec("w", root, "TD-002", state="idle")])["cards"]
    }
    # a decision owed to the designer is `Kind: design-first`: a `decision (designer)` item is past reach (TD-1297)
    assert status == {"TD-001": "needs you", "TD-003": "blocked", "TD-004": "waiting", "TD-006": "blocked",
                      "TD-007": "blocked"}  # fmt: skip
    # without the person's member, the stalled one leads
    ents["TD-001"]["owner"] = "grinder"
    status = {
        c["top"]["id"]: c["status"] for c in _cards({root: r}, [_rec("w", root, "TD-002", state="idle")])["cards"]
    }
    assert status["TD-001"] == "stalled"


def test_in_progress_first_up_next_numbered_in_key_order(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "low", Priority="Low"), _entry(2, "high", Priority="High"),
                                    _entry(3, "medium, claimed", Priority="Medium")])  # fmt: skip
    q = _cards({root: r}, [_rec("w", root, "TD-003")])
    assert [(c["id"], c["group"], c["place"]) for c in q["cards"]] == [
        ("r#TD-003", "in_progress", None), ("r#TD-002", "up_next", 1), ("r#TD-001", "up_next", 2)]  # fmt: skip


def test_a_lined_card_keeps_its_key_and_a_member_takes_it(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "high", Priority="High"), _entry(2, "low top", Priority="Low"),
                                    _entry(3, "a newcomer", Priority="High", Blocked_by="TD-002")])  # fmt: skip
    (Path(root) / "docs" / "technical_debt_rank.yml").write_text("TD-002: 0\n", encoding="utf-8")
    r["ledger"] = ledger.reading(root, NOW, with_history=False)
    q = _cards({root: r})
    assert [c["id"] for c in q["cards"]] == ["r#TD-002", "r#TD-001"]
    assert q["cards"][0]["key"] == "0" and q["cards"][0]["lined"]


def test_a_worker_holding_a_lower_card_flags_the_card_it_passed_over(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "high", Priority="High", Owner="grinder"),
                                    _entry(2, "low", Priority="Low", Owner="grinder"),
                                    _entry(3, "high, settling", Priority="High", Owner="grinder")])  # fmt: skip
    {e["id"]: e for e in r["ledger"]["entries"]}["TD-003"]["settling"] = {"until": NOW.isoformat()}
    w = _rec("w", root, "TD-002", lane=["free-pick"])
    doing = {"t": [{"id": "w", "text": "TD-002 (Low; TD-001 is too big)", "at": NOW.isoformat()}]}
    cards = _by_id(_cards({root: r}, [w], doing=doing))
    assert cards["r#TD-001"]["passed_over"] == [
        {"by": "w", "name": "w", "holding": "r#TD-002", "ids": ["r#TD-001"], "why": "TD-002 (Low; TD-001 is too big)"}
    ]
    assert cards["r#TD-003"]["passed_over"] == []  # a settling entry never triggers it


def test_a_claim_on_no_open_entry_is_other_work(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "x", Priority="Low")])
    q = _cards({root: r}, [_rec("w", root, "board:abc123")])
    assert q["other_work"] == [
        {"ref": "board:abc123", "pr": None, "holder": {"id": "w", "name": "w", "state": "working"}}
    ]


def test_the_archive_is_cached_by_its_blob(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(_entry(1, "x"), encoding="utf-8")
    first = queue.archive_entries(p)
    assert queue.archive_entries(p) is first
    p.write_text(_entry(1, "x") + _entry(2, "y"), encoding="utf-8")
    assert [e["id"] for e in queue.archive_entries(p)] == ["TD-001", "TD-002"]
    assert queue.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


async def test_the_home_serves_the_reading_and_pushes_it_when_it_changes(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root, r = _repo(tmp_path, "r", [_entry(1, "x", Priority="Low"), _entry(2, "y", Priority="High")])
    agent._repos = {root: r}
    sent: list[dict[str, Any]] = []

    async def push(ev: dict[str, Any]) -> None:
        sent.append(ev)

    monkeypatch.setattr(agent, "_broadcast", push)
    assert (await agent.rpc_queue())["cards"] == []  # before its first pass
    await agent._queue_pass(NOW)
    got = await agent.rpc_queue()
    assert [c["id"] for c in got["cards"]] == ["r#TD-002", "r#TD-001"]
    assert [e["event"] for e in sent] == ["queue"] and sent[0]["queue"] == got
    await agent._queue_pass(NOW + timedelta(seconds=2))  # nothing changed but `at`: no push
    assert len(sent) == 1
    assert "completed" not in await agent.rpc_queue(omit=["completed"])


def test_review_findings_designer_item_archived_claim_no_hold_one_flag(tmp_path):
    """#1933's review: a claim on an archived id is other work; one flag per worker. Since TD-1297 a
    `decision (designer)` item beside an open id is past reach, so its card is blocked, and a row carries
    no `held`: the person's entry reads its need."""
    root, r = _repo(tmp_path, "r", [
        _entry(1, "open", Priority="High", Owner="grinder", Waits="event — a thing"),
        _entry(2, "after it and the designer", Priority="High", Blocked_by="TD-001, decision (designer)"),
        _entry(3, "the person's, held", Priority="High", Owner="paul"),
        _entry(4, "unclaimed, high", Priority="High", Owner="grinder"),
        _entry(5, "low", Priority="Low", Owner="grinder"),
        _entry(6, "low too", Priority="Low", Owner="grinder", Blocked_by="TD-005"),
    ], archive=[_entry(9, "archived", Resolved=f"{TODAY} — (PR #9).")])  # fmt: skip
    ents = {e["id"]: e for e in r["ledger"]["entries"]}
    ents["TD-001"]["waiting"] = {"on": "event", "until": ""}
    w = _rec("w", root, "TD-005", "TD-006", "TD-009", lane=["free-pick"])
    q = _cards({root: r}, [w])
    cards = _by_id(q)
    assert cards["r#TD-001"]["status"] == "blocked"
    assert (cards["r#TD-003"]["top"]["state"], cards["r#TD-003"]["top"]["needs"]) == ("", "owner")
    assert "held" not in cards["r#TD-003"]["top"] and "held" not in cards["r#TD-004"]["top"]
    assert [f["by"] for f in cards["r#TD-004"]["passed_over"]] == ["w"]
    assert [o["ref"] for o in q["other_work"]] == ["TD-009"]


def test_a_resolved_line_at_the_foot_of_an_archived_entry_is_read(tmp_path):
    # TD-771: most archived entries write `**Resolved:**` last, under the header block, where ledgerboard's
    # fields do not reach — the row's PR, its date and its text are still read
    foot = (
        "## TD-002: done last week\n\n**Priority:** High\n**Blocked by:** TD-009\n\n**Why:** a step.\n\n"
        "**Resolved:** 2026-10-15 (grinder, #812) — what was done.\n\n"
    )
    alone = "## TD-003: a card of its own\n\n**Priority:** Low\n\n**Resolved:** 2026-10-14 (grinder, #800) — built.\n"
    root, r = _repo(tmp_path, "r", [_entry(9, "open", Priority="Low", Blocked_by="TD-002")], archive=[foot, alone])
    q = _cards({root: r})
    row = q["cards"][0]["rows"][0]
    assert (row["state"], row["pr"], row["closed"]) == ("done #812", 812, "2026-10-15")
    assert row["resolved"] == "2026-10-15 (grinder, #812) — what was done."
    (done,) = q["completed"]
    assert (done["id"], done["pr"], done["at"]) == ("r#TD-003", 800, "2026-10-14")
    (e,) = done["entries"]
    assert (e["qid"], e["title"], e["priority"]) == ("r#TD-003", "a card of its own", "low")
    assert (e["closed"], e["pr"]) == ("2026-10-14", 800)
    assert e["resolved"] == "2026-10-14 (grinder, #800) — built."


def test_an_archived_entrys_close_is_the_commits_time_where_the_reading_holds_it(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(9, "open", Priority="Low")],
                    archive=[_entry(1, "closed today", Resolved=f"{TODAY} — done (PR #5).")])  # fmt: skip
    r["completed"] = [{"id": "TD-001", "closed": f"{TODAY}T09:30:00+00:00", "pr": 5}]
    (done,) = _cards({root: r})["completed"]
    assert done["at"] == f"{TODAY}T09:30:00+00:00" and done["entries"][0]["closed"] == done["at"]


def test_a_completed_cards_entries_are_ordered_by_instant_a_bare_date_its_days_end(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(9, "open", Priority="Low")],
                    archive=[_entry(1, "a commit's time", Resolved=f"{TODAY} — (PR #5)."),
                             _entry(2, "a bare date", Blocked_by="TD-001", Resolved=f"{TODAY} (PR #6).")])  # fmt: skip
    r["completed"] = [{"id": "TD-001", "closed": f"{TODAY}T09:30:00-06:00", "pr": 5}]
    (done,) = _cards({root: r})["completed"]
    assert [e["id"] for e in done["entries"]] == ["TD-002", "TD-001"] and done["at"] == TODAY


def test_a_td748_shaped_card_hangs_parts_under_their_parent_and_never_tops_an_archived_one(tmp_path):
    """TD-1130's Done when (§4.4 *The top entry*, *Rows*, *A row's state*, the within-card order): a design, its
    parts, a trial, a part blocked from another group, a cross-repo blocker, an archived part and an archived
    parent with an open part. Indentation is `Part of:` alone; a blocker is the row's `after`; an open part
    makes its parent *waiting*; the top entry is the open root parent, never the archived one."""
    _, other = _repo(tmp_path, "db", [_entry(7, "another repo's", Priority="Medium")])
    root, r = _repo(tmp_path, "r", [
        _entry(40, "the design", Priority="Medium", Kind="design-first"),
        _entry(41, "part one", Priority="High", Part_of="TD-040"),
        _entry(42, "part two, after part one", Priority="High", Part_of="TD-040", Blocked_by="TD-041"),
        _entry(43, "a trial, after the design", Priority="Low", Blocked_by="TD-040"),
        _entry(44, "a part of the trial, after part two", Priority="Medium", Part_of="TD-043",
               Blocked_by="TD-042, db#TD-7"),
        _entry(45, "an open part of a finished parent", Priority="Low", Part_of="TD-030"),
    ], archive=[
        _entry(39, "a done part", Part_of="TD-040", Resolved=f"{TODAY} — done (PR #39)."),
        _entry(30, "a finished parent", Kind="design-first", Resolved=f"{TODAY} — (PR #30)."),
    ])  # fmt: skip
    q = _cards({root: r, str(tmp_path / "db"): other})
    card = next(c for c in q["cards"] if c["top"]["id"] == "TD-040")
    assert card["top"]["state"] == "waiting" and card["top"]["parent"] is None, "it waits on its open parts"
    got = [(x["id"], x["parent"], x["depth"], x["state"], x["after"]) for x in card["rows"]]
    # the top entry's group first (open parts in pick order, then its done part), then each loose group in
    # the pick order of its first open member: the other repo's blocker, then the trial with its part
    assert got == [
        ("TD-041", "r#TD-040", 1, "ready", []),
        ("TD-042", "r#TD-040", 1, "waiting", ["r#TD-041"]),
        ("TD-039", "r#TD-040", 1, "done #39", []),
        ("TD-007", None, 1, "ready", []),
        ("TD-043", None, 1, "waiting", ["r#TD-040"]),
        ("TD-044", "r#TD-043", 2, "waiting", ["r#TD-042", "db#TD-007"]),
    ]
    assert card["done"] == 1 and card["of"] == 7
    # picked after its blockers and its parts: a parent after its parts, a part after its blocker
    order = card["order"]
    assert order.index("r#TD-041") < order.index("r#TD-042") < order.index("r#TD-044") < order.index("r#TD-043")
    assert order.index("r#TD-042") < order.index("r#TD-040") < order.index("r#TD-043")
    # an archived parent with an open part: a done group head over it on that part's card, never Completed
    lone = next(c for c in q["cards"] if c["top"]["id"] == "TD-045")
    assert [(x["id"], x["parent"], x["state"]) for x in lone["rows"]] == [("TD-030", None, "done #30")]
    assert not [c for c in q["completed"] if any(e.get("qid") == "r#TD-030" for e in c.get("entries") or ())]


def test_a_card_whose_parents_are_all_archived_takes_the_rule_from_before(tmp_path):
    root, r = _repo(tmp_path, "r", [
        _entry(51, "an open part", Priority="High", Part_of="TD-050"),
        _entry(52, "a design after it", Priority="Low", Kind="design-first", Blocked_by="TD-051"),
    ], archive=[_entry(50, "the finished parent", Resolved=f"{TODAY} — (PR #50).")])  # fmt: skip
    card = _cards({root: r})["cards"][0]
    assert card["top"]["id"] == "TD-052", "the design-first entry, as before; an archived parent never tops"
    assert [(x["id"], x["parent"], x["depth"]) for x in card["rows"]] == [
        ("TD-050", None, 1),
        ("TD-051", "r#TD-050", 2),
    ]


def test_part_of_edge_cases_a_cycle_the_tops_archived_parent_and_a_card_of_waiting_parents(tmp_path):
    """TD-1130 review: a `Part of:` cycle draws every member once, loose; the top entry's own archived parent
    is a done group head over its open siblings; a card whose open members all wait on open parts is Waiting."""  # noqa: E501
    root, r = _repo(tmp_path, "r", [
        _entry(61, "a", Priority="High", Part_of="TD-062"),
        _entry(62, "b", Priority="High", Part_of="TD-061"),
    ])  # fmt: skip
    card = _cards({root: r})["cards"][0]
    assert sorted([card["top"]["id"], *(x["id"] for x in card["rows"])]) == ["TD-061", "TD-062"]
    # each waits on the other's open part: Waiting, read as past reach, never *ready*
    assert card["status"] == "waiting" and card["wait"]["column"] == "blocked"
    root, r = _repo(tmp_path, "s", [
        _entry(71, "the top, a parent", Priority="High", Part_of="TD-070"),
        _entry(72, "its part", Priority="High", Part_of="TD-071"),
        _entry(73, "its sibling, after its part", Priority="Low", Part_of="TD-070", Blocked_by="TD-072"),
    ], archive=[_entry(70, "a finished grandparent", Resolved=f"{TODAY} — (PR #70).")])  # fmt: skip
    card = _cards({root: r})["cards"][0]
    assert card["top"]["id"] == "TD-071" and card["top"]["state"] == "waiting" and card["status"] == "ready"
    assert [(x["id"], x["parent"], x["depth"]) for x in card["rows"]] == [
        ("TD-072", "s#TD-071", 1),
        ("TD-070", None, 1),
        ("TD-073", "s#TD-070", 2),
    ]
