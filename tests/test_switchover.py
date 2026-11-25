"""The switch-over's check, its first slice: the logins a host's profiles make and the blockers to cure beforehand
(design §4.9e *The three commands*, §4.2b *What the switch-over makes*, TD-2071)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shiftlead import cli, switchover
from shiftlead.adapters import claude_code, gemini, grok
from shiftlead.profiles import Profile

SALT = b"s" * 32


class Fake:
    """An adapter's switch-over reads: its default home, its model table, and who each folder is signed in as."""

    def __init__(self, default: Path, signed: dict[Path, str] | None = None, table: dict[str, str] | None = None):
        self.default, self.signed, self.table = default, signed or {}, table or {"opus-4": "opus"}

    def default_home(self, _env: Any) -> Path:
        return self.default

    def model_family(self, model: str) -> str | None:
        return self.table.get(model)

    def identity(self, home: Path, _salt: bytes) -> dict | None:
        m = self.signed.get(Path(home).resolve())
        return {"match": m} if m else None


def run(tmp_path: Path, profs: list[Profile], **kw: Any) -> tuple[list[switchover.Login], list[switchover.Blocker]]:
    fakes = kw.pop("fakes", None) or {"claude-code": Fake(tmp_path / "default-claude")}

    def adapter_of(name: str) -> Any:
        return fakes[name]

    return switchover.host_logins("h", {p.name: p for p in profs}, env={}, salt=SALT, adapter_of=adapter_of, **kw)


def P(name: str, folder: Path | None = None, **kw: Any) -> Profile:  # noqa: N802 — a fixture's constructor
    return Profile(name=name, config_dir=folder, **kw)


def test_one_login_per_folder_named_for_its_first_profile(tmp_path):
    a = tmp_path / "a"
    made, blockers = run(tmp_path, [P("paul", a), P("grind", a, account="paul"), P("other", tmp_path / "b")])
    assert blockers == []
    assert [(m.name, m.profiles) for m in made] == [("paul", ["paul", "grind"]), ("other", ["other"])]


def test_a_shell_profile_and_an_unregistered_adapter_make_no_login(tmp_path):
    profs = [P("sh", adapter="shell"), P("x", tmp_path / "x", adapter="nope"), P("c", tmp_path / "c")]

    def adapter_of(name: str) -> Any:
        if name == "nope":
            raise KeyError(name)
        return Fake(tmp_path / "d")

    made, _ = switchover.host_logins("h", {p.name: p for p in profs}, env={}, salt=SALT, adapter_of=adapter_of)
    assert [m.name for m in made] == ["c"]


def test_the_default_home_is_the_folder_of_a_profile_with_no_config_dir(tmp_path):
    made, blockers = run(tmp_path, [P("paul")])
    assert made[0].folder == (tmp_path / "default-claude").resolve() and not blockers


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("billing", "metered"),
        ("extra_args", ["--x"]),
        ("unattended_args", ["--y"]),
        ("permission_wait", 9),
        ("prices", {"input": 1.0}),
    ],
)
def test_profiles_on_one_folder_that_disagree_on_a_setting_block(tmp_path, setting, value):
    a = tmp_path / "a"
    _, blockers = run(tmp_path, [P("paul", a), P("grind", a, account="paul", **{setting: value})])
    assert [b for b in blockers if setting in b.what and not b.day]


def test_permission_prompts_alone_is_no_disagreement(tmp_path):
    a = tmp_path / "a"
    _, blockers = run(tmp_path, [P("paul", a), P("ask", a, account="paul", permission_prompts="ask")])
    assert blockers == []


def test_two_keys_on_one_folder_block(tmp_path):
    a = tmp_path / "a"
    _, blockers = run(tmp_path, [P("paul", a), P("grind", a)])
    assert any("more than one key" in b.what and "account:" in b.cure for b in blockers)


def test_one_folder_reached_as_a_config_dir_and_as_the_default_blocks(tmp_path):
    d = tmp_path / "default-claude"
    _, blockers = run(tmp_path, [P("paul"), P("grind", d, account="paul")])
    assert any("both as a config_dir" in b.what for b in blockers)


