"""`shiftlead.org` — the `org.yml` reader (design §4.9, TD-040 step b): the defaults, the
validation, a repo's own `teams:` folded in, and the per-host checkout lookup."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shiftlead import org

ORG = {
    "projects": {
        "shiftlead": {"repos": {"shiftlead": {"kmaster": "~/agentorc"}}},
        "guardians": {
            "title": "Guardians",
            "repos": {
                "guardians": {"devenv": "/workspaces/guardians"},
                "guardians-api": {"devenv": "/workspaces/guardians/api"},
            },
        },
    },
    "teams": {
        "ao-grind": {
            "repo": "shiftlead",
            "manager": {"role": "manager", "name": "manager-ao-1"},
            "members": [
                {"role": "grinder", "count": 2, "name": "tdgrind-ao", "lane": "free-pick"},
                {"role": "hunter", "name": "hunter-ao", "lane": "ui"},
            ],
        },
        "guardians": {
            "repo": "guardians-api",
            "manager": {"profile": "orc"},
            "members": [
                {"role": "grinder", "brief": "docs/briefs/api-grinder.md"},
            ],
        },
        "guardians-ui": {
            "repo": "guardians",
            "manager": {"role": "person"},
            "members": [{"role": "grinder", "unattended": False, "grants": ["control"]}],
        },
    },
    "roles": {"grinder": {"profile": "grind"}},
}


def write(tmp_path: Path, doc: object) -> Path:
    p = tmp_path / "org.yml"
    p.write_text(yaml.safe_dump(doc) if not isinstance(doc, str) else doc)
    return p


def test_missing_file_is_an_empty_org(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    o = org.load()
    assert o.projects == {} and o.teams == {} and o.roles == {}
    assert o.path == tmp_path / "org.yml"
    assert o.checkout("shiftlead", "kmaster") is None


def test_projects_are_headings_and_checkouts_one_store_per_repo(tmp_path):
    """§4.9 *Projects* (TD-722): a project is a heading on repos with an optional `title`; where each
    repo is checked out per host is one store, `Org.checkouts`, read by `checkout(repo, host)`."""
    o = org.load(write(tmp_path, ORG))
    assert o.checkout("shiftlead", "kmaster") == Path("~/agentorc").expanduser()
    assert o.checkout("guardians-api", "devenv") == Path("/workspaces/guardians/api")
    assert o.checkout("guardians-api", "kmaster") is None  # not on this host: phase 2
    assert o.checkout("nope", "devenv") is None
    assert o.projects["guardians"].title == "Guardians" and o.projects["shiftlead"].title == ""
    assert list(o.projects["guardians"].repos) == ["guardians", "guardians-api"]  # the heading keeps the names
    # a repo's project is the heading that lists it, else the repo's own name (a heading of its own)
    assert o.project_of("guardians-api") == "guardians" and o.project_of("loose") == "loose"
    assert o.roles == {"grinder": {"profile": "grind"}}
    assert o.path == tmp_path / "org.yml"


def test_every_default_of_section_4_9(tmp_path):
    o = org.load(write(tmp_path, ORG))
    grind = o.teams["ao-grind"]
    assert grind.source == tmp_path / "org.yml" and grind.repo == "shiftlead"
    assert grind.manager == org.ManagerDef(role="manager", name="manager-ao-1", profile=None)
    two, one = grind.members
    # count 1, name = the role, unattended true, grants/brief/profile = the role's; no `home`: the team's repo
    assert one == org.MemberDef(role="hunter", name="hunter-ao", lane=["ui"])
    assert one.count == 1 and one.unattended is True and one.grants is None and one.brief is None
    assert two.count == 2 and two.lane == ["free-pick"] and two.names() == ["tdgrind-ao-1", "tdgrind-ao-2"]
    assert one.names() == ["hunter-ao"]
    # manager defaults: role manager, name <team>-lead
    g = o.teams["guardians"]
    assert g.manager.role == "manager" and g.manager.name == "guardians-lead" and g.manager.profile == "orc"
    assert g.members[0].brief == "docs/briefs/api-grinder.md"
    assert len(g.members) == 1  # no team holds another (§4.9 *Teams*)
    ui = o.teams["guardians-ui"]
    assert ui.manager.role == "person" and ui.repo == "guardians"
    assert ui.members[0].unattended is False and ui.members[0].grants == ["control"]
    assert o.team_repos(g) == ["guardians-api"]


def test_member_name_defaults_to_the_role_and_lane_forms(tmp_path):
    doc = {
        "projects": {"p": {"repos": {"r": {"h": "/r"}}}},
        "teams": {
            "t": {
                "repo": "r",
                "members": [{"role": "grinder", "lane": "TD-027, TD-019"}, {"role": "x", "lane": ["a"]}],
            }
        },
    }
    t = org.load(write(tmp_path, doc)).teams["t"]
    assert t.repo == "r" and t.manager.name == "t-lead"
    assert [m.name for m in t.members] == ["grinder", "x"]
    assert t.members[0].lane == ["TD-027", "TD-019"] and t.members[1].lane == ["a"]


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ("- a list", "the top level must be a mapping"),
        ({"projects": [1]}, "projects must be a mapping"),
        ({"projects": {"p": {"repos": "x"}}}, "projects.p.repos must be a mapping"),
        ({"projects": {"p": {"repos": {"r": "x"}}}}, "projects.p.repos.r must be a mapping"),
        ({"teams": {"t": [1]}}, "teams.t must be a mapping"),
        ({"teams": {"t": {"projects": ["p"]}}}, "teams.t.projects: 'p' is not a defined project"),
        ({"projects": {"p": {"repos": {"r": {"h": "/r"}}}}, "teams": {"t": {}}}, "teams.t.repo: a team works one repo"),
        (
            {"projects": {"p": {"repos": {"r": {"h": "/r"}}}, "q": {"repos": {"r": {"h": "/r"}}}}},
            "projects: repo 'r' is listed by p and by q — a repo sits in at most one project",
        ),
        ({"projects": {"p": {"repo": {}}}}, "projects.p: unknown key(s) ['repo']"),
        ({"projects": {"p": {"title": [1]}}}, "projects.p.title must be a string"),
        (
            {"projects": {"p": {}}, "teams": {"t": {"projects": ["p"]}}},
            "teams.t: `projects:` is gone — write `repo: <repo>`",
        ),
        (
            {"projects": {"p": {"repos": {"r": {"h": "/r"}}}}, "teams": {"t": {"repo": "r", "members": {}}}},
            "teams.t.members must be a list",
        ),
        (
            {"projects": {"p": {"repos": {"r": {"h": "/r"}}}}, "teams": {"t": {"repo": "r", "members": [{}]}}},
            "teams.t.members[0].role is required",
        ),
        (
            {
                "projects": {"p": {"repos": {"r": {"h": "/r"}}}},
                "teams": {"t": {"repo": "r", "members": [{"role": "g", "count": 0}]}},
            },
            "teams.t.members[0].count must be a positive integer",
        ),
        (
            {
                "projects": {"p": {"repos": {"r": {"h": "/r"}}}},
                "teams": {"t": {"repo": "r", "members": [{"role": "g", "unattended": "no"}]}},
            },
            "teams.t.members[0].unattended must be true or false",
        ),
        (
            {
                "projects": {"p": {"repos": {"r": {"h": "/r"}}}},
                "teams": {"t": {"repo": "r", "members": [{"team": "x", "role": "g"}]}},
            },
            "teams.t.members[0].team: no team holds another",
        ),
        (
            {
                "projects": {"p": {"repos": {"r": {"h": "/r"}}}},
                "teams": {"t": {"repo": "r", "members": [{"team": "t"}]}},
            },
            "teams.t.members[0].team: no team holds another",
        ),
        ({"roles": {"g": [1]}}, "roles.g must be a mapping"),
    ],
)
def test_malformed_files_name_the_key(tmp_path, doc, message):
    with pytest.raises(ValueError, match="org.yml: " + __import__("re").escape(message)):
        org.load(write(tmp_path, doc))


def test_the_old_keys_are_refused_by_name_with_their_fix(tmp_path):
    """§4.9 *A definition written before TD-722*: `projects:` and `home:` are refused by name, as any
    key nobody reads is, the message saying the fix — `repo:` naming the one repo they meant (the
    homes where any is written, else the projects' repos), or, where they stretch over two, a team
    per repo under their heading. There is no release of warnings."""
    doc = dict(ORG, teams={"a": {"projects": ["shiftlead"], "members": [{"role": "grinder"}]}})
    with pytest.raises(ValueError, match=r"teams\.a: `projects:` is gone — write `repo: shiftlead` \(design"):
        org.load(write(tmp_path, doc))
    doc["teams"]["a"] = {"projects": ["guardians"], "manager": {"home": "guardians"},
                         "members": [{"role": "grinder", "home": "guardians"}]}  # fmt: skip
    with pytest.raises(ValueError, match=r"`projects:` and `home:` are gone — write `repo: guardians`"):
        org.load(write(tmp_path, doc))
    doc["teams"] = {"b": {"projects": ["guardians"], "members": [{"role": "grinder"}]}}  # two repos, no home
    with pytest.raises(ValueError) as e:
        org.load(write(tmp_path, doc))
    assert str(e.value).endswith(
        "teams.b: b spans guardians and guardians-api: a team works one repo — split it into a team per repo "
        "under the guardians heading (design §4.9 *Teams*)"
    )
    # `repo:` beside a `home:` naming another repo spans too
    doc["teams"] = {"c": {"repo": "shiftlead", "manager": {"home": "guardians"}}}
    with pytest.raises(ValueError, match=r"c spans shiftlead and guardians"):
        org.load(write(tmp_path, doc))
    # a `home:` on a repo's team: the repo is the file's own, so the fix is to delete it
    with pytest.raises(
        ValueError, match=r"teams\.solo-grind: `home:` is gone — a repo's team works its own repo, solo"
    ):
        org.merge_repo_teams(org.Org(), tmp_path / "solo", {"solo-grind": {"members": [{"role": "g", "home": "x"}]}})


def test_a_team_member_is_refused_by_name_with_its_fix(tmp_path):
    """§4.9 *Teams* (TD-722, TD-775): no team holds another, so `{team: <name>}` fails to load, naming
    the key and saying the fix — a team of its own, started on its own — whether or not the name is
    a defined team."""
    doc = {
        "projects": {"p": {"repos": {"r": {"h": "/r"}}}},
        "teams": {"a": {"repo": "r", "members": [{"role": "g"}]}, "b": {"repo": "r", "members": [{"team": "a"}]}},
    }
    with pytest.raises(ValueError) as e:
        org.load(write(tmp_path, doc))
    assert str(e.value).endswith(
        "teams.b.members[0].team: no team holds another — teams that work together are teams on one repo, or on "
        "repos under one heading, and settle things by mail: delete the entry and start that team on its own "
        "(design §4.9 *Teams*)"
    )
    assert "team" not in {f.name for f in __import__("dataclasses").fields(org.MemberDef)}


def test_merge_repo_teams(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))  # no hosts.yml: the short hostname
    repo = tmp_path / "myrepo"
    repo.mkdir()
    base = org.load(write(tmp_path, ORG))
    repo_teams = {
        "grind": {"manager": {"name": "orc"}, "members": [{"role": "grinder", "count": 2, "name": "tdgrind"}]},
        "ao-grind": {"members": [{"role": "impostor"}]},  # collides with the org file: the org wins
    }
    merged = org.merge_repo_teams(base, repo, repo_teams)
    assert "grind" not in base.teams and "myrepo" not in base.checkouts  # the input is untouched
    from sessionorc.hosts import local_host

    # no project is made for it: a repo in no project is a heading of its own (§4.9 *Projects*, TD-722)
    assert "myrepo" not in merged.projects and merged.project_of("myrepo") == "myrepo"
    assert merged.checkout("myrepo", local_host().name) == repo.resolve()
    g = merged.teams["grind"]
    assert g.repo == "myrepo" and g.source == repo / ".shiftlead.yml"
    assert g.manager == org.ManagerDef(role="manager", name="orc")
    assert g.members[0].names() == ["tdgrind-1", "tdgrind-2"]
    assert merged.teams["ao-grind"] is base.teams["ao-grind"]  # org wins, source still org.yml
    assert merged.teams["ao-grind"].source == tmp_path / "org.yml"
    assert merged.roles == base.roles
    # nothing to merge leaves the org as it was, and the repo's checkout is not stored for nothing
    assert org.merge_repo_teams(base, repo, None).checkouts == base.checkouts
    # the repo's team the org file wins over is recorded, for `ao team list`'s *shadowed* (TD-229)
    assert merged.shadowed == {"ao-grind": [repo / ".shiftlead.yml"]} and base.shadowed == {}
    # no team holds another (§4.9 *Teams*), in a repo's file as in the org's, and the error names the file
    with pytest.raises(ValueError, match=r"\.shiftlead\.yml: teams\.bad\.members\[0\]\.team: no team holds another"):
        org.merge_repo_teams(base, repo, {"bad": {"members": [{"team": "ao-grind"}]}})
    # its `repo:` is unsaid, and written it is refused by name, as `projects:` is (§4.9 *The org is an aggregate*)
    for key, value in (("repo", "myrepo"), ("repo", "shiftlead"), ("projects", ["p"])):
        with pytest.raises(
            ValueError, match=rf"teams\.other\.{key}: a repo's team works its own repo, myrepo, unsaid — delete the key"
        ):
            org.merge_repo_teams(base, repo, {"other": {key: value}})
    # a heading of the org file listing the repo keeps its paths; this host's checkout is added beside them
    doc = dict(ORG, projects={**ORG["projects"], "mine": {"repos": {"myrepo": {"elsewhere": "/x"}}}})
    merged = org.merge_repo_teams(org.load(write(tmp_path, doc)), repo, repo_teams)
    assert merged.checkouts["myrepo"] == {"elsewhere": Path("/x"), local_host().name: repo.resolve()}
    assert merged.project_of("myrepo") == "mine"


def test_a_manager_may_name_its_own_brief_lane_grants_and_mode(tmp_path):
    """§4.9's lead had only role, name, home and profile, so a `brief:` on it was read by nobody —
    and a lead's brief is the one a repo most often keeps its own copy of. Found while
    writing the first real org.yml (2026-09-13)."""
    doc = {
        "projects": {"p": {"repos": {"r": {"kmaster": str(tmp_path)}}}},
        "teams": {
            "t": {
                "repo": "r",
                "manager": {"role": "manager", "brief": "docs/briefs/orc.md", "lane": "TD-1", "unattended": False},
            }
        },
    }
    (tmp_path / "org.yml").write_text(yaml.safe_dump(doc))
    lead = org.load(tmp_path / "org.yml").teams["t"].manager
    assert lead.brief == "docs/briefs/orc.md" and lead.lane == ["TD-1"] and lead.unattended is False
    assert lead.grants is None  # unsaid: the role's, as for a member


def test_a_key_nobody_reads_is_an_error_naming_it(tmp_path):
    """Silence about a stray key is how a lead's `brief:` disappeared into a file that looked
    right. A typo must stop the load, not be ignored (2026-09-13)."""
    base = {"projects": {"p": {"repos": {"r": {"kmaster": str(tmp_path)}}}}}
    for block, bad in (
        ({"repo": "r", "leed": {}}, "leed"),
        ({"repo": "r", "manager": {"role": "manager", "breif": "x"}}, "breif"),
        ({"repo": "r", "members": [{"role": "grinder", "profil": "grind"}]}, "profil"),
    ):
        (tmp_path / "org.yml").write_text(yaml.safe_dump({**base, "teams": {"t": block}}))
        with pytest.raises(ValueError, match=bad):
            org.load(tmp_path / "org.yml")


def test_grants_orchestrate_in_a_team_is_an_unknown_grant(tmp_path):
    """TD-107: `grants: [orchestrate]` on a team's manager or member is refused when the file loads."""
    f = tmp_path / "org.yml"
    f.write_text(
        "projects: {p: {repos: {r: {kmaster: /tmp}}}}\n"
        "teams:\n"
        "  t: {repo: r, members: [{role: grinder, grants: [orchestrate, control]}]}\n"
    )
    with pytest.raises(ValueError, match="unknown grant 'orchestrate'"):
        org.load(f)


def test_a_team_may_name_the_host_it_lands_on(tmp_path):
    """Design §4.4a "Teams across hosts", TD-057 step 4a: `host:` on a team definition; unsaid, the
    host the start runs on (`teams.plan` reads it); still a stray key anywhere else."""
    f = tmp_path / "org.yml"
    f.write_text(
        "projects: {p: {repos: {r: {contractmatch: /home/x/r}}}}\n"
        "teams:\n"
        "  t: {repo: r, host: contractmatch, manager: {role: manager}, members: [{role: grinder}]}\n"
        "  u: {repo: r, manager: {role: manager}}\n"
    )
    loaded = org.load(f)
    assert loaded.teams["t"].host == "contractmatch" and loaded.teams["u"].host == ""
    f.write_text("projects: {p: {repos: {r: {k: /x}}}}\nteams: {t: {repo: r, members: [{role: g, host: k}]}}\n")
    with pytest.raises(ValueError, match="host"):
        org.load(f)


def test_the_old_lead_key_is_a_stray_key(tmp_path):
    """TD-107: `lead:` was read as `manager:` for a release that never came; it is now refused as
    any unknown key on a team is."""
    f = tmp_path / "org.yml"
    f.write_text("projects: {p: {repos: {r: {kmaster: /tmp}}}}\nteams:\n  t: {repo: r, lead: {name: orc}}\n")
    with pytest.raises(ValueError, match=r"teams\.t: unknown key\(s\) \['lead'\]"):
        org.load(f)


def test_techlead_is_an_org_role_like_any_other(tmp_path):
    """TD-075 step 1: `techlead` is a preset now (design §4.9b), so `org.yml`'s `roles:` may carry
    it — the usual place to give the go-between a stronger profile."""
    f = tmp_path / "org.yml"
    f.write_text("roles:\n  techlead: {profile: x}\n")
    assert org.load(f).roles["techlead"] == {"profile": "x"}


def test_a_team_may_carry_one_techlead_seat(tmp_path):
    """TD-075 step 1, design §4.9b: `techlead: {name, profile, brief, context}` beside `manager:`; the
    name defaults to `<team>-techlead`, and it works the team's repo. The seat is the role
    and holds no grant, so `role:` and `grants:` are refused as unknown keys, and so is a bare
    string — `techlead: person` included: a person answering questions is the person."""
    f = tmp_path / "org.yml"
    base = "projects: {p: {repos: {r: {kmaster: /tmp/r}}}}\nteams:\n  t:\n    repo: r\n"
    f.write_text(base + "    techlead: {profile: strong}\n")
    seat = org.load(f).teams["t"].techlead
    assert (seat.name, seat.profile, seat.brief, seat.grants) == ("t-techlead", "strong", None, None)
    assert seat.context is None
    f.write_text(base + "    techlead: {context: docs/primer.md}\n")  # the primer (§4.9b *Its standing context*)
    assert org.load(f).teams["t"].techlead.context == "docs/primer.md"
    f.write_text(base)
    assert org.load(f).teams["t"].techlead is None
    for bad, why in (("{role: grinder}", r"unknown key\(s\) \['role'\]"), ("{grants: [control]}", "unknown key"),
                     ("person", "must be a mapping")):  # fmt: skip
        f.write_text(base + f"    techlead: {bad}\n")
        with pytest.raises(ValueError, match=why):
            org.load(f)


def test_a_team_may_carry_seats_with_a_trigger(tmp_path):
    """TD-098 step 1, design §4.9b *Seats with a trigger*: `seats:` — each `{name, role, trigger,
    brief, profile}` — with `trigger` one of `asks`, `{prs: n}` or `{every: <duration>}`, and
    required. The name defaults to `<team>-<role>`, and it works the team's repo; a seat
    holds no grants and has no lane, so neither key is read, and it is never the person, the
    manager or the techlead, which have keys of their own."""
    f = tmp_path / "org.yml"
    base = "projects: {p: {repos: {r: {kmaster: /tmp/r}}}}\nteams:\n  t:\n    repo: r\n"
    f.write_text(
        base + "    seats:\n"
        "      - {name: docs-audit, role: auditor, brief: docs/briefs/docs-audit.md, trigger: {prs: 10}}\n"
        "      - {role: auditor, trigger: {every: 6h}, profile: strong}\n"
        "      - {name: asker, role: hunter, trigger: asks}\n"
    )
    seats = org.load(f).teams["t"].seats
    assert [(s.name, s.role, s.trigger, s.after) for s in seats] == [
        ("docs-audit", "auditor", "prs", "10"),
        ("t-auditor", "auditor", "every", "6h"),
        ("asker", "hunter", "asks", ""),
    ]
    assert seats[0].brief == "docs/briefs/docs-audit.md" and seats[1].profile == "strong"
    assert all(s.grants == [] and s.lane == [] for s in seats)
    assert [s.when() for s in seats] == ["runs after 10 PRs", "runs every 6h", "comes on the next question"]
    f.write_text(base)
    assert org.load(f).teams["t"].seats == []
    for bad, why in (
        ("[{role: auditor}]", "trigger is required"),
        ("[{trigger: asks}]", "role is required"),
        ("[{role: auditor, trigger: {prs: 0}}]", "whole number"),
        ("[{role: auditor, trigger: {prs: true}}]", "whole number"),
        ("[{role: auditor, trigger: {every: 6}}]", "duration"),
        ("[{role: auditor, trigger: {every: 6w}}]", "duration"),
        ("[{role: auditor, trigger: {daily: 1}}]", "expected"),
        ("[{role: auditor, trigger: sometimes}]", "expected"),
        ("[{role: auditor, trigger: asks, grants: [control]}]", "unknown key"),
        ("[{role: auditor, trigger: asks, lane: [TD-1]}]", "unknown key"),
        ("[{role: techlead, trigger: asks}]", "not a seat's role"),
        ("[{role: person, trigger: asks}]", "not a seat's role"),
        ("{role: auditor}", "must be a list"),
    ):
        f.write_text(base + f"    seats: {bad}\n")
        with pytest.raises(ValueError, match=why):
            org.load(f)


def test_the_org_roles_overlay_is_checked_key_by_key_as_a_repos_is(tmp_path):
    """TD-149 (4): an org `roles:` preset used to be taken as it stood — a typo was a key nothing
    reads. It is checked by `repoconfig._role_block` now, so it fails when read, naming the key."""
    good = org.load(write(tmp_path, {"roles": {"grinder": {"profile": "grind", "review": {"reader": "techlead"}}}}))
    assert good.roles["grinder"]["profile"] == "grind" and good.roles["grinder"]["review"]["reader"] == "techlead"
    for bad, names in (
        ({"grinder": {"profil": "grind"}}, "roles.grinder.profil is not a role key"),
        ({"grinder": {"icon": "rocket"}}, "unknown icon 'rocket'"),
        ({"grinder": "grind"}, "roles.grinder must be a mapping"),
    ):
        with pytest.raises(ValueError, match=names):
            org.load(write(tmp_path, {"roles": bad}))


# -- Members… (design §4.9 *Add or remove a member from the team card*, TD-163, built by TD-172) ---

MEMBERS_YML = """\
# the org, by hand
projects:
  shiftlead: {repos: {shiftlead: {kmaster: ~/agentorc}}}

teams:
  # the grind team
  ao-grind:
    repo: shiftlead   # one repo
    manager: {role: manager, name: manager-ao-1}
    members:
      # two grinders, numbered
      - {role: grinder, count: 2, name: grinder-ao, lane: [free-pick]}   # the lane
      - {role: hunter, name: hunter-ao, lane: [ui]}
    # after the members
  other:
    repo: shiftlead
    manager: {role: manager}
    members:
      - role: grinder
        name: long-one
roles: {}
"""


def _members(tmp_path: Path) -> Path:
    p = tmp_path / "org.yml"
    p.write_text(MEMBERS_YML)
    return p


def test_add_appends_a_line_beside_a_counted_one_and_never_bumps_its_count(tmp_path):
    """§4.9 *Add member and Remove keep the definition's share* (TD-1165): Add member writes a new member
    line, a second line of a role that has a counted one included; the `count:` is the size's (**+**)."""
    p = _members(tmp_path)
    did = org.edit_members(p, "ao-grind", add={"role": "grinder", "name": "grinder-ao-3"})
    after = p.read_text()
    assert did == "added grinder-ao-3 (grinder)"
    assert "count: 2, name: grinder-ao, lane: [free-pick]}   # the lane" in after
    assert after == MEMBERS_YML.replace(
        "      - {role: hunter, name: hunter-ao, lane: [ui]}\n",
        "      - {role: hunter, name: hunter-ao, lane: [ui]}\n      - {role: grinder, name: grinder-ao-3}\n",
    )
    assert [m.names() for m in org.load(p).teams["ao-grind"].members] == [
        ["grinder-ao-1", "grinder-ao-2"], ["hunter-ao"], ["grinder-ao-3"],
    ]  # fmt: skip


def test_add_of_another_role_appends_one_line_after_the_last_item(tmp_path):
    p = _members(tmp_path)
    org.edit_members(p, "ao-grind", add={"role": "auditor", "name": "audit-ao", "lane": ["docs"]})
    after = p.read_text()
    want = MEMBERS_YML.replace(
        "      - {role: hunter, name: hunter-ao, lane: [ui]}\n",
        "      - {role: hunter, name: hunter-ao, lane: [ui]}\n      - {role: auditor, name: audit-ao, lane: [docs]}\n",
    )
    assert after == want  # comments above, beside and after the block stand
    assert [m.role for m in org.load(p).teams["ao-grind"].members] == ["grinder", "hunter", "auditor"]


def test_remove_deletes_a_line_whole_whatever_its_count(tmp_path):
    """§4.9 *Add member and Remove keep the definition's share* (TD-1165): Remove takes the whole line out,
    a counted one included — a count is lowered by the size's −, never by Remove."""
    p = _members(tmp_path)
    assert org.edit_members(p, "ao-grind", remove=0, role="grinder") == "removed grinder-ao"
    after = p.read_text()
    assert "grinder-ao" not in after and "hunter-ao" in after and "# two grinders" in after
    assert len(after.splitlines()) == len(MEMBERS_YML.splitlines()) - 1
    assert org.edit_members(p, "ao-grind", remove=0, role="hunter") == "removed hunter-ao"
    after = p.read_text()
    assert "hunter-ao" not in after and "# the lane" not in after and "# after the members" in after


def test_an_edit_that_cannot_be_one_line_is_refused_and_the_file_untouched(tmp_path):
    p = _members(tmp_path)
    for kw, why in (
        ({"remove": 0, "role": "grinder"}, "spans several lines"),
        ({"remove": 5}, "no member entry 6"),
        ({"remove": 0, "role": "hunter"}, "not a hunter any more"),
    ):
        team = "other" if why == "spans several lines" else "ao-grind"
        with pytest.raises(ValueError, match=why):
            org.edit_members(p, team, **kw)
    with pytest.raises(ValueError, match="does not define a team nope"):
        org.edit_members(p, "nope", add={"role": "grinder"})
    assert p.read_text() == MEMBERS_YML


def test_an_edit_that_would_not_parse_restores_the_bytes(tmp_path, monkeypatch):
    p = _members(tmp_path)

    def broken(path=None):
        raise ValueError("org.yml: teams.ao-grind.members[2]: nonsense")

    monkeypatch.setattr(org, "load", broken)
    with pytest.raises(ValueError, match="would not parse, so org.yml is as it was"):
        org.edit_members(p, "ao-grind", add={"role": "auditor", "name": "x"})
    assert p.read_text() == MEMBERS_YML


def test_add_member_defaults_to_the_next_free_name_never_an_existing_one(tmp_path):
    """TD-268: the form offered the existing grinder's name, and Add wrote it again. The default is
    the team's pattern with the first number no name of the team holds."""
    p = _members(tmp_path)
    t = org.load(p).teams["ao-grind"]
    assert t.next_name("grinder") == "grinder-ao-3"  # a counted entry: the name its bump makes
    assert t.next_name("hunter") == "hunter-ao-2"  # an unnumbered name: its pattern from 2
    assert t.next_name("auditor") == "auditor"  # a role the team has no entry of: the role, while free
    p.write_text(MEMBERS_YML.replace("count: 2, name: grinder-ao,", "name: grinder-ao-1,"))
    t = org.load(p).teams["ao-grind"]
    assert t.next_name("grinder") == "grinder-ao-2" and t.twice_named() == []
    assert "manager-ao-1" in t.session_names()


def test_add_member_refuses_a_name_the_team_holds_and_leaves_the_file_byte_identical(tmp_path):
    """TD-268: a duplicate is refused before anything is written, in the page's words."""
    p = _members(tmp_path)
    p.write_text(MEMBERS_YML.replace("count: 2, name: grinder-ao,", "name: grinder-dc-1,"))
    before = p.read_bytes()
    for name in ("grinder-dc-1", "hunter-ao", "manager-ao-1"):
        with pytest.raises(ValueError, match=f"ao-grind already has {name}$"):
            org.edit_members(p, "ao-grind", add={"role": "grinder", "name": name})
        assert p.read_bytes() == before
    assert (
        org.edit_members(p, "ao-grind", add={"role": "auditor", "name": "grinder-ao-4"})
        == "added grinder-ao-4 (auditor)"
    )


def test_add_member_refuses_a_name_a_sized_line_holds(tmp_path, monkeypatch):
    """§4.9 *A team's size* (TD-1165): the duplicate check reads the sized names — a `count: 1` line at
    `size: 3` holds `<name>-2` and `<name>-3`, so Add member refuses them and the file is untouched."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "settings.yml").write_text("teams: {ao-grind: {size: {hunter-ao: 3}}}\n")
    p = _members(tmp_path)
    before = p.read_bytes()
    with pytest.raises(ValueError, match="ao-grind already has hunter-ao-2$"):
        org.edit_members(p, "ao-grind", add={"role": "hunter", "name": "hunter-ao-2"})
    assert p.read_bytes() == before
    assert (
        org.edit_members(p, "ao-grind", add={"role": "hunter", "name": "hunter-ao-4"}) == "added hunter-ao-4 (hunter)"
    )


def test_a_definition_holding_a_name_twice_says_it(tmp_path):
    p = _members(tmp_path)
    p.write_text(MEMBERS_YML.replace("count: 2, name: grinder-ao,", "name: hunter-ao,"))
    assert org.load(p).teams["ao-grind"].twice_named() == ["hunter-ao"]


def test_entries_names_the_role_a_persons_entry_session_takes_per_type(tmp_path, monkeypatch):
    """TD-219 slice 2, design §4.9 *Add an entry to the ledger*: `entries: {feature: <role>, debt:
    <role>}` on a team, either key optional and read as `techlead` where unsaid; an unknown key, or a
    role nothing resolves, is an error naming it when the definition is read. A role resolves from the
    presets, the org's `roles:`, the team's own members and seats, or the repo's roles for its own teams."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    f = tmp_path / "org.yml"
    base = (
        "projects: {p: {repos: {r: {kmaster: /tmp/r}}}}\nroles: {designer: {profile: x}}\nteams:\n  t:\n    repo: r\n"
    )
    f.write_text(base)
    t = org.load(f).teams["t"]
    assert t.entries == {} and (t.entry_role("debt"), t.entry_role("feature")) == ("techlead", "techlead")
    f.write_text(base + "    entries: {feature: designer}\n")
    t = org.load(f).teams["t"]
    assert (t.entry_role("feature"), t.entry_role("debt")) == ("designer", "techlead")
    f.write_text(base + "    members: [{role: sage}]\n    entries: {debt: sage}\n")  # the team's own role
    assert org.load(f).teams["t"].entry_role("debt") == "sage"
    for bad, why in (
        ("{bug: grinder}", r"unknown key\(s\) \['bug'\]"),
        ("{feature: wizard}", "unknown role 'wizard'"),
        ("{debt: person}", "not a role"),
        ("{debt: ''}", "a role name"),
        ("[designer]", "must be a mapping"),
    ):
        f.write_text(base + f"    entries: {bad}\n")
        with pytest.raises(ValueError, match=why):
            org.load(f)
    # a repo's own team may name a role its own file defines
    repo = tmp_path / "myrepo"
    repo.mkdir()
    f.write_text(base)
    teams = {"g": {"entries": {"feature": "scribe"}}}
    with pytest.raises(ValueError, match="unknown role 'scribe'"):
        org.merge_repo_teams(org.load(f), repo, teams)
    assert org.merge_repo_teams(org.load(f), repo, teams, ["scribe"]).teams["g"].entry_role("feature") == "scribe"
    # …and a second repo's merge does not check the first's team against its own roles (review of #761)
    other = tmp_path / "other"
    other.mkdir()
    merged = org.merge_repo_teams(org.merge_repo_teams(org.load(f), repo, teams, ["scribe"]), other, {"h": {}})
    assert merged.teams["g"].entry_role("feature") == "scribe" and "h" in merged.teams
    # `ao team list --json` (the rows) carries both types, said
    from shiftlead import teamrun

    f.write_text(base + "    entries: {feature: designer}\n")
    (row,) = teamrun.rows(org.load(f), [])
    assert row["entries"] == {"debt": "techlead", "feature": "designer"}


def test_this_repos_own_file_defines_ao_grind_as_the_org_file_did(tmp_path, monkeypatch):
    """TD-229 slice 2: this repo's `.shiftlead.yml` carries ao-grind, so removing the team from the
    org file starts the same team from the repo; while the org file still defines it, the repo's
    reads *shadowed* and nothing that runs changes. TD-310 (design §4.9c): the team is on flows —
    `[td, build-review]` with the top-level `held:` — and writes nothing its flow fills: no member
    lane, no `entries.feature`, no role `review:`, so `ao org check` warns of nothing redundant."""
    from sessionorc import hosts
    from shiftlead import repoconfig, teams

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    here = Path(__file__).resolve().parents[1]
    repo = tmp_path / "shiftlead"  # the checkout's directory name is the team's repo
    repo.mkdir()
    (repo / ".shiftlead.yml").write_text((here / ".shiftlead.yml").read_text())
    overlay = {"roles": {"grinder": {"profile": "grind"}, "designer": {"profile": "grind-fable"}}}

    aggregate, notes = org.with_repos(org.load(write(tmp_path, overlay)), [repo])
    assert notes == []
    team = aggregate.teams["ao-grind"]
    assert team.source == repo.resolve() / ".shiftlead.yml" and team.repo == "shiftlead" and not team.host
    assert (team.manager.name, team.manager.brief) == ("manager-ao-1", "docs/briefs/manager-ao-1.md")
    assert (team.techlead.name, team.techlead.context) == ("techlead-ao-1", "docs/briefs/techlead-context.md")
    got = [(m.role, m.names(), m.lane, m.brief, m.unattended) for m in team.members]
    assert got == [
        ("grinder", ["grinder-ao-1"], [], "docs/briefs/grinder-ao-1.md", True),
        ("grinder", ["grinder-ao-2"], [], "docs/briefs/grinder-ao-2.md", True),
        ("designer", ["designer-ao-1"], [], None, True),
    ]
    assert team.flows == ["td", "build-review"] and team.entries == {}
    briefs = [team.manager.brief, team.techlead.context, *(m.brief for m in team.members if m.brief)]
    assert all((here / b).is_file() for b in briefs)

    # the held paths are the repo's top-level `held:`; no role writes a `review:` (the flow gives the
    # reader); the profile is still the org overlay's
    cfg = repoconfig.load(repo)
    assert cfg.held == ["src/sessionorc/**", "docs/briefs/**"]
    for name, profile in (("grinder", "grind"), ("designer", "grind-fable")):
        role = repoconfig.resolve_role(cfg, name, aggregate.roles)
        assert (role.review, role.profile) == (None, profile)
    assert (here / repoconfig.resolve_role(cfg, "designer", aggregate.roles).brief).is_file()

    # both listed flows are followable, and the current one (`td`, the first) compiles to what the
    # file no longer writes: the stage lanes, `entries.feature: designer`, the techlead on `held:`;
    # `ao org check` (teams.flow_redundant) names no key the flow would fill the same
    host = hosts.local_host().name
    teams._check_flows(aggregate, team, host, host, None)
    under = teams.compiled(aggregate, team, host, host, None)
    assert under is not None and under.flow.name == "td"
    assert under.flow.stage_of("grinder").lane == ["free-pick", "owner:grinder"]
    assert under.flow.stage_of("designer").lane == ["design-first", "owner:designer"]
    assert (under.reader["reader"], under.reader["bound"]) == ("techlead", "2h")
    assert set(under.reader["held"]) == {"src/sessionorc/**", "docs/briefs/**"}
    assert teams.entry_role(aggregate, team, "feature", host, host) == "designer"
    assert teams.flow_redundant(aggregate, team, host, host) == []

    # while the org file defines ao-grind it wins, and the repo's is recorded as shadowed
    shadowing, _ = org.with_repos(org.load(write(tmp_path, ORG)), [repo])
    assert shadowing.teams["ao-grind"].source == tmp_path / "org.yml"
    assert shadowing.shadowed == {"ao-grind": [repo.resolve() / ".shiftlead.yml"]}


# ── `place:` and where a repo's team lands (design §4.9 *Where a repo's team lands*, TD-229 slice 3) ──


def _repo(tmp_path: Path, name: str, team: str) -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    (repo / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": {team: {"members": [{"role": "grinder"}]}}}))
    return repo


def _here(monkeypatch, tmp_path: Path) -> str:
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))  # no hosts.yml: the short hostname
    from sessionorc.hosts import local_host

    return local_host().name


