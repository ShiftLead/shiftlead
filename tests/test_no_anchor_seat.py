"""The anchor seat retired, on the client's side (design §4.9b *No anchor seat*, §4.9 *A definition
written before TD-722*, §5, TD-757): `anchor:` on a team or a repo is refused as retired, `anchor: false`
read and passed over; no preset is called `anchor`; a Start and Apply write no `<team>-anchor` and ask
no `checkout_held`. The manager on call (§6 rule 3, TD-410) and a seat the run lacks (TD-400), which
the seat's tests once carried, are held here. The tick's side is tests/test_anchor_retired.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shiftlead import org as orgmod
from shiftlead import repoconfig, teamrun, teams

pytestmark = pytest.mark.unit

HOST = "kmaster"
REPO = Path(__file__).resolve().parents[1]


def _org(tmp_path: Path, monkeypatch, teams_doc: dict, *, repos=("alpha",)) -> orgmod.Org:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    for r in repos:
        (tmp_path / r / ".git").mkdir(parents=True, exist_ok=True)
    doc = {"projects": {"p": {"repos": {r: {HOST: str(tmp_path / r)} for r in repos}}}, "teams": teams_doc}
    (home / "org.yml").write_text(yaml.safe_dump(doc))
    return orgmod.load()


def _team(**extra) -> dict:
    return {
        "projects": ["p"],
        "manager": {"role": "manager", "name": "lead"},
        "techlead": {"name": "tl"},
        "members": [{"role": "grinder", "name": "g"}],
        **extra,
    }


def _fake():
    calls: list[tuple[str, dict]] = []

    def call(method, **params):
        calls.append((method, params))
        if method == "name_check":
            return {"name": params["name"], "verdict": "free"}
        if method == "list":  # the definition's renames and removals, read by every Start (TD-706): none here
            return []
        if method == "create":
            return {"id": f"ao-alpha-{params['name']}", "name": params["name"]}
        raise AssertionError(method)  # `checkout_held` among them: the RPC is gone

    return call, calls


# ── the definitions ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [True, None, {}, {"name": "keeper"}, "yes"])
def test_an_anchor_key_on_a_team_is_refused_as_retired(tmp_path, monkeypatch, value):
    with pytest.raises(ValueError, match=r"teams\.t: `anchor:` is retired — the anchor seat is gone \(§4\.9b"):
        _org(tmp_path, monkeypatch, {"t": _team(anchor=value)})


def test_anchor_false_on_a_team_is_read_and_passed_over(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {"t": _team(anchor=False), "u": _team()})
    for name in ("t", "u"):
        assert org.teams[name].session_names() == ["lead", "tl", "g"]
        assert not hasattr(org.teams[name], "anchor")


def test_anchor_is_no_preset_so_a_repos_roles_anchor_block_is_refused(tmp_path):
    """§4.9b *No anchor seat*: the preset is gone, so a repo's `roles: anchor:` overlays nothing and
    `repoconfig.load` refuses it (an overlay is not a definition, §4.9c) — why shiftlead's own block went."""
    assert "anchor" not in repoconfig.PRESETS
    assert not hasattr(orgmod, "AnchorDef") and not hasattr(orgmod, "ANCHOR_WHEN")
    (tmp_path / ".shiftlead.yml").write_text("roles: {anchor: {brief: docs/a.md}}\n")
    with pytest.raises(ValueError, match=r"`roles`\.anchor: unknown role 'anchor'"):
        repoconfig.load(tmp_path)


def test_a_repos_anchor_key_is_refused_as_retired_and_false_passed_over(tmp_path):
    assert repoconfig.load_text("anchor: false\n", tmp_path).ledger == repoconfig.DEFAULT_LEDGER
    for text in ("anchor: true\n", "anchor: {}\n"):
        with pytest.raises(
            ValueError, match=r"`anchor` is not a `\.shiftlead\.yml` key any more .*anchor seat is retired"
        ):
            repoconfig.load_text(text, tmp_path)


def test_shiftleads_own_file_loads_with_no_anchor_role():
    cfg = repoconfig.load(REPO)
    assert "anchor" not in cfg.roles
    assert "anchor:" not in (REPO / ".shiftlead.yml").read_text().split("roles:", 1)[1]


# ── a Start and Apply ────────────────────────────────────────────────────────────────────────────


