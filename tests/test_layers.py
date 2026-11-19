"""The person's own additions from their agent-cadence layer (design §4.8 *The person's own additions*, TD-1016):
the listing, the reads (one's own from its working tree, a followed layer at its pin), the `{person}` slot under
*Your own rules*, and rule 7's comparison of a layer file."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import brief as brief_mod
from sessionorc import cadence
from shiftlead import layers, repoconfig


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def _layer_repo(root: Path, files: dict[str, str]) -> str:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for rel, text in files.items():
        p = root / "shiftlead" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "layer")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def two_layers(tmp_path):
    """A followed layer pinned at its first commit (its working tree moved on since), then one's own."""
    followed = tmp_path / "theirs"
    pin = _layer_repo(
        followed,
        {"briefs/grinder.md": "theirs: test twice\n", "entry.md": "theirs entry\n", "preferences.md": "- theirs\n"},
    )
    (followed / "shiftlead" / "briefs" / "grinder.md").write_text("theirs: an edit nobody pinned\n")
    own = tmp_path / "mine"
    _layer_repo(own, {"briefs/grinder.md": "mine: never on Fridays\n", "preferences.md": "- mine\n"})
    return [
        layers.Layer(root=followed, kind="followed", ref=pin, commit=pin[:7]),
        layers.Layer(root=own, kind="own", ref=None, commit="abc1234"),
    ]


def _machine(tmp_path, monkeypatch, text: str | None) -> None:
    reg = tmp_path / "reg"
    reg.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_CADENCE_REG_DIR", str(reg))
    if text is not None:
        (reg / "cadence.toml").write_text(text)
    layers._listed.clear()


def test_the_raised_oldest_is_dev_cadences_layer_listing():
    """`OLDEST` is dev-cadence TD-132's merge (#326), the commit that ships `cadence_layer.py --json`."""
    assert cadence.OLDEST == "611d911b1d88cc492ef849aa226d90f47a60a7bd"


def test_no_layer_named_lists_nothing_and_runs_nothing(tmp_path, monkeypatch):
    _machine(tmp_path, monkeypatch, None)

    def run(*a, **k):
        raise AssertionError("the listing ran with no layer named")

    assert layers.listing(tmp_path, tmp_path, run=run) == []
    _machine(tmp_path, monkeypatch, 'publish-names = ["x"]\n')
    assert layers.listing(tmp_path, tmp_path, run=run) == []


def test_the_listing_is_agent_cadences_json_in_its_order(tmp_path, monkeypatch):
    _machine(tmp_path, monkeypatch, '[[layers]]\npath = "~/x.md"\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "cadence.toml").write_text('[agent-cadence]\nsource = "x"\nref = "abc"\n')
    asked = []
    rows = [
        {"root": "/l/theirs", "kind": "followed", "ref": "f00", "commit": "f00"},
        {"root": "/l/broken", "kind": "own", "ref": None, "commit": None, "error": "not a repo"},
        {"root": "/l/mine", "kind": "own", "ref": None, "commit": "abc"},
    ]

    def run(argv, **k):
        asked.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"layers": rows}), "")

    got = layers.listing(tmp_path, None, run=run)
    assert [(str(x.root), x.kind, x.ref) for x in got] == [("/l/theirs", "followed", "f00"), ("/l/mine", "own", None)]
    assert asked[0][-3:] == ["run", "cadence_layer.py", "--json"] and str(tmp_path) in asked[0]
    assert layers.listing(tmp_path, None, run=run) == got and len(asked) == 1, "one listing answers a team start"