def test_place_is_read_and_is_for_a_repos_team_only(tmp_path):
    assert org.load(write(tmp_path, dict(ORG, place={"sam-grind": "devenv"}))).place == {"sam-grind": "devenv"}
    assert org.load(write(tmp_path, ORG)).place == {}
    with pytest.raises(ValueError, match=r"place\.ao-grind: 'ao-grind' is defined in this file"):
        org.load(write(tmp_path, dict(ORG, place={"ao-grind": "devenv"})))
    with pytest.raises(ValueError, match=r"place\.sam-grind: name the host"):
        org.load(write(tmp_path, dict(ORG, place={"sam-grind": ""})))
    with pytest.raises(ValueError, match="place must be a mapping"):
        org.load(write(tmp_path, dict(ORG, place=["sam-grind"])))


def test_the_landing_rule_is_place_then_here():
    """§4.9 *Where a repo's team lands* (TD-318): two clauses — a definition is read at the home, so
    a team `place:` does not name lands on this host, and no other host's registry is asked."""
    assert org.landing("t", {"t": "lab"}, "kmaster") == ("lab", "place")
    assert org.landing("t", {"u": "lab"}, "kmaster") == ("kmaster", "registered here")
    assert org.landing("t", {}, "kmaster") == ("kmaster", "registered here")