def test_a_start_writes_no_anchor_and_every_session_takes_a_worktree(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, {"t": _team()})
    p = teams.plan(org, "t", HOST)
    assert [x.name for x in p.launches] == ["lead", "tl", "g"]
    call, calls = _fake()
    _, out = teamrun.start(call, org, "t", HOST)
    made = [p for m, p in calls if m == "create"]
    assert [p["name"] for p in made] == ["lead", "tl", "g"]
    assert not any(p["name"] == "t-anchor" or p.get("role") == "anchor" for p in made)
    assert all(p["worktree"] == p["name"] for p in made)  # no session in the checkout itself (§9 invariant 2)
    assert all("held_reason" not in p for p in made)
    assert not any(n.startswith("t-anchor") for n in out["notes"])


def test_ao_team_list_and_members_name_no_anchor(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    org = _org(tmp_path, monkeypatch, {"t": _team()})
    rows = {r["name"]: r for r in teamrun.rows(org, [])}
    assert "anchor" not in rows["t"] and "anchor" not in [r["role"] for r in rows["t"]["roles"]]
    assert "anchor" not in teamrun.members_view(org, "t", [])
    js = (REPO / "src/shiftlead/ui/static/app.js").read_text()
    assert "anchor seat</span>" not in js and "the anchor seat's too" not in js
    monkeypatch.setattr(cli, "_org_here", lambda: org)
    monkeypatch.setattr(cli, "call_sync", lambda method, **params: [] if method == "list" else {})
    monkeypatch.setattr(teamrun, "flow_view", lambda *a, **k: {})
    assert cli.main(["team", "list"]) == 0
    assert "anchor" not in capsys.readouterr().out


def test_nothing_to_pick_says_no_anchor_seat():
    assert (
        teamrun.NOTHING_TO_PICK
        == "nothing to pick: every lane is empty, so the team will wind down as soon as it starts"
    )
    html = (REPO / "src/shiftlead/ui/templates/base.html").read_text()
    assert "the anchor seat's too" not in html


# ── the manager on call and a seat the run lacks (§6 rule 3, TD-400, TD-410) ─────────────────────


def test_a_start_writes_the_manager_on_call_held_and_its_members_name_it(tmp_path, monkeypatch, capsys):
    """TD-413 slice 1 (§6 rule 3 *A Start writes the seat and never fills it*, TD-410): the manager
    on call is created with `held`, before the rest, and every other record names its id in
    `controllers`; `ao team start` says *on call — comes when a member needs a reading* for it; a
    standing manager (`on_call: false`) is created live as before."""
    org = _org(
        tmp_path,
        monkeypatch,
        {"t": _team(), "s": _team(manager={"role": "manager", "name": "boss", "on_call": False})},
    )
    call, calls = _fake()
    _, out = teamrun.start(call, org, "t", HOST)
    made = [p for m, p in calls if m == "create"]
    assert made[0]["name"] == "lead" and made[0]["held"] is True and "held_reason" not in made[0]
    assert made[0]["seat"]["trigger"] == "team" and made[0]["unattended"] is True
    assert all(p["controllers"] == ["ao-alpha-lead"] for p in made[1:]) and out["manager"] == "ao-alpha-lead"
    calls.clear()
    teamrun.start(call, org, "s", HOST)
    (boss,) = [p for m, p in calls if m == "create" and p["name"] == "boss"]
    assert "held" not in boss
    # a manager on call the definition asks to be watched starts live: `create` writes a held seat unattended only
    watched = _org(tmp_path, monkeypatch, {"w": _team(manager={"role": "manager", "name": "eye", "unattended": False})})
    calls.clear()
    teamrun.start(call, watched, "w", HOST)
    (eye,) = [p for m, p in calls if m == "create" and p["name"] == "eye"]
    assert eye["unattended"] is False and "held" not in eye
    from shiftlead import cli

    org = _org(tmp_path, monkeypatch, {"t": _team()})
    p = teams.plan(org, "t", HOST)
    lead = {"id": "ao-alpha-lead", "name": "lead", "state": "closed", "dir": "/d"}
    assert (
        cli._team_line(lead, "t", p)
        == "ao-alpha-lead  manager manager  /d  on call — comes when a member needs a reading"
    )
    assert cli._team_line({**lead, "state": "working"}, "t", p) == "ao-alpha-lead  manager manager  /d"


def _running(p: teams.Plan, without: tuple[str, ...] = ("tl",)) -> list[dict]:
    """A live record of every launch but `without`'s: the team as it ran before it had that seat."""
    rec = {"team": "t", "state": "working"}
    return [
        {**rec, "id": f"ao-alpha-{x.name}", "name": x.name, "lane": x.lane, "review": x.review}
        for x in p.launches
        if x.name not in without
    ]


def test_a_seat_the_run_lacks_is_a_start_under_a_flow_or_none_and_one_with_a_record_is_not(tmp_path, monkeypatch):
    """TD-400 (§4.9c *A seat the definition names that the run has no record of is a difference too*):
    the techlead a run lacks reads `start`, a seat, under a flow or with none; a record of it — live or
    closed between fills — is nothing; a team with no flow compares its seats alone."""
    org = _org(tmp_path, monkeypatch, {"t": _team()})
    p = teams.plan(org, "t", HOST)
    live = _running(p)
    assert p.flow is None
    (d,) = teamrun.differences(p, live)
    assert (d.name, d.act, d.seat, d.line(None)) == ("tl", "start", True, "tl: starts")
    # a member a team with no flow lacks is no difference (no flow compiles it)
    assert [x.name for x in teamrun.differences(p, _running(p, ("tl", "g")))] == ["tl"]
    for state in ("working", "closed"):
        rec = {"id": "ao-alpha-tl", "name": "tl", "team": "t", "state": state, "seat": {"trigger": "asks"}}
        assert teamrun.differences(p, [*live, rec]) == []
    p.flow = "td"
    starts = [d for d in teamrun.differences(p, live) if d.act == "start"]
    assert [(d.name, d.seat) for d in starts] == [("tl", True)]
    assert starts[0].line("td") == "tl: starts under td"
    assert teamrun.differences(p, [{**r, "state": "exited"} for r in live]) == []


def _applying(tmp_path, monkeypatch, live_of=None):
    org = _org(tmp_path, monkeypatch, {"t": _team()})
    p = teams.plan(org, "t", HOST)
    live = live_of(p) if live_of else _running(p)
    calls: list[tuple[str, dict]] = []

    def call(method, **params):
        calls.append((method, params))
        if method == "list":
            return live
        if method == "name_check":
            return {"name": params["name"], "verdict": "free"}
        if method == "create":
            return {"id": f"ao-alpha-{params['name']}", "name": params["name"]}
        raise AssertionError(method)

    return org, call, calls


def test_apply_creates_a_seat_the_run_lacks_in_a_worktree_under_the_manager(tmp_path, monkeypatch):
    org, call, calls = _applying(tmp_path, monkeypatch)
    got = teamrun.apply(call, org, "t", HOST)
    (made,) = [p for m, p in calls if m == "create"]
    assert made["name"] == "tl" and "held" not in made and "held_reason" not in made
    assert made["controllers"] == ["ao-alpha-lead"] and made["worktree"] == "tl"
    assert [r["line"] for r in got["applied"]] == ["tl: starts"]


def test_apply_creates_a_manager_on_call_the_run_lacks_held(tmp_path, monkeypatch):
    """TD-413 slice 1 (§4.9c, TD-410): a live team whose run has no manager record reads it as a seat
    to start, and Apply writes it held, as a Start does, the line saying when it comes; a seat Apply
    starts beside a manager closed on call names it as its controller."""
    org, call, calls = _applying(tmp_path, monkeypatch, lambda p: _running(p, ("lead",)))
    got = teamrun.apply(call, org, "t", HOST)
    made = {p["name"]: p for m, p in calls if m == "create"}
    assert made["lead"]["held"] is True and "held_reason" not in made["lead"] and made["lead"]["controllers"] == []
    assert "lead: on call — comes when a member needs a reading" in [r["line"] for r in got["applied"]]
    calls.clear()
    org, call, calls = _applying(
        tmp_path,
        monkeypatch,
        lambda p: [
            *_running(p, ("lead", "tl")),
            {"team": "t", "state": "closed", "id": "ao-alpha-lead", "name": "lead", "seat": {"trigger": "team"}},
        ],
    )
    teamrun.apply(call, org, "t", HOST)
    (tl,) = [p for m, p in calls if m == "create"]
    assert tl["name"] == "tl" and tl["controllers"] == ["ao-alpha-lead"]


def test_the_mark_reads_definition_changed_where_seats_are_all_that_differ_or_no_flow_runs():
    seat = {"name": "tl", "act": "start", "seat": True, "line": "tl: starts"}
    member = {"name": "g", "act": "relaunch", "seat": False, "line": "g: relaunched — lane a → b"}
    assert teamrun.definition_changed([seat], "td") and teamrun.definition_changed([member], None)
    assert not teamrun.definition_changed([seat, member], "td") and not teamrun.definition_changed([], None)
    from shiftlead.ui.repo import flow_head

    assert flow_head({"flow": None, "differences": [seat]}, live=True)["definition_changed"] is True
    assert flow_head({"flow": None, "differences": [seat]}, live=False)["flow_changed"] == []
    head = flow_head({"flow": "td", "flows": [], "differences": [seat, member]}, live=True)
    assert head["flow_changed"] == [seat, member] and head["definition_changed"] is False
