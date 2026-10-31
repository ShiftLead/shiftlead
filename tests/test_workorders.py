"""Work orders (design §4.4 *Board write-back*, §6 rules 6 and 8, TD-380; built — TD-384): the
board's open decided lines, read in-process through ledgerboard (TD-585), as `board:<key>` in the lanes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sessionorc import ledger as ledger_mod
from sessionorc import workorders
from sessionorc.models import Session

FORMAT = (
    "Format: `- [ ] YYYY-MM-DD (session <first-8-of-session-uuid> on <host>, or n/a) — what's needed."
    " Context: TD-NNN / PR #N / branch. Due: YYYY-MM-DD.`"
)
DECIDED = (
    "- [ ] decide 2026-10-01 (session grinder-ao-1 on kmaster) — **Keep the nightly backup?** Two copies"
    " cost space. Context: TD-777. Due: 2026-10-02. Answers: keep | drop. Decided: keep (2026-10-03)."
)
OPEN = "- [ ] act 2026-10-01 (session n/a) — **Rotate the token.** Context: TD-778. Due: 2026-10-02."
FYI = "- [ ] fyi 2026-10-01 (session n/a) — **The mirror moved.** Due: 2026-10-02. Decided: seen (2026-10-03)."


def _repo(tmp_path: Path, *lines: str) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)  # no `scripts/`: a repo with a board needs no agent-cadence
    board = ["# User Attention Board", "", FORMAT, "", "## Needs the user", "", *lines, ""]
    (root / "docs" / "user_attention.md").write_text("\n".join(board), encoding="utf-8")
    return root


@pytest.mark.unit
def test_a_decided_line_is_a_work_order_and_an_open_or_fyi_line_is_not(tmp_path):
    got = workorders.read(_repo(tmp_path, DECIDED, OPEN, FYI), fetch=False)
    assert "error" not in got
    (o,) = got["orders"]
    assert workorders.is_work_order(o["id"]) and o["title"] == "Keep the nightly backup?"
    assert o["decided"] == {"text": "keep", "date": "2026-10-03"} and "TD-777" in o["refs"]
    e = workorders.entry(o)
    assert (e["priority"], e["for_page"], e["pickable"], e["work_order"]) == ("High", "pickable", "yes", True)


@pytest.mark.unit
def test_the_key_survives_a_snooze_a_reply_and_the_decide_and_is_ledgerboards_item_key(tmp_path):
    """`board:<key>` is the first eight hex of a sha256 of the line's `item_key()` — ledgerboard's —
    so the tick's next read names the same line the same way."""
    import hashlib

    from sessionorc import ledgerboard

    first = workorders.read(_repo(tmp_path / "a", DECIDED), fetch=False)["orders"][0]["id"]
    moved = DECIDED.replace("Due: 2026-10-02", "Due: 2026-10-09").replace(
        ". Answers:", " — paul, 2026-10-03: keep both. Answers:"
    )
    again = workorders.read(_repo(tmp_path / "b", moved), fetch=False)["orders"][0]["id"]
    assert first == again
    other = workorders.read(_repo(tmp_path / "c", DECIDED.replace("nightly", "weekly")), fetch=False)
    assert other["orders"][0]["id"] != first
    assert first == "board:" + hashlib.sha256(ledgerboard.item_key(DECIDED).encode()).hexdigest()[:8]


@pytest.mark.unit
def test_no_board_is_no_work_orders_and_a_board_that_will_not_read_says_so(tmp_path):
    assert workorders.read(tmp_path, fetch=False) == {"orders": []}
    root = _repo(tmp_path, DECIDED)
    (root / "docs" / "user_attention.md").write_bytes(b"- [ ] \xff\xfe not text\n")
    got = workorders.read(root, fetch=False)
    assert got == {"error": f"{root / 'docs' / 'user_attention.md'} could not be read (UnicodeDecodeError)"}


@pytest.mark.unit
def test_a_work_order_is_in_every_free_pick_lane_whatever_its_owner_words_and_in_no_other():
    e = workorders.entry({"id": "board:0123abcd", "title": "t", "decided": {"text": "keep", "date": "2026-10-03"}})
    assert ledger_mod.lane_matches(["free-pick"], e)
    assert ledger_mod.lane_matches(["free-pick", "owner:grinder"], e)
    assert not ledger_mod.lane_matches(["design-first"], e)
    assert not ledger_mod.lane_matches(["owner:grinder"], e)
    assert not ledger_mod.lane_matches(["free-pick"], {**e, "pickable": "no"})


@pytest.mark.unit
def test_rule_eight_counts_a_work_order_as_a_gain():
    from sessionorc import work as work_mod

    m = Session(id="ao-g1", name="g1", kind="interactive", adapter="shell", dir="/tmp", lane=["free-pick"])
    m.lane_seen = {"at": "2026-10-07T00:00:00Z", "ids": ["TD-001"]}
    order = workorders.entry({"id": "board:0123abcd", "title": "t"})
    assert work_mod.gained(m, [{"id": "TD-001", "pickable": "yes", "kind": "build"}, order]) == ["board:0123abcd"]