def test_a_repos_team_lands_here_unless_place_names_it(tmp_path, monkeypatch):
    here = _here(monkeypatch, tmp_path)
    repo = _repo(tmp_path, "sam", "sam-grind")
    asked: list[str] = []

    def repos_of(host: str) -> list[str]:
        asked.append(host)
        return ["/workspaces/other", "/workspaces/sam"]

    agg, notes = org.with_repos(org.load(write(tmp_path, ORG)), [repo], repos_of=repos_of)
    assert agg.landed == {"sam-grind": (here, "registered here")} and agg.teams["sam-grind"].host == ""
    assert asked == [] and notes == []  # no node is asked for a team that lands here
    # the org file's own teams are placed by their `host:`, and are not in `landed`
    assert "ao-grind" not in agg.landed

    base = org.load(write(tmp_path, dict(ORG, place={"sam-grind": "devenv"})))
    agg, notes = org.with_repos(base, [repo], repos_of=repos_of)
    assert agg.landed == {"sam-grind": ("devenv", "place")} and agg.teams["sam-grind"].host == "devenv"
    # the repo's path there is that host's registry entry of the checkout's name
    assert agg.checkout("sam", "devenv") == Path("/workspaces/sam")
    assert agg.checkout("sam", here) == repo.resolve()
    assert asked == ["devenv"] and notes == [] and agg.unlanded == {}
    assert "sam" not in base.checkouts and base.landed == {}  # the input is untouched

    # placed on this host: it lands here and nothing is asked
    agg, _ = org.with_repos(org.load(write(tmp_path, dict(ORG, place={"sam-grind": here}))), [repo])
    assert agg.landed == {"sam-grind": (here, "place")} and agg.teams["sam-grind"].host == ""


