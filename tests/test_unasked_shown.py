# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-790, design §4.4 *A held PR nobody asked is marked, never ordered*: the reading's *unasked* mark
shown — the Repo page's tag and its title (§4.5 screen 11), `ao repo`'s line and `--json` (§4.7), and
`ao pr held`'s *the repo holds* line on a *not held* answer. The reader the tag names is one function,
`review.unasked_reader`, which the page and `cmd_repo` share."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiftlead import cli
from shiftlead import review as reviewmod

pytestmark = pytest.mark.unit

NOW = datetime.now(UTC)
REVIEW = {"reader": "techlead", "held": ["docs/briefs/**", "src/sessionorc/**"], "bound": "2h"}


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def m(name: str, **kw) -> dict:
    return {"id": f"ao-r-{name}", "name": name, "state": "working", **kw}


# ── the reader: one function for the page and `ao repo` ───────────────────────────────────────────


def test_the_reader_is_the_first_team_in_the_org_order_whose_review_holds_a_touched_path():
    grind = [m("grinder-1", review=REVIEW), m("techlead-1", role="techlead")]
    docs = [
        m("writer-1", review={"reader": "editor", "held": ["docs/**"]}),
        m("editor-1", role="editor", seat={"trigger": "asks"}),
    ]
    # both teams hold docs/briefs/x.md: the first in the order given names it
    assert reviewmod.unasked_reader([grind, docs], ["docs/briefs/x.md"]) == "techlead-1"
    assert reviewmod.unasked_reader([docs, grind], ["docs/briefs/x.md"]) == "editor-1"
    # a team whose review holds none of the paths is passed over
    assert reviewmod.unasked_reader([docs, grind], ["src/sessionorc/a.py"]) == "techlead-1"


def test_under_named_sets_a_stage_is_not_named_for_a_pr_outside_its_set():
    chain = {"chain": [{"stage": "ui", "reader": "ui-reader", "held": ["src/shiftlead/ui/**"]},
                       {"stage": "review", "reader": "techlead", "held": ["src/sessionorc/**"]}]}  # fmt: skip
    team = [
        m("grinder-1", review=chain),
        m("ui-reader-1", role="ui-reader", seat={"trigger": "asks"}),
        m("techlead-1", role="techlead"),
    ]
    assert reviewmod.unasked_reader([team], ["src/sessionorc/held.py"]) == "techlead-1"
    assert reviewmod.unasked_reader([team], ["src/shiftlead/ui/app.py"]) == "ui-reader-1"


def test_a_team_without_a_seat_names_the_person_and_no_reader_names_nothing():
    assert reviewmod.unasked_reader([[m("grinder-1", review=REVIEW)]], ["docs/briefs/x.md"]) == "person"
    assert reviewmod.unasked_reader([[m("grinder-1", review={"reader": "person", "held": ["**"]})]], ["a"]) == "person"
    assert (
        reviewmod.unasked_reader([[m("grinder-1")], [m("techlead-1", role="techlead")]], ["docs/briefs/x.md"]) is None
    )
    assert reviewmod.unasked_reader([], ["docs/briefs/x.md"]) is None


def test_the_tag_is_the_readings_never_re_derived():
    r = {
        "prs": {"open": [{"number": 7, "held": ["docs/briefs/x.md"], "created": "2026-10-16T00:00:00Z"}]},
        "pr_orders": {"unasked": []},
    }
    team = [[m("grinder-1", review=REVIEW), m("techlead-1", role="techlead")]]
    assert reviewmod.unasked(r, 7, team) is None  # held, but the reading does not list it
    r["pr_orders"]["unasked"] = [7]
    assert reviewmod.unasked(r, 7, team) == {
        "paths": ["docs/briefs/x.md"],
        "reader": "techlead-1",
        "created": "2026-10-16T00:00:00Z",
    }
    assert reviewmod.unasked(r, 7, [[m("grinder-1")]]) is None  # a reader-less repo draws nothing


# ── the Repo page ─────────────────────────────────────────────────────────────────────────────────


def reading(root: str) -> dict:
    return {
        "name": "samscrape",
        "root": root,
        "remote": "git@github.com:eye/samscrape.git",
        "ledger": {"path": "docs/technical_debt.md", "entries": [], "by_kind": {}},
        "prs": {
            "open": [
                {"number": 805, "title": "brief edit", "created": _iso(NOW - timedelta(hours=17)), "author": "eye", "branch": "x", "url": "https://x/805", "held": ["docs/briefs/designer.md"]},
                {"number": 811, "title": "asked", "created": _iso(NOW - timedelta(hours=2)), "author": "eye", "branch": "y", "url": "https://x/811", "held": ["src/sessionorc/a.py"]},
            ],
        },
        "pr_orders": {"unasked": [805, 811], "asked": {}},
        "at": _iso(NOW),
    }  # fmt: skip