def test_a_failed_listing_is_an_error_never_no_layer(tmp_path, monkeypatch):
    _machine(tmp_path, monkeypatch, '[[layers]]\npath = "~/x.md"\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "cadence.toml").write_text('[agent-cadence]\nsource = "x"\nref = "abc"\n')

    def run(argv, **k):
        return subprocess.CompletedProcess(argv, 2, "", "cadence_layer: the layer file is not TOML\n")

    with pytest.raises(layers.ListingError, match="exited 2: cadence_layer: the layer file is not TOML"):
        layers.listing(tmp_path, None, run=run)


def test_no_agent_cadence_to_list_under_is_named_and_reads_no_layer(tmp_path, monkeypatch):
    _machine(tmp_path, monkeypatch, '[[layers]]\npath = "~/x.md"\n')
    with pytest.raises(layers.NoSource, match=layers.NO_SOURCE):
        layers.listing(tmp_path, None)
    assert layers.person("grinder", tmp_path, [tmp_path]) == []


def test_a_grinder_brief_holds_both_layers_under_your_own_rules(two_layers, tmp_path):
    parts = layers.brief_parts("grinder", two_layers)
    assert [p["ref"] for p in parts] == [two_layers[0].ref, None]
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "rules.md").write_text("the repo's own rule\n")
    cfg = repoconfig.load(tmp_path / "repo")
    role = repoconfig.resolve_role(cfg, "grinder")
    text, prompt_from = role.compose(["TD-001"], supplement="rules.md", person=parts)
    # the followed layer at its pin, never its working tree; then one's own; both before the repo's
    assert "theirs: test twice" in text and "an edit nobody pinned" not in text
    order = [
        text.index("## Your own rules"),
        text.index("theirs: test twice"),
        text.index("mine: never on Fridays"),
        text.index("## This repo's rules"),
        text.index("the repo's own rule"),
    ]
    assert order == sorted(order)
    assert f"— from your layer {two_layers[0].root} @ {two_layers[0].ref[:7]} —" in text
    # a replay makes the same text and names both layer files among its sources
    again, sources = brief_mod.fill(prompt_from, merged=False)  # the template as on disk, not as merged
    assert again == text
    named = {s["path"]: s for s in sources}
    assert named[parts[0]["path"]]["ref"] == two_layers[0].ref and named[parts[1]["path"]]["layer"] == "own"


def test_no_layer_reads_the_packages_alone(tmp_path):
    cfg = repoconfig.load(tmp_path)
    text, prompt_from = repoconfig.resolve_role(cfg, "grinder").compose(["TD-001"], person=[])
    assert "## Your own rules" in text and "{person}" not in text
    assert prompt_from["slots"]["{person}"] == {"text": "none"}
    assert brief_mod.fill(prompt_from, merged=False)[0] == text


def test_an_edit_to_ones_own_layer_marks_the_brief_changed(two_layers, tmp_path):
    cfg = repoconfig.load(tmp_path)
    _text, prompt_from = repoconfig.resolve_role(cfg, "grinder").compose(
        ["TD-001"], person=layers.brief_parts("grinder", two_layers)
    )
    rec = brief_mod.record(prompt_from)
    assert brief_mod.changed(rec)[0] == []
    # the followed layer's working tree moved before the start: read at its pin, so no change
    mine = two_layers[1].root / "shiftlead" / "briefs" / "grinder.md"
    mine.write_text("mine: never on Fridays, nor on Mondays\n")  # unsaved to git: one's own is its working tree
    assert brief_mod.changed(rec)[0] == [str(mine)]


def test_a_layer_without_the_roles_file_adds_nothing(two_layers):
    assert layers.brief_parts("hunter", two_layers) == []
    assert layers.read(two_layers[0], "entry.md")[0] == "theirs entry\n"
    assert layers.read(two_layers[1], "entry.md") is None


def test_a_team_start_lists_under_the_homes_checkout_and_stops_on_a_failed_listing(tmp_path, monkeypatch):
    """`teams._person`: the home's checkout of the team's repo, else the agent-cadence source among the org's
    checkouts here; a failed listing is the start's error, by name."""
    from shiftlead import org as orgmod
    from shiftlead import teams

    repo, source = tmp_path / "repo", tmp_path / "agent-cadence"
    repo.mkdir()
    (source / "files").mkdir(parents=True)
    (source / "sync.sh").write_text("")
    org = orgmod.Org(checkouts={"app": {"here": repo}, "agent-cadence": {"here": source}})
    asked = []

    def listing(where, src):
        asked.append((where, src))
        raise layers.ListingError("agent-cadence's layer listing exited 2")

    monkeypatch.setattr(layers, "listing", listing)
    with pytest.raises(teams.TeamError, match="team t: g: agent-cadence's layer listing exited 2"):
        teams._person(org, "app", "grinder", "here", "team t: g")
    assert asked == [(repo, source)]
