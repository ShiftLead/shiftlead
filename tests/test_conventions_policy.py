"""TD-258 slice 3, design §6 *Keeping a team running* rule 12: conventions relayed by the tick. The
home runs `scripts/cadence_changes.py --json` in a member's registry root, writes the headings the
member started with on its `conventions_seen`, and sends one `system` note for those that landed
after its `created`."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from sessionorc import agent_tick, cadence, conventions
from sessionorc.models import SYSTEM, Session


def _entry(day: str, title: str, landed: str | None) -> dict:
    return {"heading": f"## {day} — {title}", "date": day, "title": title, "body": "Do: it.", "landed": landed}


OLD = _entry("2026-09-27", "the rules are numbered", "2026-09-28T10:41:49-04:00")
NEW = _entry("2026-09-29", "a review comment's first line carries the verdict", "2026-09-29T17:18:40-04:00")
CREATED = "2026-09-29T12:00:00Z"  # after OLD landed (14:41Z the day before), before NEW (21:18Z)


def _view(e: dict) -> dict:
    return {k: e[k] for k in ("heading", "date", "title", "body", "landed")}


def test_the_scripts_json_is_read():
    got = conventions.parse(json.dumps({"ref": "origin/trunk", "entries": [OLD, {"date": "x"}, "junk", NEW]}))
    assert got == {"ref": "origin/trunk", "entries": [_view(OLD), _view(NEW)]}
    for bad in ("", "not json", "[]", json.dumps({"ref": "origin/main"})):
        assert conventions.parse(bad) is None, bad
    odd = [{"heading": "## a", "body": ["not", "text"]}, {"heading": "## b"}]
    assert [e["body"] for e in conventions.parse(json.dumps({"entries": odd}))["entries"]] == ["", ""]


def test_no_script_is_no_reading(tmp_path):
    assert not conventions.has_script(tmp_path) and conventions.read(tmp_path) == (None, "no script")
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "cadence_changes.py"
    script.write_text("import sys\nsys.exit(2)\n")
    assert conventions.read(tmp_path) == (None, "exit 2, no output"), "exit 2: the origin has no default branch"
    script.write_text(f"print({json.dumps(json.dumps({'ref': 'origin/main', 'entries': [OLD]}))})\n")
    assert conventions.read(tmp_path) == ({"ref": "origin/main", "entries": [_view(OLD)]}, None)


def test_what_a_reading_makes_of_a_record():
    unread = _entry("2026-09-30", "landed unknown", None)
    # the first reading: what landed at or before the create is seen untold, what landed after is told
    assert conventions.sort([NEW, OLD, unread], None, CREATED) == ([NEW["heading"], OLD["heading"]], [NEW])
    assert conventions.sort([OLD], None, CREATED) == ([OLD["heading"]], [])
    # a later reading: only a heading not held, and each once
    assert conventions.sort([NEW, OLD], [OLD["heading"]], CREATED) == ([OLD["heading"], NEW["heading"]], [NEW])
    assert conventions.sort([NEW, OLD], [OLD["heading"], NEW["heading"]], CREATED)[1] == []
    # an entry whose landed the script could not read waits for the next reading, then is sorted
    assert conventions.sort([unread], [], CREATED) == ([], [])
    late = {**unread, "landed": "2026-09-30T08:00:00+00:00"}
    assert conventions.sort([late], [], CREATED) == ([late["heading"]], [late])
    # a heading that turns out to have landed before the create joins without a word
    early = {**unread, "landed": "2026-09-01T08:00:00+00:00"}
    assert conventions.sort([early], [], CREATED) == ([early["heading"]], [])
    assert conventions.sort([OLD], None, "") is None, "a created that cannot be read writes nothing"


def test_the_fixed_words():
    assert conventions.note([NEW], "origin/main") == (
        "docs/cadence-changes.md gained 1 entry since you started: "
        '"2026-09-29 — a review comment\'s first line carries the verdict" — read it on `origin/main`, then go on'
    )
    four = [_entry("2026-10-01", f"rule {n}", "2026-10-01T00:00:00Z") for n in range(4)]
    assert conventions.note(four, "origin/trunk") == (
        'docs/cadence-changes.md gained 4 entries since you started: "2026-10-01 — rule 0", '
        '"2026-10-01 — rule 1", "2026-10-01 — rule 2" and 1 more — read them on `origin/trunk`, then go on'
    )
    assert '"an odd heading"' in conventions.note([{"heading": "## an odd heading"}], "origin/main")


# ── the tick ────────────────────────────────────────────────────────────────────────────────────


class _Script:
    """What the script would say in each root, and where it was run."""

    def __init__(self, monkeypatch):
        self.says: dict[str, list[dict] | None] = {}
        self.ran: list[str] = []
        monkeypatch.setattr(conventions, "read", self._read)
        monkeypatch.setattr(conventions, "has_script", lambda root: True)

    def _read(self, root, **kw):
        self.ran.append(str(root))
        got = self.says.get(str(root))
        return (
            (None, "exit 2, no output")
            if got is None
            else ({"ref": "origin/main", "entries": [_view(e) for e in got]}, None)
        )


def _member(agent, name: str, root: str, created: str = CREATED, **fields) -> Session:
    agent._conventions_read_at = datetime.max.replace(tzinfo=UTC)  # the tick's own pass never runs beside the test's
    s = Session(id=f"ao-x-{name}", name=name, kind="agent", adapter="shell", dir="", repo=root, created=created)
    s.host = agent.host
    s.supervised, s.unattended, s.state = True, True, "working"
    for k, v in fields.items():
        setattr(s, k, v)
    agent.sessions[s.id] = s
    return s


def _notes(s: Session) -> list[str]:
    return [e.text for e in s.inbox if e.from_ == SYSTEM]


async def test_a_member_created_before_an_entry_landed_is_told_once_and_one_created_after_never(agent, monkeypatch):
    script, root = _Script(monkeypatch), "/repo"
    agent._repos[root] = {}
    before = _member(agent, "before", root)
    after = _member(agent, "after", root, created="2026-09-30T00:00:00Z")
    script.says[root] = [OLD]
    await agent._conventions_pass([before, after])
    assert before.conventions_seen["headings"] == [OLD["heading"]] and _notes(before) == []
    assert script.ran == [root], "one run a root, whatever its members"
    script.says[root] = [NEW, OLD]
    await agent._conventions_pass([before, after])
    assert _notes(before) == [conventions.note([_view(NEW)], "origin/main")]
    assert before.conventions_seen["headings"] == [OLD["heading"], NEW["heading"]]
    assert _notes(after) == [] and after.conventions_seen["headings"] == [OLD["heading"], NEW["heading"]]
    at = before.conventions_seen["at"]
    await agent._conventions_pass([before, after])
    assert len(_notes(before)) == 1 and before.conventions_seen["at"] == at, "told once, and nothing written again"


async def test_an_entry_landed_between_the_create_and_the_first_reading_is_told(agent, monkeypatch):
    script, root = _Script(monkeypatch), "/repo"
    agent._repos[root] = {}
    script.says[root] = [NEW, OLD]
    s = _member(agent, "w", root)
    await agent._conventions_pass([s])
    assert len(_notes(s)) == 1 and NEW["title"] in _notes(s)[0] and OLD["title"] not in _notes(s)[0]


async def test_a_seat_a_finished_member_and_a_root_with_no_reading_are_told_nothing(agent, monkeypatch):
    script, root = _Script(monkeypatch), "/repo"
    agent._repos[root], agent._repos["/silent"] = {}, {}
    script.says[root] = [NEW, OLD]
    quiet = {
        "seat": {"seat": {"trigger": "asks"}},
        "finished": {"out_of_work": {"at": "2026-09-29T13:00:00Z", "why": "nothing"}},
        "unsupervised": {"supervised": False},
        "replaced": {"superseded_by": "ao-x-next"},
        "scheduled": {"state": "scheduled"},
        "crashed": {"state": "exited"},
        "closed": {"state": "closed"},
        "noroot": {"repo": "/elsewhere"},
    }
    recs = [_member(agent, name, root, **fields) for name, fields in quiet.items()]
    await agent._conventions_pass(recs)
    assert script.ran == [] and all(r.conventions_seen is None and _notes(r) == [] for r in recs)
    silent = _member(agent, "silent", "/silent")
    await agent._conventions_pass([silent])
    assert script.ran == ["/silent"] and silent.conventions_seen is None, "no reading writes nothing"


async def test_a_restart_is_written_afresh(agent, monkeypatch):
    """The replay's record is a new one: no `conventions_seen`, a new `created`, so what its
    SessionStart hook printed is seen untold."""
    script, root = _Script(monkeypatch), "/repo"
    agent._repos[root] = {}
    script.says[root] = [NEW, OLD]
    old = _member(agent, "w", root)
    await agent._conventions_pass([old])
    assert len(_notes(old)) == 1
    again = _member(agent, "w", root, created="2026-09-30T00:00:00Z")
    assert again.conventions_seen is None
    await agent._conventions_pass([old, again])
    assert len(_notes(old)) == 1, "the record that is no longer the run is left alone"
    assert _notes(again) == [] and again.conventions_seen["headings"] == [NEW["heading"], OLD["heading"]]


def test_the_field_is_the_homes():
    from sessionorc import models

    assert "conventions_seen" in models.HOME_OWNED


async def test_a_record_replaced_while_the_script_ran_is_left_alone(agent, monkeypatch):
    root = "/repo"
    agent._repos[root] = {}
    s = _member(agent, "w", root)
    monkeypatch.setattr(conventions, "has_script", lambda r: True)

    def read(r, **kw):
        _member(agent, "w", root, created="2026-09-30T00:00:00Z")  # a restart, mid-read
        return {"ref": "origin/main", "entries": [_view(NEW), _view(OLD)]}, None

    monkeypatch.setattr(conventions, "read", read)
    await agent._conventions_pass([s])
    assert s.conventions_seen is None and _notes(s) == [] and _notes(agent.sessions[s.id]) == []


# ── a pinned repo (TD-1046, §6 rule 12 *In a pinned repo*) ───────────────────────────────────────

PATH = "py launcher path cadence-changes.md"


def test_the_pinned_words_carry_each_entrys_body():
    one = {**NEW, "body": "Do: put the verdict first.\n  Why: a reader skims.\n"}
    assert conventions.note([one], "origin/main", PATH) == (
        "dev-cadence's cadence-changes.md gained 1 entry since you started: "
        '"2026-09-29 — a review comment\'s first line carries the verdict": Do: put the verdict first. '
        f"Why: a reader skims. — after rebasing onto `origin/main`, `{PATH}` prints its path; go on"
    )
    long = {**OLD, "body": "x" * 301}
    assert f": {'x' * 300}… — after" in conventions.note([long], "origin/main", PATH)
    assert f": {'x' * 300} — after" in conventions.note([{**long, "body": "x" * 300}], "origin/main", PATH)
    empty = conventions.note([{**OLD, "body": ""}], "origin/main", PATH)
    assert '"2026-09-27 — the rules are numbered" — after' in empty, "an empty body leaves the name alone"
    five = [_entry("2026-10-27", f"rule {n}", "2026-10-27T00:00:00Z") for n in range(5)]
    words = conventions.note(five, "origin/main", PATH)
    assert words.count("Do: it.") == 3 and 'rule 2": Do: it. and 2 more — after' in words
    assert conventions.note([NEW], "origin/main").startswith("docs/cadence-changes.md gained"), "unpinned: unchanged"


def _says(entries: list[dict] | None, code: int = 0, stderr: str = "") -> str:
    out = "" if entries is None else json.dumps({"ref": "origin/main", "entries": entries})
    return f"import sys\nprint({out!r})\nsys.stderr.write({stderr!r})\nsys.exit({code})\n"


class _Pinned:
    """A pinned fixture root: `cadence.pinned`, `cadence.tree` and `cadence.command` stubbed, the command
    a script printing `--json`; `tree` may be made to fail."""

    def __init__(self, tmp_path, monkeypatch, name: str = "pinned"):
        self.root = tmp_path / name
        self.root.mkdir()
        self.payload = tmp_path / f"{name}-tree"
        (self.payload / "scripts").mkdir(parents=True)
        self.script = self.payload / "scripts" / conventions.PINNED_SCRIPT
        self.why: str | None = None  # the resolver's refusal, while the tree cannot be made
        real = cadence.pinned
        monkeypatch.setattr(cadence, "pinned", lambda r: str(r) == str(self.root) or real(r))
        monkeypatch.setattr(cadence, "tree", self._tree)
        monkeypatch.setattr(cadence, "command", lambda r, *a: ([sys.executable, str(self.script)], None))

    def _tree(self, root, timeout=cadence.TREE_TIMEOUT):
        return (None, self.why) if self.why else (self.payload, None)

    def says(self, entries: list[dict] | None, code: int = 0, stderr: str = "") -> None:
        self.script.write_text(_says(entries, code, stderr))


def _lines(caplog, root) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(f"{root}: ")]


async def test_a_pinned_member_is_told_with_bodies_and_the_resolvers_command(agent, tmp_path, monkeypatch, caplog):
    p = _Pinned(tmp_path, monkeypatch)
    root = str(p.root)
    agent._repos[root] = {}
    p.says([NEW, OLD])
    home = _member(agent, "home", root)
    node = _member(agent, "node", root)
    node.host = "elsewhere"  # a node's member, its replica held as the home holds one; the words are read as sent
    agent.remote.setdefault("elsewhere", {})[node.id] = agent.sessions.pop(node.id)
    sent: dict[str, list[str]] = {}
    real = agent._system_note
    monkeypatch.setattr(
        agent, "_system_note", lambda to, text, **kw: (sent.setdefault(to, []).append(text), real(to, text, **kw))
    )
    with caplog.at_level("INFO", logger="shiftlead.agent"):
        await agent._conventions_pass([home, node])
        await agent._conventions_pass([home, node])
    typed = cadence.typed("path", "cadence-changes.md")
    assert _notes(home) == [conventions.note([_view(NEW)], "origin/main", typed)]
    told = sent[agent._address(node)]
    assert told == [conventions.note([_view(NEW)], "origin/main", agent_tick.NODE_CHANGES)]
    assert "`dev-cadence path cadence-changes.md` prints its path" in told[0] and ": Do: it." in told[0]
    assert typed in sent[agent._address(home)][0]
    assert home.conventions_seen["headings"] == [NEW["heading"], OLD["heading"]]
    assert sum("told of 1 new in dev-cadence's changes" in m for m in caplog.messages) == 2


async def test_the_migration_is_one_note_naming_three(agent, tmp_path, monkeypatch):
    """A member created before the migration whose first reading falls after it: every entry the retired
    copy carried lands at the migration's merge, so it is told them in one note."""
    p = _Pinned(tmp_path, monkeypatch)
    root = str(p.root)
    agent._repos[root] = {}
    five = [_entry("2026-10-0" + str(n), f"rule {n}", "2026-10-26T12:00:00Z") for n in range(1, 6)]
    p.says(five)
    s = _member(agent, "w", root, created="2026-10-25T00:00:00Z")
    await agent._conventions_pass([s])
    assert (
        len(_notes(s)) == 1
        and "gained 5 entries" in _notes(s)[0]
        and '"2026-10-03 — rule 3": Do: it. and 2 more' in _notes(s)[0]
    )
    assert s.conventions_seen["headings"] == [e["heading"] for e in five]