def fake(repos, fleet, inbox=None):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                key = f"{kw.get('id')}/sent" if kw.get("sent") else kw.get("id")
                return (inbox or {}).get(key, {"entries": []})
            return {"repos": repos, "doing_log": {}, "list": fleet, "usage": {}, "host": {"name": "kmaster"}}.get(
                method, {}
            )

    return Fake


def page(monkeypatch, tmp_path, fleet, inbox=None):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    root = str(tmp_path / "samscrape")
    fleet = [{**s, "kind": "agent", "team": "grind", "repo": root, "dir": root, "unattended": True} for s in fleet]
    monkeypatch.setattr(ui, "LocalClient", fake({root: reading(root)}, fleet, inbox))
    html = TestClient(ui.create_app()).get("/repo/samscrape").text
    return html[html.index('id="prs"') : html.index('id="debt"')]


def test_the_repo_page_tags_a_held_pr_nobody_asked_with_its_age_and_reader(tmp_path, monkeypatch):
    fleet = [m("grinder-1", review=REVIEW), m("techlead-1", role="techlead")]
    # 811 has a standing (an open ask): the standing is drawn, never the tag
    inbox = {
        "ao-r-techlead-1": {
            "entries": [{"kind": "ask", "pr": 811, "at": _iso(datetime.now(UTC) - timedelta(minutes=40))}]
        }
    }
    prs = page(monkeypatch, tmp_path, fleet, inbox)
    row = prs[prs.index("#805") : prs.index("#811")]
    assert (
        '<span class="tag wait" title="touches held paths (docs/briefs/designer.md): post its review, then ao msg --kind ask --pr 805 techlead-1 — where your own ao pr held says held">unasked · 17h'
        in row
    )
    tail = prs[prs.index("#811") :]
    assert "waiting on techlead-1 · 40m" in tail and "unasked" not in tail.split("</div>")[0]
    assert "<i>unasked</i> is a green PR" in prs  # the i panel says what it means


def test_a_repo_with_no_reader_draws_no_tag(tmp_path, monkeypatch):
    prs = page(monkeypatch, tmp_path, [m("grinder-1"), m("techlead-1", role="techlead")])
    assert "unasked ·" not in prs


# ── `ao repo` ─────────────────────────────────────────────────────────────────────────────────────


def _repo_world(monkeypatch, tmp_path, fleet):
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    r = reading(str(repo))
    r["name"] = "r"
    for s in fleet:
        s.setdefault("repo", str(repo))
    monkeypatch.setattr(
        cli,
        "call_sync",
        lambda rpc, **kw: {
            "repos": {str(repo): r},
            "list": fleet,
            "doing_log": {},
            "queue": {},
            "inbox": {"entries": []},
        }[rpc],
    )
    monkeypatch.chdir(repo)
    return r


def test_ao_repo_prints_the_tag_and_its_reader_for_a_session_and_its_json_carries_the_marks(
    tmp_path, monkeypatch, capsys
):
    fleet = [m("grinder-1", team="grind", review=REVIEW), m("techlead-1", team="grind", role="techlead")]
    r = _repo_world(monkeypatch, tmp_path, fleet)
    r["pr_orders"]["asked"] = {"811": {"at": "2026-10-16T10:00:00Z", "to": "ao-r-techlead-1"}}
    r["pr_orders"]["unasked"] = [805]
    assert cli.main(["repo", "r"]) == 0
    out = capsys.readouterr().out
    assert "         unasked 17h — post its review, then ao msg --kind ask --pr 805 techlead-1" in out
    assert out.count("unasked") == 1
    assert cli.main(["--json", "repo", "r"]) == 0
    prs = {p["number"]: p for p in json.loads(capsys.readouterr().out)[0]["prs"]["open"]}
    assert (prs[805]["held"], prs[805]["asked"], prs[805]["unasked"]) == (["docs/briefs/designer.md"], None, True)
    assert prs[811]["asked"] == {"at": "2026-10-16T10:00:00Z", "to": "ao-r-techlead-1"} and prs[811]["unasked"] is False