def test_a_placed_team_whose_checkout_there_cannot_be_told_is_listed_and_not_started(tmp_path, monkeypatch):
    from shiftlead import teams

    here = _here(monkeypatch, tmp_path)
    repo = _repo(tmp_path, "sam", "sam-grind")
    base = org.load(write(tmp_path, dict(ORG, place={"sam-grind": "devenv"})))

    def down(host: str) -> list[str]:
        raise OSError("devenv did not answer: the link dropped")

    for repos_of, why in (
        (down, r"registry could not be read \(devenv did not answer"),
        (None, "registry could not be read"),
        (lambda h: ["/workspaces/other"], r"holds no checkout named sam — register the one checkout of sam on devenv"),
        (lambda h: ["/a/sam", "/b/sam"], r"holds sam 2 times \(/a/sam, /b/sam\)"),
    ):
        agg, notes = org.with_repos(base, [repo], repos_of=repos_of)
        assert "sam-grind" in agg.teams and agg.teams["sam-grind"].host == "devenv"  # still listed, on its host
        assert list(agg.unlanded) == ["sam-grind"] and notes == [agg.unlanded["sam-grind"]]
        with pytest.raises(teams.TeamError, match=why):
            teams.plan(agg, "sam-grind", host=here)

    # a path the org file's heading gives on that host is used as it stands, and no registry is asked
    doc = dict(ORG, place={"sam-grind": "devenv"})
    doc["projects"] = {**ORG["projects"], "cm": {"repos": {"sam": {here: str(repo), "devenv": "/w/sam"}}}}
    agg, notes = org.with_repos(org.load(write(tmp_path, doc)), [repo], repos_of=down)
    assert agg.unlanded == {} and notes == [] and agg.checkout("sam", "devenv") == Path("/w/sam")
    # …and where the heading names no path there and the registry holds none, the fix is a path under it
    doc["projects"] = {**ORG["projects"], "cm": {"repos": {"sam": {here: str(repo)}}}}
    agg, notes = org.with_repos(org.load(write(tmp_path, doc)), [repo], repos_of=lambda h: [])
    assert agg.unlanded["sam-grind"].endswith("— add `devenv: <path>` under `projects.cm.repos.sam` in org.yml")
    assert len(notes) == 1
    # a `place:` naming a team no repo defines is a note, never silence
    agg, notes = org.with_repos(org.load(write(tmp_path, dict(ORG, place={"sam-grnd": "devenv"}))), [repo])
    assert notes == ["place.sam-grnd: no registered repo defines a team 'sam-grnd' — nothing is placed on devenv"]


