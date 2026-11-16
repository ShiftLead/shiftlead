"""**Lift the hold**'s press (design §4.4 *The press's checks*, TD-1829, built by TD-1831): `ledger_decide` with
`lift=True` lifts the entry's `decision (paul)` itself through `board.lift_on_press`, the claims read by the one
claims helper `queue.held_claims` — and every other answer leaves the gate standing."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from _v3board import ref_of, write_board
from conftest import park_ticks, served

from sessionorc import queue as queue_mod
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import ProgressEntry

BOARD_HEAD = "# User attention\n\nFormat: `- [ ] …`\n\nPeople: paul\n\n## Needs the user\n\n"
FILLER = "2026-09-21 (n/a) — an unrelated item."
ENTRY = """## TD-{n}: A window to keep

**Priority:** Low
**Added:** 2026-11-01
**Owner:** {owner}
**Status:** Open
**Blocked by:** decision (paul)

**Ask:** Go on TD-{n}?

**Why:** a test's.
"""
DECIDED = (
    "decide 2026-11-05 (session `designer-ao-1` on kmaster) — **Go on TD-190?** Say. Context: TD-190 decision (paul). "
    "Due: 2026-11-06. Answers: Go | Not yet. Decided: Not yet (by paul) (2026-11-15)."
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, forge) -> Path:
    root = tmp_path / "repo"
    (root / "docs" / "ledger").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "docs" / "ledger" / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n")
    for n, owner in ((190, "grinder"), (191, "paul")):
        (root / "docs" / "ledger" / f"TD-{n}.md").write_text(ENTRY.format(n=n, owner=owner))
    write_board(root, BOARD_HEAD + f"- [ ] {FILLER}\n- [ ] {DECIDED}\n")
    served(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", root / "scripts", dirs_exist_ok=True)
    return root


def _entry(n: int, page: str = "for-you", owner: str = "grinder", gated: bool = True) -> dict:
    return {
        "id": f"TD-{n}", "title": "A window to keep", "for_page": page, "owner": owner,
        "blocked_by": ["decision (paul)"] if gated else [], "answers": ["Go", "Not yet"], "default": 0,
    }  # fmt: skip


async def _home(agent, repo: Path, monkeypatch, entries: list[dict]) -> str:
    root = str(repo)

    async def held() -> None:  # the reading is this test's: the tick reads no registry over it
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    monkeypatch.setattr(agent, "_read_ledger", lambda root, old_led, *a, **kw: (dict(old_led), []))
    await park_ticks(agent)
    agent._repos = {root: {"name": "repo", "root": root, "ledger": {"entries": entries}, "work_orders": {"orders": []}}}
    return root


def _origin_entry(repo: Path, n: int) -> str:
    git(repo, "fetch", "-q", "origin")
    return git(repo, "show", f"origin/main:docs/ledger/TD-{n}.md")


async def test_lift_the_hold_lifts_the_gate_where_an_open_decided_line_covers_it(agent, repo, monkeypatch):
    """The press passes where an open decided line covers the entry and it no longer sorts *for you* (both
    refusals an answer meets are skipped), lands the lift and closes the line `— lifted.`; refused to a session
    and beside a road, an answer or Go with it; a person-owned entry is *yours to do*."""
    root = await _home(agent, repo, monkeypatch, [_entry(190, page="blocked"), _entry(191, owner="paul")])
    async with LocalClient() as me:
        w = (await me.call("create", name="w", dir=str(repo.parent), adapter="shell", role="worker",
                           argv=["bash", "--norc"]))["id"]  # fmt: skip
        async with LocalClient(caller=w) as worker:
            with pytest.raises(AgentError, match="a person's own act"):
                await worker.call("ledger_decide", repo=root, id="TD-190", lift=True)
        for kw in ({"road": "done"}, {"answer": 0}, {"go": True}):
            with pytest.raises(AgentError, match="Lift the hold is a press of its own"):
                await me.call("ledger_decide", repo=root, id="TD-190", lift=True, **kw)
        with pytest.raises(AgentError, match="TD-191 is yours to do: its Done answers it"):
            await me.call("ledger_decide", repo=root, id="TD-191", lift=True)
        got = await me.call("ledger_decide", repo=root, id="TD-190", lift=True)
    assert got == {"repo": root, "id": "TD-190", "lifted": True}
    entry = _origin_entry(repo, 190)
    assert "**Blocked by:**" not in entry and 'gate lifted: decision (paul) — by paul; answer "go ahead"' in entry
    assert git(repo, "show", "--stat", "--format=%s", "origin/main").startswith(
        "shiftlead: lift decision (paul) on TD-190 (session n/a)"
    )


async def test_an_archived_or_lifted_entry_is_no_longer_held_and_nothing_is_written(agent, repo, monkeypatch):
    """`{gone: true}`: the reading's entry carries no gate (or is gone), or the tree's has been archived or lifted
    since the page was drawn — no refusal, no write."""
    root = await _home(agent, repo, monkeypatch, [_entry(190), _entry(192, gated=False)])
    (repo / "docs" / "ledger" / "TD-190.md").write_text(ENTRY.format(n=190, owner="grinder").replace(
        "**Blocked by:** decision (paul)\n", ""))  # fmt: skip
    git(repo, "commit", "-qam", "lifted elsewhere")
    git(repo, "push", "-q", "origin", "main")
    head = git(repo, "rev-parse", "origin/main")
    async with LocalClient() as me:
        for n in (190, 192, 404):
            got = await me.call("ledger_decide", repo=root, id=f"TD-{n}", lift=True)
            assert got == {"repo": root, "id": f"TD-{n}", "gone": True}
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


async def test_the_claims_reach_the_write_and_case_b_refuses_a_holder(agent, repo, monkeypatch):
    """A claim on the covering line, or on the pressed entry, refuses case (b) naming the holder; nothing is
    written."""
    root = await _home(agent, repo, monkeypatch, [_entry(190)])
    head = git(repo, "rev-parse", "origin/main")
    async with LocalClient() as me:
        for ref in (ref_of(DECIDED), "repo#TD-190"):
            claims = {ref: "ao-x-grinder-ao-2"}
            monkeypatch.setattr(queue_mod, "held_claims", lambda records, repos, now, claims=claims: claims)
            with pytest.raises(AgentError, match=f"{ref_of(DECIDED)} is being acted on by ao-x-grinder-ao-2"):
                await me.call("ledger_decide", repo=root, id="TD-190", lift=True)
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


async def test_an_ordinary_answer_on_a_gated_entry_leaves_the_gate(agent, repo, monkeypatch):
    """Every other answer writes its decided line, `Context: TD-n`, and lifts nothing (§4.4)."""
    root = await _home(agent, repo, monkeypatch, [_entry(193)])
    (repo / "docs" / "ledger" / "TD-193.md").write_text(ENTRY.format(n=193, owner="grinder"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "another")
    git(repo, "push", "-q", "origin", "main")
    async with LocalClient() as me:
        got = await me.call("ledger_decide", repo=root, id="TD-193", go=True)
    assert got["decided"] == "Go"
    assert "**Blocked by:** decision (paul)" in _origin_entry(repo, 193)


def _rec(sid: str, refs: list[tuple[str, datetime]], *, unattended: bool = True, repo: str = "/r/repo",
         state: str = "working", superseded_by: str | None = None) -> SimpleNamespace:  # fmt: skip
    progress = [ProgressEntry(ref=r, at=at.isoformat()) for r, at in refs]
    return SimpleNamespace(id=sid, name=sid, progress=progress, unattended=unattended, repo=repo, state=state,
                           superseded_by=superseded_by)  # fmt: skip


def test_held_claims_reads_unexpired_claims_of_live_unattended_records():
    """The one claims helper: a `board:<key>` claim from any repo's record; an entry id only from a record of its
    repo, a `<repo>#TD-n` ref normalised to the entry's qid; an expired claim, an ended, superseded or attended
    record holds nothing; the first record by id keeps a ref."""
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    fresh, old = now - timedelta(hours=1), now - timedelta(hours=13)
    repos = {"/r/repo": {"name": "repo", "root": "/r/repo", "ledger": {"entries": []}},
             "/r/other": {"name": "other", "root": "/r/other", "ledger": {"entries": []}}}  # fmt: skip
    recs = [
        _rec("b", [("board:0000000a", fresh), ("TD-7", fresh)]),
        _rec("a", [("TD-7", fresh), ("repo#TD-008", fresh), ("other#TD-9", fresh), ("TD-10", old)]),
        _rec("c", [("board:0000000b", fresh)], repo="/r/other"),
        _rec("d", [("board:0000000c", fresh)], unattended=False),
        _rec("e", [("board:0000000d", fresh)], state="exited"),
        _rec("f", [("board:0000000e", fresh)], superseded_by="g"),
    ]
    assert queue_mod.held_claims(recs, repos, now) == {
        "repo#TD-007": "a", "repo#TD-008": "a", "board:0000000a": "b", "board:0000000b": "c",
    }  # fmt: skip
