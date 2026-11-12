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