def test_a_placed_team_starts_on_its_host_from_that_hosts_checkout(tmp_path, monkeypatch):
    from shiftlead import teams

    here = _here(monkeypatch, tmp_path)
    repo = _repo(tmp_path, "sam", "sam-grind")
    base = org.load(write(tmp_path, dict(ORG, place={"sam-grind": "devenv"}, roles={})))
    # a container node shares the path, so the node's registry names the directory this host reads
    agg, _ = org.with_repos(base, [repo], repos_of=lambda h: [str(repo)])
    p = teams.plan(agg, "sam-grind", host=here)
    assert p.host == "devenv" and [x.host for x in p.launches] == ["devenv"] * len(p.launches)
    assert {str(x.dir) for x in p.launches} == {str(repo)}
    assert p.manager_id.endswith("@devenv")


def test_two_teams_on_one_repo_badge_alike_and_a_repo_in_no_project_badges_with_its_name(tmp_path, monkeypatch):
    """§4.9 *Home and reach* (TD-722): a team session's `project` is its repo's project, the repo's own
    name where no project lists it, so two teams on one repo always share one — the mail gate's
    *across teams* edge (§4.10) reads it unchanged."""
    from shiftlead import teams

    here = _here(monkeypatch, tmp_path)
    for r in ("db", "solo"):
        (tmp_path / r).mkdir()
    doc = {
        "projects": {"shop": {"title": "Shop", "repos": {"db": {here: str(tmp_path / "db")}}}},
        "teams": {
            "db-grind": {"repo": "db", "manager": {"role": "person"}, "members": [{"role": "grinder"}]},
            "db-hunt": {"repo": "db", "manager": {"role": "person"}, "members": [{"role": "hunter"}]},
            "solo-grind": {"repo": "solo", "manager": {"role": "person"}, "members": [{"role": "grinder"}]},
        },
    }
    agg, notes = org.with_repos(org.load(write(tmp_path, doc)), [tmp_path / "solo"])
    assert notes == [] and agg.checkout("solo", here) == (tmp_path / "solo").resolve()  # a registered checkout
    badge = {t: {x.project for x in teams.plan(agg, t, here).launches} for t in agg.teams}
    assert badge == {"db-grind": {"shop"}, "db-hunt": {"shop"}, "solo-grind": {"solo"}}


