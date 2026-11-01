"""TD-195, design §6 *Keeping a team running* rule 6: a member that declared out of work is told,
by one `note` from `system`, when its lane gains ledger entries — each entry once, by the entry's
header and never its prose, and only while the member is live and not winding down."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc.agent_common import RpcError, _lane
from sessionorc.client import LocalClient
from sessionorc.ledger import entries_before, lane_matches
from sessionorc.models import ProgressEntry, lane_refs, report_line

pytestmark = pytest.mark.integration


def _e(id: str, pickable: str = "yes", kind: str = "build") -> dict:
    return {"id": id, "title": id, "priority": "medium", "owner": "grinder", "kind": kind, "pickable": pickable}


def test_a_lane_word_matches_by_the_header():
    assert lane_matches(["free-pick"], _e("TD-1")) and not lane_matches(["free-pick"], _e("TD-1", pickable="no"))
    assert not lane_matches(["free-pick"], _e("TD-1", kind="design-first"))
    assert lane_matches(["design-first"], _e("TD-1", kind="design-first"))
    assert not lane_matches(["design-first"], _e("TD-1", kind="design-first", pickable="no"))
    assert not lane_matches(["design-first"], _e("TD-1"))
    for word in ("TD-001", "hunt", ""):
        assert not lane_matches([word], _e("TD-1"))


def test_an_owner_word_narrows_the_lane_and_is_no_reference():
    """TD-227 slice 1: `[free-pick, owner:grinder]` takes an entry owned by grinder or by nobody and
    leaves the anchor's out; the word alone matches nothing; it is never counted as a reference."""
    lane = ["free-pick", "owner:grinder"]
    assert lane_matches(lane, _e("TD-1")) and lane_matches(lane, {**_e("TD-1"), "owner": ""})
    assert not lane_matches(lane, {**_e("TD-1"), "owner": "anchor"})
    assert lane_matches(["free-pick", "owner:anchor", "owner:Grinder"], _e("TD-1"))
    assert lane_matches(["free-pick"], {**_e("TD-1"), "owner": "anchor"}), "no owner word: as it was"
    assert not lane_matches(["owner:grinder"], _e("TD-1"))
    assert lane_refs(["free-pick", "owner:grinder"]) == [] and lane_refs(["TD-001", "owner:x", "design-first"]) == [
        "TD-001"
    ]
    assert report_line({"lane": ["TD-001", "owner:grinder"], "progress": []}) == "0/1 done"
    assert _lane(["free-pick", "Owner:Grinder"]) == ["free-pick", "owner:grinder"]
    assert _lane(["td-7", "owner:grinder", "owner:grinder"]) == ["TD-007", "owner:grinder"]
    for bad in (["owner:grinder"], ["free-pick", "owner:"], ["free-pick", "TD-001", "owner:grinder"]):
        with pytest.raises(RpcError):
            _lane(bad)


def _git(root, *args: str, when: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env).stdout


def _ledger(ids: list[str]) -> str:
    return "".join(f"## {i}: {i}\n\n**Kind:** build\n\n" for i in ids)


def _commit(root, ids: list[str], when: str) -> None:
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "technical_debt.md").write_text(_ledger(ids))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "ledger", when=when)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_the_ledger_before_an_instant_is_read_from_origin(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, ["TD-001"], "2026-09-27T10:00:00Z")
    _commit(tmp_path, ["TD-001", "TD-002"], "2026-09-28T10:00:00Z")
    got, why = entries_before(tmp_path, "docs/technical_debt.md", datetime(2026, 9, 27, 20, tzinfo=UTC))
    assert [e["id"] for e in got] == ["TD-001"] and why.startswith("origin/main at ")
    assert entries_before(tmp_path, "docs/technical_debt.md", datetime(2026, 9, 1, tzinfo=UTC))[0] is None
    assert entries_before(tmp_path, "docs/nope.md", datetime(2026, 9, 29, tzinfo=UTC))[0] is None
    assert entries_before(tmp_path / "docs", "technical_debt.md", datetime(2026, 9, 29, tzinfo=UTC))[0] is None
    assert [e["id"] for e in entries_before(tmp_path, "docs/technical_debt.md", None)[0]] == ["TD-001", "TD-002"]


