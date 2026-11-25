"""TD-151 slice 1, design §4.2a *How a profile is billed*: `billing` and `prices` on a profile, checked
and never guessed, the label saying *metered*, and a metered profile never polled for a quota."""

from __future__ import annotations

import json
import unittest.mock as um

import pytest

from shiftlead import profiles
from shiftlead.adapters.claude_code import ClaudeCodeAdapter

pytestmark = pytest.mark.unit


def _load(tmp_path, body: str):
    f = tmp_path / "profiles.yml"
    f.write_text(body)
    return profiles.load(f)[0]


def test_billing_defaults_to_subscription_and_a_metered_profile_carries_its_prices(tmp_path):
    got = _load(
        tmp_path,
        "profiles:\n  paul: {account: paul}\n"
        "  api: {account: key, billing: metered, config_dir: /c/api, prices: {input: 3, output: 15, cache_read: 0.3}}\n"
        "  local: {billing: metered, config_dir: /c/local}\n",
    )
    assert got["paul"].billing == "subscription" and not got["paul"].metered and got["paul"].prices == {}
    assert got["api"].metered and got["api"].prices == {"input": 3.0, "output": 15.0, "cache_read": 0.3}
    assert got["api"].label == "claude-code · key · metered"
    assert got["local"].metered and got["local"].prices == {}  # a self-hosted model: tokens, no price


@pytest.mark.parametrize(
    "block, why",
    [
        ("{billing: prepaid}", "billing is subscription or metered"),
        ("{prices: {input: 3}}", "prices belongs to a metered profile"),
        ("{billing: metered, prices: [3]}", "prices is a mapping"),
        ("{billing: metered, prices: {tokens: 3}}", "prices.tokens is not a token kind"),
        ("{billing: metered, prices: {input: -1}}", "is a price per million tokens"),
        ("{billing: metered, prices: {input: yes}}", "is a price per million tokens"),
    ],
)
def test_a_wrong_billing_is_the_files_error_never_a_guess(tmp_path, block, why):
    with pytest.raises(ValueError, match=why):
        _load(tmp_path, f"profiles:\n  p: {block}\n")


def test_a_metered_profile_needs_a_config_dir_of_its_own(tmp_path):
    """The review of #674: its spend is read from every transcript in its directory, so the tool's
    default, or another account's directory, would bill someone else's turns to it."""
    with pytest.raises(ValueError, match="names no config_dir"):
        _load(tmp_path, "profiles:\n  api: {billing: metered}\n")
    with pytest.raises(ValueError, match="shares config_dir /c/x with paul, another account"):
        _load(
            tmp_path,
            "profiles:\n  paul: {account: paul, config_dir: /c/x}\n"
            "  api: {account: key, billing: metered, config_dir: /c/x}\n",
        )
    got = _load(
        tmp_path,
        "profiles:\n  a: {account: key, billing: metered, config_dir: /c/x}\n"
        "  b: {account: key, config_dir: /c/x, model: haiku}\n",
    )
    assert got["a"].metered  # two profiles of one account may share it


def test_a_metered_profile_is_never_polled_for_a_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "profiles.yml").write_text(
        "profiles:\n  api: {account: key, billing: metered, config_dir: /c/api}\n  paul: {account: paul}\n"
    )
    ad = ClaudeCodeAdapter()
    with um.patch.object(ClaudeCodeAdapter, "usage", side_effect=AssertionError("polled")) as polled:
        assert ad.usage_for("api") == {"reason": "metered"}
        polled.assert_not_called()
    with um.patch.object(ClaudeCodeAdapter, "usage", return_value=None):
        assert ad.usage_for("paul")["reason"] == "error"  # a subscription profile is polled as ever


# ── slice 2: the adapter's spend (design §4.3 *Spend per turn*) ─────────────────────────────────


def _entry(uid: str, mid: str, *, inp=10, out=5, cr=1000, cw=0, kind="assistant", model="claude-sonnet-5") -> str:
    usage = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw,
    }
    return json.dumps({"type": kind, "uuid": uid, "timestamp": f"2026-09-27T10:00:0{uid[-1]}Z",
                       "message": {"id": mid, "model": model, "usage": usage}}) + "\n"  # fmt: skip


@pytest.fixture
def metered(tmp_path, monkeypatch):
    home, cfg = tmp_path / "home", tmp_path / "claude-api"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (home / "profiles.yml").write_text(f"profiles:\n  api: {{account: key, billing: metered, config_dir: {cfg}}}\n")
    proj = cfg / "projects" / "-w-repo"
    proj.mkdir(parents=True)
    return proj


