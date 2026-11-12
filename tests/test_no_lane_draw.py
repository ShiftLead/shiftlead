"""TD-1687 slice 1, design §4.7 `ao repo` and §4.5a team card **Start** (*what no lane will take*, TD-1573): the home's
`no_lane` mark drawn by `ao repo` (the first line's *n no lane*, a *no lane:* line per entry, never a list row) and
Start's clause (`teamrun.start_no_lane`, `no_lane_clause`)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from sessionorc import ledger
from shiftlead import teamrun

DESIGNER = ["design-first", "owner:designer"]
GRINDER = ["free-pick", "owner:grinder"]
WHY = "Owner techlead: the lanes that take design-first take owner:designer"


def _e(tid, page="design", kind="design-first", owner="techlead", **kw):
    return {"id": tid, "title": f"entry {tid}", "for_page": page, "kind": kind, "owner": owner, "pickable": "yes",
            "blocked_by": [], "priority": "Medium", **kw}  # fmt: skip


def _marked(*ents, lanes=((GRINDER, "lb"),)):
    by_kind = {k: 0 for k in ledger.KINDS}
    return ledger.mark_no_lane({"entries": list(ents), "by_kind": by_kind, "needs_team": []}, list(lanes))


@pytest.mark.unit
def test_ao_repo_counts_lists_and_carries_an_entry_no_lane_takes(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    led = _marked(_e("TD-058"), _e("TD-059", owner="designer"), lanes=[(DESIGNER, "lb"), (GRINDER, "lb")])
    reading = {str(repo): {"root": str(repo), "name": "r", "ledger": led, "prs": {"open": []}}}
    calls = {"repos": reading, "list": [], "doing_log": {}, "queue": {}, "inbox": {}}
    monkeypatch.setattr(cli, "call_sync", lambda rpc, **kw: calls[rpc])
    monkeypatch.chdir(repo)
    assert cli.main(["repo"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "1 design, 0 for you, 0 live check, 1 no lane, 0 blocked" in lines[0]
    assert f"  no lane: TD-058 — {WHY}" in lines
    rows = [ln.split()[:2] for ln in lines if ln.startswith("  design")]
    assert rows == [["design", "TD-059"]]  # the marked one is on no list
    assert cli.main(["repo", "--all"]) == 0
    assert "no lane:" not in capsys.readouterr().out
    assert cli.main(["--json", "repo"]) == 0
    got = json.loads(capsys.readouterr().out)[0]
    assert got["no_lane"] == [{"id": "TD-058", "why": WHY}]
    assert got["ledger"]["entries"][0]["no_lane"] == {"case": "owner", "why": WHY}


@pytest.mark.unit
def test_starts_clause_reads_the_starts_lanes_and_the_other_records(tmp_path):
    root = str(tmp_path / "lb")
    other = str(tmp_path / "two")
    readings = {
        root: {"name": "ledgerboard", "ledger": {"entries": [_e("TD-058"), _e("TD-060", owner="designer")]}},
        other: {"name": "two", "ledger": {"entries": [_e(f"TD-{n}") for n in range(1, 8)]}},
    }
    grinder = SimpleNamespace(dir=root, lane=GRINDER)
    rows = [
        {"repo": root, "team": "other", "lane": DESIGNER},  # another team's designer takes owner:designer
        {"repo": root, "team": "Grind", "lane": ["design-first", "owner:techlead"], "state": "closed"},  # replaced
        {"repo": root, "team": "x", "lane": ["design-first"], "superseded_by": "y"},  # superseded: never read
    ]
    gaps = teamrun.start_no_lane(lambda m, **kw: rows, readings, [grinder], "grind")
    assert [(g["repo"], g["id"], g["why"]) for g in gaps] == [("ledgerboard", "TD-058", WHY)]
    busy = [*rows, {"repo": root, "team": "grind", "lane": ["design-first", "owner:techlead"], "state": "working"}]
    assert teamrun.start_no_lane(lambda m, **kw: busy, readings, [grinder], "grind") == []  # a busy seat runs on

    def broken_list(m, **kw):
        raise TimeoutError

    assert teamrun.start_no_lane(broken_list, readings, [grinder], "grind") == []
    assert teamrun.no_lane_clause(gaps) == f"· no lane: TD-058 ({WHY})"
    two = SimpleNamespace(dir=other, lane=DESIGNER)
    gaps = teamrun.start_no_lane(lambda m, **kw: rows, readings, [grinder, two], "grind")
    clause = teamrun.no_lane_clause(gaps)
    assert clause.startswith(f"· no lane: ledgerboard: TD-058 ({WHY}); two: TD-1 (")
    assert clause.endswith("TD-5 (" + WHY + ") and 2 more")
    assert teamrun.no_lane_clause([]) == ""
    # two repos worked, one with gaps: still named
    quiet = {**readings, other: {"name": "two", "ledger": {"entries": []}}}
    gaps = teamrun.start_no_lane(lambda m, **kw: rows, quiet, [grinder, two], "grind")
    assert teamrun.no_lane_clause(gaps) == f"· no lane: ledgerboard: TD-058 ({WHY})"
    unserved = {root: {**readings[root], "seams": {"serve": {"ok": False, "lacks": [{"key": "x"}]}}}}
    assert teamrun.start_no_lane(lambda m, **kw: [], unserved, [grinder], "grind") == []
    broken = {root: {"ledger": {"error": "x", "entries": [_e("TD-058")]}}}
    assert teamrun.start_no_lane(lambda m, **kw: [], broken, [grinder], "grind") == []


# -- slice 2: the kind bar, the lanes line, the Repo page and the Start press (§4.5a, §4.5 screen 11) --------------

KIND_WHY = "no lane takes design-first"


def _seven_marked(root: str) -> dict:
    """test_seven_kinds' reading, marked against one grinder lane: its design entry TD-011 is no lane's."""
    from test_seven_kinds import _reading

    r = _reading(root)
    r["ledger"] = ledger.mark_no_lane(r["ledger"], [(GRINDER, "grind")])
    return r


@pytest.mark.unit
def test_the_kind_bar_draws_no_lane_after_live_check_with_each_why_and_its_list():
    from test_ui_team_summary import NOW, member

    from shiftlead.ui import app as ui

    r = _seven_marked("/r/samscrape")
    assert r["ledger"]["no_lane"] == [{"id": "TD-011", "why": KIND_WHY}]
    s = ui.team_summary("grind", [member("g1", "idle")], {"/r/samscrape": r}, {}, now=NOW)
    html = ui.templates.get_template("team_summary.html").render(g={"team": "grind", "summary": s})
    bar = html[html.index('aria-label="open entries by kind"') :]
    bar = bar[: bar.index("</div>")]
    assert 'class="bseg k-design"' not in bar  # one count, one kind: the marked entry left *design*
    assert bar.index("k-live-check") < bar.index("k-no-lane") < bar.index("k-blocked")
    seg = bar[bar.index('class="bseg k-no-lane"') :]
    seg = seg[: seg.index("</a>")]
    assert 'href="/repo/samscrape#debt-no-lane"' in seg and f'title="TD-011 — {KIND_WHY}"' in seg and ">1" in seg
    css = (__import__("pathlib").Path(ui.__file__).parent / "static" / "app.css").read_text(encoding="utf-8")
    assert (
        ".bseg.k-no-lane, .legend .k-no-lane { background: var(--warn-bg); border: 1px dashed var(--warn-line);" in css
    )


@pytest.mark.unit
def test_the_lanes_line_ends_with_what_no_lane_takes_in_both_forms():
    from shiftlead.ui import org

    r = _seven_marked("/r/samscrape")
    lanes = {"pickable": ["TD-010"], "design": [], "live_check": [], "rest": [], "members": []}
    ln = org.lanes_line("grind", lanes, r["ledger"]["by_kind"], org.entries_by_id(r))
    assert ln["text"].endswith(" · 1 no lane: TD-011") and ln["no_lane"] == ["TD-011"]
    html = org.templates.get_template("lanes_line.html").render(ln=ln, url="/repo/samscrape")
    assert (
        '<a class="strong" href="/repo/samscrape#debt-no-lane">1 no lane</a>: <a href="/repo/samscrape#TD-011">' in html
    )
    quiet = org.lanes_line("grind", lanes, {}, {"TD-010": {"id": "TD-010"}})
    assert "no lane" not in quiet["text"] and "no lane" not in org.templates.get_template("lanes_line.html").render(
        ln=quiet, url=""
    )


@pytest.mark.unit
def test_the_repo_page_lists_a_marked_entry_under_no_lane_and_folds_it_with_its_why(tmp_path, monkeypatch):
    from test_ui_repo_page import client, fake

    from shiftlead.ui import repo

    root = str(tmp_path / "samscrape")
    r = _seven_marked(root)
    lists = {x["key"]: x for x in repo.ledger_lists(r, [])}
    assert [k for k, _ in repo.LEDGER_LISTS].index("no-lane") == [k for k, _ in repo.LEDGER_LISTS].index(
        "live-check"
    ) + 1
    assert [e["id"] for e in lists["no-lane"]["rows"]] == ["TD-011"] and not lists["design"]["rows"]
    assert lists["no-lane"]["rows"][0]["flag"] == KIND_WHY
    html = client(monkeypatch, tmp_path, fake({root: r}, [])).get("/repo/samscrape").text
    assert "1 no lane" in html
    at = html.index('id="col-design"')
    assert 'id="TD-011"' not in html[at : html.index('class="bcol"', at + 1)]
    fold = html[html.index('class="bfold"') :]
    assert "no lane takes these (3)" in fold
    row = fold[fold.index('id="TD-011"') :]
    assert f'<span class="meta flag">· {KIND_WHY}</span>' in row[: row.index("</div>")]


@pytest.mark.unit
def test_the_rollup_draws_the_no_lane_segment_with_its_plain_title():
    from test_ui_team_summary import NOW, member

    from shiftlead.ui import app as ui

    r = _seven_marked("/r/samscrape")
    s = ui.team_summary("grind", [member("g1", "idle")], {"/r/samscrape": r}, {}, now=NOW)
    segs = s["repo"]["ledger"]["kind"]
    assert {k: v for k, v in segs[[x["key"] for x in segs].index("no-lane")].items() if k != "pct"} == {
        "key": "no-lane",
        "label": "no lane",
        "n": 1,
    }
    html = ui.templates.get_template("rollup.html").render(
        ro={"rows": [{"kind": "team", "key": "t", "segs": segs, "team": "grind"}]}, kind_bars=ui.KIND_BARS
    )
    assert '<span class="bseg k-no-lane' in html and 'title="1 no lane"' in html