def test_ao_repo_orders_two_teams_as_the_org_does(tmp_path, monkeypatch, capsys):
    """Both teams hold the path: the first in the org file names the reader, whatever the names sort to."""
    from shiftlead import org as orgmod

    fleet = [
        m("grinder-1", team="zeta", review=REVIEW), m("techlead-1", team="zeta", role="techlead"),
        m("writer-1", team="alpha", review={"reader": "editor", "held": ["docs/**"]}), m("editor-1", team="alpha", role="editor", seat={"trigger": "asks"}),
    ]  # fmt: skip
    _repo_world(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(cli, "_org_notes", lambda: (orgmod.Org(teams={"zeta": object(), "alpha": object()}), []))
    assert cli.main(["repo", "r"]) == 0
    assert "ao msg --kind ask --pr 805 techlead-1" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_org_notes", lambda: (orgmod.Org(teams={"alpha": object(), "zeta": object()}), []))
    assert cli.main(["repo", "r"]) == 0
    assert "ao msg --kind ask --pr 805 editor-1" in capsys.readouterr().out


# ── `ao pr held` ──────────────────────────────────────────────────────────────────────────────────


def _held_world(monkeypatch, review, files, reading_):
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-r-w")
    rec = {"id": "ao-r-w", "dir": "/r", "repo": "/r", "review": review}

    def call(method, **kw):
        if method == "repos":
            if reading_ is None:
                return {}
            return {"/r": reading_}
        return rec

    monkeypatch.setattr(cli, "call_sync", call)
    body = json.dumps({"files": [{"path": f} for f in files]})
    monkeypatch.setattr(reviewmod.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, body, ""))


@pytest.mark.parametrize("review", [None, {"reader": "techlead", "held": ["src/sessionorc/**"]}])
def test_ao_pr_held_says_what_the_repo_holds_on_either_not_held_branch(monkeypatch, capsys, review):
    r = {
        "root": "/r",
        "prs": {"open": [{"number": 12, "held": ["docs/briefs/a.md"]}]},
        "pr_orders": {"unasked": [12], "asked": {}},
    }
    _held_world(monkeypatch, review, ["docs/briefs/a.md"], r)
    assert cli.main(["pr", "held", "12"]) == 0
    out = capsys.readouterr().out
    assert (
        "is not held" in out
        and "the repo holds `docs/briefs/a.md`: the Repo page tags it unasked until a reader is asked" in out
    )
    # asked: who and how long ago
    r["pr_orders"] = {
        "unasked": [],
        "asked": {"12": {"at": _iso(datetime.now(UTC) - timedelta(hours=3)), "to": "ao-r-techlead-1"}},
    }
    assert cli.main(["pr", "held", "12"]) == 0
    assert "the repo holds `docs/briefs/a.md`: asked of ao-r-techlead-1 3h ago" in capsys.readouterr().out
    # a row whose hold is not yet read
    del r["prs"]["open"][0]["held"]
    assert cli.main(["pr", "held", "12", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["repo_hold"] == "the repo's hold is not yet read"
    # no reading of the repo (a node's checkout): nothing
    _held_world(monkeypatch, review, ["docs/briefs/a.md"], None)
    assert cli.main(["pr", "held", "12"]) == 0
    assert "the repo" not in capsys.readouterr().out


def test_a_held_answer_reads_no_repo_mark(monkeypatch, capsys):
    r = {
        "root": "/r",
        "prs": {"open": [{"number": 12, "held": ["src/sessionorc/a.py"]}]},
        "pr_orders": {"unasked": [12]},
    }
    _held_world(monkeypatch, {"reader": "techlead", "held": ["src/sessionorc/**"]}, ["src/sessionorc/a.py"], r)
    assert cli.main(["pr", "held", "12", "--json"]) == 0
    assert "repo_hold" not in json.loads(capsys.readouterr().out)


def test_the_repo_holds_line_names_three_held_paths_and_counts_the_rest(monkeypatch, capsys):
    held = ["a", "b", "c", "d", "e"]
    r = {"root": "/r", "prs": {"open": [{"number": 12, "held": held}]}, "pr_orders": {"unasked": [12], "asked": {}}}
    _held_world(monkeypatch, None, held, r)
    assert cli.main(["pr", "held", "12", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["repo_hold"] == (
        "the repo holds `a`, `b`, `c` and 2 more: the Repo page tags it unasked until a reader is asked"
    )


@pytest.mark.parametrize(
    ("held", "path"), [(["a", "b", "c"], "`a`, `b`, `c`"), (["a", "b", "c", "d"], "`a`, `b`, `c` and 1 more")]
)
def test_the_repo_holds_line_counts_more_only_past_three_paths(monkeypatch, capsys, held, path):
    r = {"root": "/r", "prs": {"open": [{"number": 12, "held": held}]}, "pr_orders": {"unasked": [12], "asked": {}}}
    _held_world(monkeypatch, None, held, r)
    assert cli.main(["pr", "held", "12", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["repo_hold"] == (
        f"the repo holds {path}: the Repo page tags it unasked until a reader is asked"
    )


def test_an_asked_pr_whose_reading_holds_no_path_says_nothing(monkeypatch, capsys):
    r = {
        "root": "/r",
        "prs": {"open": [{"number": 12, "held": []}]},
        "pr_orders": {"unasked": [], "asked": {"12": {"at": _iso(datetime.now(UTC)), "to": "ao-r-techlead-1"}}},
    }
    _held_world(monkeypatch, None, ["src/x.py"], r)
    assert cli.main(["pr", "held", "12", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["repo_hold"] == ""