def test_a_manager_is_on_call_when_its_definition_says_so(tmp_path):
    """TD-259 slice 1, design §4.9 `on_call`: `true` makes the manager a seat, `false` a standing
    session; unsaid is `ON_CALL_DEFAULT`; anything but a flag, the key beside `role: person` (which
    starts nothing to fill) and the key on a member are each an error naming it."""
    base = {"projects": {"p": {"repos": {"r": {"kmaster": str(tmp_path)}}}}}
    f = tmp_path / "org.yml"

    def team(block):
        f.write_text(yaml.safe_dump({**base, "teams": {"t": {"repo": "r", **block}}}))
        return org.load(f).teams["t"]

    assert team({"manager": {"on_call": True}}).manager.on_call is True
    assert team({"manager": {"on_call": False}}).manager.on_call is False
    assert org.ON_CALL_DEFAULT is True  # Paul, 2026-10-01: on call from the build; the flip is TD-259's
    assert team({"manager": {}}).manager.on_call is True and team({}).manager.on_call is True
    assert team({"manager": {"role": "person"}}).manager.on_call is False  # nothing is started, whatever the default
    # the default is the `manager` role's, whose template has a seat's shape; another role says so itself
    assert team({"manager": {"role": "grinder"}}).manager.on_call is False
    assert team({"manager": {"role": "grinder", "on_call": True}}).manager.on_call is True
    assert "on_call" in org.MANAGER_KEYS and "on_call" not in org.MEMBER_KEYS
    for block, why in (
        ({"manager": {"on_call": "yes"}}, r"t\.manager\.on_call must be true or false"),
        ({"manager": {"on_call": 1}}, r"t\.manager\.on_call must be true or false"),
        ({"manager": {"role": "person", "on_call": True}}, r"t\.manager\.on_call: a person manages"),
        ({"manager": {"role": "person", "on_call": False}}, r"t\.manager\.on_call: a person manages"),
        ({"members": [{"role": "grinder", "on_call": True}]}, r"unknown key\(s\) \['on_call'\]"),
    ):
        with pytest.raises(ValueError, match=why):
            team(block)


@pytest.mark.parametrize("name", ["interactive", "outside"])
def test_a_team_named_as_a_seat_ledger_reading_is_refused(tmp_path, name):
    """§4.9 *Names are the org's* (TD-818, built by TD-859): the seat ledger reads the person's own
    sessions as `interactive` and unowned turns as `outside`, so a team of either name fails to load —
    in the org file (`ao org check`, a start) and in a repo's definitions."""
    doc = {"projects": {"p": {"repos": {"r": {"h": "/r"}}}}, "teams": {name: {"repo": "r", "members": [{"role": "g"}]}}}
    with pytest.raises(ValueError, match=rf"teams\.{name}: `{name}` is reserved .* rename the team"):
        org.load(write(tmp_path, doc))
    with pytest.raises(ValueError, match=rf"`{name}` is reserved"):
        org.merge_repo_teams(org.Org(), tmp_path / "solo", {name: {"members": [{"role": "g"}]}})