async def test_an_empty_reading_sends_nothing_and_is_logged_once(agent, tmp_path, monkeypatch, caplog):
    p = _Pinned(tmp_path, monkeypatch)
    p.says([])
    unpinned = tmp_path / "unpinned"
    (unpinned / "scripts").mkdir(parents=True)
    (unpinned / conventions.SCRIPT).write_text(_says([]))
    locked = tmp_path / "locked"  # a pin beside docs/cadence-sync.lock: its copy is read
    (locked / "docs").mkdir(parents=True)
    (locked / "scripts").mkdir()
    (locked / "docs" / "cadence.toml").write_text(
        '[dev-cadence]\nsource = "https://x/dev-cadence"\nref = "' + "a" * 40 + '"\n'
    )
    (locked / "docs" / "cadence-sync.lock").write_text("files_commit=x\n")
    (locked / conventions.SCRIPT).write_text(_says([]))
    assert not cadence.pinned(locked)
    members = []
    for root in (p.root, unpinned, locked):
        agent._repos[str(root)] = {}
        members.append(_member(agent, root.name, str(root)))
    with caplog.at_level("INFO", logger="shiftlead.agent"):
        await agent._conventions_pass(members)
        await agent._conventions_pass(members)
    assert all(_notes(m) == [] for m in members)
    assert _lines(caplog, p.root) == [f"{p.root}: no entries — the checkout's pin may predate dev-cadence's change"]
    for root in (unpinned, locked):
        words = (
            "no entries — the checkout may predate the migration, or still hold docs/cadence-sync.lock beside its pin"
        )
        assert _lines(caplog, root) == [f"{root}: {words}"]
    p.says([OLD])  # entries end the condition; an empty reading after is logged again
    await agent._conventions_pass(members)
    p.says([])
    with caplog.at_level("INFO", logger="shiftlead.agent"):
        caplog.clear()
        await agent._conventions_pass(members)
    assert len(_lines(caplog, p.root)) == 1 and _lines(caplog, unpinned) == []