def test_spend_reads_every_transcript_past_its_cursor_one_turn_per_response(metered):
    main = metered / "s1.jsonl"
    sub = metered / "s1" / "subagents" / "agent-a.jsonl"
    sub.parent.mkdir(parents=True)
    # one response written as two content-block entries, a user line, and a second response
    main.write_text(_entry("u1", "m1") + _entry("u2", "m1") + '{"type": "user"}\n' + _entry("u3", "m2", cr=0, cw=200))
    sub.write_text(_entry("u4", "m3", model="claude-haiku-4-5"))
    got = ClaudeCodeAdapter().spend("api", {})
    assert got["reason"] == "ok"
    by = {t["id"]: t for t in got["turns"]}
    assert set(by) == {"u2", "u3", "u4"}  # m1 once, by its last entry; the subagent's turn billed too
    assert (by["u3"]["input"], by["u3"]["output"], by["u3"]["cache_read"], by["u3"]["cache_write"]) == (10, 5, 0, 200)
    assert by["u2"]["cost"] is None and by["u2"]["source"] == str(main) and by["u4"]["model"] == "claude-haiku-4-5"
    assert main.read_bytes()[by["u3"]["offset"] :].startswith(b'{"type": "assistant", "uuid": "u3"')
    assert got["cursors"] == {str(main): main.stat().st_size, str(sub): sub.stat().st_size}
    # nothing new: nothing counted, the cursors stand
    again = ClaudeCodeAdapter().spend("api", got["cursors"])
    assert again["turns"] == [] and again["cursors"] == got["cursors"]
    # a line still being written is left for the next read
    with main.open("a") as f:
        f.write(_entry("u5", "m4") + '{"type": "assistant", "uuid": "u6"')
    later = ClaudeCodeAdapter().spend("api", got["cursors"])
    assert [t["id"] for t in later["turns"]] == ["u5"] and later["cursors"][str(main)] < main.stat().st_size


def test_a_turn_says_whose_it_is_and_a_subscription_profile_is_read_too(tmp_path, monkeypatch):
    """§4.3 *Spend per turn* (TD-830): `conversation`, `cwd` and `subagent` on every turn — a subagent's
    transcript names its parent's conversation — a `<synthetic>` entry is no turn, and a subscription
    profile's transcripts are read as a metered one's are (the seat ledger asks)."""
    home, cfg = tmp_path / "home", tmp_path / "claude-sub"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (home / "profiles.yml").write_text(f"profiles:\n  sub: {{config_dir: {cfg}}}\n")
    proj = cfg / "projects" / "-w-repo"
    sub = proj / "s1" / "subagents" / "agent-a.jsonl"
    sub.parent.mkdir(parents=True)

    def at(uid: str, mid: str, cwd: str, **kw) -> str:
        d = json.loads(_entry(uid, mid, **kw))
        return json.dumps(d | {"cwd": cwd}) + "\n"

    (proj / "s1.jsonl").write_text(at("u1", "m1", "/w/repo") + at("u2", "m2", "/w/repo", model="<synthetic>"))
    sub.write_text(at("u3", "m3", "/w/repo/sub"))
    got = ClaudeCodeAdapter().spend("sub", {})
    by = {t["id"]: t for t in got["turns"]}
    assert got["reason"] == "ok" and set(by) == {"u1", "u3"}
    assert (by["u1"]["conversation"], by["u1"]["cwd"], by["u1"]["subagent"]) == ("s1", "/w/repo", False)
    assert (by["u3"]["conversation"], by["u3"]["cwd"], by["u3"]["subagent"]) == ("s1", "/w/repo/sub", True)


def test_a_cursor_past_the_end_is_a_rewrite_read_from_the_top(metered):
    main = metered / "s1.jsonl"
    main.write_text(_entry("u1", "m1"))
    got = ClaudeCodeAdapter().spend("api", {str(main): 10_000})
    assert [t["id"] for t in got["turns"]] == ["u1"] and got["cursors"][str(main)] == main.stat().st_size


def test_spend_says_why_when_it_cannot_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "profiles.yml").write_text(f"profiles:\n  api: {{billing: metered, config_dir: {tmp_path / 'none'}}}\n")
    ad = ClaudeCodeAdapter()
    assert ad.spend("nope", {"x": 3}) == {"turns": [], "cursors": {"x": 3}, "reason": "no_profile"}
    got = ad.spend("api", {"x": 3})
    assert got["turns"] == [] and got["cursors"] == {"x": 3} and got["reason"].startswith("no transcripts under ")


class _HomeWriter:
    """An adapter that writes into its tool home and reports no spend (Grok Build's shape, design §4.3)."""

    name = "homewriter"
    own_home = "~/.homewriter"


@pytest.fixture
def homewriter(monkeypatch):
    from sessionorc import adapters

    adapters.load_all()
    monkeypatch.setitem(adapters._REGISTRY, _HomeWriter.name, _HomeWriter())


@pytest.mark.parametrize(
    "body",
    [
        "profiles:\n  g: {adapter: homewriter}\n",  # unset
        "profiles:\n  g: {adapter: homewriter, config_dir: ~/.homewriter}\n",  # the tool's own home
        "profiles:\n  g: {adapter: homewriter, config_dir: ~/.homewriter/../.homewriter}\n",  # resolving to it
        "profiles:\n  g: {adapter: homewriter, account: a, config_dir: /c/g}\n  h: {account: b, config_dir: /c/g}\n",
    ],
)
def test_a_profile_of_an_adapter_writing_its_home_needs_a_config_dir_of_its_own(tmp_path, homewriter, body):
    """§4.2a, TD-1550: the load refuses it in words, naming no tool."""
    with pytest.raises(
        ValueError, match=r"profiles\.yml: g needs a config_dir of its own \(homewriter writes into it\)"
    ):
        _load(tmp_path, body)


