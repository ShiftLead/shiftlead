"""TD-2186, design §4.5 screen 6 *The ledger's entries that wait on you*, §4.5a *Inbox row: ledger entry* (TD-2172): a
`decision (paul)` entry with an `**Ask:**` and no `**Answers:**` is offered the gate's own pair, **Go** and **Not yet**
(the sweep's line's answers, no default), drawn with their titles on the Queue, the Inbox and the Repo page; a Go
writes the sweep's line decided and lifts the gate in the same commit, a Not yet closes the line `— kept waiting.` and
leaves the gate. In the pair's place: an entry's own answers, a covering line, the fact, an `Owner: paul` entry's
**Done**, a design's **Go now**, and a held build's design."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _v3board import write_board
from conftest import park_ticks, served
from markupsafe import Markup
from test_queue import NOW, _entry
from test_queue_asked_early import LATER, _one
from test_queue_board_hold import _closed, _open, _read, _setup
from test_queue_held_stamps import PART, _closed_line
from test_ui_queue import client

from sessionorc import queue
from sessionorc.client import AgentError, LocalClient
from shiftlead.ui.app import ledger_for_you, templates
from shiftlead.ui.queue import attach, card_index, queue_view, split_later

ASKED = {"Priority": "High", "Blocked_by": "decision (paul)", "Added": "2026-10-01", "Ask": "Should it go ahead?"}
GO_TITLE = 'title="lifts the hold on TD-001"'
NOT_YET_TITLE = f'title="the hold stays; asked again in {queue.REASK_DAYS} days"'
ONE = templates.get_template("queue_mail.html")
CARD = templates.env.get_template("queue_card.html").module.card


def _row(repos: dict, ref: str = "TD-001", now: datetime = NOW) -> dict:
    got = ledger_for_you(repos, [], {}, now=now)
    return next(x for g in got["groups"] for x in g["rows"] if x["id"] == ref)


def _card_html(repos: dict, ref: str = "r#TD-001") -> str:
    """The Queue card holding `ref`, drawn as the page draws it: *Later*'s rows on their cards, then `queue_view`."""
    q = _read(repos)
    lf = ledger_for_you(repos, [], {}, now=NOW)
    later = split_later(lf, [], card_index(q), entries=lf.get("entries"))[2]
    mail = attach(
        {},
        lambda e, sec: Markup(ONE.render(e=e, section=sec, board_choices={}, own="r")),
        later,
        lambda c, item, on_row: {"repo": "r", "ref": item},
    )
    v = queue_view(q, NOW, mail)
    c = next(c for g in ("in_progress", "waiting", "up_next") for c in v.get(g) or () if c["id"] == ref)
    return str(CARD(c))