async def test_no_reading_says_why(agent, tmp_path, monkeypatch, caplog):
    p = _Pinned(tmp_path, monkeypatch)
    root = str(p.root)
    agent._repos[root] = {}
    s = _member(agent, "w", root)
    p.says(None, 2, "cadence_changes: origin has no default branch\n")
    with caplog.at_level("INFO", logger="shiftlead.agent"):
        await agent._conventions_pass([s])
        p.says(None, 2)
        await agent._conventions_pass([s])
    assert _lines(caplog, root) == [
        f"{root}: cadence_changes.py gave no reading — cadence_changes: origin has no default branch",
        f"{root}: cadence_changes.py gave no reading — exit 2, no output",
    ]
    assert s.conventions_seen is None and _notes(s) == []


async def test_a_pinned_root_with_no_tree_is_logged_once_while_it_lasts(agent, tmp_path, monkeypatch, caplog):
    p = _Pinned(tmp_path, monkeypatch)
    root = str(p.root)
    agent._repos[root] = {}
    s = _member(agent, "w", root)
    p.says([])
    no_tree = f"{root}: pinned, no tree: the launcher gave no answer in 330s"
    with caplog.at_level("INFO", logger="shiftlead.agent"):
        await agent._conventions_pass([s])  # no entries, logged
        p.why = "the launcher gave no answer in 330s"
        await agent._conventions_pass([s])  # a root that logged no entries, then loses its tree
        await agent._conventions_pass([s])
        assert _lines(caplog, root)[1:] == [no_tree]
        p.why = None
        await agent._conventions_pass([s])  # has_script turns true: the condition ends
        p.why = "the launcher gave no answer in 330s"
        await agent._conventions_pass([s])
        p.why = None
        p.script.unlink()  # a tree present but lacking the script
        await agent._conventions_pass([s])
    assert _lines(caplog, root)[1:] == [
        no_tree,
        no_tree,
        f"{root}: pinned, no tree: no scripts/cadence_changes.py in the tree",
    ]
    assert _notes(s) == []


