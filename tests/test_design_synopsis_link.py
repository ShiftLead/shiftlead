# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1536 (design §4.5 screen 6 *A design links its synopsis*, §4.5a *Queue card: what needs the person*, *Queue
page: card*): the repo reading asks `git ls-tree` once per commit which synopses are there and reads the worktree
list; the Queue's reading carries on each entry with a design link the `synopsis` of the entry it resolved to; an
item about a design draws *· design #n · synopsis · GitHub* — *synopsis* a file link through the person's `open_in`,
*GitHub* the file on the forge, *synopsis* itself linking GitHub where there is no file link — and a design entry's
own line ends its title with them, by its own id alone."""

from __future__ import annotations

import html as html_mod
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_ui_queue import client, fake, mail, queue

from sessionorc import synopsis
from sessionorc.queue import SYNOPSIS_KEY, design_prs
from shiftlead.ui import uiconf
from shiftlead.ui.queue import card_index, design_link, synopsis_view

pytestmark = pytest.mark.unit

WEB = "https://github.com/o/s"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> dict[str, Any]:
    """A checkout `s` of a bare origin: `main` holds docs/synopses/TD-012.md; a design PR's branch `td12-design`,
    checked out in a worktree under `.claude/worktrees/`, adds TD-014.md; a second branch `td15-design` adds TD-015.md
    and is checked out nowhere."""
    origin, root = tmp_path / "origin.git", tmp_path / "s"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(root))
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(root, "config", k, v)
    (root / "docs" / "synopses").mkdir(parents=True)
    (root / "docs" / "synopses" / "TD-012.md").write_text("# TD-012: a design\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "main")
    _git(root, "push", "-q", "origin", "main")
    wt = root / ".claude" / "worktrees" / "designer"
    _git(root, "worktree", "add", "-q", "-b", "td12-design", str(wt))
    (wt / "docs" / "synopses" / "TD-014.md").write_text("# TD-014: another\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "TD-014 synopsis")
    head14 = _git(wt, "rev-parse", "HEAD")
    _git(root, "branch", "-q", "td15-design", "main")
    _git(root, "checkout", "-q", "td15-design")
    (root / "docs" / "synopses" / "TD-015.md").write_text("# TD-015: a third\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "TD-015 synopsis")
    head15 = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "main")
    _git(root, "fetch", "-q", "origin")
    prs = {
        "open": [
            {"number": 30, "title": "TD-014 design: another", "branch": "td12-design", "head": head14, "fork": False},
            {"number": 31, "title": "TD-015 design: a third", "branch": "td15-design", "head": head15, "fork": False},
            {
                "number": 32,
                "title": "TD-016 design: from a fork",
                "branch": "td12-design",
                "head": head14,
                "fork": True,
            },
            {"number": 33, "title": "TD-017 design: not fetched", "branch": "x", "head": "f" * 40, "fork": False},
            {"number": 34, "title": "TD-99: a build", "branch": "td99", "head": head15, "fork": False},
        ]
    }
    return {"root": str(root), "wt": str(wt), "prs": prs, "head14": head14, "head15": head15}


def test_the_reading_asks_each_commit_once_and_reads_the_worktrees(checkout, monkeypatch):
    root, prs = checkout["root"], checkout["prs"]
    asked: list[str] = []
    real = synopsis.present
    monkeypatch.setattr(synopsis, "present", lambda r, sha: asked.append(sha) or real(r, sha))
    got = synopsis.reading(root, prs, "main")
    main_sha = _git(Path(root), "rev-parse", "origin/main")
    assert got["default"] == "main" and got["default_sha"] == main_sha
    # origin/main and each open design PR's head not from a fork; a build's PR and a fork's are never asked
    assert sorted(asked) == sorted([main_sha, checkout["head14"], checkout["head15"], "f" * 40])
    assert got["present"][main_sha] == ["docs/synopses/TD-012.md"]
    assert "docs/synopses/TD-014.md" in got["present"][checkout["head14"]]
    assert "f" * 40 not in got["present"]  # a head not in the objects reads absent, and is asked again later
    assert got["worktrees"]["td12-design"] == checkout["wt"] and "td15-design" not in got["worktrees"]
    asked.clear()
    again = synopsis.reading(root, prs, "main", got)  # the next reading: each commit kept, asked once
    assert asked == ["f" * 40] and again["present"] == got["present"]


def test_an_entry_reads_the_pr_head_before_the_merge_and_origin_after(checkout):
    root, prs = checkout["root"], checkout["prs"]
    syn = synopsis.reading(root, prs, "main")
    pr = {p["number"]: p for p in prs["open"]}
    merged = synopsis.entry("TD-012", None, syn, root)
    assert (
        merged["exists"] and merged["branch"] == "main" and merged["editor_path"] == f"{root}/docs/synopses/TD-012.md"
    )
    assert merged["sha"] == syn["default_sha"] and merged["path"] == "docs/synopses/TD-012.md"
    before = synopsis.entry("TD-014", pr[30], syn, root)  # the worktree on the PR's branch holds the editor's copy
    assert before["exists"] and before["branch"] == "td12-design"
    assert before["editor_path"] == f"{checkout['wt']}/docs/synopses/TD-014.md"
    nowhere = synopsis.entry("TD-015", pr[31], syn, root)  # no worktree on its branch: no editor copy
    assert nowhere["exists"] and nowhere["editor_path"] is None
    assert not synopsis.entry("TD-016", pr[32], syn, root)["exists"]  # a fork's PR draws none
    assert not synopsis.entry("TD-017", pr[33], syn, root)["exists"]  # a head not fetched draws none
    assert not synopsis.entry("TD-013", None, syn, root)["exists"]  # a design written before TD-1527: no file
    assert synopsis.entry("TD-012", None, None, root) is None  # a repo with no reading


def test_design_prs_carries_the_resolved_entrys_synopsis_and_whose_it_is(checkout):
    root, prs = checkout["root"], checkout["prs"]
    syn = synopsis.reading(root, prs, "main")
    e = lambda tid, **kw: {"id": tid, "repo": "s", **kw}  # noqa: E731
    open_ = {
        "s#TD-012": e("TD-012", design_pr=[12]),
        "s#TD-020": e("TD-020", part_of="TD-012"),  # a build under it: the parent's synopsis, not its own
        "s#TD-014": e("TD-014", design_pr=[9]),  # an open design PR above the section: its head's copy
    }
    got = design_prs({"s": root}, {"s": prs}, open_, {}, {"s": syn})
    assert got["s#TD-012"]["own"] and got["s#TD-012"]["synopsis"]["exists"]
    assert not got["s#TD-020"]["own"] and got["s#TD-020"]["synopsis"]["path"] == "docs/synopses/TD-012.md"
    assert got["s#TD-014"]["n"] == 30 and got["s#TD-014"]["synopsis"]["branch"] == "td12-design"
    assert "synopsis" not in design_prs({"s": root}, {"s": prs}, open_, {})["s#TD-012"]  # no reading, no synopsis
    # the section's last number still open: the same number, read from the PR's head
    still = design_prs({"s": root}, {"s": prs}, {"s#TD-014": e("TD-014", design_pr=[30])}, {}, {"s": syn})["s#TD-014"]
    assert still["n"] == 30 and still["synopsis"]["branch"] == "td12-design" and still["synopsis"]["exists"]


def _q(syn: dict[str, Any] | None = None, **design: int) -> dict[str, Any]:
    """`queue()`'s cards with `{TD-n: last}` design PRs on repo `s`, each with the synopsis `syn` where given."""
    q = queue()
    q["design_prs"] = {
        f"s#TD-{k[2:]}": {"n": n, "root": "/r/s", "only": True, "own": True, **({"synopsis": syn} if syn else {})}
        for k, n in design.items()
    }
    return q


