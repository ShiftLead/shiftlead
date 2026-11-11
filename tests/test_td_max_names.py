"""td-max's ceilings and extras' names on the definition (design §4.9 *Scaling with the work*, *Names, the size
and the ceiling*; TD-1545 slice 2): `teams.<team>.max` merged onto `TeamDef`, `ceiling` and `extra_names`."""

from __future__ import annotations

from shiftlead import org as orgmod


def _team(**kw) -> orgmod.TeamDef:
    return orgmod.TeamDef(
        name="ao-grind",
        manager=orgmod.ManagerDef(role="manager", name="manager-ao-1"),
        members=[
            orgmod.MemberDef(role="grinder", name="grinder-ao", count=3),
            orgmod.MemberDef(role="designer", name="designer-ao-1"),
        ],
        techlead=orgmod.TechleadDef(name="techlead-ao-1"),
        seats=[
            orgmod.SeatDef(name="fact-check-ao-1", role="fact-checker"),
            orgmod.SeatDef(name="audit-ao-1", role="auditor", trigger="prs", after="10"),
            orgmod.SeatDef(name="qa-1", role="qa", pool=["a", "b"]),
        ],
        **kw,
    )


def test_no_max_key_is_the_default_ceilings_size_plus_two():
    team = _team()
    assert team.max is None
    assert team.ceiling("grinder-ao") == 5
    assert team.extra_names("grinder-ao") == ["grinder-ao-4", "grinder-ao-5"]
    # a seat's size is 1, its extras `<name>-2`, `-3`, as a `count: 1` line's are
    assert team.ceiling("techlead-ao-1") == 3
    assert team.extra_names("techlead-ao-1") == ["techlead-ao-1-2", "techlead-ao-1-3"]
    assert team.extra_names("fact-check-ao-1") == ["fact-check-ao-1-2", "fact-check-ao-1-3"]
    assert team.extra_names("designer-ao-1") == ["designer-ao-1-2", "designer-ao-1-3"]


def test_a_written_max_is_the_lines_own_and_the_rest_keep_their_defaults():
    team = _team(max={"grinder-ao": 6, "techlead-ao-1": 2})
    assert team.extra_names("grinder-ao") == ["grinder-ao-4", "grinder-ao-5", "grinder-ao-6"]
    assert team.extra_names("techlead-ao-1") == ["techlead-ao-1-2"]
    assert team.ceiling("designer-ao-1") == 3  # no key: its default


def test_a_max_at_or_below_the_size_and_off_are_no_scaling():
    for top in (0, 2, 3):
        team = _team(max={"grinder-ao": top})
        assert team.extra_names("grinder-ao") == []
    off = _team(max="off")
    for name in ("grinder-ao", "techlead-ao-1", "fact-check-ao-1", "designer-ao-1"):
        assert off.ceiling(name) == 0 and off.extra_names(name) == []


def test_the_size_is_the_floor_the_extras_go_past():
    team = _team(size={"grinder-ao": 2})
    team.members[0] = orgmod.MemberDef(role="grinder", name="grinder-ao", count=3, size=2)
    assert team.extra_names("grinder-ao") == ["grinder-ao-3", "grinder-ao-4"]  # size + 2, past the size
    bare = orgmod.TeamDef(name="t", members=[orgmod.MemberDef(role="grinder", name="grind", count=1, size=1)])
    assert bare.extra_names("grind") == ["grind-2", "grind-3"]  # a `count: 1` line's bare name, then -2


def test_what_may_not_scale_says_why_and_has_no_extras():
    team = _team(max={"manager-ao-1": 3, "audit-ao-1": 3, "qa-1": 3})
    assert team.scale_refusal("manager-ao-1") == "one lead per team"
    assert team.scale_refusal("audit-ao-1") == "one pass covers the repo"
    assert team.scale_refusal("qa-1") == "a pool is a fallback, not capacity"
    assert "no member line or seat" in team.scale_refusal("nope")
    for name in ("manager-ao-1", "audit-ao-1", "qa-1", "nope"):
        assert team.ceiling(name) == 0 and team.extra_names(name) == []
    for name in ("grinder-ao", "techlead-ao-1", "fact-check-ao-1"):
        assert team.scale_refusal(name) == ""
    # a person-led team has no manager session, so its name is no line's refusal by being the manager's
    person = orgmod.TeamDef(name="t", manager=orgmod.ManagerDef(role=orgmod.PERSON, name=""))
    assert "no member line or seat" in person.scale_refusal("x")


def test_with_settings_merges_max_onto_a_copy():
    org = orgmod.Org(teams={"ao-grind": _team(), "other": _team()})
    got = orgmod.with_settings(org, {"ao-grind": {"max": {"grinder-ao": 6, "bad": "x"}}, "other": {"max": "off"}})
    assert got.teams["ao-grind"].max == {"grinder-ao": 6}  # a value that is not a number is dropped
    assert got.teams["other"].max == "off"
    assert org.teams["ao-grind"].max is None  # a copy: the definition never carries it
    assert orgmod.with_settings(org, {"ao-grind": {"size": {}}}).teams["ao-grind"].max is None  # no key: defaults
    assert orgmod.with_settings(org, {"ao-grind": {"on_work": "ask"}}) is org  # nothing to merge: the org as read