def test_two_profiles_of_one_account_may_share_a_home_and_an_unregistered_adapter_is_checked_by_neither(
    tmp_path, homewriter
):
    got = _load(
        tmp_path,
        "profiles:\n  g: {adapter: homewriter, account: a, config_dir: /c/g}\n"
        "  h: {adapter: homewriter, account: a, config_dir: /c/g}\n"
        "  later: {adapter: notyet, billing: metered, config_dir: /c/later}\n"
        "  claude: {config_dir: /c/claude}\n",
    )
    assert sorted(got) == ["claude", "g", "h", "later"]


def test_a_metered_profile_of_an_adapter_with_no_spend_is_refused(tmp_path, homewriter):
    with pytest.raises(ValueError, match=r"profiles\.yml: g is metered, but homewriter reports no spend"):
        _load(tmp_path, "profiles:\n  g: {adapter: homewriter, billing: metered, config_dir: /c/g}\n")
    # Claude Code and Gemini CLI report spend: their metered profiles load as today
    got = _load(
        tmp_path,
        "profiles:\n  a: {billing: metered, config_dir: /c/a}\n"
        "  b: {adapter: gemini, billing: metered, config_dir: /c/b}\n",
    )
    assert got["a"].metered and got["b"].metered
    with pytest.raises(ValueError, match="s is metered, but shell reports no spend"):
        _load(tmp_path, "profiles:\n  s: {adapter: shell, billing: metered, config_dir: /c/s}\n")
    assert sorted(_load(tmp_path, "profiles:\n  odd: {adapter: [a]}\n")) == ["odd"]  # no adapter name: unread


# §4.9e *A record's profile* (TD-2068): on a switched host the reader answers from `logins.yml`
LOGINS = """logins:
  claude-code:grind:
    folder: /c/grind
    account: acct-1
    pin: sonnet
    extra_args: [--x]
    unattended_args: [--y]
    permission_wait: 90
  claude-code:api:
    folder: /c/api
    billing: metered
    prices: {input: 3, output: 15}
  claude-code:twin: {folder: /c/t1}
  gemini:twin: {folder: /c/t2}
accounts: {}
forgotten: {}
"""


def test_a_switched_host_answers_a_profile_by_a_logins_name(tmp_path):
    (tmp_path / "logins.yml").write_text(LOGINS)
    got = _load(tmp_path, "profiles:\n  grind: {account: old}\n  sh: {adapter: shell}\n")
    grind = got["grind"]
    assert (grind.adapter, grind.account, grind.model, str(grind.config_dir)) == (
        "claude-code",
        "acct-1",
        "sonnet",
        "/c/grind",
    )
    assert (grind.extra_args, grind.unattended_args, grind.permission_wait) == (["--x"], ["--y"], 90)
    assert "claude-code:grind" not in got, "each login once, under the name a launch writes"
    assert got["sh"].adapter == "shell", "a profile with no login of its name is answered as today"
    api = got["api"]
    assert api.metered and api.prices == {"input": 3.0, "output": 15.0} and api.account == "claude-code:api"
    assert "twin" not in got and got["gemini:twin"].adapter == "gemini", "a name two tools share is read by key"
    assert len([p for p in got.values() if p.adapter != "shell"]) == 4, "the profile named grind is the login"


def test_a_switched_host_with_no_profiles_file_answers_its_logins_and_the_default(tmp_path):
    (tmp_path / "logins.yml").write_text(LOGINS)
    got, default = profiles.load(tmp_path / "profiles.yml")
    assert default == "default" and got["grind"].account == "acct-1"
    assert profiles.account_of("grind", "claude-code", tmp_path / "profiles.yml") == "acct-1"
    assert profiles.account_of("grind", "gemini", tmp_path / "profiles.yml") is None


def test_a_host_not_switched_reads_no_logins(tmp_path):
    assert set(_load(tmp_path, "profiles:\n  grind: {account: old}\n")) == {"grind"}


def test_a_reader_of_the_profiles_file_itself_reads_no_logins(tmp_path):
    (tmp_path / "logins.yml").write_text(LOGINS)
    (tmp_path / "profiles.yml").write_text("profiles:\n  grind: {account: old}\n")
    got, _ = profiles.load(tmp_path / "profiles.yml", with_logins=False)
    assert set(got) == {"grind"} and got["grind"].account == "old"


def test_a_login_s_argument_list_that_is_not_a_list_is_none(tmp_path):
    (tmp_path / "logins.yml").write_text("logins:\n  claude-code:odd: {extra_args: 5, unattended_args: '--a --b'}\n")
    got = profiles.get("odd", tmp_path / "profiles.yml")
    assert got.extra_args == [] and got.unattended_args == []
