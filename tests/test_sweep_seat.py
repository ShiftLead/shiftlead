"""TD-1090, design §4.9b *The sweep*: the `sweeper` seat preset and its built-in brief, the `swept: <d>`
trigger, the boards reading's `swept` stamp read from origin, and rule 3's `swept` cause — due when the
board's `Swept:` stamp is `d` old or absent, once per `d` since the last fill for it."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import park_ticks

from sessionorc import paths, workorders
from sessionorc.agent_tick import FILLED_FOR, TickMixin, filled_for
from sessionorc.client import LocalClient
from shiftlead import org as orgmod
from shiftlead import repoconfig

OPEN = "- [ ] act 2026-10-01 (session n/a) — **Rotate the token.** Context: TD-778. Due: 2026-10-02."


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# ── the trigger and the preset ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_a_swept_trigger_parses_in_everys_units_and_says_so_on_the_card(tmp_path):
    raw = [{"name": "sweep-ao-1", "role": "sweeper", "trigger": {"swept": "7d"}}]
    (seat,) = orgmod._seats("ao-grind", raw, "teams.ao-grind.seats", {})
    assert (seat.name, seat.role, seat.trigger, seat.after, seat.brief) == (
        "sweep-ao-1",
        "sweeper",
        "swept",
        "7d",
        None,
    )
    assert seat.when() == "sweeps when unswept 7 d"  # §4.9b *What a sweep seat's card says*
    for bad in ("7", "0d", "1w", 7):
        with pytest.raises(ValueError, match=r"\.swept must be a duration"):
            orgmod._trigger({"swept": bad}, "seat.trigger")


@pytest.mark.unit
def test_the_sweeper_preset_is_a_seat_whose_brief_holds_every_rule_of_what_it_may_change(tmp_path):
    role = repoconfig.resolve_role(repoconfig.load(tmp_path), "sweeper")
    p = repoconfig.PRESETS["sweeper"]
    assert (p["kind"], p["lane"], p["grants"], p["label"], p["brief"]) == ("seat", [], [], "Sweeper", "sweeper.md")
    assert p["icon"] in repoconfig.ICONS and p["context"] == repoconfig.WORKER_CONTEXT
    text, _ = role.compose()
    # the procedure by both roads, never its steps
    assert "`agent-cadence path procedures/stranded-work.md`" in text and "`docs/procedures/stranded-work.md`" in text
    assert "`Swept-deep:`" in text and "`deep-sweep-every`" in text  # deep or quick
    for rule in (
        "only once you have verified it done",  # a close is verified, and says how
        "Never close on a ref's state alone",
        "`escalate-overdue-days`",  # overdue work is ledgered
        "`ao td reserve`",
        "ALLOW_MAIN_PUSH=1 git push origin <sha>:<default>",  # the stamp-only push
        "Never push your branch to the default branch",
        "redone on the new one",
        "a PR of its own",  # every other change
        "as **one** `note`",  # the person's items
        "an `ask` per decision with your recommendation first",
        "You answer nothing for the person, and you move no `Due:` date",
        "you never write it",  # another repo's board
        "`sweep/<date>`",
        "**You declare nothing**",
    ):
        assert rule in text, rule


# ── the stamp, read from origin ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_the_stamp_is_the_first_swept_line_carrying_a_calendar_date():
    content = "# Board\nSwept: junk\nSwept: 2026-10-20 (kmaster, quick)\nSwept: 2026-10-25\nSwept-deep: 2026-09-01\n"
    assert workorders.swept(content) == {"at": "2026-10-20", "deep_at": "2026-09-01"}
    assert workorders.swept("# Board\n") == {"at": None, "deep_at": None}  # never swept
    assert workorders.swept("Swept: 2026-13-45 (kmaster, quick)\n")["at"] is None  # not a date: absent
    assert workorders.swept("Swept-deep: 2026-10-01\n")["at"] is None  # `^Swept:` never matches the deep line


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _push(seed: Path, text: str, msg: str) -> None:
    (seed / "docs").mkdir(exist_ok=True)
    (seed / "docs" / "user_attention.md").write_text(text)
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", msg, cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)


@pytest.mark.unit
def test_swept_is_origins_stamp_in_every_case_of_the_read_against_origin(tmp_path):
    origin, seed, clone = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "clone"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=seed)
    _git("config", "user.name", "t", cwd=seed)
    (seed / "README").write_text("x\n")
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "first", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    _git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    (clone / "docs").mkdir()
    board = clone / "docs" / "user_attention.md"
    board.write_text(f"Swept: 2026-10-01 (kmaster, quick)\n{OPEN}\n")

    def read():
        (b,) = workorders.read_boards(clone)["boards"]
        return b["fetch_case"], b["swept"]

    assert read() == ("none", None)  # no board on origin: no reading, no cause
    _push(seed, f"{OPEN}\n", "a board never swept")
    board.unlink()
    _git("pull", "-q", "origin", "main", cwd=clone)
    assert read() == ("matches", {"at": None, "deep_at": None})  # a board without the line: due
    _push(seed, f"Swept: 2026-10-20 (kmaster, deep)\nSwept-deep: 2026-10-20\n{OPEN}\n", "swept")
    assert read() == ("behind", {"at": "2026-10-20", "deep_at": "2026-10-20"})
    _git("pull", "-q", "origin", "main", cwd=clone)
    board.write_text(board.read_text().replace("2026-10-20 (kmaster, deep)", "2026-10-21 (kmaster, quick)"))
    assert read() == ("local", {"at": "2026-10-20", "deep_at": "2026-10-20"})  # origin's, not the checkout's
    _push(seed, f"Swept: 2026-10-22 (kmaster, quick)\nSwept-deep: 2026-10-20\n{OPEN}\n", "swept again")
    assert read() == ("both", {"at": "2026-10-22", "deep_at": "2026-10-20"})
    # the write-back's tree is origin's head with the press landed: its stamp
    tree = tmp_path / "tree.md"
    tree.write_text(f"Swept: 2026-10-23\n{OPEN}\n")
    (b,) = workorders.read_boards(clone, board=tree)["boards"]
    assert b["swept"] == {"at": "2026-10-23", "deep_at": None}
    # a plain read of the checkout, and a fetch that failed, write no `swept`
    assert "swept" not in workorders.read_boards(clone, fetch=False)["boards"][0]
    _git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=clone)
    (b,) = workorders.read_boards(clone)["boards"]
    assert b["fetch_case"] == "skipped" and "swept" not in b


@pytest.mark.unit
def test_a_read_of_the_checkout_alone_carries_the_last_swept_forward(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "user_attention.md").write_text(f"{OPEN}\n")
    stamp = {"at": "2026-10-20", "deep_at": None}
    old_board = {"label": "repo", "root": str(root), "swept": stamp, "items": []}
    other = {"label": "other", "root": str(tmp_path / "other"), "swept": {"at": "2026-01-01", "deep_at": None}}
    old = {"boards": {"boards": [old_board, other], "today": "2000-01-01", "file": None}}
    bds, _ = TickMixin._read_boards(str(root), old, False, True, "t1")  # the clock's plain re-read
    assert bds["boards"][0]["swept"] == stamp, "kept, keyed by its root and label"
    real = workorders.read_boards
    monkeypatch.setattr(
        workorders, "read_boards", lambda r, **kw: {"boards": [{**real(r, fetch=False)["boards"][0], "swept": None}]}
    )
    bds, _ = TickMixin._read_boards(str(root), old, True, False, "t2")
    assert bds["boards"][0]["swept"] is None, "a read against origin writes it, null as much as a date"


# ── rule 3's cause ─────────────────────────────────────────────────────────────────────────────


async def _sweeper(person, tmp_path, name="sweep", after="7d"):
    params = {
        "name": name,
        "dir": str(tmp_path),
        "repo": str(tmp_path),
        "adapter": "shell",
        "argv": ["bash", "--norc", "--noprofile"],
        "unattended": True,
        "supervised": True,
        "prompt": "the sweeper's brief",
        "seat": {"trigger": "swept", "after": after},
    }
    return (await person.call("create", **params))["id"]


def _board(agent, tmp_path, swept, error: str | None = None) -> None:
    b = {"label": tmp_path.name, "root": str(tmp_path), "items": []}
    if swept != "absent":
        b["swept"] = swept
    # another repo's board ahead of the seat's, its stamp the opposite cause (TD-1109): the seat reads its own
    mine_due = isinstance(swept, dict) and (not swept.get("at") or swept["at"] <= _ago(7))
    other = {"label": "other", "root": str(tmp_path / "other"), "items": []}
    other["swept"] = {"at": _ago(0) if mine_due else _ago(30), "deep_at": None}
    reading = {"boards": [other, b], **({"error": error} if error else {})}
    agent._repos[str(tmp_path)] = {"boards": reading}


def _end(agent, sid: str) -> None:
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.exit_code = "exited", True, 0
    agent.store.save(rec)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("swept", "error", "due"),
    [
        ({"at": _ago(8), "deep_at": None}, None, True),
        ({"at": None, "deep_at": None}, None, True),  # never swept
        ({"at": _ago(2), "deep_at": None}, None, False),
        ({"at": _ago(-10), "deep_at": None}, None, False),  # a future date is not due until it ages
        (None, None, False),  # no board on origin
        ("absent", None, False),  # no read against origin yet
        ({"at": None, "deep_at": None}, "the reader failed", False),  # an error reading sets nothing
    ],
    ids=["8d", "never", "2d", "future", "no-origin-board", "unread", "error"],
)
async def test_the_swept_cause_reads_the_repos_stamp(agent, tmp_path, swept, error, due):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _sweeper(person, tmp_path)
        rec = agent.sessions[sid]
        _board(agent, tmp_path, swept, error)
        await agent._keep_running(datetime.now(UTC))
        assert bool(rec.seat_due) is due and (not due or rec.seat_due["by"] == "swept")
        assert agent.sessions[sid] is rec, "it runs: nothing to fill"
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_swept_fill_is_remembered_and_not_due_again_within_its_duration(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _sweeper(person, tmp_path)
        first = agent.sessions[sid]
        _end(agent, sid)
        _board(agent, tmp_path, {"at": _ago(8), "deep_at": None})
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not first and [r["why"] for r in new.restarts] == ["fill"], "filled for the stamp"
        assert [{k: v for k, v in e.items() if k != "at"} for e in new.seat_filled] == [{"by": "swept"}]
        launch = json.loads((paths.launch_dir() / f"{sid}.json").read_text())
        assert FILLED_FOR not in launch["prompt"], "a sweep's fill says nothing of why it came"
        assert filled_for({"by": "swept"}) is None
        # the run ended without stamping: not due again within 7 days of the fill, due after
        _end(agent, sid)
        await agent._keep_running(now + timedelta(days=6))
        assert agent.sessions[sid] is new and new.seat_due is None
        agent._profile_gated = lambda *a: True  # due, not filled into a pause
        await agent._keep_running(now + timedelta(days=7, minutes=1))
        assert new.seat_due and new.seat_due["by"] == "swept"
        del agent._profile_gated
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_standing_swept_due_is_read_again_and_an_unreadable_board_fills_nothing(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _sweeper(person, tmp_path)
        rec = agent.sessions[sid]
        _end(agent, sid)
        _board(agent, tmp_path, {"at": _ago(8), "deep_at": None})
        agent._profile_gated = lambda *a: True  # due, held by a pause
        await agent._keep_running(now)
        first = rec.seat_due
        assert first and first["by"] == "swept"
        await agent._keep_running(now)
        assert rec.seat_due is first, "the standing due keeps its first `at`"
        del agent._profile_gated
        _board(agent, tmp_path, {"at": _ago(8), "deep_at": None}, error="the reader failed")
        await agent._keep_running(now)
        assert agent.sessions[sid] is rec and rec.seat_due is None, "an unreadable board fills nothing"
        _board(agent, tmp_path, {"at": _ago(0), "deep_at": None})  # swept by hand meanwhile
        await agent._keep_running(now)
        assert agent.sessions[sid] is rec and rec.seat_due is None
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_an_idle_sweeper_whose_cause_was_met_while_it_ran_is_closed(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _sweeper(person, tmp_path)
        rec = agent.sessions[sid]
        _board(agent, tmp_path, {"at": None, "deep_at": None})
        await agent._keep_running(now)
        assert rec.seat_due and rec.seat_due["by"] == "swept" and rec.state != "closed", "due while it runs"
        assert agent._seat_done(rec), "the due is the next run's"
        await person.call("kill", id=sid)


@pytest.mark.unit
def test_a_sweeper_seat_line_reads_from_an_org_file(tmp_path):
    doc = {
        "teams": {
            "ao-grind": {
                "repo": "shiftlead",
                "seats": [{"name": "sweep-ao-1", "role": "sweeper", "trigger": {"swept": "7d"}}],
            }
        }
    }
    path = tmp_path / "org.yml"
    path.write_text(yaml.safe_dump(doc))
    (seat,) = orgmod.load(path).teams["ao-grind"].seats
    assert (seat.role, seat.trigger, seat.after, seat.brief) == ("sweeper", "swept", "7d", None)


@pytest.mark.unit
def test_a_sweep_seats_card_says_how_long_ago_its_repo_was_swept(tmp_path):
    from shiftlead.ui.cards import view

    rec = {
        "id": "ao-sweep",
        "name": "sweep-ao-1",
        "state": "closed",
        "repo": str(tmp_path),
        "seat": {"trigger": "swept", "after": "7d"},
    }
    seats = {"ao-sweep": "sweeps when unswept 7 d"}

    def words(swept, **reading):
        board = {"root": str(tmp_path), "label": "x", "items": []}
        if swept != "-":
            board["swept"] = swept
        # another repo's board ahead of the seat's, with a stamp of its own (TD-1109): never the one printed
        other = {"root": str(tmp_path / "other"), "label": "y", "items": [], "swept": {"at": _ago(5), "deep_at": None}}
        repos = {str(tmp_path): {"boards": {"boards": [other, board], **reading}}}
        return view(rec, seats=seats, repos=repos)["slot"]["text"]

    assert words({"at": _ago(3), "deep_at": None}) == "on call — sweeps when unswept 7 d · swept 3 d ago"
    assert words({"at": _ago(0), "deep_at": None}) == "on call — sweeps when unswept 7 d · swept today"
    assert words({"at": _ago(-3), "deep_at": None}) == "on call — sweeps when unswept 7 d · swept today"  # ahead
    assert words({"at": None, "deep_at": None}) == "on call — sweeps when unswept 7 d · never swept"
    # no board on origin, no `swept` yet, or an unreadable board: nothing guessed
    for swept, reading in ((None, {}), ("-", {}), ({"at": _ago(3)}, {"error": "boom"})):
        assert words(swept, **reading) == "on call — sweeps when unswept 7 d"
    assert view(rec, seats=seats)["slot"]["text"] == "on call — sweeps when unswept 7 d"