def _syn(
    editor: str | None = "/r/s/docs/synopses/TD-20.md", branch: str = "main", exists: bool = True
) -> dict[str, Any]:
    return {
        "sha": "a" * 40,
        "exists": exists,
        "editor_path": editor,
        "branch": branch,
        "path": "docs/synopses/TD-20.md",
        "root": "/r/s",
    }


@pytest.fixture
def github(monkeypatch):
    from shiftlead import review

    monkeypatch.setattr(review, "_github", lambda d: WEB if d == "/r/s" else "")


def test_the_index_keys_a_synopsis_only_where_it_is_there(github):
    idx = card_index(_q(_syn(), TD20=12))
    assert idx[SYNOPSIS_KEY + "s#TD-020"] == ("/r/s/docs/synopses/TD-20.md", "main", "docs/synopses/TD-20.md", "/r/s")
    assert SYNOPSIS_KEY + "TD-020" in idx  # the bare spelling where one repo holds it
    assert not any(k.startswith(SYNOPSIS_KEY) for k in card_index(_q(_syn(exists=False), TD20=12)))


def test_an_item_links_the_editor_copy_and_github(github):
    idx = card_index(_q(_syn(branch="td20/design"), TD20=12))
    got = design_link(mail("m1", "which way?", kind="steer", about="TD-20"), idx)
    assert got["design_pr"] == 12 and got["synopsis"]["editor"]["url"].endswith("/r/s/docs/synopses/TD-20.md:1")
    assert got["synopsis"]["web"] == f"{WEB}/blob/td20/design/docs/synopses/TD-20.md"  # its `/` kept
    # an ask --pr 12 about it: the number is not repeated, the synopsis is drawn
    own = design_link(mail("m2", "read #12?", pr=12, about="TD-20"), idx)
    assert "design_pr" not in own and own["synopsis"]["web"]
    # no synopsis: the number alone, as TD-1531 drew it
    assert "synopsis" not in design_link(mail("m3", "?", about="TD-20"), card_index(_q(None, TD20=12)))