@pytest.mark.unit
def test_the_fetch_read_falls_back_to_a_plain_one(tmp_path, monkeypatch):
    """No origin to fetch (a scratch repo): the fetch fails, the checkout's board is read, and the
    line is listed either way."""
    root = _repo(tmp_path, DECIDED)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    assert len(workorders.read(root)["orders"]) == 1
    (b,) = workorders.read_boards(root)["boards"]
    assert b["fetch_case"] == "skipped" and b["fetch_note"].startswith("fetch skipped (")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("stop", "why"),
    [
        (lambda argv, t: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, t)), "timeout"),
        (lambda argv, t: subprocess.CompletedProcess(argv, 2, b"", b"fatal: no remote\n"), "fatal: no remote"),
    ],
)
def test_a_stopped_fetch_marks_the_checkouts_board_unreached(tmp_path, monkeypatch, stop, why):
    """TD-626: the fetch stopped at our bound, or failed, and the checkout's board is read with
    *fetch skipped (<why>)* on it, so the Inbox draws *origin could not be reached*."""
    from shiftlead.ui.inbox import origin_note

    real = workorders._git

    def git(root, args, timeout):
        return stop(args, timeout) if args[0] == "fetch" else real(root, args, timeout)

    monkeypatch.setattr(workorders, "_git", git)
    got = workorders.read_boards(_repo(tmp_path, DECIDED))
    (b,) = got["boards"]
    assert (b["source"], b["fetch_note"], b["fetch_case"], b["fetch_why"]) == (
        None, f"fetch skipped ({why})", "skipped", why
    )  # fmt: skip
    assert len(b["items"]) == 1
    assert origin_note(b)["text"].startswith(f"origin could not be reached ({why}): showing the checkout's board")
    plain = workorders.read_boards(_repo(tmp_path / "plain", DECIDED), fetch=False)["boards"][0]
    assert not str(plain.get("fetch_note") or "").startswith("fetch skipped")


@pytest.mark.unit
def test_the_repo_reading_lists_them_on_a_full_read_and_keeps_them_between(tmp_path, monkeypatch):
    """`_read_repo` reads the board with the PRs, every `REPOS_EVERY`; a ledger-only re-read keeps
    the last orders, and a failed board read keeps them with the error beside them."""
    from sessionorc import reports
    from sessionorc.agent_tick import TickMixin

    monkeypatch.setattr(reports, "pr_reading", lambda root, now, **kw: {"open": []})
    root = _repo(tmp_path, DECIDED, OPEN)
    full = TickMixin._read_repos([str(root)], {}, {str(root)})[str(root)]
    (o,) = full["work_orders"]["orders"]
    assert o["work_order"] and o["title"] == "Keep the nightly backup?"
    again = TickMixin._read_repos([str(root)], {str(root): full}, set())[str(root)]
    assert again["work_orders"] == full["work_orders"]
    monkeypatch.setattr(workorders, "read_boards", lambda root, **kw: {"error": "the reader failed"})
    failed = TickMixin._read_repos([str(root)], {str(root): full}, {str(root)})[str(root)]
    assert failed["work_orders"]["orders"] == full["work_orders"]["orders"]
    assert failed["work_orders"]["error"] == "the reader failed"


@pytest.mark.unit
def test_a_plain_read_runs_nothing_and_writes_nothing_into_the_checkout(tmp_path, monkeypatch):
    """TD-585: the board is parsed in-process by the vendored ledgerboard — a plain read starts no
    process (no agent-cadence script, no git) and leaves the checkout as it was (TD-386's gate)."""
    root = _repo(tmp_path, DECIDED)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail(f"a process was started: {a}"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail(f"a process was run: {a}"))
    assert workorders.read(root, fetch=False)["orders"]
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.unit
def test_the_default_branch_is_origin_heads_then_init_default_branch_then_main(tmp_path):
    """The branch the board is compared against: origin/HEAD's target; with none, `init.defaultBranch`
    where origin has it; else `main` or `master`, else `main` (review of TD-585 slice 3)."""
    origin, seed, clone = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "clone"
    _git("init", "-q", "--bare", "-b", "trunk", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=seed)
    _git("config", "user.name", "t", cwd=seed)
    _git("checkout", "-q", "-b", "trunk", cwd=seed)
    _git("commit", "-q", "--allow-empty", "-m", "first", cwd=seed)
    _git("push", "-q", "origin", "trunk", cwd=seed)
    _git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    assert workorders.default_branch(clone) == "trunk"  # origin/HEAD, set by the clone
    _git("remote", "set-head", "origin", "-d", cwd=clone)
    assert workorders.default_branch(clone) == "main"  # nothing names it, and origin has no main
    _git("config", "init.defaultBranch", "trunk", cwd=clone)
    assert workorders.default_branch(clone) == "trunk"