async def test_the_first_write_is_the_ledger_at_the_declaration(agent, tmp_path):
    """TD-227 slice 1: declared at 20:00, an entry merged at 21:00, the first tick a day later — the
    entry is new and is told on that first tick; a checkout with no history falls back."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, ["TD-001"], "2026-09-27T10:00:00Z")
    _commit(repo, ["TD-001", "TD-002"], "2026-09-27T21:00:00Z")
    async with LocalClient() as person:
        # the checkout's reading also holds TD-009, an entry only a branch here has: never told as new
        led = [_e("TD-001"), _e("TD-002"), _e("TD-009")]
        sid = await _finished(agent, person, repo, "w", ["free-pick"], led)
        agent._repos[str(repo)]["ledger"]["path"] = "docs/technical_debt.md"
        rec = agent.sessions[sid]
        await agent._lane_news(rec, now)
        assert rec.lane_seen["ids"] == ["TD-001", "TD-009", "TD-002"] and "TD-009" not in _notes(agent, sid)[0]
        await agent._lane_news(rec, now + timedelta(minutes=1))
        assert len(_notes(agent, sid)) == 1, "the checkout's own entry is not told on a later tick either"
        # a second `none` looks afresh: the first write again sees the checkout's own entry, untold
        rec.out_of_work, rec.lane_seen = {"at": "2026-09-28T00:00:00Z", "why": "nothing pickable"}, None
        await agent._lane_news(rec, now + timedelta(minutes=2))
        await agent._lane_news(rec, now + timedelta(minutes=3))
        assert rec.lane_seen["ids"] == ["TD-001", "TD-002", "TD-009"] and len(_notes(agent, sid)) == 1
        assert (
            len(_notes(agent, sid)) == 1
            and "gained 1 entry since you declared out of work: TD-002" in _notes(agent, sid)[0]
        )
        await person.call("kill", id=sid)


async def _finished(agent, person, tmp_path, name: str, lane: list[str], entries: list[dict], **fields) -> str:
    """A supervised, unattended member of `tmp_path`'s repo that declared out of work, and the
    repo's ledger reading holding `entries`."""
    (tmp_path / name).mkdir()
    sid = (
        await person.call(
            "create", name=name, dir=str(tmp_path / name), adapter="shell", argv=["bash", "--norc"],
            unattended=True, supervised=True, lane=lane,
        )
    )["id"]  # fmt: skip
    rec = agent.sessions[sid]
    rec.repo = str(tmp_path)
    rec.out_of_work = {"at": "2026-09-27T20:00:00Z", "why": "nothing pickable"}
    for k, v in fields.items():
        setattr(rec, k, v)
    agent._repos[str(tmp_path)] = {"name": "r", "root": str(tmp_path), "ledger": {"entries": entries}}
    return sid


def _notes(agent, sid: str) -> list[str]:
    return [e.text for e in agent.sessions[sid].inbox if e.from_ == "system"]


