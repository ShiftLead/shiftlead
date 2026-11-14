"""The Grok launch home and the `all` refusal (design §4.3 *The third adapter: Grok Build*, *`launch`*, TD-1836):
every launch runs with `HOME` a mirror of the person's home by links, but Claude Code's two user-level settings files;
an unattended launch under `permission_prompts: all` is refused where a Claude Code file the tool still reads (the
managed file, a project's) sets a mode or names a `HOME`, `GROK_*` or `XAI_*` key in its `env`; `ao doctor` notes
what no longer reaches a Grok session. The offline suite reads no developer's home: both names are patched."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shiftlead.adapters import grok
from shiftlead.adapters.grok import GrokAdapter
from shiftlead.adapters.grok import launch_home as lh


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A scratch ShiftLead home with Grok profiles under each `permission_prompts`, a binary, the person's home and
    the managed file patched into the case's directory, and a session directory outside any repo."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "sl"))
    (tmp_path / "sl").mkdir()
    g = tmp_path / "g"
    (tmp_path / "sl" / "profiles.yml").write_text(
        "default: skip\nprofiles:\n"
        f"  skip: {{adapter: grok, account: p, config_dir: {g}}}\n"
        f"  ask: {{adapter: grok, account: p, permission_prompts: ask, config_dir: {g}}}\n"
        f"  all: {{adapter: grok, account: p, permission_prompts: all, config_dir: {g}}}\n"
    )
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "grok").write_text("#!/bin/sh\n")
    person = tmp_path / "person"
    person.mkdir()
    monkeypatch.setattr(grok, "PERSON_HOME", person)
    monkeypatch.setattr(grok, "MANAGED_SETTINGS", tmp_path / "etc" / "managed-settings.json")
    (tmp_path / "work").mkdir()
    return tmp_path


def _ad(t: Path) -> GrokAdapter:
    return GrokAdapter(binary=str(t / "bin" / "grok"), hook_cmd="/venv/bin/shiftlead-hook")


def _launch(t: Path, profile: str, *, resume: str | None = None, unattended: bool = True, cwd: Path | None = None):
    return _ad(t).launch(profile=profile, resume=resume, prompt=None, unattended=unattended, cwd=cwd or t / "work")


def _write(p: Path, doc: object) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return p


def _person(home: Path) -> None:
    """A home with a file, a directory, a dangling link, `.grok`, and `.claude` holding both settings files."""
    (home / ".gitconfig").write_text("[user]\n")
    (home / ".ssh").mkdir()
    (home / ".gone").symlink_to(home / "nowhere")
    (home / ".grok").mkdir()
    (home / ".claude" / "skills").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("mine")
    _write(home / ".claude" / "settings.json", {"permissions": {"defaultMode": "auto", "allow": ["Bash(ls:*)"]}})
    _write(home / ".claude" / "settings.local.json", {"defaultMode": "auto"})


def _links(d: Path) -> dict[str, str]:
    return {n: os.readlink(d / n) for n in os.listdir(d) if os.path.islink(d / n)}


# -- the launch home -------------------------------------------------------------------------------


def test_every_entry_linked_at_both_levels_but_the_two_settings_files(tmp_path):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    _person(home)
    lh.refresh(home, out)
    assert _links(out) == {n: str(home / n) for n in (".gitconfig", ".ssh", ".gone")}  # absolute, unresolved
    assert not os.path.lexists(out / ".grok")  # the person's own Grok home is never linked
    assert (out / ".claude").is_dir() and not (out / ".claude").is_symlink()
    assert _links(out / ".claude") == {n: str(home / ".claude" / n) for n in ("skills", "CLAUDE.md")}
    assert sorted(os.listdir(out / ".claude")) == ["CLAUDE.md", "skills"]  # no settings file in any form
    assert (out / ".claude" / "CLAUDE.md").read_text() == "mine"  # read through the link
    assert os.path.islink(out / ".gone") and not (out / ".gone").exists()  # a dangling link mirrored


def test_a_link_pointing_elsewhere_is_replaced_and_a_refresh_follows_the_home(tmp_path):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    _person(home)
    lh.refresh(home, out)
    os.unlink(out / ".gitconfig")
    (out / ".gitconfig").symlink_to(tmp_path / "elsewhere")
    (home / ".netrc").write_text("x")
    (home / ".ssh").rmdir()
    (home / ".claude" / "skills").rmdir()
    (home / ".claude" / "agents").mkdir()
    lh.refresh(home, out)
    assert _links(out) == {n: str(home / n) for n in (".gitconfig", ".gone", ".netrc")}
    assert _links(out / ".claude") == {n: str(home / ".claude" / n) for n in ("agents", "CLAUDE.md")}


def test_a_shadow_is_moved_aside_twice_in_one_second_and_a_sessions_own_file_kept(tmp_path, monkeypatch):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    (home / ".bashrc").write_text("person")
    lh.refresh(home, out)
    monkeypatch.setattr(lh.time, "gmtime", lambda *a: (2026, 11, 14, 1, 2, 3, 4, 318, 0))
    for copy in ("first", "second"):
        os.unlink(out / ".bashrc")
        (out / ".bashrc").write_text(copy)  # a tool rewrote it by a rename
        lh.refresh(home, out)
    assert os.readlink(out / ".bashrc") == str(home / ".bashrc")
    assert (out / ".bashrc.shiftlead-shadow-20261114T010203Z").read_text() == "first"
    assert (out / ".bashrc.shiftlead-shadow-20261114T010203Z-1").read_text() == "second"
    (out / "notes.txt").write_text("a session's own")
    lh.refresh(home, out)
    assert (out / "notes.txt").read_text() == "a session's own"  # a non-link the home does not hold: left
    assert (out / ".bashrc.shiftlead-shadow-20261114T010203Z").exists()  # never deleted


def test_a_settings_file_and_a_settings_link_in_the_launch_homes_claude(tmp_path, monkeypatch):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    _person(home)
    lh.refresh(home, out)
    monkeypatch.setattr(lh.time, "gmtime", lambda *a: (2026, 11, 14, 1, 2, 3, 4, 318, 0))
    (out / ".claude" / "settings.json").symlink_to(home / ".claude" / "settings.json")
    (out / ".claude" / "settings.local.json").write_text('{"defaultMode": "auto"}')  # a session wrote one
    lh.refresh(home, out)
    names = sorted(os.listdir(out / ".claude"))
    assert names == ["CLAUDE.md", "settings.local.json.shiftlead-removed-20261114T010203Z", "skills"]


@pytest.mark.parametrize("kind", ["absent", "link", "file", "dangling"])
def test_the_persons_claude_absent_a_link_a_file_and_a_dangling_link(tmp_path, kind):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    real = tmp_path / "dotclaude"
    (real / "skills").mkdir(parents=True)
    _write(real / "settings.json", {"defaultMode": "auto"})
    if kind == "link":
        (home / ".claude").symlink_to(real)
    elif kind == "file":
        (home / ".claude").write_text("not a directory")
    elif kind == "dangling":
        (home / ".claude").symlink_to(tmp_path / "nowhere")
    lh.refresh(home, out)
    assert (out / ".claude").is_dir() and not (out / ".claude").is_symlink()
    want = {"skills": str(home / ".claude" / "skills")} if kind == "link" else {}  # listed through the link
    assert _links(out / ".claude") == want and set(os.listdir(out / ".claude")) == set(want)


def test_a_grok_in_the_launch_home_of_either_kind_is_left(tmp_path):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    (home / ".grok").mkdir()
    out.mkdir()
    (out / ".grok").symlink_to(tmp_path / "somewhere")
    lh.refresh(home, out)
    assert os.readlink(out / ".grok") == str(tmp_path / "somewhere")
    os.unlink(out / ".grok")
    (out / ".grok").mkdir()
    lh.refresh(home, out)
    assert (out / ".grok").is_dir() and not (out / ".grok").is_symlink()


@pytest.mark.parametrize("kind", ["link", "file"])
def test_a_link_or_a_file_in_place_of_claude(tmp_path, monkeypatch, kind):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    _person(home)
    out.mkdir()
    monkeypatch.setattr(lh.time, "gmtime", lambda *a: (2026, 11, 14, 1, 2, 3, 4, 318, 0))
    if kind == "link":
        (out / ".claude").symlink_to(home / ".claude")  # would hand the tool the person's settings
    else:
        (out / ".claude").write_text("x")
    lh.refresh(home, out)
    assert (out / ".claude").is_dir() and not (out / ".claude").is_symlink()
    assert not os.path.lexists(out / ".claude" / "settings.json")
    assert (home / ".claude" / "settings.json").exists()  # the person's own untouched
    aside = out / ".claude.shiftlead-shadow-20261114T010203Z"
    assert (aside.read_text() == "x") if kind == "file" else not os.path.lexists(aside)


def test_a_temporary_link_a_crash_left_and_one_found_existing(tmp_path):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    (home / ".profile").write_text("p")
    out.mkdir()
    crashed = out / f"{lh.TMP}1-.profile"
    crashed.symlink_to(home / ".profile")  # another pid's, left by a crash
    mine = out / f"{lh.TMP}{os.getpid()}-.profile"
    mine.symlink_to(tmp_path / "stale")  # this pid's own name, found existing
    lh.refresh(home, out)
    assert sorted(os.listdir(out)) == [".claude", ".profile"]
    assert os.readlink(out / ".profile") == str(home / ".profile")


def test_a_renames_enoent_reads_the_name_again(tmp_path, monkeypatch):
    """A concurrent refresh removes this one's temporary link (a link whose name the home does not hold): the rename
    fails `ENOENT`, and the step reads the name again and makes the link."""
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    (home / ".profile").write_text("p")
    real, seen = os.rename, []

    def rename(a, b):
        if not seen:
            seen.append(a)
            os.unlink(a)
        return real(a, b)

    monkeypatch.setattr(lh.os, "rename", rename)
    lh.refresh(home, out)
    assert seen and os.readlink(out / ".profile") == str(home / ".profile")


REFRESH_MANY = (
    "import sys; from pathlib import Path; from shiftlead.adapters.grok import launch_home as lh\n"
    "for _ in range(15): lh.refresh(Path(sys.argv[1]), Path(sys.argv[2]))"
)


def test_two_refreshes_at_once(tmp_path):
    home, out = tmp_path / "h", tmp_path / "lh"
    home.mkdir()
    _person(home)
    for i in range(20):
        (home / f".f{i}").write_text(str(i))
    procs = [
        subprocess.Popen([sys.executable, "-c", REFRESH_MANY, str(home), str(out)], stderr=subprocess.PIPE)
        for _ in range(3)
    ]
    assert [p.wait(60) for p in procs] == [0, 0, 0], [p.stderr.read() for p in procs]
    assert _links(out) == {n: str(home / n) for n in os.listdir(home) if n not in (".grok", ".claude")}
    assert sorted(os.listdir(out / ".claude")) == ["CLAUDE.md", "skills"]
    assert not [n for n in os.listdir(out) if n.startswith(lh.TMP) or "shiftlead-shadow" in n]


# -- the launch ------------------------------------------------------------------------------------


@pytest.mark.parametrize("resume", [None, "abc-123"])
def test_the_create_and_the_resume_carry_home_and_folder_trust(env, resume):
    _person(env / "person")
    spec = _launch(env, "skip", resume=resume)
    assert spec.env["HOME"] == str(env / "g" / "launch-home") and spec.env["GROK_FOLDER_TRUST"] == "0"
    assert os.readlink(env / "g" / "launch-home" / ".gitconfig") == str(env / "person" / ".gitconfig")
    assert not os.path.lexists(env / "g" / "launch-home" / ".claude" / "settings.json")


def test_a_launch_home_that_cannot_be_made_is_refused_in_its_words(env):
    (env / "g").mkdir()
    (env / "g" / "launch-home").write_text("a file where the directory goes")
    with pytest.raises(ValueError, match=r"^Grok's launch home .*/g/launch-home could not be made: "):
        _launch(env, "skip")


def test_stub_setup_patches_both_names_into_the_cases_directory(tmp_path, monkeypatch):
    from conformance._harness import HARNESSES

    HARNESSES["grok"].stub_setup(tmp_path, monkeypatch)
    assert grok.PERSON_HOME.is_relative_to(tmp_path) and grok.PERSON_HOME.is_dir()
    assert grok.MANAGED_SETTINGS.is_relative_to(tmp_path)
    assert not grok.PERSON_HOME.samefile(Path.home())


# -- the `all` refusal -----------------------------------------------------------------------------

MODE = "Grok would run all under {}'s defaultMode {}, not asking as permission_prompts: all says; use another profile or remove the mode"  # noqa: E501


def _cannot(path: Path) -> str:
    return rf"^Grok's permission mode under {path} cannot be read \(.+\), so all cannot keep permission_prompts: all$"


def _refused(env: Path, resume: str | None, cwd: Path | None = None) -> str:
    with pytest.raises(ValueError) as e:
        _launch(env, "all", resume=resume, cwd=cwd)
    return str(e.value)


RESUMES = pytest.mark.parametrize("resume", [None, "abc-123"])


@RESUMES
@pytest.mark.parametrize("mode", ["acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"])
def test_a_mode_in_the_sessions_own_file_refuses(env, resume, mode):
    f = _write(env / "work" / ".claude" / "settings.json", {"permissions": {"defaultMode": mode}})
    assert _refused(env, resume) == MODE.format(f, mode)


@RESUMES
@pytest.mark.parametrize("value", ["manual", 3, None, "Auto"])
def test_a_bad_value_and_manual_cannot_be_read(env, resume, value):
    f = _write(env / "work" / ".claude" / "settings.json", {"permissions": {"defaultMode": value}})
    assert pytest.raises(ValueError, _launch, env, "all", resume=resume).match(_cannot(f))


@RESUMES
@pytest.mark.parametrize("text", ["{not json", "[1]", '{"permissions": 1}', b"\xff\xfe"])
def test_an_unreadable_or_unparseable_file_refuses(env, resume, text):
    f = env / "work" / ".claude" / "settings.json"
    f.parent.mkdir(parents=True)
    f.write_bytes(text if isinstance(text, bytes) else text.encode())
    assert pytest.raises(ValueError, _launch, env, "all", resume=resume).match(_cannot(f))


@RESUMES
def test_a_file_that_cannot_be_opened_refuses(env, resume):
    (env / "work" / ".claude" / "settings.json").mkdir(parents=True)  # a directory: IsADirectoryError
    f = env / "work" / ".claude" / "settings.json"
    assert pytest.raises(ValueError, _launch, env, "all", resume=resume).match(_cannot(f))


@RESUMES
def test_the_managed_file_refuses_first(env, resume):
    managed = _write(grok.MANAGED_SETTINGS, {"permissions": {"defaultMode": "dontAsk"}})
    _write(env / "work" / ".claude" / "settings.json", {"defaultMode": "auto"})
    assert _refused(env, resume) == MODE.format(managed, "dontAsk")


@RESUMES
def test_a_parent_directorys_file_inside_the_repo_and_none_above_its_root(env, resume):
    repo = env / "outer" / "repo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    _write(env / "outer" / ".claude" / "settings.json", {"defaultMode": "auto"})  # above the root: not read
    _launch(env, "all", resume=resume, cwd=sub)
    f = _write(repo / "a" / ".claude" / "settings.json", {"defaultMode": "plan"})
    assert _refused(env, resume, sub) == MODE.format(f, "plan")


@RESUMES
def test_a_worktree_root_with_git_a_file_ends_the_walk(env, resume):
    wt = env / "main" / "wt"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /elsewhere\n")
    (env / "main" / ".git").mkdir()
    _write(env / "main" / ".claude" / "settings.json", {"defaultMode": "auto"})
    _launch(env, "all", resume=resume, cwd=wt)  # the main checkout's file is above the worktree's root


@RESUMES
def test_no_git_anywhere_reads_the_sessions_directory_alone(env, resume):
    sub = env / "work" / "sub"
    sub.mkdir()
    _write(env / "work" / ".claude" / "settings.json", {"defaultMode": "auto"})  # a non-repo parent: not read
    _launch(env, "all", resume=resume, cwd=sub)
    f = _write(sub / ".claude" / "settings.json", {"defaultMode": "auto"})
    assert _refused(env, resume, sub) == MODE.format(f, "auto")


@RESUMES
def test_the_session_directory_the_home_itself_reads_the_homes_files_as_a_projects(env, resume):
    f = _write(env / "person" / ".claude" / "settings.json", {"permissions": {"defaultMode": "auto"}})
    assert _refused(env, resume, env / "person") == MODE.format(f, "auto")


@RESUMES
def test_settings_local_first_and_a_top_level_key_alone(env, resume):
    d = env / "work" / ".claude"
    _write(d / "settings.json", {"permissions": {"defaultMode": "auto"}})
    local = _write(d / "settings.local.json", {"defaultMode": "plan"})  # top-level alone, read first
    assert _refused(env, resume) == MODE.format(local, "plan")


@RESUMES
def test_a_top_level_auto_beside_a_nested_default_refuses(env, resume):
    f = _write(
        env / "work" / ".claude" / "settings.json", {"defaultMode": "auto", "permissions": {"defaultMode": "default"}}
    )
    assert _refused(env, resume) == MODE.format(f, "auto")


@RESUMES
@pytest.mark.parametrize(
    "doc",
    [{"permissions": {"defaultMode": "default"}}, {"defaultMode": "default"}, {"permissions": {"allow": []}}, None],
)
def test_default_no_key_and_no_file_are_no_refusal(env, resume, doc):
    if doc is not None:
        _write(env / "work" / ".claude" / "settings.json", doc)
        _write(grok.MANAGED_SETTINGS, doc)
    spec = _launch(env, "all", resume=resume)
    assert spec.argv[-2:] == ["--permission-mode", "default"]


@RESUMES
def test_an_attended_launch_and_skip_and_ask_read_nothing(env, resume):
    _write(env / "work" / ".claude" / "settings.json", "{not json")
    _write(grok.MANAGED_SETTINGS, {"defaultMode": "auto", "env": {"HOME": "/x"}})
    _launch(env, "all", resume=resume, unattended=False)
    _launch(env, "skip", resume=resume)
    _launch(env, "ask", resume=resume)


# -- the `env` block: the file's wins over the launch's on 1.0.77 (TD-1836's probe) ------------------


@RESUMES
@pytest.mark.parametrize("key", ["HOME", "GROK_FOLDER_TRUST", "GROK_ANYTHING", "XAI_API_KEY"])
def test_an_env_key_refuses_under_all_and_is_accepted_under_skip_and_ask(env, resume, key):
    f = _write(env / "work" / ".claude" / "settings.json", {"env": {"PATH_EXTRA": "1", key: "x"}})
    assert _refused(env, resume) == MODE.replace("defaultMode {}", "env {}").format(f, key)
    _launch(env, "skip", resume=resume)
    _launch(env, "ask", resume=resume)


@RESUMES
def test_an_env_of_other_names_is_no_refusal_and_a_mode_is_read_first(env, resume):
    f = _write(env / "work" / ".claude" / "settings.json", {"env": {"CADENCE_ATTENTION_SCOPE": "x", "HOMEDIR": "y"}})
    _launch(env, "all", resume=resume)
    _write(f, {"env": {"HOME": "/x"}, "defaultMode": "plan"})
    assert _refused(env, resume) == MODE.format(f, "plan")


@RESUMES
def test_an_env_not_an_object_cannot_be_read(env, resume):
    f = _write(env / "work" / ".claude" / "settings.json", {"env": ["HOME=/x"]})
    assert pytest.raises(ValueError, _launch, env, "all", resume=resume).match(_cannot(f))


def test_the_managed_files_env_refuses(env):
    managed = _write(grok.MANAGED_SETTINGS, {"env": {"XAI_API_KEY": "k"}})
    assert "env XAI_API_KEY" in _refused(env, None) and str(managed) in _refused(env, None)


# -- ao doctor's notes ------------------------------------------------------------------------------


def _rows(env: Path) -> dict[str, dict]:
    return {r["profile"]: r for r in _ad(env).doctor_profiles()}


def test_doctor_notes_none_with_no_claude_settings(env, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_CODE_XAI_API_KEY", raising=False)
    assert not any("note" in r for r in _rows(env).values())


def test_doctor_notes_the_homes_rules_reach_no_profile_and_its_mode_none_under_ask(env, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_CODE_XAI_API_KEY", raising=False)
    s = _write(env / "person" / ".claude" / "settings.json", {"permissions": {"allow": ["Bash(ls:*)"]}})
    rows = _rows(env)
    for name in ("skip", "ask", "all"):
        assert f"permissions rules in {s} do not reach {name}" in rows[name]["note"]
        assert "defaultMode" not in rows[name]["note"]
    local = _write(env / "person" / ".claude" / "settings.local.json", {"defaultMode": "auto"})
    rows = _rows(env)
    assert f"the defaultMode in {local} does not reach ask" in rows["ask"]["note"]
    assert "the defaultMode in" not in rows["skip"]["note"] and "the defaultMode in" not in rows["all"]["note"]


@pytest.mark.parametrize(
    "doc,words",
    [
        ({"defaultMode": "auto"}, "defaultMode auto"),
        ({"defaultMode": "manual"}, "cannot be read"),
        ("{not json", "cannot be read"),
        ({"env": {"GROK_HOME": "/x"}}, "env GROK_HOME"),
    ],
)
def test_doctor_notes_a_managed_file_that_refuses_every_all_launch(env, monkeypatch, doc, words):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_CODE_XAI_API_KEY", raising=False)
    _write(grok.MANAGED_SETTINGS, doc)
    rows = _rows(env)
    assert "every unattended launch is refused" in rows["all"]["note"] and words in rows["all"]["note"]
    assert "note" not in rows["skip"] and "note" not in rows["ask"]
