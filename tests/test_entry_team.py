"""An entry names its team (design §4.4 *An entry names its team*, §4.8 the claim, §4.7 `ao repo`; TD-730,
built by TD-762): the `**Team:**` line read as `team`, the `Fields:` line's `Team` vocabulary as
`declared_teams`, `needs_team` marked on an untagged or unknown entry and withheld from every lane,
`lane_matches` and `in_lanes` read with the lane's record's team, the claim's two refusals, and `ao repo`'s
words and `--json`."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import park_ticks

from sessionorc import ledger, mail, settle, work
from sessionorc.client import AgentError, LocalClient

NOW = datetime.now(UTC)
TOMORROW = (NOW.astimezone().date() + timedelta(days=1)).isoformat()
GRINDER = ["free-pick", "owner:grinder"]


def _entry(n: int, team: str = "", kind: str = "build", owner: str = "grinder", extra: str = "") -> str:
    head = f"## TD-{n:03d}: entry {n}\n\n**Priority:** Medium\n**Owner:** {owner}\n**Kind:** {kind}\n"
    return head + extra + (f"**Team:** {team}\n" if team else "") + "**Status:** Open\n\n**Why:** a reason.\n"


def _ledger(*parts: str, teams: str = "db | ops") -> str:
    fields = "Fields: Owner = grinder | paul | anchor" + (f"; Team = {teams}" if teams else "")
    return "# Ledger\n\n" + fields + "\n\n" + "\n".join(parts)


def _read(*parts: str, teams: str = "db | ops") -> dict[str, dict]:
    got = settle.mark_waits(ledger.entries(_ledger(*parts, teams=teams)), NOW)
    return {e["id"]: e for e in got}


def test_two_teams_mark_an_untagged_lane_entry_and_an_unknown_one_and_nothing_else():
    got = _read(
        _entry(1),  # pickable, untagged
        _entry(2, "qa"),  # unknown
        _entry(3, "db"),
        _entry(4, extra="**Blocked by:** TD-099\n"),  # blocked: a lane does not take it yet
        _entry(5, kind="evaluation"),
        _entry(6, owner="paul"),  # for you
        _entry(7, kind="design-first"),  # design: a lane takes it
        _entry(8, kind="live-check #1"),  # live check: a lane takes it
    )
    assert got["TD-001"]["needs_team"] == {"why": "untagged"}
    assert got["TD-002"]["needs_team"] == {"why": "unknown qa"}
    assert got["TD-007"]["needs_team"] == {"why": "untagged"}
    assert {i for i, e in got.items() if e.get("needs_team")} == {"TD-001", "TD-002", "TD-007", "TD-008"}
    assert got["TD-003"]["team"] == "db" and got["TD-001"]["team"] == ""
    assert got["TD-001"]["for_page"] == "pickable", "its page kind is unchanged"


def test_one_declared_name_requires_nothing_but_still_marks_an_unknown_one():
    got = _read(_entry(1), _entry(2, "qa"), _entry(3, "ao-grind"), teams="ao-grind")
    assert "needs_team" not in got["TD-001"] and "needs_team" not in got["TD-003"]
    assert got["TD-002"]["needs_team"] == {"why": "unknown qa"}
    # no vocabulary at all: nothing is marked, a stray line is the cadence's to flag
    bare = _read(_entry(1), _entry(2, "qa"), teams="")
    assert not any(e.get("needs_team") for e in bare.values())


def test_a_team_reads_case_folded_and_the_reading_carries_the_vocabulary_in_order(tmp_path):
    got = _read(_entry(1, "DB"))
    assert got["TD-001"]["team"] == "db" and "needs_team" not in got["TD-001"]
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "technical_debt.md").write_text(
        _ledger(_entry(1, "ops"), _entry(2), teams="ops | db"), encoding="utf-8"
    )
    r = ledger.reading(tmp_path, NOW, with_history=False)
    assert r["declared_teams"] == ["ops", "db"] and r["needs_team"] == ["TD-002"]


def test_a_lane_takes_its_own_teams_entries_and_a_teamless_lane_takes_both():
    got = _read(_entry(1, "db"), _entry(2, "ops"), _entry(3), _entry(4, "DB"))
    assert ledger.lane_matches(GRINDER, got["TD-001"], "db")
    assert not ledger.lane_matches(GRINDER, got["TD-002"], "db")
    assert ledger.lane_matches(GRINDER, got["TD-004"], "db") and ledger.lane_matches(GRINDER, got["TD-001"], "DB")
    assert ledger.lane_matches(GRINDER, got["TD-001"]) and ledger.lane_matches(GRINDER, got["TD-002"], "")
    assert not any(ledger.lane_matches(GRINDER, got["TD-003"], t) for t in (None, "", "db", "ops")), "untagged"
    # one declared name, a lane of another team: what is tagged otherwise is not its; untagged is
    one = _read(_entry(1, "db"), _entry(2), teams="db")
    assert not ledger.lane_matches(GRINDER, one["TD-001"], "ops") and ledger.lane_matches(GRINDER, one["TD-002"], "ops")


def test_a_work_order_carries_no_team_and_is_in_every_teams_lane():
    order = {"id": "board:ab12cd34", "work_order": True, "pickable": "yes"}
    assert ledger.lane_matches(GRINDER, order, "db") and ledger.lane_matches(GRINDER, order, "ops")


def test_in_lanes_reads_each_lane_with_its_records_team_and_counts_a_marked_entry_nowhere():
    entries = list(_read(_entry(1, "db"), _entry(2, "ops"), _entry(3), _entry(4, "qa")).values())
    records = [
        {"id": "d1", "name": "db-grinder", "lane": GRINDER, "team": "db", "state": "idle", "out_of_work": {"at": "x"}},
        {"id": "o1", "name": "ops-grinder", "lane": GRINDER, "team": "ops", "state": "idle"},
    ]
    db = ledger.in_lanes(entries, records[:1])
    assert db["pickable"] == ["TD-001"] and db["rest"] == [], "another team's entry is no rest; a marked one none"
    assert db["members"][0]["ids"] == ["TD-001"]
    assert db["out_of_work"] == [{"id": "d1", "name": "db-grinder", "ids": ["TD-001"]}]
    teamless = ledger.in_lanes(entries, [{**records[0], "team": ""}])
    assert teamless["pickable"] == ["TD-001", "TD-002"], "a teamless lane narrows nothing; a marked entry stays out"
    both = ledger.in_lanes(entries, records)
    assert both["pickable"] == ["TD-001", "TD-002"]
    assert [m["ids"] for m in both["members"]] == [["TD-001"], ["TD-002"]]


def test_a_settling_or_waiting_entry_that_needs_a_team_reads_as_that_first():
    got = _read(_entry(1, extra=f"**Waits:** until {TOMORROW} — CI\n"), _entry(2))
    got["TD-002"]["settling"] = {"until": (NOW + timedelta(minutes=7)).isoformat()}
    assert all(e.get("needs_team") for e in got.values())
    assert settle.wait_refusal(got["TD-001"]).startswith(f"TD-001 waits until {TOMORROW}")
    assert settle.words(got["TD-002"], NOW).startswith("settles")


def test_rule_six_reads_the_members_team():
    got = _read(_entry(1, "db"), _entry(2, "ops"))
    member = SimpleNamespace(lane=GRINDER, team="db", lane_seen={"ids": []})
    assert work.reread(member, list(got.values()))[1] == ["TD-001"]


def test_the_claim_refusals_in_their_words():
    got = _read(_entry(1, "db"), _entry(2), _entry(3, "qa"))
    assert settle.team_refusal(got["TD-001"], "compliance", "compliance-grinder-1").startswith(
        "TD-001 is db's: compliance-grinder-1 is compliance's"
    )
    assert settle.team_refusal(got["TD-001"], "DB", "g") is None
    assert settle.team_refusal(got["TD-001"], "", "g") is None, "never raised against a claimer with no team"
    assert settle.team_refusal(got["TD-002"], "", "g").startswith("TD-002 needs a team (untagged)")
    assert settle.team_refusal(got["TD-003"], "db", "g").startswith("TD-003 needs a team (unknown qa)")


@pytest.mark.integration
async def test_a_claim_across_teams_or_on_a_marked_entry_is_refused_and_force_passes_it(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "r")
    got = _read(_entry(1, "db"), _entry(2), _entry(3, "ops"))
    agent._repos[root] = {"name": "r", "root": root, "ledger": {"entries": list(got.values())}}
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        agent.sessions[g].team = "ops"
        # the person's own shell with a team's badge (TD-821) reads it as any badged record does
        assert mail.person_shell(agent.sessions[g])
        with pytest.raises(AgentError, match="TD-001 is db's: g is ops's"):
            await person.call("progress", id=g, ref="TD-001", status="claimed")
        with pytest.raises(AgentError, match=r"TD-002 needs a team \(untagged\)"):
            await person.call("progress", id=g, ref="TD-002", status="claimed")
        await person.call("progress", id=g, ref="TD-003", status="claimed")
        await person.call("progress", id=g, ref="TD-001", status="claimed", force=True)
        agent.sessions[g].team = ""  # a teamless claimer: another team's entry passes, a marked one does not
        with pytest.raises(AgentError, match=r"TD-002 needs a team \(untagged\)"):
            await person.call("progress", id=g, ref="TD-002", status="claimed")
        assert [e.ref for e in agent.sessions[g].progress] == ["TD-003", "TD-001"]


@pytest.fixture
def git_repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    return root


def test_ao_repo_says_needs_a_team_and_json_carries_the_three_fields(git_repo, monkeypatch, capsys):
    from shiftlead import cli

    led = ledger.entries(_ledger(_entry(1, "db"), _entry(2), _entry(3, "qa")))
    led_reading = {
        "entries": led,
        "by_kind": {"pickable": 3},
        "declared_teams": ["db", "ops"],
        "needs_team": ["TD-002", "TD-003"],
    }
    reading = {str(git_repo): {"name": "r", "root": str(git_repo), "prs": {"open": []}, "ledger": led_reading}}
    fleet = [{"id": "w1", "name": "w1", "lane": GRINDER, "state": "idle", "repo": str(git_repo), "team": "db"}]
    monkeypatch.setattr(
        cli,
        "call_sync",
        lambda rpc, **kw: {"repos": reading, "list": fleet, "doing_log": {}, "queue": {}, "inbox": {}}[rpc],
    )
    monkeypatch.chdir(git_repo)
    assert cli.main(["repo"]) == 0
    out = capsys.readouterr().out
    assert "1 pickable (db 1)" in out, "a marked entry is not counted pickable"
    assert "  needs a team: TD-002, TD-003 — no techlead seat to tag them\n" in out
    assert "grinder needs a team" in next(line for line in out.splitlines() if " TD-002 " in line)
    assert "needs a team" not in next(line for line in out.splitlines() if " TD-001 " in line)
    assert cli.main(["--json", "repo"]) == 0
    r = json.loads(capsys.readouterr().out)[0]
    assert r["declared_teams"] == ["db", "ops"] and r["needs_team"] == ["TD-002", "TD-003"]
    assert [e["team"] for e in r["ledger"]["entries"]] == ["db", "", "qa"]


@pytest.mark.parametrize(
    ("seats", "said"),
    [
        ([("tl-ops", "ops", True, "idle"), ("tl-db", "db", True, "closed")], "handed to tl-db"),
        ([("tl-ops", "ops", True, "closed")], "tl-ops's team is stopped"),
        ([("tl-db", "db", False, "closed")], "no techlead seat carries tags yet — the next Start of db writes it"),
        ([], "no techlead seat to tag them"),
    ],
)
def test_ao_repo_names_the_tagging_seat_or_why_there_is_none(git_repo, monkeypatch, capsys, seats, said):
    """§4.4 *Shown where it is read* (TD-763): the first declared live team's seat carrying `tags`."""
    from shiftlead import cli

    led = ledger.entries(_ledger(_entry(2)))
    led_reading = {"entries": led, "by_kind": {}, "declared_teams": ["db", "ops"], "needs_team": ["TD-002"]}
    reading = {str(git_repo): {"name": "r", "root": str(git_repo), "prs": {"open": []}, "ledger": led_reading}}
    fleet = [
        {
            "id": n,
            "name": n,
            "state": st,
            "repo": str(git_repo),
            "team": team,
            "unattended": True,
            "seat": {"trigger": "asks", **({"tags": True} if tags else {})},
        }
        for n, team, tags, st in seats
    ]
    # a live grinder of db keeps db live; ops has nothing live but its seat, when that is idle
    fleet.append({"id": "g", "name": "g", "state": "idle", "repo": str(git_repo), "team": "db", "unattended": True})
    monkeypatch.setattr(
        cli,
        "call_sync",
        lambda rpc, **kw: {"repos": reading, "list": fleet, "doing_log": {}, "queue": {}, "inbox": {}}[rpc],
    )
    monkeypatch.chdir(git_repo)
    assert cli.main(["repo"]) == 0
    assert f"  needs a team: TD-002 — {said}\n" in capsys.readouterr().out