def test_a_pin_only_where_every_profile_names_one_model(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    made, blockers = run(
        tmp_path,
        [
            P("p1", a, model="opus-4"),
            P("p2", a, account="p1", model="opus-4"),
            P("q1", b, model="opus-4"),
            P("q2", b, account="q1"),
        ],
    )
    assert [m.pin for m in made] == ["opus", None] and not blockers


def test_a_pin_the_table_cannot_map_blocks(tmp_path):
    _, blockers = run(tmp_path, [P("p", tmp_path / "a", model="mystery-9")])
    assert any("cannot map" in b.what and "mystery-9" in b.what for b in blockers)


def test_a_bad_name_and_two_names_of_one_fold_block(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    names = {f"claude-code:{switchover.shown(a.resolve())}": "bad name!"}
    _, blockers = run(tmp_path, [P("p", a), P("q", b)], names=names)
    assert any("not a login name" in x.what for x in blockers)
    names = {f"claude-code:{switchover.shown(b.resolve())}": "P"}
    _, blockers = run(tmp_path, [P("p", a), P("q", b)], names=names)
    assert any("one name of one tool" in x.what for x in blockers)


def test_two_keys_signed_in_as_one_account_block(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fakes = {"claude-code": Fake(tmp_path / "d", signed={a.resolve(): "m1", b.resolve(): "m1"})}
    _, blockers = run(tmp_path, [P("p", a), P("q", b)], fakes=fakes)
    assert any("signed in as one account" in x.what for x in blockers)


def test_one_key_whose_folders_read_two_accounts_blocks(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fakes = {"claude-code": Fake(tmp_path / "d", signed={a.resolve(): "m1", b.resolve(): "m2"})}
    _, blockers = run(tmp_path, [P("p", a), P("q", b, account="p")], fakes=fakes)
    assert any("signed in as 2 accounts" in x.what for x in blockers)


def test_one_account_on_two_tools_is_no_blocker(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fakes = {
        "claude-code": Fake(tmp_path / "d", signed={a.resolve(): "m1"}),
        "gemini": Fake(tmp_path / "e", signed={b.resolve(): "m1"}),
    }
    _, blockers = run(tmp_path, [P("p", a), P("q", b, adapter="gemini")], fakes=fakes)
    assert blockers == []


def test_each_adapter_maps_a_model_through_its_own_table():
    assert claude_code.ClaudeCodeAdapter().model_family("claude-opus-4-1") == claude_code.model_family(
        "claude-opus-4-1"
    )
    assert gemini.GeminiAdapter().model_family("gemini-3.5-flash-lite") == "flash-lite"
    assert grok.GrokAdapter().model_family("nothing-known") is None


def test_the_report_lists_logins_then_blockers(tmp_path):
    made, blockers = run(tmp_path, [P("p", tmp_path / "a", model="mystery-9")])
    lines = switchover.report("h", made, blockers)
    assert lines[0] == "h: logins the move would make" and lines[1].startswith("  claude-code:p  ")
    assert lines[2] == "blockers to cure beforehand" and "mystery-9" in lines[3]
    assert switchover.report("h", [], [])[-1] == "no blockers"


def test_check_exits_nonzero_while_a_blocker_to_cure_beforehand_stands(tmp_path, capsys, monkeypatch):
    from sessionorc import paths

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))  # never the suite's shared unit home
    home = paths.home()
    home.mkdir()
    a, b = tmp_path / "a", tmp_path / "b"
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {a}}}\n  q: {{config_dir: {a}}}\n")
    assert cli.main(["switch-over", "check"]) == 1
    assert "more than one key" in capsys.readouterr().out
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {a}}}\n  q: {{config_dir: {b}}}\n")
    assert cli.main(["switch-over", "check"]) == 0
    assert "no blockers" in capsys.readouterr().out


def test_a_profiles_file_that_does_not_parse_is_reported_not_raised(tmp_path, capsys, monkeypatch):
    from sessionorc import paths

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))  # never the suite's shared unit home: a later test reads it
    (paths.home() / "profiles.yml").write_text("profiles: [unclosed\n")
    assert cli.main(["switch-over", "check"]) == 1
    assert "cannot be read" in capsys.readouterr().err


def test_an_adapter_whose_home_raises_makes_no_login(tmp_path):
    class Broken(Fake):
        def default_home(self, _env: Any) -> Path:
            raise RuntimeError("no home")

    made, _ = run(tmp_path, [P("p"), P("q", tmp_path / "q")], fakes={"claude-code": Broken(tmp_path)})
    assert [m.name for m in made] == ["q"]


def test_a_folder_under_a_symlinked_home_is_shown_from_tilde(tmp_path, monkeypatch):
    real = tmp_path / "real"
    (real / ".claude").mkdir(parents=True)
    (tmp_path / "link").symlink_to(real)
    monkeypatch.setenv("HOME", str(tmp_path / "link"))
    assert switchover.shown((tmp_path / "link" / ".claude").resolve()) == "~/.claude"
