"""The home merges a mechanical sync PR (design §6 *Sync*, steps 3 to 5; TD-685 slice 2): who the pass
takes up and declines, the SHIP and BLOCK comments, the gate's three outcomes, the pinned merge and its
note, the switch, and TD-684's order read through `sync.mark`. The check (slice 1, tested with fixture
repos in `test_sync_check.py`), the gate and every `gh` call are stubbed: no test reaches GitHub."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import cadence, sync, workorders
from sessionorc import settings as settings_mod

HEAD = "a" * 40
ROOT = "/r/samscrape"


def _pr(n: int = 1097, **over) -> dict:
    pr = {
        "number": n,
        "title": "cadence sync",
        "url": f"https://github.com/ContractMatch/samscrape/pull/{n}",
        "branch": "cadence-sync-2026-10-15",
        "head": HEAD,
        "author": "eyecantell",
        "draft": False,
        "conflicting": False,
        "checks": "green",
        "failing": [],
        "fork": False,
        "sync": True,
        "sync_since": "2026-10-15T00:00:00+00:00",
    }
    return {**pr, **over}


MECHANICAL = {"verdict": "mechanical", "why": "", "head": HEAD, "commit": "d" * 40, "files": ["scripts/x.sh"],
              "post_sync": False}  # fmt: skip


@pytest.fixture
def gh(monkeypatch):
    """Every outward call of the pass, recorded and answered from `state`."""
    state = {
        "check": dict(MECHANICAL),
        "gate": {"verdict": "pass", "failed": []},
        "comment": None,
        "merge": None,
        "head": (HEAD, "open"),
        "login": "eyecantell",
        "gated": cadence.DEFAULT_GATE,
        "calls": [],
    }

    def record(name, value):
        def f(*a, **k):
            state["calls"].append((name, a))
            return state[value] if not callable(state[value]) else state[value](*a)

        return f

    monkeypatch.setattr(sync, "check", record("check", "check"))
    monkeypatch.setattr(cadence, "check", record("gate", "gate"))
    monkeypatch.setattr(sync, "comment", record("comment", "comment"))
    monkeypatch.setattr(sync, "merge", record("merge", "merge"))
    monkeypatch.setattr(cadence, "head", record("head", "head"))
    monkeypatch.setattr(sync, "gh_login", record("login", "login"))
    monkeypatch.setattr(cadence, "gate", lambda root: state["gated"])
    monkeypatch.setattr(sync, "held_globs", lambda root: [])
    return state


@pytest.fixture
async def agent(agent):
    """The running agent, its tick loop parked (TD-695, TD-1101). The first tick's full reading starts
    `_sync_pass` as a task; where the reading is slow (CI), that task ran beside the test's own pass and set
    `_sync_ran` again after the test had cleared it, and each tick's `_refresh_repos` drops the test's `ROOT`,
    which no registry lists. Holding those two tasks was not enough: the loop's other passes save `_repos` too,
    and under load one landed inside `test_off_is_written_once_per_head`'s pass. So no tick runs but the test's."""
    await park_ticks(agent)
    return agent


def _names(state) -> list[str]:
    return [c[0] for c in state["calls"]]


# -- pure ---------------------------------------------------------------------------------------------


def test_candidates_are_green_unheld_unjudged_sync_prs():
    prs = [
        _pr(1),
        _pr(2, draft=True),
        _pr(3, conflicting=True),
        _pr(4, checks="pending"),
        _pr(5, checks="not_run"),
        _pr(6, sync=False),
        _pr(7),
        _pr(8),
    ]
    done = {"7": {"head": HEAD, "verdict": "refused"}, "8": {"head": "b" * 40, "verdict": "gate"}}
    got = sync.candidates(prs, done, lambda p: p["number"] == 1)
    assert [p["number"] for p in got] == [8], "held, draft, conflicting, pending, not_run, no flag, judged: out"


def test_decline_a_fork_then_another_login():
    assert sync.decline(_pr(fork=True), "eyecantell") == "forked"
    assert sync.decline(_pr(author="mallory"), "eyecantell") == "author mallory is not the home's"
    assert sync.decline(_pr(author="EyeCantell"), "eyecantell") is None, "logins are case-insensitive"


def test_prune_keeps_the_open_prs():
    kept = {"1": {"head": HEAD, "verdict": "refused"}, "2": {"head": HEAD}, "9": {}}
    assert set(sync.prune(kept, [_pr(1), _pr(2)])) == {"1", "2"}
    # the newest *merged* entry outlives its PR, for the Repos card (§4.5a); an older one does not
    kept = {
        "5": {"head": HEAD, "verdict": "merged", "at": "2026-10-15T01:00:00Z"},
        "6": {"head": HEAD, "verdict": "merged", "at": "2026-10-15T02:00:00Z"},
        "7": {"head": HEAD, "verdict": "refused", "at": "2026-10-15T03:00:00Z"},
    }
    assert set(sync.prune(kept, [])) == {"6"}
    assert [p["number"] for p in sync.candidates([_pr(1)], sync.prune(kept, []), lambda p: False)] == [1]


def test_mark_the_homes_prs_are_no_order_and_a_verdicts_why_is_the_context():
    prs = [_pr(1), _pr(2), _pr(3), _pr(4, checks="red", failing=["test"]), _pr(5, sync=False, checks="red")]
    kept = {
        "1": {"head": HEAD, "verdict": "merged"},
        "2": {"head": HEAD, "verdict": "refused", "why": "lock not dev-cadence's: scripts/x.sh"},
        "3": {"head": HEAD, "verdict": "", "tries": 1},  # a retry: still the home's
    }
    got = {p["number"]: p for p in sync.mark(prs, kept, True)}
    assert got[1]["sync_home"] and got[3]["sync_home"]
    assert got[2]["sync_why"] == "lock not dev-cadence's: scripts/x.sh" and not got[2].get("sync_home")
    assert not got[4].get("sync_home") and got[5] is prs[4]
    assert workorders.sync_reason(got[2]) == "lock not dev-cadence's: scripts/x.sh"
    assert not workorders.is_sync_order(got[1]) and not workorders.is_sync_order(got[3])
    assert workorders.is_sync_order(got[2]) and workorders.is_sync_order(got[4])
    off = {p["number"]: p for p in sync.mark(prs, {}, False)}
    assert not any(p.get("sync_home") for p in off.values()), "switch off: every sync PR is the team's"
    # *off* at the head is the order's Context; a stale *off* under a switch on again is the home's
    offs = {"1": {"head": HEAD, "verdict": "off", "why": "sync is off"}, "2": {"head": "0" * 40, "verdict": "off"}}
    off = {p["number"]: p for p in sync.mark(prs, offs, False)}
    assert workorders.sync_reason(off[1]) == "sync is off" and not off[2].get("sync_why")
    assert sync.mark(prs, offs, True)[0]["sync_home"] and not sync.mark(prs, offs, True)[0].get("sync_why")


def test_the_ship_comment_is_the_cadence_line_and_what_was_checked():
    body = sync.review_body(MECHANICAL)
    assert body.splitlines()[0] == "cadence-review: SHIP · sync-check · code · 0 findings"
    assert "d" * 40 in body and "`scripts/x.sh`" in body and "no post_sync" in body and HEAD in body
    assert sync.block_body("ci: not green").splitlines()[0] == "cadence-review: BLOCK · sync-check · code · 1 findings"


# -- judge ------------------------------------------------------------------------------------------------


def test_judge_mechanical_and_gated_is_ready_and_posts_once(gh):
    e = sync.judge(ROOT, _pr(), None, [], "T0")
    assert e["ready"] and e["posted"] and e["commit"] == "d" * 40 and e["files"] == 1
    assert _names(gh) == ["check", "comment", "gate"]
    assert gh["calls"][1][1][2].startswith("cadence-review: SHIP")
    # no reading from the gate: tried again, not posted again, and *error* at the third
    gh["gate"], gh["calls"] = None, []
    e = sync.judge(ROOT, _pr(), {k: v for k, v in e.items() if k != "ready"}, [], "T1")
    assert (e["verdict"], e["tries"], e["posted"]) == ("", 1, True) and "comment" not in _names(gh)
    gh["gate"] = {"verdict": "unknown", "failed": []}  # the script's exit 3
    e = sync.judge(ROOT, _pr(), e, [], "T2")
    e = sync.judge(ROOT, _pr(), e, [], "T3")
    assert (e["verdict"], e["tries"], e["why"]) == ("error", 3, "the gate gave no reading")


def test_judge_a_failed_gate_blocks_and_a_refusal_posts_nothing(gh):
    gh["gate"] = {"verdict": "fail", "failed": ["ci", "review"]}
    e = sync.judge(ROOT, _pr(), None, [], "T0")
    assert (e["verdict"], e["why"]) == ("gate", "ci; review")
    assert [c[1][2].splitlines()[0] for c in gh["calls"] if c[0] == "comment"] == [
        "cadence-review: SHIP · sync-check · code · 0 findings",
        "cadence-review: BLOCK · sync-check · code · 1 findings",
    ]
    gh["calls"], gh["check"] = [], {"verdict": "refused", "why": "scripts/y.sh is not in the lock", "head": HEAD}
    e = sync.judge(ROOT, _pr(), None, [], "T0")
    assert (e["verdict"], e["why"]) == ("refused", "scripts/y.sh is not in the lock") and _names(gh) == ["check"]
    gh["check"] = {"verdict": "moved", "why": "moved", "head": HEAD}
    assert sync.judge(ROOT, _pr(), None, [], "T0") is None
    gh["check"] = {"verdict": "error", "why": "git fetch: TimeoutExpired", "head": HEAD}
    assert sync.judge(ROOT, _pr(), None, [], "T0")["tries"] == 1


BUMP = {"verdict": "mechanical", "why": "", "head": HEAD, "kind": "bump", "commit": "e" * 40, "old": "d" * 40,
        "files": ["docs/cadence.toml"], "post_sync": False}  # fmt: skip


def test_judge_a_bump_posts_nothing_and_waits_on_a_review_of_its_compare(gh, monkeypatch):
    """TD-1015, §6 *Sync* step 3 for a bump: the home posts no evidence of its own; the bump waits, uncounted,
    for a review of its compare at the head, then gates as any; a day with none is *refused*."""
    gh["check"], review = dict(BUMP), [None, False]
    monkeypatch.setattr(sync, "compare_review", lambda root, n, head: tuple(review))
    e = sync.judge(ROOT, _pr(), None, [], "2026-10-26T00:00:00+00:00")
    assert (e["verdict"], e["waits"], e["tries"], e["posted"]) == ("", "review", 0, False)
    assert e["why"] == f"no review of the compare at {HEAD[:7]}" and e["waiting_since"] == "2026-10-26T00:00:00+00:00"
    assert _names(gh) == ["check"]
    # unreadable comments are no reading, counted
    review[:] = ["HTTP 502", False]
    assert sync.judge(ROOT, _pr(), e, [], "2026-10-26T00:05:00+00:00")["tries"] == 1
    # reviewed: the gate runs, no comment is posted, and the wait is over
    review[:] = [None, True]
    gh["calls"] = []
    got = sync.judge(ROOT, _pr(), e, [], "2026-10-26T00:10:00+00:00")
    assert got["ready"] and got["kind"] == "bump" and got["commit"] == "e" * 40 and got["files"] == 1
    assert "waits" not in got and "waiting_since" not in got and _names(gh) == ["check", "gate"]
    # a day with no review: refused, and the PR the team's
    review[:] = [None, False]
    e = sync.judge(ROOT, _pr(), e, [], "2026-10-27T00:00:00+00:00")
    assert (e["verdict"], e["why"]) == ("refused", f"review waited a day: no review of the compare at {HEAD[:7]}")


def test_mark_a_bump_waiting_on_its_review_is_the_teams_order():
    e = {"head": HEAD, "verdict": "", "why": "no review of the compare at aaaaaaa", "waits": "review",
         "waiting_since": "T0"}  # fmt: skip
    (pr,) = sync.mark([_pr()], {"1097": e}, True)
    assert pr["sync_why"] == "no review of the compare at aaaaaaa" and "sync_home" not in pr


def _comments(monkeypatch, *bodies):
    import json

    out = json.dumps({"comments": [{"body": b} for b in bodies]})
    monkeypatch.setattr(sync, "_gh", lambda root, args, timeout=0: (None, out))


def test_compare_review_wants_another_reviewer_naming_the_head_and_no_block_after(monkeypatch):
    ship = f"Read the compare at {HEAD[:9]}.\n\ncadence-review: SHIP · claude-sonnet-5-5 · code · 0 findings"
    _comments(monkeypatch, ship)
    assert sync.compare_review(ROOT, 1, HEAD) == (None, True)
    _comments(monkeypatch, ship.replace(HEAD[:9], "b" * 9))  # another head's review
    assert sync.compare_review(ROOT, 1, HEAD) == (None, False)
    _comments(monkeypatch, f"cadence-review: SHIP · sync-check · code · 0 findings\n\n- head {HEAD}")
    assert sync.compare_review(ROOT, 1, HEAD) == (None, False)
    _comments(monkeypatch, ship, f"{HEAD[:7]}\ncadence-review: BLOCK · claude-sonnet-5-5 · code · 1 findings")
    assert sync.compare_review(ROOT, 1, HEAD) == (None, False)
    monkeypatch.setattr(sync, "_gh", lambda root, args, timeout=0: ("HTTP 502", ""))
    assert sync.compare_review(ROOT, 1, HEAD) == ("HTTP 502", False)


# -- at the home --------------------------------------------------------------------------------------------


def _reading(agent, *prs) -> None:
    agent._repos = {ROOT: {"root": ROOT, "remote": "git@github.com:ContractMatch/samscrape.git",
                           "prs": {"open": list(prs)}}}  # fmt: skip


async def _orders(agent) -> list[dict]:
    await agent._red_prs(datetime.now(UTC) + timedelta(days=1))
    return (agent._repos[ROOT].get("pr_orders") or {}).get("orders") or []


@pytest.mark.integration
async def test_a_mechanical_sync_pr_is_merged_with_the_note_and_is_no_order(agent, gh):
    _reading(agent, _pr())
    assert len(await _orders(agent)) == 1, "no pass has covered the repo yet: the team's"
    await agent._sync_pass()
    entry = agent._repos[ROOT]["sync"]["1097"]
    assert (entry["verdict"], entry["head"], entry["posted"]) == ("merged", HEAD, True)
    assert _names(gh) == ["login", "check", "comment", "gate", "head", "merge"]
    assert gh["calls"][-1][1] == (ROOT, 1097, HEAD)
    notes = [e.text for e in agent.person_inbox if e.from_ == "system"]
    assert f"merged samscrape #1097 — sync of dev-cadence {'d' * 40}, 1 files" in notes
    assert await _orders(agent) == []
    # judged at its head: never checked again
    gh["calls"] = []
    await agent._sync_pass()
    assert gh["calls"] == []
    # the reading's re-read keeps the pass's outcomes
    assert agent.repos_store.load()[ROOT]["sync"]["1097"]["verdict"] == "merged"


@pytest.mark.integration
async def test_a_reviewed_bump_is_merged_with_its_own_note(agent, gh, monkeypatch):
    gh["check"] = dict(BUMP)
    monkeypatch.setattr(sync, "compare_review", lambda root, n, head: (None, True))
    _reading(agent, _pr())
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "merged"
    assert _names(gh) == ["login", "check", "gate", "head", "merge"]
    notes = [e.text for e in agent.person_inbox if e.from_ == "system"]
    assert "merged samscrape #1097 — bump of the dev-cadence pin to eeeeeee" in notes


@pytest.mark.integration
async def test_another_login_is_refused_at_once_with_no_comment_and_the_order_says_why(agent, gh):
    _reading(agent, _pr(author="mallory"))
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "refused"
    assert _names(gh) == ["login"]
    (order,) = await _orders(agent)
    assert order["id"] == "pr:1097" and "author mallory is not the home's" in order["context"]


@pytest.mark.integration
async def test_a_repo_with_no_gate_is_unserved_its_sync_pr_not_read_and_nothing_written(agent, gh):
    """§6 *Sync*, TD-1011: an unserved repo's PR is the person's — not read, nothing written, off or on."""
    gh["gated"] = None
    _reading(agent, _pr(author="mallory"))
    await agent._sync_pass()
    assert agent._repos[ROOT].get("sync", {}) == {} and gh["calls"] == []
    settings_mod.save({"repos": {"samscrape": {"sync": {"auto": False}}}})
    await agent._sync_pass()
    assert agent._repos[ROOT].get("sync", {}) == {} and gh["calls"] == []


@pytest.mark.integration
async def test_a_repo_unserved_but_by_an_older_tree_has_its_sync_pr_left_and_an_older_tree_is_judged(agent, gh):
    """§6 *Sync*, TD-1018: a repo with the gate but no ledger is unserved, its sync PR not read and nothing
    written; one whose only lack is an older tree (TD-1012's `age`) is judged, since the sync cures it."""
    led = {"key": "ledger", "words": "unserved: no ledger at docs/technical_debt.md — x"}
    age = {"key": "age", "words": "unserved: dev-cadence at abc1234 is older than this build reads (6d92209) — sync it"}
    _reading(agent, _pr())
    agent._repos[ROOT]["seams"] = {"serve": {"ok": False, "lacks": [led, age]}}
    await agent._sync_pass()
    assert agent._repos[ROOT].get("sync", {}) == {} and gh["calls"] == []
    agent._repos[ROOT]["seams"] = {"serve": {"ok": False, "lacks": [age]}}
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "merged"


@pytest.mark.integration
async def test_a_head_moved_before_the_merge_or_a_new_holder_is_not_merged_and_gets_no_verdict(agent, gh, monkeypatch):
    _reading(agent, _pr())
    gh["head"] = ("b" * 40, "open")
    await agent._sync_pass()
    assert "merge" not in _names(gh) and "1097" not in agent._repos[ROOT].get("sync", {})
    gh["head"], gh["calls"] = (HEAD, "open"), []
    seen = iter([False, True])  # free when taken up, held by the merge
    monkeypatch.setattr(agent, "_sync_held_by", lambda root, pr: next(seen))
    await agent._sync_pass()
    entry = agent._repos[ROOT]["sync"]["1097"]
    assert "merge" not in _names(gh) and entry["verdict"] == "" and entry["posted"]


@pytest.mark.integration
async def test_a_failed_gate_leaves_the_block_and_the_order(agent, gh):
    gh["gate"] = {"verdict": "fail", "failed": ["ci"]}
    _reading(agent, _pr())
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "gate"
    (order,) = await _orders(agent)
    assert order["context"].endswith("ci")


@pytest.mark.integration
async def test_the_switch_off_merges_nothing_and_every_sync_pr_is_the_teams(agent, gh):
    settings_mod.save({"repos": {"samscrape": {"sync": {"auto": False}}}})
    _reading(agent, _pr())
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "off" and gh["calls"] == []
    (order,) = await _orders(agent)
    assert order["context"].endswith("sync is off")  # the verdict's why is the order's Context
    # on again: *off* is no verdict, so the PR is judged
    settings_mod.save({"repos": {"samscrape": {"sync": {"auto": True}}}})
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "merged"


def test_the_switch_is_a_repo_setting():
    assert settings_mod.parse_repo({"sync": {"auto": False}}) == {"sync": {"auto": False}}
    with pytest.raises(ValueError, match="sync.auto is true or false"):
        settings_mod.parse_repo({"sync": {"auto": "no"}})


@pytest.mark.integration
async def test_a_pass_that_covers_the_repo_holds_a_green_pr_back_and_one_that_cannot_does_not(agent, gh):
    gh["gate"] = None  # a retry: no verdict yet
    _reading(agent, _pr())
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["tries"] == 1
    assert await _orders(agent) == [], "green and unjudged under a pass that covers it: the home's"
    agent._sync_ran.clear()
    gh["login"], agent._sync_login = None, None
    await agent._sync_pass()
    assert ROOT not in agent._sync_ran and len(await _orders(agent)) == 1, "no login: no cover, the team's"


@pytest.mark.integration
async def test_off_is_written_once_per_head(agent, gh, monkeypatch):
    settings_mod.save({"repos": {"samscrape": {"sync": {"auto": False}}}})
    _reading(agent, _pr())
    await agent._sync_pass()
    saved = []
    monkeypatch.setattr(agent.repos_store, "save", lambda r: saved.append(r))
    await agent._sync_pass()
    assert saved == [], "nothing changed: nothing saved or pushed"


@pytest.mark.integration
async def test_the_kept_merged_entry_is_saved_once_and_never_judged(agent, gh, monkeypatch):
    """The newest *merged* entry outlives its PR (§6 *Sync*, for the Repos card): a pass over the repo
    with that PR closed keeps it, judges nothing and saves nothing."""
    _reading(agent, _pr())
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "merged"
    agent._repos[ROOT]["prs"] = {"open": []}  # the PR closed with its merge
    calls = len(gh["calls"])
    saved = []
    monkeypatch.setattr(agent.repos_store, "save", lambda r: saved.append(r))
    await agent._sync_pass()
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "merged" and saved == [] and len(gh["calls"]) == calls


@pytest.mark.integration
async def test_a_merge_refused_under_a_moved_head_writes_nothing(agent, gh):
    heads = iter([(HEAD, "open"), ("b" * 40, "open")])
    gh["head"] = lambda *a: next(heads)
    gh["merge"] = "Head branch was modified"
    _reading(agent, _pr())
    await agent._sync_pass()
    assert "1097" not in agent._repos[ROOT].get("sync", {})


def test_an_unreadable_held_list_is_no_reading(gh, monkeypatch):
    monkeypatch.setattr(sync, "held_globs", lambda root: None)
    e = sync.judge(ROOT, _pr(), None, [], "T0")
    assert (e["tries"], e["verdict"]) == (1, "") and "held" in e["why"] and _names(gh) == []


def test_held_globs_reads_the_repo_file(tmp_path):
    assert sync.held_globs(tmp_path) == []
    (tmp_path / ".shiftlead.yml").write_text('held: ["src/x/**"]\n')
    assert sync.held_globs(tmp_path) == ["src/x/**"]
    (tmp_path / ".shiftlead.yml").write_text("held: src/x\n")
    assert sync.held_globs(tmp_path) is None
    (tmp_path / ".shiftlead.yml").write_text("held: [\n")
    assert sync.held_globs(tmp_path) is None
    # a mapping of named sets (§4.9c) is their union, a glob once
    (tmp_path / ".shiftlead.yml").write_text(
        'held:\n  core: ["src/x/**", "docs/b/**"]\n  ui: ["src/y/**", "docs/b/**"]\n'
    )
    assert sync.held_globs(tmp_path) == ["src/x/**", "docs/b/**", "src/y/**"]
    (tmp_path / ".shiftlead.yml").write_text("held:\n  core: src/x\n")
    assert sync.held_globs(tmp_path) is None