@pytest.mark.unit
def test_each_case_of_the_read_against_origin(tmp_path):
    """§4.5 screen 6 *Boards are read against origin* (TD-585): the checkout's board against
    `origin/<default>` and their merge-base's, real git — *matches*; *behind*, origin's copy read and
    named as the source; *local*; *both*; *none* for an origin with no board — each case a word
    (`fetch_case`), which the Inbox's origin note reads, and a sentence for people."""
    from shiftlead.ui.inbox import origin_case

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
    board.write_text(f"{OPEN}\n")

    def case():
        (b,) = workorders.read_boards(clone)["boards"]
        return b["fetch_case"], origin_case(b["source"] or "", b["fetch_case"]), b

    assert case()[:2] == ("none", None)
    (seed / "docs").mkdir()
    (seed / "docs" / "user_attention.md").write_text(f"{OPEN}\n")
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "board", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    board.unlink()
    _git("pull", "-q", "origin", "main", cwd=clone)
    assert case()[:2] == ("matches", None)
    with (seed / "docs" / "user_attention.md").open("a") as f:
        f.write(f"{DECIDED}\n")
    _git("commit", "-qam", "a decided line", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    got, note, b = case()
    assert (got, note, b["source"]) == ("behind", "behind", "origin/main")
    assert [it["line"] for it in b["items"]] == [1, 2] and b["items"][1]["key"] == workorders.ref("", DECIDED[6:])
    _git("pull", "-q", "origin", "main", cwd=clone)
    board.write_text(board.read_text() + f"{FYI}\n")
    assert case()[:2] == ("local", "local")
    with (seed / "docs" / "user_attention.md").open("a") as f:
        f.write("- [ ] act 2026-10-02 (session n/a) — **Another.** Due: 2026-10-03.\n")
    _git("commit", "-qam", "another", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    got, note, b = case()
    assert (got, note, b["source"]) == ("both", "both", None)
    assert [it["text"].split("**")[1] for it in b["items"]] == [
        "Rotate the token.",
        "Keep the nightly backup?",
        "The mirror moved.",
    ]  # the checkout's
    # the write-back's tree: read as the checkout's board read from origin, no fetch
    tree = tmp_path / "tree.md"
    tree.write_text(f"{OPEN}\n")
    (b,) = workorders.read_boards(clone, board=tree)["boards"]
    assert (b["board"], b["source"], b["fetch_case"], len(b["items"])) == (str(board), "origin", "behind", 1)


@pytest.mark.unit
def test_every_line_has_an_id_that_a_snooze_a_reply_a_decide_and_a_close_keep_and_a_reword_changes(tmp_path):
    """§4.4 *A board line's id* (TD-603, TD-607): every board line, decided or not, has its id —
    the same before and after each tool's edit, and another after a reword. `show` finds the line by
    it, open or closed, with the reader's detail block, and is None for an id no line holds."""
    root = _repo(tmp_path, OPEN, "  more about the token", "  - not an item, the block's own list", DECIDED)
    text = OPEN.removeprefix("- [ ] ")
    key = workorders.ref(root, text)
    assert workorders.is_work_order(key)
    from sessionorc import board as board_mod

    edits = (
        board_mod.edit_line(OPEN, text, "snooze", "2026-10-09"),
        board_mod.edit_line(OPEN, text, "reply", reply="soon", by="paul", today="2026-10-03"),
        board_mod.edit_line(OPEN, text, "decide", answer="now", today="2026-10-03"),
        board_mod.edit_line(OPEN, text, "done") + " Closed: 2026-10-04.",
    )
    assert {workorders.ref(root, e.split("] ", 1)[1]) for e in edits} == {key}
    assert workorders.ref(root, text.replace("Rotate", "Revoke")) != key  # a reword is a new line
    got = workorders.show(root, key, fetch=False)
    assert got == {
        "key": key,
        "line": 7,
        "text": text,
        "detail": ["more about the token", "- not an item, the block's own list"],
        "open": True,
        "source": "checkout",
    }
    board = root / "docs" / "user_attention.md"
    board.write_text(board.read_text().replace(OPEN, OPEN.replace("- [ ]", "- [x]") + " Closed: 2026-10-04."))
    closed = workorders.show(root, key, fetch=False)
    assert closed is not None and closed["open"] is False and closed["line"] == 7
    assert workorders.show(root, "board:00000000", fetch=False) is None


@pytest.mark.unit
def test_ao_board_show_finds_a_line_by_its_id_and_refuses_one_no_line_holds(tmp_path, monkeypatch, capsys):
    """§4.7 `ao board show <board:key>` (TD-607): from the repo this directory is in, the line's
    number, text and detail block — `--json` `{key, line, text, detail, open, source}` — from the
    host agent's `boards` reading (§4.4 *The boards*, TD-615), else the checkout's file, where a
    closed line is; an id no line holds is *no line … — reworded or closed*, exit 1, and a word that
    is not an id exit 2. Read-only: `ao` runs no reader and fetches nothing."""
    import json

    from shiftlead import cli

    root = _repo(tmp_path, OPEN, "  more about the token")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    monkeypatch.chdir(root)
    repos = {str(root): {"root": str(root), "boards": workorders.read_boards(root, fetch=False)}}
    monkeypatch.setattr(cli, "call_sync", lambda method, **k: repos if method == "repos" else pytest.fail(method))
    real_run = subprocess.run

    def run(argv, *a, **k):  # git finds the checkout; no fetch is run
        assert "fetch" not in argv, argv
        return real_run(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", run)
    key = workorders.ref(root, OPEN.removeprefix("- [ ] "))
    assert cli.main(["board", "show", key, "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["key"] == key and got["line"] == 7 and got["detail"] == ["more about the token"]
    assert got["open"] is True and got["source"] == "checkout"
    assert cli.main(["board", "show", key]) == 0
    out = capsys.readouterr().out
    assert f"{key}  line 7 of docs/user_attention.md on checkout" in out and "    more about the token" in out
    assert cli.main(["board", "show", "board:00000000"]) == 1
    assert "no line board:00000000 on the board — reworded or closed" in capsys.readouterr().err
    # read from origin, the reading says so
    repos[str(root)]["boards"]["boards"][0]["source"] = "origin"
    assert cli.main(["board", "show", key, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "origin"
    # a line the reading does not hold — closed since — is the checkout's
    repos[str(root)]["boards"] = {"boards": []}
    board = root / "docs" / "user_attention.md"
    board.write_text(board.read_text().replace(OPEN, OPEN.replace("- [ ]", "- [x]") + " Closed: 2026-10-04."))
    assert cli.main(["board", "show", key, "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["open"] is False and got["line"] == 7 and got["source"] == "checkout"
    # the host agent down: the checkout's file still answers (a read is most wanted then)
    from sessionorc.client import AgentUnavailable

    def down(method, **k):
        raise AgentUnavailable("no agent")

    monkeypatch.setattr(cli, "call_sync", down)
    assert cli.main(["board", "show", key, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["line"] == 7
    assert cli.main(["board", "show", "TD-607"]) == 2
    assert not (root / "scripts").exists()  # the line is found with no agent-cadence script in the repo


# -- a red PR nobody holds (design §4.4, TD-613) ---------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from sessionorc.models import ProgressEntry  # noqa: E402

HOUR = timedelta(hours=1)
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _red(n=1573, since=T0, **kw):
    pr = {"number": n, "title": "sync agent-cadence", "url": f"https://github.com/o/r/pull/{n}", "branch": f"b{n}"}
    return {**pr, "author": "a", "checks": "red", "failing": ["test (3.13)"], "red_since": since.isoformat(), **kw}


def _rec(sid="ao-g1", state="idle", **kw):
    return Session(id=sid, name=sid, kind="interactive", adapter="shell", dir="/tmp", state=state, **kw)


@pytest.mark.unit
def test_an_unheld_red_pr_is_an_order_after_orphan_after_and_not_before():
    prs = [_red(), {"number": 9, "branch": "b9", "checks": "green"}, {"number": 8, "checks": "pending"}]
    assert workorders.red_prs(prs, [], T0 + HOUR - timedelta(seconds=1), {}, HOUR) == ([], {}, [])
    orders, told, notes = workorders.red_prs(prs, [], T0 + HOUR, {}, HOUR)
    (o,) = orders
    assert (o["id"], o["priority"], o["pickable"], o["work_order"], o["pr_order"]) == (
        "pr:1573",
        "High",
        "yes",
        True,
        True,
    )
    assert o["title"] == "sync agent-cadence"
    assert o["context"] == "https://github.com/o/r/pull/1573 · test (3.13)"
    assert (told, notes) == ({}, [])
    assert workorders.is_pr_order("pr:1573") and not workorders.is_pr_order("pr:x")
    assert not workorders.is_work_order("pr:1573")  # a board line's id is still `board:` alone
    # a conflicting one names it in its context
    (c,) = workorders.red_prs([_red(failing=[], checks="green", conflicting=True)], [], T0 + HOUR, {}, HOUR)[0]
    assert c["context"].endswith(" · conflicting")


@pytest.mark.unit
def test_a_red_pr_held_by_a_working_record_is_no_order_and_nobody_is_told():
    by_branch = _rec(state="working", git={"branch": "b1573"})
    by_claim = _rec("ao-a", state="working", progress=[ProgressEntry(ref="pr:1573")])
    by_pr = _rec("ao-b", state="working", progress=[ProgressEntry(ref="TD-613", pr=1573, status="done")])
    for r in (by_branch, by_claim, by_pr):
        assert workorders.red_prs([_red()], [r], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])
    # a holder that is gone, closed or out of work holds nothing
    for gone in (_rec(state="exited", git={"branch": "b1573"}), _rec(git={"branch": "b1573"}, out_of_work={"at": "x"})):
        assert workorders.red_prs([_red()], [gone], T0 + HOUR, {}, HOUR)[0]


@pytest.mark.unit
def test_an_idle_holder_is_told_once_then_after_a_second_bound_the_pr_is_an_order():
    holder = _rec(git={"branch": "b1573"})
    orders, told, notes = workorders.red_prs([_red()], [holder], T0 + HOUR, {}, HOUR)
    assert orders == [] and [(sid, p["number"]) for sid, p in notes] == [("ao-g1", 1573)]
    assert told == {"1573": {"red_since": T0.isoformat(), "at": (T0 + HOUR).isoformat()}}
    assert "PR #1573 has been red since" in workorders.pr_note(notes[0][1])
    assert "test (3.13) — fix it or say why" in workorders.pr_note(notes[0][1])
    # told: no second note, no order before the second bound
    later = workorders.red_prs([_red()], [holder], T0 + 2 * HOUR - timedelta(seconds=1), told, HOUR)
    assert later == ([], told, [])
    orders, kept, notes = workorders.red_prs([_red()], [holder], T0 + 2 * HOUR, told, HOUR)
    assert [o["id"] for o in orders] == ["pr:1573"] and kept == told and notes == []
    # a new red spell (another red_since) starts over: told again
    again = workorders.red_prs([_red(since=T0 + 3 * HOUR)], [holder], T0 + 4 * HOUR, told, HOUR)
    assert again[0] == [] and len(again[2]) == 1
    # green: the memory goes with it
    assert workorders.red_prs([{"number": 1573, "checks": "green"}], [holder], T0 + 2 * HOUR, told, HOUR)[1] == {}


@pytest.mark.unit
def test_a_red_pr_order_is_every_free_pick_lanes():
    """§4.9b *No anchor seat* (TD-757): the grinders' pick list, whatever owner words stand beside it."""
    o = workorders.pr_order(_red())
    assert not ledger_mod.lane_matches(["anchor"], o)
    assert ledger_mod.lane_matches(["free-pick"], o)
    assert ledger_mod.lane_matches(["free-pick", "owner:grinder"], o)
    assert not ledger_mod.lane_matches(["design-first"], o)


def _sync(n=1728, since=T0, checks="green", **kw):
    pr = {"number": n, "title": "sync dev-cadence 517a2b5", "url": f"https://github.com/o/r/pull/{n}"}
    return {**pr, "branch": f"cadence-sync-{n}", "author": "a", "checks": checks, "failing": [], "sync": True,
            "sync_since": since.isoformat(), **kw}  # fmt: skip


@pytest.mark.unit
def test_a_sync_pr_is_an_order_from_the_first_reading_whatever_its_checks_but_pending():
    """TD-684, design §4.4 *A sync PR is the team's at once*: no `ORPHAN_AFTER`, green or red; a
    pending one waits; the reason is the order's `Context` beside the URL."""
    red = _sync(1, checks="red", failing=["test (3.13)"], red_since=T0.isoformat())
    cases = {
        "green": (_sync(2), "green: review and merge it"),
        "red": (red, "test (3.13)"),
        "conflicting": (_sync(3, conflicting=True), "conflicting"),
        "draft": (_sync(4, draft=True), "draft"),
    }
    for word, (pr, reason) in cases.items():
        (o,) = workorders.red_prs([pr], [], T0, {}, HOUR)[0]
        assert (o["id"], o["sync"], o["reason"]) == (f"pr:{pr['number']}", True, reason), word
        assert o["context"] == f"{pr['url']} · {reason}" and o["sync_since"] == T0.isoformat(), word
        assert o["pr_order"] and o["priority"] == "High" and o["pickable"] == "yes", word
    assert workorders.red_prs([_sync(checks="pending")], [], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])
    # a conflicting one runs no checks, so pending never clears: it is an order at once
    (o,) = workorders.red_prs([_sync(checks="pending", conflicting=True)], [], T0, {}, HOUR)[0]
    assert (o["sync"], o["reason"]) == (True, "conflicting")
    # a cadence-sync branch whose files lack the lock is no sync PR: a green one is never an order
    assert workorders.red_prs([_sync(sync=False)], [], T0 + 3 * HOUR, {}, HOUR)[0] == []
    # sync orders come first, before a red PR's
    orders = workorders.red_prs([_red(since=T0 - HOUR), _sync()], [], T0, {}, HOUR)[0]
    assert [o["id"] for o in orders] == ["pr:1728", "pr:1573"]
    assert "sync" not in orders[1]


@pytest.mark.unit
def test_a_held_sync_pr_is_no_order_and_its_idle_holder_is_told_then_passed_over_on_sync_since():
    working = _rec(state="working", git={"branch": "cadence-sync-1728"})
    assert workorders.red_prs([_sync()], [working], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])
    holder = _rec(progress=[ProgressEntry(ref="pr:1728")])
    assert workorders.red_prs([_sync()], [holder], T0 + HOUR - timedelta(seconds=1), {}, HOUR) == ([], {}, [])
    orders, told, notes = workorders.red_prs([_sync()], [holder], T0 + HOUR, {}, HOUR)
    assert orders == [] and [(sid, p["number"]) for sid, p in notes] == [("ao-g1", 1728)]
    assert told == {"1728": {"red_since": T0.isoformat(), "at": (T0 + HOUR).isoformat()}}
    note = workorders.pr_note(notes[0][1])
    assert note.startswith("sync PR #1728 has been open since") and "green: review and merge it" in note
    assert workorders.red_prs([_sync()], [holder], T0 + 2 * HOUR - timedelta(seconds=1), told, HOUR)[0] == []
    orders, kept, notes = workorders.red_prs([_sync()], [holder], T0 + 2 * HOUR, told, HOUR)
    assert [o["id"] for o in orders] == ["pr:1728"] and orders[0]["sync"] and kept == told and notes == []


@pytest.mark.unit
def test_a_red_draft_is_no_order_held_or_not_and_an_order_once_ready():
    """TD-745, design §4.4 *A draft is no work order*: no order, no note and no told entry for a draft,
    however long it is red; marked ready, it is an order on the next reading."""
    draft = _red(draft=True)
    assert workorders.red_prs([draft], [], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])
    holder = _rec(git={"branch": "b1573"})  # idle: a ready PR's holder would be told
    assert workorders.red_prs([draft], [holder], T0 + HOUR, {}, HOUR) == ([], {}, [])
    assert workorders.red_prs([draft], [holder], T0 + 2 * HOUR, {}, HOUR) == ([], {}, [])
    assert [o["id"] for o in workorders.red_prs([_red()], [], T0 + 3 * HOUR, {}, HOUR)[0]] == ["pr:1573"]
    # a sync draft is still the sync rule's: an order at once, but a pending one waits as any sync PR does
    assert [o["id"] for o in workorders.red_prs([_sync(draft=True)], [], T0, {}, HOUR)[0]] == ["pr:1728"]
    assert workorders.red_prs([_sync(draft=True, checks="pending")], [], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])


@pytest.mark.unit
def test_a_red_forks_pr_is_no_order_and_no_note_held_or_not():
    """TD-1285, design §4.4 *A fork's PR is no work order*: a stranger's code is never handed to a
    session to run, so a fork's PR red past the bound is no order, and its idle holder is not told."""
    fork = _red(fork=True)
    assert workorders.red_prs([fork], [], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])
    holder = _rec(git={"branch": "b1573"})
    assert workorders.red_prs([fork], [holder], T0 + HOUR, {}, HOUR) == ([], {}, [])
    assert workorders.red_prs([fork], [holder], T0 + 3 * HOUR, {}, HOUR) == ([], {}, [])
    assert [o["id"] for o in workorders.red_prs([_red(fork=False)], [], T0 + 3 * HOUR, {}, HOUR)[0]] == ["pr:1573"]


@pytest.mark.unit
def test_a_holder_told_before_a_draft_is_not_told_again_once_it_is_ready():
    """The memory of an earlier non-draft spell survives the draft (TD-745): readied within `after` of the
    tell, no second note and no order yet; readied past it, an order at once and still no second note."""
    holder = _rec(git={"branch": "b1573"})
    _, told, notes = workorders.red_prs([_red()], [holder], T0 + HOUR, {}, HOUR)
    assert len(notes) == 1
    assert workorders.red_prs([_red(draft=True)], [holder], T0 + HOUR + HOUR / 2, told, HOUR) == ([], told, [])
    assert workorders.red_prs([_red()], [holder], T0 + 2 * HOUR - timedelta(seconds=1), told, HOUR) == ([], told, [])
    orders, kept, notes = workorders.red_prs([_red()], [holder], T0 + 3 * HOUR, told, HOUR)
    assert [o["id"] for o in orders] == ["pr:1573"] and kept == told and notes == []


@pytest.mark.unit
def test_the_holders_of_a_red_pr_are_named_past_the_bound():
    """TD-652: the reading names each red PR's holders, for the pages' *held by <name>*: a live
    record on its head or with a claim on it, never one that ended or is out of work."""
    on_head = _rec("ao-h", state="working", git={"branch": "b1573"})
    claimed = _rec("ao-c", progress=[ProgressEntry(ref="pr:1573")])
    ended = _rec("ao-e", state="exited", git={"branch": "b1573"})
    out = _rec("ao-o", git={"branch": "b1573"}, out_of_work={"at": "x"})
    recs = [on_head, claimed, ended, out]
    assert workorders.red_holders([_red()], recs, T0 + HOUR, HOUR) == {"1573": ["ao-h", "ao-c"]}
    assert workorders.red_holders([_red()], recs, T0 + HOUR - timedelta(seconds=1), HOUR) == {}  # before the bound
    assert workorders.red_holders([_red()], [ended, out], T0 + HOUR, HOUR) == {}  # nobody's: the order names it
    assert workorders.red_holders([{"number": 9, "checks": "green"}], recs, T0 + HOUR, HOUR) == {}
    naive = _red(since=T0.replace(tzinfo=None))  # a stamp with no offset is UTC
    assert workorders.red_holders([naive], [on_head], T0 + HOUR, HOUR) == {"1573": ["ao-h"]}


async def test_the_home_tells_an_idle_holder_and_lists_an_unheld_red_pr(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    holder = _rec("ao-holder", git={"branch": "b1"}, repo=root, host=agent.host)
    elsewhere = _rec("ao-other", state="working", git={"branch": "b2"}, repo=str(tmp_path / "other"))
    agent.sessions[holder.id] = holder
    agent.sessions[elsewhere.id] = elsewhere
    agent._repos[root] = {"name": "repo", "root": root, "prs": {"open": [_red(1, branch="b1"), _red(2, branch="b2")]}}
    now = T0 + HOUR
    await agent._red_prs(now)
    po = agent._repos[root]["pr_orders"]
    # PR 2's head is a branch of a session in another repo: it holds nothing here
    assert [o["id"] for o in po["orders"]] == ["pr:2"] and set(po["told"]) == {"1"}
    assert po["held"] == {"1": ["ao-holder"]}
    # the page reads the reading's holders and names the one the home found (TD-652)
    from shiftlead import teamrun

    views = [{**s.to_dict(), "state": s.state} for s in (holder, elsewhere)]
    whose = {x["number"]: x["whose"] for x in teamrun.red_prs({**agent._repos[root], "root": root}, views, now)}
    assert whose == {1: "held by ao-holder", 2: "nobody's"}
    (note,) = [e for e in agent.sessions["ao-holder"].inbox if e.from_ == "system"]
    assert note.text.startswith("PR #1 has been red since") and note.uncharged
    await agent._red_prs(now + timedelta(minutes=5))  # once per red spell
    assert len([e for e in agent.sessions["ao-holder"].inbox if e.from_ == "system"]) == 1
    from sessionorc.agent_tick import _orders

    assert [o["id"] for o in _orders(agent._repos[root])] == ["pr:2"]


async def test_an_unserved_repo_has_no_red_pr_order_and_tells_no_holder(agent, tmp_path):
    """TD-1011, design §5 *The seams*: no order in an unserved repo, and no idle holder told."""
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    holder = _rec("ao-holder", git={"branch": "b1"}, repo=root, host=agent.host)
    agent.sessions[holder.id] = holder
    lacks = [{"key": "gate", "words": "unserved: no gate (no scripts/check_cadence.py) — cure"}]
    agent._repos[root] = {
        "name": "repo", "root": root, "prs": {"open": [_red(1, branch="b1"), _red(2, branch="b2")]},
        "seams": {"serve": {"ok": False, "lacks": lacks}},
    }  # fmt: skip
    await agent._red_prs(T0 + HOUR)
    assert not (agent._repos[root].get("pr_orders") or {}).get("orders")
    assert not [e for e in agent.sessions["ao-holder"].inbox if e.from_ == "system"]


async def test_an_idle_holder_on_a_node_is_told_at_its_address(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    node = _rec("ao-far", git={"branch": "b1"}, repo=root, host="far")
    agent.remote["far"] = {node.id: node}
    agent._repos[root] = {"name": "repo", "root": root, "prs": {"open": [_red(1, branch="b1")]}}
    await agent._red_prs(T0 + HOUR)
    assert agent._repos[root]["pr_orders"]["orders"] == []
    (note,) = [e for e in node.inbox if e.from_ == "system"]
    assert note.to == ["ao-far@far"] and note.text.startswith("PR #1 has been red")


# -- the boards are the host agent's reading (§4.4 *Each reading has one owner*, TD-615) ---------------


@pytest.mark.unit
def test_the_board_reading_carries_every_item_with_its_id_and_the_orders_are_its_decided_subset(tmp_path):
    root = _repo(tmp_path, DECIDED, OPEN, FYI)
    got = workorders.read_boards(root, fetch=False)
    (b,) = got["boards"]
    assert b["board"] == str(root / workorders.BOARD) and got["today"]
    assert len(b["items"]) == 3 and all(workorders.is_work_order(it["key"]) for it in b["items"])
    assert all(it["detail"] == [] and "due" in it for it in b["items"])  # the reader's own fields, kept
    (o,) = workorders.orders(got)
    assert o["id"] == b["items"][0]["key"] and o["title"] == "Keep the nightly backup?"
    assert workorders.read(root, fetch=False) == {"orders": [o]}


@pytest.mark.unit
def test_a_write_backs_tree_is_read_as_the_checkouts_board_from_origin(tmp_path):
    """After a press the host agent reads its own tree — origin's head, the press landed — named as
    the checkout's board read from origin, so the Inbox draws the press and the *behind* note."""
    root = _repo(tmp_path, DECIDED, OPEN)
    tree = tmp_path / "tree" / "user_attention.md"
    tree.parent.mkdir()
    tree.write_text((root / workorders.BOARD).read_text().replace(DECIDED + "\n", ""), encoding="utf-8")
    (b,) = workorders.read_boards(root, fetch=False, board=tree)["boards"]
    assert (b["board"], b["root"], b["label"]) == (str(root / workorders.BOARD), str(root), "repo")
    assert b["source"] == "origin"
    assert [it["text"] for it in b["items"]] == [OPEN.removeprefix("- [ ] ")]


@pytest.mark.unit
def test_the_boards_clock_rereads_only_a_moved_board_and_the_full_pass_fetches(tmp_path, monkeypatch):
    """`BOARD_EVERY` reads the checkout plainly, and only when its board's file or the day moved; the
    `REPOS_EVERY` pass reads with the reader's `--fetch`; a failed read keeps the last items and orders
    with the error and its time beside them, and the next tick of the clock reads again."""
    from sessionorc.agent_tick import TickMixin

    root = _repo(tmp_path, DECIDED, OPEN)
    real = workorders.read_boards
    calls: list[bool] = []

    def spy(r, *, fetch=True, board=None):
        calls.append(fetch)
        return real(r, fetch=False, board=board)

    monkeypatch.setattr(workorders, "read_boards", spy)
    bds, wos = TickMixin._read_boards(str(root), {}, False, True, "t1")
    assert calls == [False] and len(bds["boards"][0]["items"]) == 2 and len(wos["orders"]) == 1
    old = {"boards": bds, "work_orders": wos}
    assert TickMixin._read_boards(str(root), old, False, True, "t2") == (bds, wos) and calls == [False]
    assert TickMixin._read_boards(str(root), old, False, False, "t2") == (bds, wos) and calls == [False]
    TickMixin._read_boards(str(root), old, True, False, "t3")
    assert calls == [False, True]  # the full pass, against origin
    board = root / workorders.BOARD
    board.write_text(board.read_text().replace(OPEN + "\n", ""), encoding="utf-8")
    moved, _ = TickMixin._read_boards(str(root), old, False, True, "t4")
    assert calls == [False, True, False] and len(moved["boards"][0]["items"]) == 1

    monkeypatch.setattr(workorders, "read_boards", lambda r, **kw: {"error": "the reader failed"})
    failed, fwos = TickMixin._read_boards(str(root), {"boards": moved, "work_orders": wos}, True, False, "t5")
    assert failed["boards"] == moved["boards"] and (failed["error"], failed["failed_at"]) == ("the reader failed", "t5")
    assert fwos["orders"] == wos["orders"] and fwos["error"] == "the reader failed"
    # the same error on the next tick is the same reading: nothing saved, nothing pushed
    old_failed = {"boards": failed, "work_orders": fwos}
    assert TickMixin._read_boards(str(root), old_failed, False, True, "t5b") == (failed, fwos)
    monkeypatch.setattr(workorders, "read_boards", spy)
    again, _ = TickMixin._read_boards(str(root), {"boards": failed, "work_orders": fwos}, False, True, "t6")
    assert "error" not in again and calls[-1] is False

    # a new day re-reads; a board last read from origin is read against origin again, not the checkout
    yesterday = {**again, "today": "2000-01-01"}
    TickMixin._read_boards(str(root), {"boards": yesterday, "work_orders": wos}, False, True, "t7")
    assert calls[-1] is False
    pulled_not = {**yesterday, "boards": [{**yesterday["boards"][0], "source": "origin"}]}
    TickMixin._read_boards(str(root), {"boards": pulled_not, "work_orders": wos}, False, True, "t8")
    assert calls[-1] is True


@pytest.mark.unit
def test_a_pass_for_the_board_alone_keeps_the_ledger_unread(tmp_path, monkeypatch):
    """`_read_repos` with the board's clock and no ledger due reads the board and leaves the ledger
    as the last reading had it — the 200k-token file is not parsed every minute."""
    from sessionorc import reports
    from sessionorc.agent_tick import TickMixin

    monkeypatch.setattr(reports, "pr_reading", lambda root, now, **kw: {"open": []})
    root = _repo(tmp_path, DECIDED)
    full = TickMixin._read_repos([str(root)], {}, {str(root)})[str(root)]
    assert full["boards"]["boards"][0]["items"]
    monkeypatch.setattr(ledger_mod, "reading", lambda *a, **kw: pytest.fail("the ledger was read"))
    (root / workorders.BOARD).write_text((root / workorders.BOARD).read_text().replace(DECIDED + "\n", ""))
    alone = TickMixin._read_repos([str(root)], {str(root): full}, set(), None, None, set(), True)[str(root)]
    assert alone["ledger"] == full["ledger"]
    assert alone["boards"]["boards"][0]["items"] == [] and alone["work_orders"]["orders"] == []


async def test_a_red_pr_rows_snooze_is_kept_by_repo_and_number(agent):
    """§4.5a *Inbox row: red PR* (TD-618 slice 4): its Snooze ▾ is the attention store's, keyed
    `red_pr:<repo>:<n>` — a PR, not a record."""
    from conftest import park_ticks

    from sessionorc.client import LocalClient

    await park_ticks(agent)
    async with LocalClient() as person:
        got = await person.call("attention_snooze", id="red_pr:samscrape:802", kind="red_pr", until="2030-01-01")
    assert got["row"] == "red_pr:samscrape:802|red_pr" and agent.attention_snoozed[got["row"]] == "2030-01-01"