async def test_an_entry_filed_after_the_declaration_is_told_once(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        led = [_e("TD-001"), _e("TD-002", pickable="no"), _e("TD-003", kind="design-first")]
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick"], led)
        rec = agent.sessions[sid]
        await agent._keep_running(now)
        assert rec.lane_seen and rec.lane_seen["ids"] == ["TD-001"], "the first tick writes what was there"
        assert _notes(agent, sid) == [], "an entry present at the declaration is not new"
        # an entry filed since, one that turned pickable, and a design-first one that is not this lane's
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [
            _e("TD-001"), _e("TD-002"), _e("TD-003", kind="design-first"), _e("TD-004"),
        ]  # fmt: skip
        await agent._lane_news(rec, now)
        notes = _notes(agent, sid)
        assert len(notes) == 1
        assert "your lane gained 2 entries since you declared out of work: TD-002, TD-004" in notes[0]
        assert rec.lane_seen["ids"] == ["TD-001", "TD-002", "TD-004"]
        await agent._lane_news(rec, now + timedelta(minutes=1))
        assert len(_notes(agent, sid)) == 1, "an entry is told once"
        # more than five: named up to five, and the rest counted
        agent._repos[str(tmp_path)]["ledger"]["entries"] += [_e(f"TD-01{i}") for i in range(7)]
        await agent._lane_news(rec, now)
        assert "7 entries" in _notes(agent, sid)[1] and "TD-014 and 2 more —" in _notes(agent, sid)[1]
        # a claim takes the declaration back, and rule 6's memory with it
        await person.call("progress", id=sid, ref="TD-2", status="claimed", caller=sid)
        assert rec.out_of_work is None and rec.lane_seen is None
        await person.call("kill", id=sid)


async def test_rule_six_tells_a_member_only_its_own_teams_entries(agent, tmp_path):
    """Rule 6 reads the lane with the record's `team` (§4.4 *An entry names its team*, TD-762): an entry
    tagged for another team, and one that needs a team, are no news to db's member."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _finished(
            agent, person, tmp_path, "w", ["free-pick"], [_e("TD-001"), {**_e("TD-005"), "team": "ops"}]
        )
        rec = agent.sessions[sid]
        rec.team = "db"
        await agent._keep_running(now)
        assert rec.lane_seen and rec.lane_seen["ids"] == ["TD-001"], "the tick reads the member's team"
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [
            _e("TD-001"), {**_e("TD-002"), "team": "db"}, {**_e("TD-003"), "team": "ops"},
            {**_e("TD-004"), "needs_team": {"why": "untagged"}},
        ]  # fmt: skip
        await agent._lane_news(rec, now)
        assert len(notes := _notes(agent, sid)) == 1 and "1 entry since you declared out of work: TD-002" in notes[0]
        await person.call("kill", id=sid)


async def test_an_entry_on_a_designer_decision_item_is_no_ones_news_until_decided_and_then_the_grinders(
    agent, tmp_path
):
    """TD-1297 (design §6 rule 6, TD-1296): a decision owed to the designer is `Kind: design-first`, so an
    entry blocked by `decision (designer)` is in no lane, the designer's included; the PR that drops the
    item makes it the grinder's lane news."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    held = {**_e("TD-151", pickable="no"), "blocked_by": ["decision (designer)"]}
    async with LocalClient() as person:
        des = await _finished(agent, person, tmp_path, "d", ["design-first", "owner:designer"], [_e("TD-001")])
        gri = await _finished(agent, person, tmp_path, "g", ["free-pick", "owner:grinder"], [_e("TD-001")])
        await agent._keep_running(now)
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [_e("TD-001"), held]
        for sid in (des, gri):
            await agent._lane_news(agent.sessions[sid], now)
        assert _notes(agent, des) == [] and _notes(agent, gri) == []
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [_e("TD-001"), _e("TD-151")]
        for sid in (des, gri):
            await agent._lane_news(agent.sessions[sid], now + timedelta(minutes=1))
        assert len(_notes(agent, gri)) == 1 and "TD-151" in _notes(agent, gri)[0]
        assert _notes(agent, des) == [], "never the designer's"
        for sid in (des, gri):
            await person.call("kill", id=sid)


async def test_a_lease_a_sibling_dropped_is_told_once(agent, tmp_path):
    """Rule 6's dropped lease (TD-258 slice 4): an id the member saw at its declaration, dropped
    since by another record of its repo, is told once with the dropper's name; a drop before the
    declaration, one in another repo, the member's own, and one taken again by a live record are
    not; a second drop of the same id, later, is told again."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        led = [_e("TD-001"), _e("TD-002"), _e("TD-003"), _e("TD-004")]
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick"], led)
        rec = agent.sessions[sid]
        sib = await _finished(agent, person, tmp_path, "grinder-2", ["free-pick"], led, out_of_work=None)
        other = tmp_path / "elsewhere"
        other.mkdir()
        far = await _finished(agent, person, other, "far", ["free-pick"], led, out_of_work=None)
        before, after = "2026-09-27T19:00:00Z", "2026-09-27T21:00:00Z"
        agent.sessions[sib].progress = [
            ProgressEntry(ref="TD-001", status="dropped", why="needs a live look", at=after),
            ProgressEntry(ref="TD-002", status="dropped", why="old", at=before),
            ProgressEntry(ref="TD-004", status="dropped", why="mine now", at=after),
        ]
        agent.sessions[sib].progress += [
            ProgressEntry(ref="TD-002", status="dropped", why="no instant", at="yesterday"),
            ProgressEntry(ref="TD-003", at=before),  # a lease past its twelve hours holds nothing
        ]
        agent.sessions[far].progress = [ProgressEntry(ref="TD-003", status="dropped", why="another repo's", at=after)]
        rec.progress = [ProgressEntry(ref="TD-003", status="dropped", why="its own", at=after)]
        taker = await _finished(agent, person, tmp_path, "taker", ["free-pick"], led, out_of_work=None)
        agent.sessions[taker].progress = [ProgressEntry(ref="TD-004")]  # a live lease, claimed now
        await agent._lane_news(rec, now)
        notes = _notes(agent, sid)
        assert len(notes) == 1
        assert "your lane gained 1 entry since you declared out of work: TD-001 (dropped by grinder-2) —" in notes[0]
        assert rec.lane_seen["ids"] == ["TD-001", "TD-002", "TD-003", "TD-004"]
        assert rec.lane_seen["dropped"] == {"TD-001": after}
        await agent._lane_news(rec, now + timedelta(minutes=1))
        assert len(_notes(agent, sid)) == 1, "a second look at the same drop tells nothing"
        # a new entry and a later drop of the same id, in one note; the taker let go as well
        again = "2026-09-27T22:00:00Z"
        agent.sessions[sib].progress.append(ProgressEntry(ref="TD-001", status="dropped", why="again", at=again))
        agent.sessions[taker].progress = [ProgressEntry(ref="TD-004", status="dropped", why="no", at=again)]
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [*led, _e("TD-005")]
        await agent._lane_news(rec, now)
        assert "gained 3 entries" in _notes(agent, sid)[1]
        assert "TD-005, TD-001 (dropped by grinder-2), TD-004 (dropped by taker) —" in _notes(agent, sid)[1]
        assert rec.lane_seen["dropped"] == {"TD-001": again, "TD-004": again}
        # a kept instant that cannot be read is no memory of that id alone
        rec.lane_seen["dropped"]["TD-004"] = "never"
        await agent._lane_news(rec, now)
        assert len(_notes(agent, sid)) == 3 and "1 entry" in _notes(agent, sid)[2]
        assert "TD-004 (dropped by taker)" in _notes(agent, sid)[2]
        for s in (sid, sib, far, taker):
            await person.call("kill", id=s)


async def test_what_rule_six_leaves_alone(agent, tmp_path):
    """A lane of references, a seat, an exited member, a gated one, one past its stop, one asked to
    wrap up and one not supervised are told nothing; a failed ledger reading writes nothing."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    past = (now - timedelta(minutes=5)).isoformat()
    async with LocalClient() as person:
        cases = {
            "refs": (["TD-001"], {}),
            "seat": (["free-pick"], {"seat": "techlead"}),
            "exited": (["free-pick"], {"state": "exited"}),
            "gated": (["free-pick"], {"gated": {"since": past, "profile": "p"}}),
            "stopped": (["free-pick"], {"run_until": past}),
            "wrapping": (["free-pick"], {"wrapup_sent_at": past}),
            "unsupervised": (["free-pick"], {"supervised": False}),
        }
        ids = {}
        for n, (lane, fields) in cases.items():
            sub = tmp_path / n
            sub.mkdir()
            ids[n] = await _finished(agent, person, sub, n, lane, [_e("TD-001")], **fields)
            await agent._lane_news(agent.sessions[ids[n]], now)
            agent._repos[str(sub)]["ledger"]["entries"].append(_e("TD-002"))
            await agent._lane_news(agent.sessions[ids[n]], now)
        for n, sid in ids.items():
            assert _notes(agent, sid) == [], n
        assert agent.sessions[ids["refs"]].lane_seen == {"at": agent.sessions[ids["refs"]].lane_seen["at"], "ids": []}
        assert agent.sessions[ids["seat"]].lane_seen is None and agent.sessions[ids["unsupervised"]].lane_seen is None
        # the reading failed: nothing written, and the tick looks again
        broken = tmp_path / "broken"
        broken.mkdir()
        failed = await _finished(agent, person, broken, "broken", ["free-pick"], [_e("TD-001")])
        agent._repos[str(broken)]["ledger"]["error"] = "docs/technical_debt.md: gone"
        await agent._lane_news(agent.sessions[failed], now)
        assert agent.sessions[failed].lane_seen is None
        for sid in [*ids.values(), failed]:
            await person.call("kill", id=sid)


async def test_a_live_check_whose_build_becomes_live_is_told_once(agent, tmp_path):
    """TD-323 (design §4.9b): a live check matches `free-pick` once its build reads live, so a build
    that becomes live is new work in the lane — told once by rule 6, as an entry filed since is; one
    not live, and one the anchor owns, are told to nobody."""
    await park_ticks(agent)
    now = datetime.now(UTC)

    def check(id: str, live: str, owner: str = "grinder") -> dict:
        return {**_e(id, kind="live-check"), "owner": owner, "built": [7], "live": live}

    async with LocalClient() as person:
        led = [_e("TD-001"), check("TD-002", "no"), check("TD-003", "no", owner="anchor")]
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick", "owner:grinder"], led)
        rec = agent.sessions[sid]
        await agent._keep_running(now)
        assert rec.lane_seen["ids"] == ["TD-001"] and _notes(agent, sid) == []
        # the promote makes #7 live: the repo facts read both checks `live: yes`
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [
            _e("TD-001"), check("TD-002", "yes"), check("TD-003", "yes", owner="anchor"),
        ]  # fmt: skip
        await agent._lane_news(rec, now)
        await agent._lane_news(rec, now + timedelta(minutes=1))
        notes = _notes(agent, sid)
        assert len(notes) == 1 and "your lane gained 1 entry since you declared out of work: TD-002" in notes[0]
        await person.call("kill", id=sid)


async def test_an_entry_that_leaves_the_lane_and_comes_back_is_told_again(agent, tmp_path):
    """TD-411 (design §6 rule 6 *`lane_seen` is the lane's memory, never the ledger's*, TD-407): an id
    the reading holds and the lane no longer takes leaves `lane_seen`, its `dropped` mark with it,
    untold; back in the lane it is news once more — a build its merge made a live check not yet live,
    then live at the promote (TD-400's case), and a `Blocked by` that reopened and cleared. An id the
    reading does not hold is kept, and a gone member's memory is pruned as a live one's is."""
    await park_ticks(agent)
    now = datetime.now(UTC)

    def check(id: str, live: str) -> dict:
        return {**_e(id, kind="live-check"), "built": [7], "live": live}

    async with LocalClient() as person:
        sid = await _finished(
            agent, person, tmp_path, "w", ["free-pick", "owner:grinder"], [_e("TD-001"), _e("TD-002")]
        )
        rec = agent.sessions[sid]
        reading = agent._repos[str(tmp_path)]["ledger"]
        await agent._keep_running(now)
        assert rec.lane_seen["ids"] == ["TD-001", "TD-002"] and _notes(agent, sid) == []
        # merged: TD-002 reads as a live check whose build is not live — out of the lane, told nothing
        reading["entries"] = [_e("TD-001"), check("TD-002", "no")]
        await agent._lane_news(rec, now)
        assert rec.lane_seen["ids"] == ["TD-001"] and _notes(agent, sid) == []
        # the promote: live, in the lane again — news, told once
        reading["entries"] = [_e("TD-001"), check("TD-002", "yes")]
        await agent._lane_news(rec, now)
        await agent._lane_news(rec, now + timedelta(minutes=1))
        notes = _notes(agent, sid)
        assert len(notes) == 1 and "your lane gained 1 entry since you declared out of work: TD-002" in notes[0]
        # a `Blocked by` that reopens takes TD-001 out, its drop mark with it; cleared, it is told again
        rec.lane_seen["dropped"] = {"TD-001": "2026-09-27T21:00:00Z", "TD-002": "2026-09-27T21:00:00Z"}
        reading["entries"] = [_e("TD-001", pickable="no"), check("TD-002", "yes")]
        await agent._lane_news(rec, now)
        assert rec.lane_seen["ids"] == ["TD-002"] and rec.lane_seen["dropped"] == {"TD-002": "2026-09-27T21:00:00Z"}
        assert agent.store.load(sid).lane_seen["ids"] == ["TD-002"], "the pruned memory is saved"
        reading["entries"] = [_e("TD-001"), check("TD-002", "yes")]
        await agent._lane_news(rec, now)
        assert (
            len(_notes(agent, sid)) == 2
            and "gained 1 entry since you declared out of work: TD-001" in _notes(agent, sid)[1]
        )
        # an id the reading does not hold (archived, or the checkout's moment) is kept
        reading["entries"] = [check("TD-002", "yes")]
        await agent._lane_news(rec, now)
        assert rec.lane_seen["ids"] == ["TD-002", "TD-001"]
        # a gone member's memory is pruned too, though it is told nothing
        rec.state = "exited"
        reading["entries"] = [_e("TD-001"), check("TD-002", "no")]
        await agent._lane_news(rec, now)
        assert rec.lane_seen["ids"] == ["TD-001"] and len(_notes(agent, sid)) == 2
        await person.call("kill", id=sid)


@pytest.mark.parametrize("promoted", ["before", "after"])
async def test_a_live_check_live_at_the_declaration_is_told_to_nobody(agent, tmp_path, promoted):
    """The techlead's read of #1051 (§4.9b *told once by rule 6*, §6 rule 6 *the ledger as it stood
    at the declaration*): when the promote that made today's live commit live concluded before the
    declaration, the ledger then is read against it, so a check live then stood in the lane and is
    told to nobody — not after a second `none` either; promoted after the declaration, it is told
    once."""
    import json

    from sessionorc import promote

    await park_ticks(agent)
    now = datetime.now(UTC)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "docs").mkdir()
    (repo / "docs" / "technical_debt.md").write_text(
        "## TD-001: a build\n\n**Kind:** build\n\n## TD-002: a check\n\n**Kind:** live-check #5\n\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "TD-002: the build (#5)", when="2026-09-27T10:00:00Z")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    sha = _git(repo, "rev-parse", "HEAD").strip()
    agent._promotes["repo"] = {"live": sha}
    when = "2026-09-27T12:00:00+00:00" if promoted == "before" else "2026-09-27T22:00:00+00:00"
    promote.repo_dir("repo").mkdir(parents=True, exist_ok=True)
    (promote.repo_dir("repo") / "last.json").write_text(json.dumps({"sha": sha, "from": None, "at": when}))
    async with LocalClient() as person:
        led = [_e("TD-001"), {**_e("TD-002", kind="live-check"), "built": [5], "live": "yes"}]
        sid = await _finished(agent, person, repo, "w", ["free-pick"], led)
        agent._repos[str(repo)]["ledger"]["path"] = "docs/technical_debt.md"
        rec = agent.sessions[sid]
        await agent._lane_news(rec, now)
        await agent._lane_news(rec, now + timedelta(minutes=1))
        rec.out_of_work, rec.lane_seen = {"at": "2026-09-27T23:00:00Z", "why": "nothing pickable"}, None
        await agent._lane_news(rec, now + timedelta(minutes=2))  # a second `none`, after the promote
        await agent._lane_news(rec, now + timedelta(minutes=3))
        notes = _notes(agent, sid)
        if promoted == "before":
            assert notes == [] and "TD-002" in rec.lane_seen["ids"]
        else:
            assert len(notes) == 1 and "gained 1 entry since you declared out of work: TD-002" in notes[0]
        await person.call("kill", id=sid)


async def test_parking_the_ticks_lands_a_detached_pass_still_in_flight(agent):
    """TD-858: the case above failed once in a full run, its note unsent, when a promote reading the
    fixture's first tick started landed after the test had set `_promotes`, and put back a reading
    without its live commit. `park_ticks` lets such a pass land first, so what the test sets stands."""
    import asyncio

    landed = []

    async def late() -> None:
        await asyncio.sleep(0.2)  # a reading's thread, slow on a loaded machine
        agent._promotes = {}
        landed.append(True)  # its last step: set only by a pass that ran to its end

    agent._late_task = asyncio.create_task(late())  # beside the first tick's own `_promote_task`
    await park_ticks(agent)
    assert landed == [True] and agent._late_task.done(), "park_ticks returned before the pass landed"
    agent._promotes["repo"] = {"live": "abc"}
    await asyncio.sleep(0)  # nothing is left to land over it
    assert agent._promotes == {"repo": {"live": "abc"}}


async def test_parking_the_ticks_cancels_a_pass_past_its_drain_and_returns(agent, monkeypatch):
    """TD-868: a pass not finished in `PASS_DRAIN` is cancelled, so a hung reading never holds the test;
    the drain is the conftest's, patched short here, and the pass sleeps well past it."""
    import asyncio

    monkeypatch.setitem(park_ticks.__globals__, "PASS_DRAIN", 0.05)
    landed = []

    async def hung() -> None:
        await asyncio.sleep(30)
        landed.append(True)

    agent._hung_task = asyncio.create_task(hung())
    started = asyncio.get_running_loop().time()
    await park_ticks(agent)
    assert asyncio.get_running_loop().time() - started < 5, "park_ticks waited out the pass, not its drain"
    assert agent._hung_task.cancelled() and landed == []


async def test_a_decided_board_line_is_told_at_once_to_the_free_pick_lane_and_claimed_as_a_lease(agent, tmp_path):
    """TD-384 (design §6 rule 6, §4.9a): a work order, `board:<key>`, is in every `free-pick` lane
    whatever its `owner:` words; one already there when the member declared is told on the first
    tick, since it sat unclaimed; the note says to read the board; a claim on it is a lease."""
    from sessionorc import workorders

    await park_ticks(agent)
    now = datetime.now(UTC)
    order = workorders.entry({"id": "board:0123abcd", "title": "Keep the backup?", "decided": {"text": "keep"}})
    async with LocalClient() as person:
        gri = await _finished(agent, person, tmp_path, "g", ["free-pick", "owner:grinder"], [_e("TD-001")])
        des = await _finished(agent, person, tmp_path, "d", ["design-first", "owner:designer"], [_e("TD-001")])
        agent._repos[str(tmp_path)]["work_orders"] = {"orders": [order]}
        await agent._keep_running(now)
        assert agent.sessions[gri].lane_seen["ids"] == ["TD-001", "board:0123abcd"]
        notes = _notes(agent, gri)
        assert len(notes) == 1 and "board:0123abcd" in notes[0] and "read the ledger and the board" in notes[0]
        assert _notes(agent, des) == []
        await agent._lane_news(agent.sessions[gri], now + timedelta(minutes=1))
        assert len(_notes(agent, gri)) == 1, "told once"
        await person.call("progress", id=gri, ref="board:0123abcd", status="claimed", caller=gri)
        from sessionorc.client import AgentError

        with pytest.raises(AgentError, match="board:0123abcd is claimed by"):
            await person.call("progress", id=des, ref="board:0123abcd", status="claimed", caller=des)
        for sid in (gri, des):
            await person.call("kill", id=sid)


async def test_a_decided_line_a_live_sibling_holds_is_seen_untold_and_its_drop_is_told(agent, tmp_path):
    """TD-899 (design §6 rule 6): a decided line, never in the first `lane_seen`, that a live sibling of
    the repo already holds is written into it untold — so a second `none` beside it is not answered by
    a note naming it — and the sibling's later drop is told once as a dropped lease. A lease past its
    twelve hours, or held in another repo, holds nothing."""
    from sessionorc import workorders

    await park_ticks(agent)
    now = datetime.now(UTC)
    held, stale, far_held = (
        workorders.entry({"id": f"board:{k}", "title": k, "decided": {"text": "go"}}) for k in ("aa", "bb", "cc")
    )
    async with LocalClient() as person:
        led = [_e("TD-001")]
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick"], led)
        rec = agent.sessions[sid]
        sib = await _finished(agent, person, tmp_path, "grinder-2", ["free-pick"], led, out_of_work=None)
        other = tmp_path / "elsewhere"
        other.mkdir()
        far = await _finished(agent, person, other, "far", ["free-pick"], led, out_of_work=None)
        old = (now - timedelta(hours=13)).isoformat().replace("+00:00", "Z")
        agent.sessions[sib].progress = [ProgressEntry(ref="board:aa"), ProgressEntry(ref="board:bb", at=old)]
        agent.sessions[far].progress = [ProgressEntry(ref="board:cc")]
        agent._repos[str(tmp_path)]["work_orders"] = {"orders": [held, stale, far_held]}
        await agent._keep_running(now)
        assert rec.lane_seen["ids"] == ["TD-001", "board:aa", "board:bb", "board:cc"]
        notes = _notes(agent, sid)
        assert len(notes) == 1 and "gained 2 entries" in notes[0] and "board:bb, board:cc —" in notes[0]
        assert "board:aa" not in notes[0], "the held line is its holder's"
        await agent._lane_news(rec, now + timedelta(minutes=1))
        assert len(_notes(agent, sid)) == 1
        later = (datetime.now(UTC) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        agent.sessions[sib].progress = [ProgressEntry(ref="board:aa", status="dropped", why="no", at=later)]
        await agent._lane_news(rec, now + timedelta(minutes=2))
        assert len(_notes(agent, sid)) == 2 and "board:aa (dropped by grinder-2)" in _notes(agent, sid)[1]
        for s in (sid, sib, far):
            await person.call("kill", id=s)


async def test_an_entry_still_settling_is_told_only_once_it_settles(agent, tmp_path):
    """TD-710, §4.4 *A new entry settles before it is pickable*: the home marks an entry `settling` in the
    reading, and rule 6 reads the mark as no lane's, so the news waits for it to settle."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick"], [_e("TD-001")])
        rec = agent.sessions[sid]
        await agent._keep_running(now)
        assert rec.lane_seen and rec.lane_seen["ids"] == ["TD-001"]
        until = {"until": (now + timedelta(minutes=5)).isoformat()}
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [_e("TD-001"), {**_e("TD-002"), "settling": until}]
        await agent._lane_news(rec, now)
        assert _notes(agent, sid) == [] and rec.lane_seen["ids"] == ["TD-001"], "not news while it settles"
        agent._repos[str(tmp_path)]["ledger"]["entries"] = [_e("TD-001"), _e("TD-002")]
        await agent._lane_news(rec, now + timedelta(minutes=6))
        assert len(_notes(agent, sid)) == 1 and "TD-002" in _notes(agent, sid)[0]
        await person.call("kill", id=sid)


async def test_an_entry_settling_at_the_declaration_is_told_by_a_first_write_after_it_settled(agent, tmp_path):
    """TD-718 (TD-710, §4.4 *A new entry settles before it is pickable*, §6 rule 6): the first write reads
    the ledger at the declaration from git, which carries no mark, and the settle clock marks it as the
    clock stood then. An entry settling at the declaration whose window ended before a late first tick
    is not in `lane_seen`, and is told on that tick; unmarked, it would be recorded as seen, never told."""
    from sessionorc import ledger, settle

    await park_ticks(agent)
    now = datetime.now(UTC)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "docs").mkdir()
    one = "## TD-001: one\n\n**Kind:** design-first\n\n"
    two = one + "## TD-002: two\n\n**Kind:** design-first\n\n"
    for text, ago in ((one, timedelta(hours=1)), (two, timedelta(minutes=15))):
        (repo / "docs" / "technical_debt.md").write_text(text)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "ledger", when=(now - ago).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    # the clock as the tick keeps it (keyed by the path: the reading has no remote): TD-001 in the repo's
    # first reading, settled; TD-002 first seen 12 minutes ago, settling for the built-in 5m
    spans = settle.spans(repo)
    settle.observe(ledger.entries(one), str(repo), spans, now - timedelta(hours=1))
    assert settle.observe(ledger.entries(two), str(repo), spans, now - timedelta(minutes=12))[1].get("settling")
    async with LocalClient() as person:
        # the checkout's reading at the first tick: TD-002 has settled, so it carries no mark
        sid = await _finished(agent, person, repo, "d", ["design-first"], ledger.entries(two))
        agent._repos[str(repo)]["ledger"]["path"] = "docs/technical_debt.md"
        rec = agent.sessions[sid]
        rec.out_of_work = {"at": (now - timedelta(minutes=10)).isoformat(), "why": "nothing pickable"}
        await agent._lane_news(rec, now)
        await agent._lane_news(rec, now + timedelta(minutes=1))
        notes = _notes(agent, sid)
        assert len(notes) == 1 and "gained 1 entry since you declared out of work: TD-002" in notes[0]
        assert rec.lane_seen["ids"] == ["TD-001", "TD-002"]
        await person.call("kill", id=sid)


async def test_an_entry_whose_wait_ends_is_told_once_and_not_before(agent, tmp_path):
    """TD-716 (design §4.4 *An entry says what it waits for*, §6 rule 6): an entry marked `waiting`
    matches no lane, so a member that declared out of work is told nothing of it; on its date the mark
    goes and it is news to the lane, told once, as an entry filed since is."""
    from sessionorc import settle

    await park_ticks(agent)
    now = datetime.now(UTC)
    tomorrow = (now.astimezone() + timedelta(days=1)).date().isoformat()
    waits = {"on": "until", "date": tomorrow, "why": "CI runs then"}
    async with LocalClient() as person:
        led = settle.mark_waits([_e("TD-001"), {**_e("TD-002"), "waits": waits}], now)
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick", "owner:grinder"], led)
        rec = agent.sessions[sid]
        await agent._keep_running(now)
        assert rec.lane_seen["ids"] == ["TD-001"] and _notes(agent, sid) == [], "a waiting entry is no lane's"
        settle.mark_waits(agent._repos[str(tmp_path)]["ledger"]["entries"], now + timedelta(days=1))
        await agent._lane_news(rec, now)
        await agent._lane_news(rec, now + timedelta(minutes=1))
        notes = _notes(agent, sid)
        assert len(notes) == 1 and "your lane gained 1 entry since you declared out of work: TD-002" in notes[0]
        await person.call("kill", id=sid)


async def test_an_unserved_repos_lane_reads_empty_and_a_turn_to_unserved_is_told_once(agent, tmp_path):
    """TD-1011, design §5 *The seams*: an unserved repo's lane reads empty — a member out of work is told
    nothing of it, and is told once it is served again — and the person gets one `system` note when a
    served repo with a team running turns unserved."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    lack = (
        "unserved: no agent-cadence (no pin in docs/cadence.toml, no docs/cadence-sync.lock) — `ao repo add /r --adopt`"
    )
    unserved = {"serve": {"ok": False, "lacks": [{"key": "cadence", "words": lack}]}}
    async with LocalClient() as person:
        sid = await _finished(agent, person, tmp_path, "w", ["free-pick"], [_e("TD-001")])
        rec = agent.sessions[sid]
        rec.team = "grind"
        await agent._keep_running(now)
        facts = agent._repos[str(tmp_path)]
        facts["seams"] = unserved
        facts["ledger"]["entries"] = [_e("TD-001"), _e("TD-002")]
        await agent._lane_news(rec, now)
        assert _notes(agent, sid) == [], "an unserved repo's lane gains nothing"
        facts["seams"] = {"serve": {"ok": True, "lacks": []}}
        await agent._lane_news(rec, now)
        assert len(_notes(agent, sid)) == 1 and "TD-002" in _notes(agent, sid)[0]

        def told() -> list[str]:
            return [e.text for e in agent.person_inbox if e.from_ == "system" and "has no lane" in e.text]

        served = {**facts, "seams": {"serve": {"ok": True, "lacks": []}}}
        agent._turned_unserved(str(tmp_path), served, {**facts, "seams": unserved})
        assert told() == [f"{tmp_path.name} is {lack} — team grind has no lane until it is cured"]
        agent._turned_unserved(str(tmp_path), {**facts, "seams": unserved}, {**facts, "seams": unserved})
        agent._turned_unserved(str(tmp_path), {}, {**facts, "seams": unserved})  # read unserved from the first
        assert len(told()) == 1
        await person.call("kill", id=sid)
