"""The stage record on `shiftlead/state` and a move to the person (design §4.9c, §4.4, TD-2048), on a scratch repo,
its bare origin and the fake forge: a record survives a restart and reads from a second clone, the branch's writes
touch no checkout, a refused push is the flow's reason, and a move to the person lands one pull request holding the
gate, the Ask, the lifting Answers and the covering decide item, which a crash does not write twice."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _v3board import write_board

from sessionorc import board, ledgerboard
from sessionorc import ledger as ledger_mod
from shiftlead import stagerecord
from shiftlead.stagerecord import OTHER_ANSWER, StageStore, StateRefused, ask_words, new_record

BOARD = (
    "# User attention\n\nFormat: `- [ ] …`\n\nPeople: paul\n\n## Needs the user\n\n- [ ] 2026-09-21 (n/a) — filler.\n"
)
ENTRY = """## TD-{n}: A window to keep

**Priority:** Low
**Added:** 2026-11-01
**Owner:** grinder
**Status:** Open
{blocked}
**Why:** a test's.
"""
ANSWERS = {"Try again — a session builds it again": "build", "Back to design — a session designs it again": "design"}


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
    (root / "docs" / "ledger" / "TD-190.md").write_text(ENTRY.format(n=190, blocked=""))
    (root / "docs" / "ledger" / "TD-191.md").write_text(ENTRY.format(n=191, blocked=""))
    (root / "docs" / "ledger" / "TD-192.md").write_text(ENTRY.format(n=192, blocked="**Blocked by:** TD-191\n"))
    write_board(root, BOARD)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    return root


def _on_main(root: Path, tid: str) -> str:
    git(root, "fetch", "-q", "origin")
    return git(root, "show", f"origin/main:docs/ledger/{tid}.md")


def _items(root: Path) -> list[ledgerboard.BoardItem]:
    git(root, "fetch", "-q", "origin")
    b = ledgerboard.load_board(board.BOARD.as_posix(), *ledger_mod.git_io(root, "origin/main", under="docs"))
    return [it for it in b.items if it.kind == "decide"]


def _asked(store: StageStore, tid: str = "TD-190") -> dict:
    store.ensure_branch()
    store.put_entry(new_record(tid, "build-review", "build", holder="s1"), "entered")
    ask, context = ask_words("build", "not-needed", "The fix landed with TD-1900. Nothing is left.")
    return store.record_intent(tid, "paul", ask, context, ANSWERS, blocked={"stage": "build"})


def test_a_record_is_read_back_after_a_restart_and_from_another_clone(repo, tmp_path):
    store = StageStore(repo)
    store.ensure_branch()
    store.put_entry(new_record("TD-190", "build-review", "build", holder="s1"), "entered")
    assert StageStore(repo).entry("TD-190")["holder"] == "s1"  # a new store is a restarted home: nothing was cached
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", git(repo, "remote", "get-url", "origin"), str(other)], check=True)
    assert StageStore(other).entries()["TD-190"]["stage"] == "build"


def test_a_write_is_one_commit_and_touches_no_checkout(repo):
    head, status = git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")
    store = StageStore(repo)
    first = store.ensure_branch()
    second = store.put_entry(new_record("TD-190", "f", "build"), "entered")
    assert git(repo, "rev-parse", f"{second}^") == first
    assert store.put_entry(store.entry("TD-190"), "unchanged") == second  # no change, no commit
    assert (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")) == (head, status)
    assert git(repo, "symbolic-ref", "--short", "HEAD") == "main"


def test_jobs_are_kept_by_key_apart_from_entries(repo):
    store = StageStore(repo)
    store.ensure_branch()
    store.put_job({"id": "board-9099da3b", "seat": "board-answers", "waits": None}, "offered")
    store.put_job({"id": "pr-4490", "seat": "unheld-pull-requests", "waits": "person"}, "to the person")
    assert store.job("board-9099da3b")["seat"] == "board-answers"
    assert set(store.jobs()) == {"board-9099da3b", "pr-4490"}
    assert store.entries() == {} and store.job("pr-1") is None
    store.put_job({"id": "pr-4490", "seat": "unheld-pull-requests", "waits": None}, "a new job")  # over the old one
    assert store.job("pr-4490")["waits"] is None
    store.write({"jobs/notes.json": "{}\n"}, "a stray file")
    assert set(store.jobs()) == {"board-9099da3b", "pr-4490"}
    for bad in ("TD-7", "board-XYZ", "pr-0", "../pr-1"):
        with pytest.raises(ValueError):
            store.put_job({"id": bad, "waits": None}, "x")
    with pytest.raises(ValueError):
        store.put_job({"id": "pr-3", "waits": "parts?"}, "x")


def test_audits_and_the_last_good_flow_are_kept_apart(repo):
    store = StageStore(repo)
    store.ensure_branch()
    store.put_audit("ao-grind", "docs", {"holder": "s2"})
    store.put_flow("ao-grind", "format: 3\n")
    assert store.audit("ao-grind", "docs") == {"holder": "s2"}
    assert store.flow("ao-grind") == "format: 3\n"
    assert store.entries() == {}
    with pytest.raises(ValueError):
        store.put_flow("../main", "x")


def test_a_push_the_forge_refuses_is_the_flows_reason(repo, monkeypatch):
    store = StageStore(repo)
    real = store._git

    def refused(*args, **kw):
        if args[0] == "push":
            return subprocess.CompletedProcess(args, 1, "", "remote: error: GH013: a rule forbids this branch\n")
        return real(*args, **kw)

    monkeypatch.setattr(store, "_git", refused)
    with pytest.raises(StateRefused) as e:
        store.ensure_branch()
    assert "a rule forbids this branch" in e.value.reason
    assert store.tip() is None


def test_a_push_that_lost_the_race_is_made_again_on_the_new_tip(repo, tmp_path):
    store = StageStore(repo)
    store.ensure_branch()
    real, raced = store._git, []

    def beaten(*args, **kw):
        if args[0] == "push" and not raced:
            raced.append(1)
            other = tmp_path / "racer"
            subprocess.run(["git", "clone", "-q", git(repo, "remote", "get-url", "origin"), str(other)], check=True)
            git(other, "config", "user.email", "t@example.com")
            git(other, "config", "user.name", "t")
            StageStore(other).put_audit("t", "a", {"n": 1})
        return real(*args, **kw)

    store._git = beaten
    store.put_entry(new_record("TD-190", "f", "build"), "entered")
    assert raced and store.audit("t", "a") == {"n": 1} and store.entry("TD-190")


def test_the_ask_is_one_line_with_the_reason_in_its_context():
    ask, context = ask_words("build", "not-needed", "The fix landed with TD-1900.\nNothing is left.")
    assert ask == "Build ended as not needed, what next?"
    assert context == "The fix landed with TD-1900. Nothing is left."


@pytest.mark.parametrize(
    ("stage", "reason"),
    [
        ("build", " ".join(["a long reason"] * 13)),
        ("build", "It broke in `src/shiftlead/stagerecord.py` at ask_words()."),
        ("protected-read", "Fine."),
        ("src/x.py", "A stage name holding code."),
        ("one two three four five six", "A long stage name."),
    ],
)
def test_the_ask_passes_the_sentence_rule_whatever_the_reason_or_stage(stage, reason):
    ask, context = ask_words(stage, "not-needed", reason)
    assert ledgerboard.person_text_problems(ask, question=True) == []
    assert ledgerboard.sentence_problems(ask, question=True, max_words=ledgerboard.SENTENCE_WORDS) == []
    assert "`" not in ask and "/" not in ask and "_" not in ask
    assert context == " ".join(reason.split())


def test_a_move_to_the_person_is_one_pull_request_with_the_gate_and_its_item(repo):
    store = StageStore(repo)
    _asked(store)
    assert store.intents() == ["TD-190"] and "decision" not in _on_main(repo, "TD-190")
    before = git(repo, "rev-parse", "origin/main")
    got = store.land_intent("TD-190")
    entry = _on_main(repo, "TD-190")
    assert git(repo, "rev-parse", "origin/main~1") == before  # one squash
    assert "**Blocked by:** decision (paul)" in entry and "**Ask:** Build ended as not needed" in entry
    assert OTHER_ANSWER in entry and "**Lifts:** Try again | Back to design | Something else: <what>" in entry
    item = next(it for it in _items(repo) if it.context.startswith("TD-190 decision (paul)"))
    assert got["id"] == item.id and item.lifts == ["Try again", "Back to design", "Something else: <what>"]
    record = store.entry("TD-190")
    assert record["waits"] == "person" and record["intent"] is None
    assert record["answers"]["Back to design"] == "design" and record["blocked"] == {"stage": "build"}


def test_the_landed_question_passes_the_gates_coverage_and_tripwire(repo):
    store = StageStore(repo)
    _asked(store)
    store.land_intent("TD-190")
    git(repo, "fetch", "-q", "origin")

    def tree(rev: str) -> dict[str, str]:
        names = git(repo, "ls-tree", "-r", "--name-only", rev, "--", "docs").splitlines()
        return {p: git(repo, "show", f"{rev}:{p}") + "\n" for p in names}

    old, new = tree("origin/main~1"), tree("origin/main")
    subject = git(repo, "log", "-1", "--format=%s", "origin/main")
    assert ledgerboard.tripwire(old, new, subject, "repo") == []
    refusals, _flags = ledgerboard.uncovered_decisions(old, new, [], "repo")
    assert refusals == []
    io = [ledger_mod.git_io(repo, rev, under="docs") for rev in ("origin/main~1", "origin/main")]
    before, after = (ledgerboard.load_board(board.BOARD.as_posix(), *x) for x in io)
    assert [p for p in ledgerboard.board_problems(after, before) if not p[1].startswith("ℹ")] == []


def test_a_crash_after_the_merge_writes_nothing_twice(repo):
    store = StageStore(repo)
    record = _asked(store)
    got = store.land_intent("TD-190")
    store.put_entry({**store.entry("TD-190"), "intent": record["intent"], "waits": None}, "as if it crashed")
    head = git(repo, "rev-parse", "origin/main")
    again = store.land_intent("TD-190")
    assert again["already"] and got["id"]
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head
    assert store.entry("TD-190")["waits"] == "person" and store.intents() == []


def test_a_crash_then_the_persons_answer_is_not_asked_again(repo):
    store = StageStore(repo)
    record = _asked(store)
    got = store.land_intent("TD-190")
    store.put_entry({**store.entry("TD-190"), "intent": record["intent"], "waits": None}, "as if it crashed")
    board.write_back(repo, None, "", "decide", key=got["key"], answer="Try again")
    git(repo, "fetch", "-q", "origin")
    head = git(repo, "rev-parse", "origin/main")
    assert store.land_intent("TD-190") == {"already": True}
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head and store.entry("TD-190")["waits"] == "person"


def test_a_second_question_after_an_answer_is_asked(repo):
    store = StageStore(repo)
    _asked(store)
    first = store.land_intent("TD-190")
    board.write_back(repo, None, "", "decide", key=first["key"], answer="Try again")
    store.record_intent("TD-190", "paul", "Build ended as other. What next?", "A reason.", ANSWERS)
    second = store.land_intent("TD-190")
    assert second["id"] != first["id"] and "**Blocked by:** decision (paul)" in _on_main(repo, "TD-190")


def test_the_gate_joins_what_the_entry_is_already_blocked_by(repo):
    store = StageStore(repo)
    store.ensure_branch()
    store.put_entry(new_record("TD-192", "f", "build"), "entered")
    store.record_intent("TD-192", "paul", "Build ended as other. What next?", "A reason.", ANSWERS)
    store.land_intent("TD-192")
    assert "**Blocked by:** TD-191, decision (paul)" in _on_main(repo, "TD-192")
    assert any(it.context.startswith("TD-192 decision (paul)") for it in _items(repo))


def test_an_entry_already_waiting_on_a_decision_is_refused_and_keeps_its_intent(repo):
    (repo / "docs/ledger/TD-190.md").write_text(
        ENTRY.format(n=190, blocked="**Blocked by:** decision (paul)\n") + "\n**Ask:** Another question?\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "gated")
    git(repo, "push", "-q", "origin", "main")
    store = StageStore(repo)
    _asked(store)
    with pytest.raises(board.Refused, match="asked once at a time"):
        store.land_intent("TD-190")
    assert store.intents() == ["TD-190"]


def test_an_archived_entry_clears_the_intent(repo):
    store = StageStore(repo)
    _asked(store)
    (repo / "docs/ledger/archive").mkdir()
    git(repo, "mv", "docs/ledger/TD-190.md", "docs/ledger/archive/TD-190.md")
    p = repo / "docs/ledger/archive/TD-190.md"
    p.write_text(p.read_text().replace("**Status:** Open", "**Status:** Resolved 2026-11-22"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "archived")
    git(repo, "push", "-q", "origin", "main")
    assert store.land_intent("TD-190") == {"gone": True}
    assert store.entry("TD-190")["intent"] is None and store.entry("TD-190")["waits"] is None


def test_the_persons_press_lifts_the_gate_with_the_label_the_map_reads(repo):
    store = StageStore(repo)
    _asked(store)
    got = store.land_intent("TD-190")
    board.write_back(repo, None, "", "decide", key=got["key"], answer="Back to design")
    entry = _on_main(repo, "TD-190")
    assert "decision (paul)" not in entry.split("**Why:**")[0]
    assert 'answer "Back to design"' in entry
    assert store.entry("TD-190")["answers"]["Back to design"] == "design"


def test_the_person_s_own_words_fill_the_form_and_lift(repo):
    store = StageStore(repo)
    _asked(store)
    got = store.land_intent("TD-190")
    board.write_back(repo, None, "", "decide", key=got["key"], answer="Something else: split it in two")
    entry = _on_main(repo, "TD-190")
    assert "decision (paul)" not in entry.split("**Why:**")[0] and "split it in two" in entry


def test_only_the_stage_end_call_and_a_flows_save_read_the_store_so_far():
    src = Path(stagerecord.__file__).parent
    users = sorted(p.name for p in src.rglob("*.py") if p.name != "stagerecord.py" and "stagerecord" in p.read_text())
    assert users == [
        "flow_save.py",
        "job_prs.py",
        "stage_audit_end.py",
        "stage_audit_pass.py",
        "stage_end.py",
        "stage_job.py",
        "stage_job_end.py",
        "stage_job_make.py",
        "stage_job_merge.py",
        "stage_job_pass.py",
        "stage_job_tick.py",
        "stage_make.py",
        "stage_merge.py",
        "stage_pass.py",
        "stage_tick.py",
        "team_show.py",
    ]  # stage_job takes only the job key's pattern, stage_job_make, stage_job_end and stage_job_merge write a job's
    # record, stage_job_pass and stage_job_tick read the seats' records, stage_audit_pass reads and writes an audit's
    # run record, stage_audit_end writes a run's end, and team_show and job_prs only read


def test_the_home_archives_an_entry_in_one_pull_request_and_a_second_call_writes_nothing(repo):
    store = StageStore(repo)
    got = store.archive("TD-190", "the person's answer: Archive the entry")
    assert got["pr"]
    git(repo, "fetch", "-q", "origin")
    names = git(repo, "ls-tree", "-r", "--name-only", "origin/main", "docs/ledger").splitlines()
    assert "docs/ledger/archive/TD-190.md" in names and "docs/ledger/TD-190.md" not in names
    text = git(repo, "show", "origin/main:docs/ledger/archive/TD-190.md")
    assert "the person's answer: Archive the entry" in text
    head = git(repo, "rev-parse", "origin/main")
    assert store.archive("TD-190", "again") == {"gone": True}
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


def test_an_entry_another_is_blocked_by_can_be_archived_and_a_missing_one_is_gone(repo):
    store = StageStore(repo)
    assert store.archive("TD-999", "no such entry") == {"gone": True}
    assert store.archive("TD-191", "the person's answer")["pr"]