def test_with_no_editor_link_synopsis_links_github(github, monkeypatch):
    idx = card_index(_q(_syn(editor=None), TD20=12))
    assert design_link(mail("m1", "?", about="TD-20"), idx)["synopsis"] == {
        "editor": None,
        "web": f"{WEB}/blob/main/docs/synopses/TD-20.md",
    }
    monkeypatch.setattr(uiconf, "open_in", lambda: uiconf.OpenIn(kind="none"))
    idx = card_index(_q(_syn(), TD20=12))
    assert design_link(mail("m1", "?", about="TD-20"), idx)["synopsis"]["editor"] is None
    # no web base and no editor link: nothing drawn
    assert synopsis_view({**_syn(), "root": "/r/x"}) is None


def _draws(html: str) -> list[str]:
    return re.findall(r'<span class="st synopsis">.*?</span>', html, re.S)


def test_the_card_the_inbox_row_and_the_design_s_own_header_draw_it(github, tmp_path, monkeypatch):
    q = _q(_syn(), TD20=12, TD3=13)
    q["cards"][1]["top"]["synopsis"] = _syn()  # the design entry's own line (the reading's, by its own id)
    entries = [
        mail("m1", "which way?", about="TD-20"),
        mail("m2", "read #12?", pr=12, about="TD-20"),
        mail("m3", "TD-3 shipped", kind="note", about="TD-3"),  # needs nobody, on no card: the Inbox's row
    ]
    c = client(monkeypatch, tmp_path, fake(q, entries))
    html = c.get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    head = card20[card20.index('<span class="qtitle">') :]
    head = head[: head.index("</span></span>") + 14]
    head = html_mod.unescape(head)
    assert "the queue's design" in head and "data-file-link" in head and ">GitHub</a>" in head
    items = _draws(card20)
    assert len(items) == 3  # the header's, and each item's
    assert card20.count('class="st designpr"') == 1 and f'href="{WEB}/pull/12"' in card20  # the ask --pr 12 drops it
    first = items[1]
    assert re.search(
        r"<a class=\"editor ref\"[^>]*data-file-link[^>]*title=\"the design(&#39;|')s synopsis, in your editor\">synopsis</a>",
        first,
    )
    assert f'href="{WEB}/blob/main/docs/synopses/TD-20.md"' in first and 'title="the synopsis on GitHub"' in first
    # a build's row under it draws none: its own id has no design link
    build = card20[card20.index("build the queue") - 300 : card20.index("build the queue") + 200]
    assert "synopsis" not in build
    inbox = c.get("/inbox").text
    fyi = inbox[inbox.index('id="sec-fyi"') :]
    assert "TD-3 shipped" in fyi and len(_draws(fyi)) == 1 and "data-file-link" in _draws(fyi)[0]


def test_with_no_editor_link_the_word_itself_links_github(github, tmp_path, monkeypatch):
    monkeypatch.setattr(uiconf, "open_in", lambda: uiconf.OpenIn(kind="none"))
    c = client(monkeypatch, tmp_path, fake(_q(_syn(), TD20=12), [mail("m1", "which way?", about="TD-20")]))
    (got,) = _draws(html_mod.unescape(c.get("/queue").text))
    assert 'title="the design\'s synopsis, on GitHub">synopsis</a>' in got and "GitHub</a>" not in got.replace(
        ">synopsis</a>", ""
    )
    assert "data-file-link" not in got


def test_the_repo_page_row_of_a_design_draws_it(github):
    from shiftlead.ui import repo
    from shiftlead.ui.common import templates

    q = _q(_syn(), TD20=12)
    q["cards"][1]["top"]["synopsis"] = _syn()
    cards = repo.debt_cards(q, "s", [])
    top = next(c for c in cards["cards"] if c["id"] == "s#TD-20")["top"]
    assert top["synopsis"]["web"] == f"{WEB}/blob/main/docs/synopses/TD-20.md"
    html = templates.env.get_template("queue_row.html").module.row(top, "s")
    assert len(_draws(str(html))) == 1
