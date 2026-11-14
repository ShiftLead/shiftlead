"""The lane words #2664 (TD-1223) put in the New-session form, `ao new --lane`'s help and the shipped grinder
brief (design §4.7, §4.8; TD-1234): a lane is `free-pick` or `design-first`, narrowed by `owner:<word>`, its
words shared by its members — never the old list of references a member was handed."""

from __future__ import annotations

import pathlib

import pytest

import shiftlead
from shiftlead import cli

PKG = pathlib.Path(shiftlead.__file__).parent
PLACEHOLDER = "free-pick or design-first · owner:<word>"


def test_the_new_session_forms_lane_field_names_the_lane_words(tmp_path, monkeypatch):
    """The Lane field's placeholder and note, as the template draws them and as app.js puts back when the
    Role pick names no lane of its own."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    from shiftlead.ui.app import templates

    html = templates.get_template("new.html").render(
        host="kmaster", active="Sessions", profiles={}, default_profile="default", recent=[],
        adapters=["claude-code"], control_holders=[], grants_all=[], grant_notes={},
        roles=[{"name": "plain", "source": "built-in", "lane": [], "controllers": [], "grants": []}],
        default_controllers=[], projects=[],
        prefill={"dir": "", "adapter": "claude-code", "resume": "", "project": "", "name": "", "profile": "",
                 "role": "", "team": "", "lane": "", "controllers": [], "unattended": False, "prefilled": False,
                 "why": ""},
    )  # fmt: skip
    assert 'placeholder="free-pick or design-first · owner:&lt;word&gt;"' in html
    assert "the lane's words, shared by its members; empty: the role's default" in html
    assert "TD-027, TD-019" not in html
    js = (PKG / "ui" / "static" / "app.js").read_text()
    assert f'$("[name=lane]").placeholder = o.dataset.lane || "{PLACEHOLDER}";' in js


def test_ao_new_lane_help_names_the_lane_words(capsys):
    """`ao new --help`: `--lane` takes the lane words; a list of references is kept but matched by no lane."""
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["new", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "lane words: `free-pick` or `design-first`, narrowed by `owner:<word>`" in out
    assert "a list of references (`TD-027,TD-019`) is kept as written but matched by no lane" in out
    assert "the references this session was handed" not in out


def test_the_shipped_grinder_brief_has_no_named_list_out_of_work_rule():
    """The grinder brief's *Out of work* is the `free-pick` lane's alone: no rule for a named list's lane
    running out when every item is done or dropped."""
    brief = (PKG / "briefs" / "grinder.md").read_text()
    para = next(p for p in brief.split("\n\n") if p.startswith("**Out of work**"))
    assert para.startswith("**Out of work** (design §4.9a): a `free-pick` lane is out of work only when")
    assert "named lane is out of work" not in brief
