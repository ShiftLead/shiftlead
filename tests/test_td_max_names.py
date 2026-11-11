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
    team = _team()
    team.members[0] = orgmod.MemberDef(role="grinder", name="grinder-ao", count=3, size=2)
    assert team.extra_names("grinder-ao") == ["grinder-ao-3", "grinder-ao-4"]  # size + 2, past the size
    bare = orgmod.TeamDef(name="t", members=[orgmod.MemberDef(role="grinder", name="grind", count=1, size=1)])
    assert bare.extra_names("grind") == ["grind-2", "grind-3"]  # a `count: 1` line's bare name, then -2
    # a line sized 0 runs none at its size, and its default ceiling's extras are its first two names
    none = orgmod.TeamDef(name="t", members=[orgmod.MemberDef(role="grinder", name="grind", count=1, size=0)])
    assert none.ceiling("grind") == 2 and none.extra_names("grind") == ["grind", "grind-2"]


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


# ── the names readers read the extras (TD-1545 slice 7, §4.9 *Names, the size and the ceiling*) ──────────────


def test_session_and_started_names_read_each_line_and_seats_extras():
    team = _team()
    sized = ["manager-ao-1", "techlead-ao-1", "grinder-ao-1", "grinder-ao-2", "grinder-ao-3", "designer-ao-1"]
    assert team.session_names(extras=False) == sized
    assert team.session_names() == sized + [
        "techlead-ao-1-2", "techlead-ao-1-3", "grinder-ao-4", "grinder-ao-5", "designer-ao-1-2", "designer-ao-1-3",
    ]  # fmt: skip
    # the started names add the seats, and an `asks` seat's extras; a seat on `prs` and a pool scale not
    started = team.started_names()
    assert started[: len(team.session_names())] == team.session_names()
    assert started[len(team.session_names()) :] == [
        "fact-check-ao-1", "audit-ao-1", "qa-1", "qa-1-p2", "fact-check-ao-1-2", "fact-check-ao-1-3",
    ]  # fmt: skip
    assert team.started_names(extras=False) == sized + ["fact-check-ao-1", "audit-ao-1", "qa-1", "qa-1-p2"]
    off = _team(max="off")
    assert off.session_names() == sized and off.started_names() == off.started_names(extras=False)


def test_the_twice_named_check_reads_an_extra_and_says_a_twice_held_line_once():
    team = _team()
    team.members.append(orgmod.MemberDef(role="grinder", name="grinder-ao-4"))  # the grinder line's first extra
    assert team.twice_named() == ["grinder-ao-4"]
    assert _team(max={"grinder-ao": 3}).twice_named() == []  # no scaling on the line: no extra to meet
    # two lines of one name hold the same extras too: the name is said, its extras' names not again
    twin = _team(max="off")
    twin.members.append(orgmod.MemberDef(role="designer", name="designer-ao-1"))
    assert twin.twice_named() == ["designer-ao-1"]
    twin.max = None
    assert twin.twice_named() == ["designer-ao-1"]


def test_add_members_default_name_goes_past_the_lines_extras():
    assert _team().next_name("grinder") == "grinder-ao-6"  # past the size 3 and the extras -4, -5
    assert _team(max={"grinder-ao": 7}).next_name("grinder") == "grinder-ao-8"
    assert _team(max="off").next_name("grinder") == "grinder-ao-4"
    assert _team().next_name("designer") == "designer-ao-2"  # a line of its own: no -1-n extra is in the way


def test_a_name_two_teams_share_only_through_an_extra_is_read_after_the_merge():
    """The parse reads no extras (an old team's `off` is not merged yet), so it refuses only sized names;
    `shared_names` on the merged org says the rest, and a team at `off` shares nothing through an extra."""
    a = _team()
    b = orgmod.TeamDef(
        name="other", manager=orgmod.ManagerDef(role=orgmod.PERSON, name=""),
        members=[orgmod.MemberDef(role="grinder", name="grinder-ao-5")],
    )  # fmt: skip
    org = orgmod.Org(teams={"ao-grind": a, "other": b})
    assert orgmod.shared_names(org, extras=False) == []
    orgmod._names_per_repo(org, "org.yml")  # not refused at parse
    assert [(x, t.name, n) for x, t, n in orgmod.shared_names(org)] == [("ao-grind", "other", "grinder-ao-5")]
    merged = orgmod.with_settings(org, {"ao-grind": {"max": "off"}})
    assert orgmod.shared_names(merged) == []


def test_a_counted_line_held_twice_is_said_by_its_sized_names_and_a_seats_extra_is_held():
    """#3293's review: two `count: 2` lines of one name are said by `g-1`, `g-2` and not again by their extras
    `g-3`, `g-4`; and an `asks` seat's extra is a name a member line may not take."""
    twin = orgmod.TeamDef(
        name="t", manager=orgmod.ManagerDef(role=orgmod.PERSON, name=""),
        members=[orgmod.MemberDef(role="grinder", name="g", count=2) for _ in range(2)],
    )  # fmt: skip
    assert twin.twice_named() == ["g-1", "g-2"]
    team = _team()
    team.members.append(orgmod.MemberDef(role="checker", name="fact-check-ao-1-2"))
    assert team.twice_named() == ["fact-check-ao-1-2"]
    assert "fact-check-ao-1-3" in team.held_names() and "fact-check-ao-1-2" not in _team(max="off").held_names()