def _pages(monkeypatch, tmp_path, repos: dict) -> dict[str, str]:
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": []}
            return {"repos": repos, "list": [], "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setenv("SHIFTLEAD_INBOX_BOARD_SHOW", "all")
    c = client(monkeypatch, tmp_path, Fake)
    return {page: c.get(page).text for page in ("/repo/r", "/inbox")}


def _pair_buttons(html: str) -> list[str]:
    return re.findall(r'<button[^>]*data-act="ledger"[^>]*data-index="\d"[^>]*>', html)


def _pair(html: str) -> list[str]:
    """The pair's own buttons: an answer by index whose title is the pair's (**Lift the hold** shares Go's title)."""
    return [b for b in _pair_buttons(html) if GO_TITLE in b or NOT_YET_TITLE in b]


@pytest.mark.unit
def test_a_held_question_with_no_answers_draws_go_and_not_yet_on_the_queue_the_inbox_and_the_repo_page(
    tmp_path, monkeypatch
):
    root, r = _setup(tmp_path, [_entry(1, "the question", **ASKED)])
    row = _row({root: r})
    assert (row["answers"], row["default"], row["gate_pair"]) == (["Go", "Not yet"], "", True)
    assert row["lift_item"] is True, "Lift the hold stays beside the pair where it is stamped"
    html = _card_html({root: r})
    for page, got in {"queue": html, **_pages(monkeypatch, tmp_path, {root: r})}.items():
        buttons = _pair_buttons(got)
        assert len(buttons) == 2, page
        assert 'data-index="0" data-answer="Go"' in buttons[0] and GO_TITLE in buttons[0], page
        assert 'data-index="1" data-answer="Not yet"' in buttons[1] and NOT_YET_TITLE in buttons[1], page
        assert ">Go with it</button>" not in got, f"{page}: no default, so no Go with it"
    assert "Lift the hold" in html, "on the card, beside the pair"


@pytest.mark.unit
def test_an_entrys_own_answers_are_drawn_in_the_pairs_place(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the question", **ASKED, Answers="Ship it | Hold it (default)")])
    row = _row({root: r})
    assert (row["answers"], row["gate_pair"]) == (["Ship it", "Hold it"], False)
    assert not _pair(_card_html({root: r}))


@pytest.mark.unit
def test_no_ask_no_pair(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the question", **{k: v for k, v in ASKED.items() if k != "Ask"})])
    assert (_row({root: r})["answers"], _row({root: r})["gate_pair"]) == ([], False)


@pytest.mark.unit
def test_a_covering_open_line_is_drawn_in_the_entrys_place(tmp_path, monkeypatch):
    root, r = _setup(tmp_path, [_entry(1, "the question", **ASKED)], _open("TD-001 decision (paul)", decided=None))
    for page, html in {"queue": _card_html({root: r}), **_pages(monkeypatch, tmp_path, {root: r})}.items():
        assert not _pair(html) and NOT_YET_TITLE not in html, f"{page}: the line's own answers, not the pair"


@pytest.mark.unit
def test_an_open_part_draws_no_answer(tmp_path):
    part = {"Priority": "High", "Part_of": "TD-001"}
    root, r = _one(tmp_path, _entry(1, "the question", **ASKED), _entry(2, "an open part", **part))
    row = _row({root: r})
    assert row["then_yours"] and row["gate_pair"] is False and row["answers"] == []


@pytest.mark.unit
def test_a_person_owned_entry_draws_done(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the question", **ASKED, Owner="paul")])
    row = _row({root: r})
    assert (row["why"], row["answers"], row["gate_pair"]) == ("yours", [], False)
    html = _card_html({root: r})
    assert ">Done</button>" in html and not _pair(html)


@pytest.mark.unit
def test_a_design_with_held_builds_draws_go_now_and_its_held_build_no_pair(tmp_path):
    entries = [_entry(1, "the design", **ASKED), _entry(2, "build a", **PART, Ask="Build it?")]
    root, r = _setup(tmp_path, entries, _closed_line("TD-002"))
    now = datetime(2026, 10, 16, tzinfo=UTC)
    design, build = _row({root: r}, "TD-001", now), _row({root: r}, "TD-002", now)
    assert design["go_builds"] == ["TD-002"] and design["lift_item"] is True, "Go now"
    assert (design["answers"], design["gate_pair"]) == ([], False)
    assert build["held_by"] == "r#TD-001" and (build["answers"], build["gate_pair"]) == ([], False)


@pytest.mark.unit
def test_an_early_entry_draws_the_pair_beside_its_early_line(tmp_path):
    root, r = _one(
        tmp_path,
        _entry(1, "the question", **{**ASKED, "Blocked_by": "TD-002, decision (paul)"}),
        _entry(2, "a dated blocker", Priority="High", Blocked_by=f"until {LATER}"),
    )
    row = _row({root: r})
    assert row["early"] and row["early_line"] and (row["answers"], row["gate_pair"]) == (["Go", "Not yet"], True)
    html = _card_html({root: r}, "r#TD-002")  # drawn on its blocker's card
    assert "Asked early: your answer acts" in html and len(_pair(html)) == 2


@pytest.mark.unit
def test_the_pair_is_drawn_again_once_a_not_yets_line_has_closed_and_the_days_pass(tmp_path):
    log = '**Log:**\n- 2026-10-15: kept waiting: decision (paul) — by paul; answer "Not yet"\n'
    entry = _entry(1, "the question", **ASKED) + log + "\n"
    line = _closed("TD-001 decision (paul)", "kept waiting", decided="Not yet (2026-10-15)")
    root, r = _setup(tmp_path, [entry], line)
    soon = _row({root: r}, now=datetime(2026, 10, 20, tzinfo=UTC))
    assert soon["answered"] and soon["answered"]["until"], "kept waiting: answered, asked again on its date"
    later = _row({root: r}, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert not later["answered"] and (later["answers"], later["gate_pair"]) == (["Go", "Not yet"], True)


# -- the press (`ledger_decide`'s `answer` against the pair) --------------------------------------------------------

LEDGER_ENTRY = """## TD-{n}: A question to go ahead

**Priority:** Low
**Added:** 2026-11-01
**Owner:** grinder
**Status:** Open
**Blocked by:** decision (paul)

**Ask:** Should TD-{n} go ahead?

**Why:** a test's.
"""


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
    for n in (190, 191):
        (root / "docs" / "ledger" / f"TD-{n}.md").write_text(LEDGER_ENTRY.format(n=n))
    write_board(root, "# User attention\n\nFormat: `- [ ] …`\n\nPeople: paul\n\n## Needs the user\n\n"
                "- [ ] 2026-09-21 (n/a) — an unrelated item.\n")  # fmt: skip
    served(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", root / "scripts", dirs_exist_ok=True)
    return root


async def _home(agent, repo: Path, monkeypatch) -> str:
    root = str(repo)

    async def held() -> None:  # the reading is this test's: the tick reads no registry over it
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    monkeypatch.setattr(agent, "_read_ledger", lambda root, old_led, *a, **kw: (dict(old_led), []))
    await park_ticks(agent)
    entries = [
        {"id": f"TD-{n}", "title": "A question to go ahead", "for_page": "for-you", "owner": "grinder",
         "blocked_by": ["decision (paul)"], "ask": f"Should TD-{n} go ahead?"}
        for n in (190, 191)
    ]  # fmt: skip
    agent._repos = {root: {"name": "repo", "root": root, "ledger": {"entries": entries}, "work_orders": {"orders": []}}}
    return root


def _origin(repo: Path, path: str) -> str:
    git(repo, "fetch", "-q", "origin")
    return git(repo, "show", f"origin/main:{path}")


def _line(repo: Path, key: str) -> tuple[str, str]:
    """The decided line's file on origin, open or archived, by its key: (its path, its text)."""
    git(repo, "fetch", "-q", "origin")
    nonce = key.removeprefix("board:")
    path = next(p for p in git(repo, "ls-tree", "-r", "--name-only", "origin/main", "docs").splitlines()
                if p.endswith(f"-{nonce}.md"))  # fmt: skip
    return path, _origin(repo, path)


async def test_go_writes_the_sweeps_line_decided_and_lifts_the_gate_in_one_commit(agent, repo, monkeypatch):
    root = await _home(agent, repo, monkeypatch)
    async with LocalClient() as me:
        with pytest.raises(AgentError, match="has no answer 2"):
            await me.call("ledger_decide", repo=root, id="TD-190", answer=2)
        with pytest.raises(AgentError, match="marks no answer"):
            await me.call("ledger_decide", repo=root, id="TD-190", go=True)
        got = await me.call("ledger_decide", repo=root, id="TD-190", answer=0)
    assert got["decided"] == "Go"
    path, text = _line(repo, got["key"])
    assert "/archive/" in path, "the decide lift closes its line"
    assert "**Context:** TD-190 decision (paul)" in text and "**Answers:** Go | Not yet" in text
    assert re.search(r"\*\*Decided:\*\* \S+ by paul — Go\n", text), text
    entry = _origin(repo, "docs/ledger/TD-190.md")
    assert "**Blocked by:**" not in entry and 'gate lifted: decision (paul) — by paul; answer "Go"' in entry
    changed = git(repo, "show", "--name-only", "--format=", "origin/main").splitlines()
    assert "docs/ledger/TD-190.md" in changed and path in changed, "the line and the lift in the press's one commit"


async def test_not_yet_closes_the_line_kept_waiting_and_leaves_the_gate(agent, repo, monkeypatch):
    root = await _home(agent, repo, monkeypatch)
    async with LocalClient() as me:
        got = await me.call("ledger_decide", repo=root, id="TD-191", answer=1)
    assert got["decided"] == "Not yet"
    path, text = _line(repo, got["key"])
    assert "/archive/" in path and "**Context:** TD-191 decision (paul)" in text
    assert re.search(r"\*\*Decided:\*\* \S+ by paul — Not yet\n", text) and "kept waiting" in text, text
    entry = _origin(repo, "docs/ledger/TD-191.md")
    assert "**Blocked by:** decision (paul)" in entry and "kept waiting: decision (paul)" in entry


async def test_a_reply_on_a_pair_entry_takes_the_plain_road(agent, repo, monkeypatch):
    """The Reply's words are not the pair: one decided line naming the id, the gate standing (§4.4)."""
    root = await _home(agent, repo, monkeypatch)
    async with LocalClient() as me:
        got = await me.call("ledger_decide", repo=root, id="TD-190", words="wait for the next release")
    _path, text = _line(repo, got["key"])
    assert "**Context:** TD-190\n" in text and "**Answers:**" not in text
    assert "**Blocked by:** decision (paul)" in _origin(repo, "docs/ledger/TD-190.md")