def test_dev_cadences_source_reads_its_own_script(tmp_path):
    (tmp_path / "files" / "scripts").mkdir(parents=True)
    (tmp_path / "sync.sh").write_text("")
    assert cadence.is_source(tmp_path) and not conventions.has_script(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / conventions.SCRIPT).write_text(_says([OLD]))  # not the source's script
    assert not conventions.has_script(tmp_path)
    (tmp_path / conventions.SOURCE_SCRIPT).write_text(_says([NEW]))
    assert conventions.has_script(tmp_path)
    assert conventions.read(tmp_path) == ({"ref": "origin/main", "entries": [_view(NEW)]}, None)


def test_each_why_and_each_bound(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    script = tmp_path / conventions.SCRIPT
    script.write_text(_says(None, 2, "first\nlast line\n"))
    assert conventions.read(tmp_path) == (None, "last line")
    script.write_text("print('not json')\n")
    assert conventions.read(tmp_path) == (None, "output is not the script's --json")
    bounds: list[float] = []

    def run(argv, timeout, **kw):
        bounds.append(timeout)
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(conventions.subprocess, "run", run)
    assert conventions.read(tmp_path) == (None, "timed out after 180s")

    def fails(argv, timeout, **kw):
        bounds.append(timeout)
        raise OSError("no python3 here")

    monkeypatch.setattr(conventions.subprocess, "run", fails)
    assert conventions.read(tmp_path) == (None, "no python3 here")
    payload = tmp_path / "tree"
    (payload / "scripts").mkdir(parents=True)
    (payload / "scripts" / conventions.PINNED_SCRIPT).write_text("")
    monkeypatch.setattr(cadence, "pinned", lambda r: True)
    monkeypatch.setattr(cadence, "tree", lambda r, timeout=0: (payload, None))
    monkeypatch.setattr(cadence, "command", lambda r, *a: (["x"], None))
    assert conventions.read(tmp_path) == (None, "no python3 here")
    assert bounds == [conventions.TIMEOUT, conventions.TIMEOUT, cadence.TREE_TIMEOUT] == [180.0, 180.0, 330.0]
    with pytest.raises(AssertionError):
        assert conventions.read(tmp_path, timeout=5.0) == (None, "x")
    assert bounds[-1] == 5.0, "an explicit bound is kept"
